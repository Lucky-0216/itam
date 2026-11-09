import hashlib
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.core.database import AsyncSessionLocal, get_db
from app.core.dingtalk_crypto import (
    decrypt_message,
    encrypt_message,
    verify_signature,
)
from app.core.exceptions import BizError
from app.core.response import ok
from app.core.secrets import decrypt_secret
from app.schemas.dingtalk import DingTalkConfigUpdate, DingTalkTestPayload
from app.services import dingtalk_approval
from app.services.dingtalk_sync_service import DingTalkSyncService
from app.services.permission_service import AuthContext

logger = logging.getLogger("itam.dingtalk")

router = APIRouter(prefix="/system/dingtalk", tags=["钉钉同步"])


async def _run_manual_sync(
    config_id: int,
    operator_id: int | None,
    operator_name: str | None,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await DingTalkSyncService(session).run_sync(
                config_id=config_id,
                trigger_type="MANUAL",
                operator_id=operator_id,
                operator_name=operator_name,
            )
    except Exception:  # noqa: BLE001 - background task must not surface after response
        logger.exception("manual DingTalk sync failed (config=%s)", config_id)


@router.get("/config", summary="获取钉钉同步配置")
async def get_config(
    context: AuthContext = Depends(require_perm("system:dingtalk:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await DingTalkSyncService(session).get_config_out()
    return ok(result.model_dump(mode="json"))


@router.put("/config", summary="保存钉钉同步配置")
async def save_config(
    payload: DingTalkConfigUpdate,
    context: AuthContext = Depends(require_perm("system:dingtalk:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await DingTalkSyncService(session).save_config(payload, context)
    return ok(result.model_dump(mode="json"), message="钉钉同步配置已保存")


@router.post("/test", summary="测试钉钉通讯录连接")
async def test_config(
    payload: DingTalkTestPayload,
    context: AuthContext = Depends(require_perm("system:dingtalk:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await DingTalkSyncService(session).test_config(payload, context)
    return ok(
        result.model_dump(mode="json"),
        message="钉钉连接测试成功" if result.success else "钉钉连接测试失败",
    )


@router.get("/options", summary="默认角色与部门选项")
async def options(
    context: AuthContext = Depends(require_perm("system:dingtalk:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await DingTalkSyncService(session).options()
    return ok(result.model_dump(mode="json"))


@router.post("/sync", summary="手动触发钉钉人员同步")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    context: AuthContext = Depends(require_perm("system:dingtalk:sync")),
    session: AsyncSession = Depends(get_db),
):
    service = DingTalkSyncService(session)
    config = await service.get_config()
    if config is None:
        raise BizError("尚未配置钉钉同步")
    if not config.enabled:
        raise BizError("钉钉同步未启用，请先保存并启用配置")
    if config.last_sync_status == "RUNNING":
        raise BizError("已有同步任务正在执行，请稍后刷新同步日志")

    operator_name = context.user.real_name or context.user.username
    background_tasks.add_task(
        _run_manual_sync,
        config.id,
        context.user.id,
        operator_name,
    )
    return ok(
        {
            "accepted": True,
            "config_id": config.id,
            "trigger_type": "MANUAL",
        },
        message="同步任务已提交，完成后可在同步日志中查看结果",
    )


@router.get("/logs", summary="钉钉同步日志列表")
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(RUNNING|SUCCESS|PARTIAL|FAILED)$"),
    context: AuthContext = Depends(require_perm("system:dingtalk:view")),
    session: AsyncSession = Depends(get_db),
):
    items, total = await DingTalkSyncService(session).list_logs(
        page=page,
        page_size=page_size,
        status=status,
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/logs/{log_id}", summary="钉钉同步日志详情")
async def get_log(
    log_id: int,
    context: AuthContext = Depends(require_perm("system:dingtalk:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await DingTalkSyncService(session).get_log(log_id)
    return ok(result.model_dump(mode="json"))


def _callback_denied(message: str) -> JSONResponse:
    logger.warning("dingtalk callback rejected: %s", message)
    return JSONResponse(status_code=401, content={"detail": message})


@router.post("/callback", summary="钉钉审批事件回调（免鉴权）")
async def approval_callback(
    request: Request,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    """接收钉钉审批实例变更事件，验签解密后驱动单据状态机。"""
    service = DingTalkSyncService(session)
    config = await service.get_config()
    if config is None or not config.callback_token_encrypted or not config.callback_aes_key_encrypted:
        return _callback_denied("回调配置未设置")
    try:
        token = decrypt_secret(config.callback_token_encrypted)
        aes_key = decrypt_secret(config.callback_aes_key_encrypted)
    except BizError:
        return _callback_denied("回调密钥无效")

    if not verify_signature(token, timestamp, nonce, signature):
        return _callback_denied("签名校验失败")

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _callback_denied("请求体不是合法 JSON")
    encrypted = body.get("encrypt")
    if not encrypted:
        return _callback_denied("缺少 encrypt 字段")

    try:
        message = json.loads(decrypt_message(aes_key, encrypted))
    except Exception:  # noqa: BLE001
        return _callback_denied("消息解密失败")

    def _reply(payload: str) -> JSONResponse:
        encrypt = encrypt_message(aes_key, payload)
        msg_signature = hashlib.sha1(
            "".join(sorted([token, timestamp, nonce, encrypt])).encode("utf-8")
        ).hexdigest()
        return JSONResponse(
            {
                "msg_signature": msg_signature,
                "timeStamp": timestamp,
                "nonce": nonce,
                "encrypt": encrypt,
            }
        )

    event_type = message.get("EventType")
    if event_type == "check_url" or event_type is None:
        return _reply("success")

    if event_type != "bpms_instance_change":
        logger.info("dingtalk callback: ignoring event %s", event_type)
        return _reply("success")

    instance_id = str(message.get("processInstanceId") or "")
    change_type = message.get("type")
    result = message.get("result")
    if not instance_id:
        return _reply("success")
    try:
        if change_type == "terminate":
            await dingtalk_approval.apply_outcome(session, instance_id, "terminate")
        elif change_type == "finish":
            if result in ("agree", "refuse"):
                await dingtalk_approval.apply_outcome(session, instance_id, result)
            else:
                logger.warning(
                    "dingtalk callback: finish without valid result: %r", message
                )
    except Exception:  # noqa: BLE001 - 对账任务兜底，回调必须正常应答
        logger.exception("dingtalk callback apply failed for %s", instance_id)
    return _reply("success")
