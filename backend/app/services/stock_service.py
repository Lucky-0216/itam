from __future__ import annotations

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import AssetStatus
from app.core.exceptions import NotFoundError
from app.models import Asset, AssetCategory
from app.schemas.inbound import (
    StockAssetOut,
    StockAssetPageOut,
    StockLocationOut,
    StockOverviewOut,
    StockWarningOut,
)
from app.services.permission_service import AuthContext
from app.services.scope_service import asset_scope_conditions

NO_LOCATION_KEY = "__none__"
NO_LOCATION_LABEL = "未指定位置"


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _scope_conditions(
        self, context: AuthContext, *, location: str | None
    ) -> list:
        conditions = await asset_scope_conditions(
            self.session, context, resource="stock"
        )
        conditions.append(Asset.status == AssetStatus.IN_STOCK)
        if location == NO_LOCATION_KEY:
            conditions.append(Asset.location.is_(None))
        elif location:
            conditions.append(Asset.location == location)
        return conditions

    async def overview(
        self, context: AuthContext, *, location: str | None
    ) -> StockOverviewOut:
        conditions = await self._scope_conditions(context, location=location)
        location_rows = (
            await self.session.execute(
                select(
                    Asset.location,
                    func.count(Asset.id),
                    func.coalesce(func.sum(Asset.purchase_price), 0),
                )
                .where(*conditions)
                .group_by(Asset.location)
                .order_by(func.count(Asset.id).desc(), Asset.location.asc())
            )
        ).all()
        price_visible = context.can_view_field("asset", "purchase_price")
        locations = [
            StockLocationOut(
                location=row[0],
                location_label=row[0] or NO_LOCATION_LABEL,
                asset_count=int(row[1] or 0),
                total_value=float(row[2] or 0) if price_visible else 0.0,
            )
            for row in location_rows
        ]
        if locations and not context.can_view_field("asset", "location"):
            locations = [
                StockLocationOut(
                    location=None,
                    location_label="位置已隐藏",
                    asset_count=sum(item.asset_count for item in locations),
                    total_value=sum(item.total_value for item in locations),
                )
            ]

        count_expr = func.count(Asset.id)
        warning_rows = (
            await self.session.execute(
                select(
                    AssetCategory.id,
                    AssetCategory.name,
                    AssetCategory.safety_stock,
                    count_expr,
                )
                .join(Asset, Asset.category_id == AssetCategory.id)
                .where(*conditions, AssetCategory.safety_stock > 0)
                .group_by(
                    AssetCategory.id,
                    AssetCategory.name,
                    AssetCategory.safety_stock,
                )
                .having(count_expr < AssetCategory.safety_stock)
                .order_by(
                    (AssetCategory.safety_stock - count_expr).desc(),
                    AssetCategory.name,
                )
            )
        ).all()
        warnings = [
            StockWarningOut(
                category_id=row[0],
                category_name=row[1],
                stock_count=int(row[3] or 0),
                safety_stock=int(row[2] or 0),
                shortage=int(row[2] or 0) - int(row[3] or 0),
            )
            for row in warning_rows
        ]

        return StockOverviewOut(
            in_stock_count=sum(item.asset_count for item in locations),
            in_stock_value=sum(item.total_value for item in locations),
            location_count=len(locations),
            warning_count=len(warnings),
            locations=locations,
            warnings=warnings,
        )

    async def _category_ids(
        self, category_id: int | None, include_child: bool
    ) -> list[int] | None:
        if category_id is None:
            return None
        category = await self.session.get(AssetCategory, category_id)
        if category is None:
            raise NotFoundError("资产分类不存在")
        if not include_child:
            return [category.id]
        rows = (
            await self.session.execute(select(AssetCategory.id, AssetCategory.path))
        ).all()
        return [
            int(row[0])
            for row in rows
            if int(row[0]) == category.id or str(row[1]).startswith(category.path)
        ]

    async def list_items(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        category_id: int | None,
        include_child: bool,
        location: str | None,
        page: int,
        page_size: int,
    ) -> StockAssetPageOut:
        conditions = await self._scope_conditions(context, location=location)
        category_ids = await self._category_ids(category_id, include_child)
        if category_ids is not None:
            if not category_ids:
                conditions.append(false())
            else:
                conditions.append(Asset.category_id.in_(category_ids))
        if keyword:
            like = f"%{keyword.strip()}%"
            matchers = [Asset.asset_no.like(like)]
            if context.can_view_field("asset", "name"):
                matchers.append(Asset.name.like(like))
            if context.can_view_field("asset", "serial_no"):
                matchers.append(Asset.serial_no.like(like))
            conditions.append(or_(*matchers))
        total = await self.session.scalar(
            select(func.count()).select_from(Asset).where(*conditions)
        )
        rows = (
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.location.asc(), Asset.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        def visible(field: str, value):
            return value if context.can_view_field("asset", field) else None

        items = [
            StockAssetOut(
                id=asset.id,
                asset_no=asset.asset_no,
                name=asset.name
                if context.can_view_field("asset", "name")
                else "已隐藏",
                category_id=asset.category_id,
                category_name=asset.category.name if asset.category else None,
                model_name=asset.model.name if asset.model else None,
                serial_no=visible("serial_no", asset.serial_no),
                location=visible("location", asset.location),
                dept_id=asset.dept_id,
                dept_name=asset.dept.name if asset.dept else None,
                purchase_price=visible(
                    "purchase_price",
                    float(asset.purchase_price)
                    if asset.purchase_price is not None
                    else None,
                ),
                warranty_end=visible("warranty_end", asset.warranty_end),
                remark=visible("remark", asset.remark),
                created_at=asset.created_at,
            )
            for asset in rows
        ]
        return StockAssetPageOut(
            items=items,
            total=int(total or 0),
            page=page,
            page_size=page_size,
        )

    async def categories(self, context: AuthContext) -> list[dict[str, object]]:
        conditions: list = [AssetCategory.status == 1]
        domains = context.allowed_domains("stock")
        if domains is not None:
            conditions.append(AssetCategory.asset_domain.in_(domains))
        rows = (
            (
                await self.session.execute(
                    select(AssetCategory)
                    .where(*conditions)
                    .order_by(AssetCategory.path, AssetCategory.sort, AssetCategory.id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": category.id,
                "parent_id": category.parent_id,
                "name": category.name,
                "level": category.level,
                "path": category.path,
                "safety_stock": category.safety_stock,
            }
            for category in rows
        ]
