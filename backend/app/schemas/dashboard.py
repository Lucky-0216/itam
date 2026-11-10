from datetime import date, datetime

from pydantic import BaseModel


class DashboardMetrics(BaseModel):
    total_assets: int
    total_value: float
    pending_stock: int
    in_stock: int
    in_use: int
    idle: int
    repairing: int
    pending_scrap: int
    scrapped: int
    warranty_30d: int
    month_inbound: int
    month_requisition: int
    contract_expiring: int
    idle_rate: float


class StatusSlice(BaseModel):
    status: str
    label: str
    count: int


class CategorySlice(BaseModel):
    category_id: int | None = None
    name: str
    count: int


class DeptSlice(BaseModel):
    dept_id: int | None = None
    name: str
    count: int


class TrendPoint(BaseModel):
    month: str
    count: int


class WarrantyItem(BaseModel):
    id: int
    asset_no: str
    name: str
    category_name: str | None = None
    dept_name: str | None = None
    custodian_name: str | None = None
    warranty_end: date
    days_left: int


class RecentAssetItem(BaseModel):
    id: int
    asset_no: str
    name: str
    category_name: str | None = None
    dept_name: str | None = None
    status: str
    status_label: str
    created_at: datetime


class DashboardPeriod(BaseModel):
    months: int
    start_date: date
    new_assets: int
    inbound: int
    requisition: int


class DashboardDeptOption(BaseModel):
    id: int
    parent_id: int | None = None
    name: str
    level: int


class DashboardSummaryOut(BaseModel):
    scope: str
    metrics: DashboardMetrics
    status_distribution: list[StatusSlice]
    category_distribution: list[CategorySlice]
    dept_distribution: list[DeptSlice]
    purchase_trend: list[TrendPoint]
    warranty_expiring: list[WarrantyItem]
    recent_assets: list[RecentAssetItem]
    data_scope_label: str
    period: DashboardPeriod
    dept_options: list[DashboardDeptOption]
    dept_id: int | None = None
