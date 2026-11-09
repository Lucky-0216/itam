from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import ASSET_STATUS_LABELS, AssetStatus, CategoryType
from app.core.exceptions import BizError, NotFoundError
from app.core.permissions import DATA_SCOPE_LABELS
from app.core.report import COMPLIANCE_ISSUES, REPORT_EXPORT_LABELS, REPORT_TYPE_LABELS
from app.models import Asset, AssetCategory, AssetHistory, Dept
from app.models.base import now_cst
from app.schemas.report import (
    AssetReportOverviewOut,
    ComplianceAssetPage,
    ComplianceAssetRow,
    ComplianceIssueBrief,
    ComplianceIssueSummary,
    ComplianceSummaryOut,
    IdleAssetPage,
    IdleAssetRow,
    ReportAssetPage,
    ReportAssetRow,
    ReportCategoryOption,
    ReportCategorySlice,
    ReportDeptOption,
    ReportDeptSlice,
    ReportMetrics,
    ReportOptionsOut,
    ReportStatusSlice,
    ReportTrendPoint,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_scope_conditions,
    category_domain_allowed,
    is_self_only,
    scoped_dept_ids,
)

_TREND_MONTHS = 12
_EXPORT_ROW_LIMIT = 20000
_PDF_ROW_LIMIT = 1000
_SEVERITY_RANK = {"warning": 0, "info": 1}


@dataclass(slots=True)
class ReportFilters:
    keyword: str | None = None
    status: str | None = None
    category_id: int | None = None
    include_child: bool = True
    dept_id: int | None = None
    purchase_from: date | None = None
    purchase_to: date | None = None


@dataclass(slots=True)
class ReportExportResult:
    filename: str
    media_type: str
    content: bytes
    row_count: int


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_sequence(today: date, count: int) -> list[tuple[int, int]]:
    return [
        _shift_month(today.year, today.month, -offset)
        for offset in range(count - 1, -1, -1)
    ]


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _category_ids(
        self, context: AuthContext, category_id: int, include_child: bool
    ) -> list[int]:
        categories = list(
            (await self.session.execute(select(AssetCategory))).scalars().all()
        )
        selected = next(
            (item for item in categories if item.id == category_id),
            None,
        )
        if selected is None or not category_domain_allowed(
            selected, context, "report"
        ):
            raise NotFoundError("资产分类不存在")
        if not include_child:
            return [selected.id]
        return [
            item.id
            for item in categories
            if item.id == selected.id or item.path.startswith(selected.path)
        ]

    def _validate_filters(self, filters: ReportFilters) -> None:
        if filters.status and filters.status not in ASSET_STATUS_LABELS:
            raise BizError("资产状态取值不正确")
        if (
            filters.purchase_from
            and filters.purchase_to
            and filters.purchase_from > filters.purchase_to
        ):
            raise BizError("采购开始日期不能晚于结束日期")

    async def _conditions(
        self,
        context: AuthContext,
        filters: ReportFilters,
        *,
        apply_status: bool = True,
    ) -> list[Any]:
        self._validate_filters(filters)
        conditions = await asset_scope_conditions(
            self.session, context, resource="report"
        )
        if filters.keyword:
            like = f"%{filters.keyword.strip()}%"
            matchers = [Asset.asset_no.like(like)]
            # 不可见字段不能参与筛选，否则可用关键字逐位推断被遮蔽的内容。
            for field_name, column in (
                ("name", Asset.name),
                ("serial_no", Asset.serial_no),
                ("supplier", Asset.supplier),
                ("location", Asset.location),
            ):
                if context.can_view_field("asset", field_name):
                    matchers.append(column.like(like))
            conditions.append(or_(*matchers))
        if apply_status and filters.status:
            conditions.append(Asset.status == filters.status)
        if filters.category_id is not None:
            category_ids = await self._category_ids(
                context, filters.category_id, filters.include_child
            )
            conditions.append(Asset.category_id.in_(category_ids))
        if filters.dept_id is not None:
            conditions.append(Asset.dept_id == filters.dept_id)
        if filters.purchase_from is not None:
            conditions.append(Asset.purchase_date >= filters.purchase_from)
        if filters.purchase_to is not None:
            conditions.append(Asset.purchase_date <= filters.purchase_to)
        return conditions

    def _status_label(self, status: str) -> str:
        return ASSET_STATUS_LABELS.get(status, status)

    def _asset_row(self, asset: Asset, context: AuthContext) -> ReportAssetRow:
        def visible(field: str, value: Any) -> Any:
            return value if context.can_view_field("asset", field) else None

        custodian_name = asset.custodian.real_name if asset.custodian else None
        return ReportAssetRow(
            id=asset.id,
            asset_no=asset.asset_no,
            name=asset.name if context.can_view_field("asset", "name") else "已隐藏",
            category_name=asset.category.name if asset.category else None,
            model_name=asset.model.name if asset.model else None,
            serial_no=visible("serial_no", asset.serial_no),
            dept_name=asset.dept.name if asset.dept else None,
            custodian_name=visible("custodian_id", custodian_name),
            status=asset.status,
            status_label=self._status_label(asset.status),
            purchase_date=visible("purchase_date", asset.purchase_date),
            purchase_price=visible(
                "purchase_price",
                float(asset.purchase_price)
                if asset.purchase_price is not None
                else None,
            ),
            warranty_end=visible("warranty_end", asset.warranty_end),
            location=visible("location", asset.location),
            supplier=visible("supplier", asset.supplier),
        )

    async def overview(
        self, context: AuthContext, filters: ReportFilters
    ) -> AssetReportOverviewOut:
        conditions = await self._conditions(context, filters)
        today = now_cst().date()
        price_visible = context.can_view_field("asset", "purchase_price")

        status_rows = (
            await self.session.execute(
                select(
                    Asset.status,
                    func.count(Asset.id),
                    func.coalesce(func.sum(Asset.purchase_price), 0),
                )
                .where(*conditions)
                .group_by(Asset.status)
            )
        ).all()
        status_counts: dict[str, int] = {status: 0 for status in ASSET_STATUS_LABELS}
        status_values: dict[str, float] = {status: 0.0 for status in ASSET_STATUS_LABELS}
        for status, count, value in status_rows:
            status_counts[str(status)] = int(count)
            status_values[str(status)] = float(value or 0) if price_visible else 0.0

        total_count = sum(status_counts.values())
        total_value = round(sum(status_values.values()), 2)
        avg_value = round(total_value / total_count, 2) if total_count else 0.0

        warranty_30d = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(
                    *conditions,
                    Asset.warranty_end.is_not(None),
                    Asset.warranty_end >= today,
                    Asset.warranty_end <= today + timedelta(days=30),
                    Asset.status != AssetStatus.SCRAPPED,
                )
            )
            or 0
        )
        warranty_expired = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(
                    *conditions,
                    Asset.warranty_end.is_not(None),
                    Asset.warranty_end < today,
                    Asset.status != AssetStatus.SCRAPPED,
                )
            )
            or 0
        )
        compliance_asset_count = int(
            await self.session.scalar(
                select(func.count(func.distinct(Asset.id))).where(
                    *conditions,
                    or_(*self._issue_conditions(today)),
                )
            )
            or 0
        )

        status_distribution = [
            ReportStatusSlice(
                status=status,
                label=label,
                count=status_counts.get(status, 0),
                value=round(status_values.get(status, 0.0), 2),
            )
            for status, label in ASSET_STATUS_LABELS.items()
        ]
        for status in sorted(set(status_counts) - set(ASSET_STATUS_LABELS)):
            status_distribution.append(
                ReportStatusSlice(
                    status=status,
                    label=status,
                    count=status_counts[status],
                    value=round(status_values.get(status, 0.0), 2),
                )
            )

        dept_distribution = await self._dept_distribution(conditions, price_visible)
        category_distribution = await self._category_distribution(
            conditions, price_visible
        )
        purchase_trend = await self._purchase_trend(
            conditions, today, price_visible
        )

        return AssetReportOverviewOut(
            metrics=ReportMetrics(
                total_count=total_count,
                total_value=total_value,
                avg_value=avg_value,
                in_use_count=status_counts.get(AssetStatus.IN_USE, 0),
                in_stock_count=status_counts.get(AssetStatus.IN_STOCK, 0),
                idle_count=status_counts.get(AssetStatus.IDLE, 0),
                idle_value=round(status_values.get(AssetStatus.IDLE, 0.0), 2),
                repairing_count=status_counts.get(AssetStatus.REPAIRING, 0),
                pending_scrap_count=status_counts.get(AssetStatus.PENDING_SCRAP, 0),
                scrapped_count=status_counts.get(AssetStatus.SCRAPPED, 0),
                warranty_expiring_30d=warranty_30d,
                warranty_expired=warranty_expired,
                compliance_asset_count=compliance_asset_count,
            ),
            status_distribution=status_distribution,
            dept_distribution=dept_distribution,
            category_distribution=category_distribution,
            purchase_trend=purchase_trend,
            data_scope_label=DATA_SCOPE_LABELS.get(
                context.effective_scope("report"), context.data_scope
            ),
            generated_at=now_cst(),
        )

    async def _dept_distribution(
        self, conditions: list[Any], price_visible: bool = True
    ) -> list[ReportDeptSlice]:
        rows = (
            await self.session.execute(
                select(
                    Asset.dept_id,
                    Dept.name,
                    func.count(Asset.id),
                    func.coalesce(func.sum(Asset.purchase_price), 0),
                )
                .outerjoin(Dept, Asset.dept_id == Dept.id)
                .where(*conditions)
                .group_by(Asset.dept_id, Dept.name)
                .order_by(
                    func.coalesce(func.sum(Asset.purchase_price), 0).desc(),
                    func.count(Asset.id).desc(),
                )
            )
        ).all()
        return [
            ReportDeptSlice(
                dept_id=int(dept_id) if dept_id is not None else None,
                name=name or "未分配部门",
                count=int(count),
                value=round(float(value or 0), 2) if price_visible else 0.0,
            )
            for dept_id, name, count, value in rows
        ]

    async def _category_distribution(
        self, conditions: list[Any], price_visible: bool = True
    ) -> list[ReportCategorySlice]:
        rows = (
            await self.session.execute(
                select(
                    Asset.category_id,
                    AssetCategory.name,
                    func.count(Asset.id),
                    func.coalesce(func.sum(Asset.purchase_price), 0),
                )
                .join(AssetCategory, Asset.category_id == AssetCategory.id)
                .where(*conditions)
                .group_by(Asset.category_id, AssetCategory.name)
                .order_by(
                    func.coalesce(func.sum(Asset.purchase_price), 0).desc(),
                    func.count(Asset.id).desc(),
                )
            )
        ).all()
        return [
            ReportCategorySlice(
                category_id=int(category_id),
                name=name,
                count=int(count),
                value=round(float(value or 0), 2) if price_visible else 0.0,
            )
            for category_id, name, count, value in rows
        ]

    async def _purchase_trend(
        self, conditions: list[Any], today: date, price_visible: bool = True
    ) -> list[ReportTrendPoint]:
        months = _month_sequence(today, _TREND_MONTHS)
        start_date = date(months[0][0], months[0][1], 1)
        rows = (
            await self.session.execute(
                select(Asset.purchase_date, Asset.purchase_price).where(
                    *conditions,
                    Asset.purchase_date.is_not(None),
                    Asset.purchase_date >= start_date,
                )
            )
        ).all()
        counts: dict[tuple[int, int], int] = {}
        values: dict[tuple[int, int], float] = {}
        for purchase_date, price in rows:
            key = (purchase_date.year, purchase_date.month)
            counts[key] = counts.get(key, 0) + 1
            values[key] = values.get(key, 0.0) + float(price or 0)
        return [
            ReportTrendPoint(
                month=f"{year:04d}-{month:02d}",
                count=counts.get((year, month), 0),
                value=round(values.get((year, month), 0.0), 2)
                if price_visible
                else 0.0,
            )
            for year, month in months
        ]

    async def assets_page(
        self,
        context: AuthContext,
        filters: ReportFilters,
        *,
        page: int,
        page_size: int,
    ) -> ReportAssetPage:
        conditions = await self._conditions(context, filters)
        total = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return ReportAssetPage(
            items=[self._asset_row(asset, context) for asset in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _asset_rows(
        self, context: AuthContext, conditions: list[Any]
    ) -> list[ReportAssetRow]:
        rows = (
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.id.desc())
                    .limit(_EXPORT_ROW_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return [self._asset_row(asset, context) for asset in rows]

    def _idle_since_subquery(self):
        return (
            select(
                AssetHistory.asset_id.label("asset_id"),
                func.max(AssetHistory.created_at).label("idle_since"),
            )
            .where(AssetHistory.to_status == AssetStatus.IDLE)
            .group_by(AssetHistory.asset_id)
            .subquery()
        )

    async def idle_page(
        self,
        context: AuthContext,
        filters: ReportFilters,
        *,
        page: int,
        page_size: int,
    ) -> IdleAssetPage:
        conditions = await self._conditions(context, filters, apply_status=False)
        conditions.append(Asset.status == AssetStatus.IDLE)
        idle_subq = self._idle_since_subquery()

        total = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(*conditions)
            )
            or 0
        )
        rows = (
            await self.session.execute(
                select(Asset, idle_subq.c.idle_since)
                .outerjoin(idle_subq, idle_subq.c.asset_id == Asset.id)
                .where(*conditions)
                .order_by(
                    func.coalesce(idle_subq.c.idle_since, Asset.updated_at).asc(),
                    Asset.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        now = now_cst()
        items = []
        for asset, idle_since in rows:
            since = idle_since or asset.updated_at
            items.append(
                IdleAssetRow(
                    **self._asset_row(asset, context).model_dump(),
                    idle_since=since,
                    idle_days=max((now - since).days, 0),
                )
            )
        return IdleAssetPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _idle_rows(
        self, context: AuthContext, conditions: list[Any]
    ) -> list[IdleAssetRow]:
        idle_subq = self._idle_since_subquery()
        rows = (
            await self.session.execute(
                select(Asset, idle_subq.c.idle_since)
                .outerjoin(idle_subq, idle_subq.c.asset_id == Asset.id)
                .where(*conditions)
                .order_by(
                    func.coalesce(idle_subq.c.idle_since, Asset.updated_at).asc(),
                    Asset.id.asc(),
                )
                .limit(_EXPORT_ROW_LIMIT)
            )
        ).all()
        now = now_cst()
        return [
            IdleAssetRow(
                **self._asset_row(asset, context).model_dump(),
                idle_since=idle_since or asset.updated_at,
                idle_days=max((now - (idle_since or asset.updated_at)).days, 0),
            )
            for asset, idle_since in rows
        ]

    def _issue_conditions(self, today: date) -> list[Any]:
        active = Asset.status != AssetStatus.SCRAPPED
        hardware_category_ids = select(AssetCategory.id).where(
            AssetCategory.category_type == CategoryType.HARDWARE
        )
        missing_text = lambda column: or_(column.is_(None), column == "")  # noqa: E731
        return [
            # MISSING_CUSTODIAN
            (Asset.status.in_([AssetStatus.IN_USE, AssetStatus.BORROWED]))
            & Asset.custodian_id.is_(None),
            # MISSING_LOCATION
            active & missing_text(Asset.location),
            # MISSING_PRICE
            active & Asset.purchase_price.is_(None),
            # MISSING_PURCHASE_DATE
            active & Asset.purchase_date.is_(None),
            # MISSING_SERIAL
            active
            & Asset.category_id.in_(hardware_category_ids)
            & missing_text(Asset.serial_no),
            # EXPIRED_WARRANTY
            Asset.warranty_end.is_not(None)
            & (Asset.warranty_end < today)
            & Asset.status.in_(
                [
                    AssetStatus.IN_USE,
                    AssetStatus.BORROWED,
                    AssetStatus.IDLE,
                    AssetStatus.REPAIRING,
                ]
            ),
            # MISSING_DEPT
            active & Asset.dept_id.is_(None),
        ]

    def _asset_issue_codes(self, asset: Asset, today: date) -> list[str]:
        codes: list[str] = []
        if (
            asset.status in (AssetStatus.IN_USE, AssetStatus.BORROWED)
            and asset.custodian_id is None
        ):
            codes.append("MISSING_CUSTODIAN")
        if asset.status != AssetStatus.SCRAPPED and not (asset.location or "").strip():
            codes.append("MISSING_LOCATION")
        if asset.status != AssetStatus.SCRAPPED and asset.purchase_price is None:
            codes.append("MISSING_PRICE")
        if asset.status != AssetStatus.SCRAPPED and asset.purchase_date is None:
            codes.append("MISSING_PURCHASE_DATE")
        if (
            asset.status != AssetStatus.SCRAPPED
            and asset.category is not None
            and asset.category.category_type == CategoryType.HARDWARE
            and not (asset.serial_no or "").strip()
        ):
            codes.append("MISSING_SERIAL")
        if (
            asset.warranty_end is not None
            and asset.warranty_end < today
            and asset.status
            in (
                AssetStatus.IN_USE,
                AssetStatus.BORROWED,
                AssetStatus.IDLE,
                AssetStatus.REPAIRING,
            )
        ):
            codes.append("EXPIRED_WARRANTY")
        if asset.status != AssetStatus.SCRAPPED and asset.dept_id is None:
            codes.append("MISSING_DEPT")
        return codes

    async def compliance_summary(
        self, context: AuthContext, filters: ReportFilters
    ) -> ComplianceSummaryOut:
        conditions = await self._conditions(context, filters)
        today = now_cst().date()
        issue_conditions = self._issue_conditions(today)
        items = []
        for code, condition in zip(COMPLIANCE_ISSUES, issue_conditions):
            count = int(
                await self.session.scalar(
                    select(func.count(Asset.id)).where(*conditions, condition)
                )
                or 0
            )
            meta = COMPLIANCE_ISSUES[code]
            items.append(
                ComplianceIssueSummary(
                    issue_type=code,
                    label=meta["label"],
                    severity=meta["severity"],
                    count=count,
                    suggestion=meta["suggestion"],
                )
            )
        asset_count = int(
            await self.session.scalar(
                select(func.count(func.distinct(Asset.id))).where(
                    *conditions,
                    or_(*issue_conditions),
                )
            )
            or 0
        )
        return ComplianceSummaryOut(
            items=items,
            asset_count=asset_count,
            generated_at=now_cst(),
        )

    async def _compliance_assets(
        self,
        context: AuthContext,
        conditions: list[Any],
        *,
        issue_type: str | None,
    ) -> list[ComplianceAssetRow]:
        today = now_cst().date()
        issue_conditions = self._issue_conditions(today)
        if issue_type:
            if issue_type not in COMPLIANCE_ISSUES:
                raise BizError("合规检查项取值不正确")
            issue_codes = list(COMPLIANCE_ISSUES)
            conditions = [
                *conditions,
                issue_conditions[issue_codes.index(issue_type)],
            ]
        else:
            conditions = [*conditions, or_(*issue_conditions)]
        assets = (
            (
                await self.session.execute(
                    select(Asset).where(*conditions).limit(_EXPORT_ROW_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        rows = []
        for asset in assets:
            codes = self._asset_issue_codes(asset, today)
            if issue_type:
                if issue_type not in codes:
                    continue
                codes = [issue_type]
            issues = [
                ComplianceIssueBrief(
                    issue_type=code,
                    label=COMPLIANCE_ISSUES[code]["label"],
                    severity=COMPLIANCE_ISSUES[code]["severity"],
                )
                for code in codes
            ]
            rows.append(
                ComplianceAssetRow(
                    **self._asset_row(asset, context).model_dump(),
                    issues=issues,
                )
            )
        rows.sort(
            key=lambda row: (
                min(
                    (_SEVERITY_RANK[item.severity] for item in row.issues),
                    default=9,
                ),
                row.asset_no,
            )
        )
        return rows

    async def compliance_page(
        self,
        context: AuthContext,
        filters: ReportFilters,
        *,
        issue_type: str | None,
        page: int,
        page_size: int,
    ) -> ComplianceAssetPage:
        conditions = await self._conditions(context, filters)
        rows = await self._compliance_assets(
            context, conditions, issue_type=issue_type
        )
        start = (page - 1) * page_size
        return ComplianceAssetPage(
            items=rows[start : start + page_size],
            total=len(rows),
            page=page,
            page_size=page_size,
        )

    async def options(self, context: AuthContext) -> ReportOptionsOut:
        dept_stmt = select(Dept).where(Dept.status == 1)
        allowed = await scoped_dept_ids(self.session, context, resource="report")
        if allowed is not None:
            dept_stmt = dept_stmt.where(
                Dept.id.in_(allowed) if allowed else Dept.id.in_([-1])
            )
        depts = (
            (
                await self.session.execute(
                    dept_stmt.order_by(Dept.path, Dept.sort, Dept.id)
                )
            )
            .scalars()
            .all()
        )
        category_stmt = select(AssetCategory)
        domains = context.allowed_domains("report")
        if domains is not None:
            category_stmt = category_stmt.where(
                AssetCategory.asset_domain.in_(domains)
            )
        categories = (
            (
                await self.session.execute(
                    category_stmt.order_by(
                        AssetCategory.path, AssetCategory.sort, AssetCategory.id
                    )
                )
            )
            .scalars()
            .all()
        )
        return ReportOptionsOut(
            departments=[
                ReportDeptOption(
                    id=dept.id,
                    parent_id=dept.parent_id,
                    name=dept.name,
                    level=dept.level,
                    path=dept.path,
                )
                for dept in depts
            ],
            categories=[
                ReportCategoryOption(
                    id=category.id,
                    parent_id=category.parent_id,
                    name=category.name,
                    level=category.level,
                    path=category.path,
                    category_type=category.category_type,
                    status=category.status,
                )
                for category in categories
            ],
        )

    async def _filter_description(
        self, context: AuthContext, filters: ReportFilters
    ) -> str:
        allowed = await scoped_dept_ids(self.session, context, resource="report")
        parts = []
        if filters.keyword:
            parts.append(f"关键字：{filters.keyword.strip()}")
        if filters.status:
            parts.append(f"状态：{self._status_label(filters.status)}")
        if filters.category_id is not None:
            category = (
                await self.session.execute(
                    select(AssetCategory).where(AssetCategory.id == filters.category_id)
                )
            ).scalar_one_or_none()
            if category is not None and category_domain_allowed(
                category, context, "report"
            ):
                suffix = "（含下级）" if filters.include_child else ""
                parts.append(f"分类：{category.name}{suffix}")
        if filters.dept_id is not None:
            dept = (
                await self.session.execute(
                    select(Dept).where(Dept.id == filters.dept_id)
                )
            ).scalar_one_or_none()
            if dept is not None and (allowed is None or dept.id in allowed):
                parts.append(f"部门：{dept.name}")
        if filters.purchase_from or filters.purchase_to:
            start = filters.purchase_from.isoformat() if filters.purchase_from else "不限"
            end = filters.purchase_to.isoformat() if filters.purchase_to else "不限"
            parts.append(f"采购日期：{start} 至 {end}")
        if allowed is not None:
            parts.append("数据范围：当前角色可见范围")
        return "；".join(parts) or "全部资产"

    async def export(
        self,
        context: AuthContext,
        filters: ReportFilters,
        *,
        report_type: str,
        export_format: str,
        issue_type: str | None = None,
    ) -> ReportExportResult:
        if report_type not in REPORT_TYPE_LABELS:
            raise BizError("报表类型取值不正确")
        if export_format not in REPORT_EXPORT_LABELS:
            raise BizError("导出格式取值不正确")
        if issue_type and issue_type not in COMPLIANCE_ISSUES:
            raise BizError("合规检查项取值不正确")

        self._validate_filters(filters)
        conditions = await self._conditions(context, filters)
        today = now_cst().date()
        filter_text = await self._filter_description(context, filters)
        report_scope = context.effective_scope("report")
        data_scope = DATA_SCOPE_LABELS.get(report_scope, report_scope)
        generated_at = now_cst()
        overview = None
        rows: list[Any] = []
        compliance_items: list[ComplianceIssueSummary] = []
        summary_asset_count = 0

        if report_type == "OVERVIEW":
            overview = await self.overview(context, filters)
        elif report_type == "ASSETS":
            rows = await self._asset_rows(context, conditions)
        elif report_type == "IDLE":
            idle_conditions = await self._conditions(
                context, filters, apply_status=False
            )
            idle_conditions.append(Asset.status == AssetStatus.IDLE)
            rows = await self._idle_rows(context, idle_conditions)
        else:
            compliance_conditions = await self._conditions(context, filters)
            rows = await self._compliance_assets(
                context, compliance_conditions, issue_type=issue_type
            )
            summary = await self.compliance_summary(context, filters)
            compliance_items = summary.items
            summary_asset_count = summary.asset_count

        from app.services import report_export

        if export_format == "XLSX":
            content = report_export.build_xlsx(
                report_type=report_type,
                title=REPORT_TYPE_LABELS[report_type],
                filter_text=filter_text,
                data_scope=data_scope,
                generated_at=generated_at,
                overview=overview,
                rows=rows,
                compliance_items=compliance_items,
                summary_asset_count=summary_asset_count,
                today=today,
            )
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            suffix = "xlsx"
            row_count = (
                overview.metrics.total_count if overview else len(rows)
            )
        else:
            content = report_export.build_pdf(
                report_type=report_type,
                title=REPORT_TYPE_LABELS[report_type],
                filter_text=filter_text,
                data_scope=data_scope,
                generated_at=generated_at,
                overview=overview,
                rows=rows,
                compliance_items=compliance_items,
                summary_asset_count=summary_asset_count,
                today=today,
                row_limit=_PDF_ROW_LIMIT,
            )
            media_type = "application/pdf"
            suffix = "pdf"
            row_count = (
                overview.metrics.total_count if overview else len(rows)
            )

        audit = AuditService(self.session)
        await audit.record(
            action="asset.report.export",
            module="asset_report",
            summary=(
                f"导出{REPORT_TYPE_LABELS[report_type]}（"
                f"{REPORT_EXPORT_LABELS[export_format]}，{row_count} 条）"
            ),
            actor=context.user,
            resource_type="asset_report",
            resource_id=report_type,
            after={
                "report_type": report_type,
                "format": export_format,
                "issue_type": issue_type,
                "filters": {
                    "keyword": filters.keyword,
                    "status": filters.status,
                    "category_id": filters.category_id,
                    "include_child": filters.include_child,
                    "dept_id": filters.dept_id,
                    "purchase_from": filters.purchase_from.isoformat()
                    if filters.purchase_from
                    else None,
                    "purchase_to": filters.purchase_to.isoformat()
                    if filters.purchase_to
                    else None,
                },
                "row_count": row_count,
            },
        )
        await self.session.commit()

        filename = (
            f"itam-{report_type.lower()}-"
            f"{generated_at.strftime('%Y%m%d-%H%M%S')}.{suffix}"
        )
        return ReportExportResult(
            filename=filename,
            media_type=media_type,
            content=content,
            row_count=row_count,
        )
