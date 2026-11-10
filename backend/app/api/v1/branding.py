from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_context, require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.settings import AnnouncementIn, BrandingUpdate
from app.services.branding_service import BrandingService
from app.services.permission_service import AuthContext

router = APIRouter(prefix="/branding", tags=["品牌与首页"])

IMAGE_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("", summary="公开品牌配置")
async def public_branding(session: AsyncSession = Depends(get_db)):
    result = await BrandingService(session).get_public()
    return ok(result.model_dump(mode="json"))


@router.get("/logo", summary="系统 Logo")
async def branding_logo(session: AsyncSession = Depends(get_db)):
    path, media_type = await BrandingService(session).get_image("logo")
    return FileResponse(path, media_type=media_type, headers=IMAGE_CACHE_HEADERS)


@router.get("/background", summary="登录背景图")
async def branding_background(session: AsyncSession = Depends(get_db)):
    path, media_type = await BrandingService(session).get_image("background")
    return FileResponse(path, media_type=media_type, headers=IMAGE_CACHE_HEADERS)


@router.get("/announcements", summary="当前生效公告")
async def active_announcements(
    context: AuthContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).active_announcements()
    return ok([item.model_dump(mode="json") for item in result])


@router.get("/admin", summary="品牌与首页配置")
async def admin_branding(
    context: AuthContext = Depends(require_perm("system:settings:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).get_admin()
    return ok(result.model_dump(mode="json"))


@router.put("/admin", summary="保存品牌与首页配置")
async def update_branding(
    payload: BrandingUpdate,
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).update(payload, context)
    return ok(result.model_dump(mode="json"), message="品牌配置已保存")


@router.post("/admin/images/{kind}", summary="上传 Logo 或登录背景图")
async def upload_branding_image(
    kind: str,
    file: UploadFile = File(...),
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).upload_image(kind, file, context)
    return ok(result.model_dump(mode="json"), message="图片已上传")


@router.delete("/admin/images/{kind}", summary="恢复默认 Logo 或背景图")
async def delete_branding_image(
    kind: str,
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).delete_image(kind, context)
    return ok(result.model_dump(mode="json"), message="已恢复默认")


@router.get("/admin/announcements", summary="公告列表")
async def list_announcements(
    context: AuthContext = Depends(require_perm("system:settings:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).list_announcements()
    return ok([item.model_dump(mode="json") for item in result])


@router.post("/admin/announcements", summary="新增公告")
async def create_announcement(
    payload: AnnouncementIn,
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).create_announcement(payload, context)
    return ok(result.model_dump(mode="json"), message="公告已发布")


@router.put("/admin/announcements/{announcement_id}", summary="更新公告")
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementIn,
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await BrandingService(session).update_announcement(
        announcement_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="公告已更新")


@router.delete("/admin/announcements/{announcement_id}", summary="删除公告")
async def delete_announcement(
    announcement_id: int,
    context: AuthContext = Depends(require_perm("system:settings:update")),
    session: AsyncSession = Depends(get_db),
):
    await BrandingService(session).delete_announcement(announcement_id, context)
    return ok(None, message="公告已删除")
