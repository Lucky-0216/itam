from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin


class LdapConfig(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_ldap_configs"

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    server_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    server_port: Mapped[int] = mapped_column(Integer, nullable=False, default=389)
    use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_dn: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    bind_dn: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    bind_password_encrypted: Mapped[str | None] = mapped_column(String(1024))

    user_filter: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="(&(objectCategory=person)(objectClass=user))",
    )
    dept_filter: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="(objectClass=organizationalUnit)",
    )
    username_attribute: Mapped[str] = mapped_column(
        String(80), nullable=False, default="sAMAccountName"
    )
    real_name_attribute: Mapped[str] = mapped_column(
        String(80), nullable=False, default="displayName"
    )
    email_attribute: Mapped[str] = mapped_column(String(80), nullable=False, default="mail")
    phone_attribute: Mapped[str] = mapped_column(
        String(80), nullable=False, default="telephoneNumber"
    )
    employee_no_attribute: Mapped[str] = mapped_column(
        String(80), nullable=False, default="employeeID"
    )

    default_role_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_roles.id", ondelete="SET NULL"),
    )
    root_dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="SET NULL"),
    )
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(20))
    last_sync_message: Mapped[str | None] = mapped_column(String(1000))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_message: Mapped[str | None] = mapped_column(String(1000))


class LdapSyncLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_ldap_sync_logs"
    __table_args__ = (
        Index("ix_sys_ldap_sync_logs_config_id", "config_id"),
        Index("ix_sys_ldap_sync_logs_started_at", "started_at"),
    )

    config_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_ldap_configs.id", ondelete="SET NULL"),
    )
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    dept_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dept_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dept_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dept_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    operator_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="SET NULL"),
    )
    operator_name: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str | None] = mapped_column(String(1000))
    details: Mapped[list | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)


__all__ = ["LdapConfig", "LdapSyncLog"]
