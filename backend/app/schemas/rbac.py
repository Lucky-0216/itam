import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.permissions import (
    DATA_RESOURCE_LABELS,
    DATA_SCOPE_LABELS,
    FIELD_CATALOG,
    DataScope,
    DomainScope,
)

_ROLE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")
_RESOURCE_FIELDS = {
    resource: {item["field"] for item in fields}
    for resource, fields in FIELD_CATALOG.items()
}


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    data_scope: str = Field(default=DataScope.SELF)
    domain_scope: str = Field(default=DomainScope.CUSTOM)
    asset_domains: list[str] = Field(default_factory=list)
    sort: int = Field(default=0, ge=0, le=9999)
    status: int = Field(default=1, ge=0, le=1)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = str(value or "").strip().upper()
        if not _ROLE_CODE_RE.fullmatch(code):
            raise ValueError("角色编码需为 2-50 位大写字母、数字或下划线，且以字母开头")
        return code

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("data_scope")
    @classmethod
    def check_scope(cls, value: str) -> str:
        if value not in DATA_SCOPE_LABELS or value == DataScope.ROLE:
            raise ValueError("数据范围不合法")
        return value

    @field_validator("domain_scope")
    @classmethod
    def check_domain_scope(cls, value: str) -> str:
        if value not in (DomainScope.ALL, DomainScope.CUSTOM):
            raise ValueError("资产域范围不合法")
        return value

    @field_validator("asset_domains")
    @classmethod
    def dedupe_domains(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class RoleUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    sort: int = Field(default=0, ge=0, le=9999)
    status: int = Field(default=1, ge=0, le=1)
    version: int = Field(ge=1)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    data_scope: str
    data_scope_label: str
    domain_scope: str
    asset_domains: list[str] = Field(default_factory=list)
    status: int
    sort: int
    is_system: bool
    version: int
    user_count: int = 0
    menu_count: int = 0
    created_at: datetime
    updated_at: datetime


class RoleBriefOut(BaseModel):
    id: int
    code: str
    name: str
    data_scope: str


class RoleMemberOut(BaseModel):
    id: int
    username: str
    real_name: str
    dept_name: str | None = None
    status: int


class RoleUserOptionOut(BaseModel):
    id: int
    username: str
    real_name: str
    dept_name: str | None = None
    status: int


class FieldPermissionItem(BaseModel):
    resource: str = Field(min_length=1, max_length=50)
    field: str = Field(min_length=1, max_length=50)
    can_view: bool = True
    can_edit: bool = True

    @field_validator("field")
    @classmethod
    def check_field(cls, value: str, info) -> str:
        resource = info.data.get("resource")
        if resource and value not in _RESOURCE_FIELDS.get(resource, set()):
            raise ValueError("字段不在可授权目录中")
        return value


class RoleDetailOut(RoleOut):
    menu_ids: list[int] = Field(default_factory=list)
    dept_ids: list[int] = Field(default_factory=list)
    field_permissions: list[FieldPermissionItem] = Field(default_factory=list)
    data_permissions: list["ResourceDataPermissionItem"] = Field(default_factory=list)
    users: list[RoleMemberOut] = Field(default_factory=list)


class MenuAssignRequest(BaseModel):
    menu_ids: list[int]
    version: int = Field(ge=1)

    @field_validator("menu_ids")
    @classmethod
    def dedupe(cls, value: list[int]) -> list[int]:
        result = list(dict.fromkeys(value))
        if any(item <= 0 for item in result):
            raise ValueError("菜单 ID 不合法")
        return result


class FieldPermissionsAssignRequest(BaseModel):
    permissions: list[FieldPermissionItem]
    version: int = Field(ge=1)

    @field_validator("permissions")
    @classmethod
    def dedupe(cls, value: list[FieldPermissionItem]) -> list[FieldPermissionItem]:
        seen: set[tuple[str, str]] = set()
        for item in value:
            key = (item.resource, item.field)
            if key in seen:
                raise ValueError("字段权限存在重复项")
            seen.add(key)
        return value


class ResourceDataPermissionItem(BaseModel):
    resource: str = Field(min_length=1, max_length=50)
    data_scope: str = Field(default=DataScope.SELF)
    dept_ids: list[int] = Field(default_factory=list)

    @field_validator("resource")
    @classmethod
    def check_resource(cls, value: str) -> str:
        if value not in DATA_RESOURCE_LABELS:
            raise ValueError("数据资源不合法")
        return value

    @field_validator("data_scope")
    @classmethod
    def check_scope(cls, value: str) -> str:
        if value not in DATA_SCOPE_LABELS or value == DataScope.ROLE:
            raise ValueError("数据范围不合法")
        return value

    @field_validator("dept_ids")
    @classmethod
    def dedupe_dept_ids(cls, value: list[int]) -> list[int]:
        result = sorted(set(value))
        if any(item <= 0 for item in result):
            raise ValueError("部门 ID 不合法")
        return result


class DataPermissionsAssignRequest(BaseModel):
    data_scope: str
    domain_scope: str
    asset_domains: list[str] = Field(default_factory=list)
    permissions: list[ResourceDataPermissionItem] = Field(default_factory=list)
    dept_ids: list[int] = Field(default_factory=list)
    version: int = Field(ge=1)

    @field_validator("data_scope")
    @classmethod
    def check_global_scope(cls, value: str) -> str:
        if value not in DATA_SCOPE_LABELS or value == DataScope.ROLE:
            raise ValueError("数据范围不合法")
        return value

    @field_validator("domain_scope")
    @classmethod
    def check_domain_scope(cls, value: str) -> str:
        if value not in (DomainScope.ALL, DomainScope.CUSTOM):
            raise ValueError("资产域范围不合法")
        return value

    @field_validator("asset_domains")
    @classmethod
    def dedupe_domains(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @field_validator("permissions")
    @classmethod
    def dedupe(
        cls, value: list[ResourceDataPermissionItem]
    ) -> list[ResourceDataPermissionItem]:
        seen: set[str] = set()
        for item in value:
            if item.resource in seen:
                raise ValueError("同一资源只能配置一条数据权限")
            seen.add(item.resource)
        return value

    @field_validator("dept_ids")
    @classmethod
    def dedupe_depts(cls, value: list[int]) -> list[int]:
        result = list(dict.fromkeys(value))
        if any(item <= 0 for item in result):
            raise ValueError("部门 ID 不合法")
        return result


class RoleUsersAssignRequest(BaseModel):
    user_ids: list[int]
    version: int = Field(ge=1)

    @field_validator("user_ids")
    @classmethod
    def dedupe(cls, value: list[int]) -> list[int]:
        result = list(dict.fromkeys(value))
        if any(item <= 0 for item in result):
            raise ValueError("用户 ID 不合法")
        return result


class MenuAdminNode(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    type: str
    permission_code: str | None = None
    path: str | None = None
    component: str | None = None
    icon: str | None = None
    sort: int = 0
    visible: bool = True
    status: int = 1
    children: list["MenuAdminNode"] = Field(default_factory=list)


MenuAdminNode.model_rebuild()


class DataScopeOption(BaseModel):
    value: str
    label: str


class ResourceOption(BaseModel):
    value: str
    label: str


class RoleMetaOut(BaseModel):
    data_scopes: list[DataScopeOption]
    field_catalog: dict[str, list[dict[str, str]]]
    data_resources: list[ResourceOption] = Field(default_factory=list)
    asset_domains: list[DataScopeOption] = Field(default_factory=list)


RoleDetailOut.model_rebuild()
