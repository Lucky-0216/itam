"""rename direct outbound menu to asset outbound

Revision ID: f7a1c9d2e6b3
Revises: e5c8a1f4b7d2
Create Date: 2026-11-09
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c9d2e6b3"
down_revision: Union[str, Sequence[str], None] = "e5c8a1f4b7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CST = timezone(timedelta(hours=8))
PERMISSION_CODE = "asset:outbound:direct"


def _now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def _update(bind: sa.Connection, *, name: str, sort: int) -> None:
    bind.execute(
        sa.text(
            "UPDATE sys_menus SET name = :name, sort = :sort, updated_at = :now "
            "WHERE permission_code = :code"
        ),
        {"name": name, "sort": sort, "now": _now(), "code": PERMISSION_CODE},
    )


def upgrade() -> None:
    _update(op.get_bind(), name="资产出库", sort=25)


def downgrade() -> None:
    _update(op.get_bind(), name="直接出库", sort=35)
