from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import DataScope
from app.models import (
    Asset,
    AssetCategory,
    AssetModel,
    Dept,
    Menu,
    Role,
    User,
)
from app.repositories.audit_repo import AuditLogRepository
from app.schemas.audit import (
    AuditFilterOptions,
    AuditLogDetail,
    AuditLogPage,
)
from app.services.permission_service import AuthContext
from app.services.scope_service import scoped_dept_ids

_ID_FIELD_KINDS: dict[str, str] = {
    "user_id": "user",
    "custodian_id": "user",
    "owner_id": "user",
    "manager_id": "user",
    "applicant_id": "user",
    "from_custodian_id": "user",
    "to_custodian_id": "user",
    "created_by_id": "user",
    "updated_by_id": "user",
    "dept_id": "dept",
    "from_dept_id": "dept",
    "to_dept_id": "dept",
    "category_id": "category",
    "model_id": "model",
    "asset_id": "asset",
    "user_ids": "user",
    "dept_ids": "dept",
    "menu_ids": "menu",
    "role_ids": "role",
    "asset_ids": "asset",
}


def _value_ids(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdigit():
        return [int(value)]
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            result.extend(_value_ids(item))
        return result
    return []


def _parent_kind(module: str, resource_type: str | None) -> str | None:
    text = f"{module} {resource_type or ''}"
    if "分类" in text:
        return "category"
    if "部门" in text or "组织" in text:
        return "dept"
    if "菜单" in text:
        return "menu"
    return None


def _field_kinds(
    before: dict[str, Any], after: dict[str, Any], module: str, resource_type: str | None
) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for field in set(before) | set(after):
        kind = _ID_FIELD_KINDS.get(field)
        if kind is None and field == "parent_id":
            kind = _parent_kind(module, resource_type)
        if kind:
            kinds[field] = kind
    return kinds


def _labels_for(
    snapshot: dict[str, Any], kinds: dict[str, str], names: dict[str, dict[int, str]]
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for field, kind in kinds.items():
        value = snapshot.get(field)
        ids = _value_ids(value)
        lookup = names.get(kind, {})
        if isinstance(value, list):
            if not ids:
                labels[field] = "无"
            else:
                labels[field] = "、".join(lookup.get(item, f"#{item}") for item in ids)
        elif ids and ids[0] in lookup:
            labels[field] = lookup[ids[0]]
    return labels


class AuditQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logs = AuditLogRepository(session)

    async def _allowed_user_ids(self, context: AuthContext) -> set[int] | None:
        if context.is_superuser or context.data_scope == DataScope.ALL:
            return None
        if context.data_scope == DataScope.SELF:
            return {context.user.id}
        dept_ids = await scoped_dept_ids(self.session, context)
        if not dept_ids:
            return set()
        stmt = select(User.id).where(User.dept_id.in_(dept_ids))
        return set((await self.session.execute(stmt)).scalars().all())

    async def list(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        module: str | None,
        action: str | None,
        status: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
        page: int,
        page_size: int,
    ) -> AuditLogPage:
        user_ids = await self._allowed_user_ids(context)
        rows, total = await self.logs.list_paginated(
            user_ids=user_ids,
            keyword=keyword,
            module=module,
            action=action,
            status=status,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
        return AuditLogPage(items=rows, total=total, page=page, page_size=page_size)

    async def _name_maps(
        self, ids_by_kind: dict[str, set[int]]
    ) -> dict[str, dict[int, str]]:
        names: dict[str, dict[int, str]] = {}

        user_ids = ids_by_kind.get("user")
        if user_ids:
            rows = await self.session.execute(
                select(User.id, User.real_name, User.username).where(
                    User.id.in_(user_ids)
                )
            )
            names["user"] = {
                row.id: (f"{row.real_name}（{row.username}）" if row.real_name else row.username)
                for row in rows
            }

        dept_ids = ids_by_kind.get("dept")
        if dept_ids:
            rows = await self.session.execute(
                select(Dept.id, Dept.name).where(Dept.id.in_(dept_ids))
            )
            names["dept"] = {row.id: row.name for row in rows}

        category_ids = ids_by_kind.get("category")
        if category_ids:
            rows = await self.session.execute(
                select(AssetCategory.id, AssetCategory.name).where(
                    AssetCategory.id.in_(category_ids)
                )
            )
            names["category"] = {row.id: row.name for row in rows}

        model_ids = ids_by_kind.get("model")
        if model_ids:
            rows = await self.session.execute(
                select(AssetModel.id, AssetModel.name, AssetModel.brand).where(
                    AssetModel.id.in_(model_ids)
                )
            )
            names["model"] = {
                row.id: (
                    f"{row.brand} {row.name}"
                    if row.brand and row.brand not in row.name
                    else row.name
                )
                for row in rows
            }

        menu_ids = ids_by_kind.get("menu")
        if menu_ids:
            rows = await self.session.execute(
                select(Menu.id, Menu.name).where(Menu.id.in_(menu_ids))
            )
            names["menu"] = {row.id: row.name for row in rows}

        role_ids = ids_by_kind.get("role")
        if role_ids:
            rows = await self.session.execute(
                select(Role.id, Role.name).where(Role.id.in_(role_ids))
            )
            names["role"] = {row.id: row.name for row in rows}

        asset_ids = ids_by_kind.get("asset")
        if asset_ids:
            rows = await self.session.execute(
                select(Asset.id, Asset.name, Asset.asset_no).where(
                    Asset.id.in_(asset_ids)
                )
            )
            names["asset"] = {
                row.id: f"{row.name}（{row.asset_no}）" for row in rows
            }

        return names

    async def detail(self, log_id: int, context: AuthContext) -> AuditLogDetail:
        log = await self.logs.get(log_id)
        if log is None:
            raise NotFoundError("审计日志不存在")
        user_ids = await self._allowed_user_ids(context)
        if user_ids is not None and (log.user_id is None or log.user_id not in user_ids):
            raise NotFoundError("审计日志不存在")
        result = AuditLogDetail.model_validate(log)

        before = log.before_data if isinstance(log.before_data, dict) else {}
        after = log.after_data if isinstance(log.after_data, dict) else {}
        kinds = _field_kinds(before, after, log.module, log.resource_type)
        if kinds:
            ids_by_kind: dict[str, set[int]] = {}
            for field, kind in kinds.items():
                for snapshot in (before, after):
                    ids_by_kind.setdefault(kind, set()).update(
                        _value_ids(snapshot.get(field))
                    )
            names = await self._name_maps(ids_by_kind)
            result.before_labels = _labels_for(before, kinds, names) or None
            result.after_labels = _labels_for(after, kinds, names) or None
        return result

    async def options(self, context: AuthContext) -> AuditFilterOptions:
        user_ids = await self._allowed_user_ids(context)
        modules, actions = await self.logs.filter_options(user_ids=user_ids)
        return AuditFilterOptions(modules=modules, actions=actions)
