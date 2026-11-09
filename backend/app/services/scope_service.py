from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import DataScope
from app.models import (
    Asset,
    AssetCategory,
    AssetContract,
    AssetContractAsset,
    Dept,
)
from app.services.permission_service import AuthContext


def is_self_only(context: AuthContext, resource: str | None = None) -> bool:
    if context.is_superuser:
        return False
    scope = context.effective_scope(resource) if resource else context.data_scope
    return scope == DataScope.SELF


def asset_domain_condition(context: AuthContext, resource: str):
    """按资源维度把资产限定在允许的业务域；None 表示不限制。"""
    domains = context.allowed_domains(resource)
    if domains is None:
        return None
    return Asset.category_id.in_(
        select(AssetCategory.id).where(AssetCategory.asset_domain.in_(domains))
    )


def category_domain_condition(column, context: AuthContext, resource: str):
    """把直接引用分类的列限定在允许的业务域；None 表示不限制。"""
    domains = context.allowed_domains(resource)
    if domains is None:
        return None
    return column.in_(
        select(AssetCategory.id).where(AssetCategory.asset_domain.in_(domains))
    )


def contract_domain_condition(context: AuthContext):
    """受限域用户只能看到关联资产属于其域的合同。"""
    domain_condition = asset_domain_condition(context, "contract")
    if domain_condition is None:
        return None
    linked_ids = (
        select(AssetContractAsset.contract_id)
        .join(Asset, Asset.id == AssetContractAsset.asset_id)
        .where(domain_condition)
    )
    return AssetContract.id.in_(linked_ids)


def category_domain_allowed(
    category: AssetCategory | None,
    context: AuthContext,
    resource: str | None = None,
) -> bool:
    domains = context.allowed_domains(resource)
    if domains is None:
        return True
    if category is None:
        return False
    return category.asset_domain in domains


async def asset_scope_conditions(
    session: AsyncSession,
    context: AuthContext,
    *,
    resource: str = "asset",
    include_deleted: bool = False,
) -> list:
    """资产类查询的通用数据范围条件。"""
    conditions: list = [] if include_deleted else [Asset.deleted_at.is_(None)]
    if is_self_only(context, resource):
        conditions.append(
            or_(
                Asset.custodian_id == context.user.id,
                Asset.created_by_id == context.user.id,
            )
        )
    else:
        allowed = await scoped_dept_ids(session, context, resource=resource)
        if allowed is not None:
            if not allowed:
                conditions.append(false())
            else:
                conditions.append(Asset.dept_id.in_(allowed))
    domain_condition = asset_domain_condition(context, resource)
    if domain_condition is not None:
        conditions.append(domain_condition)
    return conditions


async def scoped_dept_ids(
    session: AsyncSession,
    context: AuthContext,
    *,
    resource: str | None = None,
) -> set[int] | None:
    """返回数据范围内可见部门；None 表示全部部门。"""
    scope = context.effective_scope(resource) if resource else context.data_scope
    if context.is_superuser or scope == DataScope.ALL:
        return None
    if scope in (DataScope.ROLE, DataScope.SELF):
        return set()

    own_dept_id = context.user.dept_id
    if scope == DataScope.DEPT:
        return {own_dept_id} if own_dept_id else set()
    if scope == DataScope.CUSTOM:
        if resource:
            return set(context.allowed_custom_dept_ids(resource))
        return set(context.custom_dept_ids)
    if scope == DataScope.DEPT_AND_CHILD:
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
    *,
    resource: str | None = None,
) -> set[int] | None:
    """部门树需要保留祖先节点，避免子部门因父节点被过滤而丢失层级。"""
    allowed = await scoped_dept_ids(session, context, resource=resource)
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
