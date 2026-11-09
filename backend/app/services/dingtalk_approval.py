"""钉钉审批对接服务。

渠道选择：钉钉配置启用审批对接、对应单据类型配置了 process_code 且申请人已绑定
dingtalk_userid 时，单据走钉钉审批；否则回退系统内审批（原有逻辑不变）。
回调与对账统一通过 apply_outcome 驱动现有状态机（assert_transition / 状态校验），
不直接写状态、不做权限检查（外部审批结果视为已授权）。
"""

from __future__ import annotations

import logging

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import ApprovalTaskStatus
from app.core.asset_flow import RequestStatus, RequestType, assert_transition
from app.core.asset_ops import TransferStatus
from app.core.exceptions import BizError
from app.core.secrets import decrypt_secret
from app.models import (
    ApprovalTask,
    AssetRequest,
    AssetTransfer,
    DingTalkApproval,
    DingTalkConfig,
    User,
)
from app.models.base import now_cst
from app.services import dingtalk_client
from app.services.audit_service import AuditService
from app.services.txn import commit_or_conflict

logger = logging.getLogger("itam.dingtalk.approval")

DOC_TYPE_REQUISITION = "REQUISITION"
DOC_TYPE_BORROW = "BORROW"
DOC_TYPE_TRANSFER = "TRANSFER"

LINK_RUNNING = "RUNNING"
LINK_APPROVED = "APPROVED"
LINK_REJECTED = "REJECTED"
LINK_TERMINATED = "TERMINATED"

LINK_STATUS_LABELS = {
    LINK_RUNNING: "钉钉审批中",
    LINK_APPROVED: "钉钉已通过",
    LINK_REJECTED: "钉钉已驳回",
    LINK_TERMINATED: "钉钉已撤销",
}

REQUEST_TYPE_TO_DOC_TYPE = {
    RequestType.REQUISITION: DOC_TYPE_REQUISITION,
    RequestType.BORROW: DOC_TYPE_BORROW,
}

_PROCESS_CODE_ATTR = {
    DOC_TYPE_REQUISITION: "requisition_process_code",
    DOC_TYPE_BORROW: "borrow_process_code",
    DOC_TYPE_TRANSFER: "transfer_process_code",
}

_STATUS_CONFLICT_MESSAGE = "单据状态已变化，请刷新后重试"


def channel_enabled(
    config: DingTalkConfig | None, doc_type: str | None, user: User | None
) -> bool:
    if doc_type is None or user is None:
        return False
    if config is None or not config.approval_enabled:
        return False
    process_code = getattr(config, _PROCESS_CODE_ATTR.get(doc_type, ""), None)
    if not process_code:
        return False
    return bool(user.dingtalk_userid)


def _secret(config: DingTalkConfig) -> str:
    if not config.app_secret_encrypted:
        raise BizError("钉钉 AppSecret 未配置，无法发起审批")
    return decrypt_secret(config.app_secret_encrypted)


async def get_approval_config(session: AsyncSession) -> DingTalkConfig | None:
    return (
        await session.execute(
            select(DingTalkConfig).order_by(DingTalkConfig.id).limit(1)
        )
    ).scalar_one_or_none()


def running_link_exists(*, request_id: int | None = None, transfer_id: int | None = None):
    conditions = [DingTalkApproval.status == LINK_RUNNING]
    if request_id is not None:
        conditions.append(DingTalkApproval.request_id == request_id)
    if transfer_id is not None:
        conditions.append(DingTalkApproval.transfer_id == transfer_id)
    return exists(select(DingTalkApproval.id).where(*conditions))


async def has_running_link(
    session: AsyncSession, *, request_id: int | None = None, transfer_id: int | None = None
) -> bool:
    conditions = [DingTalkApproval.status == LINK_RUNNING]
    if request_id is not None:
        conditions.append(DingTalkApproval.request_id == request_id)
    if transfer_id is not None:
        conditions.append(DingTalkApproval.transfer_id == transfer_id)
    return bool(
        await session.scalar(select(DingTalkApproval.id).where(*conditions).limit(1))
    )


async def create_instance(
    session: AsyncSession,
    config: DingTalkConfig,
    *,
    doc_type: str,
    doc_no: str,
    title: str,
    originator_userid: str,
    form_values: list[dict[str, str]],
    request_id: int | None = None,
    transfer_id: int | None = None,
) -> DingTalkApproval:
    """调用钉钉创建审批实例并落关联记录；失败抛 BizError（调用方事务随之回滚）。"""
    process_code = getattr(config, _PROCESS_CODE_ATTR.get(doc_type, ""), None)
    if not process_code:
        raise BizError("未配置该单据类型的钉钉审批模板编码")
    try:
        instance_id = await dingtalk_client.create_process_instance(
            config.app_key,
            _secret(config),
            agent_id=config.agent_id,
            request=dingtalk_client.ApprovalInstanceCreate(
                process_code=process_code,
                originator_userid=originator_userid,
                title=title,
                form_values=form_values,
            ),
        )
    except BizError as exc:
        raise BizError(f"发起钉钉审批失败：{exc.message}") from exc
    link = DingTalkApproval(
        request_id=request_id,
        transfer_id=transfer_id,
        doc_type=doc_type,
        doc_no=doc_no,
        process_instance_id=instance_id,
        process_code=process_code,
        status=LINK_RUNNING,
        title=title,
        originator_userid=originator_userid,
    )
    session.add(link)
    await session.flush()
    return link


async def _skip_pending_tasks(
    session: AsyncSession, request_id: int, comment: str
) -> None:
    rows = list(
        (
            await session.execute(
                select(ApprovalTask).where(
                    ApprovalTask.request_id == request_id,
                    ApprovalTask.status.in_(
                        (ApprovalTaskStatus.PENDING, ApprovalTaskStatus.WAITING)
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for task in rows:
        task.status = ApprovalTaskStatus.SKIPPED
        task.acted_at = now_cst()
        task.comment = comment


async def apply_outcome(
    session: AsyncSession,
    instance_id: str,
    result: str,
    *,
    operator: str = "钉钉审批回调",
    event: str = "callback",
) -> str:
    """按钉钉审批结果驱动单据状态机。

    返回 "applied"（已驱动单据）、"skipped"（链接不存在或已处理）、
    "pending"（未知结果，未处理）。
    """
    link = (
        await session.execute(
            select(DingTalkApproval).where(
                DingTalkApproval.process_instance_id == instance_id
            )
        )
    ).scalar_one_or_none()
    if link is None:
        logger.warning("dingtalk approval callback: unknown instance %s", instance_id)
        return "skipped"
    if link.status != LINK_RUNNING:
        return "skipped"

    if result == "agree":
        target_status = LINK_APPROVED
    elif result == "refuse":
        target_status = LINK_REJECTED
    elif result in ("terminate", "cancel"):
        target_status = LINK_TERMINATED
    else:
        logger.warning(
            "dingtalk approval callback: unknown result %r for %s", result, instance_id
        )
        return "pending"

    audit = AuditService(session)
    now = now_cst()
    if link.request_id is not None:
        request = (
            await session.execute(
                select(AssetRequest)
                .where(AssetRequest.id == link.request_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if request is not None and request.status == RequestStatus.PENDING_APPROVAL:
            module = (
                "资产领用"
                if request.request_type == RequestType.REQUISITION
                else "资产借用"
            )
            if target_status == LINK_APPROVED:
                assert_transition(
                    request.request_type,
                    request.status,
                    RequestStatus.PENDING_OUTBOUND,
                )
                request.status = RequestStatus.PENDING_OUTBOUND
                request.approved_at = now
                request.approver_id = None
                request.approver_name = "钉钉审批"
                request.approval_comment = "钉钉审批通过"
                request.current_step_no = None
                await _skip_pending_tasks(session, request.id, "钉钉审批已通过")
            elif target_status == LINK_REJECTED:
                assert_transition(
                    request.request_type, request.status, RequestStatus.REJECTED
                )
                request.status = RequestStatus.REJECTED
                request.approval_comment = "钉钉审批驳回"
                request.current_step_no = None
                await _skip_pending_tasks(session, request.id, "钉钉审批已驳回")
            else:
                assert_transition(
                    request.request_type, request.status, RequestStatus.CANCELLED
                )
                request.status = RequestStatus.CANCELLED
                request.approval_comment = "钉钉审批已撤销"
                request.current_step_no = None
                await _skip_pending_tasks(session, request.id, "钉钉审批已撤销")
            await audit.record(
                action=f"asset.request.dingtalk.{result}",
                module=module,
                summary=f"钉钉审批结果同步：{request.request_no}（{LINK_STATUS_LABELS[target_status]}）",
                actor_id=None,
                actor_name=operator,
                resource_type="asset_request",
                resource_id=request.id,
                before={"status": RequestStatus.PENDING_APPROVAL},
                after={
                    "status": request.status,
                    "dingtalk_instance_id": instance_id,
                    "dingtalk_result": result,
                },
            )
    elif link.transfer_id is not None:
        item = (
            await session.execute(
                select(AssetTransfer)
                .where(AssetTransfer.id == link.transfer_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is not None and item.status == TransferStatus.PENDING_APPROVAL:
            if target_status == LINK_APPROVED:
                item.status = TransferStatus.PENDING_TRANSFER
                item.approver_id = None
                item.approver_name = "钉钉审批"
                item.approved_at = now
                item.approval_comment = "钉钉审批通过"
            elif target_status == LINK_REJECTED:
                item.status = TransferStatus.REJECTED
                item.approval_comment = "钉钉审批驳回"
            else:
                item.status = TransferStatus.CANCELLED
                item.approval_comment = "钉钉审批已撤销"
            await audit.record(
                action=f"asset.transfer.dingtalk.{result}",
                module="asset",
                summary=f"钉钉审批结果同步：{item.transfer_no}（{LINK_STATUS_LABELS[target_status]}）",
                actor_id=None,
                actor_name=operator,
                resource_type="asset_transfer",
                resource_id=item.id,
                before={"status": TransferStatus.PENDING_APPROVAL},
                after={
                    "status": item.status,
                    "dingtalk_instance_id": instance_id,
                    "dingtalk_result": result,
                },
            )

    link.status = target_status
    link.result = result
    link.finish_time = now
    await commit_or_conflict(session, message=_STATUS_CONFLICT_MESSAGE, code=40911)
    logger.info(
        "dingtalk approval %s applied: %s -> %s (%s)",
        event,
        instance_id,
        target_status,
        link.doc_no or "-",
    )
    return "applied"


async def refresh_link(
    session: AsyncSession, config: DingTalkConfig, link: DingTalkApproval
) -> None:
    """查询钉钉实例状态，已结束时驱动单据；调用方负责 commit。"""
    try:
        instance = await dingtalk_client.get_process_instance(
            config.app_key, _secret(config), link.process_instance_id
        )
    except BizError as exc:
        link.error_message = (exc.message or "查询失败")[:1000]
        await session.commit()
        return
    status = instance.get("status")
    result = instance.get("result")
    if status == "COMPLETED":
        if result not in ("agree", "refuse"):
            link.error_message = f"钉钉返回未知审批结果：{result}"
            await session.commit()
            return
        await apply_outcome(
            session,
            link.process_instance_id,
            result,
            operator="钉钉审批对账",
            event="reconcile",
        )
    elif status == "TERMINATED":
        await apply_outcome(
            session,
            link.process_instance_id,
            "terminate",
            operator="钉钉审批对账",
            event="reconcile",
        )


async def reconcile(session: AsyncSession, config: DingTalkConfig) -> dict[str, int]:
    """对账所有 RUNNING 的钉钉审批关联记录，作为回调的安全网。"""
    links = list(
        (
            await session.execute(
                select(DingTalkApproval).where(
                    DingTalkApproval.status == LINK_RUNNING
                )
            )
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {"total": len(links), "settled": 0, "errors": 0}
    for link in links:
        try:
            await refresh_link(session, config, link)
            if link.status != LINK_RUNNING:
                counts["settled"] += 1
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻塞其余对账
            counts["errors"] += 1
            logger.exception("dingtalk approval reconcile failed: %s", link.process_instance_id)
            link.error_message = (str(exc) or "对账失败")[:1000]
            try:
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
    return counts


__all__ = [
    "DOC_TYPE_REQUISITION",
    "DOC_TYPE_BORROW",
    "DOC_TYPE_TRANSFER",
    "LINK_RUNNING",
    "LINK_APPROVED",
    "LINK_REJECTED",
    "LINK_TERMINATED",
    "LINK_STATUS_LABELS",
    "REQUEST_TYPE_TO_DOC_TYPE",
    "channel_enabled",
    "get_approval_config",
    "has_running_link",
    "running_link_exists",
    "create_instance",
    "apply_outcome",
    "refresh_link",
    "reconcile",
]
