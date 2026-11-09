"""asset creator for role-scoped data permissions

Revision ID: e2b7c4f8a1d6
Revises: d1a6f3c9b7e2
Create Date: 2026-11-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b7c4f8a1d6"
down_revision: Union[str, Sequence[str], None] = "d1a6f3c9b7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ast_assets",
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "ast_assets",
        sa.Column("created_by_name", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_ast_assets_created_by_id",
        "ast_assets",
        ["created_by_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_ast_assets_created_by_id_sys_users"),
        "ast_assets",
        "sys_users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 历史资产回填：按最新入库编码映射到入库单创建人
    op.get_bind().execute(
        sa.text(
            "UPDATE ast_assets a "
            "JOIN ("
            "  SELECT asset_no, MAX(id) AS id FROM ast_asset_inbound_codes "
            "  GROUP BY asset_no"
            ") latest ON latest.asset_no = a.asset_no "
            "JOIN ast_asset_inbound_codes c ON c.id = latest.id "
            "JOIN ast_asset_inbounds i ON i.id = c.inbound_id "
            "SET a.created_by_id = i.created_by_id, "
            "    a.created_by_name = i.created_by_name "
            "WHERE a.created_by_id IS NULL AND a.deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ast_assets_created_by_id_sys_users"),
        "ast_assets",
        type_="foreignkey",
    )
    op.drop_index("ix_ast_assets_created_by_id", table_name="ast_assets")
    op.drop_column("ast_assets", "created_by_name")
    op.drop_column("ast_assets", "created_by_id")
