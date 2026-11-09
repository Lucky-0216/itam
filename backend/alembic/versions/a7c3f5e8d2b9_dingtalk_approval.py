"""dingtalk approval integration: config fields and approval link records

Revision ID: a7c3f5e8d2b9
Revises: e8f4c2a9d1b6
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3f5e8d2b9"
down_revision: Union[str, Sequence[str], None] = "e8f4c2a9d1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("approval_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("requisition_process_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("borrow_process_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("transfer_process_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("callback_token_encrypted", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "sys_dingtalk_configs",
        sa.Column("callback_aes_key_encrypted", sa.String(length=1024), nullable=True),
    )

    op.create_table(
        "ast_dingtalk_approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=True),
        sa.Column("transfer_id", sa.BigInteger(), nullable=True),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("doc_no", sa.String(length=50), nullable=True),
        sa.Column("process_instance_id", sa.String(length=64), nullable=False),
        sa.Column("process_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("originator_userid", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("finish_time", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ast_dingtalk_approvals")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ast_asset_requests.id"],
            name=op.f("fk_ast_dingtalk_approvals_request_id_ast_asset_requests"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["ast_asset_transfers.id"],
            name=op.f("fk_ast_dingtalk_approvals_transfer_id_ast_asset_transfers"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "process_instance_id",
            name=op.f("uq_ast_dingtalk_approvals_process_instance_id"),
        ),
    )
    op.create_index(
        "ix_ast_dingtalk_approvals_request_id",
        "ast_dingtalk_approvals",
        ["request_id"],
    )
    op.create_index(
        "ix_ast_dingtalk_approvals_transfer_id",
        "ast_dingtalk_approvals",
        ["transfer_id"],
    )
    op.create_index(
        "ix_ast_dingtalk_approvals_status",
        "ast_dingtalk_approvals",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ast_dingtalk_approvals_status", table_name="ast_dingtalk_approvals")
    op.drop_index("ix_ast_dingtalk_approvals_transfer_id", table_name="ast_dingtalk_approvals")
    op.drop_index("ix_ast_dingtalk_approvals_request_id", table_name="ast_dingtalk_approvals")
    op.drop_table("ast_dingtalk_approvals")
    op.drop_column("sys_dingtalk_configs", "callback_aes_key_encrypted")
    op.drop_column("sys_dingtalk_configs", "callback_token_encrypted")
    op.drop_column("sys_dingtalk_configs", "transfer_process_code")
    op.drop_column("sys_dingtalk_configs", "borrow_process_code")
    op.drop_column("sys_dingtalk_configs", "requisition_process_code")
    op.drop_column("sys_dingtalk_configs", "approval_enabled")
