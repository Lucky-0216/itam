"""asset void status, code release and inbound correction

Revision ID: b5d9f3a1c2e7
Revises: c4e9a1b7d2f3
Create Date: 2026-11-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5d9f3a1c2e7"
down_revision: Union[str, Sequence[str], None] = "c4e9a1b7d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ast_assets",
        sa.Column(
            "void_seq", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "ast_assets", sa.Column("voided_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "ast_assets", sa.Column("voided_by_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "ast_assets", sa.Column("voided_by_name", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "ast_assets", sa.Column("void_reason", sa.String(length=500), nullable=True)
    )
    op.create_foreign_key(
        "fk_ast_assets_voided_by_id_sys_users",
        "ast_assets",
        "sys_users",
        ["voided_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("uq_ast_assets_asset_no", "ast_assets", type_="unique")
    op.create_unique_constraint(
        "uq_ast_assets_asset_no_void_seq",
        "ast_assets",
        ["asset_no", "void_seq"],
    )
    op.execute(
        sa.text(
            "UPDATE ast_assets SET status = 'VOIDED', void_seq = 1, "
            "voided_at = deleted_at, void_reason = '历史删除迁移' "
            "WHERE deleted_at IS NOT NULL"
        )
    )

    op.add_column(
        "ast_asset_inbounds",
        sa.Column("source_inbound_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ast_asset_inbounds_source_inbound_id_ast_asset_inbounds",
        "ast_asset_inbounds",
        "ast_asset_inbounds",
        ["source_inbound_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ast_asset_inbounds_source_inbound_id",
        "ast_asset_inbounds",
        ["source_inbound_id"],
    )

    op.drop_constraint(
        "uq_ast_asset_inbound_codes_asset_no",
        "ast_asset_inbound_codes",
        type_="unique",
    )
    op.create_index(
        "ix_ast_asset_inbound_codes_asset_no",
        "ast_asset_inbound_codes",
        ["asset_no"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ast_asset_inbound_codes_asset_no",
        table_name="ast_asset_inbound_codes",
    )
    op.create_unique_constraint(
        "uq_ast_asset_inbound_codes_asset_no",
        "ast_asset_inbound_codes",
        ["asset_no"],
    )

    op.drop_index(
        "ix_ast_asset_inbounds_source_inbound_id",
        table_name="ast_asset_inbounds",
    )
    op.drop_constraint(
        "fk_ast_asset_inbounds_source_inbound_id_ast_asset_inbounds",
        "ast_asset_inbounds",
        type_="foreignkey",
    )
    op.drop_column("ast_asset_inbounds", "source_inbound_id")

    op.drop_constraint(
        "uq_ast_assets_asset_no_void_seq", "ast_assets", type_="unique"
    )
    op.create_unique_constraint(
        "uq_ast_assets_asset_no", "ast_assets", ["asset_no"]
    )
    op.drop_constraint(
        "fk_ast_assets_voided_by_id_sys_users", "ast_assets", type_="foreignkey"
    )
    op.drop_column("ast_assets", "void_reason")
    op.drop_column("ast_assets", "voided_by_name")
    op.drop_column("ast_assets", "voided_by_id")
    op.drop_column("ast_assets", "voided_at")
    op.drop_column("ast_assets", "void_seq")
