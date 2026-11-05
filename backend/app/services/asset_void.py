from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import ACTIVE_REQUEST_STATUSES
from app.core.asset_ops import (
    SCRAP_ACTIVE_STATUSES,
    TRANSFER_ACTIVE_STATUSES,
    InventoryStatus,
)
from app.core.assets import AssetStatus
from app.core.exceptions import BizError
from app.core.maintenance import MAINTENANCE_ACTIVE_STATUSES
from app.models import (
    Asset,
    AssetHistory,
    AssetMaintenance,
    AssetRequest,
    AssetScrap,
    AssetTransfer,
    InventoryItem,
    InventoryTask,
    User,
)
from app.models.base import now_cst
from app.services.asset_snapshot import asset_snapshot

VOIDABLE_STATUSES = (AssetStatus.PENDING_STOCK, AssetStatus.IN_STOCK)


def assert_voidable(asset: Asset) -> None:
    if asset.status == AssetStatus.VOIDED or asset.deleted_at is not None:
        raise BizError("资产已作废，请勿重复操作")
    if asset.status not in VOIDABLE_STATUSES:
        raise BizError(
            f"资产当前为「{asset.status}」状态，无法直接作废，请先归还或走完业务流程"
        )


async def ensure_no_active_business(session: AsyncSession, asset_id: int) -> None:
    checks = (
        (
            AssetRequest.id,
            AssetRequest.asset_id == asset_id,
            AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES),
            "该资产存在处理中的领用/借用单据，请先处理后再作废",
        ),
        (
            AssetTransfer.id,
            AssetTransfer.asset_id == asset_id,
            AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
            "该资产存在处理中的调拨单，请先处理后再作废",
        ),
        (
            AssetScrap.id,
            AssetScrap.asset_id == asset_id,
            AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
            "该资产存在处理中的报废单，请先处理后再作废",
        ),
        (
            AssetMaintenance.id,
            AssetMaintenance.asset_id == asset_id,
            AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES),
            "该资产存在处理中的维修工单，请先处理后再作废",
        ),
    )
    for column, *conditions, message in checks:
        found = await session.scalar(select(column).where(*conditions).limit(1))
        if found is not None:
            raise BizError(message)

    active_inventory = await session.scalar(
        select(InventoryItem.id)
        .join(InventoryTask, InventoryTask.id == InventoryItem.task_id)
        .where(
            InventoryItem.asset_id == asset_id,
            InventoryTask.status == InventoryStatus.IN_PROGRESS,
        )
        .limit(1)
    )
    if active_inventory is not None:
        raise BizError("该资产正在盘点中，请先完成盘点后再作废")


async def next_void_seq(session: AsyncSession, asset_no: str) -> int:
    max_seq = await session.scalar(
        select(func.max(Asset.void_seq)).where(
            func.lower(Asset.asset_no) == asset_no.casefold()
        )
    )
    return int(max_seq or 0) + 1


async def apply_void(
    session: AsyncSession,
    asset: Asset,
    *,
    reason: str,
    operator: User,
    action: str,
    action_label: str,
    summary: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before = asset_snapshot(asset)
    from_status = asset.status
    now = now_cst()
    asset.void_seq = await next_void_seq(session, asset.asset_no)
    asset.status = AssetStatus.VOIDED
    asset.deleted_at = now
    asset.voided_at = now
    asset.voided_by_id = operator.id
    asset.voided_by_name = operator.real_name or operator.username
    asset.void_reason = reason
    await session.flush()
    after = asset_snapshot(asset)
    session.add(
        AssetHistory(
            asset_id=asset.id,
            action=action,
            action_label=action_label,
            from_status=from_status,
            to_status=AssetStatus.VOIDED,
            before_snapshot=before,
            after_snapshot=after,
            operator_id=operator.id,
            operator_name=operator.real_name or operator.username,
            summary=summary,
        )
    )
    return before, after
