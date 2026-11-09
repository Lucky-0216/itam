from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import validate_password_strength


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=64)

    @field_validator("username")
    @classmethod
    def trim_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("请输入用户名")
        return value


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def check_strength(cls, value: str) -> str:
        validate_password_strength(value)
        return value

    @model_validator(mode="after")
    def check_not_same(self) -> "ChangePasswordRequest":
        if self.old_password == self.new_password:
            raise ValueError("新密码不能与当前密码相同")
        return self


class TokenBundle(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class LoginUserInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str
    dept_name: str | None = None
    avatar: str | None = None


class LoginResponse(TokenBundle):
    must_change_password: bool
    user: LoginUserInfo


class RoleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    data_scope: str


class MenuNode(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    type: str
    path: str | None = None
    component: str | None = None
    icon: str | None = None
    sort: int = 0
    permission_code: str | None = None
    children: list["MenuNode"] = Field(default_factory=list)


MenuNode.model_rebuild()


class FieldPermissionOut(BaseModel):
    can_view: bool
    can_edit: bool


class UserProfile(BaseModel):
    id: int
    username: str
    real_name: str
    employee_no: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    position: str | None = None
    status: int
    source: str = "local"
    must_change_password: bool
    last_login_at: datetime | None = None


class CurrentUserOut(BaseModel):
    user: UserProfile
    roles: list[RoleBrief]
    permissions: list[str]
    data_scope: str
    data_scope_label: str
    custom_dept_ids: list[int]
    menus: list[MenuNode]
    field_permissions: dict[str, dict[str, FieldPermissionOut]]
    domain_scope: str
    asset_domains: list[str]
    resource_scopes: dict[str, str]
