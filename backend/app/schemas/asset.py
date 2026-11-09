import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CATEGORY_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,49}$")
_MODEL_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,49}$")
_DOMAIN_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_ASSET_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,49}$")


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _trim_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class CategoryFieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    field_key: str = Field(min_length=2, max_length=50)
    field_type: Literal["TEXT", "NUMBER", "DATE", "SELECT"] = "TEXT"
    required: bool = False
    options: list[str] | None = None
    sort: int = Field(default=0, ge=0, le=9999)
    status: int = Field(default=1, ge=0, le=1)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("field_key", mode="before")
    @classmethod
    def normalize_key(cls, value: object) -> str:
        key = str(value or "").strip().lower()
        if not _FIELD_KEY_RE.fullmatch(key):
            raise ValueError("字段标识需为小写字母开头的 2-50 位小写字母、数字或下划线")
        return key

    @field_validator("name", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        result = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(result) > 50:
            raise ValueError("下拉选项不能超过 50 个")
        return result or None

    @model_validator(mode="after")
    def check_select_options(self) -> "CategoryFieldCreate":
        if self.field_type == "SELECT" and not self.options:
            raise ValueError("下拉选项字段必须配置选项")
        return self


class CategoryFieldUpdate(CategoryFieldCreate):
    version: int = Field(ge=1)


class CategoryFieldOut(BaseModel):
    id: int
    category_id: int
    name: str
    field_key: str
    field_type: str
    required: bool
    options: list[str] | None = None
    sort: int
    status: int
    remark: str | None = None
    version: int


class AssetDomainCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    sort: int = Field(default=100, ge=0, le=9999)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = str(value or "").strip().upper()
        if not _DOMAIN_CODE_RE.fullmatch(code):
            raise ValueError("资产域编码需为 1-20 位大写字母、数字或下划线，且以字母开头")
        return code

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return _trim_text(value)


class AssetDomainUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    sort: int = Field(default=100, ge=0, le=9999)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return _trim_text(value)


class AssetDomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    sort: int
    is_builtin: bool


class CategoryCreate(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=2, max_length=50)
    category_type: Literal["HARDWARE", "SOFTWARE", "ACCESSORY", "CONSUMABLE"] | None = None
    asset_domain: str | None = Field(default=None, min_length=1, max_length=20)
    sort: int = Field(default=0, ge=0, le=9999)
    safety_stock: int = Field(default=0, ge=0, le=99999)
    status: int = Field(default=1, ge=0, le=1)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("name", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = str(value or "").strip().upper()
        if not _CATEGORY_CODE_RE.fullmatch(code):
            raise ValueError("分类编码需为 2-50 位大写字母、数字、下划线或短横线")
        return code

    @field_validator("asset_domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: object) -> str | None:
        if value is None:
            return None
        code = str(value).strip().upper()
        if not _DOMAIN_CODE_RE.fullmatch(code):
            raise ValueError("资产域编码需为 1-20 位大写字母、数字或下划线，且以字母开头")
        return code


class CategoryUpdate(CategoryCreate):
    version: int = Field(ge=1)
    confirm_domain_change: bool = False


class CategoryOut(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    code: str
    category_type: str
    asset_domain: str
    path: str
    level: int
    sort: int
    safety_stock: int
    status: int
    remark: str | None = None
    version: int
    model_count: int = 0
    asset_count: int = 0
    field_defs: list[CategoryFieldOut] = Field(default_factory=list)
    children: list["CategoryOut"] = Field(default_factory=list)


CategoryOut.model_rebuild()


class ModelCreate(BaseModel):
    category_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=2, max_length=50)
    brand: str | None = Field(default=None, max_length=80)
    spec: str | None = Field(default=None, max_length=255)
    unit: str = Field(default="台", min_length=1, max_length=20)
    depreciation_months: int | None = Field(default=None, ge=1, le=600)
    residual_rate: float = Field(default=0.05, ge=0, le=1)
    status: int = Field(default=1, ge=0, le=1)
    remark: str | None = Field(default=None, max_length=255)

    @field_validator("name", "brand", "spec", "remark", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> str:
        code = str(value or "").strip().upper()
        if not _MODEL_CODE_RE.fullmatch(code):
            raise ValueError("型号编码需为 2-50 位大写字母、数字、点、下划线或短横线")
        return code

    @field_validator("unit", mode="before")
    @classmethod
    def trim_unit(cls, value: object) -> str:
        unit = str(value or "台").strip() or "台"
        return unit


class ModelUpdate(ModelCreate):
    version: int = Field(ge=1)
    confirm_domain_change: bool = False


class ModelOut(BaseModel):
    id: int
    category_id: int
    category_name: str | None = None
    name: str
    code: str
    brand: str | None = None
    spec: str | None = None
    unit: str
    depreciation_months: int | None = None
    residual_rate: float
    status: int
    remark: str | None = None
    version: int
    asset_count: int = 0
    created_at: datetime
    updated_at: datetime


class ModelPageOut(BaseModel):
    items: list[ModelOut]
    total: int
    page: int
    page_size: int


class CustodianOptionOut(BaseModel):
    id: int
    username: str
    real_name: str
    dept_id: int | None = None
    dept_name: str | None = None


class DeptOptionOut(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    path: str
    level: int


class AssetCreate(BaseModel):
    asset_no: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    category_id: int = Field(gt=0)
    model_id: int | None = Field(default=None, gt=0)
    serial_no: str | None = Field(default=None, max_length=120)
    mac_address: str | None = Field(default=None, max_length=64)
    purchase_date: date | None = None
    supplier: str | None = Field(default=None, max_length=120)
    purchase_price: float | None = Field(default=None, ge=0, le=9999999999)
    warranty_end: date | None = None
    location: str | None = Field(default=None, max_length=120)
    dept_id: int | None = Field(default=None, gt=0)
    custodian_id: int | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "name",
        "serial_no",
        "mac_address",
        "supplier",
        "location",
        "remark",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("asset_no", mode="before")
    @classmethod
    def validate_asset_no(cls, value: object) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if not _ASSET_NO_RE.fullmatch(raw):
            raise ValueError("资产编号需为 3-50 位字母、数字、点、下划线或短横线")
        return raw

    @field_validator("mac_address")
    @classmethod
    def normalize_mac(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.replace("-", ":").upper()
        parts = cleaned.split(":")
        if len(parts) != 6 or any(len(part) != 2 for part in parts):
            raise ValueError("MAC 地址格式不正确")
        return cleaned


class AssetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category_id: int = Field(gt=0)
    model_id: int | None = Field(default=None, gt=0)
    serial_no: str | None = Field(default=None, max_length=120)
    mac_address: str | None = Field(default=None, max_length=64)
    purchase_date: date | None = None
    supplier: str | None = Field(default=None, max_length=120)
    purchase_price: float | None = Field(default=None, ge=0, le=9999999999)
    warranty_end: date | None = None
    location: str | None = Field(default=None, max_length=120)
    dept_id: int | None = Field(default=None, gt=0)
    custodian_id: int | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(ge=1)

    @field_validator(
        "name",
        "serial_no",
        "mac_address",
        "supplier",
        "location",
        "remark",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("mac_address")
    @classmethod
    def normalize_mac(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.replace("-", ":").upper()
        parts = cleaned.split(":")
        if len(parts) != 6 or any(len(part) != 2 for part in parts):
            raise ValueError("MAC 地址格式不正确")
        return cleaned


class AssetStockInPayload(BaseModel):
    version: int = Field(ge=1)


class AssetVoidPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=1)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class AssetBatchVoidPayload(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("asset_ids")
    @classmethod
    def normalize_asset_ids(cls, value: list[int]) -> list[int]:
        unique: list[int] = []
        seen: set[int] = set()
        for raw in value:
            item = int(raw)
            if item <= 0:
                raise ValueError("资产编号不正确")
            if item not in seen:
                seen.add(item)
                unique.append(item)
        if len(unique) > 200:
            raise ValueError("单次批量作废最多 200 项资产")
        return unique

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return _blank_to_none(value)


class AssetOut(BaseModel):
    id: int
    asset_no: str
    name: str
    category_id: int
    category_name: str | None = None
    category_type: str | None = None
    model_id: int | None = None
    model_name: str | None = None
    model_brand: str | None = None
    serial_no: str | None = None
    mac_address: str | None = None
    purchase_date: date | None = None
    supplier: str | None = None
    purchase_price: float | None = None
    warranty_end: date | None = None
    location: str | None = None
    dept_id: int | None = None
    dept_name: str | None = None
    custodian_id: int | None = None
    custodian_name: str | None = None
    status: str
    status_label: str
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None
    masked_fields: list[str] = Field(default_factory=list)
    voided_at: datetime | None = None
    voided_by_name: str | None = None
    void_reason: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class AssetPageOut(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int


class AssetBatchUpdate(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=200)
    dept_id: int | None = Field(default=None, gt=0)
    custodian_id: int | None = Field(default=None, gt=0)
    location: str | None = Field(default=None, max_length=120)
    clear_dept: bool = False
    clear_custodian: bool = False
    clear_location: bool = False

    @field_validator("asset_ids")
    @classmethod
    def normalize_asset_ids(cls, value: list[int]) -> list[int]:
        unique: list[int] = []
        seen: set[int] = set()
        for raw in value:
            item = int(raw)
            if item <= 0:
                raise ValueError("资产编号不正确")
            if item not in seen:
                seen.add(item)
                unique.append(item)
        if not unique:
            raise ValueError("请选择要更新的资产")
        if len(unique) > 200:
            raise ValueError("单次批量操作最多 200 项资产")
        return unique

    @field_validator("location", mode="before")
    @classmethod
    def trim_location(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def check_changes(self) -> "AssetBatchUpdate":
        if self.dept_id is not None and self.clear_dept:
            raise ValueError("设置部门与清除部门不能同时选择")
        if self.custodian_id is not None and self.clear_custodian:
            raise ValueError("设置责任人与清除责任人不能同时选择")
        if self.location is not None and self.clear_location:
            raise ValueError("设置存放位置与清除存放位置不能同时选择")
        if self.clear_dept and self.custodian_id is not None:
            raise ValueError("设置责任人时不能同时清除部门")
        if (
            self.dept_id is None
            and self.custodian_id is None
            and self.location is None
            and not self.clear_dept
            and not self.clear_custodian
            and not self.clear_location
        ):
            raise ValueError("请至少选择一个要修改的字段")
        return self


class AssetBatchUpdateResult(BaseModel):
    updated: int


class AssetAttachmentOut(BaseModel):
    id: int
    asset_id: int
    file_name: str
    content_type: str | None = None
    file_size: int
    kind: str
    uploaded_by_name: str | None = None
    created_at: datetime


class AssetTimelineItem(BaseModel):
    id: int
    action: str
    summary: str | None = None
    username: str | None = None
    status: str
    created_at: datetime
