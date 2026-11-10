from httpx import AsyncClient
from sqlalchemy import insert, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import Asset, AssetCategory, AuditLog, Dept, Role, User, user_roles
from app.services.dingtalk_sync_service import DingTalkSyncService
from app.services.ldap_service import LdapSyncService, _normalize_dn
from tests.helpers import auth_headers, login

TEST_PASSWORD = "Test@12345"


def _flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node.get("children") or []))
    return result


async def _dept_id(code: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (await session.execute(select(Dept.id).where(Dept.code == code))).scalar_one()
        )


async def _dept_row(dept_id: int) -> Dept:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(Dept).where(Dept.id == dept_id))
        ).scalar_one()


async def _ensure_user(
    username: str,
    real_name: str,
    role_code: str,
    dept_code: str = "IT",
) -> int:
    async with AsyncSessionLocal() as session:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one()
        dept = (
            await session.execute(select(Dept).where(Dept.code == dept_code))
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


async def _create_dept(
    name: str,
    code: str,
    source: str,
    *,
    ldap_dn: str | None = None,
    dingtalk_dept_id: str | None = None,
) -> int:
    async with AsyncSessionLocal() as session:
        dept = Dept(
            name=name,
            code=code,
            path="",
            level=1,
            sort=0,
            status=1,
            source=source,
            ldap_dn=ldap_dn,
            dingtalk_dept_id=dingtalk_dept_id,
        )
        session.add(dept)
        await session.flush()
        dept.path = f"/{dept.id}/"
        await session.commit()
        return dept.id


async def _create_user(
    username: str,
    real_name: str,
    dept_id: int,
    source: str,
    *,
    employee_no: str | None = None,
    position: str | None = None,
    ldap_dn: str | None = None,
    dingtalk_userid: str | None = None,
) -> int:
    async with AsyncSessionLocal() as session:
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            real_name=real_name,
            dept_id=dept_id,
            status=1,
            source=source,
            employee_no=employee_no,
            position=position,
            ldap_dn=ldap_dn,
            dingtalk_userid=dingtalk_userid,
            must_change_password=False,
        )
        session.add(user)
        await session.commit()
        return user.id


async def _audits(action: str) -> list[AuditLog]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == action)
                    .order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )


async def _tree(client: AsyncClient, headers: dict, source: str) -> list[dict]:
    response = await client.get(
        "/api/v1/dept-managers/tree", params={"source": source}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _find(nodes: list[dict], code: str) -> dict:
    return next(node for node in _flatten(nodes) if node["code"] == code)


async def _assign(
    client: AsyncClient,
    headers: dict,
    dept_id: int,
    *,
    source: str,
    manager_id: int | None,
    version: int,
):
    return await client.put(
        f"/api/v1/dept-managers/{dept_id}",
        json={"source": source, "manager_id": manager_id, "version": version},
        headers=headers,
    )


async def _category_id(code: str = "HW-LAPTOP") -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(
                    select(AssetCategory.id).where(AssetCategory.code == code)
                )
            ).scalar_one()
        )


async def _ensure_asset(asset_no: str, name: str) -> int:
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
            status="IN_STOCK",
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


async def test_dept_manager_requires_permission(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    await _ensure_user("dm_emp", "部门负责人普通员工", "EMPLOYEE")
    it_id = await _dept_id("IT")
    emp_headers = await _login_as(client, "dm_emp")

    tree = await client.get(
        "/api/v1/dept-managers/tree", params={"source": "local"}, headers=emp_headers
    )
    assert tree.status_code == 403, tree.text

    members = await client.get(
        f"/api/v1/dept-managers/{it_id}/users",
        params={"source": "local"},
        headers=emp_headers,
    )
    assert members.status_code == 403, members.text

    forbidden = await _assign(
        client, emp_headers, it_id, source="local", manager_id=None, version=1
    )
    assert forbidden.status_code == 403, forbidden.text

    assert await _audits("org.dept.manager.assign") == []
    assert await _audits("org.dept.manager.clear") == []

    # 管理员可访问
    ok_tree = await client.get(
        "/api/v1/dept-managers/tree", params={"source": "local"}, headers=admin_headers
    )
    assert ok_tree.status_code == 200, ok_tree.text


async def test_dept_manager_source_isolation_and_assign_audit(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])

    ldap_dept = await _create_dept(
        "域控研发部", "LDAP-RD", "ldap", ldap_dn="OU=研发部,DC=example,DC=com"
    )
    ldap_empty = await _create_dept(
        "域控空部门", "LDAP-EMPTY", "ldap", ldap_dn="OU=空部门,DC=example,DC=com"
    )
    dd_dept = await _create_dept(
        "钉钉市场部", "DD-MKT", "dingtalk", dingtalk_dept_id="dd-mkt-001"
    )

    zhang = await _create_user(
        "ldap_zhang",
        "域控张三",
        ldap_dept,
        "ldap",
        employee_no="E-L001",
        position="研发经理",
        ldap_dn="CN=张三,OU=研发部,DC=example,DC=com",
    )
    await _create_user(
        "ldap_li",
        "域控李四",
        ldap_dept,
        "ldap",
        employee_no="E-L002",
        position="研发工程师",
        ldap_dn="CN=李四,OU=研发部,DC=example,DC=com",
    )
    stray = await _create_user("ldap_stray", "同部门本地来源", ldap_dept, "local")
    await _create_user(
        "dd_wang",
        "钉钉王五",
        dd_dept,
        "dingtalk",
        employee_no="E-D001",
        dingtalk_userid="dd-wang",
    )

    ldap_tree = await _tree(client, admin_headers, "ldap")
    assert {node["code"] for node in _flatten(ldap_tree)} == {"LDAP-RD", "LDAP-EMPTY"}

    dd_tree = await _tree(client, admin_headers, "dingtalk")
    assert {node["code"] for node in _flatten(dd_tree)} == {"DD-MKT"}

    local_tree = await _tree(client, admin_headers, "local")
    local_codes = {node["code"] for node in _flatten(local_tree)}
    assert "IT" in local_codes
    assert "LDAP-RD" not in local_codes and "DD-MKT" not in local_codes

    members = await client.get(
        f"/api/v1/dept-managers/{ldap_dept}/users",
        params={"source": "ldap"},
        headers=admin_headers,
    )
    assert members.status_code == 200, members.text
    member_data = members.json()["data"]
    # 直属成员中只返回 ldap 来源，local 来源同名部门成员被隔离
    assert member_data["total"] == 2
    assert {item["source"] for item in member_data["items"]} == {"ldap"}
    assert member_data["manager"] is None

    searched = await client.get(
        f"/api/v1/dept-managers/{ldap_dept}/users",
        params={"source": "ldap", "keyword": "李四"},
        headers=admin_headers,
    )
    assert searched.status_code == 200, searched.text
    assert [item["username"] for item in searched.json()["data"]["items"]] == ["ldap_li"]

    empty_members = await client.get(
        f"/api/v1/dept-managers/{ldap_empty}/users",
        params={"source": "ldap"},
        headers=admin_headers,
    )
    assert empty_members.status_code == 200, empty_members.text
    assert empty_members.json()["data"]["total"] == 0

    node = _find(ldap_tree, "LDAP-RD")
    assigned = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=zhang,
        version=node["version"],
    )
    assert assigned.status_code == 200, assigned.text
    assigned_data = assigned.json()["data"]
    assert assigned_data["manager_id"] == zhang
    assert assigned_data["manager_name"] == "域控张三"
    assert assigned_data["source"] == "ldap"

    dept = await _dept_row(ldap_dept)
    assert dept.manager_id == zhang

    refreshed = _find(await _tree(client, admin_headers, "ldap"), "LDAP-RD")
    assert refreshed["manager_id"] == zhang
    assert refreshed["manager_name"] == "域控张三"
    assert refreshed["version"] == assigned_data["version"]

    member_after = await client.get(
        f"/api/v1/dept-managers/{ldap_dept}/users",
        params={"source": "ldap"},
        headers=admin_headers,
    )
    member_after_data = member_after.json()["data"]
    assert member_after_data["manager"]["id"] == zhang
    assert [item["is_manager"] for item in member_after_data["items"] if item["id"] == zhang] == [
        True
    ]

    # 跨部门选人（钉钉成员）
    dd_member = (await _tree(client, admin_headers, "dingtalk"))[0]
    cross_dept = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=(await client.get(
            f"/api/v1/dept-managers/{dd_member['id']}/users",
            params={"source": "dingtalk"},
            headers=admin_headers,
        )).json()["data"]["items"][0]["id"],
        version=refreshed["version"],
    )
    assert cross_dept.status_code == 400, cross_dept.text
    assert "直属成员" in cross_dept.json()["message"]

    # 同部门但来源不同（local 成员挂在 ldap 部门下）也不允许
    cross_source = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=stray,
        version=refreshed["version"],
    )
    assert cross_source.status_code == 400, cross_source.text
    assert "跨来源" in cross_source.json()["message"]

    # 部门来源与请求来源不一致
    mismatched = await _assign(
        client,
        admin_headers,
        dd_dept,
        source="ldap",
        manager_id=zhang,
        version=1,
    )
    assert mismatched.status_code == 400, mismatched.text
    assert "来源" in mismatched.json()["message"]

    # 乐观锁：使用旧版本号
    stale = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=zhang,
        version=node["version"],
    )
    assert stale.status_code == 409, stale.text

    audits = await _audits("org.dept.manager.assign")
    assert len(audits) == 1
    assert audits[0].before_data == {"manager_id": None, "manager_name": None}
    assert audits[0].after_data == {"manager_id": zhang, "manager_name": "域控张三"}
    assert "LDAP-RD" not in (audits[0].summary or "")
    assert "域控研发部" in (audits[0].summary or "")

    cleared = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=None,
        version=assigned_data["version"],
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["manager_id"] is None
    assert cleared.json()["data"]["manager_name"] is None

    cleared_audits = await _audits("org.dept.manager.clear")
    assert len(cleared_audits) == 1
    assert cleared_audits[0].before_data == {"manager_id": zhang, "manager_name": "域控张三"}

    cleared_tree = _find(await _tree(client, admin_headers, "ldap"), "LDAP-RD")
    assert cleared_tree["manager_id"] is None
    assert cleared_tree["manager_name"] is None


def _node(name: str, approver_type: str) -> dict:
    return {
        "name": name,
        "approver_type": approver_type,
        "manager_level": 1,
        "user_id": None,
        "role_code": None,
        "approve_mode": "OR",
        "fallback_type": "ASSET_ADMIN",
    }


async def test_assigned_manager_drives_approval_flow(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])
    await _ensure_asset("ITAM-DM-0001", "部门负责人审批笔记本")
    first_manager = await _ensure_user("dm_mgr_a", "审批经理一", "EMPLOYEE")
    second_manager = await _ensure_user("dm_mgr_b", "审批经理二", "EMPLOYEE")
    await _ensure_user("dm_emp2", "审批申请员工", "EMPLOYEE")
    it_id = await _dept_id("IT")

    it_node = _find(await _tree(client, admin_headers, "local"), "IT")
    assign_first = await _assign(
        client,
        admin_headers,
        it_id,
        source="local",
        manager_id=first_manager,
        version=it_node["version"],
    )
    assert assign_first.status_code == 200, assign_first.text

    flow = await client.post(
        "/api/v1/approval-flows",
        json={
            "name": "部门负责人联动流程",
            "description": "负责人指定后审批联动",
            "dept_ids": [it_id],
            "nodes": [_node("部门负责人审批", "DEPT_MANAGER")],
        },
        headers=admin_headers,
    )
    assert flow.status_code == 200, flow.text

    emp_headers = await _login_as(client, "dm_emp2")
    payload = {
        "request_type": "REQUISITION",
        "category_id": await _category_id(),
        "reason": "验证负责人联动",
    }
    first_request = await client.post(
        "/api/v1/asset-requests", json=payload, headers=emp_headers
    )
    assert first_request.status_code == 200, first_request.text
    assert first_request.json()["data"]["current_approvers"] == ["审批经理一"]

    assign_second = await _assign(
        client,
        admin_headers,
        it_id,
        source="local",
        manager_id=second_manager,
        version=assign_first.json()["data"]["version"],
    )
    assert assign_second.status_code == 200, assign_second.text

    second_request = await client.post(
        "/api/v1/asset-requests", json=payload, headers=emp_headers
    )
    assert second_request.status_code == 200, second_request.text
    assert second_request.json()["data"]["current_approvers"] == ["审批经理二"]

    # 原「编辑部门 / 组织架构」读取同一份数据
    org_tree = await client.get(
        "/api/v1/departments/tree", params={"source": "local"}, headers=admin_headers
    )
    assert org_tree.status_code == 200, org_tree.text
    org_it = _find(org_tree.json()["data"], "IT")
    assert org_it["manager_id"] == second_manager
    assert org_it["manager_name"] == "审批经理二"

    assert len(await _audits("org.dept.manager.assign")) == 2


async def test_sync_does_not_overwrite_designated_manager(client: AsyncClient):
    admin_headers = auth_headers((await login(client))["access_token"])

    ldap_dept = await _create_dept(
        "域控已指定部", "LDAP-SET", "ldap", ldap_dn="OU=已指定,DC=example,DC=com"
    )
    ldap_empty = await _create_dept(
        "域控待填充部", "LDAP-FILL", "ldap", ldap_dn="OU=待填充,DC=example,DC=com"
    )
    ldap_a = await _create_user(
        "sync_ldap_a",
        "域控指定负责人",
        ldap_dept,
        "ldap",
        ldap_dn="CN=A,OU=已指定,DC=example,DC=com",
    )
    ldap_b = await _create_user(
        "sync_ldap_b",
        "域控同步负责人",
        ldap_dept,
        "ldap",
        ldap_dn="CN=B,OU=已指定,DC=example,DC=com",
    )
    await _create_user(
        "sync_ldap_c",
        "域控填充负责人",
        ldap_empty,
        "ldap",
        ldap_dn="CN=C,OU=待填充,DC=example,DC=com",
    )

    dd_dept = await _create_dept(
        "钉钉已指定部", "DD-SET", "dingtalk", dingtalk_dept_id="dd-set-001"
    )
    dd_empty = await _create_dept(
        "钉钉待填充部", "DD-FILL", "dingtalk", dingtalk_dept_id="dd-fill-001"
    )
    await _create_user(
        "sync_dd_a",
        "钉钉指定负责人",
        dd_dept,
        "dingtalk",
        dingtalk_userid="dd-a",
    )
    await _create_user(
        "sync_dd_b",
        "钉钉同步负责人",
        dd_dept,
        "dingtalk",
        dingtalk_userid="dd-b",
    )
    await _create_user(
        "sync_dd_c",
        "钉钉填充负责人",
        dd_empty,
        "dingtalk",
        dingtalk_userid="dd-c",
    )

    ldap_node = _find(await _tree(client, admin_headers, "ldap"), "LDAP-SET")
    assigned = await _assign(
        client,
        admin_headers,
        ldap_dept,
        source="ldap",
        manager_id=ldap_a,
        version=ldap_node["version"],
    )
    assert assigned.status_code == 200, assigned.text
    dd_node = _find(await _tree(client, admin_headers, "dingtalk"), "DD-SET")
    dd_assigned = await _assign(
        client,
        admin_headers,
        dd_dept,
        source="dingtalk",
        manager_id=await _user_id("sync_dd_a"),
        version=dd_node["version"],
    )
    assert dd_assigned.status_code == 200, dd_assigned.text

    async with AsyncSessionLocal() as session:
        ldap_service = LdapSyncService(session)
        dept_set = await session.get(Dept, ldap_dept)
        dept_fill = await session.get(Dept, ldap_empty)
        counts = {"dept_updated": 0}
        add = lambda *_args, **_kwargs: None  # noqa: E731
        await ldap_service._sync_dept_managers(
            [
                {
                    "dn": "OU=已指定,DC=example,DC=com",
                    "attributes": {"managedBy": "CN=B,OU=已指定,DC=example,DC=com"},
                },
                {
                    "dn": "OU=待填充,DC=example,DC=com",
                    "attributes": {"managedBy": "CN=C,OU=待填充,DC=example,DC=com"},
                },
            ],
            {
                _normalize_dn("OU=已指定,DC=example,DC=com"): dept_set,
                _normalize_dn("OU=待填充,DC=example,DC=com"): dept_fill,
            },
            counts,
            add,
        )
        await session.commit()
        assert counts["dept_updated"] == 1
        await session.refresh(dept_set)
        await session.refresh(dept_fill)
        assert dept_set.manager_id == ldap_a
        assert dept_fill.manager_id == await _user_id("sync_ldap_c")

    async with AsyncSessionLocal() as session:
        dd_service = DingTalkSyncService(session)
        dd_set = await session.get(Dept, dd_dept)
        dd_fill = await session.get(Dept, dd_empty)
        counts = {"dept_updated": 0}
        add = lambda *_args, **_kwargs: None  # noqa: E731
        await dd_service._sync_dept_managers(
            [
                {"dept_id": "dd-set-001", "manager_userids": ["dd-b"]},
                {"dept_id": "dd-fill-001", "manager_userids": ["dd-c"]},
            ],
            {"dd-set-001": dd_set, "dd-fill-001": dd_fill},
            counts,
            add,
        )
        await session.commit()
        assert counts["dept_updated"] == 1
        await session.refresh(dd_set)
        await session.refresh(dd_fill)
        assert dd_set.manager_id == await _user_id("sync_dd_a")
        assert dd_fill.manager_id == await _user_id("sync_dd_c")


async def _user_id(username: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            (
                await session.execute(select(User.id).where(User.username == username))
            ).scalar_one()
        )
