from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.asset import Asset, AssetCategory, AssetModel
from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin, now_cst
from app.models.dingtalk import DingTalkApproval
from app.models.rbac import Dept, User


class AssetTransfer(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_asset_transfers"
    __table_args__ = (
        UniqueConstraint("transfer_no", name="uq_ast_asset_transfers_transfer_no"),
        Index("ix_ast_asset_transfers_asset_id", "asset_id"),
        Index("ix_ast_asset_transfers_status", "status"),
        Index("ix_ast_asset_transfers_from_dept_id", "from_dept_id"),
        Index("ix_ast_asset_transfers_applicant_id", "applicant_id"),
    )

    transfer_no: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    from_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    from_dept_name: Mapped[str | None] = mapped_column(String(100))
    from_custodian_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    from_custodian_name: Mapped[str | None] = mapped_column(String(50))
    from_location: Mapped[str | None] = mapped_column(String(120))

    to_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    to_dept_name: Mapped[str | None] = mapped_column(String(100))
    to_custodian_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    to_custodian_name: Mapped[str | None] = mapped_column(String(50))
    to_location: Mapped[str | None] = mapped_column(String(120))

    reason: Mapped[str | None] = mapped_column(String(500))
    applicant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    applicant_name: Mapped[str] = mapped_column(String(50), nullable=False)
    applicant_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    applicant_dept_name: Mapped[str | None] = mapped_column(String(100))

    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    approver_name: Mapped[str | None] = mapped_column(String(50))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_comment: Mapped[str | None] = mapped_column(String(500))

    completed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    completed_by_name: Mapped[str | None] = mapped_column(String(50))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_comment: Mapped[str | None] = mapped_column(String(500))

    asset: Mapped[Asset] = relationship("Asset", lazy="selectin")
    applicant: Mapped[User] = relationship(
        "User", foreign_keys=[applicant_id], lazy="selectin"
    )
    dingtalk_approval: Mapped[DingTalkApproval | None] = relationship(
        primaryjoin=(
            "and_(foreign(DingTalkApproval.transfer_id) == AssetTransfer.id)"
        ),
        uselist=False,
        lazy="selectin",
        viewonly=True,
    )


class AssetScrap(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_asset_scraps"
    __table_args__ = (
        UniqueConstraint("scrap_no", name="uq_ast_asset_scraps_scrap_no"),
        Index("ix_ast_asset_scraps_asset_id", "asset_id"),
        Index("ix_ast_asset_scraps_status", "status"),
        Index("ix_ast_asset_scraps_applicant_id", "applicant_id"),
    )

    scrap_no: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)

    from_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    from_dept_name: Mapped[str | None] = mapped_column(String(100))
    from_custodian_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    from_custodian_name: Mapped[str | None] = mapped_column(String(50))
    from_location: Mapped[str | None] = mapped_column(String(120))

    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    disposal_method: Mapped[str | None] = mapped_column(String(120))
    residual_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    applicant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    applicant_name: Mapped[str] = mapped_column(String(50), nullable=False)
    applicant_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    applicant_dept_name: Mapped[str | None] = mapped_column(String(100))

    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    approver_name: Mapped[str | None] = mapped_column(String(50))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_comment: Mapped[str | None] = mapped_column(String(500))

    completed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    completed_by_name: Mapped[str | None] = mapped_column(String(50))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_comment: Mapped[str | None] = mapped_column(String(500))

    asset: Mapped[Asset] = relationship("Asset", lazy="selectin")
    applicant: Mapped[User] = relationship(
        "User", foreign_keys=[applicant_id], lazy="selectin"
    )


class InventoryTask(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_inventory_tasks"
    __table_args__ = (
        UniqueConstraint("task_no", name="uq_ast_inventory_tasks_task_no"),
        Index("ix_ast_inventory_tasks_status", "status"),
        Index("ix_ast_inventory_tasks_created_by_id", "created_by_id"),
    )

    task_no: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)

    scope_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    scope_dept_name: Mapped[str | None] = mapped_column(String(100))
    include_child: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scope_category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_categories.id", ondelete="SET NULL")
    )
    scope_category_name: Mapped[str | None] = mapped_column(String(100))
    include_child_category: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    planned_date: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(500))

    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    created_by_name: Mapped[str | None] = mapped_column(String(50))

    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id], lazy="selectin"
    )


class InventoryItem(Base, IdMixin):
    __tablename__ = "ast_inventory_items"
    __table_args__ = (
        UniqueConstraint("task_id", "asset_id", name="uq_ast_inventory_items_task_asset"),
        Index("ix_ast_inventory_items_task_id", "task_id"),
        Index("ix_ast_inventory_items_asset_id", "asset_id"),
        Index("ix_ast_inventory_items_result", "result"),
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_inventory_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_name: Mapped[str | None] = mapped_column(String(100))
    dept_name: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(120))
    custodian_name: Mapped[str | None] = mapped_column(String(50))
    expected_status: Mapped[str] = mapped_column(String(20), nullable=False)

    result: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    actual_location: Mapped[str | None] = mapped_column(String(120))
    remark: Mapped[str | None] = mapped_column(String(500))
    checked_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    checked_by_name: Mapped[str | None] = mapped_column(String(50))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cst
    )


class InventoryAdjustment(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_inventory_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "adjustment_no", name="uq_ast_inventory_adjustments_adjustment_no"
        ),
        Index("ix_ast_inventory_adjustments_task_id", "task_id"),
        Index("ix_ast_inventory_adjustments_status", "status"),
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_inventory_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    task_no: Mapped[str] = mapped_column(String(50), nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    adjustment_no: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    surplus_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500))

    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    requested_by_name: Mapped[str | None] = mapped_column(String(50))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cst
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    reviewed_by_name: Mapped[str | None] = mapped_column(String(50))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_comment: Mapped[str | None] = mapped_column(String(500))


class InventorySurplus(Base, IdMixin, TimestampMixin):
    __tablename__ = "ast_inventory_surplus"
    __table_args__ = (
        Index("ix_ast_inventory_surplus_task_id", "task_id"),
        Index("ix_ast_inventory_surplus_asset_no", "asset_no"),
        Index("ix_ast_inventory_surplus_applied_at", "applied_at"),
    )

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_inventory_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_name: Mapped[str | None] = mapped_column(String(100))
    model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_models.id", ondelete="SET NULL")
    )
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    dept_name: Mapped[str | None] = mapped_column(String(100))
    serial_no: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    remark: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    created_by_name: Mapped[str | None] = mapped_column(String(50))
    created_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_assets.id", ondelete="SET NULL")
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)

    category: Mapped[AssetCategory] = relationship("AssetCategory", lazy="selectin")
    dept: Mapped[Dept | None] = relationship("Dept", lazy="selectin")
    model: Mapped[AssetModel | None] = relationship("AssetModel", lazy="selectin")


__all__ = [
    "AssetScrap",
    "AssetTransfer",
    "InventoryAdjustment",
    "InventoryItem",
    "InventorySurplus",
    "InventoryTask",
]
