from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.assets import AssetStatus, CategoryType
from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin, now_cst
from app.models.rbac import Dept, User


class AssetCategory(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_categories"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ast_categories_code"),
        Index("ix_ast_categories_parent_id", "parent_id"),
        Index("ix_ast_categories_path", "path"),
    )

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    category_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CategoryType.HARDWARE,
    )
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(255))

    field_defs: Mapped[list["AssetCategoryField"]] = relationship(
        "AssetCategoryField",
        back_populates="category",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AssetCategoryField.sort",
    )


class AssetCategoryField(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_category_fields"
    __table_args__ = (
        UniqueConstraint("category_id", "field_key", name="uq_ast_category_fields_key"),
        Index("ix_ast_category_fields_category_id", "category_id"),
    )

    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[list[str] | None] = mapped_column(JSON)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(255))

    category: Mapped[AssetCategory] = relationship(
        "AssetCategory",
        back_populates="field_defs",
        lazy="selectin",
    )


class AssetModel(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_models"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ast_models_code"),
        Index("ix_ast_models_category_id", "category_id"),
    )

    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(80))
    spec: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="台")
    depreciation_months: Mapped[int | None] = mapped_column(Integer)
    residual_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0500"),
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(255))

    category: Mapped[AssetCategory] = relationship("AssetCategory", lazy="selectin")


class AssetRequest(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_asset_requests"
    __table_args__ = (
        UniqueConstraint("request_no", name="uq_ast_asset_requests_request_no"),
        Index("ix_ast_asset_requests_asset_id", "asset_id"),
        Index("ix_ast_asset_requests_type", "request_type"),
        Index("ix_ast_asset_requests_status", "status"),
        Index("ix_ast_asset_requests_applicant_id", "applicant_id"),
        Index("ix_ast_asset_requests_expected_return_date", "expected_return_date"),
    )

    request_no: Mapped[str] = mapped_column(String(50), nullable=False)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    include_child: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="RESTRICT"),
        nullable=True,
    )
    asset_no: Mapped[str | None] = mapped_column(String(50))
    asset_name: Mapped[str | None] = mapped_column(String(120))
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    applicant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    applicant_name: Mapped[str] = mapped_column(String(50), nullable=False)
    applicant_dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="RESTRICT"),
    )
    applicant_dept_name: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(String(500))
    expected_return_date: Mapped[date | None] = mapped_column(Date)
    source_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_requests.id", ondelete="SET NULL"),
    )

    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    approver_name: Mapped[str | None] = mapped_column(String(50))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_comment: Mapped[str | None] = mapped_column(String(500))
    approval_stage: Mapped[str | None] = mapped_column(String(16))
    flow_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_approval_flows.id", ondelete="SET NULL")
    )
    flow_name: Mapped[str | None] = mapped_column(String(80))
    current_step_no: Mapped[int | None] = mapped_column(Integer)
    dept_approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    outbound_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    outbound_by_name: Mapped[str | None] = mapped_column(String(50))
    outbound_at: Mapped[datetime | None] = mapped_column(DateTime)
    outbound_location: Mapped[str | None] = mapped_column(String(120))

    return_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirm_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    confirm_by_name: Mapped[str | None] = mapped_column(String(50))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirm_comment: Mapped[str | None] = mapped_column(String(500))

    asset: Mapped[Asset | None] = relationship("Asset", lazy="selectin")
    category: Mapped[AssetCategory] = relationship("AssetCategory", lazy="selectin")
    approvals: Mapped[list["AssetRequestApproval"]] = relationship(
        "AssetRequestApproval",
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AssetRequestApproval.step_no",
    )
    tasks: Mapped[list["ApprovalTask"]] = relationship(
        "ApprovalTask",
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApprovalTask.step_no, ApprovalTask.id",
    )
    applicant: Mapped[User] = relationship(
        "User", foreign_keys=[applicant_id], lazy="selectin"
    )
    applicant_dept: Mapped[Dept | None] = relationship(
        "Dept", foreign_keys=[applicant_dept_id], lazy="selectin"
    )


class AssetRequestApproval(Base, IdMixin, TimestampMixin):
    """领用/借用申请的逐级审批记录，只追加、不修改。"""

    __tablename__ = "ast_request_approvals"
    __table_args__ = (
        Index("ix_ast_request_approvals_request_id", "request_id"),
        Index("ix_ast_request_approvals_request_step", "request_id", "step_no"),
        Index("ix_ast_request_approvals_approver_id", "approver_id"),
    )

    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_approval_tasks.id", ondelete="SET NULL")
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    step_code: Mapped[str] = mapped_column(String(16), nullable=False)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    approver_name: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(String(500))
    operated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cst)

    request: Mapped[AssetRequest] = relationship(
        "AssetRequest", back_populates="approvals"
    )


class AssetRequestSetting(Base, IdMixin, TimestampMixin, VersionMixin):
    """申请审批流程的全局开关（单行）。"""

    __tablename__ = "ast_request_settings"

    dept_approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    updated_by_name: Mapped[str | None] = mapped_column(String(50))


class AssetHistory(Base, IdMixin):
    """资产状态变更快照，只追加、不提供删除入口。"""

    __tablename__ = "ast_asset_histories"
    __table_args__ = (
        Index("ix_ast_asset_histories_asset_id", "asset_id"),
        Index("ix_ast_asset_histories_request_id", "request_id"),
        Index("ix_ast_asset_histories_created_at", "created_at"),
    )

    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_requests.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    action_label: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    before_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    operator_name: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_cst)


class Asset(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_assets"
    __table_args__ = (
        UniqueConstraint(
            "asset_no", "void_seq", name="uq_ast_assets_asset_no_void_seq"
        ),
        Index("ix_ast_assets_category_id", "category_id"),
        Index("ix_ast_assets_model_id", "model_id"),
        Index("ix_ast_assets_dept_id", "dept_id"),
        Index("ix_ast_assets_custodian_id", "custodian_id"),
        Index("ix_ast_assets_status", "status"),
        Index("ix_ast_assets_warranty_end", "warranty_end"),
        Index("ix_ast_assets_deleted_at", "deleted_at"),
    )

    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_models.id", ondelete="RESTRICT"),
    )
    serial_no: Mapped[str | None] = mapped_column(String(120))
    mac_address: Mapped[str | None] = mapped_column(String(64))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    supplier: Mapped[str | None] = mapped_column(String(120))
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    warranty_end: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(120))
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="RESTRICT"),
    )
    custodian_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AssetStatus.PENDING_STOCK,
    )
    custom_fields: Mapped[dict | None] = mapped_column(JSON)
    remark: Mapped[str | None] = mapped_column(String(255))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    void_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    voided_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="SET NULL"),
    )
    voided_by_name: Mapped[str | None] = mapped_column(String(50))
    void_reason: Mapped[str | None] = mapped_column(String(500))

    category: Mapped[AssetCategory] = relationship("AssetCategory", lazy="selectin")
    model: Mapped[AssetModel | None] = relationship("AssetModel", lazy="selectin")
    dept: Mapped[Dept | None] = relationship("Dept", lazy="selectin")
    custodian: Mapped[User | None] = relationship(
        "User", foreign_keys=[custodian_id], lazy="selectin"
    )


class AssetAttachment(Base, IdMixin, TimestampMixin):
    __tablename__ = "ast_asset_attachments"
    __table_args__ = (
        Index("ix_ast_asset_attachments_asset_id", "asset_id"),
        Index("ix_ast_asset_attachments_deleted_at", "deleted_at"),
    )

    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="FILE")
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="SET NULL"),
    )
    uploaded_by_name: Mapped[str | None] = mapped_column(String(80))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    asset: Mapped[Asset] = relationship("Asset", lazy="selectin")


__all__ = [
    "Asset",
    "AssetAttachment",
    "AssetCategory",
    "AssetCategoryField",
    "AssetHistory",
    "AssetModel",
    "AssetRequest",
    "AssetRequestApproval",
    "AssetRequestSetting",
]
