"""钉钉审批对账任务：轮询 RUNNING 的审批实例，兜底回调丢失的场景。"""

import asyncio
import logging

from app.celery_app import celery
from app.core.database import AsyncSessionLocal
from app.services import dingtalk_approval

logger = logging.getLogger("itam.dingtalk.approval")


async def _reconcile() -> dict:
    result: dict = {"configs": 0, "total": 0, "settled": 0, "errors": 0}
    async with AsyncSessionLocal() as session:
        config = await dingtalk_approval.get_approval_config(session)
        if config is None or not config.approval_enabled:
            return result
        if not config.app_secret_encrypted:
            logger.warning("dingtalk approval reconcile skipped: AppSecret 未配置")
            return result
        counts = await dingtalk_approval.reconcile(session, config)
        result["configs"] = 1
        result.update(counts)
    return result


@celery.task(name="app.tasks.dingtalk_approval.reconcile_dingtalk_approvals")
def reconcile_dingtalk_approvals() -> dict:
    return asyncio.run(_reconcile())
