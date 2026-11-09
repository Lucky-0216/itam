from datetime import date
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetCategory, AssetModel
from app.repositories.base import BaseRepository


class AssetCategoryRepository(BaseRepository[AssetCategory]):
    model = AssetCategory

    async def list_all(self) -> list[AssetCategory]:
        stmt = select(AssetCategory).order_by(AssetCategory.sort, AssetCategory.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(self, code: str) -> AssetCategory | None:
        stmt = select(AssetCategory).where(AssetCategory.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_children(self, category_id: int) -> int:
        stmt = select(func.count()).select_from(AssetCategory).where(
            AssetCategory.parent_id == category_id
        )
        return int(await self.session.scalar(stmt) or 0)

    async def model_counts(
        self, conditions: list[Any] | None = None
    ) -> dict[int, int]:
        stmt = select(AssetModel.category_id, func.count(AssetModel.id)).group_by(
            AssetModel.category_id
        )
        if conditions is not None:
            stmt = stmt.where(*conditions)
        return {int(category_id): int(count) for category_id, count in (await self.session.execute(stmt)).all()}

    async def asset_counts(self, conditions: list[Any] | None = None) -> dict[int, int]:
        stmt = (
            select(Asset.category_id, func.count(Asset.id))
            .where(
                *(conditions if conditions is not None else [Asset.deleted_at.is_(None)])
            )
            .group_by(Asset.category_id)
        )
        return {int(category_id): int(count) for category_id, count in (await self.session.execute(stmt)).all()}

    async def count_models(self, category_id: int) -> int:
        return (await self.model_counts()).get(category_id, 0)

    async def count_assets(self, category_id: int) -> int:
        return (await self.asset_counts()).get(category_id, 0)


class AssetModelRepository(BaseRepository[AssetModel]):
    model = AssetModel

    async def get_by_code(self, code: str) -> AssetModel | None:
        stmt = select(AssetModel).where(AssetModel.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        category_ids: list[int] | None,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[AssetModel], int]:
        conditions = []
        if category_ids is not None:
            if not category_ids:
                return [], 0
            conditions.append(AssetModel.category_id.in_(category_ids))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetModel.name.like(pattern),
                    AssetModel.code.like(pattern),
                    AssetModel.brand.like(pattern),
                    AssetModel.spec.like(pattern),
                )
            )
        if status is not None:
            conditions.append(AssetModel.status == status)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AssetModel).where(*conditions)
            )
            or 0
        )
        stmt = (
            select(AssetModel)
            .where(*conditions)
            .order_by(AssetModel.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def count_assets(
        self, model_id: int, conditions: list[Any] | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Asset)
            .where(
                Asset.model_id == model_id,
                *(conditions if conditions is not None else [Asset.deleted_at.is_(None)]),
            )
        )
        return int(await self.session.scalar(stmt) or 0)


class AssetRepository(BaseRepository[Asset]):
    model = Asset

    async def get_detail(self, asset_id: int, *, include_deleted: bool = False) -> Asset | None:
        stmt = select(Asset).where(Asset.id == asset_id)
        if not include_deleted:
            stmt = stmt.where(Asset.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def max_asset_no(self, prefix: str) -> str | None:
        stmt = (
            select(func.max(Asset.asset_no))
            .where(Asset.asset_no.like(f"{prefix}%"))
        )
        return await self.session.scalar(stmt)

    async def get_by_asset_no(
        self, asset_no: str, *, include_deleted: bool = False
    ) -> Asset | None:
        stmt = select(Asset).where(Asset.asset_no == asset_no)
        if not include_deleted:
            stmt = stmt.where(Asset.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count(self, conditions: list[Any]) -> int:
        stmt = select(func.count()).select_from(Asset).where(*conditions)
        return int(await self.session.scalar(stmt) or 0)

    async def sum_value(self, conditions: list[Any]) -> float:
        stmt = select(func.coalesce(func.sum(Asset.purchase_price), 0)).where(*conditions)
        return float(await self.session.scalar(stmt) or 0)

    async def list_paginated(
        self,
        conditions: list[Any],
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Asset], int]:
        total = await self.count(conditions)
        stmt = (
            select(Asset)
            .where(*conditions)
            .order_by(Asset.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    async def count_by_status(self, conditions: list[Any]) -> dict[str, int]:
        stmt = (
            select(Asset.status, func.count(Asset.id))
            .where(*conditions)
            .group_by(Asset.status)
        )
        return {status: int(count) for status, count in (await self.session.execute(stmt)).all()}

    async def count_by_category(self, conditions: list[Any]) -> dict[int, int]:
        stmt = (
            select(Asset.category_id, func.count(Asset.id))
            .where(*conditions)
            .group_by(Asset.category_id)
        )
        return {
            int(category_id): int(count)
            for category_id, count in (await self.session.execute(stmt)).all()
        }

    async def count_by_dept(self, conditions: list[Any]) -> dict[int | None, int]:
        stmt = (
            select(Asset.dept_id, func.count(Asset.id))
            .where(*conditions)
            .group_by(Asset.dept_id)
        )
        return {dept_id: int(count) for dept_id, count in (await self.session.execute(stmt)).all()}

    async def count_by_month(self, conditions: list[Any]) -> dict[str, int]:
        month_expr = func.substr(cast(Asset.created_at, String), 1, 7)
        stmt = (
            select(month_expr, func.count(Asset.id))
            .where(*conditions)
            .group_by(month_expr)
        )
        return {str(month): int(count) for month, count in (await self.session.execute(stmt)).all()}

    async def warranty_list(
        self,
        conditions: list[Any],
        *,
        start: date,
        end: date,
        limit: int,
    ) -> list[Asset]:
        stmt = (
            select(Asset)
            .where(
                *conditions,
                Asset.warranty_end.is_not(None),
                Asset.warranty_end >= start,
                Asset.warranty_end <= end,
            )
            .order_by(Asset.warranty_end.asc(), Asset.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
