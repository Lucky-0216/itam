from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import DataScope, DomainScope
from app.models.base import Base, IdMixin, TimestampMixin, VersionMixin
from app.models.domain import AssetDomain

user_roles = Table(
    "sys_user_roles",
    Base.metadata,
    Column("user_id", BigInteger, ForeignKey("sys_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", BigInteger, ForeignKey("sys_roles.id", ondelete="CASCADE"), primary_key=True),
)

role_menus = Table(
    "sys_role_menus",
    Base.metadata,
    Column("role_id", BigInteger, ForeignKey("sys_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("menu_id", BigInteger, ForeignKey("sys_menus.id", ondelete="CASCADE"), primary_key=True),
)

role_depts = Table(
    "sys_role_depts",
    Base.metadata,
    Column("role_id", BigInteger, ForeignKey("sys_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("dept_id", BigInteger, ForeignKey("sys_departments.id", ondelete="CASCADE"), primary_key=True),
)


class Dept(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_departments"
    __table_args__ = (
        UniqueConstraint("code", name="uq_sys_departments_code"),
        UniqueConstraint("ldap_dn", name="uq_sys_departments_ldap_dn"),
        Index("ix_sys_departments_parent_id", "parent_id"),
        Index("ix_sys_departments_path", "path"),
    )

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    leader: Mapped[str | None] = mapped_column(String(50))
    manager_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "sys_users.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_sys_departments_manager_id_sys_users",
        ),
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="local")
    ldap_dn: Mapped[str | None] = mapped_column(String(512))
    ldap_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    dingtalk_dept_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    dingtalk_synced_at: Mapped[datetime | None] = mapped_column(DateTime)

    manager: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[manager_id],
        lazy="selectin",
        post_update=True,
    )

    @property
    def manager_name(self) -> str | None:
        return self.manager.real_name if self.manager else None


class User(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_users"
    __table_args__ = (
        UniqueConstraint("ldap_dn", name="uq_sys_users_ldap_dn"),
        Index("ix_sys_users_dept_id", "dept_id"),
        Index("ix_sys_users_status", "status"),
        Index("ix_sys_users_ldap_uid", "ldap_uid"),
    )

    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_no: Mapped[str | None] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(String(120), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    avatar: Mapped[str | None] = mapped_column(String(255))
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_departments.id", ondelete="RESTRICT"),
    )
    position: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_ip: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    remark: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="local")
    ldap_dn: Mapped[str | None] = mapped_column(String(512))
    ldap_uid: Mapped[str | None] = mapped_column(String(255))
    ldap_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    dingtalk_userid: Mapped[str | None] = mapped_column(String(128), unique=True)
    dingtalk_synced_at: Mapped[datetime | None] = mapped_column(DateTime)

    dept: Mapped[Dept | None] = relationship(
        "Dept",
        foreign_keys=[dept_id],
        lazy="selectin",
    )
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=user_roles,
        lazy="selectin",
    )


class OrgSyncPolicy(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_org_sync_policies"

    source_priority: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ldap,dingtalk,local"
    )
    conflict_strategy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fill_empty"
    )
    protect_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disable_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="own")


class Role(Base, IdMixin, TimestampMixin, VersionMixin):
    __tablename__ = "sys_roles"
    __table_args__ = (UniqueConstraint("code", name="uq_sys_roles_code"),)

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    data_scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DataScope.SELF,
    )
    domain_scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DomainScope.CUSTOM,
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    menus: Mapped[list["Menu"]] = relationship(
        "Menu",
        secondary=role_menus,
        lazy="selectin",
    )
    depts: Mapped[list[Dept]] = relationship(
        "Dept",
        secondary=role_depts,
        lazy="selectin",
    )
    data_permissions: Mapped[list["RoleDataPermission"]] = relationship(
        "RoleDataPermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    domain_grants: Mapped[list["RoleDomain"]] = relationship(
        "RoleDomain",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Menu(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_menus"
    __table_args__ = (
        UniqueConstraint("permission_code", name="uq_sys_menus_permission_code"),
        Index("ix_sys_menus_parent_id", "parent_id"),
        Index("ix_sys_menus_type", "type"),
    )

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_menus.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="MENU")
    permission_code: Mapped[str | None] = mapped_column(String(100))
    path: Mapped[str | None] = mapped_column(String(200))
    component: Mapped[str | None] = mapped_column(String(200))
    icon: Mapped[str | None] = mapped_column(String(50))
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(255))


class RoleFieldPermission(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_role_field_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "resource", "field", name="uq_role_field_scope"),
        Index("ix_sys_role_field_permissions_role_id", "role_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RoleDomain(Base, IdMixin, TimestampMixin):
    __tablename__ = "sys_role_domains"
    __table_args__ = (
        UniqueConstraint("role_id", "domain_id", name="uq_role_domain"),
        Index("ix_sys_role_domains_role_id", "role_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ast_domains.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[Role] = relationship("Role", back_populates="domain_grants")
    domain: Mapped[AssetDomain] = relationship("AssetDomain", lazy="joined")


class RoleDataPermission(Base, IdMixin, TimestampMixin):
    """角色在单个资源上的数据范围；未配置时沿用 Role.data_scope。"""

    __tablename__ = "sys_role_data_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "resource", name="uq_role_data_permission"),
        Index("ix_sys_role_data_permissions_role_id", "role_id"),
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    data_scope: Mapped[str] = mapped_column(String(20), nullable=False, default=DataScope.SELF)
    dept_ids: Mapped[list[int] | None] = mapped_column(JSON)

    role: Mapped[Role] = relationship("Role", back_populates="data_permissions")


__all__ = [
    "Dept",
    "Menu",
    "Role",
    "RoleDataPermission",
    "RoleDomain",
    "RoleFieldPermission",
    "User",
    "role_depts",
    "role_menus",
    "user_roles",
]
