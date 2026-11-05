from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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

from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin, now_cst
from app.models.rbac import Dept, User


class AssetInbound(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "ast_asset_inbounds"
    __table_args__ = (
        UniqueConstraint("inbound_no", name="uq_ast_asset_inbounds_inbound_no"),
        Index("ix_ast_asset_inbounds_status", "status"),
        Index("ix_ast_asset_inbounds_inbound_type", "inbound_type"),
        Index("ix_ast_asset_inbounds_dept_id", "dept_id"),
        Index("ix_ast_asset_inbounds_created_by_id", "created_by_id"),
        Index("ix_ast_asset_inbounds_source_inbound_id", "source_inbound_id"),
    )

    inbound_no: Mapped[str] = mapped_column(String(50), nullable=False)
    inbound_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(120))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(120))
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_departments.id", ondelete="SET NULL")
    )
    dept_name: Mapped[str | None] = mapped_column(String(100))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    remark: Mapped[str | None] = mapped_column(String(500))
    source_inbound_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_inbounds.id", ondelete="SET NULL"),
    )

    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    created_by_name: Mapped[str | None] = mapped_column(String(50))
    confirmed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_users.id", ondelete="SET NULL")
    )
    confirmed_by_name: Mapped[str | None] = mapped_column(String(50))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_comment: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(500))

    dept: Mapped[Dept | None] = relationship("Dept", lazy="selectin")
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id], lazy="selectin"
    )
    items: Mapped[list["AssetInboundItem"]] = relationship(
        "AssetInboundItem",
        back_populates="inbound",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AssetInboundItem.id",
    )


class AssetInboundItem(Base, IdMixin):
    __tablename__ = "ast_asset_inbound_items"
    __table_args__ = (
        Index("ix_ast_asset_inbound_items_inbound_id", "inbound_id"),
        Index("ix_ast_asset_inbound_items_category_id", "category_id"),
    )

    inbound_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ast_models.id", ondelete="SET NULL")
    )
    model_name: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_asset_no: Mapped[str | None] = mapped_column(String(40))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    warranty_end: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cst
    )

    inbound: Mapped[AssetInbound] = relationship(
        "AssetInbound", back_populates="items"
    )


class AssetCodeSequence(Base):
    __tablename__ = "ast_asset_code_sequences"

    base_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cst, onupdate=now_cst
    )


class AssetInboundCode(Base, IdMixin):
    __tablename__ = "ast_asset_inbound_codes"
    __table_args__ = (
        Index("ix_ast_asset_inbound_codes_asset_no", "asset_no"),
        Index("ix_ast_asset_inbound_codes_inbound_id", "inbound_id"),
        Index("ix_ast_asset_inbound_codes_item_id", "item_id"),
    )

    inbound_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_inbounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_asset_inbound_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_no: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=now_cst
    )


__all__ = [
    "AssetCodeSequence",
    "AssetInbound",
    "AssetInboundCode",
    "AssetInboundItem",
]
