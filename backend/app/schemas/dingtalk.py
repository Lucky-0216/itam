from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class DingTalkConfigPayload(BaseModel):
    enabled: bool = False
    corp_id: str = Field(default="", max_length=128)
    app_key: str = Field(default="", max_length=128)
    app_secret: str | None = Field(default=None, max_length=256)
    agent_id: int | None = Field(default=None, gt=0)
    default_role_id: int | None = Field(default=None, gt=0)
    root_dept_id: int | None = Field(default=None, gt=0)
    sync_interval_minutes: int = Field(default=120, ge=5, le=10080)
    disable_on_leave: bool = True
    match_existing: bool = True
    approval_enabled: bool = False
    requisition_process_code: str | None = Field(default=None, max_length=64)
    borrow_process_code: str | None = Field(default=None, max_length=64)
    transfer_process_code: str | None = Field(default=None, max_length=64)
    callback_token: str | None = Field(default=None, max_length=128)
    callback_aes_key: str | None = Field(default=None, max_length=64)

    @field_validator(
        "corp_id",
        "app_key",
        "app_secret",
        "requisition_process_code",
        "borrow_process_code",
        "transfer_process_code",
        "callback_token",
        "callback_aes_key",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _strip(value)

    @field_validator("callback_aes_key")
    @classmethod
    def check_aes_key(cls, value: str | None) -> str | None:
        if value and len(value) != 43:
            raise ValueError("回调 AES Key 须为 43 位字符")
        return value

    @model_validator(mode="after")
    def check_enabled(self) -> "DingTalkConfigPayload":
        if self.enabled:
            if not self.corp_id:
                raise ValueError("启用同步时必须填写 CorpId")
            if not self.app_key:
                raise ValueError("启用同步时必须填写 AppKey")
            if self.root_dept_id is None:
                raise ValueError("启用同步时必须选择钉钉组织挂载的根部门")
        return self


class DingTalkTestPayload(BaseModel):
    """连接测试只关心凭证，不校验同步启用相关的必填项（挂载根部门等）。"""

    model_config = ConfigDict(extra="ignore")

    corp_id: str = Field(default="", max_length=128)
    app_key: str = Field(default="", max_length=128)
    app_secret: str | None = Field(default=None, max_length=256)
    agent_id: int | None = Field(default=None, gt=0)

    @field_validator("corp_id", "app_key", "app_secret", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _strip(value)


class DingTalkConfigUpdate(DingTalkConfigPayload):
    version: int | None = Field(default=None, ge=1)


class DingTalkConfigOut(BaseModel):
    id: int
    enabled: bool
    corp_id: str
    app_key: str
    has_secret: bool
    agent_id: int | None = None
    default_role_id: int | None = None
    default_role_name: str | None = None
    root_dept_id: int | None = None
    root_dept_name: str | None = None
    sync_interval_minutes: int
    disable_on_leave: bool
    match_existing: bool
    approval_enabled: bool = False
    requisition_process_code: str | None = None
    borrow_process_code: str | None = None
    transfer_process_code: str | None = None
    has_callback_token: bool = False
    has_callback_aes_key: bool = False
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    last_sync_message: str | None = None
    last_test_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DingTalkTestResult(BaseModel):
    success: bool
    message: str
    corp_id: str | None = None
    dept_sample: int = 0
    user_sample: int = 0
    elapsed_ms: int = 0
    checked_at: datetime


class DingTalkSyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int
    dept_total: int
    dept_created: int
    dept_updated: int
    user_total: int
    user_created: int
    user_updated: int
    user_matched: int
    user_disabled: int
    user_skipped: int
    error_count: int
    operator_name: str | None = None
    message: str | None = None
    details: list[dict] | None = None
    error_message: str | None = None


class DingTalkRoleOption(BaseModel):
    id: int
    code: str
    name: str


class DingTalkDeptOption(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    level: int
    status: int


class DingTalkOptionsOut(BaseModel):
    roles: list[DingTalkRoleOption]
    depts: list[DingTalkDeptOption]
    dingtalk_dept_count: int
    dingtalk_user_count: int
