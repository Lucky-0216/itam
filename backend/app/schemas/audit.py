from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    module: str
    resource_type: str | None = None
    resource_id: str | None = None
    summary: str | None = None
    method: str | None = None
    path: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    status: str
    created_at: datetime


class AuditLogDetail(AuditLogItem):
    before_data: Any | None = None
    after_data: Any | None = None
    before_labels: dict[str, str] | None = None
    after_labels: dict[str, str] | None = None


class AuditLogPage(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    page_size: int


class AuditFilterOptions(BaseModel):
    modules: list[str]
    actions: list[str]
