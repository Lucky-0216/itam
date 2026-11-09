from httpx import AsyncClient

from tests.helpers import auth_headers, login


def _flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node["children"]))
    return result


async def _context(client: AsyncClient, headers: dict[str, str]) -> tuple[dict, dict, list[dict]]:
    tree = (await client.get("/api/v1/departments/tree", headers=headers)).json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == "IT":
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    menus = (await client.get("/api/v1/roles/menu-tree", headers=headers)).json()["data"]
    return walk(tree), {menu["permission_code"]: menu for menu in _flatten(menus)}, menus


async def test_role_authorization_flow_and_data_scope(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    it_dept, menu_map, _ = await _context(client, headers)

    created = await client.post(
        "/api/v1/roles",
        json={
            "code": "TEST_OPERATOR",
            "name": "测试操作员",
            "description": "组织只读",
            "data_scope": "SELF",
            "sort": 80,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    role = created.json()["data"]
    role_id = role["id"]

    assigned = await client.put(
        f"/api/v1/roles/{role_id}/menus",
        json={"menu_ids": [menu_map["system:org:view"]["id"]], "version": role["version"]},
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    role = assigned.json()["data"]
    assert menu_map["system:org:view"]["id"] in role["menu_ids"]
    assert menu_map["system:view"]["id"] in role["menu_ids"]
    assert menu_map["system:user:create"]["id"] not in role["menu_ids"]

    scoped = await client.put(
        f"/api/v1/roles/{role_id}/data-permissions",
        json={
            "data_scope": "CUSTOM",
            "domain_scope": "CUSTOM",
            "asset_domains": [],
            "permissions": [],
            "dept_ids": [it_dept["id"]],
            "version": role["version"],
        },
        headers=headers,
    )
    assert scoped.status_code == 200, scoped.text
    role = scoped.json()["data"]
    assert role["data_scope"] == "CUSTOM"
    assert role["dept_ids"] == [it_dept["id"]]

    field_scoped = await client.put(
        f"/api/v1/roles/{role_id}/field-permissions",
        json={
            "permissions": [
                {"resource": "asset", "field": "serial_no", "can_view": False, "can_edit": False},
                {"resource": "asset", "field": "purchase_price", "can_view": False, "can_edit": False},
            ],
            "version": role["version"],
        },
        headers=headers,
    )
    assert field_scoped.status_code == 200, field_scoped.text
    role = field_scoped.json()["data"]
    assert {item["field"] for item in role["field_permissions"]} == {
        "serial_no",
        "purchase_price",
    }

    user_created = await client.post(
        "/api/v1/users",
        json={
            "username": "lisi",
            "password": "Init@12345",
            "real_name": "李四",
            "dept_id": it_dept["id"],
            "role_ids": [role_id],
            "status": 1,
        },
        headers=headers,
    )
    assert user_created.status_code == 200, user_created.text
    lisi = user_created.json()["data"]

    lisi_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "lisi", "password": "Init@12345"},
    )
    assert lisi_login.status_code == 200, lisi_login.text
    lisi_tokens = lisi_login.json()["data"]

    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "Init@12345", "new_password": "Lisi@12345"},
        headers=auth_headers(lisi_tokens["access_token"]),
    )
    assert changed.status_code == 200, changed.text
    lisi_access = changed.json()["data"]["access_token"]
    lisi_headers = auth_headers(lisi_access)

    me = await client.get("/api/v1/auth/me", headers=lisi_headers)
    assert me.status_code == 200, me.text
    profile = me.json()["data"]
    assert profile["data_scope"] == "CUSTOM"
    assert profile["custom_dept_ids"] == [it_dept["id"]]
    assert "system:org:view" in profile["permissions"]
    assert "system:user:create" not in profile["permissions"]
    assert profile["field_permissions"]["asset"]["serial_no"]["can_view"] is False
    assert profile["menus"][0]["path"] == "/system"

    scoped_list = await client.get("/api/v1/users", headers=lisi_headers)
    assert scoped_list.status_code == 200, scoped_list.text
    usernames = {item["username"] for item in scoped_list.json()["data"]["items"]}
    assert "lisi" in usernames
    assert "admin" in usernames

    forbidden = await client.post(
        "/api/v1/users",
        json={
            "username": "wangwu",
            "password": "Init@12345",
            "real_name": "王五",
            "dept_id": it_dept["id"],
            "role_ids": [role_id],
        },
        headers=lisi_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40300

    detail = await client.get(f"/api/v1/roles/{role_id}", headers=headers)
    role = detail.json()["data"]
    assert [member["username"] for member in role["users"]] == ["lisi"]

    cleared = await client.put(
        f"/api/v1/roles/{role_id}/users",
        json={"user_ids": [], "version": role["version"]},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    role = cleared.json()["data"]
    assert role["users"] == []

    me_after = await client.get("/api/v1/auth/me", headers=lisi_headers)
    assert me_after.status_code == 200
    assert "system:org:view" not in me_after.json()["data"]["permissions"]

    removed = await client.delete(f"/api/v1/roles/{role_id}", headers=headers)
    assert removed.status_code == 200, removed.text


async def test_role_data_permissions_can_be_resaved(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    created = await client.post(
        "/api/v1/roles",
        json={
            "code": "TEST_RESAVE",
            "name": "重复保存资源数据权限",
            "description": None,
            "data_scope": "SELF",
            "sort": 81,
            "status": 1,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    role = created.json()["data"]

    first = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "CUSTOM",
            "asset_domains": ["IT"],
            "permissions": [
                {"resource": "asset", "data_scope": "SELF"},
                {"resource": "inbound", "data_scope": "DEPT_AND_CHILD"},
            ],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text
    role = first.json()["data"]

    second = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "CUSTOM",
            "asset_domains": ["IT", "ADMIN"],
            "permissions": [
                {"resource": "asset", "data_scope": "DEPT"},
                {"resource": "inbound", "data_scope": "SELF"},
                {"resource": "stock", "data_scope": "DEPT"},
            ],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    role = second.json()["data"]
    assert role["domain_scope"] == "CUSTOM"
    assert role["asset_domains"] == ["ADMIN", "IT"]
    assert {
        (item["resource"], item["data_scope"])
        for item in role["data_permissions"]
    } == {
        ("asset", "DEPT"),
        ("inbound", "SELF"),
        ("stock", "DEPT"),
    }

    third = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [
                {"resource": "asset", "data_scope": "SELF"},
            ],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=headers,
    )
    assert third.status_code == 200, third.text
    assert third.json()["data"]["domain_scope"] == "ALL"
    assert third.json()["data"]["asset_domains"] == []
    assert [
        (item["resource"], item["data_scope"])
        for item in third.json()["data"]["data_permissions"]
    ] == [("asset", "SELF")]


async def test_super_admin_role_guards(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    listed = await client.get(
        "/api/v1/roles",
        params={"keyword": "SUPER_ADMIN"},
        headers=headers,
    )
    assert listed.status_code == 200
    super_role = next(
        item for item in listed.json()["data"]["items"] if item["code"] == "SUPER_ADMIN"
    )

    detail = await client.get(f"/api/v1/roles/{super_role['id']}", headers=headers)
    role = detail.json()["data"]
    assert role["is_system"] is True
    assert role["data_scope"] == "ALL"
    assert any(user["username"] == "admin" for user in role["users"])

    clear_members = await client.put(
        f"/api/v1/roles/{role['id']}/users",
        json={"user_ids": [], "version": role["version"]},
        headers=headers,
    )
    assert clear_members.status_code == 400
    assert clear_members.json()["code"] == 40020

    assign_menu = await client.put(
        f"/api/v1/roles/{role['id']}/menus",
        json={"menu_ids": [], "version": role["version"]},
        headers=headers,
    )
    assert assign_menu.status_code == 400

    assign_data = await client.put(
        f"/api/v1/roles/{role['id']}/data-permissions",
        json={
            "data_scope": "SELF",
            "domain_scope": "ALL",
            "asset_domains": [],
            "permissions": [],
            "dept_ids": [],
            "version": role["version"],
        },
        headers=headers,
    )
    assert assign_data.status_code == 400

    delete_role = await client.delete(f"/api/v1/roles/{role['id']}", headers=headers)
    assert delete_role.status_code == 400

    delete_self = await client.delete(
        f"/api/v1/users/{tokens['user']['id']}",
        headers=headers,
    )
    assert delete_self.status_code == 400
