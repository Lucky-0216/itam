"""multi-source org: sync policy table and dept sync timestamps

Revision ID: b8e4d1a7c3f5
Revises: a7c3f5e8d2b9
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e4d1a7c3f5"
down_revision: Union[str, Sequence[str], None] = "a7c3f5e8d2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_org_sync_policies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "source_priority",
            sa.String(length=50),
            nullable=False,
            server_default="ldap,dingtalk,local",
        ),
        sa.Column(
            "conflict_strategy",
            sa.String(length=20),
            nullable=False,
            server_default="fill_empty",
        ),
        sa.Column("protect_local", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "disable_scope",
            sa.String(length=20),
            nullable=False,
            server_default="own",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_org_sync_policies")),
    )
    op.add_column(
        "sys_departments",
        sa.Column("ldap_synced_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "sys_departments",
        sa.Column("dingtalk_synced_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "sys_ldap_sync_logs",
        sa.Column("dept_skipped", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sys_dingtalk_sync_logs",
        sa.Column("dept_skipped", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("sys_dingtalk_sync_logs", "dept_skipped")
    op.drop_column("sys_ldap_sync_logs", "dept_skipped")
    op.drop_column("sys_departments", "dingtalk_synced_at")
    op.drop_column("sys_departments", "ldap_synced_at")
    op.drop_table("sys_org_sync_policies")
