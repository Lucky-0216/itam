from httpx import AsyncClient
from sqlalchemy import func, insert, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import AuditLog, Dept, Role, User, user_roles
from tests.helpers import TEST_PASSWORD, auth_headers, login


async def test_login_me_and_menu_permissions(client: AsyncClient):
    data = await login(client)
    assert data["user"]["username"] == "admin"
    assert data["must_change_password"] is False
    assert data["access_token"] and data["refresh_token"]

    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(data["access_token"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    me = body["data"]
    assert me["user"]["username"] == "admin"
    assert "SUPER_ADMIN" in [role["code"] for role in me["roles"]]
    assert "dashboard:view" in me["permissions"]
    assert me["data_scope"] == "ALL"
    assert me["menus"][0]["path"] == "/dashboard"


async def test_menu_groups_and_employee_visibility(client: AsyncClient):
    admin = await login(client)
    admin_me = await client.get(
        "/api/v1/auth/me", headers=auth_headers(admin["access_token"])
    )
    admin_menus = admin_me.json()["data"]["menus"]
    assert [node["name"] for node in admin_menus] == [
        "工作台",
        "我的工作",
        "资产生命周期",
        "基础数据",
        "运维与合同",
        "分析报表",
        "系统管理",
    ]
    roots = {node["name"]: node for node in admin_menus}
    assert [node["name"] for node in roots["我的工作"]["children"]] == [
        "我的待办",
        "我的资产",
        "我的申请",
        "业务审批",
    ]
    assert [node["name"] for node in roots["资产生命周期"]["children"]] == [
        "资产台账",
        "资产入库",
        "资产出库",
        "资产领用确认",
        "资产归还确认",
        "资产调拨",
        "资产盘点",
        "资产报废",
    ]
    assert [node["name"] for node in roots["基础数据"]["children"]] == [
        "资产分类",
        "库存管理",
    ]
    assert [node["name"] for node in roots["运维与合同"]["children"]] == [
        "维修管理",
        "合同管理",
        "到期提醒",
    ]
    assert [node["name"] for node in roots["分析报表"]["children"]] == ["报表分析"]

    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == "EMPLOYEE"))
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        user = User(
            username="menu_emp",
            password_hash=hash_password(TEST_PASSWORD),
            real_name="菜单员工",
            dept_id=dept.id,
            status=1,
            must_change_password=False,
        )
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )
        await session.commit()

    emp_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "menu_emp", "password": TEST_PASSWORD},
    )
    assert emp_login.status_code == 200, emp_login.text
    emp_me = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(emp_login.json()["data"]["access_token"]),
    )
    emp_menus = emp_me.json()["data"]["menus"]
    emp_roots = {node["name"]: node for node in emp_menus}
    assert [node["name"] for node in emp_roots["我的工作"]["children"]] == [
        "我的待办",
        "我的资产",
        "我的申请",
        "业务审批",
    ]
    lifecycle_names = {
        child["name"] for child in emp_roots["资产生命周期"]["children"]
    }
    assert "资产领用确认" not in lifecycle_names
    assert "资产归还确认" not in lifecycle_names
    assert "基础数据" not in emp_roots
    assert "分析报表" not in emp_roots


async def test_login_failure_is_audited(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "WrongPass123"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == 40100

    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "auth.login",
                AuditLog.status == "FAILED",
            )
        )
        assert count == 1


async def test_refresh_rotation_and_logout(client: AsyncClient):
    data = await login(client)
    first_refresh = data["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert response.status_code == 200
    rotated = response.json()["data"]
    assert rotated["refresh_token"] != first_refresh

    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert replay.status_code == 401

    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(rotated["access_token"]),
    )
    assert response.status_code == 200

    response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": rotated["refresh_token"]},
        headers=auth_headers(rotated["access_token"]),
    )
    assert response.status_code == 200

    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(rotated["access_token"]),
    )
    assert response.status_code == 401


async def test_change_password_invalidates_old_tokens(client: AsyncClient):
    data = await login(client)
    old_access = data["access_token"]

    response = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "NewPass@456"},
        headers=auth_headers(old_access),
    )
    assert response.status_code == 200, response.text
    new_access = response.json()["data"]["access_token"]

    old_token_response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(old_access),
    )
    assert old_token_response.status_code == 401

    me_response = await client.get(
        "/api/v1/auth/me",
        headers=auth_headers(new_access),
    )
    assert me_response.status_code == 200
    assert me_response.json()["data"]["user"]["must_change_password"] is False

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "NewPass@456"},
    )
    assert new_login.status_code == 200


async def test_me_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 40100
    assert body["data"] is None
