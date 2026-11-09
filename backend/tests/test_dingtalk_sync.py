from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BizError
from app.core.secrets import decrypt_secret
from app.models import Dept, DingTalkConfig, User
from app.services.dingtalk_client import RosterDept
from app.services.dingtalk_sync_service import DingTalkSyncService
from tests.helpers import auth_headers, login


def _dept_entries() -> list[dict]:
    return [
        {"dept_id": "10", "name": "总部", "parent_id": None, "manager_userids": []},
        {
            "dept_id": "11",
            "name": "信息部",
            "parent_id": "10",
            "manager_userids": ["zhangsan001"],
        },
    ]


def _user_entries() -> list[dict]:
    return [
        {
            "userid": "zhangsan001",
            "name": "张三",
            "mobile": "13800000001",
            "email": "zhangsan@example.com",
            "avatar": "",
            "position": "工程师",
            "job_number": "E1001",
            "active": True,
            "dept_id_list": [11],
        },
        {
            "userid": "lisi002",
            "name": "李四",
            "mobile": "13800000002",
            "email": "lisi@example.com",
            "job_number": "",
            "active": False,
            "dept_id_list": [10],
        },
    ]


async def _create_root_dept(name: str = "钉钉组织") -> Dept:
    async with AsyncSessionLocal() as session:
        dept = Dept(
            parent_id=None,
            name=name,
            code="DT-ROOT",
            path="",
            level=1,
            sort=0,
            status=1,
            source="local",
        )
        session.add(dept)
        await session.commit()
        await session.refresh(dept)
        return dept


def _config_payload(root_dept_id: int | None, **overrides) -> dict:
    payload = {
        "enabled": True,
        "corp_id": "ding1234567890abcdef",
        "app_key": "dingappkey001",
        "app_secret": "secret-abc-123",
        "agent_id": 123456789,
        "default_role_id": None,
        "root_dept_id": root_dept_id,
        "sync_interval_minutes": 120,
        "disable_on_leave": True,
        "match_existing": True,
    }
    payload.update(overrides)
    return payload


async def _save_config(
    client: AsyncClient, headers: dict[str, str], root_dept_id: int, **overrides
) -> dict:
    response = await client.put(
        "/api/v1/system/dingtalk/config",
        json=_config_payload(root_dept_id, **overrides),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


async def _run_sync(config_id: int):
    async with AsyncSessionLocal() as session:
        return await DingTalkSyncService(session).run_sync(
            config_id=config_id,
            trigger_type="MANUAL",
            operator_name="tester",
        )


async def _get_user(username: str) -> User | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()


async def _get_dept_by_key(key: str) -> Dept | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(Dept).where(Dept.dingtalk_dept_id == key)
            )
        ).scalar_one_or_none()


async def test_dingtalk_config_secret_masked_and_encrypted(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()

    created = await _save_config(client, headers, root.id)
    assert created["has_secret"] is True
    assert "app_secret" not in created
    assert created["corp_id"] == "ding1234567890abcdef"

    async with AsyncSessionLocal() as session:
        config = (
            await session.execute(select(DingTalkConfig).order_by(DingTalkConfig.id))
        ).scalar_one()
        assert config.app_secret_encrypted
        assert config.app_secret_encrypted != "secret-abc-123"
        assert decrypt_secret(config.app_secret_encrypted) == "secret-abc-123"

    fetched = await client.get("/api/v1/system/dingtalk/config", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["has_secret"] is True
    assert fetched.json()["data"]["root_dept_name"] == "钉钉组织"

    updated = await _save_config(
        client, headers, root.id, app_secret=None, enabled=False
    )
    assert updated["has_secret"] is True
    assert updated["enabled"] is False

    options = await client.get("/api/v1/system/dingtalk/options", headers=headers)
    assert options.status_code == 200
    body = options.json()["data"]
    role_codes = {item["code"] for item in body["roles"]}
    assert "EMPLOYEE" in role_codes
    assert any(item["id"] == root.id for item in body["depts"])


async def test_dingtalk_connection_test_reports_result(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    await _save_config(client, headers, root.id)

    tree = [RosterDept(dept_id="10", name="总部", parent_id=None)]
    with (
        patch(
            "app.services.dingtalk_sync_service.dingtalk_client.fetch_dept_tree",
            return_value=tree,
        ),
        patch(
            "app.services.dingtalk_sync_service.dingtalk_client.list_dept_user_ids",
            return_value=["u1", "u2"],
        ),
    ):
        response = await client.post(
            "/api/v1/system/dingtalk/test",
            json=_config_payload(root.id),
            headers=headers,
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["success"] is True
    assert data["dept_sample"] == 1
    assert data["user_sample"] == 2

    with patch(
        "app.services.dingtalk_sync_service.dingtalk_client.fetch_dept_tree",
        side_effect=BizError("token 无效"),
    ):
        failed = await client.post(
            "/api/v1/system/dingtalk/test",
            json=_config_payload(root.id),
            headers=headers,
        )
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["success"] is False
    assert "token 无效" in failed.json()["data"]["message"]

    async with AsyncSessionLocal() as session:
        config = (
            await session.execute(select(DingTalkConfig).order_by(DingTalkConfig.id))
        ).scalar_one()
        assert config.last_test_status == "FAILED"


async def test_dingtalk_connection_test_does_not_require_mount_dept(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    # enabled=True 但未选挂载根部门：连接测试只验证凭证，不应被启用校验拦截
    payload = _config_payload(None)
    tree = [RosterDept(dept_id="10", name="总部", parent_id=None)]
    with (
        patch(
            "app.services.dingtalk_sync_service.dingtalk_client.fetch_dept_tree",
            return_value=tree,
        ),
        patch(
            "app.services.dingtalk_sync_service.dingtalk_client.list_dept_user_ids",
            return_value=["u1"],
        ),
    ):
        response = await client.post(
            "/api/v1/system/dingtalk/test",
            json=payload,
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["success"] is True


async def test_dingtalk_save_requires_mount_dept_when_enabled(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    response = await client.put(
        "/api/v1/system/dingtalk/config",
        json=_config_payload(None),
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "根部门" in response.json()["message"]


async def test_dingtalk_sync_creates_dept_tree_and_users(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.dept_created == 2
    assert log.user_created == 2
    assert log.user_disabled == 1

    hq = await _get_dept_by_key("10")
    it = await _get_dept_by_key("11")
    assert hq is not None and it is not None
    assert hq.parent_id == root.id
    assert it.parent_id == hq.id
    assert hq.code == "DT-10"
    assert hq.source == "dingtalk"
    assert hq.path == f"/{root.id}/{hq.id}/"
    assert it.path == f"/{root.id}/{hq.id}/{it.id}/"
    assert it.level == root.level + 2

    zhangsan = await _get_user("e1001")
    assert zhangsan is not None
    assert zhangsan.source == "dingtalk"
    assert zhangsan.real_name == "张三"
    assert zhangsan.email == "zhangsan@example.com"
    assert zhangsan.phone == "13800000001"
    assert zhangsan.employee_no == "E1001"
    assert zhangsan.dept_id == it.id
    assert zhangsan.dingtalk_userid == "zhangsan001"
    assert zhangsan.status == 1
    assert zhangsan.remark == "由钉钉通讯录同步自动创建"

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(Dept, it.id)
        assert refreshed is not None
        assert refreshed.manager_id == zhangsan.id

    lisi = await _get_user("dt_lisi002")
    assert lisi is not None
    assert lisi.status == 0
    assert lisi.dept_id == hq.id

    async with AsyncSessionLocal() as session:
        config_refreshed = await session.get(DingTalkConfig, config["id"])
        assert config_refreshed is not None
        assert config_refreshed.last_sync_status == "SUCCESS"


async def test_dingtalk_sync_matches_ldap_user_without_overwriting(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id)

    async with AsyncSessionLocal() as session:
        session.add(
            User(
                username="zhangsan.ad",
                password_hash="not-a-real-hash",
                real_name="域控张三",
                email="zhangsan@example.com",
                source="ldap",
                ldap_dn="CN=张三,DC=example,DC=com",
                status=1,
            )
        )
        await session.commit()

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_matched == 1
    assert log.user_created == 1

    matched = await _get_user("zhangsan.ad")
    assert matched is not None
    assert matched.source == "ldap"
    assert matched.real_name == "域控张三"
    assert matched.dept_id is None
    assert matched.status == 1
    assert matched.dingtalk_userid == "zhangsan001"
    assert matched.phone == "13800000001"
    assert matched.dingtalk_synced_at is not None


async def test_dingtalk_sync_adopts_legacy_dt_temp_user(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id)

    async with AsyncSessionLocal() as session:
        session.add(
            User(
                username="dt_zhangsan001",
                password_hash="not-a-real-hash",
                real_name="导入临时账号",
                source="local",
                status=1,
            )
        )
        await session.commit()

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_matched == 1

    adopted = await _get_user("dt_zhangsan001")
    assert adopted is not None
    assert adopted.source == "dingtalk"
    assert adopted.real_name == "张三"
    assert adopted.dingtalk_userid == "zhangsan001"
    assert adopted.email == "zhangsan@example.com"


async def test_dingtalk_sync_disables_missing_user_and_dept(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        first = await _run_sync(config["id"])
    assert first.status == "SUCCESS", first.error_message

    remaining_depts = [_dept_entries()[0]]
    remaining_users = [
        {
            **_user_entries()[1],
            "active": True,
            "job_number": "E2002",
        }
    ]
    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(remaining_depts, remaining_users),
    ):
        second = await _run_sync(config["id"])

    assert second.status == "SUCCESS", second.error_message
    assert second.user_disabled == 1

    zhangsan = await _get_user("e1001")
    assert zhangsan is not None
    assert zhangsan.status == 0
    assert zhangsan.deleted_at is None
    assert zhangsan.token_version == 1

    lisi = await _get_user("dt_lisi002")
    assert lisi is not None and lisi.status == 1

    it = await _get_dept_by_key("11")
    assert it is not None and it.status == 0


async def test_dingtalk_sync_keeps_users_when_disable_on_leave_off(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id, disable_on_leave=False)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        await _run_sync(config["id"])

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=([_dept_entries()[0]], [_user_entries()[1]]),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    zhangsan = await _get_user("e1001")
    assert zhangsan is not None and zhangsan.status == 1


async def test_dingtalk_sync_rejects_empty_roster_for_existing_users(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_config(client, headers, root.id)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        await _run_sync(config["id"])

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=([], []),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "FAILED"
    assert "已中止同步" in (log.error_message or "")
    zhangsan = await _get_user("e1001")
    assert zhangsan is not None and zhangsan.status == 1


async def test_manual_sync_endpoint_records_log(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    await _save_config(client, headers, root.id)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dept_entries(), _user_entries()),
    ):
        response = await client.post("/api/v1/system/dingtalk/sync", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["accepted"] is True

    logs = await client.get("/api/v1/system/dingtalk/logs", headers=headers)
    assert logs.status_code == 200
    data = logs.json()["data"]
    assert data["total"] >= 1
    assert data["items"][0]["status"] == "SUCCESS"
    assert data["items"][0]["trigger_type"] == "MANUAL"

    detail = await client.get(
        f"/api/v1/system/dingtalk/logs/{data['items'][0]['id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["user_created"] == 2
    assert detail.json()["data"]["user_disabled"] == 1


async def test_trigger_sync_requires_enabled_config(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    await _save_config(client, headers, root.id, enabled=False)

    response = await client.post("/api/v1/system/dingtalk/sync", headers=headers)
    assert response.status_code == 400, response.text
    assert "未启用" in response.json()["message"]
