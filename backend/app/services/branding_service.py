from __future__ import annotations

import mimetypes
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.models import Announcement, SysSetting
from app.models.base import now_cst
from app.schemas.settings import (
    AnnouncementIn,
    AnnouncementOut,
    BrandingOut,
    BrandingUpdate,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.txn import commit_or_conflict

BRANDING_KEY = "branding"
BRANDING_DIR = "branding"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
UPLOAD_LIMITS = {"logo": 2 * 1024 * 1024, "background": 10 * 1024 * 1024}
CHUNK_SIZE = 64 * 1024
ANNOUNCEMENT_LEVELS = {"INFO": "通知", "IMPORTANT": "重要", "WARNING": "提醒"}

DEFAULT_BRANDING: dict = {
    "site_name": "ITAM",
    "site_subtitle": "IT ASSET CONTROL",
    "brand_mark_text": "IT",
    "logo_file": None,
    "background_file": None,
    "login_footer_text": "ITAM · IT 资产管理系统",
    "dashboard_welcome": "",
}


def _image_url(kind: str, stored_name: str | None) -> str:
    if not stored_name:
        return ""
    return f"{settings.API_V1_PREFIX}/branding/{kind}?v={Path(stored_name).stem}"


def _announcement_out(item: Announcement) -> AnnouncementOut:
    return AnnouncementOut(
        id=item.id,
        title=item.title,
        content=item.content,
        level=item.level,
        level_label=ANNOUNCEMENT_LEVELS.get(item.level, "通知"),
        is_active=item.is_active,
        start_at=item.start_at,
        end_at=item.end_at,
        sort=item.sort,
        created_by_name=item.created_by_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


class BrandingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _get_row(self) -> SysSetting | None:
        return await self.session.scalar(
            select(SysSetting).where(SysSetting.setting_key == BRANDING_KEY)
        )

    async def _load_values(self) -> dict:
        row = await self._get_row()
        stored = row.value if row is not None and isinstance(row.value, dict) else {}
        values = deepcopy(DEFAULT_BRANDING)
        for key in DEFAULT_BRANDING:
            if key in stored and stored[key] is not None:
                values[key] = stored[key]
        return values

    async def _admin_out(self) -> BrandingOut:
        row = await self._get_row()
        values = await self._load_values()
        return BrandingOut(
            site_name=values["site_name"],
            site_subtitle=values["site_subtitle"],
            brand_mark_text=values["brand_mark_text"],
            login_footer_text=values["login_footer_text"],
            dashboard_welcome=values["dashboard_welcome"],
            logo_url=_image_url("logo", values.get("logo_file")),
            background_url=_image_url("background", values.get("background_file")),
            updated_at=row.updated_at if row is not None else None,
        )

    async def get_public(self) -> BrandingOut:
        return await self._admin_out()

    async def get_admin(self) -> BrandingOut:
        return await self._admin_out()

    async def update(self, payload: BrandingUpdate, context: AuthContext) -> BrandingOut:
        values = await self._load_values()
        before = await self._admin_out()
        data = payload.model_dump()
        data["logo_file"] = values.get("logo_file")
        data["background_file"] = values.get("background_file")

        row = await self._get_row()
        if row is None:
            row = SysSetting(setting_key=BRANDING_KEY, value=data)
            self.session.add(row)
        else:
            row.value = data

        await self.audit.record(
            action="system.branding.update",
            module="系统设置",
            summary="更新登录封面与首页配置",
            actor=context.user,
            resource_type="settings",
            resource_id=BRANDING_KEY,
            before=before.model_dump(mode="json"),
            after=payload.model_dump(mode="json"),
        )
        await commit_or_conflict(self.session)
        return await self._admin_out()

    async def upload_image(
        self, kind: str, upload: UploadFile, context: AuthContext
    ) -> BrandingOut:
        if kind not in UPLOAD_LIMITS:
            raise BizError("不支持的图片类型")
        original_name = Path(upload.filename or "").name.strip()
        if not original_name:
            raise BizError("请选择要上传的图片")
        extension = Path(original_name).suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            raise BizError("仅支持 PNG、JPG、JPEG、WEBP 格式的图片")

        limit = UPLOAD_LIMITS[kind]
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise BizError(
                    f"{'Logo' if kind == 'logo' else '背景图'}不能超过"
                    f"{limit // 1024 // 1024}MB"
                )
            chunks.append(chunk)
        if size == 0:
            raise BizError("图片内容为空")

        stored_name = f"{kind}-{uuid4().hex}{extension}"
        directory = Path(settings.UPLOAD_DIR) / BRANDING_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / stored_name
        path.write_bytes(b"".join(chunks))

        values = await self._load_values()
        old_name = values.get(f"{kind}_file")
        values[f"{kind}_file"] = stored_name
        row = await self._get_row()
        if row is None:
            row = SysSetting(setting_key=BRANDING_KEY, value=values)
            self.session.add(row)
        else:
            row.value = values

        label = "Logo" if kind == "logo" else "登录背景图"
        await self.audit.record(
            action=f"system.branding.{kind}.upload",
            module="系统设置",
            summary=f"上传{label}：{original_name}",
            actor=context.user,
            resource_type="settings",
            resource_id=f"{BRANDING_KEY}.{kind}",
            after={"file_name": original_name, "file_size": size},
        )
        try:
            await commit_or_conflict(self.session)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if old_name and old_name != stored_name:
            (directory / old_name).unlink(missing_ok=True)
        return await self._admin_out()

    async def delete_image(self, kind: str, context: AuthContext) -> BrandingOut:
        if kind not in UPLOAD_LIMITS:
            raise BizError("不支持的图片类型")
        values = await self._load_values()
        old_name = values.get(f"{kind}_file")
        values[f"{kind}_file"] = None
        row = await self._get_row()
        if row is not None:
            row.value = values
        label = "Logo" if kind == "logo" else "登录背景图"
        await self.audit.record(
            action=f"system.branding.{kind}.delete",
            module="系统设置",
            summary=f"恢复默认{label}",
            actor=context.user,
            resource_type="settings",
            resource_id=f"{BRANDING_KEY}.{kind}",
        )
        await commit_or_conflict(self.session)
        if old_name:
            (Path(settings.UPLOAD_DIR) / BRANDING_DIR / old_name).unlink(missing_ok=True)
        return await self._admin_out()

    async def get_image(self, kind: str) -> tuple[Path, str]:
        if kind not in UPLOAD_LIMITS:
            raise NotFoundError("图片不存在")
        values = await self._load_values()
        stored_name = values.get(f"{kind}_file")
        if not stored_name:
            raise NotFoundError("尚未上传图片")
        path = Path(settings.UPLOAD_DIR) / BRANDING_DIR / stored_name
        if not path.is_file():
            raise NotFoundError("图片文件不存在")
        media_type = IMAGE_CONTENT_TYPES.get(
            Path(stored_name).suffix.lower(),
            mimetypes.guess_type(stored_name)[0] or "application/octet-stream",
        )
        return path, media_type

    async def active_announcements(self, limit: int = 10) -> list[AnnouncementOut]:
        now = now_cst()
        rows = (
            (
                await self.session.execute(
                    select(Announcement)
                    .where(Announcement.is_active.is_(True))
                    .order_by(Announcement.sort, Announcement.id.desc())
                )
            )
            .scalars()
            .all()
        )
        active = [
            item
            for item in rows
            if (item.start_at is None or item.start_at <= now)
            and (item.end_at is None or item.end_at >= now)
        ]
        return [_announcement_out(item) for item in active[:limit]]

    async def list_announcements(self) -> list[AnnouncementOut]:
        rows = (
            (
                await self.session.execute(
                    select(Announcement).order_by(
                        Announcement.sort, Announcement.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        return [_announcement_out(item) for item in rows]

    @staticmethod
    def _validate_window(start_at: datetime | None, end_at: datetime | None) -> None:
        if start_at is not None and end_at is not None and start_at > end_at:
            raise BizError("生效时间不能晚于失效时间")

    async def create_announcement(
        self, payload: AnnouncementIn, context: AuthContext
    ) -> AnnouncementOut:
        self._validate_window(payload.start_at, payload.end_at)
        item = Announcement(
            title=payload.title,
            content=payload.content,
            level=payload.level,
            is_active=payload.is_active,
            start_at=payload.start_at,
            end_at=payload.end_at,
            sort=payload.sort,
            created_by_id=context.user.id,
            created_by_name=context.user.real_name,
        )
        self.session.add(item)
        await self.session.flush()
        await self.audit.record(
            action="system.announcement.create",
            module="系统设置",
            summary=f"新增公告：{payload.title}",
            actor=context.user,
            resource_type="announcement",
            resource_id=item.id,
            after=payload.model_dump(mode="json"),
        )
        await commit_or_conflict(self.session)
        return _announcement_out(item)

    async def update_announcement(
        self, announcement_id: int, payload: AnnouncementIn, context: AuthContext
    ) -> AnnouncementOut:
        item = await self.session.get(Announcement, announcement_id)
        if item is None:
            raise NotFoundError("公告不存在或已被删除")
        self._validate_window(payload.start_at, payload.end_at)
        before = _announcement_out(item).model_dump(mode="json")
        item.title = payload.title
        item.content = payload.content
        item.level = payload.level
        item.is_active = payload.is_active
        item.start_at = payload.start_at
        item.end_at = payload.end_at
        item.sort = payload.sort
        await self.audit.record(
            action="system.announcement.update",
            module="系统设置",
            summary=f"更新公告：{payload.title}",
            actor=context.user,
            resource_type="announcement",
            resource_id=item.id,
            before=before,
            after=payload.model_dump(mode="json"),
        )
        await commit_or_conflict(self.session)
        return _announcement_out(item)

    async def delete_announcement(
        self, announcement_id: int, context: AuthContext
    ) -> None:
        item = await self.session.get(Announcement, announcement_id)
        if item is None:
            raise NotFoundError("公告不存在或已被删除")
        before = _announcement_out(item).model_dump(mode="json")
        await self.session.delete(item)
        await self.audit.record(
            action="system.announcement.delete",
            module="系统设置",
            summary=f"删除公告：{item.title}",
            actor=context.user,
            resource_type="announcement",
            resource_id=announcement_id,
            before=before,
        )
        await commit_or_conflict(self.session)
