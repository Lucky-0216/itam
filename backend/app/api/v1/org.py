from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.org import (
    DeptCreate,
    DeptUpdate,
    OrgSyncPolicyUpdate,
    ResetPasswordRequest,
    UserCreate,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.dept_service import DeptService
from app.services.org_policy_service import OrgSyncPolicyService
from app.services.permission_service import AuthContext
from app.services.user_admin_service import UserAdminService

router = APIRouter(tags=["组织与人员"])

_SOURCE_PATTERN = "^(local|ldap|dingtalk)$"


@router.get("/departments/tree", summary="部门树")
async def department_tree(
    source: str | None = Query(None, pattern=_SOURCE_PATTERN),
    context: AuthContext = Depends(require_perm("system:org:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await DeptService(session).tree(context, source=source)
    return ok([item.model_dump(mode="json") for item in result])


@router.post("/departments", summary="新增部门")
async def create_department(
    payload: DeptCreate,
    context: AuthContext = Depends(require_perm("system:dept:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await DeptService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="部门创建成功")


@router.put("/departments/{dept_id}", summary="编辑部门")
async def update_department(
    dept_id: int,
    payload: DeptUpdate,
    context: AuthContext = Depends(require_perm("system:dept:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await DeptService(session).update(dept_id, payload, context)
    return ok(result.model_dump(mode="json"), message="部门更新成功")


@router.delete("/departments/{dept_id}", summary="删除部门")
async def delete_department(
    dept_id: int,
    context: AuthContext = Depends(require_perm("system:dept:delete")),
    session: AsyncSession = Depends(get_db),
):
    await DeptService(session).delete(dept_id, context)
    return ok(None, message="部门已删除")


@router.get("/users", summary="用户列表（分页、部门与数据范围过滤）")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    dept_id: int | None = Query(None, ge=1),
    include_child: bool = True,
    status: int | None = Query(None, ge=0, le=1),
    role_id: int | None = Query(None, ge=1),
    source: str | None = Query(None, pattern=_SOURCE_PATTERN),
    context: AuthContext = Depends(require_perm("system:org:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await UserAdminService(session).list_users(
        context,
        page=page,
        page_size=page_size,
        keyword=keyword,
        dept_id=dept_id,
        include_child=include_child,
        status=status,
        role_id=role_id,
        source=source,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/users/{user_id}", summary="用户详情")
async def get_user(
    user_id: int,
    context: AuthContext = Depends(require_perm("system:org:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await UserAdminService(session).get_user(user_id, context)
    return ok(result.model_dump(mode="json"))


@router.post("/users", summary="新增用户")
async def create_user(
    payload: UserCreate,
    context: AuthContext = Depends(require_perm("system:user:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await UserAdminService(session).create_user(payload, context)
    return ok(result.model_dump(mode="json"), message="用户创建成功，首次登录需修改密码")


@router.put("/users/{user_id}", summary="编辑用户")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    context: AuthContext = Depends(require_perm("system:user:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await UserAdminService(session).update_user(user_id, payload, context)
    return ok(result.model_dump(mode="json"), message="用户更新成功")


@router.put("/users/{user_id}/status", summary="启用或停用用户")
async def set_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    context: AuthContext = Depends(require_perm("system:user:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await UserAdminService(session).set_status(user_id, payload, context)
    return ok(result.model_dump(mode="json"), message="用户状态已更新")


@router.post("/users/{user_id}/reset-password", summary="重置用户密码")
async def reset_user_password(
    user_id: int,
    payload: ResetPasswordRequest,
    context: AuthContext = Depends(require_perm("system:user:reset-password")),
    session: AsyncSession = Depends(get_db),
):
    await UserAdminService(session).reset_password(user_id, payload, context)
    return ok(None, message="密码已重置，目标用户所有登录状态已失效")


@router.delete("/users/{user_id}", summary="删除用户（软删除）")
async def delete_user(
    user_id: int,
    context: AuthContext = Depends(require_perm("system:user:delete")),
    session: AsyncSession = Depends(get_db),
):
    await UserAdminService(session).delete_user(user_id, context)
    return ok(None, message="用户已删除（历史记录保留）")


@router.get("/sync-policy", summary="组织同步策略")
async def get_sync_policy(
    context: AuthContext = Depends(require_perm("system:org-sync-policy:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await OrgSyncPolicyService(session).get_policy_out()
    return ok(result.model_dump(mode="json"))


@router.put("/sync-policy", summary="更新组织同步策略")
async def update_sync_policy(
    payload: OrgSyncPolicyUpdate,
    context: AuthContext = Depends(require_perm("system:org-sync-policy:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await OrgSyncPolicyService(session).save_policy(payload, context.user)
    return ok(result.model_dump(mode="json"), message="组织同步策略已更新")
