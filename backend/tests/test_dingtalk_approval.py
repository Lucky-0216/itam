import base64
import hashlib
import json
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import insert, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.core.dingtalk_crypto import (
    decrypt_message,
    encrypt_message,
    verify_signature,
)
from app.core.exceptions import BizError
from app.core.secrets import decrypt_secret
from app.core.security import hash_password
from app.models import (
    Asset,
    AssetCategory,
    AssetRequest,
    AssetTransfer,
    Dept,
    DingTalkApproval,
    DingTalkConfig,
    Role,
    User,
    user_roles,
)
from app.services import dingtalk_approval
from tests.helpers import auth_headers, login

TEST_PASSWORD = "Test@12345"
AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
CALLBACK_TOKEN = "callback-token-123"


async def _ensure_user(
    username: str, real_name: str, role_code: str, *, dingtalk_userid: str | None = None
) -> int:
    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            real_name=real_name,
            dept_id=dept.id,
            status=1,
            must_change_password=False,
            dingtalk_userid=dingtalk_userid,
        )
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )
        await session.commit()
        return user.id


async def _login_as(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["data"]["access_token"])


async def _create_root_dept() -> int:
    async with AsyncSessionLocal() as session:
        dept = Dept(
            parent_id=None,
            name="钉钉组织",
            code="DT-ROOT",
            path="",
            level=1,
            sort=0,
            status=1,
            source="local",
        )
        session.add(dept)
        await session.commit()
        return dept.id


def _approval_config_payload(root_dept_id: int | None, **overrides) -> dict:
    payload = {
        "enabled": True,
        "corp_id": "ding1234567890abcdef",
        "app_key": "dingappkey001",
        "app_secret": "secret-abc-123",
        "agent_id": 123456789,
        "root_dept_id": root_dept_id,
        "sync_interval_minutes": 120,
        "approval_enabled": True,
        "requisition_process_code": "PROC-REQ-001",
        "borrow_process_code": "PROC-BOR-001",
        "transfer_process_code": "PROC-TRF-001",
    }
    payload.update(overrides)
    return payload


async def _save_config(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    root = await _create_root_dept()
    response = await client.put(
        "/api/v1/system/dingtalk/config",
        json=_approval_config_payload(root, **overrides),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


async def _ensure_in_stock_asset(asset_no: str, name: str) -> int:
    async with AsyncSessionLocal() as session:
        category = (
            await session.execute(
                select(AssetCategory).where(AssetCategory.code == "HW-LAPTOP")
            )
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        asset = Asset(
            asset_no=asset_no,
            name=name,
            category_id=category.id,
            dept_id=dept.id,
            status=AssetStatus.IN_STOCK,
            location="A 座 101",
        )
        session.add(asset)
        await session.commit()
        return asset.id


async def _category_id() -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    select(AssetCategory.id).where(AssetCategory.code == "HW-LAPTOP")
                )
            ).scalar_one()
        )


async def _create_request_via_dingtalk(
    client: AsyncClient,
    headers: dict[str, str],
    instance_id: str,
    request_type: str = "REQUISITION",
) -> dict:
    async def _fake_create(*args, **kwargs):
        return instance_id

    with patch(
        "app.services.dingtalk_approval.dingtalk_client.create_process_instance",
        side_effect=_fake_create,
    ):
        response = await client.post(
            "/api/v1/asset-requests",
            json={
                "request_type": request_type,
                "category_id": await _category_id(),
                "include_child": True,
                "reason": "测试钉钉审批申请",
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.json()
    return response.json()["data"]


async def _get_link(instance_id: str) -> DingTalkApproval | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(DingTalkApproval).where(
                    DingTalkApproval.process_instance_id == instance_id
                )
            )
        ).scalar_one_or_none()


async def _get_request(request_id: int) -> AssetRequest | None:
    async with AsyncSessionLocal() as session:
        return await session.get(AssetRequest, request_id)


# ---------- 加解密与签名 ----------


async def test_dingtalk_crypto_roundtrip():
    for message in ["", "x" * 31, "x" * 32, "x" * 33, "中文消息测试", "success"]:
        encrypted = encrypt_message(AES_KEY, message)
        assert len(base64.b64decode(encrypted)) % 32 == 0
        assert decrypt_message(AES_KEY, encrypted) == message


async def test_dingtalk_crypto_signature():
    token, timestamp, nonce = "tok", "1700000000", "abc"
    expected = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce])).encode("utf-8")
    ).hexdigest()
    assert verify_signature(token, timestamp, nonce, expected) is True
    assert verify_signature(token, timestamp, nonce, "bad") is False
    assert verify_signature("other", timestamp, nonce, expected) is False


# ---------- 渠道选择 ----------


async def test_channel_enabled_matrix():
    config = DingTalkConfig(
        approval_enabled=True,
        requisition_process_code="PROC-1",
    )
    assert (
        dingtalk_approval.channel_enabled(config, "REQUISITION", None) is False
    )
    user = User(username="u1", dingtalk_userid=None)
    assert (
        dingtalk_approval.channel_enabled(config, "REQUISITION", user) is False
    )
    user.dingtalk_userid = "ding001"
    assert (
        dingtalk_approval.channel_enabled(config, "REQUISITION", user) is True
    )
    assert dingtalk_approval.channel_enabled(config, "BORROW", user) is False
    config.approval_enabled = False
    assert (
        dingtalk_approval.channel_enabled(config, "REQUISITION", user) is False
    )
    assert (
        dingtalk_approval.channel_enabled(None, "REQUISITION", user) is False
    )
    assert (
        dingtalk_approval.channel_enabled(config, None, user) is False
    )


# ---------- 配置保存与回调凭证 ----------


async def test_config_persists_approval_fields_and_encrypts_callback_secrets(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    created = await _save_config(
        client,
        headers,
        callback_token=CALLBACK_TOKEN,
        callback_aes_key=AES_KEY,
    )
    assert created["approval_enabled"] is True
    assert created["requisition_process_code"] == "PROC-REQ-001"
    assert created["borrow_process_code"] == "PROC-BOR-001"
    assert created["transfer_process_code"] == "PROC-TRF-001"
    assert created["has_callback_token"] is True
    assert created["has_callback_aes_key"] is True

    async with AsyncSessionLocal() as session:
        config = (
            await session.execute(select(DingTalkConfig).order_by(DingTalkConfig.id))
        ).scalar_one()
        assert config.callback_token_encrypted
        assert config.callback_token_encrypted != CALLBACK_TOKEN
        assert config.callback_aes_key_encrypted != AES_KEY
        assert decrypt_secret(config.callback_token_encrypted) == CALLBACK_TOKEN
        assert decrypt_secret(config.callback_aes_key_encrypted) == AES_KEY

    fetched = await client.get("/api/v1/system/dingtalk/config", headers=headers)
    assert fetched.status_code == 200
    data = fetched.json()["data"]
    assert data["has_callback_token"] is True
    assert data["has_callback_aes_key"] is True
    assert "callback_token" not in data


async def test_config_rejects_bad_aes_key_length(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    response = await client.put(
        "/api/v1/system/dingtalk/config",
        json=_approval_config_payload(
            root, callback_aes_key="too-short", callback_token=CALLBACK_TOKEN
        ),
        headers=headers,
    )
    assert response.status_code == 422


# ---------- 创建单据渠道路由 ----------


async def test_unbound_user_falls_back_to_in_system_approval(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0001", "回退测试笔记本")
    await _ensure_user("dtap_emp", "未绑定员工", "EMPLOYEE")
    headers = await _login_as(client, "dtap_emp")

    async def _fake_create(*args, **kwargs):
        raise AssertionError("未绑定用户不应调用钉钉创建实例")

    with patch(
        "app.services.dingtalk_approval.dingtalk_client.create_process_instance",
        side_effect=_fake_create,
    ):
        response = await client.post(
            "/api/v1/asset-requests",
            json={
                "request_type": "REQUISITION",
                "category_id": await _category_id(),
                "include_child": True,
                "reason": "回退到系统内审批",
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["dingtalk_instance_id"] is None
    assert data["dingtalk_status"] is None
    assert data["approval_stage"] == "DEPT"


async def test_bound_user_routes_to_dingtalk_and_blocks_in_system_approve(
    client: AsyncClient,
):
    tokens = await login(client)
    admin_headers = auth_headers(tokens["access_token"])
    await _save_config(client, admin_headers)
    await _ensure_in_stock_asset("ITAM-DTAP-0002", "钉钉审批测试笔记本")
    await _ensure_user("dtap_bound", "已绑定员工", "EMPLOYEE", dingtalk_userid="ding001")
    await _ensure_user("dtap_dept", "部门管理员", "DEPT_ADMIN")
    emp_headers = await _login_as(client, "dtap_bound")
    dept_headers = await _login_as(client, "dtap_dept")

    data = await _create_request_via_dingtalk(
        client, emp_headers, "inst-req-0001"
    )
    assert data["dingtalk_instance_id"] == "inst-req-0001"
    assert data["dingtalk_status"] == "RUNNING"
    assert data["approval_stage"] is None
    request_id = data["id"]

    link = await _get_link("inst-req-0001")
    assert link is not None
    assert link.request_id == request_id
    assert link.doc_type == "REQUISITION"
    assert link.status == "RUNNING"
    assert link.originator_userid == "ding001"

    blocked = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "试图系统内审批"},
        headers=dept_headers,
    )
    assert blocked.status_code == 400
    assert "钉钉" in blocked.json()["message"]

    review = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_APPROVAL"},
        headers=dept_headers,
    )
    assert review.status_code == 200
    assert review.json()["data"]["total"] == 0


async def test_dingtalk_create_failure_aborts_request(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0003", "失败回滚测试笔记本")
    await _ensure_user("dtap_fail", "失败员工", "EMPLOYEE", dingtalk_userid="ding002")
    headers = await _login_as(client, "dtap_fail")

    async def _fake_create(*args, **kwargs):
        raise BizError("审批模板不存在")

    with patch(
        "app.services.dingtalk_approval.dingtalk_client.create_process_instance",
        side_effect=_fake_create,
    ):
        response = await client.post(
            "/api/v1/asset-requests",
            json={
                "request_type": "REQUISITION",
                "category_id": await _category_id(),
                "include_child": True,
                "reason": "钉钉失败应回滚",
            },
            headers=headers,
        )
    assert response.status_code == 400, response.text
    assert "发起钉钉审批失败" in response.json()["message"]

    async with AsyncSessionLocal() as session:
        count = len(
            (await session.execute(select(AssetRequest))).scalars().all()
        )
    assert count == 0


# ---------- apply_outcome 驱动状态机 ----------


async def test_apply_outcome_agree_drives_request_and_is_idempotent(
    client: AsyncClient,
):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0004", "回调同意测试笔记本")
    await _ensure_user("dtap_agree", "同意员工", "EMPLOYEE", dingtalk_userid="ding003")
    headers = await _login_as(client, "dtap_agree")

    data = await _create_request_via_dingtalk(
        client, headers, "inst-agree-01"
    )
    request_id = data["id"]

    async with AsyncSessionLocal() as session:
        result = await dingtalk_approval.apply_outcome(
            session, "inst-agree-01", "agree"
        )
    assert result == "applied"

    request = await _get_request(request_id)
    assert request.status == "PENDING_OUTBOUND"
    assert request.approver_name == "钉钉审批"
    assert request.approval_comment == "钉钉审批通过"

    link = await _get_link("inst-agree-01")
    assert link.status == "APPROVED"
    assert link.result == "agree"

    async with AsyncSessionLocal() as session:
        second = await dingtalk_approval.apply_outcome(
            session, "inst-agree-01", "refuse"
        )
    assert second == "skipped"
    request = await _get_request(request_id)
    assert request.status == "PENDING_OUTBOUND"


async def test_apply_outcome_refuse_and_terminate(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0005", "回调驳回测试笔记本")
    await _ensure_user("dtap_rej", "驳回员工", "EMPLOYEE", dingtalk_userid="ding004")
    headers = await _login_as(client, "dtap_rej")

    refused = await _create_request_via_dingtalk(
        client, headers, "inst-refuse-01"
    )
    cancelled = await _create_request_via_dingtalk(
        client, headers, "inst-term-01"
    )

    async with AsyncSessionLocal() as session:
        assert (
            await dingtalk_approval.apply_outcome(session, "inst-refuse-01", "refuse")
        ) == "applied"
    async with AsyncSessionLocal() as session:
        assert (
            await dingtalk_approval.apply_outcome(session, "inst-term-01", "terminate")
        ) == "applied"

    refused_req = await _get_request(refused["id"])
    assert refused_req.status == "REJECTED"
    assert refused_req.approval_comment == "钉钉审批驳回"

    cancelled_req = await _get_request(cancelled["id"])
    assert cancelled_req.status == "CANCELLED"
    assert cancelled_req.approval_comment == "钉钉审批已撤销"


async def test_transfer_routes_to_dingtalk_and_outcome_drives(client: AsyncClient):
    tokens = await login(client)
    admin_headers = auth_headers(tokens["access_token"])
    await _save_config(client, admin_headers)
    await _ensure_user(
        "dtap_asset", "资产管理员", "ASSET_ADMIN", dingtalk_userid="dingadmin"
    )
    holder_id = await _ensure_user("dtap_holder", "资产持有人", "EMPLOYEE")
    async with AsyncSessionLocal() as session:
        category = (
            await session.execute(
                select(AssetCategory).where(AssetCategory.code == "HW-LAPTOP")
            )
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        fin = (
            await session.execute(select(Dept).where(Dept.code == "FIN"))
        ).scalar_one()
        asset = Asset(
            asset_no="ITAM-DTAP-0006",
            name="调拨钉钉测试笔记本",
            category_id=category.id,
            dept_id=dept.id,
            status=AssetStatus.IN_USE,
            custodian_id=holder_id,
            location="A 座 101",
        )
        session.add(asset)
        await session.commit()
        asset_id = asset.id
        fin_id = fin.id

    asset_headers = await _login_as(client, "dtap_asset")

    async def _fake_create(*args, **kwargs):
        return "inst-trf-01"

    with patch(
        "app.services.dingtalk_approval.dingtalk_client.create_process_instance",
        side_effect=_fake_create,
    ):
        response = await client.post(
            "/api/v1/asset-transfers",
            json={"asset_id": asset_id, "to_dept_id": fin_id, "reason": "测试钉钉调拨"},
            headers=asset_headers,
        )
    assert response.status_code == 200, response.text
    transfer = response.json()["data"]
    assert transfer["dingtalk_instance_id"] == "inst-trf-01"
    assert transfer["dingtalk_status"] == "RUNNING"
    transfer_id = transfer["id"]

    async with AsyncSessionLocal() as session:
        assert (
            await dingtalk_approval.apply_outcome(session, "inst-trf-01", "agree")
        ) == "applied"

    async with AsyncSessionLocal() as session:
        item = await session.get(AssetTransfer, transfer_id)
        assert item.status == "PENDING_TRANSFER"
        assert item.approver_name == "钉钉审批"


async def test_apply_outcome_skips_unknown_instance(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    async with AsyncSessionLocal() as session:
        assert (
            await dingtalk_approval.apply_outcome(session, "inst-unknown", "agree")
        ) == "skipped"


# ---------- 回调接口 ----------


def _sign(token: str, timestamp: str, nonce: str, *extra: str) -> str:
    return hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, *extra])).encode("utf-8")
    ).hexdigest()


def _callback_params(
    token: str, timestamp: str, nonce: str, event: dict
) -> dict:
    encrypted = encrypt_message(AES_KEY, json.dumps(event))
    signature = _sign(token, timestamp, nonce)
    return {
        "params": {
            "signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        "json": {"encrypt": encrypted},
    }


async def test_callback_rejects_without_credentials(client: AsyncClient):
    response = await client.post(
        "/api/v1/system/dingtalk/callback",
        params={"signature": "x", "timestamp": "1", "nonce": "n"},
        json={"encrypt": "x"},
    )
    assert response.status_code == 401


async def test_callback_rejects_bad_signature(client: AsyncClient):
    tokens = await login(client)
    await _save_config(
        client,
        auth_headers(tokens["access_token"]),
        callback_token=CALLBACK_TOKEN,
        callback_aes_key=AES_KEY,
    )
    response = await client.post(
        "/api/v1/system/dingtalk/callback",
        params={"signature": "bad", "timestamp": "1700000000", "nonce": "abc"},
        json={"encrypt": encrypt_message(AES_KEY, json.dumps({"EventType": "check_url"}))},
    )
    assert response.status_code == 401


async def test_callback_check_url_replies_encrypted_success(client: AsyncClient):
    tokens = await login(client)
    await _save_config(
        client,
        auth_headers(tokens["access_token"]),
        callback_token=CALLBACK_TOKEN,
        callback_aes_key=AES_KEY,
    )
    timestamp, nonce = "1700000000", "check-nonce"
    response = await client.post(
        "/api/v1/system/dingtalk/callback",
        params=_callback_params(
            CALLBACK_TOKEN, timestamp, nonce, {"EventType": "check_url"}
        )["params"],
        json=_callback_params(
            CALLBACK_TOKEN, timestamp, nonce, {"EventType": "check_url"}
        )["json"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timeStamp"] == timestamp
    assert body["nonce"] == nonce
    assert decrypt_message(AES_KEY, body["encrypt"]) == "success"
    expected_signature = _sign(
        CALLBACK_TOKEN, timestamp, nonce, body["encrypt"]
    )
    assert body["msg_signature"] == expected_signature


async def test_callback_finish_agree_drives_request_state(client: AsyncClient):
    tokens = await login(client)
    await _save_config(
        client,
        auth_headers(tokens["access_token"]),
        callback_token=CALLBACK_TOKEN,
        callback_aes_key=AES_KEY,
    )
    await _ensure_in_stock_asset("ITAM-DTAP-0007", "回调驱动测试笔记本")
    await _ensure_user("dtap_cb", "回调员工", "EMPLOYEE", dingtalk_userid="ding005")
    headers = await _login_as(client, "dtap_cb")

    data = await _create_request_via_dingtalk(client, headers, "inst-cb-01")
    request_id = data["id"]

    timestamp, nonce = "1700000001", "cb-nonce"
    event = {
        "EventType": "bpms_instance_change",
        "processInstanceId": "inst-cb-01",
        "type": "finish",
        "result": "agree",
    }
    kwargs = _callback_params(CALLBACK_TOKEN, timestamp, nonce, event)
    response = await client.post(
        "/api/v1/system/dingtalk/callback",
        params=kwargs["params"],
        json=kwargs["json"],
    )
    assert response.status_code == 200, response.text
    assert decrypt_message(AES_KEY, response.json()["encrypt"]) == "success"

    request = await _get_request(request_id)
    assert request.status == "PENDING_OUTBOUND"


async def test_callback_terminate_cancels_request(client: AsyncClient):
    tokens = await login(client)
    await _save_config(
        client,
        auth_headers(tokens["access_token"]),
        callback_token=CALLBACK_TOKEN,
        callback_aes_key=AES_KEY,
    )
    await _ensure_in_stock_asset("ITAM-DTAP-0008", "回调撤销测试笔记本")
    await _ensure_user("dtap_ct", "撤销员工", "EMPLOYEE", dingtalk_userid="ding006")
    headers = await _login_as(client, "dtap_ct")

    data = await _create_request_via_dingtalk(client, headers, "inst-cb-02")
    request_id = data["id"]

    timestamp, nonce = "1700000002", "cb-nonce2"
    event = {
        "EventType": "bpms_instance_change",
        "processInstanceId": "inst-cb-02",
        "type": "terminate",
    }
    kwargs = _callback_params(CALLBACK_TOKEN, timestamp, nonce, event)
    response = await client.post(
        "/api/v1/system/dingtalk/callback",
        params=kwargs["params"],
        json=kwargs["json"],
    )
    assert response.status_code == 200, response.text

    request = await _get_request(request_id)
    assert request.status == "CANCELLED"


# ---------- 对账 ----------


async def test_reconcile_settles_running_links(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0009", "对账测试笔记本")
    await _ensure_user("dtap_rec", "对账员工", "EMPLOYEE", dingtalk_userid="ding007")
    headers = await _login_as(client, "dtap_rec")

    data = await _create_request_via_dingtalk(client, headers, "inst-rec-01")
    request_id = data["id"]

    async def _fake_get(app_key, app_secret, instance_id):
        return {"status": "COMPLETED", "result": "agree"}

    async with AsyncSessionLocal() as session:
        config = await dingtalk_approval.get_approval_config(session)
        with patch(
            "app.services.dingtalk_approval.dingtalk_client.get_process_instance",
            side_effect=_fake_get,
        ):
            counts = await dingtalk_approval.reconcile(session, config)
    assert counts["total"] == 1
    assert counts["settled"] == 1
    assert counts["errors"] == 0

    request = await _get_request(request_id)
    assert request.status == "PENDING_OUTBOUND"
    link = await _get_link("inst-rec-01")
    assert link.status == "APPROVED"


async def test_reconcile_records_api_errors(client: AsyncClient):
    tokens = await login(client)
    await _save_config(client, auth_headers(tokens["access_token"]))
    await _ensure_in_stock_asset("ITAM-DTAP-0010", "对账失败测试笔记本")
    await _ensure_user("dtap_err", "对账失败员工", "EMPLOYEE", dingtalk_userid="ding008")
    headers = await _login_as(client, "dtap_err")

    await _create_request_via_dingtalk(client, headers, "inst-rec-02")

    async def _fake_get(app_key, app_secret, instance_id):
        raise BizError("token 失效")

    async with AsyncSessionLocal() as session:
        config = await dingtalk_approval.get_approval_config(session)
        with patch(
            "app.services.dingtalk_approval.dingtalk_client.get_process_instance",
            side_effect=_fake_get,
        ):
            counts = await dingtalk_approval.reconcile(session, config)
    assert counts["total"] == 1
    assert counts["settled"] == 0
    assert counts["errors"] == 0

    link = await _get_link("inst-rec-02")
    assert link.status == "RUNNING"
    assert "token 失效" in (link.error_message or "")
