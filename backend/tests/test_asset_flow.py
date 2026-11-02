from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import insert, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AssetModel,
    AuditLog,
    Dept,
    Role,
    User,
    user_roles,
)
from app.services.asset_flow_service import AssetFlowService
from tests.helpers import auth_headers, login

TEST_PASSWORD = "Test@12345"


async def _ensure_user(username: str, real_name: str, role_code: str) -> int:
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
        )
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role.id)
        )
        await session.commit()
        return user.id


async def _ensure_asset(
    asset_no: str,
    name: str,
    status: str = AssetStatus.IN_STOCK,
    category_code: str = "HW-LAPTOP",
    model_code: str | None = None,
) -> int:
    async with AsyncSessionLocal() as session:
        category = (
            await session.execute(
                select(AssetCategory).where(AssetCategory.code == category_code)
            )
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        model_id = None
        if model_code:
            model_id = int(
                (
                    await session.execute(
                        select(AssetModel.id).where(AssetModel.code == model_code)
                    )
                ).scalar_one()
            )
        asset = Asset(
            asset_no=asset_no,
            name=name,
            category_id=category.id,
            model_id=model_id,
            dept_id=dept.id,
            status=status,
            location="A 座 101",
        )
        session.add(asset)
        await session.commit()
        return asset.id


async def _category_id(code: str = "HW-LAPTOP") -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    select(AssetCategory.id).where(AssetCategory.code == code)
                )
            ).scalar_one()
        )


async def _dept_id(code: str = "IT") -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(select(Dept.id).where(Dept.code == code))
            ).scalar_one()
        )


async def _create_and_stock_in(
    client: AsyncClient,
    headers: dict[str, str],
    asset_no: str,
    name: str,
) -> int:
    created = await client.post(
        "/api/v1/assets",
        json={
            "asset_no": asset_no,
            "name": name,
            "category_id": await _category_id(),
            "dept_id": await _dept_id(),
            "location": "A 座 101",
            "custom_fields": {},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    asset = created.json()["data"]
    assert asset["status"] == AssetStatus.PENDING_STOCK

    stocked = await client.post(
        f"/api/v1/assets/{asset['id']}/stock-in",
        json={"version": asset["version"]},
        headers=headers,
    )
    assert stocked.status_code == 200, stocked.text
    assert stocked.json()["data"]["status"] == AssetStatus.IN_STOCK
    return asset["id"]


async def _login_as(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["data"]["access_token"])


async def test_requisition_and_return_flow(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    asset_id = await _create_and_stock_in(
        client, admin_headers, "ITAM-FLOW-0001", "流程测试笔记本"
    )
    employee_id = await _ensure_user("flow_emp", "流程员工", "EMPLOYEE")
    await _ensure_user("flow_dept", "部门管理员", "DEPT_ADMIN")
    await _ensure_user("flow_asset", "资产管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "flow_emp")
    dept_headers = await _login_as(client, "flow_dept")
    asset_headers = await _login_as(client, "flow_asset")

    available = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": await _category_id()},
        headers=emp_headers,
    )
    assert available.status_code == 200, available.text
    assert available.json()["data"]["total"] == 1

    categories = await client.get(
        "/api/v1/asset-requests/available-categories", headers=emp_headers
    )
    assert categories.status_code == 200, categories.text
    assert categories.json()["data"][0]["available_count"] == 1

    missing_category = await client.get(
        "/api/v1/asset-requests/available-assets", headers=emp_headers
    )
    assert missing_category.status_code == 422

    unknown_category = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": 999999},
        headers=emp_headers,
    )
    assert unknown_category.status_code == 404

    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": await _category_id(),
            "include_child": True,
            "reason": "新员工办公使用",
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request = created.json()["data"]
    assert request["request_no"].startswith("LY-")
    assert request["status"] == "PENDING_APPROVAL"
    assert request["category_name"] == "笔记本电脑"
    assert request["asset_id"] is None
    assert request["approval_stage"] == "DEPT"
    assert request["can_cancel"] is True
    request_id = request["id"]

    forbidden_approve = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "自助审批"},
        headers=emp_headers,
    )
    assert forbidden_approve.status_code == 403
    assert forbidden_approve.json()["code"] == 40300

    asset_pending = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_APPROVAL"},
        headers=asset_headers,
    )
    assert asset_pending.status_code == 200, asset_pending.text
    assert asset_pending.json()["data"]["total"] == 0

    wrong_stage = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "越级审批"},
        headers=asset_headers,
    )
    assert wrong_stage.status_code == 403, wrong_stage.text

    review = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_APPROVAL"},
        headers=dept_headers,
    )
    assert review.status_code == 200, review.text
    review_page = review.json()["data"]
    assert review_page["total"] == 1
    assert review_page["items"][0]["can_approve"] is True
    assert review_page["items"][0]["can_outbound"] is False

    dept_approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "部门同意"},
        headers=dept_headers,
    )
    assert dept_approved.status_code == 200, dept_approved.text
    dept_data = dept_approved.json()["data"]
    assert dept_data["status"] == "PENDING_APPROVAL"
    assert dept_data["approval_stage"] == "ASSET"
    assert dept_data["approvals"][0]["step_code"] == "DEPT"
    assert dept_data["approvals"][0]["action"] == "APPROVE"
    assert dept_data["asset_id"] is None

    approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "同意领用"},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["status"] == "PENDING_OUTBOUND"
    assert approved_data["approval_stage"] is None
    assert len(approved_data["approvals"]) == 2
    assert approved_data["approvals"][1]["step_code"] == "ASSET"
    assert approved_data["asset_id"] is None

    forbidden_outbound = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={"asset_id": asset_id, "version": 1, "location": "B 座 202"},
        headers=dept_headers,
    )
    assert forbidden_outbound.status_code == 403

    candidates = await client.get(
        f"/api/v1/asset-requests/{request_id}/outbound-assets",
        headers=asset_headers,
    )
    assert candidates.status_code == 200, candidates.text
    candidate_data = candidates.json()["data"]
    assert candidate_data["total"] == 1
    candidate = candidate_data["items"][0]
    assert candidate["id"] == asset_id

    outbound = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={
            "asset_id": candidate["id"],
            "version": candidate["version"],
            "location": "B 座 202",
        },
        headers=asset_headers,
    )
    assert outbound.status_code == 200, outbound.text
    outbound_data = outbound.json()["data"]
    assert outbound_data["status"] == "COMPLETED"
    assert outbound_data["asset_id"] == asset_id
    assert outbound_data["asset_no"] == "ITAM-FLOW-0001"
    assert outbound_data["asset_status"] == "IN_USE"

    detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    asset = detail.json()["data"]
    assert asset["status"] == "IN_USE"
    assert asset["custodian_id"] == employee_id
    assert asset["location"] == "B 座 202"

    history = await client.get(
        f"/api/v1/assets/{asset_id}/history", headers=admin_headers
    )
    assert history.status_code == 200, history.text
    history_items = history.json()["data"]
    assert len(history_items) == 2
    assert history_items[0]["action"] == "OUTBOUND"
    assert history_items[0]["from_status"] == "IN_STOCK"
    assert history_items[0]["to_status"] == "IN_USE"
    assert history_items[0]["before_snapshot"]["custodian_name"] is None
    assert history_items[0]["after_snapshot"]["custodian_name"] == "流程员工"
    assert history_items[1]["action"] == "INBOUND"
    assert history_items[1]["from_status"] == "PENDING_STOCK"
    assert history_items[1]["to_status"] == "IN_STOCK"

    duplicate_outbound = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={"version": outbound_data["asset_version"]},
        headers=asset_headers,
    )
    assert duplicate_outbound.status_code == 400

    mine = await client.get("/api/v1/my-assets", headers=emp_headers)
    assert mine.status_code == 200, mine.text
    assert [item["asset_id"] for item in mine.json()["data"]] == [asset_id]

    return_created = await client.post(
        "/api/v1/asset-returns",
        json={"asset_id": asset_id, "reason": "岗位调整"},
        headers=emp_headers,
    )
    assert return_created.status_code == 200, return_created.text
    return_request = return_created.json()["data"]
    assert return_request["request_no"].startswith("GH-")
    assert return_request["status"] == "PENDING_RETURN"
    assert return_request["source_request_id"] == request_id
    return_id = return_request["id"]

    forbidden_employee_confirm = await client.post(
        f"/api/v1/asset-requests/{return_id}/return-confirm",
        json={"version": return_request["asset_version"]},
        headers=emp_headers,
    )
    assert forbidden_employee_confirm.status_code == 403

    forbidden_dept_confirm = await client.post(
        f"/api/v1/asset-requests/{return_id}/return-confirm",
        json={"version": return_request["asset_version"]},
        headers=dept_headers,
    )
    assert forbidden_dept_confirm.status_code == 403

    returned = await client.post(
        f"/api/v1/asset-requests/{return_id}/return-confirm",
        json={
            "version": return_request["asset_version"],
            "location": "A 座 101",
            "comment": "外观完好",
        },
        headers=asset_headers,
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["status"] == "COMPLETED"

    detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    asset = detail.json()["data"]
    assert asset["status"] == "IN_STOCK"
    assert asset["custodian_id"] is None
    assert asset["location"] == "A 座 101"

    history = await client.get(
        f"/api/v1/assets/{asset_id}/history", headers=admin_headers
    )
    history_items = history.json()["data"]
    assert len(history_items) == 3
    latest = history_items[0]
    assert latest["action"] == "RETURN"
    assert latest["from_status"] == "IN_USE"
    assert latest["to_status"] == "IN_STOCK"
    assert latest["before_snapshot"]["custodian_name"] == "流程员工"
    assert latest["after_snapshot"]["custodian_name"] is None


async def test_available_assets_by_category(client: AsyncClient):
    await _ensure_user("cat_emp", "分类员工", "EMPLOYEE")
    emp_headers = await _login_as(client, "cat_emp")
    laptop_id = await _ensure_asset("ITAM-CAT-0001", "分类测试笔记本")
    desktop_id = await _ensure_asset(
        "ITAM-CAT-0002", "分类测试台式机", category_code="HW-DESKTOP"
    )

    computer_category_id = await _category_id("HW-COMPUTER")
    laptop_category_id = await _category_id("HW-LAPTOP")

    parent = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": computer_category_id},
        headers=emp_headers,
    )
    assert parent.status_code == 200, parent.text
    parent_data = parent.json()["data"]
    assert parent_data["total"] == 2
    assert {item["id"] for item in parent_data["items"]} == {laptop_id, desktop_id}

    direct = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": computer_category_id, "include_child": False},
        headers=emp_headers,
    )
    assert direct.status_code == 200, direct.text
    assert direct.json()["data"]["total"] == 0

    laptop = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": laptop_category_id},
        headers=emp_headers,
    )
    assert laptop.status_code == 200, laptop.text
    laptop_data = laptop.json()["data"]
    assert laptop_data["total"] == 1
    assert laptop_data["items"][0]["id"] == laptop_id

    categories = await client.get(
        "/api/v1/asset-requests/available-categories", headers=emp_headers
    )
    assert categories.status_code == 200, categories.text
    computer = next(
        item for item in categories.json()["data"] if item["id"] == computer_category_id
    )
    assert computer["available_count"] == 2
    laptop_node = next(
        item for item in computer["children"] if item["id"] == laptop_category_id
    )
    assert laptop_node["available_count"] == 1


async def test_available_models_and_model_filter(client: AsyncClient):
    await _ensure_user("model_emp", "型号员工", "EMPLOYEE")
    emp_headers = await _login_as(client, "model_emp")
    model_code = "LENOVO-X1-CARBON-G11"
    modeled_a = await _ensure_asset(
        "ITAM-MODEL-0001", "型号测试笔记本 A", model_code=model_code
    )
    modeled_b = await _ensure_asset(
        "ITAM-MODEL-0002", "型号测试笔记本 B", model_code=model_code
    )
    unmodeled = await _ensure_asset("ITAM-MODEL-0003", "未指定型号笔记本")
    await _ensure_asset(
        "ITAM-MODEL-0004",
        "在用笔记本",
        status=AssetStatus.IN_USE,
        model_code=model_code,
    )
    laptop_category_id = await _category_id()

    async with AsyncSessionLocal() as session:
        model_id = int(
            (
                await session.execute(
                    select(AssetModel.id).where(AssetModel.code == model_code)
                )
            ).scalar_one()
        )

    models = await client.get(
        "/api/v1/asset-requests/available-models",
        params={"category_id": laptop_category_id},
        headers=emp_headers,
    )
    assert models.status_code == 200, models.text
    model_items = models.json()["data"]
    assert sum(item["available_count"] for item in model_items) == 3
    modeled = next(item for item in model_items if item["model_id"] == model_id)
    assert modeled["model_name"] == "ThinkPad X1 Carbon Gen 11"
    assert modeled["brand"] == "Lenovo"
    assert modeled["spec"]
    assert modeled["available_count"] == 2
    unmodeled_item = next(item for item in model_items if item["model_id"] == 0)
    assert unmodeled_item["model_name"] == "未指定型号"
    assert unmodeled_item["available_count"] == 1

    unknown_category = await client.get(
        "/api/v1/asset-requests/available-models",
        params={"category_id": 999999},
        headers=emp_headers,
    )
    assert unknown_category.status_code == 404

    missing_category = await client.get(
        "/api/v1/asset-requests/available-models", headers=emp_headers
    )
    assert missing_category.status_code == 422

    by_model = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={
            "category_id": laptop_category_id,
            "model_ids": str(model_id),
            "page_size": 50,
        },
        headers=emp_headers,
    )
    assert by_model.status_code == 200, by_model.text
    by_model_data = by_model.json()["data"]
    assert by_model_data["total"] == 2
    assert {item["id"] for item in by_model_data["items"]} == {modeled_a, modeled_b}
    assert {item["model_id"] for item in by_model_data["items"]} == {model_id}

    unmodeled_only = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": laptop_category_id, "model_ids": "0"},
        headers=emp_headers,
    )
    assert unmodeled_only.status_code == 200, unmodeled_only.text
    assert unmodeled_only.json()["data"]["total"] == 1
    assert unmodeled_only.json()["data"]["items"][0]["id"] == unmodeled

    combined = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={
            "category_id": laptop_category_id,
            "model_ids": f"{model_id},0",
            "page_size": 50,
        },
        headers=emp_headers,
    )
    assert combined.status_code == 200, combined.text
    assert combined.json()["data"]["total"] == 3

    invalid = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": laptop_category_id, "model_ids": "abc"},
        headers=emp_headers,
    )
    assert invalid.status_code == 400


async def test_version_conflict_returns_exact_message(client: AsyncClient):
    await _ensure_user("flow_emp2", "流程员工二", "EMPLOYEE")
    await _ensure_user("flow_dept2", "部门管理员二", "DEPT_ADMIN")
    await _ensure_user("flow_asset2", "资产管理员二", "ASSET_ADMIN")
    asset_id = await _ensure_asset("ITAM-FLOW-0002", "乐观锁测试笔记本")
    emp_headers = await _login_as(client, "flow_emp2")
    dept_headers = await _login_as(client, "flow_dept2")
    asset_headers = await _login_as(client, "flow_asset2")

    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": await _category_id(),
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request_id = created.json()["data"]["id"]

    dept_approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "部门同意"},
        headers=dept_headers,
    )
    assert dept_approved.status_code == 200, dept_approved.text

    approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "同意"},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text
    candidates = await client.get(
        f"/api/v1/asset-requests/{request_id}/outbound-assets",
        headers=asset_headers,
    )
    stale_version = candidates.json()["data"]["items"][0]["version"]

    async with AsyncSessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        asset.location = "并发修改位置"
        await session.commit()

    conflict = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={
            "asset_id": asset_id,
            "version": stale_version,
            "location": "C 座 101",
        },
        headers=asset_headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == 40911
    assert conflict.json()["message"] == "资产状态已变更，请刷新后重试"

    async with AsyncSessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        assert asset.status == "IN_STOCK"
        history_count = await session.scalar(
            select(AssetHistory).where(AssetHistory.asset_id == asset_id)
        )
    assert history_count is None


async def test_borrow_flow_due_reminder_and_completion(client: AsyncClient):
    await _ensure_user("flow_emp3", "借用员工", "EMPLOYEE")
    await _ensure_user("flow_dept3", "部门管理员三", "DEPT_ADMIN")
    await _ensure_user("flow_asset3", "资产管理员三", "ASSET_ADMIN")
    asset_id = await _ensure_asset("ITAM-FLOW-0003", "借用测试投影仪")
    emp_headers = await _login_as(client, "flow_emp3")
    dept_headers = await _login_as(client, "flow_dept3")
    asset_headers = await _login_as(client, "flow_asset3")

    expected = (date.today() + timedelta(days=2)).isoformat()
    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "BORROW",
            "category_id": await _category_id(),
            "include_child": True,
            "reason": "会议室使用",
            "expected_return_date": expected,
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request = created.json()["data"]
    request_id = request["id"]
    assert request["asset_id"] is None

    dept_approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "部门同意借用"},
        headers=dept_headers,
    )
    assert dept_approved.status_code == 200, dept_approved.text

    approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "同意借用"},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text

    candidates = await client.get(
        f"/api/v1/asset-requests/{request_id}/outbound-assets",
        headers=asset_headers,
    )
    candidate = candidates.json()["data"]["items"][0]
    outbound = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={"asset_id": candidate["id"], "version": candidate["version"]},
        headers=asset_headers,
    )
    assert outbound.status_code == 200, outbound.text
    outbound_data = outbound.json()["data"]
    assert outbound_data["status"] == "BORROWED"
    assert outbound_data["asset_status"] == "BORROWED"

    async with AsyncSessionLocal() as session:
        created_reminders = await AssetFlowService(session).record_due_reminders()
    assert created_reminders >= 1
    async with AsyncSessionLocal() as session:
        duplicate_reminders = await AssetFlowService(session).record_due_reminders()
    assert duplicate_reminders == 0

    notifications = await client.get(
        "/api/v1/notifications/summary", headers=emp_headers
    )
    assert notifications.status_code == 200, notifications.text
    ids = {item["id"] for item in notifications.json()["data"]["items"]}
    assert f"borrow-due-{request_id}" in ids

    mine = await client.get("/api/v1/my-assets", headers=emp_headers)
    mine_item = next(
        item for item in mine.json()["data"] if item["asset_id"] == asset_id
    )
    assert mine_item["status"] == "BORROWED"
    assert mine_item["days_to_due"] == 2

    return_created = await client.post(
        "/api/v1/asset-returns",
        json={"asset_id": asset_id, "reason": "提前归还"},
        headers=emp_headers,
    )
    assert return_created.status_code == 200, return_created.text
    return_data = return_created.json()["data"]

    returned = await client.post(
        f"/api/v1/asset-requests/{return_data['id']}/return-confirm",
        json={"version": return_data["asset_version"]},
        headers=asset_headers,
    )
    assert returned.status_code == 200, returned.text

    source = await client.get(
        f"/api/v1/asset-requests/{request_id}", headers=asset_headers
    )
    assert source.json()["data"]["status"] == "COMPLETED"


async def test_rejection_requires_reason_and_writes_audit(client: AsyncClient):
    await _ensure_asset("ITAM-REJECT-0001", "驳回测试笔记本")
    await _ensure_user("reject_emp", "驳回员工", "EMPLOYEE")
    await _ensure_user("reject_dept", "驳回部门管理员", "DEPT_ADMIN")
    await _ensure_user("reject_asset", "驳回资产管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "reject_emp")
    dept_headers = await _login_as(client, "reject_dept")
    asset_headers = await _login_as(client, "reject_asset")

    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": await _category_id(),
            "reason": "驳回流程测试",
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request_id = created.json()["data"]["id"]

    missing_reason = await client.post(
        f"/api/v1/asset-requests/{request_id}/reject",
        json={"comment": "  "},
        headers=dept_headers,
    )
    assert missing_reason.status_code == 400, missing_reason.text

    rejected = await client.post(
        f"/api/v1/asset-requests/{request_id}/reject",
        json={"comment": "部门预算不足"},
        headers=dept_headers,
    )
    assert rejected.status_code == 200, rejected.text
    rejected_data = rejected.json()["data"]
    assert rejected_data["status"] == "REJECTED"
    assert rejected_data["approval_stage"] is None
    assert rejected_data["approvals"][0]["step_code"] == "DEPT"
    assert rejected_data["approvals"][0]["action"] == "REJECT"
    assert rejected_data["approvals"][0]["comment"] == "部门预算不足"

    approve_rejected = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "继续审批"},
        headers=asset_headers,
    )
    assert approve_rejected.status_code == 400, approve_rejected.text

    detail = await client.get(
        f"/api/v1/asset-requests/{request_id}", headers=emp_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["approvals"][0]["action_label"] == "驳回"

    async with AsyncSessionLocal() as session:
        actions = list(
            (
                await session.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.in_(
                            ("asset.request.create", "asset.request.reject")
                        )
                    )
                )
            ).scalars()
        )
    assert "asset.request.create" in actions
    assert "asset.request.reject" in actions


async def test_approval_config_toggle_skips_department_stage(client: AsyncClient):
    await _ensure_asset("ITAM-CONFIG-0001", "审批配置测试笔记本")
    await _ensure_user("config_emp", "配置员工", "EMPLOYEE")
    await _ensure_user("config_dept", "配置部门管理员", "DEPT_ADMIN")
    await _ensure_user("config_asset", "配置资产管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "config_emp")
    dept_headers = await _login_as(client, "config_dept")
    asset_headers = await _login_as(client, "config_asset")

    config = await client.get(
        "/api/v1/asset-requests/approval-config", headers=asset_headers
    )
    assert config.status_code == 200, config.text
    config_data = config.json()["data"]
    assert config_data["dept_approval_required"] is True

    forbidden = await client.get(
        "/api/v1/asset-requests/approval-config", headers=emp_headers
    )
    assert forbidden.status_code == 403

    wrong_role = await client.put(
        "/api/v1/asset-requests/approval-config",
        json={
            "dept_approval_required": False,
            "version": config_data["version"],
        },
        headers=dept_headers,
    )
    assert wrong_role.status_code == 403, wrong_role.text

    stale = await client.put(
        "/api/v1/asset-requests/approval-config",
        json={"dept_approval_required": False, "version": 999},
        headers=asset_headers,
    )
    assert stale.status_code == 409, stale.text

    updated = await client.put(
        "/api/v1/asset-requests/approval-config",
        json={
            "dept_approval_required": False,
            "version": config_data["version"],
        },
        headers=asset_headers,
    )
    assert updated.status_code == 200, updated.text
    updated_data = updated.json()["data"]
    assert updated_data["dept_approval_required"] is False
    assert updated_data["version"] == config_data["version"] + 1

    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": await _category_id(),
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request = created.json()["data"]
    assert request["approval_stage"] == "ASSET"
    assert request["dept_approval_required"] is False
    request_id = request["id"]

    dept_pending = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_APPROVAL"},
        headers=dept_headers,
    )
    assert dept_pending.json()["data"]["total"] == 0

    dept_attempt = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "部门审批"},
        headers=dept_headers,
    )
    assert dept_attempt.status_code == 403, dept_attempt.text

    approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "资产审批"},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "PENDING_OUTBOUND"


async def test_category_drilldown_requires_leaf_and_keeps_flow(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    employee_id = await _ensure_user("drill_emp", "钻取员工", "EMPLOYEE")
    await _ensure_user("drill_dept", "钻取部门管理员", "DEPT_ADMIN")
    await _ensure_user("drill_asset", "钻取资产管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "drill_emp")
    dept_headers = await _login_as(client, "drill_dept")
    asset_headers = await _login_as(client, "drill_asset")

    computer_id = await _category_id("HW-COMPUTER")
    laptop_id = await _category_id("HW-LAPTOP")
    drawing = await client.post(
        "/api/v1/asset-categories",
        json={
            "parent_id": laptop_id,
            "name": "绘图笔记本",
            "code": "HW-LAPTOP-DRAW",
            "sort": 1,
        },
        headers=admin_headers,
    )
    assert drawing.status_code == 200, drawing.text
    drawing_id = drawing.json()["data"]["id"]
    asset_id = await _ensure_asset(
        "ITAM-DRILL-0001", "绘图测试笔记本", category_code="HW-LAPTOP-DRAW"
    )

    roots = await client.get(
        "/api/v1/asset-requests/category-options", headers=emp_headers
    )
    assert roots.status_code == 200, roots.text
    computer = next(
        item for item in roots.json()["data"] if item["id"] == computer_id
    )
    assert computer["has_children"] is True
    assert computer["available_count"] == 1

    level_one = await client.get(
        "/api/v1/asset-requests/category-options",
        params={"parent_id": computer_id},
        headers=emp_headers,
    )
    assert level_one.status_code == 200, level_one.text
    laptop = next(
        item for item in level_one.json()["data"] if item["id"] == laptop_id
    )
    assert laptop["has_children"] is True
    assert laptop["available_count"] == 1

    level_two = await client.get(
        "/api/v1/asset-requests/category-options",
        params={"parent_id": laptop_id},
        headers=emp_headers,
    )
    assert level_two.status_code == 200, level_two.text
    leaf = next(
        item for item in level_two.json()["data"] if item["id"] == drawing_id
    )
    assert leaf["has_children"] is False
    assert leaf["available_count"] == 1

    empty_level = await client.get(
        "/api/v1/asset-requests/category-options",
        params={"parent_id": drawing_id},
        headers=emp_headers,
    )
    assert empty_level.status_code == 200, empty_level.text
    assert empty_level.json()["data"] == []

    unknown_level = await client.get(
        "/api/v1/asset-requests/category-options",
        params={"parent_id": 999999},
        headers=emp_headers,
    )
    assert unknown_level.status_code == 404

    for middle_id in (computer_id, laptop_id):
        rejected = await client.post(
            "/api/v1/asset-requests",
            json={
                "request_type": "REQUISITION",
                "category_id": middle_id,
                "reason": "中间层级提交测试",
            },
            headers=emp_headers,
        )
        assert rejected.status_code == 400, rejected.text
        assert "最终一级分类" in rejected.json()["message"]

    created = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": drawing_id,
            "include_child": True,
            "reason": "绘图工作站使用",
        },
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    request = created.json()["data"]
    request_id = request["id"]
    assert request["category_id"] == drawing_id
    assert request["category_name"] == "绘图笔记本"
    assert request["include_child"] is False
    assert request["status"] == "PENDING_APPROVAL"

    dept_approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "部门同意"},
        headers=dept_headers,
    )
    assert dept_approved.status_code == 200, dept_approved.text

    approved = await client.post(
        f"/api/v1/asset-requests/{request_id}/approve",
        json={"comment": "资产同意"},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "PENDING_OUTBOUND"

    candidates = await client.get(
        f"/api/v1/asset-requests/{request_id}/outbound-assets",
        headers=asset_headers,
    )
    assert candidates.status_code == 200, candidates.text
    candidate_data = candidates.json()["data"]
    assert candidate_data["total"] == 1
    candidate = candidate_data["items"][0]
    assert candidate["id"] == asset_id

    outbound = await client.post(
        f"/api/v1/asset-requests/{request_id}/outbound",
        json={"asset_id": candidate["id"], "version": candidate["version"]},
        headers=asset_headers,
    )
    assert outbound.status_code == 200, outbound.text
    outbound_data = outbound.json()["data"]
    assert outbound_data["status"] == "COMPLETED"
    assert outbound_data["asset_id"] == asset_id

    detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    asset = detail.json()["data"]
    assert asset["status"] == "IN_USE"
    assert asset["custodian_id"] == employee_id

    return_created = await client.post(
        "/api/v1/asset-returns",
        json={"asset_id": asset_id, "reason": "测试归还"},
        headers=emp_headers,
    )
    assert return_created.status_code == 200, return_created.text
    return_data = return_created.json()["data"]

    returned = await client.post(
        f"/api/v1/asset-requests/{return_data['id']}/return-confirm",
        json={"version": return_data["asset_version"]},
        headers=asset_headers,
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["data"]["status"] == "COMPLETED"

    detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    asset = detail.json()["data"]
    assert asset["status"] == "IN_STOCK"
    assert asset["custodian_id"] is None


async def test_application_category_tree_matches_enabled_catalog(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    await _ensure_user("tree_emp", "分类树员工", "EMPLOYEE")
    emp_headers = await _login_as(client, "tree_emp")

    catalog_response = await client.get(
        "/api/v1/asset-categories/tree", headers=admin_headers
    )
    assert catalog_response.status_code == 200, catalog_response.text

    def flatten_enabled(nodes: list[dict]) -> list[tuple]:
        result: list[tuple] = []
        for node in nodes:
            if node["status"] != 1:
                continue
            result.append(
                (node["id"], node["parent_id"], node["name"], bool(node["children"]))
            )
            result.extend(flatten_enabled(node["children"]))
        return result

    expected = flatten_enabled(catalog_response.json()["data"])

    async def walk_options(parent_id: int | None = None) -> list[tuple]:
        response = await client.get(
            "/api/v1/asset-requests/category-options",
            params={"parent_id": parent_id} if parent_id else None,
            headers=emp_headers,
        )
        assert response.status_code == 200, response.text
        result: list[tuple] = []
        for item in response.json()["data"]:
            result.append(
                (item["id"], item["parent_id"], item["name"], item["has_children"])
            )
            if item["has_children"]:
                result.extend(await walk_options(item["id"]))
        return result

    actual = await walk_options()
    assert actual == expected

    computer_id = await _category_id("HW-COMPUTER")
    server_id = await _category_id("HW-SERVER")
    level_one = await client.get(
        "/api/v1/asset-requests/category-options",
        params={"parent_id": computer_id},
        headers=emp_headers,
    )
    assert level_one.status_code == 200, level_one.text
    server = next(
        item for item in level_one.json()["data"] if item["id"] == server_id
    )
    assert server["has_children"] is False
    assert server["available_count"] == 0

    nested = await client.get(
        "/api/v1/asset-requests/available-categories", headers=emp_headers
    )
    assert nested.status_code == 200, nested.text
    nested_roots = nested.json()["data"]
    assert {item["name"] for item in nested_roots} >= {
        "计算机设备",
        "网络设备",
        "外设与配件",
        "软件资产",
        "办公耗材",
    }
    nested_computer = next(item for item in nested_roots if item["id"] == computer_id)
    nested_server = next(
        item for item in nested_computer["children"] if item["id"] == server_id
    )
    assert nested_server["available_count"] == 0

    no_stock = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": server_id,
            "reason": "无库存叶子分类校验",
        },
        headers=emp_headers,
    )
    assert no_stock.status_code == 400, no_stock.text
    assert "暂无可用的在库资产" in no_stock.json()["message"]

    rejected = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": computer_id,
            "reason": "中间层级不可提交",
        },
        headers=emp_headers,
    )
    assert rejected.status_code == 400, rejected.text
    assert "最终一级分类" in rejected.json()["message"]
