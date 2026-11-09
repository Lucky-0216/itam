from httpx import AsyncClient
from sqlalchemy import insert, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.initial_data import seed_initial_data
from app.models import Asset, Dept, Role, User, user_roles
from tests.helpers import auth_headers, login

TEST_PASSWORD = "Test@12345"


def _flatten_menus(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten_menus(node["children"]))
    return result


def _flatten_categories(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten_categories(node["children"]))
    return result


async def _menu_map(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict]:
    menus = (await client.get("/api/v1/roles/menu-tree", headers=headers)).json()["data"]
    return {
        menu["permission_code"]: menu
        for menu in _flatten_menus(menus)
        if menu["permission_code"]
    }


async def _category(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    tree = (await client.get("/api/v1/asset-categories/tree", headers=headers)).json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == code:
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    category = walk(tree)
    assert category is not None, code
    return category


async def _it_dept(client: AsyncClient, headers: dict[str, str]) -> dict:
    tree = (await client.get("/api/v1/departments/tree", headers=headers)).json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == "IT":
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    dept = walk(tree)
    assert dept is not None
    return dept


async def _create_role(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    code: str,
    menus: dict[str, dict],
    permission_codes: list[str],
    data_scope: str = "ALL",
    domain_scope: str = "ALL",
    asset_domains: list[str] | None = None,
) -> dict:
    created = await client.post(
        "/api/v1/roles",
        json={
            "code": code,
            "name": code,
            "description": None,
            "data_scope": data_scope,
            "domain_scope": domain_scope,
            "asset_domains": asset_domains or [],
            "sort": 90,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    role = created.json()["data"]
    assigned = await client.put(
        f"/api/v1/roles/{role['id']}/menus",
        json={
            "menu_ids": [menus[item]["id"] for item in permission_codes],
            "version": role["version"],
        },
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    return assigned.json()["data"]


async def _create_user(
    username: str, role_id: int, *, dept_code: str = "IT"
) -> int:
    async with AsyncSessionLocal() as session:
        dept = (
            await session.execute(select(Dept).where(Dept.code == dept_code))
        ).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            real_name=username,
            dept_id=dept.id,
            status=1,
            must_change_password=False,
        )
        session.add(user)
        await session.flush()
        await session.execute(
            insert(user_roles).values(user_id=user.id, role_id=role_id)
        )
        await session.commit()
        return user.id


async def _login_user(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return auth_headers(response.json()["data"]["access_token"])


async def _create_asset(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    category_id: int,
    dept_id: int,
    custodian_id: int | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/assets",
        json={
            "name": name,
            "category_id": category_id,
            "dept_id": dept_id,
            "custodian_id": custodian_id,
            "custom_fields": {},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _create_inbound(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    supplier: str,
    category_id: int,
    dept_id: int,
    expected_status: int = 200,
) -> dict:
    response = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "supplier": supplier,
            "location": "A 座 101",
            "dept_id": dept_id,
            "items": [
                {
                    "category_id": category_id,
                    "name": supplier,
                    "quantity": 1,
                    "unit_price": 100,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == expected_status, response.text
    return response.json()["data"] if expected_status == 200 else {}


async def test_inbound_view_only_role_cannot_mutate(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    laptop = await _category(client, admin_headers, "HW-LAPTOP")
    dept = await _it_dept(client, admin_headers)

    inbound = await _create_inbound(
        client,
        admin_headers,
        supplier="只读角色测试供应商",
        category_id=laptop["id"],
        dept_id=dept["id"],
    )

    role = await _create_role(
        client,
        admin_headers,
        code="INBOUND_VIEWER",
        menus=menus,
        permission_codes=["asset:inbound:view"],
    )
    await _create_user("inbound_viewer", role["id"])
    viewer_headers = await _login_user(client, "inbound_viewer")

    listed = await client.get("/api/v1/inbounds", headers=viewer_headers)
    assert listed.status_code == 200, listed.text
    assert any(
        item["id"] == inbound["id"] for item in listed.json()["data"]["items"]
    )

    detail = await client.get(
        f"/api/v1/inbounds/{inbound['id']}", headers=viewer_headers
    )
    assert detail.status_code == 200, detail.text

    create_blocked = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "越权新增",
            "dept_id": dept["id"],
            "items": [{"category_id": laptop["id"], "name": "越权新增", "quantity": 1}],
        },
        headers=viewer_headers,
    )
    assert create_blocked.status_code == 403
    assert create_blocked.json()["code"] == 40300

    update_blocked = await client.put(
        f"/api/v1/inbounds/{inbound['id']}",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "越权修改",
            "dept_id": dept["id"],
            "items": [{"category_id": laptop["id"], "name": "越权修改", "quantity": 1}],
            "version": inbound["version"],
        },
        headers=viewer_headers,
    )
    assert update_blocked.status_code == 403

    cancel_blocked = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/cancel",
        json={"reason": "越权取消"},
        headers=viewer_headers,
    )
    assert cancel_blocked.status_code == 403

    confirm_blocked = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/confirm",
        json={"version": inbound["version"]},
        headers=viewer_headers,
    )
    assert confirm_blocked.status_code == 403

    options_blocked = await client.get(
        "/api/v1/inbounds/options/categories", headers=viewer_headers
    )
    assert options_blocked.status_code == 403


async def test_admin_domain_role_only_sees_admin_assets(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    it_category = await _category(client, admin_headers, "HW-LAPTOP")
    admin_category = await _category(client, admin_headers, "ADM-FURNITURE")
    dept = await _it_dept(client, admin_headers)

    it_asset = await _create_asset(
        client,
        admin_headers,
        name="域隔离-IT-资产",
        category_id=it_category["id"],
        dept_id=dept["id"],
    )
    admin_asset = await _create_asset(
        client,
        admin_headers,
        name="域隔离-行政-资产",
        category_id=admin_category["id"],
        dept_id=dept["id"],
    )
    it_inbound = await _create_inbound(
        client,
        admin_headers,
        supplier="域隔离-IT-入库",
        category_id=it_category["id"],
        dept_id=dept["id"],
    )
    admin_inbound = await _create_inbound(
        client,
        admin_headers,
        supplier="域隔离-行政-入库",
        category_id=admin_category["id"],
        dept_id=dept["id"],
    )
    it_models = await client.get(
        "/api/v1/asset-models",
        params={
            "category_id": it_category["id"],
            "include_child": False,
            "page_size": 1,
        },
        headers=admin_headers,
    )
    assert it_models.status_code == 200, it_models.text
    it_model = it_models.json()["data"]["items"][0]
    admin_model_created = await client.post(
        "/api/v1/asset-models",
        json={
            "category_id": admin_category["id"],
            "name": "域隔离-行政-型号",
            "code": "DOMAIN-ADMIN-MODEL",
        },
        headers=admin_headers,
    )
    assert admin_model_created.status_code == 200, admin_model_created.text
    admin_model = admin_model_created.json()["data"]

    role = await _create_role(
        client,
        admin_headers,
        code="ADMIN_DOMAIN_OPERATOR",
        menus=menus,
        permission_codes=[
            "asset:ledger:view",
            "asset:ledger:create",
            "asset:inbound:view",
            "asset:inbound:create",
            "asset:category:view",
            "asset:category:create",
            "asset:category:update",
            "asset:category:delete",
            "asset:model:create",
            "asset:model:update",
            "asset:model:delete",
        ],
    )
    scoped = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "ALL",
            "domain_scope": "CUSTOM",
            "asset_domains": ["ADMIN"],
            "permissions": [
                {"resource": "asset", "data_scope": "ALL"},
                {"resource": "inbound", "data_scope": "ALL"},
            ],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=admin_headers,
    )
    assert scoped.status_code == 200, scoped.text
    scoped_role = scoped.json()["data"]
    assert scoped_role["domain_scope"] == "CUSTOM"
    assert scoped_role["asset_domains"] == ["ADMIN"]
    assert {
        (item["resource"], item["data_scope"])
        for item in scoped_role["data_permissions"]
    } == {("asset", "ALL"), ("inbound", "ALL")}

    await _create_user("admin_domain_user", role["id"])
    user_headers = await _login_user(client, "admin_domain_user")

    domain_options = await client.get("/api/v1/asset-domains", headers=user_headers)
    assert domain_options.status_code == 200, domain_options.text
    assert [item["code"] for item in domain_options.json()["data"]] == ["ADMIN"]
    domain_create_blocked = await client.post(
        "/api/v1/asset-domains",
        json={"code": "UNAUTHORIZED", "name": "越权新增域"},
        headers=user_headers,
    )
    assert domain_create_blocked.status_code == 403
    domain_update_blocked = await client.put(
        f"/api/v1/asset-domains/{domain_options.json()['data'][0]['id']}",
        json={"name": "越权改名", "sort": 1},
        headers=user_headers,
    )
    assert domain_update_blocked.status_code == 403

    user_tree = await client.get(
        "/api/v1/asset-categories/tree", headers=user_headers
    )
    assert user_tree.status_code == 200, user_tree.text
    user_categories = _flatten_categories(user_tree.json()["data"])
    assert user_categories
    assert {item["asset_domain"] for item in user_categories} == {"ADMIN"}
    assert all(item["code"] != "HW-LAPTOP" for item in user_categories)
    furniture = next(item for item in user_categories if item["code"] == "ADM-FURNITURE")
    assert furniture["asset_count"] == 1

    user_models = await client.get(
        "/api/v1/asset-models", params={"page_size": 200}, headers=user_headers
    )
    assert user_models.status_code == 200, user_models.text
    admin_category_ids = {item["id"] for item in user_categories}
    model_items = user_models.json()["data"]["items"]
    assert [item["id"] for item in model_items] == [admin_model["id"]]
    assert all(item["category_id"] in admin_category_ids for item in model_items)

    forbidden_models = await client.get(
        "/api/v1/asset-models",
        params={"category_id": it_category["id"]},
        headers=user_headers,
    )
    assert forbidden_models.status_code == 403

    forbidden_category_create = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "越权IT根分类",
            "code": "DOMAIN-IT-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "IT",
        },
        headers=user_headers,
    )
    assert forbidden_category_create.status_code == 403
    forbidden_child_create = await client.post(
        "/api/v1/asset-categories",
        json={"parent_id": it_category["id"], "name": "越权IT子分类", "code": "DOMAIN-IT-CHILD"},
        headers=user_headers,
    )
    assert forbidden_child_create.status_code == 403
    forbidden_category_update = await client.put(
        f"/api/v1/asset-categories/{it_category['id']}",
        json={
            "parent_id": it_category["parent_id"],
            "name": "越权修改IT分类",
            "code": it_category["code"],
            "version": it_category["version"],
        },
        headers=user_headers,
    )
    assert forbidden_category_update.status_code == 403
    forbidden_category_delete = await client.delete(
        f"/api/v1/asset-categories/{it_category['id']}", headers=user_headers
    )
    assert forbidden_category_delete.status_code == 403
    forbidden_field = await client.post(
        f"/api/v1/asset-categories/{it_category['id']}/fields",
        json={"name": "越权字段", "field_key": "forbidden_field", "field_type": "TEXT"},
        headers=user_headers,
    )
    assert forbidden_field.status_code == 403

    forbidden_model_create = await client.post(
        "/api/v1/asset-models",
        json={"category_id": it_category["id"], "name": "越权IT型号", "code": "DOMAIN-IT-MODEL"},
        headers=user_headers,
    )
    assert forbidden_model_create.status_code == 403
    forbidden_model_update = await client.put(
        f"/api/v1/asset-models/{it_model['id']}",
        json={
            "category_id": it_model["category_id"],
            "name": it_model["name"],
            "code": it_model["code"],
            "version": it_model["version"],
        },
        headers=user_headers,
    )
    assert forbidden_model_update.status_code == 403
    forbidden_model_delete = await client.delete(
        f"/api/v1/asset-models/{it_model['id']}", headers=user_headers
    )
    assert forbidden_model_delete.status_code == 403

    allowed_child = await client.post(
        "/api/v1/asset-categories",
        json={
            "parent_id": admin_category["id"],
            "name": "域隔离-行政-子分类",
            "code": "DOMAIN-ADMIN-CHILD",
        },
        headers=user_headers,
    )
    assert allowed_child.status_code == 200, allowed_child.text
    assert allowed_child.json()["data"]["asset_domain"] == "ADMIN"
    allowed_model = await client.post(
        "/api/v1/asset-models",
        json={
            "category_id": admin_category["id"],
            "name": "域隔离-行政-新型号",
            "code": "DOMAIN-ADMIN-MODEL-NEW",
        },
        headers=user_headers,
    )
    assert allowed_model.status_code == 200, allowed_model.text

    listed = await client.get(
        "/api/v1/assets", params={"keyword": "域隔离"}, headers=user_headers
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["data"]["items"]
    assert [item["id"] for item in items] == [admin_asset["id"]]

    forbidden_detail = await client.get(
        f"/api/v1/assets/{it_asset['id']}", headers=user_headers
    )
    assert forbidden_detail.status_code == 404

    allowed_detail = await client.get(
        f"/api/v1/assets/{admin_asset['id']}", headers=user_headers
    )
    assert allowed_detail.status_code == 200

    inbounds = await client.get(
        "/api/v1/inbounds", params={"keyword": "域隔离"}, headers=user_headers
    )
    assert inbounds.status_code == 200, inbounds.text
    assert [item["id"] for item in inbounds.json()["data"]["items"]] == [
        admin_inbound["id"]
    ]

    denied_inbound = await client.get(
        f"/api/v1/inbounds/{it_inbound['id']}", headers=user_headers
    )
    assert denied_inbound.status_code == 403

    allowed_inbound = await client.get(
        f"/api/v1/inbounds/{admin_inbound['id']}", headers=user_headers
    )
    assert allowed_inbound.status_code == 200

    categories = await client.get(
        "/api/v1/inbounds/options/categories", headers=user_headers
    )
    assert categories.status_code == 200, categories.text

    def collect(nodes):
        result = []
        for node in nodes:
            result.append(node)
            result.extend(collect(node["children"]))
        return result

    domain_map = {
        item["id"]: item["asset_domain"]
        for item in collect(
            (await client.get("/api/v1/asset-categories/tree", headers=admin_headers)).json()["data"]
        )
    }
    assert categories.json()["data"]
    assert {
        domain_map[item["id"]] for item in categories.json()["data"]
    } == {"ADMIN"}

    create_blocked = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "域隔离-越权IT入库",
            "dept_id": dept["id"],
            "items": [
                {"category_id": it_category["id"], "name": "越权IT", "quantity": 1}
            ],
        },
        headers=user_headers,
    )
    assert create_blocked.status_code == 403

    admin_inbound_allowed = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "域隔离-行政入库-新建",
            "dept_id": dept["id"],
            "items": [
                {"category_id": admin_category["id"], "name": "行政入库", "quantity": 1}
            ],
        },
        headers=user_headers,
    )
    assert admin_inbound_allowed.status_code == 200, admin_inbound_allowed.text

    asset_create_blocked = await client.post(
        "/api/v1/assets",
        json={
            "name": "域隔离-越权IT资产",
            "category_id": it_category["id"],
            "dept_id": dept["id"],
            "custom_fields": {},
        },
        headers=user_headers,
    )
    assert asset_create_blocked.status_code == 400

    asset_create_allowed = await client.post(
        "/api/v1/assets",
        json={
            "name": "域隔离-行政资产-新建",
            "category_id": admin_category["id"],
            "dept_id": dept["id"],
            "custom_fields": {},
        },
        headers=user_headers,
    )
    assert asset_create_allowed.status_code == 200, asset_create_allowed.text


async def test_self_scope_does_not_share_role_member_data(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    laptop = await _category(client, admin_headers, "HW-LAPTOP")
    dept = await _it_dept(client, admin_headers)

    meta = (
        await client.get("/api/v1/roles/options/meta", headers=admin_headers)
    ).json()["data"]
    assert {item["value"] for item in meta["data_resources"]} >= {
        "asset",
        "inbound",
        "stock",
    }
    assert {item["value"] for item in meta["data_scopes"]} == {
        "ALL",
        "DEPT_AND_CHILD",
        "DEPT",
        "CUSTOM",
        "SELF",
    }

    global_role_rejected = await client.post(
        "/api/v1/roles",
        json={
            "code": "ROLE_SCOPE_INVALID",
            "name": "ROLE_SCOPE_INVALID",
            "data_scope": "ROLE",
            "sort": 90,
            "status": 1,
        },
        headers=admin_headers,
    )
    assert global_role_rejected.status_code == 422

    role = await _create_role(
        client,
        admin_headers,
        code="CREATOR_SCOPE_OPERATOR",
        menus=menus,
        permission_codes=[
            "asset:ledger:view",
            "asset:ledger:create",
            "asset:ledger:update",
            "asset:inbound:view",
            "asset:inbound:create",
            "asset:inbound:update",
            "asset:inbound:confirm",
            "asset:ledger:delete",
            "asset:stock:view",
        ],
        data_scope="SELF",
    )
    scoped = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [
                {"resource": "asset", "data_scope": "SELF"},
                {"resource": "inbound", "data_scope": "SELF"},
                {"resource": "stock", "data_scope": "SELF"},
            ],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=admin_headers,
    )
    assert scoped.status_code == 200, scoped.text
    assert {
        (item["resource"], item["data_scope"])
        for item in scoped.json()["data"]["data_permissions"]
    } == {
        ("asset", "SELF"),
        ("inbound", "SELF"),
        ("stock", "SELF"),
    }

    unsupported = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [
                {"resource": "asset", "data_scope": "SELF"},
                {"resource": "contract", "data_scope": "ROLE"},
            ],
            "dept_ids": [],
            "version": scoped.json()["data"]["version"],
        },
        headers=admin_headers,
    )
    assert unsupported.status_code == 422

    user_a = await _create_user("creator_a", role["id"])
    user_b = await _create_user("creator_b", role["id"])
    await _create_user("creator_c", role["id"])
    headers_a = await _login_user(client, "creator_a")
    headers_b = await _login_user(client, "creator_b")

    asset_a = await _create_asset(
        client,
        headers_a,
        name="创建人范围-甲方资产",
        category_id=laptop["id"],
        dept_id=dept["id"],
        custodian_id=user_a,
    )
    asset_b = await _create_asset(
        client,
        headers_b,
        name="创建人范围-乙方资产",
        category_id=laptop["id"],
        dept_id=dept["id"],
        custodian_id=user_b,
    )

    listed_a = await client.get(
        "/api/v1/assets", params={"keyword": "创建人范围"}, headers=headers_a
    )
    assert listed_a.status_code == 200, listed_a.text
    assert {item["id"] for item in listed_a.json()["data"]["items"]} == {
        asset_a["id"]
    }

    listed_b = await client.get(
        "/api/v1/assets", params={"keyword": "创建人范围"}, headers=headers_b
    )
    assert {item["id"] for item in listed_b.json()["data"]["items"]} == {
        asset_b["id"]
    }

    updated = await client.put(
        f"/api/v1/assets/{asset_a['id']}",
        json={
            "name": "创建人范围-甲方资产-乙方修改",
            "category_id": laptop["id"],
            "dept_id": dept["id"],
            "custom_fields": {},
            "version": asset_a["version"],
        },
        headers=headers_b,
    )
    assert updated.status_code == 404, updated.text

    inbound = await _create_inbound(
        client,
        headers_a,
        supplier="创建人范围-入库资产",
        category_id=laptop["id"],
        dept_id=dept["id"],
    )
    inbounds_b = await client.get(
        "/api/v1/inbounds", params={"keyword": "创建人范围-入库资产"}, headers=headers_b
    )
    assert inbounds_b.status_code == 200, inbounds_b.text
    assert inbounds_b.json()["data"]["items"] == []

    inbound_updated = await client.put(
        f"/api/v1/inbounds/{inbound['id']}",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "创建人范围-入库资产-本人修改",
            "dept_id": dept["id"],
            "items": [
                {"category_id": laptop["id"], "name": "创建人范围-入库资产", "quantity": 1}
            ],
            "version": inbound["version"],
        },
        headers=headers_a,
    )
    assert inbound_updated.status_code == 200, inbound_updated.text
    confirmed = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/confirm",
        json={"version": inbound_updated.json()["data"]["version"]},
        headers=headers_a,
    )
    assert confirmed.status_code == 200, confirmed.text

    confirmed_assets = await client.get(
        "/api/v1/assets", params={"keyword": "创建人范围-入库资产"}, headers=headers_a
    )
    assert confirmed_assets.status_code == 200, confirmed_assets.text
    confirmed_items = confirmed_assets.json()["data"]["items"]
    assert [item["name"] for item in confirmed_items].count("创建人范围-入库资产") == 1
    confirmed_asset_id = next(
        item["id"] for item in confirmed_items if item["name"] == "创建人范围-入库资产"
    )

    stock_items_a = await client.get("/api/v1/stock/items", headers=headers_a)
    assert stock_items_a.status_code == 200, stock_items_a.text
    assert confirmed_asset_id in {
        item["id"] for item in stock_items_a.json()["data"]["items"]
    }

    outsider_role = await _create_role(
        client,
        admin_headers,
        code="CREATOR_SCOPE_OUTSIDER",
        menus=menus,
        permission_codes=[
            "asset:ledger:view",
            "asset:inbound:view",
            "asset:stock:view",
        ],
        data_scope="SELF",
    )
    await _create_user("creator_outsider", outsider_role["id"], dept_code="FIN")
    outsider_headers = await _login_user(client, "creator_outsider")

    outsider_assets = await client.get(
        "/api/v1/assets", params={"keyword": "创建人范围"}, headers=outsider_headers
    )
    assert outsider_assets.status_code == 200, outsider_assets.text
    assert outsider_assets.json()["data"]["items"] == []

    outsider_detail = await client.get(
        f"/api/v1/assets/{asset_b['id']}", headers=outsider_headers
    )
    assert outsider_detail.status_code == 404

    outsider_inbounds = await client.get(
        "/api/v1/inbounds", params={"keyword": "创建人范围-入库资产"}, headers=outsider_headers
    )
    assert outsider_inbounds.status_code == 200, outsider_inbounds.text
    assert outsider_inbounds.json()["data"]["items"] == []

    outsider_inbound_detail = await client.get(
        f"/api/v1/inbounds/{inbound['id']}", headers=outsider_headers
    )
    assert outsider_inbound_detail.status_code == 403

    outsider_stock = await client.get("/api/v1/stock/items", headers=outsider_headers)
    assert outsider_stock.status_code == 200, outsider_stock.text
    assert outsider_stock.json()["data"]["items"] == []

    await _create_user("creator_d", role["id"])
    headers_d = await _login_user(client, "creator_d")
    listed_d = await client.get(
        "/api/v1/assets", params={"keyword": "创建人范围"}, headers=headers_d
    )
    assert listed_d.status_code == 200, listed_d.text
    assert listed_d.json()["data"]["items"] == []

    stock_items_d = await client.get("/api/v1/stock/items", headers=headers_d)
    assert stock_items_d.status_code == 200, stock_items_d.text
    assert stock_items_d.json()["data"]["items"] == []


async def test_empty_domain_grants_no_catalog_access(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    role = await _create_role(
        client,
        admin_headers,
        code="EMPTY_DOMAIN_OPERATOR",
        menus=menus,
        permission_codes=[
            "asset:category:view",
            "asset:category:create",
            "asset:model:create",
        ],
        domain_scope="CUSTOM",
        asset_domains=[],
    )
    await _create_user("empty_domain_user", role["id"])
    headers = await _login_user(client, "empty_domain_user")

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["data"]["domain_scope"] == "CUSTOM"
    assert me.json()["data"]["asset_domains"] == []

    tree = await client.get("/api/v1/asset-categories/tree", headers=headers)
    assert tree.status_code == 200, tree.text
    assert tree.json()["data"] == []
    models = await client.get("/api/v1/asset-models", headers=headers)
    assert models.status_code == 200, models.text
    assert models.json()["data"]["items"] == []
    assert models.json()["data"]["total"] == 0

    created = await client.post(
        "/api/v1/asset-categories",
        json={
            "name": "空域越权分类",
            "code": "EMPTY-DOMAIN-ROOT",
            "category_type": "HARDWARE",
            "asset_domain": "ADMIN",
        },
        headers=headers,
    )
    assert created.status_code == 403


async def test_confirmation_page_view_codes_are_read_only(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    laptop = await _category(client, admin_headers, "HW-LAPTOP")
    dept = await _it_dept(client, admin_headers)

    inbound = await _create_inbound(
        client,
        admin_headers,
        supplier="页面码-出库资产",
        category_id=laptop["id"],
        dept_id=dept["id"],
    )
    confirmed = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/confirm",
        json={"version": inbound["version"]},
        headers=admin_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assets = await client.get(
        "/api/v1/assets", params={"keyword": "页面码-出库资产"}, headers=admin_headers
    )
    assert assets.status_code == 200, assets.text
    asset = assets.json()["data"]["items"][0]
    asset_id = asset["id"]

    created = await client.post(
        "/api/v1/asset-requests",
        json={"request_type": "REQUISITION", "category_id": laptop["id"]},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    order = created.json()["data"]
    for _ in range(3):
        if order["status"] != "PENDING_APPROVAL":
            break
        approved = await client.post(
            f"/api/v1/asset-requests/{order['id']}/approve",
            json={"comment": "同意"},
            headers=admin_headers,
        )
        assert approved.status_code == 200, approved.text
        order = approved.json()["data"]
    assert order["status"] == "PENDING_OUTBOUND"

    role = await _create_role(
        client,
        admin_headers,
        code="CONFIRMATION_PAGE_VIEWER",
        menus=menus,
        permission_codes=["asset:outbound:view", "asset:return:confirm:view"],
    )
    await _create_user("confirmation_viewer", role["id"])
    viewer_headers = await _login_user(client, "confirmation_viewer")

    listed = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_OUTBOUND", "pending_mine": False},
        headers=viewer_headers,
    )
    assert listed.status_code == 200, listed.text
    item = next(
        entry for entry in listed.json()["data"]["items"] if entry["id"] == order["id"]
    )
    assert item["can_outbound"] is False
    detail = await client.get(
        f"/api/v1/asset-requests/{order['id']}", headers=viewer_headers
    )
    assert detail.status_code == 200, detail.text
    summary = await client.get(
        "/api/v1/asset-requests/review-summary", headers=viewer_headers
    )
    assert summary.status_code == 200, summary.text
    selectable = await client.get(
        f"/api/v1/asset-requests/{order['id']}/outbound-assets",
        headers=viewer_headers,
    )
    assert selectable.status_code == 200, selectable.text
    outbound_blocked = await client.post(
        f"/api/v1/asset-requests/{order['id']}/outbound",
        json={"version": asset["version"], "asset_id": asset_id},
        headers=viewer_headers,
    )
    assert outbound_blocked.status_code == 403

    outbound = await client.post(
        f"/api/v1/asset-requests/{order['id']}/outbound",
        json={"version": asset["version"], "asset_id": asset_id},
        headers=admin_headers,
    )
    assert outbound.status_code == 200, outbound.text
    returned = await client.post(
        "/api/v1/asset-returns",
        json={"asset_id": asset_id, "reason": "页面码归还测试"},
        headers=admin_headers,
    )
    assert returned.status_code == 200, returned.text
    return_order = returned.json()["data"]
    assert return_order["status"] == "PENDING_RETURN"

    returns = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_RETURN", "pending_mine": False},
        headers=viewer_headers,
    )
    assert returns.status_code == 200, returns.text
    return_item = next(
        entry
        for entry in returns.json()["data"]["items"]
        if entry["id"] == return_order["id"]
    )
    assert return_item["can_confirm_return"] is False
    return_detail = await client.get(
        f"/api/v1/asset-requests/{return_order['id']}", headers=viewer_headers
    )
    assert return_detail.status_code == 200, return_detail.text
    return_blocked = await client.post(
        f"/api/v1/asset-requests/{return_order['id']}/return-confirm",
        json={"version": return_order["asset_version"]},
        headers=viewer_headers,
    )
    assert return_blocked.status_code == 403

    admin_role = await _create_role(
        client,
        admin_headers,
        code="ADMIN_CONFIRMATION_VIEWER",
        menus=menus,
        permission_codes=["asset:outbound:view", "asset:return:confirm:view"],
        domain_scope="CUSTOM",
        asset_domains=["ADMIN"],
    )
    await _create_user("admin_confirmation_viewer", admin_role["id"])
    admin_viewer_headers = await _login_user(client, "admin_confirmation_viewer")
    cross_domain_list = await client.get(
        "/api/v1/asset-requests/review",
        params={"status": "PENDING_RETURN", "pending_mine": False},
        headers=admin_viewer_headers,
    )
    assert cross_domain_list.status_code == 200, cross_domain_list.text
    assert cross_domain_list.json()["data"]["items"] == []
    cross_domain_detail = await client.get(
        f"/api/v1/asset-requests/{return_order['id']}",
        headers=admin_viewer_headers,
    )
    assert cross_domain_detail.status_code == 403


async def test_seed_does_not_restore_revoked_builtin_menu(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    listed = await client.get(
        "/api/v1/roles", params={"keyword": "ASSET_ADMIN"}, headers=admin_headers
    )
    assert listed.status_code == 200, listed.text
    role = next(
        item for item in listed.json()["data"]["items"] if item["code"] == "ASSET_ADMIN"
    )
    detail = await client.get(f"/api/v1/roles/{role['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    role = detail.json()["data"]
    target_menu_id = menus["asset:outbound:view"]["id"]
    assert target_menu_id in role["menu_ids"]

    revoked = await client.put(
        f"/api/v1/roles/{role['id']}/menus",
        json={
            "menu_ids": [item for item in role["menu_ids"] if item != target_menu_id],
            "version": role["version"],
        },
        headers=admin_headers,
    )
    assert revoked.status_code == 200, revoked.text
    await _create_user("seed_revoked_user", role["id"])
    headers = await _login_user(client, "seed_revoked_user")
    before = await client.get("/api/v1/auth/me", headers=headers)
    assert before.status_code == 200, before.text
    assert "asset:outbound:view" not in before.json()["data"]["permissions"]

    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    after = await client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 200, after.text
    assert "asset:outbound:view" not in after.json()["data"]["permissions"]
    refreshed = await client.get(f"/api/v1/roles/{role['id']}", headers=admin_headers)
    assert refreshed.status_code == 200, refreshed.text
    assert target_menu_id not in refreshed.json()["data"]["menu_ids"]


FIELD_MASKED_FIELDS = [
    "name",
    "serial_no",
    "mac_address",
    "purchase_date",
    "supplier",
    "purchase_price",
    "warranty_end",
    "location",
    "custodian_id",
    "remark",
]


async def test_masked_fields_hidden_across_search_stock_and_reports(
    client: AsyncClient,
):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    laptop = await _category(client, admin_headers, "HW-LAPTOP")
    dept = await _it_dept(client, admin_headers)

    created = await client.post(
        "/api/v1/assets",
        json={
            "name": "字段遮蔽-资产名称",
            "category_id": laptop["id"],
            "dept_id": dept["id"],
            "serial_no": "SN-MASK-SECRET",
            "mac_address": "AA-BB-CC-DD-EE-FF",
            "purchase_date": "2025-01-15",
            "supplier": "字段遮蔽-供应商",
            "purchase_price": 8888,
            "warranty_end": "2028-01-15",
            "location": "字段遮蔽-位置",
            "remark": "字段遮蔽-备注",
            "custom_fields": {},
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    asset = created.json()["data"]

    async with AsyncSessionLocal() as session:
        row = await session.get(Asset, asset["id"])
        row.status = AssetStatus.IN_STOCK
        await session.commit()

    role = await _create_role(
        client,
        admin_headers,
        code="FIELD_MASK_VIEWER",
        menus=menus,
        permission_codes=[
            "asset:ledger:view",
            "asset:stock:view",
            "asset:report:view",
            "dashboard:view",
        ],
    )
    detail = await client.get(f"/api/v1/roles/{role['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    masked = await client.put(
        f"/api/v1/roles/{role['id']}/field-permissions",
        json={
            "permissions": [
                {
                    "resource": "asset",
                    "field": field_name,
                    "can_view": False,
                    "can_edit": False,
                }
                for field_name in FIELD_MASKED_FIELDS
            ],
            "version": detail.json()["data"]["version"],
        },
        headers=admin_headers,
    )
    assert masked.status_code == 200, masked.text

    await _create_user("field_mask_viewer", role["id"])
    headers = await _login_user(client, "field_mask_viewer")

    detail_resp = await client.get(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert detail_resp.status_code == 200, detail_resp.text
    asset_body = detail_resp.json()["data"]
    assert asset_body["name"] == "已隐藏"
    for field_name in (
        "serial_no",
        "mac_address",
        "purchase_date",
        "supplier",
        "purchase_price",
        "warranty_end",
        "location",
        "custodian_id",
        "custodian_name",
        "remark",
    ):
        assert asset_body[field_name] is None, field_name
    assert set(asset_body["masked_fields"]) == set(FIELD_MASKED_FIELDS)

    # 资产编号可以检索，但标题中的名称被遮蔽。
    search_by_no = await client.get(
        "/api/v1/search", params={"keyword": asset["asset_no"]}, headers=headers
    )
    assert search_by_no.status_code == 200, search_by_no.text
    asset_hits = [
        item
        for item in search_by_no.json()["data"]["items"]
        if item["type"] == "asset"
    ]
    assert len(asset_hits) == 1
    assert asset_hits[0]["title"] == f"已隐藏 · {asset['asset_no']}"

    # 被遮蔽的序列号不能用于检索。
    search_by_serial = await client.get(
        "/api/v1/search", params={"keyword": "SN-MASK-SECRET"}, headers=headers
    )
    assert search_by_serial.status_code == 200, search_by_serial.text
    assert [
        item
        for item in search_by_serial.json()["data"]["items"]
        if item["type"] == "asset"
    ] == []

    stock = await client.get(
        "/api/v1/stock/items", params={"page_size": 200}, headers=headers
    )
    assert stock.status_code == 200, stock.text
    stock_item = next(
        item for item in stock.json()["data"]["items"] if item["id"] == asset["id"]
    )
    assert stock_item["name"] == "已隐藏"
    for field_name in (
        "serial_no",
        "location",
        "purchase_price",
        "warranty_end",
        "remark",
    ):
        assert stock_item[field_name] is None, field_name

    stock_by_serial = await client.get(
        "/api/v1/stock/items",
        params={"keyword": "SN-MASK-SECRET"},
        headers=headers,
    )
    assert stock_by_serial.status_code == 200, stock_by_serial.text
    assert stock_by_serial.json()["data"]["total"] == 0

    overview = await client.get("/api/v1/stock/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    overview_body = overview.json()["data"]
    assert overview_body["in_stock_count"] == 1
    assert overview_body["in_stock_value"] == 0.0
    assert overview_body["locations"] == [
        {
            "location": None,
            "location_label": "位置已隐藏",
            "asset_count": 1,
            "total_value": 0.0,
        }
    ]

    report = await client.get(
        "/api/v1/reports/assets",
        params={"keyword": asset["asset_no"]},
        headers=headers,
    )
    assert report.status_code == 200, report.text
    report_row = report.json()["data"]["items"][0]
    assert report_row["name"] == "已隐藏"
    for field_name in (
        "serial_no",
        "purchase_date",
        "supplier",
        "purchase_price",
        "warranty_end",
        "location",
        "custodian_name",
    ):
        assert report_row[field_name] is None, field_name

    report_by_serial = await client.get(
        "/api/v1/reports/assets",
        params={"keyword": "SN-MASK-SECRET"},
        headers=headers,
    )
    assert report_by_serial.status_code == 200, report_by_serial.text
    assert report_by_serial.json()["data"]["total"] == 0

    ledger_by_serial = await client.get(
        "/api/v1/assets",
        params={"keyword": "SN-MASK-SECRET"},
        headers=headers,
    )
    assert ledger_by_serial.status_code == 200, ledger_by_serial.text
    assert ledger_by_serial.json()["data"]["total"] == 0

    # 报表聚合金额同样不能暴露被遮蔽的采购价。
    report_overview = await client.get(
        "/api/v1/reports/assets/overview", headers=headers
    )
    assert report_overview.status_code == 200, report_overview.text
    overview_data = report_overview.json()["data"]
    metrics = overview_data["metrics"]
    assert metrics["total_count"] >= 1
    assert metrics["total_value"] == 0.0
    assert metrics["avg_value"] == 0.0
    assert metrics["idle_value"] == 0.0
    assert all(item["value"] == 0.0 for item in overview_data["status_distribution"])
    assert all(item["value"] == 0.0 for item in overview_data["dept_distribution"])
    assert all(
        item["value"] == 0.0 for item in overview_data["category_distribution"]
    )
    assert all(item["value"] == 0.0 for item in overview_data["purchase_trend"])

    # 驾驶舱总金额与最近资产名称同样受字段权限约束。
    dashboard = await client.get("/api/v1/dashboard/summary", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    dashboard_data = dashboard.json()["data"]
    assert dashboard_data["metrics"]["total_assets"] >= 1
    assert dashboard_data["metrics"]["total_value"] == 0.0
    recent = next(
        item for item in dashboard_data["recent_assets"] if item["id"] == asset["id"]
    )
    assert recent["name"] == "已隐藏"


async def test_builtin_roles_are_superuser_only(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)

    role = await _create_role(
        client,
        admin_headers,
        code="ROLE_MANAGER",
        menus=menus,
        permission_codes=[
            "system:role:view",
            "system:role:update",
            "system:role:delete",
            "system:role:assign-menu",
            "system:role:assign-data",
            "system:role:assign-field",
            "system:role:assign-user",
        ],
    )
    await _create_user("role_manager", role["id"])
    headers = await _login_user(client, "role_manager")

    listed = await client.get(
        "/api/v1/roles", params={"keyword": "ASSET_ADMIN"}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    builtin = next(
        item for item in listed.json()["data"]["items"] if item["code"] == "ASSET_ADMIN"
    )
    assert builtin["is_system"] is True
    builtin_id = builtin["id"]

    detail = await client.get(f"/api/v1/roles/{builtin_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    builtin_detail = detail.json()["data"]
    version = builtin_detail["version"]

    blocked_update = await client.put(
        f"/api/v1/roles/{builtin_id}",
        json={"name": "越权改名", "sort": 10, "status": 1, "version": version},
        headers=headers,
    )
    assert blocked_update.status_code == 403

    blocked_menus = await client.put(
        f"/api/v1/roles/{builtin_id}/menus",
        json={"menu_ids": builtin_detail["menu_ids"], "version": version},
        headers=headers,
    )
    assert blocked_menus.status_code == 403

    blocked_data = await client.put(
        f"/api/v1/roles/{builtin_id}/data-permissions",
        json={
            "data_scope": "ALL",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [],
            "dept_ids": [],
            "version": version,
        },
        headers=headers,
    )
    assert blocked_data.status_code == 403

    blocked_fields = await client.put(
        f"/api/v1/roles/{builtin_id}/field-permissions",
        json={"permissions": [], "version": version},
        headers=headers,
    )
    assert blocked_fields.status_code == 403

    blocked_users = await client.put(
        f"/api/v1/roles/{builtin_id}/users",
        json={"user_ids": [item["id"] for item in builtin_detail["users"]], "version": version},
        headers=headers,
    )
    assert blocked_users.status_code == 403

    blocked_delete = await client.delete(
        f"/api/v1/roles/{builtin_id}", headers=headers
    )
    assert blocked_delete.status_code in (400, 403)

    admin_update = await client.put(
        f"/api/v1/roles/{builtin_id}",
        json={
            "name": builtin_detail["name"],
            "description": builtin_detail["description"],
            "sort": builtin_detail["sort"],
            "status": builtin_detail["status"],
            "version": version,
        },
        headers=admin_headers,
    )
    assert admin_update.status_code == 200, admin_update.text


async def test_data_permissions_saved_atomically(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    menus = await _menu_map(client, admin_headers)
    dept = await _it_dept(client, admin_headers)

    role = await _create_role(
        client,
        admin_headers,
        code="ATOMIC_SCOPE_OPERATOR",
        menus=menus,
        permission_codes=[
            "asset:ledger:view",
            "asset:inbound:view",
            "asset:stock:view",
            "asset:report:view",
        ],
    )

    saved = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "CUSTOM",
            "domain_scope": "CUSTOM",
            "asset_domains": ["ADMIN"],
            "permissions": [
                {"resource": "asset", "data_scope": "CUSTOM", "dept_ids": [dept["id"]]},
                {"resource": "report", "data_scope": "DEPT"},
            ],
            "dept_ids": [dept["id"]],
            "version": role["version"],
        },
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text
    saved_role = saved.json()["data"]
    assert saved_role["data_scope"] == "CUSTOM"
    assert saved_role["dept_ids"] == [dept["id"]]
    assert saved_role["domain_scope"] == "CUSTOM"
    assert saved_role["asset_domains"] == ["ADMIN"]
    assert {
        (item["resource"], item["data_scope"], tuple(item["dept_ids"]))
        for item in saved_role["data_permissions"]
    } == {
        ("asset", "CUSTOM", (dept["id"],)),
        ("report", "DEPT", ()),
    }

    await _create_user("atomic_scope_user", role["id"])
    headers = await _login_user(client, "atomic_scope_user")
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    me_body = me.json()["data"]
    assert me_body["data_scope"] == "CUSTOM"
    assert me_body["custom_dept_ids"] == [dept["id"]]
    assert me_body["domain_scope"] == "CUSTOM"
    assert me_body["asset_domains"] == ["ADMIN"]
    assert me_body["resource_scopes"]["asset"] == "CUSTOM"
    assert me_body["resource_scopes"]["report"] == "DEPT"

    # 一次保存同时替换全局范围、资产域与资源级范围。
    replaced = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "DEPT",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [],
            "dept_ids": [],
            "version": saved_role["version"],
        },
        headers=admin_headers,
    )
    assert replaced.status_code == 200, replaced.text
    replaced_role = replaced.json()["data"]
    assert replaced_role["data_scope"] == "DEPT"
    assert replaced_role["dept_ids"] == []
    assert replaced_role["domain_scope"] == "ALL"
    assert replaced_role["asset_domains"] == []
    assert replaced_role["data_permissions"] == []

    refreshed = await client.get("/api/v1/auth/me", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    refreshed_body = refreshed.json()["data"]
    assert refreshed_body["data_scope"] == "DEPT"
    assert refreshed_body["domain_scope"] == "ALL"
    assert refreshed_body["resource_scopes"]["asset"] == "DEPT"
    assert refreshed_body["resource_scopes"]["report"] == "DEPT"

    # 旧的两步保存端点已移除，避免全局范围与资源级范围分两次写入。
    legacy = await client.put(
        f"/api/v1/roles/{role['id']}/data-scope",
        json={"data_scope": "DEPT", "dept_ids": [], "version": replaced_role["version"]},
        headers=admin_headers,
    )
    assert legacy.status_code == 404
