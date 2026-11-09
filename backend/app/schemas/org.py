import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import validate_password_strength

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
_DEPT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,49}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class DeptCreate(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=2, max_length=50)
    leader: str | None = Field(default=None, max_length=50)
    manager_id: int | None = Field(default=None, gt=0)
    phone: str | None = Field(default=None, max_length=30)
    sort: int = Field(default=0, ge=0, le=9999)
    status: int = Field(default=1, ge=0, le=1)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("name", "leader", "phone", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = str(value or "").strip().upper()
        if not _DEPT_CODE_RE.fullmatch(code):
            raise ValueError("部门编码需为 2-50 位大写字母、数字、下划线或短横线")
        return code


class DeptUpdate(DeptCreate):
    version: int = Field(ge=1)


class DeptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None = None
    name: str
    code: str
    leader: str | None = None
    manager_id: int | None = None
    manager_name: str | None = None
    phone: str | None = None
    path: str
    level: int
    sort: int
    status: int
    remark: str | None = None
    source: str = "local"
    ldap_dn: str | None = None
    version: int
    user_count: int = 0
    children: list["DeptOut"] = Field(default_factory=list)


DeptOut.model_rebuild()


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=64)
    real_name: str = Field(min_length=1, max_length=50)
    dept_id: int = Field(gt=0)
    position: str | None = Field(default=None, max_length=64)
    employee_no: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    status: int = Field(default=1, ge=0, le=1)
    role_ids: list[int] = Field(min_length=1)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> str:
        username = str(value or "").strip().lower()
        if not _USERNAME_RE.fullmatch(username):
            raise ValueError("用户名需为 3-50 位小写字母、数字、点、下划线或短横线")
        return username

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        validate_password_strength(value)
        return value

    @field_validator("real_name", "position", "employee_no", "email", "phone", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL_RE.fullmatch(value):
            raise ValueError("邮箱格式不正确")
        return value.lower() if value else None

    @field_validator("role_ids")
    @classmethod
    def dedupe_roles(cls, value: list[int]) -> list[int]:
        result = list(dict.fromkeys(value))
        if any(item <= 0 for item in result):
            raise ValueError("角色 ID 不合法")
        return result


class UserUpdate(BaseModel):
    real_name: str = Field(min_length=1, max_length=50)
    dept_id: int = Field(gt=0)
    position: str | None = Field(default=None, max_length=64)
    employee_no: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    role_ids: list[int] | None = Field(default=None, min_length=1)
    remark: str | None = Field(default=None, max_length=255)
    version: int = Field(ge=1)

    @field_validator("real_name", "position", "employee_no", "email", "phone", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL_RE.fullmatch(value):
            raise ValueError("邮箱格式不正确")
        return value.lower() if value else None

    @field_validator("role_ids")
    @classmethod
    def dedupe_roles(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        result = list(dict.fromkeys(value))
        if any(item <= 0 for item in result):
            raise ValueError("角色 ID 不合法")
        return result


class UserStatusUpdate(BaseModel):
    status: int = Field(ge=0, le=1)
    version: int = Field(ge=1)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=64)
    version: int = Field(ge=1)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class UserRoleOut(BaseModel):
    id: int
    code: str
    name: str
    data_scope: str


class UserOut(BaseModel):
    id: int
    username: str
    real_name: str
    employee_no: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    dept_path: str | None = None
    position: str | None = None
    status: int
    source: str = "local"
    must_change_password: bool
    last_login_at: datetime | None = None
    created_at: datetime
    version: int
    roles: list[UserRoleOut] = Field(default_factory=list)


class UserDetailOut(UserOut):
    remark: str | None = None
    token_version: int


class UserPageOut(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


class OrgSyncPolicyUpdate(BaseModel):
    source_priority: str = Field(min_length=10, max_length=50)
    conflict_strategy: str = Field(min_length=1, max_length=20)
    protect_local: bool
    disable_scope: str = Field(min_length=1, max_length=20)
    version: int = Field(ge=1)


class OrgSyncPolicyOut(BaseModel):
    source_priority: str
    conflict_strategy: str
    protect_local: bool
    disable_scope: str
    version: int
