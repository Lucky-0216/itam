from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AssetRequest,
    AuditLog,
    Dept,
    User,
)
from tests.helpers import auth_headers, login


async def _admin(client: AsyncClient) -> dict[str, str]:
    return auth_headers((await login(client))["access_token"])


async def _base_data() -> tuple[int, int]:
    async with AsyncSessionLocal() as session:
        category = (
            await session.execute(
                select(AssetCategory).where(AssetCategory.code == "HW-LAPTOP")
            )
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == "IT"))
        ).scalar_one()
        return category.id, dept.id


async def _create_inbound(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    category_id: int,
    dept_id: int,
    name: str,
    quantity: int,
    base_no: str | None = None,
    asset_nos: list[str] | None = None,
    source_inbound_id: int | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "测试供应商",
            "location": "测试库位",
            "dept_id": dept_id,
            "source_inbound_id": source_inbound_id,
            "items": [
                {
                    "category_id": category_id,
                    "name": name,
                    "quantity": quantity,
                    "base_asset_no": base_no,
                    "asset_nos": asset_nos,
                    "unit_price": 1000,
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _confirm(
    client: AsyncClient, headers: dict[str, str], inbound: dict
) -> dict:
    response = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/confirm",
        json={"version": inbound["version"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _assets_by_nos(*asset_nos: str) -> dict[str, Asset]:
    async with AsyncSessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(Asset).where(Asset.asset_no.in_(asset_nos))
                )
            )
            .scalars()
            .all()
        )
        return {asset.asset_no: asset for asset in rows}


async def test_void_releases_code_and_rejects_active_business(
    client: AsyncClient,
):
    headers = await _admin(client)
    category_id, dept_id = await _base_data()
    inbound = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="作废测试笔记本",
        quantity=2,
        base_no="VOID-T1",
    )
    await _confirm(client, headers, inbound)
    assets = await _assets_by_nos("VOID-T1-1", "VOID-T1-2")
    first = assets["VOID-T1-1"]
    second = assets["VOID-T1-2"]
    assert first.status == AssetStatus.IN_STOCK

    voided = await client.post(
        f"/api/v1/assets/{first.id}/void",
        json={"reason": "入库数量多录", "version": first.version},
        headers=headers,
    )
    assert voided.status_code == 200, voided.text
    body = voided.json()["data"]
    assert body["status"] == "VOIDED"
    assert body["void_reason"] == "入库数量多录"

    async with AsyncSessionLocal() as session:
        record = await session.get(Asset, first.id)
        assert record.deleted_at is not None
        assert record.void_seq == 1
        history = (
            await session.execute(
                select(AssetHistory).where(
                    AssetHistory.asset_id == first.id,
                    AssetHistory.action == "VOID",
                )
            )
        ).scalar_one()
        assert history.action == "VOID"
        assert history.to_status == AssetStatus.VOIDED
        audit_rows = list(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "asset.ledger.void",
                        AuditLog.resource_id == str(first.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert audit_rows
        assert audit_rows[0].before_data is not None
        assert audit_rows[0].after_data is not None
        assert audit_rows[0].after_data["status"] == AssetStatus.VOIDED

    history_resp = await client.get(
        f"/api/v1/assets/{first.id}/history", headers=headers
    )
    assert history_resp.status_code == 200, history_resp.text
    history_items = history_resp.json()["data"]
    assert len(history_items) == 2
    assert [item["action"] for item in history_items] == ["VOID", "INBOUND"]
    assert history_items[0]["from_status"] == AssetStatus.IN_STOCK
    assert history_items[0]["to_status"] == AssetStatus.VOIDED
    assert history_items[0]["before_snapshot"]["status"] == AssetStatus.IN_STOCK
    assert history_items[0]["after_snapshot"]["status"] == AssetStatus.VOIDED

    stock = await client.get(
        "/api/v1/stock/items",
        params={"keyword": "VOID-T1-1"},
        headers=headers,
    )
    assert stock.status_code == 200, stock.text
    assert stock.json()["data"]["total"] == 0

    available = await client.get(
        "/api/v1/asset-requests/available-assets",
        params={"category_id": category_id, "page_size": 200},
        headers=headers,
    )
    assert available.status_code == 200, available.text
    available_nos = {
        item["asset_no"] for item in available.json()["data"]["items"]
    }
    assert "VOID-T1-1" not in available_nos
    assert "VOID-T1-2" in available_nos

    reused = await client.post(
        "/api/v1/assets",
        json={
            "asset_no": "VOID-T1-1",
            "name": "复用编码资产",
            "category_id": category_id,
            "custom_fields": {},
        },
        headers=headers,
    )
    assert reused.status_code == 200, reused.text
    reused_asset = reused.json()["data"]
    assert reused_asset["status"] == "PENDING_STOCK"

    with_business = second
    async with AsyncSessionLocal() as session:
        applicant = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        session.add(
            AssetRequest(
                request_no="LY-TEST-VOID-0001",
                request_type="REQUISITION",
                status="PENDING_APPROVAL",
                category_id=category_id,
                category_name="笔记本电脑",
                asset_id=with_business.id,
                asset_no=with_business.asset_no,
                asset_name=with_business.name,
                applicant_id=applicant.id,
                applicant_name=applicant.real_name or applicant.username,
            )
        )
        await session.commit()

    blocked = await client.post(
        f"/api/v1/assets/{with_business.id}/void",
        json={"reason": "存在进行中单据", "version": with_business.version},
        headers=headers,
    )
    assert blocked.status_code == 400, blocked.text
    assert "处理中的领用/借用单据" in blocked.json()["message"]


async def test_inbound_update_reverse_and_supplement(client: AsyncClient):
    headers = await _admin(client)
    category_id, dept_id = await _base_data()
    inbound = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="数量纠错笔记本",
        quantity=3,
        base_no="FIX-T1",
    )

    updated = await client.put(
        f"/api/v1/inbounds/{inbound['id']}",
        json={
            "inbound_type": "PURCHASE",
            "supplier": "测试供应商",
            "location": "测试库位",
            "dept_id": dept_id,
            "items": [
                {
                    "category_id": category_id,
                    "name": "数量纠错笔记本",
                    "quantity": 2,
                    "base_asset_no": "FIX-T1",
                    "unit_price": 1000,
                }
            ],
            "version": inbound["version"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    updated_inbound = updated.json()["data"]
    assert updated_inbound["total_quantity"] == 2
    assert len(updated_inbound["items"][0]["asset_nos"]) == 2

    confirmed = await _confirm(client, headers, updated_inbound)
    assert confirmed["status"] == "COMPLETED"
    assert len(confirmed["assets"]) == 2
    assert all(item["can_reverse"] for item in confirmed["assets"])
    codes = [item["asset_no"] for item in confirmed["assets"]]

    reversed_one = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/reverse-assets",
        json={
            "asset_nos": [codes[0]],
            "reason": "多录一台",
            "version": confirmed["version"],
        },
        headers=headers,
    )
    assert reversed_one.status_code == 200, reversed_one.text
    reversed_body = reversed_one.json()["data"]
    statuses = {item["asset_no"]: item["status"] for item in reversed_body["assets"]}
    assert statuses[codes[0]] == "VOIDED"
    assert statuses[codes[1]] == "IN_STOCK"
    assert reversed_body["can_reverse"] is True

    async with AsyncSessionLocal() as session:
        reverse_audits = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "asset.inbound.reverse")
        )
    assert reverse_audits >= 2

    supplement = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="数量纠错笔记本",
        quantity=1,
        base_no="FIX-T1",
        source_inbound_id=inbound["id"],
    )
    assert supplement["source_inbound_id"] == inbound["id"]
    supplement_codes = supplement["items"][0]["asset_nos"]
    assert len(supplement_codes) == 1
    assert supplement_codes[0] not in codes
    supplement_confirmed = await _confirm(client, headers, supplement)
    assert supplement_confirmed["status"] == "COMPLETED"
    assert len(supplement_confirmed["assets"]) == 1

    async with AsyncSessionLocal() as session:
        asset = (
            await session.execute(
                select(Asset).where(Asset.asset_no == codes[1])
            )
        ).scalar_one()
        asset.status = AssetStatus.IN_USE
        await session.commit()
        in_use_version = asset.version

    blocked = await client.post(
        f"/api/v1/inbounds/{inbound['id']}/reverse-assets",
        json={
            "asset_nos": [codes[1]],
            "reason": "已领用",
            "version": reversed_body["version"],
        },
        headers=headers,
    )
    assert blocked.status_code == 400, blocked.text
    assert in_use_version >= 1


async def test_pending_reservation_and_released_code_reuse(client: AsyncClient):
    headers = await _admin(client)
    category_id, dept_id = await _base_data()

    first = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="手工编码测试",
        quantity=1,
        asset_nos=["MANUAL-T1-1"],
    )
    second = await client.post(
        "/api/v1/inbounds",
        json={
            "inbound_type": "PURCHASE",
            "dept_id": dept_id,
            "items": [
                {
                    "category_id": category_id,
                    "name": "手工编码测试",
                    "quantity": 1,
                    "asset_nos": ["MANUAL-T1-1"],
                }
            ],
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text

    cancelled = await client.post(
        f"/api/v1/inbounds/{first['id']}/cancel",
        json={"reason": "重新登记"},
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    third = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="手工编码测试",
        quantity=1,
        asset_nos=["MANUAL-T1-1"],
    )
    confirmed = await _confirm(client, headers, third)
    asset = (await _assets_by_nos("MANUAL-T1-1"))["MANUAL-T1-1"]
    assert asset.status == AssetStatus.IN_STOCK

    voided = await client.post(
        f"/api/v1/assets/{asset.id}/void",
        json={"reason": "释放编码", "version": asset.version},
        headers=headers,
    )
    assert voided.status_code == 200, voided.text

    fourth = await _create_inbound(
        client,
        headers,
        category_id=category_id,
        dept_id=dept_id,
        name="手工编码复用",
        quantity=1,
        asset_nos=["MANUAL-T1-1"],
    )
    assert fourth["status"] == "PENDING"
    assert confirmed["status"] == "COMPLETED"
