from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.core.permissions import DataScope, SUPER_ADMIN_ROLE
from app.core.security import hash_password
from app.models import Dept, Role, User
from app.models.base import now_cst
from app.repositories.dept_repo import DeptRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.org import (
    ResetPasswordRequest,
    UserCreate,
    UserDetailOut,
    UserOut,
    UserPageOut,
    UserRoleOut,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import is_self_only, scoped_dept_ids
from app.services.txn import commit_or_conflict


def _role_briefs(roles: list[Role]) -> list[UserRoleOut]:
    ordered = sorted(roles, key=lambda role: (role.sort, role.id))
    return [
        UserRoleOut(id=role.id, code=role.code, name=role.name, data_scope=role.data_scope)
        for role in ordered
    ]


async def _dept_path_lookup(session: AsyncSession) -> dict[int, str]:
    depts = list((await session.execute(select(Dept))).scalars().all())
    by_id = {dept.id: dept for dept in depts}
    cache: dict[int, str] = {}

    def build(dept: Dept) -> str:
        cached = cache.get(dept.id)
        if cached is not None:
            return cached
        names: list[str] = []
        current: Dept | None = dept
        seen: set[int] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        path = "\\".join(reversed(names))
        cache[dept.id] = path
        return path

    return {dept.id: build(dept) for dept in depts}


def _serialize(user: User, dept_paths: dict[int, str] | None = None) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        employee_no=user.employee_no,
        email=user.email,
        phone=user.phone,
        avatar=user.avatar,
        dept_id=user.dept_id,
        dept_name=user.dept.name if user.dept else None,
        dept_path=dept_paths.get(user.dept_id) if dept_paths and user.dept_id else None,
        position=user.position,
        status=user.status,
        source=user.source,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        version=user.version,
        roles=_role_briefs(list(user.roles)),
    )


def _serialize_detail(
    user: User, dept_paths: dict[int, str] | None = None
) -> UserDetailOut:
    base = _serialize(user, dept_paths)
    return UserDetailOut(**base.model_dump(), remark=user.remark, token_version=user.token_version)


def _snapshot(user: User, roles: list[Role] | None = None) -> dict[str, object]:
    role_list = list(user.roles) if roles is None else roles
    return {
        "username": user.username,
        "real_name": user.real_name,
        "employee_no": user.employee_no,
        "email": user.email,
        "phone": user.phone,
        "dept_id": user.dept_id,
        "position": user.position,
        "status": user.status,
        "remark": user.remark,
        "role_codes": sorted(role.code for role in role_list),
        "version": user.version,
    }


class UserAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)
        self.depts = DeptRepository(session)
        self.audit = AuditService(session)

    async def list_users(
        self,
        context: AuthContext,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        dept_id: int | None = None,
        include_child: bool = True,
        status: int | None = None,
        role_id: int | None = None,
    ) -> UserPageOut:
        allowed = await scoped_dept_ids(self.session, context)
        dept_ids = allowed
        if dept_id is not None:
            subtree_ids = await self._dept_subtree_ids(dept_id, include_child)
            dept_ids = subtree_ids if allowed is None else (subtree_ids & allowed)

        users, total = await self.users.list_paginated(
            page=page,
            page_size=page_size,
            keyword=keyword,
            dept_ids=dept_ids,
            status=status,
            role_id=role_id,
            self_user_id=context.user.id if is_self_only(context) else None,
        )
        dept_paths = await _dept_path_lookup(self.session)
        return UserPageOut(
            items=[_serialize(user, dept_paths) for user in users],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _dept_subtree_ids(self, dept_id: int, include_child: bool) -> set[int]:
        depts = await self.depts.list_all()
        target = next((dept for dept in depts if dept.id == dept_id), None)
        if target is None:
            return set()
        if not include_child:
            return {target.id}
        return {dept.id for dept in depts if dept.path.startswith(target.path)}

    async def get_user(self, user_id: int, context: AuthContext) -> UserDetailOut:
        user = await self.users.get_detail(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        await self._assert_visible(user, context)
        return _serialize_detail(user, await _dept_path_lookup(self.session))

    async def create_user(self, payload: UserCreate, context: AuthContext) -> UserDetailOut:
        dept = await self._assert_dept_active(payload.dept_id)
        roles = await self._load_roles(payload.role_ids)
        self._assert_roles_grantable(roles, context)

        conflict = await self.users.find_conflict(
            username=payload.username,
            employee_no=payload.employee_no,
            email=payload.email,
        )
        if conflict is not None:
            raise ConflictError("用户名、工号或邮箱已被使用（已删除账号同样占用唯一标识）", code=40920)

        user = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
            real_name=payload.real_name,
            employee_no=payload.employee_no,
            email=payload.email,
            phone=payload.phone,
            dept=dept,
            position=payload.position,
            status=payload.status,
            must_change_password=True,
            remark=payload.remark,
        )
        user.roles = roles
        self.session.add(user)
        await self.session.flush()

        await self.audit.record(
            action="org.user.create",
            module="人员管理",
            summary=f"新增用户：{user.real_name}（{user.username}）",
            actor=context.user,
            resource_type="user",
            resource_id=user.id,
            after=_snapshot(user, roles),
        )
        await commit_or_conflict(self.session)
        reloaded = await self.users.get_detail(user.id)
        return _serialize_detail(reloaded or user, await _dept_path_lookup(self.session))

    async def update_user(
        self,
        user_id: int,
        payload: UserUpdate,
        context: AuthContext,
    ) -> UserDetailOut:
        user = await self.users.get_detail(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.version != payload.version:
            raise ConflictError("用户信息已被他人修改，请刷新后重试")
        await self._assert_manage_target(user, context)
        await self._assert_visible(user, context)

        if user.id == context.user.id and payload.role_ids is not None:
            current_role_ids = {role.id for role in user.roles}
            if set(payload.role_ids) != current_role_ids:
                raise BizError("不能修改自己的角色，请联系其他管理员操作")

        dept = await self._assert_dept_assignment(user, payload.dept_id)
        conflict = await self.users.find_conflict(
            username=user.username,
            employee_no=payload.employee_no,
            email=payload.email,
            exclude_id=user.id,
        )
        if conflict is not None:
            raise ConflictError("工号或邮箱已被其他账号使用", code=40920)

        before = _snapshot(user)
        new_roles: list[Role] | None = None
        if payload.role_ids is not None:
            new_roles = await self._load_roles(payload.role_ids)
            self._assert_roles_grantable(new_roles, context)
            await self._assert_super_admin_retained(user, new_roles)

        user.real_name = payload.real_name
        user.dept = dept
        user.position = payload.position
        user.employee_no = payload.employee_no
        user.email = payload.email
        user.phone = payload.phone
        user.remark = payload.remark

        if new_roles is not None:
            current_role_ids = {role.id for role in user.roles}
            if {role.id for role in new_roles} != current_role_ids:
                user.roles = new_roles
                user.updated_at = now_cst()

        await self.audit.record(
            action="org.user.update",
            module="人员管理",
            summary=f"编辑用户：{user.real_name}（{user.username}）",
            actor=context.user,
            resource_type="user",
            resource_id=user.id,
            before=before,
            after=_snapshot(user, new_roles if new_roles is not None else list(user.roles)),
        )
        await commit_or_conflict(self.session)
        reloaded = await self.users.get_detail(user.id)
        return _serialize_detail(reloaded or user, await _dept_path_lookup(self.session))

    async def set_status(
        self,
        user_id: int,
        payload: UserStatusUpdate,
        context: AuthContext,
    ) -> UserDetailOut:
        user = await self.users.get_detail(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.version != payload.version:
            raise ConflictError("用户信息已被他人修改，请刷新后重试")
        await self._assert_manage_target(user, context)
        await self._assert_visible(user, context)
        if user.id == context.user.id and payload.status == 0:
            raise BizError("不能停用当前登录账号")

        if payload.status == 0 and self._is_super_admin(user):
            await self._assert_last_super_admin(user)

        before = _snapshot(user)
        user.status = payload.status
        if payload.status == 0:
            user.token_version += 1

        await self.audit.record(
            action="org.user.status",
            module="人员管理",
            summary=f"{'启用' if payload.status == 1 else '停用'}用户：{user.username}",
            actor=context.user,
            resource_type="user",
            resource_id=user.id,
            before=before,
            after=_snapshot(user),
        )
        await commit_or_conflict(self.session)
        return _serialize_detail(user, await _dept_path_lookup(self.session))

    async def reset_password(
        self,
        user_id: int,
        payload: ResetPasswordRequest,
        context: AuthContext,
    ) -> None:
        user = await self.users.get_detail(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.version != payload.version:
            raise ConflictError("用户信息已被他人修改，请刷新后重试")
        if user.id == context.user.id:
            raise BizError("请通过「修改密码」功能更新自己的登录密码")
        if user.source == "ldap":
            raise BizError("域控账号的密码由 AD 域管理，无法在系统中重置")
        await self._assert_manage_target(user, context)
        await self._assert_visible(user, context)

        before = {"must_change_password": user.must_change_password, "token_version": user.token_version}
        user.password_hash = hash_password(payload.new_password)
        user.must_change_password = True
        user.token_version += 1
        await self.audit.record(
            action="org.user.reset_password",
            module="人员管理",
            summary=f"重置用户密码：{user.username}，历史登录状态已失效",
            actor=context.user,
            resource_type="user",
            resource_id=user.id,
            before=before,
            after={"must_change_password": True, "token_version": user.token_version},
        )
        await commit_or_conflict(self.session)

    async def delete_user(self, user_id: int, context: AuthContext) -> None:
        user = await self.users.get_detail(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.id == context.user.id:
            raise BizError("不能删除当前登录账号")
        await self._assert_manage_target(user, context)
        await self._assert_visible(user, context)
        if self._is_super_admin(user):
            await self._assert_last_super_admin(user)

        before = _snapshot(user)
        user.deleted_at = now_cst()
        user.status = 0
        user.token_version += 1
        await self.audit.record(
            action="org.user.delete",
            module="人员管理",
            summary=f"删除用户（软删除）：{user.username}",
            actor=context.user,
            resource_type="user",
            resource_id=user.id,
            before=before,
            after={"deleted_at": user.deleted_at},
        )
        await commit_or_conflict(self.session)

    async def _assert_dept_active(self, dept_id: int) -> Dept:
        dept = await self.depts.get(dept_id)
        if dept is None:
            raise NotFoundError("所属部门不存在")
        if dept.status != 1:
            raise BizError("所属部门已停用，无法分配用户")
        return dept

    async def _assert_dept_assignment(self, user: User, dept_id: int) -> Dept:
        dept = await self.depts.get(dept_id)
        if dept is None:
            raise NotFoundError("所属部门不存在")
        if dept.status != 1 and dept.id != user.dept_id:
            raise BizError("目标部门已停用，无法调入用户")
        return dept

    async def _load_roles(self, role_ids: list[int]) -> list[Role]:
        roles = await self.roles.list_by_ids(role_ids)
        if len(roles) != len(set(role_ids)):
            raise BizError("包含不存在的角色")
        if any(role.status != 1 for role in roles):
            raise BizError("包含已停用的角色")
        return roles

    @staticmethod
    def _is_super_admin(user: User) -> bool:
        return any(role.code == SUPER_ADMIN_ROLE for role in user.roles)

    def _assert_roles_grantable(self, roles: list[Role], context: AuthContext) -> None:
        if context.is_superuser:
            return
        for role in roles:
            if role.code == SUPER_ADMIN_ROLE:
                raise PermissionDenied("只有超级管理员可以授予超级管理员角色")
            role_permissions = {
                menu.permission_code
                for menu in role.menus
                if menu.status == 1 and menu.permission_code
            }
            if not role_permissions.issubset(context.permissions):
                raise PermissionDenied(f"角色「{role.name}」超出当前账号可授予的权限范围")
            if role.data_scope == DataScope.ALL and context.data_scope != DataScope.ALL:
                raise PermissionDenied(f"角色「{role.name}」的数据范围超出当前账号")

    async def _assert_manage_target(self, user: User, context: AuthContext) -> None:
        if self._is_super_admin(user) and not context.is_superuser:
            raise PermissionDenied("只有超级管理员可以修改超级管理员账号")

    async def _assert_visible(self, user: User, context: AuthContext) -> None:
        allowed = await scoped_dept_ids(self.session, context)
        if allowed is None:
            return
        if is_self_only(context):
            if user.id != context.user.id:
                raise PermissionDenied("无权访问该用户")
            return
        if user.dept_id not in allowed:
            raise PermissionDenied("该用户不在当前数据范围内")

    async def _assert_super_admin_retained(self, user: User, new_roles: list[Role]) -> None:
        if not self._is_super_admin(user):
            return
        if any(role.code == SUPER_ADMIN_ROLE for role in new_roles):
            return
        await self._assert_last_super_admin(user)

    async def _assert_last_super_admin(self, user: User) -> None:
        remaining = await self.users.count_active_super_admins(exclude_user_id=user.id)
        if remaining == 0:
            raise BizError("系统至少需要保留一名启用的超级管理员", code=40020)
