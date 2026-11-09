"""钉钉服务端 OpenAPI 客户端（gettoken、通讯录、审批实例）。

只读为主：拉取名册、查询审批状态；写操作仅限创建审批实例。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.exceptions import BizError

logger = logging.getLogger("itam.dingtalk")

GETTOKEN_URL = "https://oapi.dingtalk.com/gettoken"
LISTS_SUB_DEPT_URL = "https://oapi.dingtalk.com/topapi/v2/department/listsub"
GET_DEPT_URL = "https://oapi.dingtalk.com/topapi/v2/department/get"
LIST_DEPT_USERS_URL = "https://oapi.dingtalk.com/topapi/v2/user/list"
GET_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/get"
CREATE_INSTANCE_URL = "https://oapi.dingtalk.com/topapi/processinstance/create"
GET_INSTANCE_URL = "https://oapi.dingtalk.com/topapi/processinstance/get"

_TOKEN_INVALID_CODES = {40014, 42001, 42004, 88}

_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = asyncio.Lock()

_semaphore = asyncio.Semaphore(8)


def _check(response: dict[str, Any], context: str) -> dict[str, Any]:
    errcode = response.get("errcode")
    if errcode != 0:
        errmsg = response.get("errmsg") or f"errcode={errcode}"
        raise BizError(f"钉钉{context}失败：{errmsg}")
    return response


async def _post_json(url: str, payload: dict[str, Any], context: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return _check(resp.json(), context)
    except BizError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise BizError(f"钉钉{context}请求失败：{exc}") from exc


async def get_access_token(app_key: str, app_secret: str, *, force: bool = False) -> str:
    """获取并缓存 access_token（有效期 7200 秒，提前 5 分钟过期）。"""
    now = time.time()
    cached = _token_cache.get(app_key)
    if not force and cached is not None:
        token, expires_at = cached
        if now < expires_at:
            return token
    async with _token_lock:
        cached = _token_cache.get(app_key)
        if not force and cached is not None:
            token, expires_at = cached
            if now < expires_at:
                return token
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(
                    GETTOKEN_URL,
                    params={"appkey": app_key, "appsecret": app_secret},
                )
                resp.raise_for_status()
                data = _check(resp.json(), "获取 access_token")
            except BizError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise BizError(f"钉钉获取 access_token 请求失败：{exc}") from exc
        token = str(data.get("access_token") or "")
        if not token:
            raise BizError("钉钉获取 access_token 返回为空")
        _token_cache[app_key] = (token, now + max(int(data.get("expires_in", 7200)) - 300, 60))
        return token


def invalidate_token(app_key: str) -> None:
    _token_cache.pop(app_key, None)


async def _call(
    app_key: str,
    app_secret: str,
    url: str,
    payload: dict[str, Any],
    context: str,
) -> dict[str, Any]:
    token = await get_access_token(app_key, app_secret)
    try:
        return await _post_json(f"{url}?access_token={token}", payload, context)
    except BizError as exc:
        message = str(exc)
        if any(str(code) in message for code in _TOKEN_INVALID_CODES):
            invalidate_token(app_key)
            token = await get_access_token(app_key, app_secret, force=True)
            return await _post_json(f"{url}?access_token={token}", payload, context)
        raise


async def list_sub_departments(
    app_key: str, app_secret: str, dept_id: int
) -> list[dict[str, Any]]:
    data = await _call(
        app_key, app_secret, LISTS_SUB_DEPT_URL, {"dept_id": dept_id}, "查询子部门"
    )
    return list(data.get("result") or [])


async def get_department(
    app_key: str, app_secret: str, dept_id: int
) -> dict[str, Any]:
    data = await _call(
        app_key,
        app_secret,
        GET_DEPT_URL,
        {"dept_id": dept_id, "language": "zh_CN"},
        "查询部门详情",
    )
    return dict(data.get("result") or {})


async def list_dept_user_ids(
    app_key: str, app_secret: str, dept_id: int
) -> list[str]:
    user_ids: list[str] = []
    cursor = 0
    while True:
        data = await _call(
            app_key,
            app_secret,
            LIST_DEPT_USERS_URL,
            {"dept_id": dept_id, "cursor": cursor, "size": 100},
            "查询部门成员",
        )
        result = data.get("result") or {}
        for item in result.get("list") or []:
            userid = str(item.get("userid") or "")
            if userid:
                user_ids.append(userid)
        if not result.get("has_more"):
            break
        cursor = int(result.get("next_cursor") or 0)
    return user_ids


async def get_user(
    app_key: str, app_secret: str, userid: str
) -> dict[str, Any]:
    data = await _call(
        app_key,
        app_secret,
        GET_USER_URL,
        {"userid": userid, "language": "zh_CN"},
        "查询成员详情",
    )
    return dict(data.get("result") or {})


async def fetch_users(
    app_key: str, app_secret: str, user_ids: list[str]
) -> list[dict[str, Any]]:
    async def fetch_one(userid: str) -> dict[str, Any]:
        async with _semaphore:
            return await get_user(app_key, app_secret, userid)

    results = await asyncio.gather(*(fetch_one(uid) for uid in user_ids))
    return [item for item in results if item.get("userid")]


@dataclass(slots=True)
class RosterDept:
    dept_id: str
    name: str
    parent_id: str | None


async def fetch_dept_managers(
    app_key: str, app_secret: str, dept_ids: list[int]
) -> dict[str, list[str]]:
    """批量拉取部门负责人（仅 department/get 返回 dept_manager_userid_list）。"""

    async def fetch_one(dept_id: int) -> tuple[str, list[str]]:
        async with _semaphore:
            try:
                detail = await get_department(app_key, app_secret, dept_id)
            except BizError:
                # 负责人信息为辅助数据，单个部门失败不中断整次同步
                return str(dept_id), []
        managers = [
            str(uid) for uid in (detail.get("dept_manager_userid_list") or []) if uid
        ]
        return str(dept_id), managers

    results = await asyncio.gather(*(fetch_one(did) for did in dept_ids))
    return {key: value for key, value in results}


async def fetch_dept_tree(
    app_key: str, app_secret: str, root_dept_id: int = 1
) -> list[RosterDept]:
    """递归拉取部门树（不含根节点自身），按层级升序返回。"""
    collected: list[RosterDept] = []

    async def walk(dept_id: int, parent_key: str | None) -> None:
        subs = await list_sub_departments(app_key, app_secret, dept_id)
        for sub in subs:
            key = str(sub.get("dept_id") or "")
            name = str(sub.get("name") or "") or f"部门{key}"
            if not key:
                continue
            collected.append(RosterDept(dept_id=key, name=name, parent_id=parent_key))
        for sub in subs:
            key = str(sub.get("dept_id") or "")
            if key:
                await walk(int(key), key)

    await walk(root_dept_id, None)
    return collected


@dataclass(slots=True)
class ApprovalInstanceCreate:
    process_code: str
    originator_userid: str
    title: str
    form_values: list[dict[str, str]]


async def create_process_instance(
    app_key: str,
    app_secret: str,
    *,
    agent_id: int | None,
    request: ApprovalInstanceCreate,
) -> str:
    payload: dict[str, Any] = {
        "process_code": request.process_code,
        "originator_user_id": request.originator_userid,
        "title": request.title,
        "form_component_values": [
            {"name": item["name"], "value": item["value"]} for item in request.form_values
        ],
    }
    if agent_id:
        payload["agent_id"] = agent_id
    data = await _call(
        app_key, app_secret, CREATE_INSTANCE_URL, payload, "创建审批实例"
    )
    instance_id = str(data.get("process_instance_id") or "")
    if not instance_id:
        raise BizError("钉钉创建审批实例未返回实例 ID")
    return instance_id


async def get_process_instance(
    app_key: str, app_secret: str, instance_id: str
) -> dict[str, Any]:
    data = await _call(
        app_key,
        app_secret,
        GET_INSTANCE_URL,
        {"process_instance_id": instance_id},
        "查询审批实例",
    )
    return dict(data.get("process_instance") or {})
