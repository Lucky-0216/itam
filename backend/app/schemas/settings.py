from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import CST


class BrandingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    site_name: str = Field(min_length=1, max_length=60)
    site_subtitle: str = Field(default="", max_length=80)
    brand_mark_text: str = Field(default="IT", max_length=8)
    login_footer_text: str = Field(default="", max_length=200)
    dashboard_welcome: str = Field(default="", max_length=300)


class BrandingOut(BrandingUpdate):
    logo_url: str = ""
    background_url: str = ""
    updated_at: datetime | None = None


class AnnouncementIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    level: Literal["INFO", "IMPORTANT", "WARNING"] = "INFO"
    is_active: bool = True
    start_at: datetime | None = None
    end_at: datetime | None = None
    sort: int = Field(default=0, ge=-9999, le=9999)

    @field_validator("start_at", "end_at")
    @classmethod
    def _to_cst_naive(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(CST).replace(tzinfo=None)
        return value


class AnnouncementOut(BaseModel):
    id: int
    title: str
    content: str
    level: str
    level_label: str
    is_active: bool
    start_at: datetime | None = None
    end_at: datetime | None = None
    sort: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
