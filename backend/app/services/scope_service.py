from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import DataScope
from app.models import Asset, Dept
from app.services.permission_service import AuthContext


def is_self_only(context: AuthContext) -> bool:
    return not context.is_superuser and context.data_scope == DataScope.SELF


async def asset_scope_conditions(
    session: AsyncSession,
    context: AuthContext,
    *,
    include_deleted: bool = False,
) -> list:
    """资产类查询的通用数据范围条件。"""
    conditions: list = [] if include_deleted else [Asset.deleted_at.is_(None)]
    if is_self_only(context):
        conditions.append(Asset.custodian_id == context.user.id)
        return conditions
    allowed = await scoped_dept_ids(session, context)
    if allowed is not None:
        if not allowed:
            conditions.append(false())
        else:
            conditions.append(Asset.dept_id.in_(allowed))
    return conditions


async def scoped_dept_ids(
    session: AsyncSession,
    context: AuthContext,
) -> set[int] | None:
    """返回数据范围内可见部门；None 表示全部部门。"""
    if context.is_superuser or context.data_scope == DataScope.ALL:
        return None

    own_dept_id = context.user.dept_id
    if context.data_scope == DataScope.SELF:
        return {own_dept_id} if own_dept_id else set()
    if context.data_scope == DataScope.DEPT:
        return {own_dept_id} if own_dept_id else set()
    if context.data_scope == DataScope.CUSTOM:
        return set(context.custom_dept_ids)
    if context.data_scope == DataScope.DEPT_AND_CHILD:
        if not own_dept_id:
            return set()
        depts = list((await session.execute(select(Dept))).scalars().all())
        own = next((item for item in depts if item.id == own_dept_id), None)
        if own is None:
            return set()
        prefix = own.path or f"/{own.id}/"
        return {dept.id for dept in depts if dept.path.startswith(prefix)}
    return set()


async def scoped_dept_tree_ids(
    session: AsyncSession,
    context: AuthContext,
) -> set[int] | None:
    """部门树需要保留祖先节点，避免子部门因父节点被过滤而丢失层级。"""
    allowed = await scoped_dept_ids(session, context)
    if allowed is None:
        return None
    if not allowed:
        return set()

    depts = list((await session.execute(select(Dept))).scalars().all())
    by_id = {dept.id: dept for dept in depts}
    result = set(allowed)
    for dept_id in list(allowed):
        current = by_id.get(dept_id)
        while current is not None and current.parent_id:
            result.add(current.parent_id)
            current = by_id.get(current.parent_id)
    return result
