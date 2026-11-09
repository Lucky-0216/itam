from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class TransferCreate(BaseModel):
    asset_id: int = Field(gt=0)
    to_dept_id: int | None = Field(default=None, gt=0)
    to_custodian_id: int | None = Field(default=None, gt=0)
    to_location: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("to_location", "reason", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def check_target(self) -> "TransferCreate":
        if (
            self.to_dept_id is None
            and self.to_custodian_id is None
            and self.to_location is None
        ):
            raise ValueError("请至少填写调入部门、责任人或存放位置之一")
        return self


class ScrapCreate(BaseModel):
    asset_id: int = Field(gt=0)
    reason: str = Field(min_length=2, max_length=500)
    disposal_method: str | None = Field(default=None, max_length=120)
    residual_value: float | None = Field(default=None, ge=0)

    @field_validator("reason", "disposal_method", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class OpsComment(BaseModel):
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value: object) -> object:
        return _blank_to_none(value)


class OpsConfirmPayload(BaseModel):
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value: object) -> object:
        return _blank_to_none(value)


class ScrapApprovePayload(OpsConfirmPayload):
    pass


class OpsAssetOut(BaseModel):
    id: int
    asset_no: str
    name: str
    category_name: str | None = None
    model_name: str | None = None
    serial_no: str | None = None
    location: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    custodian_id: int | None = None
    custodian_name: str | None = None
    status: str
    status_label: str
    version: int


class AssetTransferOut(BaseModel):
    id: int
    transfer_no: str
    status: str
    status_label: str
    status_tag_type: str
    asset_id: int
    asset_no: str
    asset_name: str
    asset_version: int
    asset_status: str
    asset_status_label: str
    from_dept_id: int | None = None
    from_dept_name: str | None = None
    from_custodian_id: int | None = None
    from_custodian_name: str | None = None
    from_location: str | None = None
    to_dept_id: int | None = None
    to_dept_name: str | None = None
    to_custodian_id: int | None = None
    to_custodian_name: str | None = None
    to_location: str | None = None
    reason: str | None = None
    applicant_id: int
    applicant_name: str
    applicant_dept_id: int | None = None
    applicant_dept_name: str | None = None
    approver_name: str | None = None
    approved_at: datetime | None = None
    approval_comment: str | None = None
    dingtalk_instance_id: str | None = None
    dingtalk_status: str | None = None
    dingtalk_result: str | None = None
    completed_by_name: str | None = None
    completed_at: datetime | None = None
    completion_comment: str | None = None
    can_approve: bool = False
    can_reject: bool = False
    can_confirm: bool = False
    can_cancel: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class AssetTransferPageOut(BaseModel):
    items: list[AssetTransferOut]
    total: int
    page: int
    page_size: int


class AssetScrapOut(BaseModel):
    id: int
    scrap_no: str
    status: str
    status_label: str
    status_tag_type: str
    asset_id: int
    asset_no: str
    asset_name: str
    asset_version: int
    asset_status: str
    asset_status_label: str
    from_status: str
    from_status_label: str
    from_dept_id: int | None = None
    from_dept_name: str | None = None
    from_custodian_id: int | None = None
    from_custodian_name: str | None = None
    from_location: str | None = None
    reason: str
    disposal_method: str | None = None
    residual_value: float | None = None
    applicant_id: int
    applicant_name: str
    applicant_dept_id: int | None = None
    applicant_dept_name: str | None = None
    approver_name: str | None = None
    approved_at: datetime | None = None
    approval_comment: str | None = None
    completed_by_name: str | None = None
    completed_at: datetime | None = None
    completion_comment: str | None = None
    can_approve: bool = False
    can_reject: bool = False
    can_confirm: bool = False
    can_cancel: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class AssetScrapPageOut(BaseModel):
    items: list[AssetScrapOut]
    total: int
    page: int
    page_size: int


class InventoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scope_dept_id: int | None = Field(default=None, gt=0)
    include_child: bool = True
    scope_category_id: int | None = Field(default=None, gt=0)
    include_child_category: bool = True
    planned_date: date | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryItemUpdate(BaseModel):
    result: Literal["NORMAL", "ABNORMAL", "MISSING"]
    actual_location: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("actual_location", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryScanPayload(InventoryItemUpdate):
    result: Literal["NORMAL", "ABNORMAL", "MISSING"] = "NORMAL"
    code: str = Field(min_length=1, max_length=120)

    @field_validator("code", mode="before")
    @classmethod
    def trim_code(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryCancelPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryTaskOut(BaseModel):
    id: int
    task_no: str
    name: str
    status: str
    status_label: str
    status_tag_type: str
    scope_dept_id: int | None = None
    scope_dept_name: str | None = None
    include_child: bool
    scope_category_id: int | None = None
    scope_category_name: str | None = None
    include_child_category: bool
    planned_date: date | None = None
    remark: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    created_by_name: str | None = None
    total_assets: int = 0
    checked_assets: int = 0
    normal_count: int = 0
    abnormal_count: int = 0
    missing_count: int = 0
    surplus_count: int = 0
    pending_count: int = 0
    can_manage: bool = False
    adjustment_id: int | None = None
    adjustment_no: str | None = None
    adjustment_status: str | None = None
    adjustment_status_label: str | None = None
    adjustment_status_tag_type: str | None = None
    adjustment_version: int | None = None
    can_submit_adjustment: bool = False
    can_approve_adjustment: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class InventoryTaskPageOut(BaseModel):
    items: list[InventoryTaskOut]
    total: int
    page: int
    page_size: int


class InventoryItemOut(BaseModel):
    id: int
    task_id: int
    asset_id: int
    asset_no: str
    asset_name: str
    category_name: str | None = None
    dept_name: str | None = None
    location: str | None = None
    custodian_name: str | None = None
    expected_status: str
    expected_status_label: str
    result: str
    result_label: str
    result_tag_type: str
    actual_location: str | None = None
    remark: str | None = None
    checked_by_name: str | None = None
    checked_at: datetime | None = None
    created_at: datetime


class InventoryItemPageOut(BaseModel):
    items: list[InventoryItemOut]
    total: int
    page: int
    page_size: int


class InventorySurplusCreate(BaseModel):
    asset_no: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    category_id: int = Field(gt=0)
    model_id: int | None = Field(default=None, gt=0)
    dept_id: int | None = Field(default=None, gt=0)
    serial_no: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    purchase_date: date | None = None
    purchase_price: float | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=500)

    @field_validator(
        "asset_no",
        "name",
        "serial_no",
        "location",
        "remark",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)


class InventorySurplusOut(BaseModel):
    id: int
    task_id: int
    asset_no: str
    name: str
    category_id: int
    category_name: str | None = None
    model_id: int | None = None
    model_name: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    serial_no: str | None = None
    location: str | None = None
    purchase_date: date | None = None
    purchase_price: float | None = None
    remark: str | None = None
    created_by_name: str | None = None
    created_asset_id: int | None = None
    applied_at: datetime | None = None
    created_at: datetime


class InventoryAdjustmentCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryAdjustmentReview(BaseModel):
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value: object) -> object:
        return _blank_to_none(value)


class InventoryAdjustmentOut(BaseModel):
    id: int
    task_id: int
    task_no: str
    task_name: str
    adjustment_no: str
    status: str
    status_label: str
    status_tag_type: str
    loss_count: int
    surplus_count: int
    reason: str | None = None
    requested_by_name: str | None = None
    requested_at: datetime
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class InventoryReportOut(BaseModel):
    task: InventoryTaskOut
    missing_items: list[InventoryItemOut]
    abnormal_items: list[InventoryItemOut]
    surplus_items: list[InventorySurplusOut]
    adjustment: InventoryAdjustmentOut | None = None
    generated_at: datetime
