from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import ASSET_STATUS_LABELS, AssetStatus
from app.models import Asset, AssetCategory, AssetHistory, AssetModel
from app.schemas.asset import CategoryCreate, ModelCreate
from app.services.asset_catalog_service import CategoryService, ModelService
from app.services.asset_snapshot import asset_snapshot
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext

_IMPORTABLE_STATUSES = {
    AssetStatus.IN_STOCK,
    AssetStatus.IN_USE,
    AssetStatus.BORROWED,
    AssetStatus.IDLE,
    AssetStatus.REPAIRING,
    AssetStatus.PENDING_SCRAP,
    AssetStatus.SCRAPPED,
}
_REMARK_LIMIT = 255


@dataclass
class ImportIssue:
    row: int
    action: str
    asset_no: str | None = None
    record_id: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "action": self.action,
            "asset_no": self.asset_no,
            "record_id": self.record_id,
            "message": self.message,
        }


@dataclass
class ImportReport:
    total: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    categories_created: int = 0
    models_created: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    missing_categories: list[str] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "total": self.total,
            "created": self.created,
            "skipped": self.skipped,
            "failed": self.failed,
            "categories_created": self.categories_created,
            "models_created": self.models_created,
            "status_counts": self.status_counts,
            "missing_categories": self.missing_categories,
            "issues": [item.as_dict() for item in self.issues],
        }


class DingTalkImportService:
    """一次性历史数据导入：只写入 ITAM 侧，不触碰钉钉数据源。"""

    def __init__(self, session: AsyncSession, context: AuthContext) -> None:
        self.session = session
        self.context = context
        self.audit = AuditService(session)
        self._category_service = CategoryService(session)
        self._model_service = ModelService(session)

    async def run(
        self,
        payload: dict[str, Any],
        *,
        create_categories: bool,
        create_models: bool,
        dry_run: bool,
    ) -> ImportReport:
        report = ImportReport(dry_run=dry_run)
        assets = payload.get("assets") or []
        report.total = len(assets)

        categories = await self._ensure_categories(
            payload.get("categories") or [],
            report,
            create=create_categories and not dry_run,
            assume_create=create_categories and dry_run,
        )
        models = await self._ensure_models(
            payload.get("models") or [],
            categories,
            report,
            create=create_models and not dry_run,
        )
        await self._import_assets(
            assets,
            categories,
            models,
            payload.get("source") or {},
            report,
            dry_run=dry_run,
        )
        if not dry_run:
            await self.audit.record(
                action="asset.import.dingtalk.batch",
                module="资产台账",
                summary=(
                    f"钉钉 AI 表格历史资产导入：成功 {report.created} 条，"
                    f"跳过 {report.skipped} 条，失败 {report.failed} 条"
                ),
                actor=self.context.user,
                resource_type="asset_import",
                resource_id=payload.get("source", {}).get("table_id"),
                after={
                    "source": payload.get("source") or {},
                    "created": report.created,
                    "skipped": report.skipped,
                    "failed": report.failed,
                    "status_counts": report.status_counts,
                },
            )
            await self.session.commit()
        return report

    async def _ensure_categories(
        self,
        items: list[dict[str, Any]],
        report: ImportReport,
        *,
        create: bool,
        assume_create: bool = False,
    ) -> dict[str, AssetCategory]:
        rows = list(
            (await self.session.execute(select(AssetCategory))).scalars().all()
        )
        by_name = {item.name: item for item in rows}
        by_code = {item.code: item for item in rows}
        missing: list[str] = []
        for item in items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            if name in by_name:
                continue
            code = (item.get("code") or "").strip().upper()
            existing = by_code.get(code)
            if existing is not None:
                by_name[existing.name] = existing
                continue
            if not create:
                if assume_create:
                    by_name[name] = SimpleNamespace(id=0, name=name, code=code)
                    report.categories_created += 1
                else:
                    missing.append(name)
                continue
            category = await self._category_service.create(
                CategoryCreate(
                    name=name,
                    code=code,
                    category_type=item.get("category_type") or "HARDWARE",
                ),
                self.context,
            )
            loaded = await self.session.get(AssetCategory, category.id)
            if loaded is not None:
                by_name[loaded.name] = loaded
                by_code[loaded.code] = loaded
            report.categories_created += 1
        report.missing_categories = missing
        return by_name

    async def _ensure_models(
        self,
        items: list[dict[str, Any]],
        categories: dict[str, AssetCategory],
        report: ImportReport,
        *,
        create: bool,
    ) -> dict[str, AssetModel]:
        rows = list((await self.session.execute(select(AssetModel))).scalars().all())
        by_code = {item.code: item for item in rows}
        by_key: dict[str, AssetModel] = {}
        for item in items:
            key = item.get("key")
            name = (item.get("name") or "").strip()
            code = (item.get("code") or "").strip().upper()
            category = categories.get(item.get("category_name") or "")
            if not key or not name or not code or category is None:
                continue
            model = by_code.get(code)
            if model is None and create:
                created = await self._model_service.create(
                    ModelCreate(
                        category_id=category.id,
                        name=name,
                        code=code,
                        brand=item.get("brand"),
                        spec=item.get("spec"),
                    ),
                    self.context,
                )
                model = await self.session.get(AssetModel, created.id)
                if model is not None:
                    by_code[code] = model
                report.models_created += 1
            if model is not None:
                by_key[key] = model
        return by_key

    async def _import_assets(
        self,
        assets: list[dict[str, Any]],
        categories: dict[str, AssetCategory],
        models: dict[str, AssetModel],
        source: dict[str, Any],
        report: ImportReport,
        *,
        dry_run: bool,
    ) -> None:
        existing = set(
            (
                await self.session.execute(
                    select(Asset.asset_no).where(Asset.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        seen: set[str] = set()
        for row in assets:
            row_no = int(row.get("row") or 0)
            asset_no = (row.get("asset_no") or "").strip()
            name = (row.get("name") or "").strip()
            record_id = row.get("record_id")
            if not asset_no or not name:
                report.failed += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="failed",
                        asset_no=asset_no or None,
                        record_id=record_id,
                        message="资产编码或资产名称为空",
                    )
                )
                continue
            if asset_no in existing or asset_no in seen:
                report.skipped += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="skipped",
                        asset_no=asset_no,
                        record_id=record_id,
                        message="资产编码已存在，已跳过",
                    )
                )
                continue
            category = categories.get(row.get("category_name") or "")
            if category is None:
                report.failed += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="failed",
                        asset_no=asset_no,
                        record_id=record_id,
                        message=f"资产分类「{row.get('category_name')}」不存在",
                    )
                )
                continue
            status = row.get("status")
            if status not in _IMPORTABLE_STATUSES:
                report.failed += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="failed",
                        asset_no=asset_no,
                        record_id=record_id,
                        message=f"资产状态「{status}」不受支持",
                    )
                )
                continue
            try:
                purchase_date = self._parse_date(row.get("purchase_date"))
            except ValueError:
                report.failed += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="failed",
                        asset_no=asset_no,
                        record_id=record_id,
                        message=f"到货时间「{row.get('purchase_date')}」格式不正确",
                    )
                )
                continue
            model = models.get(row.get("model_key") or "")
            if model is not None and model.category_id != category.id:
                model = None
            if dry_run:
                seen.add(asset_no)
                report.created += 1
                report.status_counts[status] = report.status_counts.get(status, 0) + 1
                continue
            try:
                await self._create_asset(
                    row,
                    category,
                    model,
                    purchase_date,
                    source,
                )
            except Exception as exc:  # noqa: BLE001 - 逐行失败需继续导入
                await self.session.rollback()
                report.failed += 1
                report.issues.append(
                    ImportIssue(
                        row=row_no,
                        action="failed",
                        asset_no=asset_no,
                        record_id=record_id,
                        message=str(getattr(exc, "message", exc) or exc),
                    )
                )
                continue
            seen.add(asset_no)
            report.created += 1
            report.status_counts[status] = report.status_counts.get(status, 0) + 1

    async def _create_asset(
        self,
        row: dict[str, Any],
        category: AssetCategory,
        model: AssetModel | None,
        purchase_date: date | None,
        source: dict[str, Any],
    ) -> None:
        asset = Asset(
            asset_no=row["asset_no"].strip(),
            name=row["name"].strip(),
            category_id=category.id,
            category=category,
            model_id=model.id if model else None,
            model=model,
            purchase_date=purchase_date,
            status=row["status"],
            custom_fields={},
            remark=self._remark(row),
        )
        self.session.add(asset)
        await self.session.flush()
        snapshot = asset_snapshot(asset)
        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="IMPORT",
                action_label="历史数据导入",
                from_status=asset.status,
                to_status=asset.status,
                before_snapshot={},
                after_snapshot=snapshot,
                operator_id=self.context.user.id,
                operator_name=(
                    self.context.user.real_name or self.context.user.username
                ),
                summary=f"钉钉 AI 表格导入（来源记录 {row.get('record_id')}）",
            )
        )
        await self.audit.record(
            action="asset.import.dingtalk",
            module="资产台账",
            summary=f"导入资产：{asset.name}（{asset.asset_no}）",
            actor=self.context.user,
            resource_type="asset",
            resource_id=asset.id,
            after={
                "status": asset.status,
                "status_label": ASSET_STATUS_LABELS.get(asset.status, asset.status),
                "source": {
                    "base_id": source.get("base_id"),
                    "table_id": source.get("table_id"),
                    "record_id": row.get("record_id"),
                    "source_status": row.get("source_status"),
                },
            },
        )
        await self.session.commit()

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError(text) from exc

    @staticmethod
    def _remark(row: dict[str, Any]) -> str | None:
        parts = []
        remark = (row.get("remark") or "").strip()
        detail = (row.get("detail") or "").strip()
        if remark:
            parts.append(remark)
        if detail:
            parts.append(f"描述：{detail}")
        text = "；".join(parts)
        if len(text) > _REMARK_LIMIT:
            text = text[: _REMARK_LIMIT - 1] + "…"
        return text or None
