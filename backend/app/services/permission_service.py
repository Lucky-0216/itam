from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    DATA_RESOURCE_LABELS,
    DATA_SCOPE_LABELS,
    FIELD_CATALOG,
    SCOPE_PRIORITY,
    SUPER_ADMIN_ROLE,
    DataScope,
    DomainScope,
)
from app.models import AssetDomain, Menu, Role, RoleFieldPermission, User
from app.repositories.menu_repo import MenuRepository
from app.schemas.auth import (
    CurrentUserOut,
    FieldPermissionOut,
    MenuNode,
    RoleBrief,
    UserProfile,
)


@dataclass(slots=True)
class AuthContext:
    user: User
    roles: list[Role]
    permissions: set[str]
    is_superuser: bool
    data_scope: str
    custom_dept_ids: list[int]
    field_permissions: dict[str, dict[str, FieldPermissionOut]]
    menus: list[MenuNode]
    access_jti: str
    access_exp: int
    resource_scopes: dict[str, str]
    resource_custom_dept_ids: dict[str, tuple[int, ...]]
    domain_scope: str
    asset_domains: tuple[str, ...]

    def has_permission(self, code: str) -> bool:
        return self.is_superuser or code in self.permissions

    def effective_scope(self, resource: str) -> str:
        return self.resource_scopes.get(resource, self.data_scope)

    def allowed_domains(self, resource: str | None = None) -> tuple[str, ...] | None:
        """None 仅表示角色被显式授予全部域；空元组表示无任何域权限。"""
        if self.domain_scope == DomainScope.ALL:
            return None
        return self.asset_domains

    def allowed_custom_dept_ids(self, resource: str) -> tuple[int, ...]:
        return self.resource_custom_dept_ids.get(resource, tuple(self.custom_dept_ids))

    def can_view_field(self, resource: str, field_name: str) -> bool:
        if self.is_superuser:
            return True
        permission = self.field_permissions.get(resource, {}).get(field_name)
        return permission.can_view if permission else True

    def can_edit_field(self, resource: str, field_name: str) -> bool:
        if self.is_superuser:
            return True
        permission = self.field_permissions.get(resource, {}).get(field_name)
        return permission.can_edit if permission else True

    def to_profile(self) -> CurrentUserOut:
        user = self.user
        return CurrentUserOut(
            user=UserProfile(
                id=user.id,
                username=user.username,
                real_name=user.real_name,
                employee_no=user.employee_no,
                email=user.email,
                phone=user.phone,
                avatar=user.avatar,
                dept_id=user.dept_id,
                dept_name=user.dept.name if user.dept else None,
                position=user.position,
                status=user.status,
                source=user.source,
                must_change_password=user.must_change_password,
                last_login_at=user.last_login_at,
            ),
            roles=[RoleBrief.model_validate(role) for role in self.roles],
            permissions=sorted(self.permissions),
            data_scope=self.data_scope,
            data_scope_label=DATA_SCOPE_LABELS.get(self.data_scope, self.data_scope),
            custom_dept_ids=self.custom_dept_ids,
            menus=self.menus,
            field_permissions=self.field_permissions,
            domain_scope=self.domain_scope,
            asset_domains=list(self.asset_domains),
            resource_scopes=self.resource_scopes,
        )


class PermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_context(
        self,
        user: User,
        *,
        access_jti: str,
        access_exp: int,
    ) -> AuthContext:
        roles = [role for role in user.roles if role.status == 1]
        is_superuser = any(role.code == SUPER_ADMIN_ROLE for role in roles)
        menu_repo = MenuRepository(self.session)
        all_menus = await menu_repo.list_all_enabled()

        if is_superuser:
            allowed_menu_ids: set[int] | None = None
            permissions = {
                menu.permission_code for menu in all_menus if menu.permission_code
            }
        else:
            allowed_menu_ids = {menu.id for role in roles for menu in role.menus}
            permissions = {
                menu.permission_code
                for role in roles
                for menu in role.menus
                if menu.status == 1 and menu.permission_code
            }

        menus = self._build_menu_tree(all_menus, allowed_menu_ids)
        data_scope = self._resolve_data_scope(roles, is_superuser)
        custom_dept_ids = sorted(
            {
                dept.id
                for role in roles
                if role.data_scope == DataScope.CUSTOM
                for dept in role.depts
            }
        )
        field_permissions = await self._build_field_permissions(roles, is_superuser)
        resource_scopes, resource_custom_dept_ids = self._resolve_resource_permissions(
            roles,
            is_superuser,
            data_scope,
            custom_dept_ids,
        )
        all_domains = list(
            (
                await self.session.execute(
                    select(AssetDomain).order_by(AssetDomain.sort, AssetDomain.id)
                )
            ).scalars().all()
        )
        domain_scope, asset_domains = self._resolve_domains(
            roles, is_superuser, [domain.code for domain in all_domains]
        )

        return AuthContext(
            user=user,
            roles=roles,
            permissions=permissions,
            is_superuser=is_superuser,
            data_scope=data_scope,
            custom_dept_ids=custom_dept_ids,
            field_permissions=field_permissions,
            menus=menus,
            access_jti=access_jti,
            access_exp=access_exp,
            resource_scopes=resource_scopes,
            resource_custom_dept_ids=resource_custom_dept_ids,
            domain_scope=domain_scope,
            asset_domains=asset_domains,
        )

    @staticmethod
    def _resolve_domains(
        roles: list[Role],
        is_superuser: bool,
        all_domain_codes: list[str],
    ) -> tuple[str, tuple[str, ...]]:
        if is_superuser or any(role.domain_scope == DomainScope.ALL for role in roles):
            return DomainScope.ALL, tuple(all_domain_codes)
        domains = sorted(
            {
                grant.domain.code
                for role in roles
                for grant in role.domain_grants
            }
        )
        return DomainScope.CUSTOM, tuple(domains)

    @staticmethod
    def _resolve_resource_permissions(
        roles: list[Role],
        is_superuser: bool,
        data_scope: str,
        custom_dept_ids: list[int],
    ) -> tuple[dict[str, str], dict[str, tuple[int, ...]]]:
        """资源级范围：未配置的资源回落全局范围，多角色取最宽范围。"""
        scopes: dict[str, str] = {}
        custom_ids: dict[str, tuple[int, ...]] = {}
        for resource in DATA_RESOURCE_LABELS:
            if is_superuser:
                scopes[resource] = DataScope.ALL
                custom_ids[resource] = ()
                continue
            role_scopes: list[str] = []
            role_custom_ids: set[int] = set()
            for role in roles:
                config = next(
                    (
                        item
                        for item in role.data_permissions
                        if item.resource == resource
                    ),
                    None,
                )
                role_scope = config.data_scope if config else role.data_scope
                if role_scope == DataScope.ROLE:
                    role_scope = DataScope.SELF
                role_scopes.append(role_scope)
                if role_scope == DataScope.CUSTOM:
                    if config is not None:
                        role_custom_ids.update(config.dept_ids or [])
                    else:
                        role_custom_ids.update(dept.id for dept in role.depts)
            scope = data_scope
            if role_scopes:
                for candidate in SCOPE_PRIORITY:
                    if candidate == DataScope.ROLE:
                        continue
                    if candidate in role_scopes:
                        scope = candidate
                        break
            scopes[resource] = scope
            custom_ids[resource] = (
                tuple(sorted(role_custom_ids)) if scope == DataScope.CUSTOM else ()
            )
        return scopes, custom_ids

    @staticmethod
    def _resolve_data_scope(roles: list[Role], is_superuser: bool) -> str:
        if is_superuser:
            return DataScope.ALL
        scope_set = {role.data_scope for role in roles}
        for scope in SCOPE_PRIORITY:
            if scope == DataScope.ROLE:
                # 全局范围不支持按创建人限定，避免被误当作「不限部门」
                continue
            if scope in scope_set:
                return scope
        return DataScope.SELF

    @staticmethod
    def _build_menu_tree(
        all_menus: list[Menu],
        allowed_menu_ids: set[int] | None,
    ) -> list[MenuNode]:
        if not all_menus:
            return []

        menu_map = {menu.id: menu for menu in all_menus}
        if allowed_menu_ids is None:
            included_ids = set(menu_map)
        else:
            included_ids: set[int] = set()
            for menu_id in allowed_menu_ids:
                current = menu_map.get(menu_id)
                while current is not None:
                    included_ids.add(current.id)
                    current = menu_map.get(current.parent_id) if current.parent_id else None

        visible_menus = [
            menu
            for menu in all_menus
            if menu.visible and menu.type in ("DIR", "MENU") and menu.id in included_ids
        ]
        visible_menus.sort(key=lambda menu: (menu.sort, menu.id))

        node_map: dict[int, MenuNode] = {}
        for menu in visible_menus:
            node_map[menu.id] = MenuNode(
                id=menu.id,
                parent_id=menu.parent_id,
                name=menu.name,
                type=menu.type,
                path=menu.path,
                component=menu.component,
                icon=menu.icon,
                sort=menu.sort,
                permission_code=menu.permission_code,
            )

        roots: list[MenuNode] = []
        for menu in visible_menus:
            node = node_map[menu.id]
            if menu.parent_id and menu.parent_id in node_map:
                node_map[menu.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    async def _build_field_permissions(
        self,
        roles: list[Role],
        is_superuser: bool,
    ) -> dict[str, dict[str, FieldPermissionOut]]:
        if is_superuser:
            return {}

        role_ids = [role.id for role in roles]
        rows: list[RoleFieldPermission] = []
        if role_ids:
            stmt = select(RoleFieldPermission).where(RoleFieldPermission.role_id.in_(role_ids))
            rows = list((await self.session.execute(stmt)).scalars().all())

        configured = {
            (row.role_id, row.resource, row.field): row
            for row in rows
        }

        result: dict[str, dict[str, FieldPermissionOut]] = {}
        for resource, catalog in FIELD_CATALOG.items():
            resource_permissions: dict[str, FieldPermissionOut] = {}
            for field_def in catalog:
                field_name = field_def["field"]
                can_view = False
                can_edit = False
                for role_id in role_ids:
                    row = configured.get((role_id, resource, field_name))
                    if row is None:
                        # 未配置的角色不施加字段限制
                        can_view = True
                        can_edit = True
                    else:
                        can_view = can_view or row.can_view
                        can_edit = can_edit or row.can_edit
                resource_permissions[field_name] = FieldPermissionOut(
                    can_view=can_view,
                    can_edit=can_edit,
                )
            result[resource] = resource_permissions
        return result
