import asyncio
import logging

from sqlalchemy import select

from app.celery_app import celery
from app.core.database import AsyncSessionLocal
from app.models import DingTalkConfig
from app.models.base import now_cst
from app.services.dingtalk_sync_service import (
    DingTalkSyncService,
    due_for_sync,
)

logger = logging.getLogger("itam.dingtalk")


async def _execute_sync(
    config_id: int,
    trigger_type: str,
    operator_id: int | None = None,
    operator_name: str | None = None,
):
    async with AsyncSessionLocal() as session:
        return await DingTalkSyncService(session).run_sync(
            config_id=config_id,
            trigger_type=trigger_type,
            operator_id=operator_id,
            operator_name=operator_name,
        )


async def run_manual_sync(
    config_id: int,
    operator_id: int | None,
    operator_name: str | None,
) -> None:
    try:
        await _execute_sync(config_id, "MANUAL", operator_id, operator_name)
    except Exception:  # noqa: BLE001 - background task must never crash the loop
        logger.exception("manual DingTalk sync failed (config=%s)", config_id)


@celery.task(name="app.tasks.dingtalk_sync.sync_due_dingtalk")
def sync_due_dingtalk() -> list[int]:
    return asyncio.run(_sync_due())


async def _sync_due() -> list[int]:
    synced: list[int] = []
    async with AsyncSessionLocal() as session:
        configs = list(
            (
                await session.execute(
                    select(DingTalkConfig).where(DingTalkConfig.enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        now = now_cst()
        for config in configs:
            if not due_for_sync(config, now):
                continue
            try:
                await DingTalkSyncService(session).run_sync(
                    config_id=config.id,
                    trigger_type="SCHEDULED",
                    operator_name="系统计划任务",
                )
                synced.append(config.id)
            except Exception:  # noqa: BLE001 - one failure must not block others
                logger.exception("scheduled DingTalk sync failed (config=%s)", config.id)
    return synced
