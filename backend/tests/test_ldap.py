from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.secrets import decrypt_secret
from app.models import Dept, LdapConfig, User
from app.services.ldap_service import LdapProbeResult, LdapSyncService
from tests.helpers import auth_headers, login

BASE_DN = "DC=example,DC=com"


def _config_payload(**overrides) -> dict:
    payload = {
        "enabled": True,
        "server_host": "dc01.example.com",
        "server_port": 389,
        "use_ssl": False,
        "start_tls": False,
        "base_dn": BASE_DN,
        "bind_dn": "CN=svc-itam,DC=example,DC=com",
        "bind_password": "P@ssw0rd!",
        "sync_interval_minutes": 30,
    }
    payload.update(overrides)
    return payload


def _dept_entries() -> list[dict]:
    return [
        {
            "dn": "OU=总部,DC=example,DC=com",
            "attributes": {"ou": "总部", "name": "总部"},
        },
        {
            "dn": "OU=研发部,OU=总部,DC=example,DC=com",
            "attributes": {"ou": "研发部", "name": "研发部"},
        },
    ]


def _user_entries() -> list[dict]:
    return [
        {
            "dn": "CN=张三,OU=研发部,OU=总部,DC=example,DC=com",
            "attributes": {
                "sAMAccountName": "zhangsan",
                "displayName": "张三",
                "mail": "zhangsan@example.com",
                "telephoneNumber": "13800000000",
                "employeeID": "E1001",
                "userAccountControl": "512",
            },
        },
        {
            "dn": "CN=李四,OU=总部,DC=example,DC=com",
            "attributes": {
                "sAMAccountName": "lisi",
                "displayName": "李四",
                "mail": "lisi@example.com",
                "userAccountControl": "514",
            },
        },
        {
            "dn": "CN=王五,OU=总部,DC=example,DC=com",
            "attributes": {
                "cn": "王五",
                "displayName": "王五",
                "userAccountControl": "512",
            },
        },
    ]


async def _save_config(
    client: AsyncClient, headers: dict[str, str], **overrides
) -> dict:
    response = await client.put(
        "/api/v1/system/ldap/config",
        json=_config_payload(**overrides),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


async def _run_sync(config_id: int):
    async with AsyncSessionLocal() as session:
        return await LdapSyncService(session).run_sync(
            config_id=config_id,
            trigger_type="MANUAL",
            operator_name="tester",
        )


async def _get_user(username: str) -> User | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()


async def _get_dept_by_dn(dn: str) -> Dept | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(Dept).where(Dept.ldap_dn == dn))
        ).scalar_one_or_none()


async def test_ldap_config_password_masked_and_encrypted(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    created = await _save_config(client, headers)
    assert created["has_password"] is True
    assert "bind_password" not in created

    async with AsyncSessionLocal() as session:
        config = (
            await session.execute(select(LdapConfig).order_by(LdapConfig.id))
        ).scalar_one()
        assert config.bind_password_encrypted
        assert config.bind_password_encrypted != "P@ssw0rd!"
        assert decrypt_secret(config.bind_password_encrypted) == "P@ssw0rd!"

    fetched = await client.get("/api/v1/system/ldap/config", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["has_password"] is True

    updated = await _save_config(client, headers, bind_password=None, enabled=False)
    assert updated["has_password"] is True
    assert updated["enabled"] is False

    options = await client.get("/api/v1/system/ldap/options", headers=headers)
    assert options.status_code == 200
    role_codes = {item["code"] for item in options.json()["data"]["roles"]}
    assert "EMPLOYEE" in role_codes


async def test_ldap_connection_test_reports_probe_result(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    await _save_config(client, headers)

    probe = LdapProbeResult(
        success=True,
        message="连接成功",
        server="dc01.example.com:389",
        dept_sample=2,
        user_sample=3,
        elapsed_ms=12,
    )
    with patch("app.services.ldap_service._probe", return_value=probe):
        response = await client.post(
            "/api/v1/system/ldap/test",
            json=_config_payload(),
            headers=headers,
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["success"] is True
    assert data["dept_sample"] == 2
    assert data["user_sample"] == 3

    with patch("app.services.ldap_service._probe", side_effect=RuntimeError("拒绝连接")):
        failed = await client.post(
            "/api/v1/system/ldap/test",
            json=_config_payload(),
            headers=headers,
        )
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["success"] is False
    assert "拒绝连接" in failed.json()["data"]["message"]

    async with AsyncSessionLocal() as session:
        config = (
            await session.execute(select(LdapConfig).order_by(LdapConfig.id))
        ).scalar_one()
        assert config.last_test_status == "FAILED"


async def test_ldap_sync_creates_dept_tree_and_users(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.dept_created == 2
    assert log.user_created == 3
    assert log.user_disabled == 1

    hq = await _get_dept_by_dn("OU=总部,DC=example,DC=com")
    rd = await _get_dept_by_dn("OU=研发部,OU=总部,DC=example,DC=com")
    assert hq is not None and rd is not None
    assert rd.parent_id == hq.id
    assert hq.path == f"/{hq.id}/"
    assert rd.path == f"/{hq.id}/{rd.id}/"
    assert rd.level == hq.level + 1

    zhangsan = await _get_user("zhangsan")
    assert zhangsan is not None
    assert zhangsan.source == "ldap"
    assert zhangsan.real_name == "张三"
    assert zhangsan.email == "zhangsan@example.com"
    assert zhangsan.dept_id == rd.id
    assert zhangsan.status == 1
    assert zhangsan.ldap_dn.startswith("CN=张三")

    lisi = await _get_user("lisi")
    assert lisi is not None
    assert lisi.status == 0

    async with AsyncSessionLocal() as session:
        wangwu = (
            await session.execute(select(User).where(User.ldap_uid == "王五"))
        ).scalar_one_or_none()
    assert wangwu is not None
    assert wangwu.source == "ldap"
    assert wangwu.real_name == "王五"
    assert wangwu.status == 1


def _deep_dept_entries() -> list[dict]:
    return [
        {
            "dn": "OU=NDCZ_Company,DC=example,DC=com",
            "attributes": {"ou": "NDCZ_Company", "name": "NDCZ_Company"},
        },
        {
            "dn": "OU=ZCB,OU=NDCZ_Company,DC=example,DC=com",
            "attributes": {"ou": "ZCB", "name": "ZCB"},
        },
        {
            "dn": "OU=XXB,OU=ZCB,OU=NDCZ_Company,DC=example,DC=com",
            "attributes": {"ou": "XXB", "name": "XXB"},
        },
    ]


def _deep_user_entries() -> list[dict]:
    return [
        {
            "dn": "CN=甘忠天,OU=XXB,OU=ZCB,OU=NDCZ_Company,DC=example,DC=com",
            "attributes": {
                "sAMAccountName": "zhongtian.gan",
                "displayName": "甘忠天",
                "mail": "zhongtian.gan@example.com",
                "userAccountControl": "512",
            },
        }
    ]


async def test_ldap_sync_builds_full_ou_path(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_deep_dept_entries(), _deep_user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.dept_created == 3
    assert log.user_created == 1

    company = await _get_dept_by_dn("OU=NDCZ_Company,DC=example,DC=com")
    center = await _get_dept_by_dn("OU=ZCB,OU=NDCZ_Company,DC=example,DC=com")
    dept = await _get_dept_by_dn("OU=XXB,OU=ZCB,OU=NDCZ_Company,DC=example,DC=com")
    assert company is not None and center is not None and dept is not None
    assert company.parent_id is None
    assert center.parent_id == company.id
    assert dept.parent_id == center.id
    assert company.path == f"/{company.id}/"
    assert center.path == f"/{company.id}/{center.id}/"
    assert dept.path == f"/{company.id}/{center.id}/{dept.id}/"
    assert dept.level == company.level + 2

    user = await _get_user("zhongtian.gan")
    assert user is not None
    assert user.dept_id == dept.id
    assert user.real_name == "甘忠天"

    response = await client.get(
        "/api/v1/users",
        params={"keyword": "zhongtian.gan"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    items = body["data"]["items"]
    matched = next(item for item in items if item["username"] == "zhongtian.gan")
    assert matched["dept_name"] == "XXB"
    assert matched["dept_path"] == "NDCZ_Company\\ZCB\\XXB"


async def test_ldap_sync_disables_missing_user_and_moves_department(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        first = await _run_sync(config["id"])
    assert first.status == "SUCCESS"

    moved_entries = [
        {
            "dn": "OU=测试组,DC=example,DC=com",
            "attributes": {"ou": "测试组"},
        }
    ]
    moved_user = [
        {
            "dn": "CN=张三,OU=测试组,DC=example,DC=com",
            "attributes": {
                "sAMAccountName": "zhangsan",
                "displayName": "张三",
                "mail": "zhangsan@example.com",
                "userAccountControl": "512",
            },
        }
    ]
    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(moved_entries, moved_user),
    ):
        second = await _run_sync(config["id"])

    assert second.status == "SUCCESS", second.error_message
    assert second.dept_created == 1
    assert second.user_disabled == 1
    assert second.user_updated == 1

    test_group = await _get_dept_by_dn("OU=测试组,DC=example,DC=com")
    zhangsan = await _get_user("zhangsan")
    assert zhangsan is not None
    assert zhangsan.status == 1
    assert zhangsan.dept_id == test_group.id

    lisi = await _get_user("lisi")
    assert lisi is not None and lisi.status == 0
    assert lisi.deleted_at is None

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(LdapConfig, config["id"])
        assert refreshed is not None
        assert refreshed.last_sync_status == "SUCCESS"
        assert refreshed.last_sync_message is not None


async def test_ldap_sync_skips_username_collision_with_local_user(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    async with AsyncSessionLocal() as session:
        session.add(
            User(
                username="zhangsan",
                password_hash="not-a-real-hash",
                real_name="本地张三",
                source="local",
                status=1,
            )
        )
        await session.commit()

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=([], _user_entries()),
    ):
        log = await _run_sync(config["id"])

    assert log.user_skipped == 1
    local = await _get_user("zhangsan")
    assert local is not None
    assert local.source == "local"
    assert local.real_name == "本地张三"


async def test_ldap_sync_rejects_empty_directory_for_existing_ldap_users(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        await _run_sync(config["id"])

    with patch(
        "app.services.ldap_service._fetch_directory", return_value=([], [])
    ):
        log = await _run_sync(config["id"])

    assert log.status == "FAILED"
    assert "已中止同步" in (log.error_message or "")
    zhangsan = await _get_user("zhangsan")
    assert zhangsan is not None and zhangsan.status == 1


async def test_manual_sync_endpoint_records_log(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        response = await client.post("/api/v1/system/ldap/sync", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["accepted"] is True

    logs = await client.get("/api/v1/system/ldap/logs", headers=headers)
    assert logs.status_code == 200
    data = logs.json()["data"]
    assert data["total"] >= 1
    assert data["items"][0]["status"] == "SUCCESS"
    assert data["items"][0]["trigger_type"] == "MANUAL"

    detail = await client.get(
        f"/api/v1/system/ldap/logs/{data['items'][0]['id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["user_created"] == 3


async def test_domain_user_login_and_local_password_change_block(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        await _run_sync(config["id"])

    with patch(
        "app.services.auth_service.authenticate_ldap_user",
        return_value=(True, "", False),
    ):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "zhangsan", "password": "DomainPass1"},
        )
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["user"]["username"] == "zhangsan"
    domain_headers = auth_headers(body["access_token"])

    blocked = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "DomainPass1", "new_password": "NewPass@123"},
        headers=domain_headers,
    )
    assert blocked.status_code == 400, blocked.text
    assert "域" in blocked.json()["message"]


async def test_domain_user_login_rejects_bad_password_and_supports_local_fallback(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_dept_entries(), _user_entries()),
    ):
        await _run_sync(config["id"])

    with patch(
        "app.services.auth_service.authenticate_ldap_user",
        return_value=(False, "用户名或密码错误", False),
    ):
        rejected = await client.post(
            "/api/v1/auth/login",
            json={"username": "zhangsan", "password": "WrongPass1"},
        )
    assert rejected.status_code == 401
    assert rejected.json()["code"] == 40101

    with patch(
        "app.services.auth_service.authenticate_ldap_user",
        return_value=(False, "域控服务不可用：timeout", True),
    ):
        unavailable = await client.post(
            "/api/v1/auth/login",
            json={"username": "zhangsan", "password": "WrongPass1"},
        )
    assert unavailable.status_code == 401
    assert unavailable.json()["code"] == 40104

    from app.core.security import hash_password

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.username == "zhangsan"))
        ).scalar_one()
        user.password_hash = hash_password("Fallback@123")
        await session.commit()

    with patch(
        "app.services.auth_service.authenticate_ldap_user",
        return_value=(False, "域控服务不可用：timeout", True),
    ):
        fallback = await client.post(
            "/api/v1/auth/login",
            json={"username": "zhangsan", "password": "Fallback@123"},
        )
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["data"]["user"]["username"] == "zhangsan"
