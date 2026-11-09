"""role resource data permissions and asset domain

Revision ID: d1a6f3c9b7e2
Revises: b8e4d1a7c3f5
Create Date: 2026-11-06
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a6f3c9b7e2"
down_revision: Union[str, Sequence[str], None] = "b8e4d1a7c3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CST = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _menu_id(bind: sa.Connection, permission_code: str) -> int | None:
    return bind.execute(
        sa.text("SELECT id FROM sys_menus WHERE permission_code = :code"),
        {"code": permission_code},
    ).scalar()


def _insert_inbound_buttons(bind: sa.Connection) -> None:
    parent_id = _menu_id(bind, "asset:inbound:view")
    if parent_id is None:
        return
    now = _now()
    buttons = [
        ("asset:inbound:update", "编辑入库单", 40),
        ("asset:inbound:delete", "删除入库单", 50),
    ]
    for code, name, sort in buttons:
        if _menu_id(bind, code) is not None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO sys_menus "
                "(parent_id, name, type, permission_code, path, component, icon, "
                " sort, visible, status, remark, created_at, updated_at) "
                "VALUES (:parent_id, :name, 'BUTTON', :code, NULL, NULL, NULL, "
                " :sort, 0, 1, NULL, :now, :now)"
            ),
            {
                "parent_id": parent_id,
                "name": name,
                "code": code,
                "sort": sort,
                "now": now,
            },
        )


def _copy_inbound_grants(bind: sa.Connection) -> None:
    # 旧码授权平滑迁移：create -> update，cancel -> delete
    pairs = [
        ("asset:inbound:create", "asset:inbound:update"),
        ("asset:inbound:cancel", "asset:inbound:delete"),
    ]
    for old_code, new_code in pairs:
        old_id = _menu_id(bind, old_code)
        new_id = _menu_id(bind, new_code)
        if old_id is None or new_id is None:
            continue
        role_ids = (
            bind.execute(
                sa.text("SELECT role_id FROM sys_role_menus WHERE menu_id = :menu_id"),
                {"menu_id": old_id},
            )
            .scalars()
            .all()
        )
        for role_id in role_ids:
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM sys_role_menus "
                    "WHERE role_id = :role_id AND menu_id = :menu_id"
                ),
                {"role_id": role_id, "menu_id": new_id},
            ).scalar()
            if not exists:
                bind.execute(
                    sa.text(
                        "INSERT INTO sys_role_menus (role_id, menu_id) "
                        "VALUES (:role_id, :menu_id)"
                    ),
                    {"role_id": role_id, "menu_id": new_id},
                )


def _ensure_admin_category(bind: sa.Connection) -> None:
    existing = bind.execute(
        sa.text("SELECT id FROM ast_categories WHERE code = 'ADM-ASSET'")
    ).scalar()
    if existing is not None:
        return
    now = _now()
    bind.execute(
        sa.text(
            "INSERT INTO ast_categories "
            "(parent_id, name, code, category_type, asset_domain, path, level, "
            " sort, safety_stock, status, remark, version, created_at, updated_at) "
            "VALUES (NULL, '行政资产', 'ADM-ASSET', 'HARDWARE', 'ADMIN', '', 1, "
            " 90, 0, 1, '办公家具、电器等非 IT 类行政资产', 1, :now, :now)"
        ),
        {"now": now},
    )
    category_id = bind.execute(
        sa.text("SELECT id FROM ast_categories WHERE code = 'ADM-ASSET'")
    ).scalar()
    bind.execute(
        sa.text("UPDATE ast_categories SET path = :path WHERE id = :id"),
        {"path": f"/{category_id}/", "id": category_id},
    )


def upgrade() -> None:
    op.add_column(
        "ast_categories",
        sa.Column(
            "asset_domain",
            sa.String(length=20),
            nullable=False,
            server_default="IT",
        ),
    )
    op.create_index(
        "ix_ast_categories_asset_domain",
        "ast_categories",
        ["asset_domain"],
        unique=False,
    )

    op.create_table(
        "sys_role_data_permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("resource", sa.String(length=50), nullable=False),
        sa.Column(
            "data_scope",
            sa.String(length=20),
            nullable=False,
            server_default="SELF",
        ),
        sa.Column("asset_domains", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["sys_roles.id"],
            name=op.f("fk_sys_role_data_permissions_role_id_sys_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_role_data_permissions")),
        sa.UniqueConstraint("role_id", "resource", name="uq_role_data_permission"),
    )
    op.create_index(
        "ix_sys_role_data_permissions_role_id",
        "sys_role_data_permissions",
        ["role_id"],
        unique=False,
    )

    bind = op.get_bind()
    _insert_inbound_buttons(bind)
    _copy_inbound_grants(bind)
    _ensure_admin_category(bind)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM sys_menus WHERE permission_code IN (:update, :delete)"),
        {"update": "asset:inbound:update", "delete": "asset:inbound:delete"},
    )
    bind.execute(
        sa.text(
            "DELETE FROM ast_categories WHERE code = 'ADM-ASSET' "
            "AND NOT EXISTS (SELECT 1 FROM ast_assets WHERE category_id = ast_categories.id)"
        )
    )

    op.drop_index(
        "ix_sys_role_data_permissions_role_id",
        table_name="sys_role_data_permissions",
    )
    op.drop_table("sys_role_data_permissions")
    op.drop_index("ix_ast_categories_asset_domain", table_name="ast_categories")
    op.drop_column("ast_categories", "asset_domain")
