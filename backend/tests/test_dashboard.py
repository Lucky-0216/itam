from datetime import timedelta

from sqlalchemy import update

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.models import Asset
from app.models.base import now_cst
from tests.helpers import auth_headers, login


async def test_dashboard_summary_metrics_and_charts(client):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    empty = await client.get(
        "/api/v1/dashboard/summary?scope=org", headers=headers
    )
    assert empty.status_code == 200, empty.text
    empty_data = empty.json()["data"]
    assert empty_data["scope"] == "org"
    assert empty_data["metrics"]["total_assets"] == 0
    assert len(empty_data["purchase_trend"]) == 12
    assert empty_data["status_distribution"]
    assert all(item["count"] == 0 for item in empty_data["status_distribution"])
    assert empty_data["category_distribution"] == []
    assert empty_data["warranty_expiring"] == []

    category = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "驾驶舱测试分类",
            "code": "DASH-CAT",
            "category_type": "HARDWARE",
            "sort": 10,
            "status": 1,
        },
        headers=headers,
    )
    assert category.status_code == 200, category.text
    category_id = category.json()["data"]["id"]

    today = now_cst().date()
    warranty_end = today + timedelta(days=10)
    created = await client.post(
        "/api/v1/assets",
        json={
            "name": "驾驶舱测试资产",
            "category_id": category_id,
            "purchase_date": today.isoformat(),
            "purchase_price": 1234.5,
            "warranty_end": warranty_end.isoformat(),
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    summary = await client.get(
        "/api/v1/dashboard/summary?scope=org", headers=headers
    )
    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]

    metrics = data["metrics"]
    assert metrics["total_assets"] == 1
    assert metrics["total_value"] == 1234.5
    assert metrics["pending_stock"] == 1
    assert metrics["warranty_30d"] == 1

    status_map = {item["status"]: item["count"] for item in data["status_distribution"]}
    assert status_map["PENDING_STOCK"] == 1
    assert status_map["IN_USE"] == 0

    categories = data["category_distribution"]
    assert categories[0]["name"] == "驾驶舱测试分类"
    assert categories[0]["count"] == 1

    trend = data["purchase_trend"]
    assert trend[-1]["month"] == today.strftime("%Y-%m")
    assert trend[-1]["count"] == 1

    warranty = data["warranty_expiring"]
    assert len(warranty) == 1
    assert warranty[0]["days_left"] == 10
    assert warranty[0]["name"] == "驾驶舱测试资产"

    recent = data["recent_assets"]
    assert recent[0]["name"] == "驾驶舱测试资产"
    assert recent[0]["status_label"] == "待入库"

    assert data["data_scope_label"] == "全部数据"
    assert data["metrics"]["month_inbound"] == 0
    assert data["metrics"]["month_requisition"] == 0
    assert data["metrics"]["contract_expiring"] == 0
    assert data["metrics"]["idle_rate"] == 0.0
    assert data["period"]["months"] == 12
    assert data["period"]["new_assets"] == 1
    assert data["dept_options"]
    assert data["dept_id"] is None


async def _dept_ids(client, headers) -> dict[str, int]:
    tree = await client.get("/api/v1/departments/tree", headers=headers)
    assert tree.status_code == 200, tree.text
    result: dict[str, int] = {}

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            result[node["code"]] = node["id"]
            walk(node.get("children") or [])

    walk(tree.json()["data"])
    return result


async def test_dashboard_dept_filter_period_and_contract(client):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    dept_ids = await _dept_ids(client, headers)
    it_id = dept_ids["IT"]
    fin_id = dept_ids["FIN"]

    category = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "驾驶舱筛选分类",
            "code": "DASH-FILTER",
            "category_type": "HARDWARE",
            "sort": 10,
            "status": 1,
        },
        headers=headers,
    )
    assert category.status_code == 200, category.text
    category_id = category.json()["data"]["id"]

    today = now_cst().date()
    for name, dept_id in (("IT 测试资产", it_id), ("财务测试资产", fin_id)):
        created = await client.post(
            "/api/v1/assets",
            json={
                "name": name,
                "category_id": category_id,
                "dept_id": dept_id,
                "purchase_date": today.isoformat(),
                "purchase_price": 100,
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text

    contract = await client.post(
        "/api/v1/contracts",
        json={
            "name": "IT 维保合同",
            "contract_type": "MAINTENANCE",
            "start_date": (today - timedelta(days=300)).isoformat(),
            "end_date": (today + timedelta(days=10)).isoformat(),
            "dept_id": it_id,
        },
        headers=headers,
    )
    assert contract.status_code == 200, contract.text

    all_summary = await client.get(
        "/api/v1/dashboard/summary?scope=org&months=3", headers=headers
    )
    assert all_summary.status_code == 200, all_summary.text
    all_data = all_summary.json()["data"]
    assert all_data["metrics"]["total_assets"] == 2
    assert all_data["metrics"]["contract_expiring"] == 1
    assert all_data["period"]["months"] == 3
    assert all_data["period"]["new_assets"] == 2
    assert len(all_data["purchase_trend"]) == 3

    filtered = await client.get(
        f"/api/v1/dashboard/summary?scope=org&dept_id={it_id}", headers=headers
    )
    assert filtered.status_code == 200, filtered.text
    filtered_data = filtered.json()["data"]
    assert filtered_data["dept_id"] == it_id
    assert filtered_data["metrics"]["total_assets"] == 1
    assert filtered_data["metrics"]["contract_expiring"] == 1
    assert [item["name"] for item in filtered_data["category_distribution"]] == [
        "驾驶舱筛选分类"
    ]

    empty = await client.get(
        f"/api/v1/dashboard/summary?scope=org&dept_id={dept_ids['HR']}", headers=headers
    )
    assert empty.status_code == 200, empty.text
    empty_data = empty.json()["data"]
    assert empty_data["metrics"]["total_assets"] == 0
    assert empty_data["metrics"]["contract_expiring"] == 0
    assert empty_data["category_distribution"] == []

    all_history = await client.get(
        "/api/v1/dashboard/summary?scope=org&months=0", headers=headers
    )
    assert all_history.status_code == 200, all_history.text
    all_history_data = all_history.json()["data"]
    assert all_history_data["period"]["months"] == 0
    assert all_history_data["period"]["new_assets"] == 2
    assert str(all_history_data["period"]["start_date"]) == "1970-01-01"
    assert all_history_data["purchase_trend"] == [
        {"month": f"{today.year:04d}", "count": 2}
    ]


async def test_dashboard_defaults_to_personal_scope(client):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    profile = await client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200, profile.text
    admin_id = profile.json()["data"]["user"]["id"]

    category = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "个人口径分类",
            "code": "DASH-MINE",
            "category_type": "HARDWARE",
            "sort": 10,
            "status": 1,
        },
        headers=headers,
    )
    assert category.status_code == 200, category.text
    category_id = category.json()["data"]["id"]

    today = now_cst().date()
    mine = await client.post(
        "/api/v1/assets",
        json={
            "name": "我的工作台资产",
            "category_id": category_id,
            "custodian_id": admin_id,
            "purchase_date": today.isoformat(),
            "purchase_price": 880.0,
            "warranty_end": (today + timedelta(days=12)).isoformat(),
        },
        headers=headers,
    )
    assert mine.status_code == 200, mine.text
    mine_id = mine.json()["data"]["id"]
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Asset)
            .where(Asset.id == mine_id)
            .values(status=AssetStatus.IN_USE)
        )
        await session.commit()

    other = await client.post(
        "/api/v1/assets",
        json={
            "name": "他人的工作台资产",
            "category_id": category_id,
            "purchase_date": today.isoformat(),
            "purchase_price": 500.0,
        },
        headers=headers,
    )
    assert other.status_code == 200, other.text

    personal = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert personal.status_code == 200, personal.text
    data = personal.json()["data"]
    assert data["scope"] == "personal"
    assert data["data_scope_label"] == "我的资产"
    assert data["metrics"]["total_assets"] == 1
    assert data["metrics"]["total_value"] == 880.0
    assert data["metrics"]["in_use"] == 1
    assert data["metrics"]["warranty_30d"] == 1
    assert data["period"]["new_assets"] == 1
    assert data["dept_options"]
    assert data["dept_id"] is None
    assert sum(item["count"] for item in data["dept_distribution"]) == 1
    assert [item["name"] for item in data["category_distribution"]] == ["个人口径分类"]
    assert [item["name"] for item in data["recent_assets"]] == ["我的工作台资产"]

    org = await client.get(
        "/api/v1/dashboard/summary?scope=org", headers=headers
    )
    assert org.status_code == 200, org.text
    org_data = org.json()["data"]
    assert org_data["scope"] == "org"
    assert org_data["data_scope_label"] == "全部数据"
    assert org_data["metrics"]["total_assets"] == 2
    assert org_data["metrics"]["total_value"] == 1380.0

