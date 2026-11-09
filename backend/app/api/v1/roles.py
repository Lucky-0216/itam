from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_perm, require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.rbac import (
    DataPermissionsAssignRequest,
    FieldPermissionsAssignRequest,
    MenuAssignRequest,
    RoleCreate,
    RoleUpdate,
    RoleUsersAssignRequest,
)
from app.services.permission_service import AuthContext
from app.services.role_service import RoleService

router = APIRouter(tags=["角色权限"])


@router.get("/roles", summary="角色列表")
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    status: int | None = Query(None, ge=0, le=1),
    _: AuthContext = Depends(require_perm("system:role:view")),
    session: AsyncSession = Depends(get_db),
):
    items, total = await RoleService(session).list_roles(
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/roles/options/all", summary="启用角色下拉选项")
async def role_options(
    _: AuthContext = Depends(
        require_any_perm(
            "system:role:view",
            "system:user:create",
            "system:user:update",
            "system:role:assign-user",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    items = await RoleService(session).list_all()
    return ok([item.model_dump(mode="json") for item in items])


@router.get("/roles/options/meta", summary="数据范围与字段权限目录")
async def role_meta(
    context: AuthContext = Depends(require_perm("system:role:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).meta(context)
    return ok(result.model_dump(mode="json"))


@router.get("/roles/menu-tree", summary="全量菜单树（含按钮）")
async def menu_tree(
    _: AuthContext = Depends(
        require_any_perm("system:role:view", "system:role:assign-menu")
    ),
    session: AsyncSession = Depends(get_db),
):
    items = await RoleService(session).menu_tree()
    return ok([item.model_dump(mode="json") for item in items])


@router.get("/roles/user-options", summary="角色成员可选用户")
async def role_user_options(
    keyword: str | None = Query(None, max_length=100),
    context: AuthContext = Depends(require_perm("system:role:assign-user")),
    session: AsyncSession = Depends(get_db),
):
    items = await RoleService(session).user_options(context, keyword=keyword)
    return ok([item.model_dump(mode="json") for item in items])


@router.post("/roles", summary="新增角色")
async def create_role(
    payload: RoleCreate,
    context: AuthContext = Depends(require_perm("system:role:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="角色创建成功")


@router.get("/roles/{role_id}", summary="角色详情（含授权）")
async def role_detail(
    role_id: int,
    context: AuthContext = Depends(require_perm("system:role:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).detail(role_id, context)
    return ok(result.model_dump(mode="json"))


@router.put("/roles/{role_id}", summary="编辑角色")
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    context: AuthContext = Depends(require_perm("system:role:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).update(role_id, payload, context)
    return ok(result.model_dump(mode="json"), message="角色更新成功")


@router.delete("/roles/{role_id}", summary="删除角色")
async def delete_role(
    role_id: int,
    context: AuthContext = Depends(require_perm("system:role:delete")),
    session: AsyncSession = Depends(get_db),
):
    await RoleService(session).delete(role_id, context)
    return ok(None, message="角色已删除")


@router.put("/roles/{role_id}/menus", summary="分配菜单与按钮权限")
async def assign_role_menus(
    role_id: int,
    payload: MenuAssignRequest,
    context: AuthContext = Depends(require_perm("system:role:assign-menu")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).assign_menus(role_id, payload, context)
    return ok(result.model_dump(mode="json"), message="菜单权限已保存")


@router.put("/roles/{role_id}/data-permissions", summary="分配数据范围、资产域与资源数据权限")
async def assign_role_data_permissions(
    role_id: int,
    payload: DataPermissionsAssignRequest,
    context: AuthContext = Depends(require_perm("system:role:assign-data")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).assign_data_permissions(role_id, payload, context)
    return ok(result.model_dump(mode="json"), message="资源数据权限已保存")


@router.put("/roles/{role_id}/field-permissions", summary="分配字段权限")
async def assign_role_field_permissions(
    role_id: int,
    payload: FieldPermissionsAssignRequest,
    context: AuthContext = Depends(require_perm("system:role:assign-field")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).assign_field_permissions(role_id, payload, context)
    return ok(result.model_dump(mode="json"), message="字段权限已保存")


@router.put("/roles/{role_id}/users", summary="分配角色成员")
async def assign_role_users(
    role_id: int,
    payload: RoleUsersAssignRequest,
    context: AuthContext = Depends(require_perm("system:role:assign-user")),
    session: AsyncSession = Depends(get_db),
):
    result = await RoleService(session).assign_users(role_id, payload, context)
    return ok(result.model_dump(mode="json"), message="角色成员已更新")
