from datetime import date, datetime, timedelta

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import RequestStatus, RequestType
from app.core.asset_ops import InboundStatus
from app.core.assets import ASSET_STATUS_LABELS, AssetStatus
from app.core.permissions import DATA_SCOPE_LABELS
from app.models import (
    Asset,
    AssetCategory,
    AssetContract,
    AssetContractAsset,
    AssetInbound,
    AssetInboundItem,
    AssetRequest,
    Dept,
)
from app.models.base import now_cst
from app.schemas.dashboard import (
    CategorySlice,
    DashboardDeptOption,
    DashboardMetrics,
    DashboardPeriod,
    DashboardSummaryOut,
    DeptSlice,
    RecentAssetItem,
    StatusSlice,
    TrendPoint,
    WarrantyItem,
)
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_scope_conditions,
    is_self_only,
    scoped_dept_ids,
)

_TREND_MONTHS = 12
_CONTRACT_REMINDER_DAYS = 30


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_sequence(today: date, count: int) -> list[tuple[int, int]]:
    return [
        _shift_month(today.year, today.month, -offset)
        for offset in range(count - 1, -1, -1)
    ]


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(
        self,
        context: AuthContext,
        *,
        dept_id: int | None = None,
        months: int = _TREND_MONTHS,
    ) -> DashboardSummaryOut:
        if months not in (3, 6, 12):
            months = _TREND_MONTHS
        today = now_cst().date()
        month_start = datetime(today.year, today.month, 1)
        period_year, period_month = _shift_month(
            today.year, today.month, -(months - 1)
        )
        period_start = datetime(period_year, period_month, 1)

        allowed_dept_ids = await self._dept_scope(context, dept_id)
        conditions = await asset_scope_conditions(
            self.session, context, resource="report"
        )
        if not is_self_only(context, "report") and allowed_dept_ids is not None:
            if not allowed_dept_ids:
                conditions.append(false())
            else:
                conditions.append(Asset.dept_id.in_(allowed_dept_ids))

        status_rows = (
            await self.session.execute(
                select(Asset.status, func.count(Asset.id))
                .where(*conditions)
                .group_by(Asset.status)
            )
        ).all()
        status_counts: dict[str, int] = {
            status: 0 for status in ASSET_STATUS_LABELS
        }
        for status, count in status_rows:
            status_counts[status] = int(count)
        total_assets = sum(status_counts.values())

        total_value = (
            float(
                await self.session.scalar(
                    select(func.coalesce(func.sum(Asset.purchase_price), 0)).where(
                        *conditions
                    )
                )
                or 0
            )
            if context.can_view_field("asset", "purchase_price")
            else 0.0
        )

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

        status_distribution = [
            StatusSlice(
                status=status,
                label=label,
                count=status_counts.get(status, 0),
            )
            for status, label in ASSET_STATUS_LABELS.items()
        ]
        extra_statuses = set(status_counts) - set(ASSET_STATUS_LABELS)
        for status in sorted(extra_statuses):
            status_distribution.append(
                StatusSlice(status=status, label=status, count=status_counts[status])
            )

        category_distribution = await self._category_distribution(conditions)
        dept_distribution = await self._dept_distribution(conditions)
        purchase_trend = await self._purchase_trend(conditions, today, months)
        warranty_expiring = await self._warranty_expiring(conditions, today, context)
        recent_assets = await self._recent_assets(conditions, context)
        dept_options = await self._dept_options(context)

        month_inbound = await self._inbound_quantity(
            context, allowed_dept_ids, month_start
        )
        month_requisition = await self._requisition_count(
            context, allowed_dept_ids, month_start
        )
        contract_expiring = await self._contract_expiring_count(
            context, allowed_dept_ids, today
        )
        idle_count = status_counts.get(AssetStatus.IDLE, 0)
        idle_rate = (
            round(idle_count * 100 / total_assets, 1) if total_assets else 0.0
        )
        period_new_assets = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(
                    *conditions,
                    Asset.created_at >= period_start,
                )
            )
            or 0
        )

        return DashboardSummaryOut(
            metrics=DashboardMetrics(
                total_assets=total_assets,
                total_value=round(total_value, 2),
                pending_stock=status_counts.get(AssetStatus.PENDING_STOCK, 0),
                in_stock=status_counts.get(AssetStatus.IN_STOCK, 0),
                in_use=status_counts.get(AssetStatus.IN_USE, 0),
                idle=idle_count,
                repairing=status_counts.get(AssetStatus.REPAIRING, 0),
                pending_scrap=status_counts.get(AssetStatus.PENDING_SCRAP, 0),
                scrapped=status_counts.get(AssetStatus.SCRAPPED, 0),
                warranty_30d=warranty_30d,
                month_inbound=month_inbound,
                month_requisition=month_requisition,
                contract_expiring=contract_expiring,
                idle_rate=idle_rate,
            ),
            status_distribution=status_distribution,
            category_distribution=category_distribution,
            dept_distribution=dept_distribution,
            purchase_trend=purchase_trend,
            warranty_expiring=warranty_expiring,
            recent_assets=recent_assets,
            data_scope_label=DATA_SCOPE_LABELS.get(
                context.effective_scope("report"), context.effective_scope("report")
            ),
            period=DashboardPeriod(
                months=months,
                start_date=period_start.date(),
                new_assets=period_new_assets,
                inbound=await self._inbound_quantity(
                    context, allowed_dept_ids, period_start
                ),
                requisition=await self._requisition_count(
                    context, allowed_dept_ids, period_start
                ),
            ),
            dept_options=dept_options,
            dept_id=dept_id,
        )

    async def _dept_scope(
        self,
        context: AuthContext,
        dept_id: int | None,
    ) -> set[int] | None:
        allowed = await scoped_dept_ids(self.session, context, resource="report")
        if dept_id is None:
            return allowed
        depts = list((await self.session.execute(select(Dept))).scalars().all())
        by_id = {dept.id: dept for dept in depts}
        target = by_id.get(dept_id)
        if target is None:
            return set()
        prefix = target.path or f"/{target.id}/"
        subtree = {dept.id for dept in depts if dept.path.startswith(prefix)}
        if allowed is None:
            return subtree
        return allowed & subtree

    async def _dept_options(self, context: AuthContext) -> list[DashboardDeptOption]:
        allowed = await scoped_dept_ids(self.session, context, resource="report")
        stmt = (
            select(Dept)
            .where(Dept.status == 1)
            .order_by(Dept.path, Dept.sort, Dept.id)
        )
        if allowed is not None:
            if not allowed:
                return []
            stmt = stmt.where(Dept.id.in_(allowed))
        depts = list((await self.session.execute(stmt)).scalars().all())
        return [
            DashboardDeptOption(
                id=dept.id,
                parent_id=dept.parent_id,
                name=dept.name,
                level=dept.level,
            )
            for dept in depts
        ]

    async def _inbound_quantity(
        self,
        context: AuthContext,
        allowed_dept_ids: set[int] | None,
        since: datetime,
    ) -> int:
        stmt = select(func.coalesce(func.sum(AssetInbound.total_quantity), 0)).where(
            AssetInbound.status == InboundStatus.COMPLETED,
            AssetInbound.confirmed_at.is_not(None),
            AssetInbound.confirmed_at >= since,
        )
        if is_self_only(context, "report"):
            stmt = stmt.where(AssetInbound.created_by_id == context.user.id)
        elif allowed_dept_ids is not None:
            if not allowed_dept_ids:
                return 0
            stmt = stmt.where(AssetInbound.dept_id.in_(allowed_dept_ids))
        domains = context.allowed_domains("report")
        if domains is not None:
            stmt = stmt.where(
                AssetInbound.id.in_(
                    select(AssetInboundItem.inbound_id)
                    .join(AssetCategory, AssetCategory.id == AssetInboundItem.category_id)
                    .where(AssetCategory.asset_domain.in_(domains))
                )
            )
        return int(await self.session.scalar(stmt) or 0)

    async def _requisition_count(
        self,
        context: AuthContext,
        allowed_dept_ids: set[int] | None,
        since: datetime,
    ) -> int:
        stmt = select(func.count(AssetRequest.id)).where(
            AssetRequest.request_type == RequestType.REQUISITION,
            AssetRequest.status == RequestStatus.COMPLETED,
            AssetRequest.outbound_at.is_not(None),
            AssetRequest.outbound_at >= since,
        )
        if is_self_only(context, "report"):
            stmt = stmt.where(AssetRequest.applicant_id == context.user.id)
        elif allowed_dept_ids is not None:
            if not allowed_dept_ids:
                return 0
            stmt = stmt.where(AssetRequest.applicant_dept_id.in_(allowed_dept_ids))
        domains = context.allowed_domains("report")
        if domains is not None:
            stmt = stmt.where(
                AssetRequest.category_id.in_(
                    select(AssetCategory.id).where(
                        AssetCategory.asset_domain.in_(domains)
                    )
                )
            )
        return int(await self.session.scalar(stmt) or 0)

    async def _contract_expiring_count(
        self,
        context: AuthContext,
        allowed_dept_ids: set[int] | None,
        today: date,
    ) -> int:
        stmt = select(func.count(AssetContract.id)).where(
            AssetContract.terminated_at.is_(None),
            AssetContract.end_date >= today,
            AssetContract.end_date <= today + timedelta(days=_CONTRACT_REMINDER_DAYS),
        )
        if is_self_only(context, "report"):
            stmt = stmt.where(
                or_(
                    AssetContract.owner_id == context.user.id,
                    AssetContract.created_by_id == context.user.id,
                )
            )
        elif allowed_dept_ids is not None:
            if not allowed_dept_ids:
                return 0
            stmt = stmt.where(AssetContract.dept_id.in_(allowed_dept_ids))
        domains = context.allowed_domains("report")
        if domains is not None:
            stmt = stmt.where(
                AssetContract.id.in_(
                    select(AssetContractAsset.contract_id)
                    .join(Asset, Asset.id == AssetContractAsset.asset_id)
                    .join(AssetCategory, AssetCategory.id == Asset.category_id)
                    .where(AssetCategory.asset_domain.in_(domains))
                )
            )
        return int(await self.session.scalar(stmt) or 0)

    async def _category_distribution(self, conditions: list) -> list[CategorySlice]:
        rows = (
            await self.session.execute(
                select(Asset.category_id, func.count(Asset.id))
                .where(*conditions)
                .group_by(Asset.category_id)
            )
        ).all()
        if not rows:
            return []

        categories = list(
            (await self.session.execute(select(AssetCategory))).scalars().all()
        )
        by_id = {category.id: category for category in categories}
        root_counts: dict[int, int] = {}
        for category_id, count in rows:
            category = by_id.get(int(category_id))
            if category is None:
                continue
            root = category
            while root.parent_id and root.parent_id in by_id:
                root = by_id[root.parent_id]
            root_counts[root.id] = root_counts.get(root.id, 0) + int(count)

        ordered = sorted(
            root_counts.items(), key=lambda item: (-item[1], item[0])
        )
        top = ordered[:8]
        result = [
            CategorySlice(
                category_id=category_id,
                name=by_id[category_id].name,
                count=count,
            )
            for category_id, count in top
        ]
        rest = sum(count for _, count in ordered[8:])
        if rest:
            result.append(CategorySlice(name="其他分类", count=rest))
        return result

    async def _dept_distribution(self, conditions: list) -> list[DeptSlice]:
        rows = (
            await self.session.execute(
                select(Dept.id, Dept.name, func.count(Asset.id))
                .join(Asset, Asset.dept_id == Dept.id)
                .where(*conditions)
                .group_by(Dept.id, Dept.name)
                .order_by(func.count(Asset.id).desc(), Dept.id)
                .limit(8)
            )
        ).all()
        return [
            DeptSlice(dept_id=int(dept_id), name=name, count=int(count))
            for dept_id, name, count in rows
        ]

    async def _purchase_trend(
        self,
        conditions: list,
        today: date,
        months: int,
    ) -> list[TrendPoint]:
        sequence = _month_sequence(today, months)
        start_year, start_month = sequence[0]
        start_date = date(start_year, start_month, 1)
        rows = (
            (
                await self.session.execute(
                    select(Asset.purchase_date).where(
                        *conditions,
                        Asset.purchase_date.is_not(None),
                        Asset.purchase_date >= start_date,
                    )
                )
            )
            .scalars()
            .all()
        )
        counts: dict[tuple[int, int], int] = {}
        for purchase_date in rows:
            key = (purchase_date.year, purchase_date.month)
            counts[key] = counts.get(key, 0) + 1
        return [
            TrendPoint(
                month=f"{year:04d}-{month:02d}",
                count=counts.get((year, month), 0),
            )
            for year, month in sequence
        ]

    async def _warranty_expiring(
        self,
        conditions: list,
        today: date,
        context: AuthContext,
    ) -> list[WarrantyItem]:
        if not context.can_view_field("asset", "warranty_end"):
            return []
        limit_date = today + timedelta(days=60)
        assets = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(
                        *conditions,
                        Asset.warranty_end.is_not(None),
                        Asset.warranty_end >= today,
                        Asset.warranty_end <= limit_date,
                        Asset.status != AssetStatus.SCRAPPED,
                    )
                    .order_by(Asset.warranty_end.asc(), Asset.id.asc())
                    .limit(8)
                )
            )
            .scalars()
            .all()
        )
        name_visible = context.can_view_field("asset", "name")
        custodian_visible = context.can_view_field("asset", "custodian_id")
        return [
            WarrantyItem(
                id=asset.id,
                asset_no=asset.asset_no,
                name=asset.name if name_visible else "已隐藏",
                category_name=asset.category.name if asset.category else None,
                dept_name=asset.dept.name if asset.dept else None,
                custodian_name=(
                    asset.custodian.real_name
                    if custodian_visible and asset.custodian
                    else None
                ),
                warranty_end=asset.warranty_end,
                days_left=(asset.warranty_end - today).days,
            )
            for asset in assets
            if asset.warranty_end is not None
        ]

    async def _recent_assets(
        self, conditions: list, context: AuthContext
    ) -> list[RecentAssetItem]:
        assets = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.created_at.desc(), Asset.id.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        name_visible = context.can_view_field("asset", "name")
        return [
            RecentAssetItem(
                id=asset.id,
                asset_no=asset.asset_no,
                name=asset.name if name_visible else "已隐藏",
                category_name=asset.category.name if asset.category else None,
                dept_name=asset.dept.name if asset.dept else None,
                status=asset.status,
                status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
                created_at=asset.created_at,
            )
            for asset in assets
        ]
