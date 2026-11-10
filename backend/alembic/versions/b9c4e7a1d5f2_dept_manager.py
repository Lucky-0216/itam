"""department manager permissions and menu

Revision ID: b9c4e7a1d5f2
Revises: f7a1c9d2e6b3
Create Date: 2026-11-09
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c4e7a1d5f2"
down_revision: Union[str, Sequence[str], None] = "f7a1c9d2e6b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CST = timezone(timedelta(hours=8))
VIEW_CODE = "system:dept-manager:view"
UPDATE_CODE = "system:dept-manager:update"


def _now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _menu_id(bind: sa.Connection, code: str) -> int | None:
    return bind.execute(
        sa.text("SELECT id FROM sys_menus WHERE permission_code = :code"),
        {"code": code},
    ).scalar()


def _insert_menu(
    bind: sa.Connection,
    *,
    parent_id: int | None,
    name: str,
    code: str,
    path: str | None,
    component: str | None,
    icon: str | None,
    sort: int,
    menu_type: str,
    visible: int,
) -> int:
    bind.execute(
        sa.text(
            "INSERT INTO sys_menus "
            "(parent_id, name, type, permission_code, path, component, icon, "
            " sort, visible, status, remark, created_at, updated_at) "
            "VALUES (:parent_id, :name, :menu_type, :code, :path, :component, "
            " :icon, :sort, :visible, 1, NULL, :now, :now)"
        ),
        {
            "parent_id": parent_id,
            "name": name,
            "menu_type": menu_type,
            "code": code,
            "path": path,
            "component": component,
            "icon": icon,
            "sort": sort,
            "visible": visible,
            "now": _now(),
        },
    )
    return int(_menu_id(bind, code))


def _target_role_ids(bind: sa.Connection) -> list[int]:
    return list(
        bind.execute(
            sa.text(
                "SELECT DISTINCT r.id FROM sys_roles r "
                "WHERE r.code IN ('ASSET_ADMIN', 'SUPER_ADMIN') "
                "OR EXISTS ("
                "  SELECT 1 FROM sys_role_menus rm "
                "  JOIN sys_menus m ON m.id = rm.menu_id "
                "  WHERE rm.role_id = r.id AND m.permission_code = 'system:org:view'"
                ")"
            )
        )
        .scalars()
        .all()
    )


def _grant(bind: sa.Connection, role_ids: list[int], menu_id: int) -> None:
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
    bind = op.get_bind()
    menu_id = _menu_id(bind, VIEW_CODE)
    if menu_id is None:
        system_id = bind.execute(
            sa.text("SELECT id FROM sys_menus WHERE permission_code = 'system:view'")
        ).scalar()
        menu_id = _insert_menu(
            bind,
            parent_id=system_id,
            name="部门负责人",
            code=VIEW_CODE,
            path="/system/dept-managers",
            component="system/dept-managers/index",
            icon="UserFilled",
            sort=15,
            menu_type="MENU",
            visible=1,
        )
    update_id = _menu_id(bind, UPDATE_CODE)
    if update_id is None:
        update_id = _insert_menu(
            bind,
            parent_id=menu_id,
            name="指定部门负责人",
            code=UPDATE_CODE,
            path=None,
            component=None,
            icon=None,
            sort=10,
            menu_type="BUTTON",
            visible=0,
        )
    role_ids = _target_role_ids(bind)
    _grant(bind, role_ids, menu_id)
    _grant(bind, role_ids, update_id)


def downgrade() -> None:
    bind = op.get_bind()
    update_id = _menu_id(bind, UPDATE_CODE)
    menu_id = _menu_id(bind, VIEW_CODE)
    for target in (update_id, menu_id):
        if target is None:
            continue
        bind.execute(
            sa.text("DELETE FROM sys_role_menus WHERE menu_id = :menu_id"),
            {"menu_id": target},
        )
        bind.execute(sa.text("DELETE FROM sys_menus WHERE id = :menu_id"), {"menu_id": target})
