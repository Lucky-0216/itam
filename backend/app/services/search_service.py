from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import ASSET_STATUS_LABELS
from app.models import Asset, Dept, User
from app.schemas.search import SearchItemOut, SearchResultOut
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_scope_conditions,
    is_self_only,
    scoped_dept_ids,
)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        context: AuthContext,
        keyword: str,
        limit: int = 5,
    ) -> SearchResultOut:
        term = keyword.strip()
        if not term:
            return SearchResultOut(keyword="", items=[])

        pattern = _like(term)
        items: list[SearchItemOut] = []
        if context.has_permission("asset:ledger:view"):
            items.extend(await self._search_assets(context, pattern, limit))
        if context.has_permission("system:org:view"):
            items.extend(await self._search_users(context, pattern, limit))
            items.extend(await self._search_depts(context, pattern, limit))
        return SearchResultOut(keyword=term, items=items)

    async def _search_assets(
        self,
        context: AuthContext,
        pattern: str,
        limit: int,
    ) -> list[SearchItemOut]:
        conditions = await asset_scope_conditions(self.session, context)
        matchers = [Asset.asset_no.ilike(pattern, escape="\\")]
        if context.can_view_field("asset", "serial_no"):
            matchers.append(Asset.serial_no.ilike(pattern, escape="\\"))
        stmt = (
            select(Asset)
            .where(*conditions, or_(*matchers))
            .order_by(Asset.id.desc())
            .limit(limit)
        )
        assets = (await self.session.execute(stmt)).scalars().all()
        results: list[SearchItemOut] = []
        name_visible = context.can_view_field("asset", "name")
        custodian_visible = context.can_view_field("asset", "custodian_id")
        for asset in assets:
            subtitle = " · ".join(
                part
                for part in [
                    asset.category.name if asset.category else None,
                    ASSET_STATUS_LABELS.get(asset.status, asset.status),
                    asset.custodian.real_name
                    if custodian_visible and asset.custodian
                    else None,
                ]
                if part
            )
            name = asset.name if name_visible else "已隐藏"
            results.append(
                SearchItemOut(
                    type="asset",
                    id=asset.id,
                    title=f"{name} · {asset.asset_no}",
                    subtitle=subtitle or None,
                    keyword=asset.asset_no,
                )
            )
        return results

    async def _search_users(
        self,
        context: AuthContext,
        pattern: str,
        limit: int,
    ) -> list[SearchItemOut]:
        allowed = await scoped_dept_ids(self.session, context)

        conditions: list = [
            User.deleted_at.is_(None),
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.real_name.ilike(pattern, escape="\\"),
                User.employee_no.ilike(pattern, escape="\\"),
                User.phone.ilike(pattern, escape="\\"),
            ),
        ]
        if is_self_only(context):
            conditions.append(User.id == context.user.id)
        elif allowed is not None:
            conditions.append(User.dept_id.in_(allowed))

        stmt = select(User).where(*conditions).order_by(User.id.desc()).limit(limit)
        users = (await self.session.execute(stmt)).scalars().all()
        results: list[SearchItemOut] = []
        for user in users:
            subtitle = " · ".join(
                part
                for part in [
                    user.username,
                    user.dept.name if user.dept else None,
                    user.position,
                ]
                if part
            )
            results.append(
                SearchItemOut(
                    type="user",
                    id=user.id,
                    title=user.real_name,
                    subtitle=subtitle or None,
                    keyword=user.username,
                )
            )
        return results

    async def _search_depts(
        self,
        context: AuthContext,
        pattern: str,
        limit: int,
    ) -> list[SearchItemOut]:
        allowed = await scoped_dept_ids(self.session, context)
        if allowed is not None and not allowed:
            return []

        conditions: list = [
            or_(
                Dept.name.ilike(pattern, escape="\\"),
                Dept.code.ilike(pattern, escape="\\"),
            )
        ]
        if allowed is not None:
            conditions.append(Dept.id.in_(allowed))

        stmt = select(Dept).where(*conditions).order_by(Dept.sort, Dept.id).limit(limit)
        depts = (await self.session.execute(stmt)).scalars().all()
        return [
            SearchItemOut(
                type="dept",
                id=dept.id,
                title=dept.name,
                subtitle=f"{dept.code} · {dept.path}",
                keyword=dept.name,
            )
            for dept in depts
        ]
