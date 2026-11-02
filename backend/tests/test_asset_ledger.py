from httpx import AsyncClient

from tests.helpers import auth_headers, login


async def _category(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    response = await client.get("/api/v1/asset-categories/tree", headers=headers)
    tree = response.json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == code:
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    category = walk(tree)
    assert category is not None
    return category


async def _dept(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    response = await client.get("/api/v1/departments/tree", headers=headers)
    tree = response.json()["data"]

    def walk(nodes):
        for node in nodes:
            if node["code"] == code:
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    dept = walk(tree)
    assert dept is not None
    return dept


async def _model(client: AsyncClient, headers: dict[str, str], code: str) -> dict:
    response = await client.get(
        "/api/v1/asset-models", params={"keyword": code, "page_size": 50}, headers=headers
    )
    items = response.json()["data"]["items"]
    model = next(item for item in items if item["code"] == code)
    return model


async def test_asset_create_list_update_delete(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _category(client, headers, "HW-LAPTOP")
    model = await _model(client, headers, "LENOVO-X1-CARBON-G11")
    it_dept = await _dept(client, headers, "IT")

    created = await client.post(
        "/api/v1/assets",
        json={
            "name": "测试笔记本",
            "category_id": laptop["id"],
            "model_id": model["id"],
            "serial_no": "SN-TEST-001",
            "purchase_date": "2026-01-15",
            "supplier": "测试供应商",
            "purchase_price": 8800.5,
            "warranty_end": "2029-01-14",
            "location": "A 座 301",
            "dept_id": it_dept["id"],
            "custom_fields": {"cpu": "i7-1365U", "memory": "32GB", "os": "Windows 11"},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    asset = created.json()["data"]
    assert asset["asset_no"].startswith("ITAM-")
    assert asset["status"] == "PENDING_STOCK"
    assert asset["status_label"] == "待入库"
    assert asset["custom_fields"] == {
        "cpu": "i7-1365U",
        "memory": "32GB",
        "os": "Windows 11",
    }
    assert asset["dept_name"] == it_dept["name"]

    duplicate = await client.post(
        "/api/v1/assets",
        json={
            "asset_no": asset["asset_no"],
            "name": "重复编号",
            "category_id": laptop["id"],
            "custom_fields": {},
        },
        headers=headers,
    )
    assert duplicate.status_code == 409

    listed = await client.get(
        "/api/v1/assets",
        params={"keyword": "SN-TEST-001", "category_id": laptop["id"]},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    page = listed.json()["data"]
    assert page["total"] == 1
    assert page["items"][0]["id"] == asset["id"]

    updated = await client.put(
        f"/api/v1/assets/{asset['id']}",
        json={
            "name": "测试笔记本（改名）",
            "category_id": laptop["id"],
            "model_id": model["id"],
            "serial_no": "SN-TEST-001",
            "purchase_date": "2026-01-15",
            "supplier": "测试供应商",
            "purchase_price": 8600,
            "warranty_end": "2029-01-14",
            "location": "A 座 302",
            "dept_id": it_dept["id"],
            "custom_fields": {"cpu": "i7-1365U", "os": "Windows 10"},
            "version": asset["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    changed = updated.json()["data"]
    assert changed["version"] == asset["version"] + 1
    assert changed["name"] == "测试笔记本（改名）"
    assert changed["asset_no"] == asset["asset_no"]
    assert changed["status"] == "PENDING_STOCK"

    stale = await client.put(
        f"/api/v1/assets/{asset['id']}",
        json={
            "name": "过期更新",
            "category_id": laptop["id"],
            "custom_fields": {},
            "version": asset["version"],
        },
        headers=headers,
    )
    assert stale.status_code == 409

    timeline = await client.get(
        f"/api/v1/assets/{asset['id']}/timeline", headers=headers
    )
    assert timeline.status_code == 200, timeline.text
    actions = [item["action"] for item in timeline.json()["data"]]
    assert "asset.ledger.create" in actions
    assert "asset.ledger.update" in actions

    removed = await client.delete(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert removed.status_code == 200, removed.text

    gone = await client.get(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert gone.status_code == 404

    listed_after = await client.get(
        "/api/v1/assets", params={"keyword": "SN-TEST-001"}, headers=headers
    )
    assert listed_after.json()["data"]["total"] == 0


async def test_ledger_asset_stock_in(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _category(client, headers, "HW-LAPTOP")
    it_dept = await _dept(client, headers, "IT")

    created = await client.post(
        "/api/v1/assets",
        json={
            "name": "台账入库测试笔记本",
            "category_id": laptop["id"],
            "dept_id": it_dept["id"],
            "location": "A 座 401",
            "custom_fields": {"cpu": "i7-1365U", "memory": "16GB", "os": "Windows 11"},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    asset = created.json()["data"]
    assert asset["status"] == "PENDING_STOCK"

    unavailable_before = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": laptop["id"]},
        headers=headers,
    )
    assert unavailable_before.status_code == 200, unavailable_before.text
    assert unavailable_before.json()["data"]["total"] == 0

    stale = await client.post(
        f"/api/v1/assets/{asset['id']}/stock-in",
        json={"version": asset["version"] + 1},
        headers=headers,
    )
    assert stale.status_code == 409, stale.text

    stocked = await client.post(
        f"/api/v1/assets/{asset['id']}/stock-in",
        json={"version": asset["version"]},
        headers=headers,
    )
    assert stocked.status_code == 200, stocked.text
    stocked_asset = stocked.json()["data"]
    assert stocked_asset["status"] == "IN_STOCK"
    assert stocked_asset["status_label"] == "在库"
    assert stocked_asset["version"] == asset["version"] + 1

    duplicate = await client.post(
        f"/api/v1/assets/{asset['id']}/stock-in",
        json={"version": stocked_asset["version"]},
        headers=headers,
    )
    assert duplicate.status_code == 400, duplicate.text

    history = await client.get(
        f"/api/v1/assets/{asset['id']}/history", headers=headers
    )
    assert history.status_code == 200, history.text
    history_items = history.json()["data"]
    assert len(history_items) == 1
    assert history_items[0]["action"] == "INBOUND"
    assert history_items[0]["action_label"] == "验收入库"
    assert history_items[0]["from_status"] == "PENDING_STOCK"
    assert history_items[0]["to_status"] == "IN_STOCK"
    assert history_items[0]["summary"] == "资产台账确认入库"

    timeline = await client.get(
        f"/api/v1/assets/{asset['id']}/timeline", headers=headers
    )
    actions = [item["action"] for item in timeline.json()["data"]]
    assert "asset.ledger.stock_in" in actions

    available_after = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": laptop["id"]},
        headers=headers,
    )
    assert available_after.status_code == 200, available_after.text
    available_items = available_after.json()["data"]["items"]
    assert [item["id"] for item in available_items] == [asset["id"]]


async def test_asset_validation_rules(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _category(client, headers, "HW-LAPTOP")
    server = await _category(client, headers, "HW-SERVER")
    desktop_model = await _model(client, headers, "DELL-OPTIPLEX-7010")

    missing_required = await client.post(
        "/api/v1/assets",
        json={"name": "缺少必填扩展字段", "category_id": server["id"], "custom_fields": {}},
        headers=headers,
    )
    assert missing_required.status_code == 400
    assert "必填" in missing_required.json()["message"]

    invalid_option = await client.post(
        "/api/v1/assets",
        json={
            "name": "非法下拉值",
            "category_id": laptop["id"],
            "custom_fields": {"os": "Linux Mint"},
        },
        headers=headers,
    )
    assert invalid_option.status_code == 400

    invalid_number = await client.post(
        "/api/v1/assets",
        json={
            "name": "非法数字",
            "category_id": server["id"],
            "custom_fields": {"cpu_cores": "many"},
        },
        headers=headers,
    )
    assert invalid_number.status_code == 400

    mismatched_model = await client.post(
        "/api/v1/assets",
        json={
            "name": "型号分类不匹配",
            "category_id": laptop["id"],
            "model_id": desktop_model["id"],
            "custom_fields": {},
        },
        headers=headers,
    )
    assert mismatched_model.status_code == 400
    assert "型号" in mismatched_model.json()["message"]


async def test_asset_options_endpoints(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    custodians = await client.get(
        "/api/v1/assets/custodian-options", params={"keyword": "admin"}, headers=headers
    )
    assert custodians.status_code == 200, custodians.text
    options = custodians.json()["data"]
    assert options
    assert options[0]["username"] == "admin"

    depts = await client.get("/api/v1/assets/dept-options", headers=headers)
    assert depts.status_code == 200, depts.text
    dept_items = depts.json()["data"]
    assert dept_items
    assert all({"id", "name", "path"} <= set(item) for item in dept_items)


async def test_asset_batch_update_and_export(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    admin_id = tokens["user"]["id"]
    laptop = await _category(client, headers, "HW-LAPTOP")
    it_dept = await _dept(client, headers, "IT")

    asset_ids: list[int] = []
    for index in (1, 2):
        created = await client.post(
            "/api/v1/assets",
            json={
                "name": f"批量资产 {index}",
                "category_id": laptop["id"],
                "serial_no": f"SN-BATCH-{index}",
                "custom_fields": {},
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        asset_ids.append(created.json()["data"]["id"])

    batch = await client.post(
        "/api/v1/assets/batch-update",
        json={
            "asset_ids": asset_ids,
            "dept_id": it_dept["id"],
            "custodian_id": admin_id,
            "location": "B 座 201",
        },
        headers=headers,
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["data"]["updated"] == 2

    for asset_id in asset_ids:
        detail = await client.get(f"/api/v1/assets/{asset_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        data = detail.json()["data"]
        assert data["dept_name"] == it_dept["name"]
        assert data["custodian_id"] == admin_id
        assert data["location"] == "B 座 201"

    cleared = await client.post(
        "/api/v1/assets/batch-update",
        json={"asset_ids": asset_ids[:1], "clear_custodian": True},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    detail = await client.get(f"/api/v1/assets/{asset_ids[0]}", headers=headers)
    assert detail.json()["data"]["custodian_id"] is None

    outside = await client.post(
        "/api/v1/assets/batch-update",
        json={"asset_ids": [asset_ids[0], 999999], "location": "C 座"},
        headers=headers,
    )
    assert outside.status_code == 404

    no_change = await client.post(
        "/api/v1/assets/batch-update",
        json={"asset_ids": asset_ids},
        headers=headers,
    )
    assert no_change.status_code == 422

    exported = await client.get(
        "/api/v1/assets/export",
        params={"keyword": "SN-BATCH-"},
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert exported.headers["x-export-rows"] == "2"
    assert exported.headers["x-export-truncated"] == "false"
    assert exported.content[:2] == b"PK"

    for asset_id in asset_ids:
        await client.delete(f"/api/v1/assets/{asset_id}", headers=headers)


async def test_asset_attachment_upload_and_download(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    laptop = await _category(client, headers, "HW-LAPTOP")

    created = await client.post(
        "/api/v1/assets",
        json={
            "name": "附件资产",
            "category_id": laptop["id"],
            "serial_no": "SN-ATTACH-1",
            "custom_fields": {},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    asset_id = created.json()["data"]["id"]

    content = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    uploaded = await client.post(
        f"/api/v1/assets/{asset_id}/attachments",
        files={"file": ("设备照片.png", content, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    attachment = uploaded.json()["data"]
    assert attachment["file_name"] == "设备照片.png"
    assert attachment["kind"] == "IMAGE"
    assert attachment["file_size"] == len(content)
    assert attachment["uploaded_by_name"]

    listed = await client.get(
        f"/api/v1/assets/{asset_id}/attachments", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["data"]] == [attachment["id"]]

    downloaded = await client.get(
        f"/api/v1/assets/{asset_id}/attachments/{attachment['id']}/download",
        headers=headers,
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "image/png"

    blocked = await client.post(
        f"/api/v1/assets/{asset_id}/attachments",
        files={"file": ("setup.exe", b"MZ", "application/octet-stream")},
        headers=headers,
    )
    assert blocked.status_code == 400
    assert "不支持" in blocked.json()["message"]

    removed = await client.delete(
        f"/api/v1/assets/{asset_id}/attachments/{attachment['id']}",
        headers=headers,
    )
    assert removed.status_code == 200, removed.text
    listed = await client.get(
        f"/api/v1/assets/{asset_id}/attachments", headers=headers
    )
    assert listed.json()["data"] == []
    gone = await client.get(
        f"/api/v1/assets/{asset_id}/attachments/{attachment['id']}/download",
        headers=headers,
    )
    assert gone.status_code == 404

    await client.delete(f"/api/v1/assets/{asset_id}", headers=headers)
