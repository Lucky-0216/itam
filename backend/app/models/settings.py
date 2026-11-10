from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class SysSetting(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_settings"

    setting_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    value: Mapped[dict | list | None] = mapped_column(JSON)


class Announcement(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_announcements"
    __table_args__ = (Index("ix_sys_announcements_is_active", "is_active"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_at: Mapped[datetime | None] = mapped_column(DateTime)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    created_by_name: Mapped[str | None] = mapped_column(String(50))


__all__ = ["Announcement", "SysSetting"]
