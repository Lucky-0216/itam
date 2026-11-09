from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BizError
from app.models import Dept, OrgSyncPolicy, User
from app.services.dingtalk_sync_service import DingTalkSyncService
from app.services.ldap_service import LdapSyncService
from app.services.org_policy_service import (
    can_disable_dept,
    can_disable_user,
    mutation_level,
    parse_priority,
)
from tests.helpers import auth_headers, login


def _policy_obj(**overrides) -> OrgSyncPolicy:
    policy = OrgSyncPolicy(
        source_priority="ldap,dingtalk,local",
        conflict_strategy="fill_empty",
        protect_local=True,
        disable_scope="own",
    )
    for key, value in overrides.items():
        setattr(policy, key, value)
    return policy


def _user_obj(**overrides) -> User:
    user = User(
        username="u_test",
        password_hash="not-a-real-hash",
        real_name="测试",
        source="local",
        status=1,
    )
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def _dept_obj(**overrides) -> Dept:
    dept = Dept(
        name="测试部门",
        code="TST",
        path="",
        level=1,
        sort=0,
        status=1,
        source="local",
    )
    for key, value in overrides.items():
        setattr(dept, key, value)
    return dept


async def _get_policy_row() -> OrgSyncPolicy | None:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(OrgSyncPolicy).limit(1))
        ).scalar_one_or_none()


async def _set_policy(**overrides) -> None:
    async with AsyncSessionLocal() as session:
        policy = (
            await session.execute(select(OrgSyncPolicy).limit(1))
        ).scalar_one_or_none()
        if policy is None:
            policy = OrgSyncPolicy(
                source_priority="ldap,dingtalk,local",
                conflict_strategy="fill_empty",
                protect_local=True,
                disable_scope="own",
            )
            session.add(policy)
        for key, value in overrides.items():
            setattr(policy, key, value)
        await session.commit()


# ---------------------------------------------------------------- unit tests


def test_parse_priority_accepts_valid_and_rejects_invalid():
    assert parse_priority("ldap,dingtalk,local") == ["ldap", "dingtalk", "local"]
    assert parse_priority(" dingtalk , ldap , local ") == ["dingtalk", "ldap", "local"]

    with pytest.raises(BizError):
        parse_priority("ldap,dingtalk")
    with pytest.raises(BizError):
        parse_priority("ldap,ldap,local")
    with pytest.raises(BizError):
        parse_priority("ldap,dingtalk,local,extra")


def test_mutation_level_rejects_unknown_source():
    with pytest.raises(BizError):
        mutation_level(_policy_obj(), "ad", "local")


@pytest.mark.parametrize(
    "policy_overrides, sync_source, target_source, expected",
    [
        ({}, "ldap", "ldap", "overwrite"),
        ({}, "dingtalk", "dingtalk", "overwrite"),
        ({}, "ldap", "local", "fill_empty"),
        ({}, "dingtalk", "local", "fill_empty"),
        (
            {"protect_local": False, "conflict_strategy": "skip"},
            "ldap",
            "local",
            "skip",
        ),
        (
            {"protect_local": False, "conflict_strategy": "overwrite"},
            "ldap",
            "local",
            "overwrite",
        ),
        ({}, "dingtalk", "ldap", "fill_empty"),
        ({}, "ldap", "dingtalk", "fill_empty"),
        ({"conflict_strategy": "skip"}, "ldap", "dingtalk", "skip"),
        ({"conflict_strategy": "overwrite"}, "ldap", "dingtalk", "overwrite"),
        (
            {"source_priority": "dingtalk,ldap,local"},
            "ldap",
            "dingtalk",
            "fill_empty",
        ),
        (
            {"source_priority": "dingtalk,ldap,local"},
            "dingtalk",
            "ldap",
            "fill_empty",
        ),
    ],
)
def test_mutation_level_matrix(policy_overrides, sync_source, target_source, expected):
    assert (
        mutation_level(_policy_obj(**policy_overrides), sync_source, target_source)
        == expected
    )


def test_can_disable_user_scope_rules():
    policy = _policy_obj()

    assert can_disable_user(policy, "ldap", _user_obj(source="ldap")) is True
    assert (
        can_disable_user(policy, "ldap", _user_obj(ldap_dn="CN=张三,DC=x")) is False
    )
    assert (
        can_disable_user(policy, "ldap", _user_obj(dingtalk_userid="u001")) is False
    )

    any_policy = _policy_obj(disable_scope="any")
    assert can_disable_user(any_policy, "ldap", _user_obj(ldap_dn="CN=张三,DC=x")) is True
    assert (
        can_disable_user(any_policy, "dingtalk", _user_obj(dingtalk_userid="u001"))
        is True
    )
    assert can_disable_user(any_policy, "ldap", _user_obj()) is False
    assert can_disable_user(any_policy, "dingtalk", _user_obj(ldap_dn="CN=x")) is False


def test_can_disable_dept_scope_rules():
    policy = _policy_obj()

    assert can_disable_dept(policy, "ldap", _dept_obj(source="ldap")) is True
    assert can_disable_dept(policy, "ldap", _dept_obj(ldap_dn="OU=x,DC=y")) is False

    any_policy = _policy_obj(disable_scope="any")
    assert can_disable_dept(any_policy, "ldap", _dept_obj(ldap_dn="OU=x,DC=y")) is True
    assert (
        can_disable_dept(any_policy, "dingtalk", _dept_obj(dingtalk_dept_id="10"))
        is True
    )
    assert can_disable_dept(any_policy, "ldap", _dept_obj()) is False
    assert can_disable_dept(any_policy, "dingtalk", _dept_obj(ldap_dn="OU=x")) is False


# ---------------------------------------------------------------- policy API


async def test_sync_policy_defaults_and_update_roundtrip(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    fetched = await client.get("/api/v1/sync-policy", headers=headers)
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()["data"]
    assert data["source_priority"] == "ldap,dingtalk,local"
    assert data["conflict_strategy"] == "fill_empty"
    assert data["protect_local"] is True
    assert data["disable_scope"] == "own"
    assert data["version"] >= 1

    updated = await client.put(
        "/api/v1/sync-policy",
        json={
            "source_priority": "dingtalk,ldap,local",
            "conflict_strategy": "skip",
            "protect_local": False,
            "disable_scope": "any",
            "version": data["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    updated_data = updated.json()["data"]
    assert updated_data["source_priority"] == "dingtalk,ldap,local"
    assert updated_data["conflict_strategy"] == "skip"
    assert updated_data["protect_local"] is False
    assert updated_data["disable_scope"] == "any"
    assert updated_data["version"] == data["version"] + 1

    fetched_again = await client.get("/api/v1/sync-policy", headers=headers)
    assert fetched_again.json()["data"]["source_priority"] == "dingtalk,ldap,local"

    row = await _get_policy_row()
    assert row is not None and row.source_priority == "dingtalk,ldap,local"


async def test_sync_policy_rejects_invalid_input_and_stale_version(
    client: AsyncClient,
):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    data = (await client.get("/api/v1/sync-policy", headers=headers)).json()["data"]

    base = {
        "source_priority": "ldap,dingtalk,local",
        "conflict_strategy": "fill_empty",
        "protect_local": True,
        "disable_scope": "own",
        "version": data["version"],
    }

    missing_source = await client.put(
        "/api/v1/sync-policy",
        json={**base, "source_priority": "ldap,dingtalk"},
        headers=headers,
    )
    assert missing_source.status_code == 400

    bad_strategy = await client.put(
        "/api/v1/sync-policy",
        json={**base, "conflict_strategy": "merge"},
        headers=headers,
    )
    assert bad_strategy.status_code == 400

    bad_scope = await client.put(
        "/api/v1/sync-policy",
        json={**base, "disable_scope": "everyone"},
        headers=headers,
    )
    assert bad_scope.status_code == 400

    applied = await client.put(
        "/api/v1/sync-policy",
        json={**base, "protect_local": False},
        headers=headers,
    )
    assert applied.status_code == 200
    assert applied.json()["data"]["version"] == data["version"] + 1

    stale = await client.put(
        "/api/v1/sync-policy",
        json={**base, "version": data["version"]},
        headers=headers,
    )
    assert stale.status_code == 409


async def test_sync_policy_requires_permission(client: AsyncClient):
    admin = await login(client)
    headers = auth_headers(admin["access_token"])

    roles = (await client.get("/api/v1/roles/options/all", headers=headers)).json()[
        "data"
    ]
    employee_role = next(role for role in roles if role["code"] == "EMPLOYEE")

    created = await client.post(
        "/api/v1/users",
        json={
            "username": "plainemp",
            "password": "Init@12345",
            "real_name": "普通员工",
            "dept_id": await _it_dept_id(client, headers),
            "role_ids": [employee_role["id"]],
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    plain_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "plainemp", "password": "Init@12345"},
    )
    assert plain_login.status_code == 200
    plain_headers = auth_headers(plain_login.json()["data"]["access_token"])

    denied = await client.get("/api/v1/sync-policy", headers=plain_headers)
    assert denied.status_code == 403


# ---------------------------------------------------------------- ldap sync fixtures


BASE_DN = "DC=example,DC=com"


def _ldap_dept_entries() -> list[dict]:
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


def _ldap_user_entries() -> list[dict]:
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
    ]


async def _save_ldap_config(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.put(
        "/api/v1/system/ldap/config",
        json={
            "enabled": True,
            "server_host": "dc01.example.com",
            "server_port": 389,
            "use_ssl": False,
            "start_tls": False,
            "base_dn": BASE_DN,
            "bind_dn": "CN=svc-itam,DC=example,DC=com",
            "bind_password": "P@ssw0rd!",
            "sync_interval_minutes": 30,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _run_ldap_sync(config_id: int):
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


ZHANGSAN_DN = "CN=张三,OU=研发部,OU=总部,DC=example,DC=com"


async def _add_bound_local_user(**overrides) -> None:
    async with AsyncSessionLocal() as session:
        user = User(
            username="localbound",
            password_hash="not-a-real-hash",
            real_name="本地张三",
            source="local",
            status=1,
            ldap_dn=ZHANGSAN_DN,
        )
        for key, value in overrides.items():
            setattr(user, key, value)
        session.add(user)
        await session.commit()


# ---------------------------------------------------------------- ldap sync integration


async def test_ldap_sync_protect_local_fills_empty_only(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)
    await _add_bound_local_user(email=None, phone=None, employee_no=None)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        log = await _run_ldap_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_created == 1
    assert log.user_updated == 1

    local = await _get_user("localbound")
    assert local is not None
    assert local.source == "local"
    assert local.real_name == "本地张三"
    assert local.dept_id is None
    assert local.status == 1
    assert local.email == "zhangsan@example.com"
    assert local.phone == "13800000000"
    assert local.employee_no == "E1001"
    assert local.ldap_uid == "zhangsan"
    assert local.ldap_synced_at is not None


async def test_ldap_sync_overwrites_bound_local_when_protect_off(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)
    await _set_policy(protect_local=False, conflict_strategy="overwrite")
    await _add_bound_local_user(email=None)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        log = await _run_ldap_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_created == 1
    assert log.user_updated == 1

    rd = await _get_dept_by_dn("OU=研发部,OU=总部,DC=example,DC=com")
    taken = await _get_user("localbound")
    assert taken is not None
    assert taken.source == "ldap"
    assert taken.real_name == "张三"
    assert taken.dept_id == rd.id
    assert taken.email == "zhangsan@example.com"


async def test_ldap_sync_skip_cross_source_but_still_binds(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)
    await _set_policy(conflict_strategy="skip")

    async with AsyncSessionLocal() as session:
        session.add(
            User(
                username="ddzhang",
                password_hash="not-a-real-hash",
                real_name="钉钉张三",
                source="dingtalk",
                status=1,
                ldap_dn=ZHANGSAN_DN,
                dingtalk_userid="zhangsan001",
            )
        )
        session.add(
            Dept(
                name="钉钉总部",
                code="DD-HQ",
                path="",
                level=1,
                sort=0,
                status=1,
                source="dingtalk",
                ldap_dn="OU=总部,DC=example,DC=com",
                dingtalk_dept_id="10",
            )
        )
        await session.commit()

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        log = await _run_ldap_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_skipped == 1
    assert log.user_created == 1
    assert log.dept_skipped == 1
    assert log.dept_created == 1

    dd = await _get_user("ddzhang")
    assert dd is not None
    assert dd.source == "dingtalk"
    assert dd.real_name == "钉钉张三"
    assert dd.dept_id is None
    assert dd.status == 1
    assert dd.ldap_uid == "zhangsan"
    assert dd.ldap_synced_at is not None

    async with AsyncSessionLocal() as session:
        dd_dept = (
            await session.execute(
                select(Dept).where(Dept.dingtalk_dept_id == "10")
            )
        ).scalar_one()
    assert dd_dept.source == "dingtalk"
    assert dd_dept.name == "钉钉总部"
    assert dd_dept.ldap_synced_at is not None


async def test_ldap_disable_scope_own_vs_any(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)
    await _add_bound_local_user()

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        first = await _run_ldap_sync(config["id"])
    assert first.status == "SUCCESS", first.error_message

    remaining_users = [
        {
            "dn": "CN=李四,OU=总部,DC=example,DC=com",
            "attributes": {
                "sAMAccountName": "lisi",
                "displayName": "李四",
                "mail": "lisi@example.com",
                "userAccountControl": "512",
            },
        }
    ]
    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), remaining_users),
    ):
        second = await _run_ldap_sync(config["id"])
    assert second.status == "SUCCESS", second.error_message

    local = await _get_user("localbound")
    assert local is not None and local.status == 1

    await _set_policy(disable_scope="any")
    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), remaining_users),
    ):
        third = await _run_ldap_sync(config["id"])
    assert third.status == "SUCCESS", third.error_message

    local = await _get_user("localbound")
    assert local is not None
    assert local.status == 0
    assert local.deleted_at is None


# ---------------------------------------------------------------- dingtalk sync fixtures


def _dd_dept_entries() -> list[dict]:
    return [
        {"dept_id": "10", "name": "总部", "parent_id": None, "manager_userids": []},
        {
            "dept_id": "11",
            "name": "信息部",
            "parent_id": "10",
            "manager_userids": ["zhangsan001"],
        },
    ]


def _dd_user_entries() -> list[dict]:
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


async def _save_dd_config(client: AsyncClient, headers: dict[str, str], root_id: int) -> dict:
    response = await client.put(
        "/api/v1/system/dingtalk/config",
        json={
            "enabled": True,
            "corp_id": "ding1234567890abcdef",
            "app_key": "dingappkey001",
            "app_secret": "secret-abc-123",
            "agent_id": 123456789,
            "default_role_id": None,
            "root_dept_id": root_id,
            "sync_interval_minutes": 120,
            "disable_on_leave": True,
            "match_existing": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _run_dd_sync(config_id: int):
    async with AsyncSessionLocal() as session:
        return await DingTalkSyncService(session).run_sync(
            config_id=config_id,
            trigger_type="MANUAL",
            operator_name="tester",
        )


async def _add_local_user_by_phone(**overrides) -> None:
    async with AsyncSessionLocal() as session:
        user = User(
            username="localdd",
            password_hash="not-a-real-hash",
            real_name="本地张三",
            source="local",
            status=1,
            phone="13800000001",
        )
        for key, value in overrides.items():
            setattr(user, key, value)
        session.add(user)
        await session.commit()


# ---------------------------------------------------------------- dingtalk sync integration


async def test_dingtalk_sync_protect_local_fills_empty_only(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_dd_config(client, headers, root.id)
    await _add_local_user_by_phone(email=None, employee_no=None)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dd_dept_entries(), _dd_user_entries()),
    ):
        log = await _run_dd_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_matched == 1
    assert log.user_created == 1

    local = await _get_user("localdd")
    assert local is not None
    assert local.source == "local"
    assert local.real_name == "本地张三"
    assert local.dept_id is None
    assert local.status == 1
    assert local.email == "zhangsan@example.com"
    assert local.employee_no == "E1001"
    assert local.dingtalk_userid == "zhangsan001"
    assert local.dingtalk_synced_at is not None


async def test_dingtalk_sync_overwrites_local_when_protect_off(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _create_root_dept()
    config = await _save_dd_config(client, headers, root.id)
    await _set_policy(protect_local=False, conflict_strategy="overwrite")
    await _add_local_user_by_phone(email=None, employee_no=None)

    with patch(
        "app.services.dingtalk_sync_service.DingTalkSyncService._fetch_roster",
        return_value=(_dd_dept_entries(), _dd_user_entries()),
    ):
        log = await _run_dd_sync(config["id"])

    assert log.status == "SUCCESS", log.error_message
    assert log.user_updated == 1
    assert log.user_created == 1

    async with AsyncSessionLocal() as session:
        it_dept = (
            await session.execute(
                select(Dept).where(Dept.dingtalk_dept_id == "11")
            )
        ).scalar_one()

    taken = await _get_user("localdd")
    assert taken is not None
    assert taken.source == "dingtalk"
    assert taken.real_name == "张三"
    assert taken.dept_id == it_dept.id
    assert taken.email == "zhangsan@example.com"


# ---------------------------------------------------------------- source filter & guards


async def _it_dept_id(client: AsyncClient, headers: dict[str, str]) -> int:
    tree = (await client.get("/api/v1/departments/tree", headers=headers)).json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == "IT":
                return node["id"]
            found = walk(node["children"])
            if found:
                return found
        return None

    dept_id = walk(tree)
    assert dept_id is not None
    return dept_id


async def _employee_role_id(client: AsyncClient, headers: dict[str, str]) -> int:
    roles = (await client.get("/api/v1/roles/options/all", headers=headers)).json()[
        "data"
    ]
    return next(role for role in roles if role["code"] == "EMPLOYEE")["id"]


async def test_users_source_filter(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        await _run_ldap_sync(config["id"])

    created = await client.post(
        "/api/v1/users",
        json={
            "username": "localsrc",
            "password": "Init@12345",
            "real_name": "本地来源",
            "dept_id": await _it_dept_id(client, headers),
            "role_ids": [await _employee_role_id(client, headers)],
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    ldap_page = (
        await client.get("/api/v1/users", params={"source": "ldap"}, headers=headers)
    ).json()["data"]
    assert ldap_page["total"] == 2
    assert {item["source"] for item in ldap_page["items"]} == {"ldap"}

    local_page = (
        await client.get("/api/v1/users", params={"source": "local"}, headers=headers)
    ).json()["data"]
    assert local_page["total"] >= 1
    assert {item["source"] for item in local_page["items"]} == {"local"}
    assert "localsrc" in {item["username"] for item in local_page["items"]}

    dd_page = (
        await client.get("/api/v1/users", params={"source": "dingtalk"}, headers=headers)
    ).json()["data"]
    assert dd_page["total"] == 0

    invalid = await client.get("/api/v1/users", params={"source": "ad"}, headers=headers)
    assert invalid.status_code == 422


async def test_dept_tree_source_filter(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    config = await _save_ldap_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        await _run_ldap_sync(config["id"])

    ldap_tree = (
        await client.get("/api/v1/departments/tree", params={"source": "ldap"}, headers=headers)
    ).json()["data"]
    assert len(ldap_tree) == 1
    ldap_nodes = [ldap_tree[0], *ldap_tree[0]["children"]]
    assert len(ldap_nodes) == 2
    assert {node["source"] for node in ldap_nodes} == {"ldap"}

    local_tree = (
        await client.get("/api/v1/departments/tree", params={"source": "local"}, headers=headers)
    ).json()["data"]
    assert len(local_tree) > 0
    assert all(node["source"] == "local" for node in local_tree)

    dd_tree = (
        await client.get("/api/v1/departments/tree", params={"source": "dingtalk"}, headers=headers)
    ).json()["data"]
    assert dd_tree == []

    invalid = await client.get(
        "/api/v1/departments/tree", params={"source": "ad"}, headers=headers
    )
    assert invalid.status_code == 422


async def _operator_headers(client: AsyncClient, admin_headers: dict[str, str]) -> dict[str, str]:
    menus = (await client.get("/api/v1/roles/menu-tree", headers=admin_headers)).json()[
        "data"
    ]

    def flatten(nodes):
        for node in nodes:
            yield node
            yield from flatten(node["children"])

    menu_map = {menu["permission_code"]: menu for menu in flatten(menus)}
    for code in (
        "system:user:update",
        "system:user:delete",
        "system:dept:update",
        "system:dept:delete",
    ):
        assert code in menu_map, f"菜单缺失：{code}"

    role = (
        await client.post(
            "/api/v1/roles",
            json={
                "code": "SRC_GUARD_OP",
                "name": "来源守卫操作员",
                "data_scope": "ALL",
                "sort": 90,
                "status": 1,
            },
            headers=admin_headers,
        )
    ).json()["data"]
    assigned = await client.put(
        f"/api/v1/roles/{role['id']}/menus",
        json={
            "menu_ids": [
                menu_map["system:user:update"]["id"],
                menu_map["system:user:delete"]["id"],
                menu_map["system:dept:update"]["id"],
                menu_map["system:dept:delete"]["id"],
            ],
            "version": role["version"],
        },
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text

    created = await client.post(
        "/api/v1/users",
        json={
            "username": "srcguardop",
            "password": "Init@12345",
            "real_name": "守卫操作员",
            "dept_id": await _it_dept_id(client, admin_headers),
            "role_ids": [role["id"]],
            "status": 1,
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text

    op_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "srcguardop", "password": "Init@12345"},
    )
    assert op_login.status_code == 200, op_login.text
    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "Init@12345", "new_password": "Guard@12345"},
        headers=auth_headers(op_login.json()["data"]["access_token"]),
    )
    assert changed.status_code == 200, changed.text
    return auth_headers(changed.json()["data"]["access_token"])


async def test_non_local_crud_guards(client: AsyncClient):
    admin = await login(client)
    headers = auth_headers(admin["access_token"])
    config = await _save_ldap_config(client, headers)

    with patch(
        "app.services.ldap_service._fetch_directory",
        return_value=(_ldap_dept_entries(), _ldap_user_entries()),
    ):
        await _run_ldap_sync(config["id"])

    listed = (
        await client.get("/api/v1/users", params={"keyword": "zhangsan"}, headers=headers)
    ).json()["data"]
    zhangsan = listed["items"][0]
    ldap_dept = (
        await client.get("/api/v1/departments/tree", params={"source": "ldap"}, headers=headers)
    ).json()["data"][0]

    local_created = await client.post(
        "/api/v1/users",
        json={
            "username": "localguarded",
            "password": "Init@12345",
            "real_name": "本地可改",
            "dept_id": await _it_dept_id(client, headers),
            "role_ids": [await _employee_role_id(client, headers)],
            "status": 1,
        },
        headers=headers,
    )
    local_user = local_created.json()["data"]
    local_detail = (
        await client.get(f"/api/v1/users/{local_user['id']}", headers=headers)
    ).json()["data"]

    op_headers = await _operator_headers(client, headers)

    update_payload = {
        "real_name": "越权改名",
        "dept_id": ldap_dept["id"],
        "version": zhangsan["version"],
    }
    denied_update = await client.put(
        f"/api/v1/users/{zhangsan['id']}", json=update_payload, headers=op_headers
    )
    assert denied_update.status_code == 403, denied_update.text

    denied_status = await client.put(
        f"/api/v1/users/{zhangsan['id']}/status",
        json={"status": 0, "version": zhangsan["version"]},
        headers=op_headers,
    )
    assert denied_status.status_code == 403

    denied_delete = await client.delete(
        f"/api/v1/users/{zhangsan['id']}", headers=op_headers
    )
    assert denied_delete.status_code == 403

    denied_dept_update = await client.put(
        f"/api/v1/departments/{ldap_dept['id']}",
        json={
            "name": ldap_dept["name"],
            "code": ldap_dept["code"],
            "sort": 0,
            "status": 1,
            "version": ldap_dept["version"],
        },
        headers=op_headers,
    )
    assert denied_dept_update.status_code == 403

    denied_dept_delete = await client.delete(
        f"/api/v1/departments/{ldap_dept['id']}", headers=op_headers
    )
    assert denied_dept_delete.status_code == 403

    allowed_local = await client.put(
        f"/api/v1/users/{local_user['id']}",
        json={
            "real_name": "本地改名",
            "dept_id": local_detail["dept_id"]
            if local_detail.get("dept_id")
            else ldap_dept["id"],
            "version": local_detail["version"],
        },
        headers=op_headers,
    )
    assert allowed_local.status_code == 200, allowed_local.text

    admin_update = await client.put(
        f"/api/v1/users/{zhangsan['id']}",
        json={
            "real_name": "管理员改名",
            "dept_id": ldap_dept["id"],
            "version": zhangsan["version"],
        },
        headers=headers,
    )
    assert admin_update.status_code == 200, admin_update.text
    assert admin_update.json()["data"]["real_name"] == "管理员改名"

    admin_dept_update = await client.put(
        f"/api/v1/departments/{ldap_dept['id']}",
        json={
            "name": f"{ldap_dept['name']}（改）",
            "code": ldap_dept["code"],
            "sort": 0,
            "status": 1,
            "version": ldap_dept["version"],
        },
        headers=headers,
    )
    assert admin_dept_update.status_code == 200, admin_dept_update.text
