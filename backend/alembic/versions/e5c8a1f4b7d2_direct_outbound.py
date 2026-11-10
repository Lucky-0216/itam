"""direct outbound permission and menu

Revision ID: e5c8a1f4b7d2
Revises: a9d4e2c7b1f8
Create Date: 2026-11-09
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c8a1f4b7d2"
down_revision: Union[str, Sequence[str], None] = "a9d4e2c7b1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CST = timezone(timedelta(hours=8))
PERMISSION_CODE = "asset:outbound:direct"


def _now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _menu_id(bind: sa.Connection) -> int | None:
    return bind.execute(
        sa.text("SELECT id FROM sys_menus WHERE permission_code = :code"),
        {"code": PERMISSION_CODE},
    ).scalar()


def _ensure_menu(bind: sa.Connection) -> None:
    if _menu_id(bind) is not None:
        return
    parent_id = bind.execute(
        sa.text("SELECT id FROM sys_menus WHERE permission_code = 'asset:view'")
    ).scalar()
    now = _now()
    bind.execute(
        sa.text(
            "INSERT INTO sys_menus "
            "(parent_id, name, type, permission_code, path, component, icon, "
            " sort, visible, status, remark, created_at, updated_at) "
            "VALUES (:parent_id, '直接出库', 'MENU', :code, "
            " '/assets/direct-outbound', 'assets/direct-outbound/index', "
            " 'Promotion', 35, 1, 1, NULL, :now, :now)"
        ),
        {"parent_id": parent_id, "code": PERMISSION_CODE, "now": now},
    )


def _grant_admin_roles(bind: sa.Connection) -> None:
    menu_id = _menu_id(bind)
    if menu_id is None:
        return
    role_ids = (
        bind.execute(
            sa.text(
                "SELECT id FROM sys_roles WHERE code IN ('ASSET_ADMIN', 'SUPER_ADMIN')"
            )
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
            {"role_id": role_id, "menu_id": menu_id},
        ).scalar()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO sys_role_menus (role_id, menu_id) "
                    "VALUES (:role_id, :menu_id)"
                ),
                {"role_id": role_id, "menu_id": menu_id},
            )


def upgrade() -> None:
    _ensure_menu(op.get_bind())
    _grant_admin_roles(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    menu_id = _menu_id(bind)
    if menu_id is None:
        return
    bind.execute(
        sa.text("DELETE FROM sys_role_menus WHERE menu_id = :menu_id"),
        {"menu_id": menu_id},
    )
    bind.execute(sa.text("DELETE FROM sys_menus WHERE id = :menu_id"), {"menu_id": menu_id})
