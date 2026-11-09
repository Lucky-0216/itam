from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class AssetDomain(Base, IdMixin, TimestampMixin):
    __tablename__ = "ast_domains"
    __table_args__ = (UniqueConstraint("code", name="uq_ast_domains_code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


__all__ = ["AssetDomain"]
