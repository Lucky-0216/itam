"""dingtalk roster sync config, logs and dingtalk fields on users/depts

Revision ID: e8f4c2a9d1b6
Revises: b5d9f3a1c2e7
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f4c2a9d1b6"
down_revision: Union[str, Sequence[str], None] = "b5d9f3a1c2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_dingtalk_configs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, comment="乐观锁版本号"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("corp_id", sa.String(length=128), nullable=False),
        sa.Column("app_key", sa.String(length=128), nullable=False),
        sa.Column("app_secret_encrypted", sa.String(length=1024), nullable=True),
        sa.Column("agent_id", sa.BigInteger(), nullable=True),
        sa.Column("default_role_id", sa.BigInteger(), nullable=True),
        sa.Column("root_dept_id", sa.BigInteger(), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("disable_on_leave", sa.Boolean(), nullable=False),
        sa.Column("match_existing", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("last_sync_message", sa.String(length=1000), nullable=True),
        sa.Column("last_test_at", sa.DateTime(), nullable=True),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_test_message", sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_dingtalk_configs")),
        sa.ForeignKeyConstraint(
            ["default_role_id"],
            ["sys_roles.id"],
            name=op.f("fk_sys_dingtalk_configs_default_role_id_sys_roles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["root_dept_id"],
            ["sys_departments.id"],
            name=op.f("fk_sys_dingtalk_configs_root_dept_id_sys_departments"),
            ondelete="SET NULL",
        ),
    )
    op.create_table(
        "sys_dingtalk_sync_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("config_id", sa.BigInteger(), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("dept_total", sa.Integer(), nullable=False),
        sa.Column("dept_created", sa.Integer(), nullable=False),
        sa.Column("dept_updated", sa.Integer(), nullable=False),
        sa.Column("user_total", sa.Integer(), nullable=False),
        sa.Column("user_created", sa.Integer(), nullable=False),
        sa.Column("user_updated", sa.Integer(), nullable=False),
        sa.Column("user_matched", sa.Integer(), nullable=False),
        sa.Column("user_disabled", sa.Integer(), nullable=False),
        sa.Column("user_skipped", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("operator_name", sa.String(length=50), nullable=True),
        sa.Column("message", sa.String(length=1000), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_dingtalk_sync_logs")),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["sys_dingtalk_configs.id"],
            name=op.f("fk_sys_dingtalk_sync_logs_config_id_sys_dingtalk_configs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["sys_users.id"],
            name=op.f("fk_sys_dingtalk_sync_logs_operator_id_sys_users"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_sys_dingtalk_sync_logs_config_id",
        "sys_dingtalk_sync_logs",
        ["config_id"],
    )
    op.create_index(
        "ix_sys_dingtalk_sync_logs_started_at",
        "sys_dingtalk_sync_logs",
        ["started_at"],
    )

    op.add_column(
        "sys_departments",
        sa.Column("dingtalk_dept_id", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_sys_departments_dingtalk_dept_id",
        "sys_departments",
        ["dingtalk_dept_id"],
    )

    op.add_column(
        "sys_users",
        sa.Column("dingtalk_userid", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "sys_users",
        sa.Column("dingtalk_synced_at", sa.DateTime(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_sys_users_dingtalk_userid", "sys_users", ["dingtalk_userid"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_sys_users_dingtalk_userid", "sys_users", type_="unique"
    )
    op.drop_column("sys_users", "dingtalk_synced_at")
    op.drop_column("sys_users", "dingtalk_userid")
    op.drop_constraint(
        "uq_sys_departments_dingtalk_dept_id", "sys_departments", type_="unique"
    )
    op.drop_column("sys_departments", "dingtalk_dept_id")
    op.drop_index("ix_sys_dingtalk_sync_logs_started_at", table_name="sys_dingtalk_sync_logs")
    op.drop_index("ix_sys_dingtalk_sync_logs_config_id", table_name="sys_dingtalk_sync_logs")
    op.drop_table("sys_dingtalk_sync_logs")
    op.drop_table("sys_dingtalk_configs")
