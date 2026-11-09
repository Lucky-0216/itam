from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.core.permissions import (
    DATA_RESOURCE_LABELS,
    DATA_SCOPE_LABELS,
    FIELD_CATALOG,
    SUPER_ADMIN_ROLE,
    DataScope,
    DomainScope,
)
from app.models import (
    AssetDomain,
    Dept,
    Menu,
    Role,
    RoleDataPermission,
    RoleDomain,
    RoleFieldPermission,
    User,
    role_depts,
    role_menus,
    user_roles,
)
from app.models.base import now_cst
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.rbac import (
    DataPermissionsAssignRequest,
    DataScopeOption,
    FieldPermissionItem,
    FieldPermissionsAssignRequest,
    MenuAdminNode,
    MenuAssignRequest,
    ResourceDataPermissionItem,
    ResourceOption,
    RoleBriefOut,
    RoleCreate,
    RoleDetailOut,
    RoleMemberOut,
    RoleMetaOut,
    RoleOut,
    RoleUpdate,
    RoleUserOptionOut,
    RoleUsersAssignRequest,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import is_self_only, scoped_dept_ids
from app.services.txn import commit_or_conflict


def _role_out(role: Role, user_count: int = 0, menu_count: int = 0) -> RoleOut:
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        data_scope=role.data_scope,
        data_scope_label=DATA_SCOPE_LABELS.get(role.data_scope, role.data_scope),
        domain_scope=role.domain_scope,
        asset_domains=sorted(grant.domain.code for grant in role.domain_grants),
        status=role.status,
        sort=role.sort,
        is_system=role.is_system,
        version=role.version,
        user_count=user_count,
        menu_count=menu_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _snapshot(role: Role, members: list[User] | None = None) -> dict[str, object]:
    data: dict[str, object] = {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "data_scope": role.data_scope,
        "domain_scope": role.domain_scope,
        "asset_domains": sorted(grant.domain.code for grant in role.domain_grants),
        "status": role.status,
        "sort": role.sort,
        "menu_ids": sorted(menu.id for menu in role.menus),
        "dept_ids": sorted(dept.id for dept in role.depts),
        "version": role.version,
    }
    if members is not None:
        data["user_ids"] = sorted(user.id for user in members)
    return data


class RoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.roles = RoleRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def list_roles(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        status: int | None = None,
    ) -> tuple[list[RoleOut], int]:
        rows, total = await self.roles.list_paginated(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
        )
        return [_role_out(role, user_count, menu_count) for role, user_count, menu_count in rows], total

    async def list_all(self) -> list[RoleBriefOut]:
        roles = await self.roles.list_enabled()
        return [
            RoleBriefOut(id=role.id, code=role.code, name=role.name, data_scope=role.data_scope)
            for role in roles
        ]

    async def user_options(
        self,
        context: AuthContext,
        *,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[RoleUserOptionOut]:
        allowed = await scoped_dept_ids(self.session, context)
        self_user_id = context.user.id if is_self_only(context) else None
        users, _ = await self.users.list_paginated(
            page=1,
            page_size=limit,
            keyword=keyword,
            dept_ids=allowed,
            status=1,
            self_user_id=self_user_id,
        )
        return [
            RoleUserOptionOut(
                id=user.id,
                username=user.username,
                real_name=user.real_name,
                dept_name=user.dept.name if user.dept else None,
                status=user.status,
            )
            for user in users
        ]

    async def meta(self, context: AuthContext) -> RoleMetaOut:
        domains = list(
            (
                await self.session.execute(
                    select(AssetDomain).order_by(AssetDomain.sort, AssetDomain.id)
                )
            ).scalars().all()
        )
        if context.allowed_domains() is not None:
            allowed = set(context.asset_domains)
            domains = [domain for domain in domains if domain.code in allowed]
        return RoleMetaOut(
            data_scopes=[
                DataScopeOption(value=value, label=label)
                for value, label in DATA_SCOPE_LABELS.items()
                if value != DataScope.ROLE
            ],
            field_catalog=FIELD_CATALOG,
            data_resources=[
                ResourceOption(value=value, label=label)
                for value, label in DATA_RESOURCE_LABELS.items()
            ],
            asset_domains=[
                DataScopeOption(value=domain.code, label=domain.name)
                for domain in domains
            ],
        )

    async def menu_tree(self) -> list[MenuAdminNode]:
        menus = list(
            (
                await self.session.execute(
                    select(Menu).order_by(Menu.sort, Menu.id)
                )
            )
            .scalars()
            .all()
        )
        nodes = {
            menu.id: MenuAdminNode(
                id=menu.id,
                parent_id=menu.parent_id,
                name=menu.name,
                type=menu.type,
                permission_code=menu.permission_code,
                path=menu.path,
                component=menu.component,
                icon=menu.icon,
                sort=menu.sort,
                visible=menu.visible,
                status=menu.status,
            )
            for menu in menus
        }
        roots: list[MenuAdminNode] = []
        for menu in menus:
            node = nodes[menu.id]
            if menu.parent_id and menu.parent_id in nodes:
                nodes[menu.parent_id].children.append(node)
            else:
                roots.append(node)
        self._sort_nodes(roots)
        return roots

    @staticmethod
    def _sort_nodes(nodes: list[MenuAdminNode]) -> None:
        nodes.sort(key=lambda item: (item.sort, item.id))
        for node in nodes:
            RoleService._sort_nodes(node.children)

    async def create(self, payload: RoleCreate, context: AuthContext) -> RoleDetailOut:
        if await self.roles.get_by_code(payload.code):
            raise ConflictError("角色编码已存在", code=40930)
        self._assert_scope_grantable(payload.data_scope, context)
        domains = await self._resolve_domains(
            payload.domain_scope, payload.asset_domains, context
        )

        role = Role(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            data_scope=payload.data_scope,
            domain_scope=payload.domain_scope,
            sort=payload.sort,
            status=payload.status,
            is_system=False,
            menus=[],
            depts=[],
            domain_grants=[],
        )
        self.session.add(role)
        await self.session.flush()
        role.domain_grants = [RoleDomain(domain=domain) for domain in domains]
        await self.session.flush()
        await self.audit.record(
            action="rbac.role.create",
            module="角色权限",
            summary=f"新增角色：{role.name}（{role.code}）",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            after=_snapshot(role),
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def detail(self, role_id: int, context: AuthContext) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        members = await self.roles.list_members(role_id)
        fields = await self.roles.list_field_permissions(role_id)
        base = _role_out(role, user_count=len(members), menu_count=len(role.menus))
        return RoleDetailOut(
            **base.model_dump(),
            menu_ids=sorted(menu.id for menu in role.menus),
            dept_ids=sorted(dept.id for dept in role.depts),
            field_permissions=[
                FieldPermissionItem(
                    resource=row.resource,
                    field=row.field,
                    can_view=row.can_view,
                    can_edit=row.can_edit,
                )
                for row in fields
            ],
            data_permissions=[
                ResourceDataPermissionItem(
                    resource=row.resource,
                    data_scope=row.data_scope,
                    dept_ids=row.dept_ids or [],
                )
                for row in sorted(
                    role.data_permissions, key=lambda item: item.resource
                )
            ],
            users=[
                RoleMemberOut(
                    id=user.id,
                    username=user.username,
                    real_name=user.real_name,
                    dept_name=user.dept.name if user.dept else None,
                    status=user.status,
                )
                for user in members
            ],
        )

    async def update(self, role_id: int, payload: RoleUpdate, context: AuthContext) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.version != payload.version:
            raise ConflictError("角色信息已被他人修改，请刷新后重试")
        self._assert_role_editable(role, context)
        if role.code == SUPER_ADMIN_ROLE and payload.status != 1:
            raise BizError("超级管理员角色不能被停用")
        if payload.status == 0:
            members = await self.roles.count_users(role.id)
            if members:
                raise BizError("该角色仍有关联用户，请先在「分配用户」中解除关联")

        before = _snapshot(role)
        role.name = payload.name
        role.description = payload.description
        role.sort = payload.sort
        role.status = payload.status
        await self.audit.record(
            action="rbac.role.update",
            module="角色权限",
            summary=f"编辑角色：{role.name}（{role.code}）",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            before=before,
            after=_snapshot(role),
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def delete(self, role_id: int, context: AuthContext) -> None:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.is_system:
            raise BizError("系统内置角色不允许删除")
        if await self.roles.count_users(role.id):
            raise BizError("该角色仍有关联用户，无法删除")

        before = _snapshot(role)
        await self.session.execute(delete(role_menus).where(role_menus.c.role_id == role.id))
        await self.session.execute(delete(role_depts).where(role_depts.c.role_id == role.id))
        await self.session.execute(
            delete(RoleFieldPermission).where(RoleFieldPermission.role_id == role.id)
        )
        await self.session.execute(
            delete(RoleDataPermission).where(RoleDataPermission.role_id == role.id)
        )
        await self.session.execute(delete(RoleDomain).where(RoleDomain.role_id == role.id))
        result = await self.session.execute(
            delete(Role)
            .where(Role.id == role.id, Role.version == role.version)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await self.session.rollback()
            raise ConflictError("角色信息已被他人修改，请刷新后重试")
        await self.audit.record(
            action="rbac.role.delete",
            module="角色权限",
            summary=f"删除角色：{role.name}（{role.code}）",
            actor=context.user,
            resource_type="role",
            resource_id=role_id,
            before=before,
        )
        await commit_or_conflict(self.session)

    async def assign_menus(
        self,
        role_id: int,
        payload: MenuAssignRequest,
        context: AuthContext,
    ) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.version != payload.version:
            raise ConflictError("角色权限已被他人修改，请刷新后重试")
        if role.code == SUPER_ADMIN_ROLE:
            raise BizError("超级管理员默认拥有全部权限，无需分配菜单")
        self._assert_role_editable(role, context)

        all_menus = list((await self.session.execute(select(Menu))).scalars().all())
        menu_map = {menu.id: menu for menu in all_menus}
        selected = []
        for menu_id in payload.menu_ids:
            menu = menu_map.get(menu_id)
            if menu is None:
                raise BizError(f"菜单不存在：{menu_id}")
            if menu.status != 1:
                raise BizError(f"菜单「{menu.name}」已停用，无法授权")
            selected.append(menu)

        expanded_ids = set(payload.menu_ids)
        for menu in selected:
            current = menu
            while current.parent_id:
                parent = menu_map.get(current.parent_id)
                if parent is None:
                    break
                expanded_ids.add(parent.id)
                current = parent

        target_menus = [menu_map[menu_id] for menu_id in sorted(expanded_ids)]
        self._assert_menus_grantable(target_menus, context)
        before = sorted(menu.id for menu in role.menus)
        role.menus = target_menus
        role.updated_at = now_cst()

        await self.audit.record(
            action="rbac.role.assign_menus",
            module="角色权限",
            summary=f"分配角色菜单：{role.name}",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            before={"menu_ids": before},
            after={"menu_ids": sorted(menu.id for menu in target_menus)},
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def assign_data_permissions(
        self,
        role_id: int,
        payload: DataPermissionsAssignRequest,
        context: AuthContext,
    ) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.version != payload.version:
            raise ConflictError("角色权限已被他人修改，请刷新后重试")
        if role.code == SUPER_ADMIN_ROLE:
            raise BizError("超级管理员固定拥有全部数据权限，无需分配")
        self._assert_role_editable(role, context)
        self._assert_scope_grantable(payload.data_scope, context)
        for item in payload.permissions:
            self._assert_scope_grantable(item.data_scope, context)
        domains = await self._resolve_domains(
            payload.domain_scope, payload.asset_domains, context
        )

        if payload.data_scope == DataScope.CUSTOM and not payload.dept_ids:
            raise BizError("全局自定义数据范围至少需要选择一个部门")
        for item in payload.permissions:
            if item.data_scope == DataScope.CUSTOM and not item.dept_ids:
                raise BizError(f"{DATA_RESOURCE_LABELS[item.resource]}需要选择自定义部门")

        all_dept_ids = set(payload.dept_ids)
        for item in payload.permissions:
            all_dept_ids.update(item.dept_ids)
        dept_rows = await self._validated_depts(all_dept_ids, context)
        global_depts = [dept for dept in dept_rows if dept.id in payload.dept_ids]

        before = _snapshot(role)
        before["resource_permissions"] = [
            {
                "resource": row.resource,
                "data_scope": row.data_scope,
                "dept_ids": row.dept_ids or [],
            }
            for row in role.data_permissions
        ]

        role.data_scope = payload.data_scope
        role.depts = global_depts if payload.data_scope == DataScope.CUSTOM else []
        role.domain_scope = payload.domain_scope
        role.domain_grants.clear()
        role.data_permissions.clear()
        await self.session.flush()
        role.domain_grants = [RoleDomain(domain=domain) for domain in domains]
        role.data_permissions = [
            RoleDataPermission(
                role_id=role.id,
                resource=item.resource,
                data_scope=item.data_scope,
                dept_ids=item.dept_ids if item.data_scope == DataScope.CUSTOM else [],
            )
            for item in payload.permissions
        ]
        role.updated_at = now_cst()

        await self.audit.record(
            action="rbac.role.assign_data",
            module="角色权限",
            summary=f"分配角色数据权限与资产域：{role.name}",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            before=before,
            after={
                "data_scope": payload.data_scope,
                "dept_ids": payload.dept_ids,
                "domain_scope": payload.domain_scope,
                "asset_domains": payload.asset_domains,
                "resource_permissions": [
                    item.model_dump() for item in payload.permissions
                ],
            },
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def assign_field_permissions(
        self,
        role_id: int,
        payload: FieldPermissionsAssignRequest,
        context: AuthContext,
    ) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.version != payload.version:
            raise ConflictError("角色权限已被他人修改，请刷新后重试")
        if role.code == SUPER_ADMIN_ROLE:
            raise BizError("超级管理员默认拥有全部字段权限，无需分配")
        self._assert_role_editable(role, context)
        self._validate_field_catalog(payload.permissions)

        existing = await self.roles.list_field_permissions(role.id)
        before = [
            {
                "resource": row.resource,
                "field": row.field,
                "can_view": row.can_view,
                "can_edit": row.can_edit,
            }
            for row in existing
        ]
        await self.session.execute(
            delete(RoleFieldPermission).where(RoleFieldPermission.role_id == role.id)
        )
        for item in payload.permissions:
            self.session.add(
                RoleFieldPermission(
                    role_id=role.id,
                    resource=item.resource,
                    field=item.field,
                    can_view=item.can_view,
                    can_edit=item.can_edit,
                )
            )
        role.updated_at = now_cst()

        await self.audit.record(
            action="rbac.role.assign_fields",
            module="角色权限",
            summary=f"分配角色字段权限：{role.name}",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            before=before,
            after=[item.model_dump() for item in payload.permissions],
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def assign_users(
        self,
        role_id: int,
        payload: RoleUsersAssignRequest,
        context: AuthContext,
    ) -> RoleDetailOut:
        role = await self.roles.get_with_relations(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        if role.version != payload.version:
            raise ConflictError("角色成员已被他人修改，请刷新后重试")
        if role.code == SUPER_ADMIN_ROLE and not context.is_superuser:
            raise PermissionDenied("只有超级管理员可以调整超级管理员成员")
        if role.status != 1:
            raise BizError("角色已停用，请先启用后再分配用户")

        members = await self.roles.list_members(role.id)
        current_ids = {user.id for user in members}
        target_users = await self.users.list_by_ids(payload.user_ids)
        if len(target_users) != len(set(payload.user_ids)):
            raise BizError("包含不存在或已删除的用户")
        target_ids = {user.id for user in target_users}

        if not context.is_superuser:
            self._assert_menus_grantable(list(role.menus), context)
            self._assert_role_domains_grantable(role, context)
            if role.data_scope == DataScope.ALL and context.data_scope != DataScope.ALL:
                raise PermissionDenied("不能分配超出自身数据范围的角色")
            allowed = await scoped_dept_ids(self.session, context)
            if allowed is not None:
                for user in target_users:
                    if user.id not in current_ids and user.dept_id not in allowed:
                        raise PermissionDenied("存在不在当前数据范围内的用户")

        if role.code == SUPER_ADMIN_ROLE:
            current_active = {user.id for user in members if user.status == 1}
            target_active = current_active & target_ids
            total_active = await self.users.count_active_super_admins()
            if total_active - (len(current_active) - len(target_active)) <= 0:
                raise BizError("系统至少需要保留一名启用的超级管理员", code=40020)

        removed_ids = current_ids - target_ids
        added_ids = target_ids - current_ids
        for user_id in removed_ids:
            await self.session.execute(
                delete(user_roles).where(
                    user_roles.c.user_id == user_id,
                    user_roles.c.role_id == role.id,
                )
            )
        for user_id in added_ids:
            await self.session.execute(
                insert(user_roles).values(user_id=user_id, role_id=role.id)
            )
        role.updated_at = now_cst()

        before_users = sorted(user.username for user in members)
        after_users = sorted(user.username for user in target_users)
        await self.audit.record(
            action="rbac.role.assign_users",
            module="角色权限",
            summary=f"调整角色成员：{role.name}",
            actor=context.user,
            resource_type="role",
            resource_id=role.id,
            before={"users": before_users},
            after={"users": after_users},
        )
        await commit_or_conflict(self.session)
        return await self.detail(role.id, context)

    async def _resolve_domains(
        self,
        domain_scope: str,
        codes: list[str],
        context: AuthContext,
    ) -> list[AssetDomain]:
        if not context.is_superuser and context.domain_scope != DomainScope.ALL:
            if domain_scope == DomainScope.ALL:
                raise PermissionDenied("不能授予超出自身资产域范围的全部域权限")
            if not set(codes).issubset(context.asset_domains):
                raise PermissionDenied("不能授予自身未拥有的资产域")
        if domain_scope == DomainScope.ALL:
            return []
        if not codes:
            return []
        domains = list(
            (
                await self.session.execute(
                    select(AssetDomain).where(AssetDomain.code.in_(codes))
                )
            ).scalars().all()
        )
        if len(domains) != len(set(codes)):
            raise BizError("包含不存在的资产域")
        return sorted(domains, key=lambda domain: (domain.sort, domain.id))

    async def _validated_depts(
        self, dept_ids: set[int], context: AuthContext
    ) -> list[Dept]:
        if not dept_ids:
            return []
        rows = list(
            (
                await self.session.execute(select(Dept).where(Dept.id.in_(dept_ids)))
            ).scalars().all()
        )
        if len(rows) != len(dept_ids):
            raise BizError("包含不存在的部门")
        allowed = await scoped_dept_ids(self.session, context)
        if allowed is not None and not dept_ids.issubset(allowed):
            raise PermissionDenied("不能将数据范围授权到自身数据范围之外")
        return rows

    @staticmethod
    def _assert_role_domains_grantable(role: Role, context: AuthContext) -> None:
        if context.is_superuser or context.domain_scope == DomainScope.ALL:
            return
        if role.domain_scope == DomainScope.ALL:
            raise PermissionDenied("不能分配超出自身资产域范围的角色")
        role_domains = {grant.domain.code for grant in role.domain_grants}
        if not role_domains.issubset(context.asset_domains):
            raise PermissionDenied("不能分配超出自身资产域范围的角色")

    def _assert_role_editable(self, role: Role, context: AuthContext) -> None:
        if role.is_system and not context.is_superuser:
            raise PermissionDenied("系统内置角色只有超级管理员可以修改")

    def _assert_scope_grantable(self, data_scope: str, context: AuthContext) -> None:
        if not context.is_superuser and data_scope == DataScope.ALL:
            raise PermissionDenied("只有超级管理员可以授予全部数据范围")

    def _assert_menus_grantable(self, menus: list[Menu], context: AuthContext) -> None:
        if context.is_superuser:
            return
        codes = {
            menu.permission_code
            for menu in menus
            if menu.status == 1 and menu.permission_code
        }
        if not codes.issubset(context.permissions):
            raise PermissionDenied("不能授予超出自身权限范围的菜单或操作")

    @staticmethod
    def _validate_field_catalog(permissions: list[FieldPermissionItem]) -> None:
        catalog = {
            resource: {item["field"] for item in fields}
            for resource, fields in FIELD_CATALOG.items()
        }
        seen: set[tuple[str, str]] = set()
        for item in permissions:
            if item.resource not in catalog:
                raise BizError(f"未知字段资源：{item.resource}")
            if item.field not in catalog[item.resource]:
                raise BizError(f"字段不在授权目录中：{item.field}")
            key = (item.resource, item.field)
            if key in seen:
                raise BizError("字段权限存在重复项")
            seen.add(key)
