"""role-level asset domains and isolated resource departments

Revision ID: f2a7c5e91d34
Revises: e2b7c4f8a1d6
Create Date: 2026-11-06
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a7c5e91d34"
down_revision: Union[str, Sequence[str], None] = "e2b7c4f8a1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CST = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _domains(value) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item})


def upgrade() -> None:
    op.create_table(
        "ast_domains",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ast_domains")),
        sa.UniqueConstraint("code", name="uq_ast_domains_code"),
    )
    op.add_column(
        "sys_roles",
        sa.Column(
            "domain_scope",
            sa.String(length=20),
            nullable=False,
            server_default="ALL",
        ),
    )
    op.create_table(
        "sys_role_domains",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["sys_roles.id"],
            name=op.f("fk_sys_role_domains_role_id_sys_roles"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"], ["ast_domains.id"],
            name=op.f("fk_sys_role_domains_domain_id_ast_domains"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_role_domains")),
        sa.UniqueConstraint("role_id", "domain_id", name="uq_role_domain"),
    )
    op.create_index(
        "ix_sys_role_domains_role_id", "sys_role_domains", ["role_id"], unique=False
    )
    op.add_column(
        "sys_role_data_permissions",
        sa.Column("dept_ids", sa.JSON(), nullable=True),
    )

    bind = op.get_bind()
    now = _now()
    domain_ids: dict[str, int] = {}
    codes = {"IT", "ADMIN"}
    codes.update(
        bind.execute(sa.text("SELECT DISTINCT asset_domain FROM ast_categories"))
        .scalars()
        .all()
    )
    for code in sorted(codes):
        if not code:
            continue
        builtin = code in {"IT", "ADMIN"}
        name = {"IT": "IT 资产", "ADMIN": "行政资产"}.get(code, code)
        bind.execute(
            sa.text(
                "INSERT INTO ast_domains "
                "(code, name, sort, is_builtin, created_at, updated_at) "
                "VALUES (:code, :name, :sort, :builtin, :now, :now)"
            ),
            {
                "code": code,
                "name": name,
                "sort": 10 if code == "IT" else 20 if code == "ADMIN" else 100,
                "builtin": builtin,
                "now": now,
            },
        )
        domain_ids[code] = bind.execute(
            sa.text("SELECT id FROM ast_domains WHERE code = :code"), {"code": code}
        ).scalar_one()

    role_domains: dict[int, set[str]] = {}
    rows = bind.execute(
        sa.text(
            "SELECT role_id, asset_domains FROM sys_role_data_permissions "
            "WHERE asset_domains IS NOT NULL"
        )
    ).all()
    for role_id, raw_domains in rows:
        domains = set(_domains(raw_domains))
        if domains:
            role_domains.setdefault(role_id, set()).update(domains)

    for role_id, domains in role_domains.items():
        bind.execute(
            sa.text("UPDATE sys_roles SET domain_scope = 'CUSTOM' WHERE id = :id"),
            {"id": role_id},
        )
        for code in sorted(domains):
            domain_id = domain_ids.get(code)
            if domain_id is None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO sys_role_domains "
                    "(role_id, domain_id, created_at, updated_at) "
                    "VALUES (:role_id, :domain_id, :now, :now)"
                ),
                {"role_id": role_id, "domain_id": domain_id, "now": now},
            )

    custom_rows = bind.execute(
        sa.text(
            "SELECT id, role_id FROM sys_role_data_permissions "
            "WHERE data_scope = 'CUSTOM'"
        )
    ).all()
    for permission_id, role_id in custom_rows:
        dept_ids = bind.execute(
            sa.text("SELECT dept_id FROM sys_role_depts WHERE role_id = :role_id"),
            {"role_id": role_id},
        ).scalars().all()
        bind.execute(
            sa.text(
                "UPDATE sys_role_data_permissions SET dept_ids = :dept_ids "
                "WHERE id = :id"
            ),
            {"dept_ids": json.dumps(sorted(dept_ids)), "id": permission_id},
        )

    bind.execute(sa.text("UPDATE sys_roles SET data_scope = 'SELF' WHERE data_scope = 'ROLE'"))
    bind.execute(
        sa.text(
            "UPDATE sys_role_data_permissions SET data_scope = 'SELF' "
            "WHERE data_scope = 'ROLE'"
        )
    )
    op.drop_column("sys_role_data_permissions", "asset_domains")
    op.alter_column(
        "sys_roles",
        "domain_scope",
        existing_type=sa.String(length=20),
        nullable=False,
        server_default="CUSTOM",
    )


def downgrade() -> None:
    op.add_column(
        "sys_role_data_permissions",
        sa.Column("asset_domains", sa.JSON(), nullable=True),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT r.id, d.code FROM sys_roles r "
            "JOIN sys_role_domains rd ON rd.role_id = r.id "
            "JOIN ast_domains d ON d.id = rd.domain_id "
            "WHERE r.domain_scope = 'CUSTOM'"
        )
    ).all()
    domains_by_role: dict[int, list[str]] = {}
    for role_id, code in rows:
        domains_by_role.setdefault(role_id, []).append(code)
    for role_id, domains in domains_by_role.items():
        bind.execute(
            sa.text(
                "UPDATE sys_role_data_permissions SET asset_domains = :domains "
                "WHERE role_id = :role_id"
            ),
            {"domains": json.dumps(sorted(domains)), "role_id": role_id},
        )
    op.drop_column("sys_role_data_permissions", "dept_ids")
    op.drop_index("ix_sys_role_domains_role_id", table_name="sys_role_domains")
    op.drop_table("sys_role_domains")
    op.drop_column("sys_roles", "domain_scope")
    op.drop_table("ast_domains")
