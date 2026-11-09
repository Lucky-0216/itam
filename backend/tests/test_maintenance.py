from httpx import AsyncClient
from sqlalchemy import insert, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AssetMaintenance,
    AssetMaintenanceRecord,
    Dept,
    Role,
    User,
    user_roles,
)
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
    *,
    custodian_id: int | None = None,
) -> int:
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
            custodian_id=custodian_id,
            status=status,
            location="A 座 101",
        )
        session.add(asset)
        await session.commit()
        return asset.id


async def _login_as(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["data"]["access_token"])


async def _create_and_approve(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    asset_id: int,
    repairer_id: int,
    approving_headers: dict[str, str],
) -> dict:
    created = await client.post(
        "/api/v1/maintenances",
        json={
            "asset_id": asset_id,
            "fault_description": "屏幕闪烁并伴随异响",
            "priority": "HIGH",
            "expected_date": "2026-11-01",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    order = created.json()["data"]
    approved = await client.post(
        f"/api/v1/maintenances/{order['id']}/approve",
        json={
            "version": order["asset_version"],
            "repairer_id": repairer_id,
            "comment": "同意送修",
        },
        headers=approving_headers,
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


async def test_maintenance_full_flow_with_optimistic_lock_and_cross_module_guard(
    client: AsyncClient,
):
    admin_headers = auth_headers((await login(client))["access_token"])
    reporter_id = await _ensure_user("mnt_reporter", "报修员工", "EMPLOYEE")
    repairer_id = await _ensure_user("mnt_repairer", "维修工程师", "REPAIRER")
    await _ensure_user("mnt_dept", "维修部门管理员", "DEPT_ADMIN")
    await _ensure_user("mnt_asset", "维修资产管理员", "ASSET_ADMIN")
    asset_id = await _ensure_asset(
        "ITAM-MNT-0001",
        "报修测试笔记本",
        AssetStatus.IN_USE,
        custodian_id=reporter_id,
    )
    reporter_headers = await _login_as(client, "mnt_reporter")
    repairer_headers = await _login_as(client, "mnt_repairer")
    dept_headers = await _login_as(client, "mnt_dept")
    asset_headers = await _login_as(client, "mnt_asset")

    created = await client.post(
        "/api/v1/maintenances",
        json={
            "asset_id": asset_id,
            "fault_description": "开机后风扇异响，屏幕偶发闪烁",
            "priority": "HIGH",
            "expected_date": "2026-11-01",
        },
        headers=reporter_headers,
    )
    assert created.status_code == 200, created.text
    order = created.json()["data"]
    assert order["maintenance_no"].startswith("WX-")
    assert order["status"] == "PENDING_APPROVAL"
    assert order["asset_status"] == "IN_USE"
    assert order["records"] == []
    order_id = order["id"]

    forbidden = await client.post(
        f"/api/v1/maintenances/{order_id}/approve",
        json={"version": order["asset_version"], "repairer_id": repairer_id},
        headers=reporter_headers,
    )
    assert forbidden.status_code == 403

    approved = await client.post(
        f"/api/v1/maintenances/{order_id}/approve",
        json={
            "version": order["asset_version"],
            "repairer_id": repairer_id,
            "comment": "同意送修",
        },
        headers=dept_headers,
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["status"] == "PENDING_REPAIR"
    assert approved_data["repairer_name"] == "维修工程师"
    assert approved_data["asset_status"] == "REPAIRING"

    blocked_transfer = await client.post(
        "/api/v1/asset-transfers",
        json={"asset_id": asset_id, "to_location": "B 座 201"},
        headers=asset_headers,
    )
    assert blocked_transfer.status_code == 400, blocked_transfer.text
    assert "维修" in blocked_transfer.json()["message"]

    async with AsyncSessionLocal() as session:
        category_id = (
            await session.execute(
                select(Asset.category_id).where(Asset.id == asset_id)
            )
        ).scalar_one()
    blocked_request = await client.post(
        "/api/v1/asset-requests",
        json={"request_type": "REQUISITION", "category_id": category_id},
        headers=reporter_headers,
    )
    assert blocked_request.status_code == 400, blocked_request.text
    assert "暂无可用的在库资产" in blocked_request.json()["message"]

    started = await client.post(
        f"/api/v1/maintenances/{order_id}/start", headers=repairer_headers
    )
    assert started.status_code == 200, started.text
    assert started.json()["data"]["status"] == "REPAIRING"

    progress = await client.post(
        f"/api/v1/maintenances/{order_id}/records",
        json={"record_type": "PROGRESS", "content": "拆机检查，清理风扇灰尘"},
        headers=repairer_headers,
    )
    assert progress.status_code == 200, progress.text
    assert len(progress.json()["data"]["records"]) == 1

    expense = await client.post(
        f"/api/v1/maintenances/{order_id}/records",
        json={
            "record_type": "EXPENSE",
            "content": "更换散热模组",
            "cost": "150.00",
        },
        headers=repairer_headers,
    )
    assert expense.status_code == 200, expense.text
    assert expense.json()["data"]["total_cost"] == "150.00"

    missing_cost = await client.post(
        f"/api/v1/maintenances/{order_id}/records",
        json={"record_type": "EXPENSE", "content": "未填写金额的费用"},
        headers=repairer_headers,
    )
    assert missing_cost.status_code == 400

    completed = await client.post(
        f"/api/v1/maintenances/{order_id}/complete",
        json={"repair_result": "更换散热模组后运行正常"},
        headers=repairer_headers,
    )
    assert completed.status_code == 200, completed.text
    completed_data = completed.json()["data"]
    assert completed_data["status"] == "PENDING_ACCEPTANCE"
    assert completed_data["asset_status"] == "REPAIRING"

    detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    stale_version = detail.json()["data"]["version"]

    async with AsyncSessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        asset.location = "并发修改位置"
        await session.commit()

    conflict = await client.post(
        f"/api/v1/maintenances/{order_id}/accept",
        json={"version": stale_version, "comment": "验收通过"},
        headers=dept_headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == 40911
    assert conflict.json()["message"] == "资产状态已变更，请刷新后重试"

    accepted = await client.post(
        f"/api/v1/maintenances/{order_id}/accept",
        json={"version": stale_version + 1, "comment": "验收通过"},
        headers=dept_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "COMPLETED"

    asset_detail = await client.get(f"/api/v1/assets/{asset_id}", headers=admin_headers)
    asset = asset_detail.json()["data"]
    assert asset["status"] == "IN_USE"
    assert asset["custodian_id"] == reporter_id
    assert asset["location"] == "并发修改位置"

    history = await client.get(
        f"/api/v1/assets/{asset_id}/history", headers=admin_headers
    )
    actions = [item["action"] for item in history.json()["data"]]
    assert actions == ["REPAIR_COMPLETED", "REPAIR_APPROVED"]

    async with AsyncSessionLocal() as session:
        row = await session.get(AssetMaintenance, order_id)
        assert row.status == "COMPLETED"
        assert row.total_cost == 150
        records = (
            await session.execute(
                select(AssetMaintenanceRecord).where(
                    AssetMaintenanceRecord.maintenance_id == order_id
                )
            )
        ).scalars().all()
        histories = (
            await session.execute(
                select(AssetHistory).where(AssetHistory.asset_id == asset_id)
            )
        ).scalars().all()
    assert len(records) == 2
    assert len(histories) == 2


async def test_maintenance_cancel_and_reject(client: AsyncClient):
    employee_id = await _ensure_user("mnt_cancel_emp", "撤销员工", "EMPLOYEE")
    await _ensure_user("mnt_cancel_asset", "撤销资产管理员", "ASSET_ADMIN")
    repairer_id = await _ensure_user("mnt_cancel_rep", "撤销维修员", "REPAIRER")
    first_asset = await _ensure_asset(
        "ITAM-MNT-0101", "待取消维修台式机", custodian_id=employee_id
    )
    second_asset = await _ensure_asset(
        "ITAM-MNT-0102", "待驳回维修显示器", custodian_id=employee_id
    )
    emp_headers = await _login_as(client, "mnt_cancel_emp")
    asset_headers = await _login_as(client, "mnt_cancel_asset")

    created = await client.post(
        "/api/v1/maintenances",
        json={"asset_id": first_asset, "fault_description": "无法开机"},
        headers=emp_headers,
    )
    assert created.status_code == 200, created.text
    order = created.json()["data"]
    cancelled = await client.post(
        f"/api/v1/maintenances/{order['id']}/cancel",
        json={"reason": "自行处理"},
        headers=emp_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    async with AsyncSessionLocal() as session:
        assert (await session.get(Asset, first_asset)).status == "IN_STOCK"

    second = await client.post(
        "/api/v1/maintenances",
        json={"asset_id": first_asset, "fault_description": "再次报修"},
        headers=emp_headers,
    )
    assert second.status_code == 200, second.text
    second_order = second.json()["data"]
    approved = await client.post(
        f"/api/v1/maintenances/{second_order['id']}/approve",
        json={"version": second_order["asset_version"], "repairer_id": repairer_id},
        headers=asset_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["asset_status"] == "REPAIRING"

    approved_cancel = await client.post(
        f"/api/v1/maintenances/{second_order['id']}/cancel",
        json={"reason": "取消送修"},
        headers=asset_headers,
    )
    assert approved_cancel.status_code == 200, approved_cancel.text
    assert approved_cancel.json()["data"]["status"] == "CANCELLED"
    async with AsyncSessionLocal() as session:
        restored = await session.get(Asset, first_asset)
        assert restored.status == "IN_STOCK"
        histories = (
            await session.execute(
                select(AssetHistory).where(AssetHistory.asset_id == first_asset)
            )
        ).scalars().all()
    assert [row.action for row in histories] == [
        "REPAIR_APPROVED",
        "REPAIR_CANCELLED",
    ]

    third = await client.post(
        "/api/v1/maintenances",
        json={"asset_id": second_asset, "fault_description": "屏幕亮线"},
        headers=emp_headers,
    )
    assert third.status_code == 200, third.text
    third_order = third.json()["data"]
    rejected = await client.post(
        f"/api/v1/maintenances/{third_order['id']}/reject",
        json={"comment": "不构成故障，建议继续观察"},
        headers=asset_headers,
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "REJECTED"
    async with AsyncSessionLocal() as session:
        assert (await session.get(Asset, second_asset)).status == "IN_STOCK"


async def test_maintenance_permissions_and_visibility(client: AsyncClient):
    first_emp = await _ensure_user("mnt_emp_one", "员工一", "EMPLOYEE")
    second_emp = await _ensure_user("mnt_emp_two", "员工二", "EMPLOYEE")
    first_repairer = await _ensure_user("mnt_rep_one", "维修员一", "REPAIRER")
    await _ensure_user("mnt_rep_two", "维修员二", "REPAIRER")
    await _ensure_user("mnt_vis_dept", "可见性部门管理员", "DEPT_ADMIN")
    first_asset = await _ensure_asset(
        "ITAM-MNT-0201",
        "员工一笔记本",
        AssetStatus.IN_USE,
        custodian_id=first_emp,
    )
    await _ensure_asset(
        "ITAM-MNT-0202",
        "员工二笔记本",
        AssetStatus.IN_USE,
        custodian_id=second_emp,
    )
    emp_one_headers = await _login_as(client, "mnt_emp_one")
    emp_two_headers = await _login_as(client, "mnt_emp_two")
    rep_one_headers = await _login_as(client, "mnt_rep_one")
    rep_two_headers = await _login_as(client, "mnt_rep_two")
    dept_headers = await _login_as(client, "mnt_vis_dept")

    options = await client.get(
        "/api/v1/maintenances/options/assets", headers=emp_two_headers
    )
    assert options.status_code == 200, options.text
    option_ids = [item["id"] for item in options.json()["data"]["items"]]
    assert first_asset not in option_ids

    denied = await client.post(
        "/api/v1/maintenances",
        json={"asset_id": first_asset, "fault_description": "无权报修他人资产"},
        headers=emp_two_headers,
    )
    assert denied.status_code == 403

    created = await client.post(
        "/api/v1/maintenances",
        json={"asset_id": first_asset, "fault_description": "键盘失灵"},
        headers=emp_one_headers,
    )
    assert created.status_code == 200, created.text
    order = created.json()["data"]

    forbidden_detail = await client.get(
        f"/api/v1/maintenances/{order['id']}", headers=emp_two_headers
    )
    assert forbidden_detail.status_code == 403

    before_assign = await client.get("/api/v1/maintenances", headers=rep_one_headers)
    assert before_assign.json()["data"]["total"] == 0

    approved = await client.post(
        f"/api/v1/maintenances/{order['id']}/approve",
        json={"version": order["asset_version"], "repairer_id": first_repairer},
        headers=dept_headers,
    )
    assert approved.status_code == 200, approved.text

    assigned = await client.get("/api/v1/maintenances", headers=rep_one_headers)
    assert assigned.json()["data"]["total"] == 1
    assert assigned.json()["data"]["items"][0]["maintenance_no"] == order["maintenance_no"]

    other_repairer = await client.get("/api/v1/maintenances", headers=rep_two_headers)
    assert other_repairer.json()["data"]["total"] == 0

    not_assigned = await client.post(
        f"/api/v1/maintenances/{order['id']}/start", headers=rep_two_headers
    )
    assert not_assigned.status_code == 403

    employee_list = await client.get("/api/v1/maintenances", headers=emp_one_headers)
    assert employee_list.json()["data"]["total"] == 1
    assert employee_list.json()["data"]["items"][0]["can_start"] is False
