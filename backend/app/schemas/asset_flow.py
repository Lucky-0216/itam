from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.asset_flow import RequestType
from app.schemas.approval_flow import ApprovalStepOut


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class AvailableCategoryOut(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    available_count: int = 0
    has_children: bool = False
    children: list["AvailableCategoryOut"] = Field(default_factory=list)


AvailableCategoryOut.model_rebuild()


class AvailableModelOut(BaseModel):
    model_id: int
    model_name: str
    model_code: str | None = None
    brand: str | None = None
    spec: str | None = None
    unit: str | None = None
    category_name: str | None = None
    available_count: int = 0


class AvailableAssetOut(BaseModel):
    id: int
    asset_no: str
    name: str
    category_name: str | None = None
    model_id: int | None = None
    model_name: str | None = None
    serial_no: str | None = None
    location: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    status: str
    status_label: str
    version: int


class AssetRequestCreate(BaseModel):
    request_type: Literal["REQUISITION", "BORROW"]
    category_id: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)
    expected_return_date: date | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def check_borrow_date(self) -> "AssetRequestCreate":
        if self.request_type != RequestType.BORROW:
            return self
        if self.expected_return_date is None:
            raise ValueError("借用申请必须填写预计归还日期")
        if self.expected_return_date < date.today():
            raise ValueError("预计归还日期不能早于今天")
        return self


class AssetRequestComment(BaseModel):
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value: object) -> object:
        return _blank_to_none(value)


class AssetOutboundPayload(BaseModel):
    version: int = Field(ge=1)
    asset_id: int | None = Field(default=None, gt=0)
    location: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("location", "comment", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class AssetReturnCreate(BaseModel):
    asset_id: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class AssetReturnConfirmPayload(BaseModel):
    version: int = Field(ge=1)
    location: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("location", "comment", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class ApprovalRecordOut(BaseModel):
    id: int
    task_id: int | None = None
    step_no: int
    step_code: str
    step_name: str
    action: str
    action_label: str
    approver_id: int | None = None
    approver_name: str | None = None
    comment: str | None = None
    operated_at: datetime


class ApprovalConfigOut(BaseModel):
    dept_approval_required: bool
    version: int
    updated_by_name: str | None = None
    updated_at: datetime


class ApprovalConfigUpdate(BaseModel):
    dept_approval_required: bool
    version: int = Field(ge=1)


class AssetRequestOut(BaseModel):
    id: int
    request_no: str
    request_type: str
    request_type_label: str
    status: str
    status_label: str
    status_tag_type: str
    category_id: int
    category_name: str
    include_child: bool = True
    approval_stage: str | None = None
    approval_stage_label: str | None = None
    dept_approval_required: bool = False
    flow_id: int | None = None
    flow_name: str | None = None
    current_step_no: int | None = None
    current_step_name: str | None = None
    current_approvers: list[str] = Field(default_factory=list)
    total_steps: int = 0
    approval_steps: list[ApprovalStepOut] = Field(default_factory=list)
    asset_id: int | None = None
    asset_no: str | None = None
    asset_name: str | None = None
    asset_version: int = 1
    asset_model_name: str | None = None
    asset_status: str | None = None
    asset_status_label: str | None = None
    asset_location: str | None = None
    asset_custodian_id: int | None = None
    asset_custodian_name: str | None = None
    applicant_id: int
    applicant_name: str
    applicant_dept_id: int | None = None
    applicant_dept_name: str | None = None
    reason: str | None = None
    expected_return_date: date | None = None
    days_to_due: int | None = None
    is_overdue: bool = False
    source_request_id: int | None = None
    approver_name: str | None = None
    approved_at: datetime | None = None
    approval_comment: str | None = None
    dingtalk_instance_id: str | None = None
    dingtalk_status: str | None = None
    dingtalk_result: str | None = None
    approvals: list[ApprovalRecordOut] = Field(default_factory=list)
    outbound_by_name: str | None = None
    outbound_at: datetime | None = None
    outbound_location: str | None = None
    return_requested_at: datetime | None = None
    confirm_by_name: str | None = None
    confirmed_at: datetime | None = None
    confirm_comment: str | None = None
    can_approve: bool = False
    can_reject: bool = False
    can_outbound: bool = False
    can_configure: bool = False
    can_cancel: bool = False
    can_confirm_return: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class AssetRequestPageOut(BaseModel):
    items: list[AssetRequestOut]
    total: int
    page: int
    page_size: int


class AssetRequestSummaryOut(BaseModel):
    pending_approval: int = 0
    pending_outbound: int = 0
    pending_return: int = 0
    borrowed: int = 0
    mine_pending: int = 0
    my_pending_approval: int = 0
    my_pending_outbound: int = 0
    my_pending_return: int = 0


class MyAssetOut(BaseModel):
    asset_id: int
    asset_no: str
    name: str
    category_name: str | None = None
    model_name: str | None = None
    serial_no: str | None = None
    location: str | None = None
    dept_name: str | None = None
    status: str
    status_label: str
    status_tag_type: str
    request_id: int | None = None
    request_type: str | None = None
    borrowed_at: datetime | None = None
    expected_return_date: date | None = None
    days_to_due: int | None = None
    is_overdue: bool = False
    return_pending: bool = False
    return_request_id: int | None = None
    version: int


class AssetHistoryOut(BaseModel):
    id: int
    asset_id: int
    request_id: int | None = None
    action: str
    action_label: str
    from_status: str
    from_status_label: str
    to_status: str
    to_status_label: str
    before_snapshot: dict[str, Any]
    after_snapshot: dict[str, Any]
    operator_name: str | None = None
    summary: str | None = None
    created_at: datetime


class ScanAssetOut(BaseModel):
    asset: AvailableAssetOut
    requests: list[AssetRequestOut]
