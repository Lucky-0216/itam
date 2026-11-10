from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import func, insert, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AuditLog,
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


async def _login_as(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["data"]["access_token"])


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
    category_code: str = "HW-LAPTOP",
) -> int:
    created = await client.post(
        "/api/v1/assets",
        json={
            "asset_no": asset_no,
            "name": name,
            "category_id": await _category_id(category_code),
            "dept_id": await _dept_id(),
            "location": "A 座 101",
            "custom_fields": {},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    asset = created.json()["data"]
    stocked = await client.post(
        f"/api/v1/assets/{asset['id']}/stock-in",
        json={"version": asset["version"]},
        headers=headers,
    )
    assert stocked.status_code == 200, stocked.text
    assert stocked.json()["data"]["status"] == AssetStatus.IN_STOCK
    return asset["id"]


async def _asset_detail(
    client: AsyncClient, headers: dict[str, str], asset_id: int
) -> dict:
    response = await client.get(f"/api/v1/assets/{asset_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _direct_items(
    client: AsyncClient,
    headers: dict[str, str],
    keyword: str,
) -> list[dict]:
    response = await client.get(
        "/api/v1/asset-direct-outbound/assets",
        params={"keyword": keyword},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def _flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node["children"]))
    return result


async def test_direct_outbound_permission_and_multi_asset(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    employee_id = await _ensure_user("direct_emp", "直接员工", "EMPLOYEE")
    await _ensure_user("direct_asset_admin", "直接资产管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "direct_emp")
    admin_asset_headers = await _login_as(client, "direct_asset_admin")

    asset_a = await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0001", "直接出库笔记本A"
    )
    asset_b = await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0002", "直接出库笔记本B"
    )

    denied_list = await client.get(
        "/api/v1/asset-direct-outbound/assets", headers=emp_headers
    )
    assert denied_list.status_code == 403
    denied_post = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "无权限直接出库",
            "items": [{"asset_id": asset_a, "version": 1}],
        },
        headers=emp_headers,
    )
    assert denied_post.status_code == 403

    available = await _direct_items(
        client, admin_asset_headers, "ITAM-DIRECT-000"
    )
    versions = {item["id"]: item["version"] for item in available}
    assert asset_a in versions and asset_b in versions

    users = await client.get(
        "/api/v1/asset-direct-outbound/users",
        params={"keyword": "direct_emp"},
        headers=admin_asset_headers,
    )
    assert users.status_code == 200, users.text
    assert any(item["real_name"] == "直接员工" for item in users.json()["data"])

    categories = await client.get(
        "/api/v1/asset-direct-outbound/categories",
        headers=admin_asset_headers,
    )
    assert categories.status_code == 200, categories.text
    assert categories.json()["data"]

    stock_before = await client.get(
        "/api/v1/stock/overview", headers=admin_asset_headers
    )
    assert stock_before.status_code == 200, stock_before.text
    before_count = stock_before.json()["data"]["in_stock_count"]

    outbound = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "新员工入职配置",
            "location": "B 座 302",
            "items": [
                {"asset_id": asset_a, "version": versions[asset_a]},
                {"asset_id": asset_b, "version": versions[asset_b]},
            ],
        },
        headers=admin_asset_headers,
    )
    assert outbound.status_code == 200, outbound.text
    result = outbound.json()["data"]
    assert result["count"] == 2
    assert result["user_name"] == "直接员工"
    assert all(item["request_id"] is None for item in result["items"])

    for asset_id in (asset_a, asset_b):
        asset = await _asset_detail(client, admin_headers, asset_id)
        assert asset["status"] == AssetStatus.IN_USE
        assert asset["custodian_id"] == employee_id
        assert asset["dept_id"] == await _dept_id()
        assert asset["location"] == "B 座 302"

        history = await client.get(
            f"/api/v1/assets/{asset_id}/history", headers=admin_headers
        )
        assert history.status_code == 200, history.text
        outbound_rows = [
            row for row in history.json()["data"] if row["action"] == "OUTBOUND"
        ]
        assert len(outbound_rows) == 1
        assert outbound_rows[0]["request_id"] is None
        assert outbound_rows[0]["after_snapshot"]["custodian_name"] == "直接员工"
        assert outbound_rows[0]["after_snapshot"]["direct_outbound"] is True

    stock_after = await client.get(
        "/api/v1/stock/overview", headers=admin_asset_headers
    )
    assert stock_after.json()["data"]["in_stock_count"] == before_count - 2

    async with AsyncSessionLocal() as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "asset.outbound.direct",
                AuditLog.resource_id == str(asset_a),
            )
        )
        assert audit_count == 1

    listed_after = await _direct_items(
        client, admin_asset_headers, "ITAM-DIRECT-000"
    )
    assert all(item["id"] not in (asset_a, asset_b) for item in listed_after)

    repeat = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "重复出库",
            "items": [
                {"asset_id": asset_a, "version": versions[asset_a]},
            ],
        },
        headers=admin_asset_headers,
    )
    assert repeat.status_code == 409


async def test_direct_outbound_version_conflict_and_validation(
    client: AsyncClient,
):
    admin_headers = auth_headers((await login(client))["access_token"])
    employee_id = await _ensure_user("direct_conflict", "冲突员工", "EMPLOYEE")
    await _ensure_user("direct_conflict_admin", "冲突管理员", "ASSET_ADMIN")
    admin_asset_headers = await _login_as(client, "direct_conflict_admin")
    asset_id = await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0101", "冲突测试资产"
    )
    items = await _direct_items(client, admin_asset_headers, "ITAM-DIRECT-0101")
    version = next(item["version"] for item in items if item["id"] == asset_id)

    stale = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "版本过期",
            "items": [{"asset_id": asset_id, "version": version + 1}],
        },
        headers=admin_asset_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == 40911

    missing_reason = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "   ",
            "items": [{"asset_id": asset_id, "version": version}],
        },
        headers=admin_asset_headers,
    )
    assert missing_reason.status_code == 422

    borrow_without_date = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "BORROW",
            "reason": "临时借用",
            "items": [{"asset_id": asset_id, "version": version}],
        },
        headers=admin_asset_headers,
    )
    assert borrow_without_date.status_code == 422

    duplicated = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "重复选择",
            "items": [
                {"asset_id": asset_id, "version": version},
                {"asset_id": asset_id, "version": version},
            ],
        },
        headers=admin_asset_headers,
    )
    assert duplicated.status_code == 422

    asset = await _asset_detail(client, admin_headers, asset_id)
    assert asset["status"] == AssetStatus.IN_STOCK


async def test_direct_borrow_return_and_reissue(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    employee_id = await _ensure_user("direct_borrow", "借用员工", "EMPLOYEE")
    await _ensure_user("direct_borrow_admin", "借用管理员", "ASSET_ADMIN")
    emp_headers = await _login_as(client, "direct_borrow")
    admin_asset_headers = await _login_as(client, "direct_borrow_admin")
    asset_id = await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0201", "借用测试笔记本"
    )
    items = await _direct_items(client, admin_asset_headers, "ITAM-DIRECT-0201")
    version = next(item["version"] for item in items if item["id"] == asset_id)
    due = (date.today() + timedelta(days=3)).isoformat()

    borrowed = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "BORROW",
            "reason": "项目临时借用",
            "expected_return_date": due,
            "items": [{"asset_id": asset_id, "version": version}],
        },
        headers=admin_asset_headers,
    )
    assert borrowed.status_code == 200, borrowed.text
    result = borrowed.json()["data"]
    assert result["request_type"] == "BORROW"
    request_id = result["items"][0]["request_id"]
    assert request_id is not None

    asset = await _asset_detail(client, admin_headers, asset_id)
    assert asset["status"] == AssetStatus.BORROWED
    assert asset["custodian_id"] == employee_id

    mine = await client.get("/api/v1/my-assets", headers=emp_headers)
    assert mine.status_code == 200, mine.text
    mine_row = next(
        item for item in mine.json()["data"] if item["asset_id"] == asset_id
    )
    assert mine_row["status"] == AssetStatus.BORROWED
    assert mine_row["request_id"] == request_id
    assert mine_row["expected_return_date"] == due

    return_created = await client.post(
        "/api/v1/asset-returns",
        json={"asset_id": asset_id, "reason": "项目结束归还"},
        headers=emp_headers,
    )
    assert return_created.status_code == 200, return_created.text
    return_request = return_created.json()["data"]
    assert return_request["status"] == "PENDING_RETURN"

    asset = await _asset_detail(client, admin_headers, asset_id)
    confirmed = await client.post(
        f"/api/v1/asset-requests/{return_request['id']}/return-confirm",
        json={"version": asset["version"], "location": "A 座 101"},
        headers=admin_asset_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "COMPLETED"

    asset = await _asset_detail(client, admin_headers, asset_id)
    assert asset["status"] == AssetStatus.IN_STOCK
    assert asset["custodian_id"] is None

    items = await _direct_items(client, admin_asset_headers, "ITAM-DIRECT-0201")
    version = next(item["version"] for item in items if item["id"] == asset_id)
    reissued = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": employee_id,
            "request_type": "REQUISITION",
            "reason": "归还后重新分配",
            "items": [{"asset_id": asset_id, "version": version}],
        },
        headers=admin_asset_headers,
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["data"]["items"][0]["status"] == AssetStatus.IN_USE

    # 员工申请链路不受影响（补一台在库资产，避免零库存拦截）
    await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0202", "员工申请用笔记本"
    )
    employee_request = await client.post(
        "/api/v1/asset-requests",
        json={
            "request_type": "REQUISITION",
            "category_id": await _category_id(),
            "reason": "员工正常申请",
        },
        headers=emp_headers,
    )
    assert employee_request.status_code == 200, employee_request.text
    assert employee_request.json()["data"]["status"] == "PENDING_APPROVAL"


async def test_direct_outbound_enforces_asset_domain(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = (
        await client.get("/api/v1/roles/menu-tree", headers=admin_headers)
    ).json()["data"]
    direct_menu = next(
        item
        for item in _flatten(menus)
        if item["permission_code"] == "asset:outbound:direct"
    )
    role_created = await client.post(
        "/api/v1/roles",
        json={
            "code": "IT_DOMAIN_OUTBOUND",
            "name": "IT域直接出库",
            "data_scope": "ALL",
            "domain_scope": "CUSTOM",
            "asset_domains": ["IT"],
            "sort": 88,
            "status": 1,
        },
        headers=admin_headers,
    )
    assert role_created.status_code == 200, role_created.text
    role = role_created.json()["data"]
    assigned = await client.put(
        f"/api/v1/roles/{role['id']}/menus",
        json={"menu_ids": [direct_menu["id"]], "version": role["version"]},
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text

    async with AsyncSessionLocal() as session:
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        domain_user = User(
            username="direct_domain",
            password_hash=hash_password(TEST_PASSWORD),
            real_name="IT域出库员",
            dept_id=dept.id,
            status=1,
            must_change_password=False,
        )
        session.add(domain_user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=domain_user.id, role_id=role["id"])
        )
        await session.commit()
        domain_user_id = domain_user.id

    domain_headers = await _login_as(client, "direct_domain")
    it_asset = await _create_and_stock_in(
        client, admin_headers, "ITAM-DIRECT-0301", "IT域可出库资产"
    )
    admin_asset = await _create_and_stock_in(
        client,
        admin_headers,
        "ITAM-DIRECT-0302",
        "行政域不可出库资产",
        category_code="ADM-FURNITURE",
    )

    visible = await _direct_items(client, domain_headers, "ITAM-DIRECT-030")
    visible_ids = {item["id"] for item in visible}
    assert it_asset in visible_ids
    assert admin_asset not in visible_ids

    it_items = await _direct_items(client, domain_headers, "ITAM-DIRECT-0301")
    it_version = next(
        item["version"] for item in it_items if item["id"] == it_asset
    )
    forbidden = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": domain_user_id,
            "request_type": "REQUISITION",
            "reason": "跨域出库",
            "items": [{"asset_id": admin_asset, "version": 1}],
        },
        headers=domain_headers,
    )
    assert forbidden.status_code == 403

    allowed = await client.post(
        "/api/v1/asset-direct-outbound",
        json={
            "user_id": domain_user_id,
            "request_type": "REQUISITION",
            "reason": "IT域内出库",
            "items": [{"asset_id": it_asset, "version": it_version}],
        },
        headers=domain_headers,
    )
    assert allowed.status_code == 200, allowed.text

    async with AsyncSessionLocal() as session:
        admin_domain_status = await session.scalar(
            select(Asset.status).where(Asset.id == admin_asset)
        )
    assert admin_domain_status == AssetStatus.IN_STOCK

    async with AsyncSessionLocal() as session:
        history_count = await session.scalar(
            select(func.count())
            .select_from(AssetHistory)
            .where(
                AssetHistory.asset_id == it_asset,
                AssetHistory.action == "OUTBOUND",
            )
        )
        assert history_count == 1
