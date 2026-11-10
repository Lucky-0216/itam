from sqlalchemy import insert, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import AuditLog, Dept, Role, User, user_roles
from tests.helpers import auth_headers, login


async def _create_user(username: str, role_code: str) -> None:
    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password("Test@12345"),
            real_name=username,
            status=1,
            must_change_password=False,
        )
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )
        await session.commit()


async def test_audit_log_list_filter_detail(client):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    created = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "审计测试分类",
            "code": "AUDIT-CAT",
            "category_type": "HARDWARE",
            "sort": 90,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    failed_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert failed_login.status_code == 401

    listing = await client.get(
        "/api/v1/audit-logs",
        params={"page": 1, "page_size": 10},
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()["data"]
    assert body["total"] >= 3
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids, reverse=True)
    newest = body["items"][0]
    assert newest["action"] == "auth.login"
    assert newest["status"] == "FAILED"
    assert newest["username"] == "admin"

    by_module = await client.get(
        "/api/v1/audit-logs",
        params={"module": "资产分类"},
        headers=headers,
    )
    module_items = by_module.json()["data"]["items"]
    assert module_items and all(item["module"] == "资产分类" for item in module_items)

    by_keyword = await client.get(
        "/api/v1/audit-logs",
        params={"keyword": "审计测试分类"},
        headers=headers,
    )
    keyword_items = by_keyword.json()["data"]["items"]
    assert len(keyword_items) == 1
    log_id = keyword_items[0]["id"]

    detail = await client.get(f"/api/v1/audit-logs/{log_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()["data"]
    assert detail_body["after_data"]["name"] == "审计测试分类"
    assert detail_body["before_data"] is None
    assert detail_body["path"] == "/api/v1/asset-categories"
    assert detail_body["method"] == "POST"

    failed_only = await client.get(
        "/api/v1/audit-logs",
        params={"status": "FAILED"},
        headers=headers,
    )
    failed_items = failed_only.json()["data"]["items"]
    assert failed_items and all(item["status"] == "FAILED" for item in failed_items)

    future = await client.get(
        "/api/v1/audit-logs",
        params={"start_time": "2099-01-01T00:00:00"},
        headers=headers,
    )
    assert future.json()["data"]["total"] == 0

    options = await client.get("/api/v1/audit-logs/options", headers=headers)
    option_data = options.json()["data"]
    assert "资产分类" in option_data["modules"]
    assert "asset.category.create" in option_data["actions"]

    missing = await client.get("/api/v1/audit-logs/999999", headers=headers)
    assert missing.status_code == 404


async def test_audit_detail_resolves_reference_labels(client):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    async with AsyncSessionLocal() as session:
        admin = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        target = User(
            username="labeluser01",
            password_hash=hash_password("Test@12345"),
            real_name="标签用户",
            status=1,
            must_change_password=False,
        )
        dept = Dept(name="标签部门", code="LABEL-DEPT-01")
        session.add_all([target, dept])
        await session.flush()
        log = AuditLog(
            user_id=admin.id,
            username=admin.username,
            action="asset.ledger.update",
            module="资产台账",
            summary="编辑资产：标签解析测试",
            status="SUCCESS",
            before_data={"custodian_id": admin.id, "dept_id": dept.id},
            after_data={"custodian_id": target.id, "dept_id": dept.id},
        )
        session.add(log)
        await session.commit()
        log_id = log.id
        target_id = target.id

    detail = await client.get(f"/api/v1/audit-logs/{log_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["before_labels"] == {
        "custodian_id": "系统管理员（admin）",
        "dept_id": "标签部门",
    }
    assert data["after_labels"] == {
        "custodian_id": "标签用户（labeluser01）",
        "dept_id": "标签部门",
    }
    assert data["after_data"]["custodian_id"] == target_id


async def test_audit_log_data_scope_and_permission(client):
    admin_tokens = await login(client)
    admin_headers = auth_headers(admin_tokens["access_token"])

    admin_logs = await client.get(
        "/api/v1/audit-logs",
        params={"action": "auth.login"},
        headers=admin_headers,
    )
    admin_log_id = admin_logs.json()["data"]["items"][0]["id"]

    await _create_user("auditor1", "AUDITOR")
    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == "AUDITOR"))
        ).scalar_one()
        role.data_scope = "SELF"
        await session.commit()

    auditor_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "auditor1", "password": "Test@12345"},
    )
    assert auditor_login.status_code == 200, auditor_login.text
    auditor_headers = auth_headers(auditor_login.json()["data"]["access_token"])

    own_list = await client.get("/api/v1/audit-logs", headers=auditor_headers)
    assert own_list.status_code == 200, own_list.text
    own_body = own_list.json()["data"]
    assert own_body["total"] == 1
    assert own_body["items"][0]["username"] == "auditor1"

    forbidden_detail = await client.get(
        f"/api/v1/audit-logs/{admin_log_id}",
        headers=auditor_headers,
    )
    assert forbidden_detail.status_code == 404

    await _create_user("employee1", "REPAIRER")
    employee_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "employee1", "password": "Test@12345"},
    )
    assert employee_login.status_code == 200, employee_login.text
    employee_headers = auth_headers(employee_login.json()["data"]["access_token"])

    denied = await client.get("/api/v1/audit-logs", headers=employee_headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == 40300
