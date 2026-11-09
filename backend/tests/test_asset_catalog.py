from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import AuditLog
from tests.helpers import auth_headers, login


async def _tree(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    response = await client.get("/api/v1/asset-categories/tree", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node["children"]))
    return result


async def _find_category(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    nodes = _flatten(await _tree(client, headers))
    for node in nodes:
        if node["code"] == code:
            return node
    raise AssertionError(f"category {code} not found")


async def test_category_tree_matches_seed(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    tree = await _tree(client, headers)
    assert len(tree) == 6
    assert {node["code"] for node in tree} >= {"HW-COMPUTER", "ADM-ASSET"}
    admin_root = next(node for node in tree if node["code"] == "ADM-ASSET")
    assert admin_root["asset_domain"] == "ADMIN"
    desktop = await _find_category(client, headers, "HW-DESKTOP")
    assert desktop["level"] == 2
    assert desktop["category_type"] == "HARDWARE"
    assert desktop["asset_domain"] == "IT"
    assert desktop["model_count"] >= 1


async def test_category_crud_and_child_type_inheritance(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    root = await _find_category(client, headers, "HW-COMPUTER")

    created = await client.post(
        "/api/v1/asset-categories",
        json={
            "parent_id": root["id"],
            "name": "测试用一体机",
            "code": "TEST-AIO",
            "sort": 50,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    child = created.json()["data"]
    assert child["category_type"] == "HARDWARE"
    assert child["level"] == root["level"] + 1
    assert child["path"].startswith(root["path"])

    duplicate = await client.post(
        "/api/v1/asset-categories",
        json={"name": "重复编码", "code": "TEST-AIO", "parent_id": root["id"]},
        headers=headers,
    )
    assert duplicate.status_code == 409

    updated = await client.put(
        f"/api/v1/asset-categories/{child['id']}",
        json={
            "parent_id": root["id"],
            "name": "测试用一体机（改名）",
            "code": "TEST-AIO",
            "sort": 51,
            "status": 1,
            "version": child["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["version"] == child["version"] + 1

    stale = await client.put(
        f"/api/v1/asset-categories/{child['id']}",
        json={
            "parent_id": root["id"],
            "name": "过期更新",
            "code": "TEST-AIO",
            "sort": 52,
            "status": 1,
            "version": child["version"],
        },
        headers=headers,
    )
    assert stale.status_code == 409

    deleted = await client.delete(
        f"/api/v1/asset-categories/{child['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text

    remaining = _flatten(await _tree(client, headers))
    assert all(node["code"] != "TEST-AIO" for node in remaining)


async def test_category_asset_domain_inherits_and_cascades(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    created = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "测试行政根分类",
            "code": "TEST-ADM-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "ADMIN",
            "sort": 95,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    root = created.json()["data"]
    assert root["asset_domain"] == "ADMIN"

    child_created = await client.post(
        "/api/v1/asset-categories",
        json={
            "parent_id": root["id"],
            "name": "测试行政子分类",
            "code": "TEST-ADM-CHILD",
            "asset_domain": "IT",
            "sort": 10,
            "status": 1,
        },
        headers=headers,
    )
    assert child_created.status_code == 200, child_created.text
    child = child_created.json()["data"]
    assert child["asset_domain"] == "ADMIN"

    unconfirmed = await client.put(
        f"/api/v1/asset-categories/{root['id']}",
        json={
            "parent_id": None,
            "name": "测试行政根分类",
            "code": "TEST-ADM-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "IT",
            "sort": 95,
            "status": 1,
            "version": root["version"],
        },
        headers=headers,
    )
    assert unconfirmed.status_code == 400
    assert "显式确认" in unconfirmed.json()["message"]

    moved = await client.put(
        f"/api/v1/asset-categories/{root['id']}",
        json={
            "parent_id": None,
            "name": "测试行政根分类",
            "code": "TEST-ADM-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "IT",
            "sort": 95,
            "status": 1,
            "version": root["version"],
            "confirm_domain_change": True,
        },
        headers=headers,
    )
    assert moved.status_code == 200, moved.text

    refreshed = _flatten(await _tree(client, headers))
    child_after = next(node for node in refreshed if node["code"] == "TEST-ADM-CHILD")
    assert child_after["asset_domain"] == "IT"

    async with AsyncSessionLocal() as session:
        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "asset.category.domain_change",
                    AuditLog.resource_id == str(root["id"]),
                )
            )
        ).scalar_one()
    assert audit.before_data["asset_domain"] == "ADMIN"
    assert audit.after_data["asset_domain"] == "IT"
    assert child["id"] in audit.after_data["affected_category_ids"]

    await client.delete(f"/api/v1/asset-categories/{child['id']}", headers=headers)
    await client.delete(f"/api/v1/asset-categories/{root['id']}", headers=headers)


async def test_custom_asset_domain_lifecycle(client: AsyncClient):
    headers = auth_headers((await login(client))["access_token"])
    listed = await client.get("/api/v1/asset-domains", headers=headers)
    assert listed.status_code == 200, listed.text
    domains = listed.json()["data"]
    assert {item["code"] for item in domains} >= {"IT", "ADMIN"}
    builtin = next(item for item in domains if item["code"] == "IT")

    created = await client.post(
        "/api/v1/asset-domains",
        json={"code": "facility", "name": "设施资产", "sort": 30},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    domain = created.json()["data"]
    assert domain["code"] == "FACILITY"
    assert domain["is_builtin"] is False

    duplicate = await client.post(
        "/api/v1/asset-domains",
        json={"code": "FACILITY", "name": "重复域"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    category = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "设施根分类",
            "code": "FACILITY-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "FACILITY",
        },
        headers=headers,
    )
    assert category.status_code == 200, category.text

    referenced = await client.delete(
        f"/api/v1/asset-domains/{domain['id']}", headers=headers
    )
    assert referenced.status_code == 400

    updated = await client.put(
        f"/api/v1/asset-domains/{domain['id']}",
        json={"name": "设施与后勤资产", "sort": 31},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["name"] == "设施与后勤资产"

    deleted_category = await client.delete(
        f"/api/v1/asset-categories/{category.json()['data']['id']}", headers=headers
    )
    assert deleted_category.status_code == 200, deleted_category.text
    deleted = await client.delete(
        f"/api/v1/asset-domains/{domain['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text

    builtin_delete = await client.delete(
        f"/api/v1/asset-domains/{builtin['id']}", headers=headers
    )
    assert builtin_delete.status_code == 400
    invalid = await client.post(
        "/api/v1/asset-domains",
        json={"code": "bad code", "name": "非法域"},
        headers=headers,
    )
    assert invalid.status_code == 422


async def test_category_field_validation_and_crud(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _find_category(client, headers, "HW-LAPTOP")

    invalid_key = await client.post(
        f"/api/v1/asset-categories/{laptop['id']}/fields",
        json={"name": "非法标识", "field_key": "Bad Key", "field_type": "TEXT"},
        headers=headers,
    )
    assert invalid_key.status_code == 422

    missing_options = await client.post(
        f"/api/v1/asset-categories/{laptop['id']}/fields",
        json={"name": "下拉字段", "field_key": "test_select", "field_type": "SELECT"},
        headers=headers,
    )
    assert missing_options.status_code == 422

    created = await client.post(
        f"/api/v1/asset-categories/{laptop['id']}/fields",
        json={
            "name": "测试下拉",
            "field_key": "test_select",
            "field_type": "SELECT",
            "required": True,
            "options": ["甲", "乙", "乙"],
            "sort": 10,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    field = created.json()["data"]
    assert field["options"] == ["甲", "乙"]

    duplicate = await client.post(
        f"/api/v1/asset-categories/{laptop['id']}/fields",
        json={"name": "重复标识", "field_key": "test_select", "field_type": "TEXT"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    updated = await client.put(
        f"/api/v1/asset-categories/{laptop['id']}/fields/{field['id']}",
        json={
            "name": "测试下拉（改名）",
            "field_key": "test_select",
            "field_type": "SELECT",
            "required": False,
            "options": ["甲"],
            "sort": 11,
            "status": 1,
            "version": field["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["required"] is False

    deleted = await client.delete(
        f"/api/v1/asset-categories/{laptop['id']}/fields/{field['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text


async def test_model_crud_and_category_guard(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _find_category(client, headers, "HW-LAPTOP")
    computer = await _find_category(client, headers, "HW-COMPUTER")

    created = await client.post(
        "/api/v1/asset-models",
        json={
            "category_id": laptop["id"],
            "name": "测试型号",
            "code": "TEST-MODEL-001",
            "brand": "TestBrand",
            "spec": "i7/16G/512G",
            "depreciation_months": 36,
            "residual_rate": 0.05,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    model = created.json()["data"]

    duplicate = await client.post(
        "/api/v1/asset-models",
        json={
            "category_id": laptop["id"],
            "name": "重复型号",
            "code": "TEST-MODEL-001",
        },
        headers=headers,
    )
    assert duplicate.status_code == 409

    updated = await client.put(
        f"/api/v1/asset-models/{model['id']}",
        json={
            "category_id": laptop["id"],
            "name": "测试型号（改名）",
            "code": "TEST-MODEL-001",
            "brand": "TestBrand",
            "spec": "i7/32G/1T",
            "depreciation_months": 48,
            "residual_rate": 0.1,
            "status": 1,
            "version": model["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["version"] == model["version"] + 1

    child_scope = await client.get(
        "/api/v1/asset-models",
        params={"category_id": computer["id"], "include_child": True, "keyword": "TEST-MODEL-001"},
        headers=headers,
    )
    assert child_scope.status_code == 200, child_scope.text
    assert child_scope.json()["data"]["total"] == 1

    root_scope = await client.get(
        "/api/v1/asset-models",
        params={"category_id": computer["id"], "include_child": False},
        headers=headers,
    )
    assert root_scope.json()["data"]["total"] == 0

    in_use_category = await client.delete(
        f"/api/v1/asset-categories/{laptop['id']}", headers=headers
    )
    assert in_use_category.status_code == 400

    deleted = await client.delete(
        f"/api/v1/asset-models/{model['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
