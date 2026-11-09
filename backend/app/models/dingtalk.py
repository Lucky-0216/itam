from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin


class DingTalkConfig(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_dingtalk_configs"

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corp_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    app_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    app_secret_encrypted: Mapped[str | None] = mapped_column(String(1024))
    agent_id: Mapped[int | None] = mapped_column(BigInteger)

    default_role_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_roles.id", ondelete="SET NULL"),
    )
    root_dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="SET NULL"),
    )
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120
    )
    # 钉钉离职成员 → 停用本系统钉钉账号（仅影响 source=dingtalk 的用户）
    disable_on_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 按手机号/邮箱匹配到现有用户时，仅补钉钉字段（dingtalk_userid 等），不改其部门/状态/来源
    match_existing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(20))
    last_sync_message: Mapped[str | None] = mapped_column(String(1000))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_message: Mapped[str | None] = mapped_column(String(1000))

    # ===== 审批对接 =====
    approval_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requisition_process_code: Mapped[str | None] = mapped_column(String(64))
    borrow_process_code: Mapped[str | None] = mapped_column(String(64))
    transfer_process_code: Mapped[str | None] = mapped_column(String(64))
    callback_token_encrypted: Mapped[str | None] = mapped_column(String(1024))
    callback_aes_key_encrypted: Mapped[str | None] = mapped_column(String(1024))


class DingTalkSyncLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_dingtalk_sync_logs"
    __table_args__ = (
        Index("ix_sys_dingtalk_sync_logs_config_id", "config_id"),
        Index("ix_sys_dingtalk_sync_logs_started_at", "started_at"),
    )

    config_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_dingtalk_configs.id", ondelete="SET NULL"),
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
    user_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class DingTalkApproval(Base, IdMixin, TimestampMixin):
    """单据与钉钉审批实例的关联记录"""

    __tablename__ = "ast_dingtalk_approvals"
    __table_args__ = (
        Index("ix_ast_dingtalk_approvals_request_id", "request_id"),
        Index("ix_ast_dingtalk_approvals_transfer_id", "transfer_id"),
        Index("ix_ast_dingtalk_approvals_status", "status"),
    )

    request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_requests.id", ondelete="SET NULL"),
    )
    transfer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_transfers.id", ondelete="SET NULL"),
    )
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_no: Mapped[str | None] = mapped_column(String(50))
    process_instance_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    process_code: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    title: Mapped[str | None] = mapped_column(String(200))
    originator_userid: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[str | None] = mapped_column(String(20))
    finish_time: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(String(1000))


__all__ = ["DingTalkConfig", "DingTalkSyncLog", "DingTalkApproval"]
