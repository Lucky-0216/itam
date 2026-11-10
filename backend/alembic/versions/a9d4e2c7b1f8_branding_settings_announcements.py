"""branding settings and announcements

Revision ID: a9d4e2c7b1f8
Revises: f2a7c5e91d34
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e2c7b1f8"
down_revision: Union[str, Sequence[str], None] = "f2a7c5e91d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("setting_key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_settings")),
        sa.UniqueConstraint("setting_key", name="uq_sys_settings_key"),
    )
    op.create_table(
        "sys_announcements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="INFO"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_name", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["sys_users.id"],
            name=op.f("fk_sys_announcements_created_by_id_sys_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_announcements")),
    )
    op.create_index(
        "ix_sys_announcements_is_active",
        "sys_announcements",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sys_announcements_is_active", table_name="sys_announcements")
    op.drop_table("sys_announcements")
    op.drop_table("sys_settings")
