from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import Role, User, user_roles
from app.models.base import now_cst
from tests.helpers import TEST_PASSWORD, auth_headers, login

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 128


async def _create_employee(username: str = "branding_employee") -> None:
    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == "EMPLOYEE"))
        ).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            real_name="品牌测试员工",
            source="local",
            status=1,
        )
        session.add(user)
        await session.flush()
        await session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await session.commit()


async def test_public_branding_defaults_without_login(client: AsyncClient):
    response = await client.get("/api/v1/branding")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["site_name"] == "ITAM"
    assert data["brand_mark_text"] == "IT"
    assert data["login_footer_text"] == "ITAM · IT 资产管理系统"
    assert data["dashboard_welcome"] == ""
    assert data["logo_url"] == ""
    assert data["background_url"] == ""


async def test_branding_update_reflects_on_public_endpoint(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    current = (await client.get("/api/v1/branding/admin", headers=headers)).json()["data"]
    payload = {
        "site_name": "星辰 ITAM",
        "site_subtitle": "STAR ASSET CENTER",
        "brand_mark_text": "星",
        "login_footer_text": "星辰 ITAM",
        "dashboard_welcome": "欢迎回来，{name}！",
    }
    updated = await client.put("/api/v1/branding/admin", json=payload, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["site_name"] == "星辰 ITAM"

    public = (await client.get("/api/v1/branding")).json()["data"]
    assert public["site_name"] == "星辰 ITAM"
    assert public["site_subtitle"] == "STAR ASSET CENTER"
    assert public["login_footer_text"] == "星辰 ITAM"
    assert public["dashboard_welcome"] == "欢迎回来，{name}！"
    assert current["site_name"] == "ITAM"


async def test_branding_update_requires_permission(client: AsyncClient):
    await _create_employee()
    logged = await client.post(
        "/api/v1/auth/login",
        json={"username": "branding_employee", "password": TEST_PASSWORD},
    )
    assert logged.status_code == 200, logged.text
    headers = auth_headers(logged.json()["data"]["access_token"])
    response = await client.put(
        "/api/v1/branding/admin",
        json={"site_name": "无权修改"},
        headers=headers,
    )
    assert response.status_code == 403, response.text


async def test_branding_image_upload_and_reset(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])

    uploaded = await client.post(
        "/api/v1/branding/admin/images/logo",
        files={"file": ("logo.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    logo_url = uploaded.json()["data"]["logo_url"]
    assert "/api/v1/branding/logo" in logo_url

    image = await client.get("/api/v1/branding/logo")
    assert image.status_code == 200, image.text
    assert image.headers["content-type"].startswith("image/png")
    assert image.content == PNG_BYTES

    public = (await client.get("/api/v1/branding")).json()["data"]
    assert public["logo_url"] == logo_url

    removed = await client.delete("/api/v1/branding/admin/images/logo", headers=headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["logo_url"] == ""
    assert (await client.get("/api/v1/branding/logo")).status_code == 404


async def test_branding_image_rejects_unsupported_type(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    response = await client.post(
        "/api/v1/branding/admin/images/logo",
        files={"file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
        headers=headers,
    )
    assert response.status_code == 400, response.text


async def test_announcement_lifecycle_and_active_filter(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    now = now_cst()

    active = await client.post(
        "/api/v1/branding/admin/announcements",
        json={
            "title": "系统升级通知",
            "content": "本周六 22:00 进行系统升级。",
            "level": "IMPORTANT",
            "is_active": True,
            "start_at": (now - timedelta(hours=1)).isoformat(),
            "end_at": (now + timedelta(days=2)).isoformat(),
            "sort": 1,
        },
        headers=headers,
    )
    assert active.status_code == 200, active.text
    active_id = active.json()["data"]["id"]

    expired = await client.post(
        "/api/v1/branding/admin/announcements",
        json={
            "title": "历史公告",
            "content": "已经过期。",
            "level": "INFO",
            "is_active": True,
            "end_at": (now - timedelta(days=1)).isoformat(),
            "sort": 2,
        },
        headers=headers,
    )
    assert expired.status_code == 200, expired.text
    expired_id = expired.json()["data"]["id"]

    inactive = await client.post(
        "/api/v1/branding/admin/announcements",
        json={
            "title": "草稿公告",
            "content": "未启用。",
            "level": "WARNING",
            "is_active": False,
        },
        headers=headers,
    )
    assert inactive.status_code == 200, inactive.text

    active_list = (await client.get("/api/v1/branding/announcements", headers=headers)).json()[
        "data"
    ]
    assert [item["id"] for item in active_list] == [active_id]
    assert active_list[0]["level_label"] == "重要"

    admin_list = (
        await client.get("/api/v1/branding/admin/announcements", headers=headers)
    ).json()["data"]
    assert {item["id"] for item in admin_list} >= {active_id, expired_id}

    updated = await client.put(
        f"/api/v1/branding/admin/announcements/{active_id}",
        json={
            "title": "系统升级通知（延期）",
            "content": "升级调整到下周日。",
            "level": "IMPORTANT",
            "is_active": True,
            "sort": 1,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["title"] == "系统升级通知（延期）"

    deleted = await client.delete(
        f"/api/v1/branding/admin/announcements/{active_id}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
    assert (
        await client.get("/api/v1/branding/announcements", headers=headers)
    ).json()["data"] == []


async def test_announcement_window_validation(client: AsyncClient):
    tokens = await login(client)
    headers = auth_headers(tokens["access_token"])
    now = now_cst()
    response = await client.post(
        "/api/v1/branding/admin/announcements",
        json={
            "title": "时间错误",
            "content": "生效时间晚于失效时间。",
            "start_at": (now + timedelta(days=2)).isoformat(),
            "end_at": now.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 400, response.text
