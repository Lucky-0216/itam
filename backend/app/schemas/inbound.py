from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_ASSET_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,49}$")
_BASE_ASSET_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class InboundItemCreate(BaseModel):
    category_id: int = Field(gt=0)
    model_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=200)
    base_asset_no: str | None = Field(default=None, max_length=40)
    asset_nos: list[str] | None = Field(default=None, max_length=200)
    unit_price: float | None = Field(default=None, ge=0, le=99999999)
    warranty_end: date | None = None
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("name", "remark", "base_asset_no", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("asset_nos", mode="before")
    @classmethod
    def trim_asset_nos(cls, value: object) -> object:
        if value is None or not isinstance(value, list):
            return value
        return [item.strip() if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def check_codes(self) -> "InboundItemCreate":
        if self.base_asset_no and not _BASE_ASSET_NO_RE.fullmatch(
            self.base_asset_no
        ):
            raise ValueError(
                "基准编码需以字母或数字开头，仅支持字母、数字、点、下划线、中划线，长度 1-40 位"
            )
        if self.asset_nos is None:
            return self
        if len(self.asset_nos) != self.quantity:
            raise ValueError("最终编码数量必须与入库数量一致")
        seen: set[str] = set()
        for code in self.asset_nos:
            if not isinstance(code, str) or not _ASSET_NO_RE.fullmatch(code):
                raise ValueError(
                    f"最终编码「{code or '空'}」格式不正确，需以字母或数字开头，长度 3-50 位，仅支持字母、数字、点、下划线、中划线"
                )
            key = code.casefold()
            if key in seen:
                raise ValueError(f"最终编码「{code}」重复，请修改后重新提交")
            seen.add(key)
        return self


class InboundCreate(BaseModel):
    inbound_type: Literal["PURCHASE", "OTHER"] = "PURCHASE"
    supplier: str | None = Field(default=None, max_length=120)
    purchase_date: date | None = None
    location: str | None = Field(default=None, max_length=120)
    dept_id: int | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=500)
    source_inbound_id: int | None = Field(default=None, gt=0)
    items: list[InboundItemCreate] = Field(min_length=1, max_length=50)

    @field_validator("supplier", "location", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def check_total(self) -> "InboundCreate":
        total = sum(item.quantity for item in self.items)
        if total > 500:
            raise ValueError("单张入库单最多支持 500 台/件资产")
        seen: dict[str, int] = {}
        for index, item in enumerate(self.items, start=1):
            for code in item.asset_nos or []:
                key = code.casefold()
                if key in seen:
                    raise ValueError(
                        f"第 {index} 行最终编码「{code}」与第 {seen[key]} 行重复，请修改后重新提交"
                    )
                seen[key] = index
        return self


class InboundUpdate(InboundCreate):
    version: int = Field(ge=1)


class InboundReversePayload(BaseModel):
    asset_nos: list[str] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=1)

    @field_validator("asset_nos", mode="before")
    @classmethod
    def trim_asset_nos(cls, value: object) -> object:
        if value is None or not isinstance(value, list):
            return value
        return [item.strip() if isinstance(item, str) else item for item in value]

    @field_validator("asset_nos")
    @classmethod
    def check_asset_nos(cls, value: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for code in value:
            if not isinstance(code, str) or not _ASSET_NO_RE.fullmatch(code):
                raise ValueError(f"资产编码「{code or '空'}」格式不正确")
            key = code.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(code)
        return unique

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class InboundConfirmPayload(BaseModel):
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def trim_comment(cls, value: object) -> object:
        return _blank_to_none(value)


class InboundCancelPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class InboundItemOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    model_id: int | None = None
    model_name: str | None = None
    name: str
    quantity: int
    base_asset_no: str | None = None
    asset_nos: list[str] = Field(default_factory=list)
    unit_price: float | None = None
    amount: float = 0
    warranty_end: date | None = None
    remark: str | None = None


class InboundAssetOut(BaseModel):
    id: int
    asset_no: str
    name: str
    status: str
    status_label: str
    can_reverse: bool = False


class AssetInboundOut(BaseModel):
    id: int
    inbound_no: str
    inbound_type: str
    inbound_type_label: str
    status: str
    status_label: str
    status_tag_type: str
    source_inbound_id: int | None = None
    supplier: str | None = None
    purchase_date: date | None = None
    location: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    total_quantity: int
    total_amount: float
    remark: str | None = None
    created_by_name: str | None = None
    confirmed_by_name: str | None = None
    confirmed_at: datetime | None = None
    completion_comment: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    can_confirm: bool = False
    can_cancel: bool = False
    can_edit: bool = False
    can_reverse: bool = False
    can_supplement: bool = False
    version: int
    created_at: datetime
    updated_at: datetime
    items: list[InboundItemOut] = Field(default_factory=list)
    assets: list[InboundAssetOut] = Field(default_factory=list)


class AssetInboundPageOut(BaseModel):
    items: list[AssetInboundOut]
    total: int
    page: int
    page_size: int


class StockLocationOut(BaseModel):
    location: str | None = None
    location_label: str
    asset_count: int
    total_value: float


class StockWarningOut(BaseModel):
    category_id: int
    category_name: str
    stock_count: int
    safety_stock: int
    shortage: int


class StockOverviewOut(BaseModel):
    in_stock_count: int
    in_stock_value: float
    location_count: int
    warning_count: int
    locations: list[StockLocationOut] = Field(default_factory=list)
    warnings: list[StockWarningOut] = Field(default_factory=list)


class StockAssetOut(BaseModel):
    id: int
    asset_no: str
    name: str
    category_id: int
    category_name: str | None = None
    model_name: str | None = None
    serial_no: str | None = None
    location: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    purchase_price: float | None = None
    warranty_end: date | None = None
    remark: str | None = None
    created_at: datetime


class StockAssetPageOut(BaseModel):
    items: list[StockAssetOut]
    total: int
    page: int
    page_size: int
