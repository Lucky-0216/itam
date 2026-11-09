from __future__ import annotations

import hashlib
import logging
import re
import secrets as pysecrets
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BizError, ConflictError, NotFoundError
from app.core.permissions import SUPER_ADMIN_ROLE
from app.core.security import hash_password
from app.core.secrets import decrypt_secret, encrypt_secret
from app.models import (
    Dept,
    DingTalkConfig,
    DingTalkSyncLog,
    OrgSyncPolicy,
    Role,
    User,
)
from app.models.base import now_cst
from app.repositories.user_repo import UserRepository
from app.schemas.dingtalk import (
    DingTalkConfigOut,
    DingTalkConfigPayload,
    DingTalkOptionsOut,
    DingTalkSyncLogOut,
    DingTalkTestPayload,
    DingTalkTestResult,
)
from app.services import dingtalk_client
from app.services.audit_service import AuditService
from app.services.org_policy_service import (
    OrgSyncPolicyService,
    can_disable_dept,
    can_disable_user,
    mutation_level,
)
from app.services.permission_service import AuthContext
from app.services.txn import commit_or_conflict

logger = logging.getLogger("itam.dingtalk")

_MANUAL = "MANUAL"
_SCHEDULED = "SCHEDULED"
_RUNNING_STALE_SECONDS = 1800
_MAX_DETAILS = 300
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
_TEMP_USER_RE = re.compile(r"^dt_[a-z0-9_-]{1,60}$")


def _normalize_username(raw: str, fallback: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[^a-z0-9._-]", ".", value)
    value = re.sub(r"\.{2,}", ".", value).strip("._-")
    if len(value) < 3:
        value = fallback.lower()
    if len(value) > 50:
        value = value[:50].rstrip("._-")
    if not _USERNAME_RE.fullmatch(value):
        digest = hashlib.sha1(fallback.lower().encode("utf-8")).hexdigest()
        value = f"dt.{digest[:16]}"
    return value


def due_for_sync(config: DingTalkConfig, now) -> bool:
    if not config.enabled:
        return False
    if config.last_sync_status == "RUNNING":
        return bool(
            config.last_sync_at is not None
            and (now - config.last_sync_at).total_seconds() >= _RUNNING_STALE_SECONDS
        )
    if config.last_sync_at is None:
        return True
    return (now - config.last_sync_at).total_seconds() >= max(
        config.sync_interval_minutes, 5
    ) * 60


class DingTalkSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ---------- 配置 ----------

    async def get_config(self) -> DingTalkConfig | None:
        return (
            await self.session.execute(
                select(DingTalkConfig).order_by(DingTalkConfig.id).limit(1)
            )
        ).scalar_one_or_none()

    async def get_config_out(self) -> DingTalkConfigOut:
        config = await self.get_config()
        if config is None:
            return DingTalkConfigOut(
                id=0,
                enabled=False,
                corp_id="",
                app_key="",
                has_secret=False,
                agent_id=None,
                default_role_id=None,
                default_role_name=None,
                root_dept_id=None,
                root_dept_name=None,
                sync_interval_minutes=120,
                disable_on_leave=True,
                match_existing=True,
                approval_enabled=False,
                version=1,
            )
        return await self._serialize_config(config)

    async def _serialize_config(self, config: DingTalkConfig) -> DingTalkConfigOut:
        role = (
            await self.session.get(Role, config.default_role_id)
            if config.default_role_id
            else None
        )
        dept = (
            await self.session.get(Dept, config.root_dept_id)
            if config.root_dept_id
            else None
        )
        return DingTalkConfigOut(
            id=config.id,
            enabled=config.enabled,
            corp_id=config.corp_id,
            app_key=config.app_key,
            has_secret=bool(config.app_secret_encrypted),
            agent_id=config.agent_id,
            default_role_id=config.default_role_id,
            default_role_name=role.name if role else None,
            root_dept_id=config.root_dept_id,
            root_dept_name=dept.name if dept else None,
            sync_interval_minutes=config.sync_interval_minutes,
            disable_on_leave=config.disable_on_leave,
            match_existing=config.match_existing,
            approval_enabled=config.approval_enabled,
            requisition_process_code=config.requisition_process_code,
            borrow_process_code=config.borrow_process_code,
            transfer_process_code=config.transfer_process_code,
            has_callback_token=bool(config.callback_token_encrypted),
            has_callback_aes_key=bool(config.callback_aes_key_encrypted),
            last_sync_at=config.last_sync_at,
            last_sync_status=config.last_sync_status,
            last_sync_message=config.last_sync_message,
            last_test_at=config.last_test_at,
            last_test_status=config.last_test_status,
            last_test_message=config.last_test_message,
            version=config.version,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    def _config_snapshot(self, config: DingTalkConfig | None) -> dict | None:
        if config is None:
            return None
        return {
            "enabled": config.enabled,
            "corp_id": config.corp_id,
            "app_key": config.app_key,
            "agent_id": config.agent_id,
            "default_role_id": config.default_role_id,
            "root_dept_id": config.root_dept_id,
            "sync_interval_minutes": config.sync_interval_minutes,
            "disable_on_leave": config.disable_on_leave,
            "match_existing": config.match_existing,
            "approval_enabled": config.approval_enabled,
            "requisition_process_code": config.requisition_process_code,
            "borrow_process_code": config.borrow_process_code,
            "transfer_process_code": config.transfer_process_code,
        }

    async def save_config(
        self,
        payload: DingTalkConfigPayload,
        context: AuthContext,
    ) -> DingTalkConfigOut:
        version = getattr(payload, "version", None)
        config = await self.get_config()
        if config is not None and version is not None and config.version != version:
            raise ConflictError("钉钉配置已被他人修改，请刷新后重试")

        if payload.default_role_id is not None:
            role = await self.session.get(Role, payload.default_role_id)
            if role is None or role.status != 1:
                raise BizError("默认角色不存在或已停用")
        if payload.root_dept_id is not None:
            dept = await self.session.get(Dept, payload.root_dept_id)
            if dept is None:
                raise BizError("钉钉组织根部门不存在")
        if payload.enabled and not payload.app_secret and not (
            config and config.app_secret_encrypted
        ):
            raise BizError("启用同步前请填写 AppSecret")

        before = self._config_snapshot(config)
        if config is None:
            config = DingTalkConfig()
            self.session.add(config)

        config.enabled = payload.enabled
        config.corp_id = payload.corp_id
        config.app_key = payload.app_key
        if payload.app_secret:
            config.app_secret_encrypted = encrypt_secret(payload.app_secret)
        config.agent_id = payload.agent_id
        config.default_role_id = payload.default_role_id
        config.root_dept_id = payload.root_dept_id
        config.sync_interval_minutes = payload.sync_interval_minutes
        config.disable_on_leave = payload.disable_on_leave
        config.match_existing = payload.match_existing
        config.approval_enabled = payload.approval_enabled
        config.requisition_process_code = payload.requisition_process_code
        config.borrow_process_code = payload.borrow_process_code
        config.transfer_process_code = payload.transfer_process_code
        if payload.callback_token:
            config.callback_token_encrypted = encrypt_secret(payload.callback_token)
        if payload.callback_aes_key:
            config.callback_aes_key_encrypted = encrypt_secret(payload.callback_aes_key)

        await self.session.flush()
        await self.audit.record(
            action="dingtalk.config.save",
            module="钉钉同步",
            summary="保存钉钉同步配置",
            actor=context.user,
            resource_type="dingtalk_config",
            resource_id=config.id,
            before=before,
            after=self._config_snapshot(config),
        )
        await commit_or_conflict(self.session)
        return await self._serialize_config(config)

    # ---------- 连接测试 ----------

    async def test_config(
        self,
        payload: DingTalkTestPayload,
        context: AuthContext,
    ) -> DingTalkTestResult:
        config = await self.get_config()
        secret = payload.app_secret
        if not secret and config and config.app_secret_encrypted:
            try:
                secret = decrypt_secret(config.app_secret_encrypted)
            except BizError:
                secret = None
        if not secret:
            raise BizError("请填写 AppSecret 后再测试")
        if not payload.corp_id or not payload.app_key:
            raise BizError("请填写 CorpId 与 AppKey 后再测试")

        started = time.monotonic()
        try:
            tree = await dingtalk_client.fetch_dept_tree(
                payload.app_key, secret, root_dept_id=1
            )
            user_sample = 0
            for item in tree[:3]:
                ids = await dingtalk_client.list_dept_user_ids(
                    payload.app_key, secret, int(item.dept_id)
                )
                user_sample += len(ids)
            message = f"连接成功：通讯录共 {len(tree)} 个部门，抽查 3 个部门共 {user_sample} 名成员"
            result = DingTalkTestResult(
                success=True,
                message=message,
                corp_id=payload.corp_id,
                dept_sample=len(tree),
                user_sample=user_sample,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                checked_at=now_cst(),
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            message = exc.message if isinstance(exc, BizError) else str(exc)
            result = DingTalkTestResult(
                success=False,
                message=message or "连接失败",
                corp_id=payload.corp_id,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                checked_at=now_cst(),
            )

        checked_at = now_cst()
        if config is not None:
            config.last_test_at = checked_at
            config.last_test_status = "SUCCESS" if result.success else "FAILED"
            config.last_test_message = result.message[:1000]
        await self.audit.record(
            action="dingtalk.config.test",
            module="钉钉同步",
            summary="测试钉钉通讯录连接" + ("成功" if result.success else "失败"),
            actor=context.user,
            resource_type="dingtalk_config",
            resource_id=config.id if config else None,
            status="SUCCESS" if result.success else "FAILED",
            after={"message": result.message},
        )
        await commit_or_conflict(self.session)
        return result

    # ---------- 选项 ----------

    async def options(self) -> DingTalkOptionsOut:
        roles = list(
            (
                await self.session.execute(
                    select(Role).where(Role.status == 1).order_by(Role.sort, Role.id)
                )
            )
            .scalars()
            .all()
        )
        depts = list(
            (
                await self.session.execute(
                    select(Dept).order_by(Dept.level, Dept.sort, Dept.id)
                )
            )
            .scalars()
            .all()
        )
        dingtalk_depts = int(
            await self.session.scalar(
                select(func.count(Dept.id)).where(Dept.source == "dingtalk")
            )
            or 0
        )
        dingtalk_users = int(
            await self.session.scalar(
                select(func.count(User.id)).where(
                    User.source == "dingtalk", User.deleted_at.is_(None)
                )
            )
            or 0
        )
        return DingTalkOptionsOut(
            roles=[
                {"id": role.id, "code": role.code, "name": role.name} for role in roles
            ],
            depts=[
                {
                    "id": dept.id,
                    "parent_id": dept.parent_id,
                    "name": dept.name,
                    "level": dept.level,
                    "status": dept.status,
                }
                for dept in depts
            ],
            dingtalk_dept_count=dingtalk_depts,
            dingtalk_user_count=dingtalk_users,
        )

    # ---------- 同步日志 ----------

    async def list_logs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> tuple[list[DingTalkSyncLogOut], int]:
        conditions = []
        if status:
            conditions.append(DingTalkSyncLog.status == status)
        total = int(
            await self.session.scalar(
                select(func.count(DingTalkSyncLog.id)).where(*conditions)
            )
            or 0
        )
        logs = list(
            (
                await self.session.execute(
                    select(DingTalkSyncLog)
                    .where(*conditions)
                    .order_by(DingTalkSyncLog.started_at.desc(), DingTalkSyncLog.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [DingTalkSyncLogOut.model_validate(log) for log in logs], total

    async def get_log(self, log_id: int) -> DingTalkSyncLogOut:
        log = await self.session.get(DingTalkSyncLog, log_id)
        if log is None:
            raise NotFoundError("同步日志不存在")
        return DingTalkSyncLogOut.model_validate(log)

    # ---------- 同步 ----------

    async def run_sync(
        self,
        *,
        config_id: int | None = None,
        trigger_type: str = _MANUAL,
        operator_id: int | None = None,
        operator_name: str | None = None,
    ) -> DingTalkSyncLog:
        config = (
            await self.session.get(DingTalkConfig, config_id)
            if config_id is not None
            else await self.get_config()
        )
        if config is None:
            raise NotFoundError("尚未配置钉钉同步")
        if not config.enabled:
            raise BizError("钉钉同步未启用")
        now = now_cst()
        if (
            config.last_sync_status == "RUNNING"
            and config.last_sync_at is not None
            and (now - config.last_sync_at).total_seconds() < _RUNNING_STALE_SECONDS
        ):
            raise BizError("已有同步任务正在执行，请稍后刷新日志")

        secret = decrypt_secret(config.app_secret_encrypted)
        log = DingTalkSyncLog(
            config_id=config.id,
            trigger_type=trigger_type,
            status="RUNNING",
            started_at=now,
            operator_id=operator_id,
            operator_name=operator_name
            or ("系统计划任务" if trigger_type == _SCHEDULED else None),
        )
        self.session.add(log)
        config.last_sync_status = "RUNNING"
        config.last_sync_at = now
        config.last_sync_message = "同步任务执行中..."
        await self.session.commit()
        log_id = log.id
        config_pk = config.id
        started = time.monotonic()

        try:
            dept_entries, user_entries = await self._fetch_roster(
                config.app_key, secret
            )
            counts, details, errors = await self._apply_roster(
                config, dept_entries, user_entries
            )
            finished = now_cst()
            duration_ms = int((time.monotonic() - started) * 1000)
            status = "PARTIAL" if errors else "SUCCESS"
            message = (
                f"同步完成：部门 +{counts['dept_created']}/~{counts['dept_updated']}，"
                f"用户 +{counts['user_created']}/~{counts['user_updated']}"
                f"/匹配{counts['user_matched']}/停用{counts['user_disabled']}"
            )
            if errors:
                message += f"，{errors} 项异常"
            log = await self.session.get(DingTalkSyncLog, log_id)
            log.status = status
            log.finished_at = finished
            log.duration_ms = duration_ms
            log.error_count = errors
            log.message = message
            log.details = details
            for key, value in counts.items():
                setattr(log, key, value)
            config = await self.session.get(DingTalkConfig, config_pk)
            if config is not None:
                config.last_sync_at = finished
                config.last_sync_status = status
                config.last_sync_message = message
            await self.audit.record(
                action="dingtalk.roster.sync",
                module="钉钉同步",
                summary=message,
                actor_id=operator_id,
                actor_name=operator_name,
                resource_type="dingtalk_config",
                resource_id=config.id if config is not None else config_pk,
                status="SUCCESS" if status == "SUCCESS" else "FAILED",
                after={**counts, "trigger": trigger_type, "duration_ms": duration_ms},
            )
            await self.session.commit()
            return log
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded
            logger.exception("DingTalk roster sync failed")
            await self.session.rollback()
            return await self._mark_failed(
                log_id=log_id,
                config_id=config_pk,
                trigger_type=trigger_type,
                operator_id=operator_id,
                operator_name=operator_name,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=exc,
            )

    async def _mark_failed(
        self,
        *,
        log_id: int,
        config_id: int,
        trigger_type: str,
        operator_id: int | None,
        operator_name: str | None,
        duration_ms: int,
        error: Exception,
    ) -> DingTalkSyncLog:
        finished = now_cst()
        message = error.message if isinstance(error, BizError) else str(error)
        log = await self.session.get(DingTalkSyncLog, log_id)
        if log is not None:
            log.status = "FAILED"
            log.finished_at = finished
            log.duration_ms = duration_ms
            log.error_count = 1
            log.message = "同步失败"
            log.error_message = message[:5000]
        config = await self.session.get(DingTalkConfig, config_id)
        if config is not None:
            config.last_sync_at = finished
            config.last_sync_status = "FAILED"
            config.last_sync_message = "同步失败"
        await self.audit.record(
            action="dingtalk.roster.sync",
            module="钉钉同步",
            summary=f"同步失败：{message[:200]}",
            actor_id=operator_id,
            actor_name=operator_name,
            resource_type="dingtalk_config",
            resource_id=config_id,
            status="FAILED",
            after={"trigger": trigger_type, "duration_ms": duration_ms},
        )
        await self.session.commit()
        return log

    # ---------- 拉取名册 ----------

    async def _fetch_roster(
        self, app_key: str, app_secret: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tree = await dingtalk_client.fetch_dept_tree(app_key, app_secret, root_dept_id=1)
        dept_ids = {int(item.dept_id) for item in tree}
        managers = await dingtalk_client.fetch_dept_managers(
            app_key, app_secret, sorted(dept_ids)
        )
        user_ids: list[str] = []
        for dept_id in dept_ids:
            user_ids.extend(
                await dingtalk_client.list_dept_user_ids(app_key, app_secret, dept_id)
            )
        user_ids = list(dict.fromkeys(user_ids))
        users = await dingtalk_client.fetch_users(app_key, app_secret, user_ids)
        return (
            [
                {
                    "dept_id": item.dept_id,
                    "name": item.name,
                    "parent_id": item.parent_id,
                    "manager_userids": managers.get(item.dept_id) or [],
                }
                for item in tree
            ],
            users,
        )

    # ---------- 应用名册 ----------

    async def _apply_roster(
        self,
        config: DingTalkConfig,
        dept_entries: list[dict[str, Any]],
        user_entries: list[dict[str, Any]],
    ) -> tuple[dict[str, int], list[dict[str, str]], int]:
        counts = {
            "dept_total": 0,
            "dept_created": 0,
            "dept_updated": 0,
            "dept_skipped": 0,
            "user_total": 0,
            "user_created": 0,
            "user_updated": 0,
            "user_matched": 0,
            "user_disabled": 0,
            "user_skipped": 0,
        }
        details: list[dict[str, str]] = []
        truncated = False

        def add(level: str, message: str) -> None:
            nonlocal truncated
            if len(details) < _MAX_DETAILS:
                details.append({"level": level, "message": message})
            elif not truncated:
                truncated = True
                details.append({"level": "warning", "message": "日志条目过多，后续明细已省略"})

        policy = await OrgSyncPolicyService(self.session).get_policy()
        dept_by_key = await self._sync_departments(config, policy, dept_entries, counts, add)
        await self._sync_users(config, policy, user_entries, dept_by_key, counts, add)
        await self.session.flush()
        await self._sync_dept_managers(dept_entries, dept_by_key, counts, add)
        await self.session.flush()
        await self._rebuild_dept_paths()
        errors = sum(1 for item in details if item["level"] == "error")
        return counts, details, errors

    async def _sync_departments(
        self,
        config: DingTalkConfig,
        policy: OrgSyncPolicy,
        entries: list[dict[str, Any]],
        counts: dict[str, int],
        add,
    ) -> dict[str, Dept]:
        counts["dept_total"] = len(entries)
        existing = list((await self.session.execute(select(Dept))).scalars().all())
        by_key: dict[str, Dept] = {
            dept.dingtalk_dept_id: dept
            for dept in existing
            if dept.dingtalk_dept_id
        }
        codes = {dept.code for dept in existing}
        root_dept = (
            await self.session.get(Dept, config.root_dept_id)
            if config.root_dept_id
            else None
        )

        parent_map = {str(item["dept_id"]): item.get("parent_id") for item in entries}

        def depth(key: str) -> int:
            level = 0
            seen: set[str] = set()
            current: str | None = key
            while current and current not in seen:
                seen.add(current)
                current = parent_map.get(current)
                level += 1
            return level

        ordered = sorted(entries, key=lambda item: depth(str(item["dept_id"])))
        seen_keys: set[str] = set()
        for entry in ordered:
            key = str(entry["dept_id"])
            name = str(entry.get("name") or "") or f"部门{key}"
            seen_keys.add(key)
            parent_key = entry.get("parent_id")
            parent_dept: Dept | None = None
            if parent_key:
                parent_dept = by_key.get(str(parent_key))
            if parent_dept is None:
                parent_dept = root_dept
            if parent_dept is not None and parent_dept.id is not None:
                target_parent_id = parent_dept.id
            else:
                target_parent_id = None

            dept = by_key.get(key)
            if dept is None:
                dept = Dept(
                    parent_id=target_parent_id,
                    name=name,
                    code=self._unique_dept_code(key, codes),
                    path="",
                    level=1,
                    sort=0,
                    status=1,
                    source="dingtalk",
                    dingtalk_dept_id=key,
                    dingtalk_synced_at=now_cst(),
                )
                codes.add(dept.code)
                self.session.add(dept)
                await self.session.flush()
                by_key[key] = dept
                counts["dept_created"] += 1
                add("info", f"新增部门：{name}")
                continue

            if target_parent_id == dept.id:
                target_parent_id = None
            level = mutation_level(policy, "dingtalk", dept.source)
            changed = False
            if level == "overwrite":
                if dept.name != name:
                    dept.name = name
                    changed = True
                if dept.parent_id != target_parent_id:
                    dept.parent_id = target_parent_id
                    changed = True
                if dept.status != 1:
                    dept.status = 1
                    changed = True
                if dept.source != "dingtalk":
                    dept.source = "dingtalk"
                    changed = True
            elif level == "fill_empty":
                if dept.parent_id is None and target_parent_id is not None:
                    dept.parent_id = target_parent_id
                    changed = True
            else:
                counts["dept_skipped"] += 1
                add("info", f"按同步策略跳过钉钉部门更新：{dept.name}")
            dept.dingtalk_synced_at = now_cst()
            if changed:
                counts["dept_updated"] += 1
                add("info", f"更新部门：{name}")

        for dept in by_key.values():
            if dept.dingtalk_dept_id and dept.dingtalk_dept_id not in seen_keys:
                if not can_disable_dept(policy, "dingtalk", dept):
                    continue
                if dept.status != 0:
                    dept.status = 0
                    counts["dept_updated"] += 1
                    add("warning", f"部门在钉钉已不存在，已停用：{dept.name}")
        return by_key

    @staticmethod
    def _unique_dept_code(key: str, codes: set[str]) -> str:
        candidate = f"DT-{key}"
        if candidate not in codes:
            return candidate
        counter = 2
        while f"{candidate}-{counter}" in codes:
            counter += 1
        return f"{candidate}-{counter}"

    async def _default_role(self, config: DingTalkConfig) -> Role | None:
        if config.default_role_id:
            role = await self.session.get(Role, config.default_role_id)
            if role is not None and role.status == 1:
                return role
        return (
            await self.session.execute(
                select(Role).where(Role.code == "EMPLOYEE", Role.status == 1).limit(1)
            )
        ).scalar_one_or_none()

    async def _is_last_super_admin(self, user: User) -> bool:
        if not any(role.code == SUPER_ADMIN_ROLE for role in user.roles):
            return False
        remaining = await UserRepository(self.session).count_active_super_admins(
            exclude_user_id=user.id
        )
        return remaining == 0

    @staticmethod
    def _claim_unique(
        mapping: dict[str, User],
        value: str | None,
        *,
        current: User | None,
    ) -> tuple[str | None, bool]:
        if not value:
            return None, False
        key = value.lower() if "@" in value else value
        owner = mapping.get(key)
        if owner is None or (current is not None and owner is current):
            return value, False
        return None, True

    async def _sync_users(
        self,
        config: DingTalkConfig,
        policy: OrgSyncPolicy,
        entries: list[dict[str, Any]],
        dept_by_key: dict[str, Dept],
        counts: dict[str, int],
        add,
    ) -> None:
        users = list(
            (
                await self.session.execute(
                    select(User).options(selectinload(User.roles))
                )
            )
            .scalars()
            .all()
        )
        by_userid: dict[str, User] = {
            user.dingtalk_userid: user for user in users if user.dingtalk_userid
        }
        username_map: dict[str, User] = {user.username: user for user in users}
        email_map: dict[str, User] = {
            (user.email or "").lower(): user for user in users if user.email
        }
        phone_map: dict[str, User] = {user.phone: user for user in users if user.phone}
        employee_map: dict[str, User] = {
            user.employee_no: user for user in users if user.employee_no
        }
        disable_candidates = [
            user
            for user in users
            if user.deleted_at is None and can_disable_user(policy, "dingtalk", user)
        ]
        if disable_candidates and not entries:
            raise BizError("钉钉未返回任何成员，已中止同步以避免误停用账号")

        role = await self._default_role(config)
        role_warning = False
        seen_ids: set[int] = set()
        counts["user_total"] = len(entries)
        now = now_cst()
        root_dept = (
            await self.session.get(Dept, config.root_dept_id)
            if config.root_dept_id
            else None
        )

        for entry in entries:
            userid = str(entry.get("userid") or "").strip()
            if not userid:
                counts["user_skipped"] += 1
                add("warning", "跳过无 userid 的成员记录")
                continue
            name = str(entry.get("name") or "").strip()
            mobile = str(entry.get("mobile") or "").strip() or None
            email = str(entry.get("email") or "").strip() or None
            avatar = str(entry.get("avatar") or "").strip() or None
            position = str(entry.get("position") or "").strip() or None
            job_number = str(entry.get("job_number") or "").strip() or None
            active = entry.get("active")
            target_status = 1 if active is not False else 0
            dept_id_list = entry.get("dept_id_list") or []

            existing = by_userid.get(userid)
            adopted_temp = False
            if existing is None and config.match_existing and mobile:
                existing = phone_map.get(mobile)
            if existing is None and config.match_existing and email:
                existing = email_map.get((email or "").lower())
            if existing is None:
                temp_name = f"dt_{userid}".lower()
                temp_user = username_map.get(temp_name)
                if temp_user is not None and temp_user.source == "local" and _TEMP_USER_RE.fullmatch(temp_user.username or ""):
                    existing = temp_user
                    adopted_temp = True

            dept_id = None
            for raw_id in dept_id_list:
                dept = dept_by_key.get(str(raw_id))
                if dept is not None:
                    dept_id = dept.id
                    break
            if dept_id is None and root_dept is not None:
                dept_id = root_dept.id

            if existing is not None:
                seen_ids.add(existing.id)
                if existing.source == "dingtalk" or adopted_temp:
                    changed: list[str] = []
                    if name and existing.real_name != name:
                        existing.real_name = name
                        changed.append("姓名")
                    if mobile and existing.phone != mobile:
                        existing.phone = mobile
                        changed.append("电话")
                    if email:
                        resolved_email, conflict = self._claim_unique(
                            email_map, email, current=existing
                        )
                        if resolved_email and (existing.email or "").lower() != resolved_email.lower():
                            existing.email = resolved_email.lower()
                            changed.append("邮箱")
                        if conflict:
                            add("warning", f"{existing.username} 的新邮箱 {email} 已被其他账号占用，已保留原邮箱")
                    if job_number:
                        resolved_employee, conflict = self._claim_unique(
                            employee_map, job_number, current=existing
                        )
                        if resolved_employee and existing.employee_no != resolved_employee:
                            existing.employee_no = resolved_employee
                            changed.append("工号")
                        if conflict:
                            add("warning", f"{existing.username} 的新工号 {job_number} 已被其他账号占用，已保留原工号")
                    if avatar and existing.avatar != avatar:
                        existing.avatar = avatar
                        changed.append("头像")
                    if position and existing.position != position:
                        existing.position = position
                        changed.append("职位")
                    if existing.dept_id != dept_id:
                        existing.dept_id = dept_id
                        changed.append("部门")
                    if existing.status != target_status:
                        if target_status == 0 and await self._is_last_super_admin(existing):
                            counts["user_skipped"] += 1
                            add("error", f"{existing.username} 是最后一名超级管理员，已跳过停用以保护系统")
                        else:
                            existing.status = target_status
                            if target_status == 0:
                                existing.token_version += 1
                                counts["user_disabled"] += 1
                                add("warning", f"钉钉成员已离职，系统账号同步停用：{existing.username}")
                            changed.append("状态")
                    if existing.source != "dingtalk":
                        existing.source = "dingtalk"
                        changed.append("来源")
                    if existing.must_change_password:
                        existing.must_change_password = False
                    if existing.dingtalk_userid != userid:
                        existing.dingtalk_userid = userid
                    existing.dingtalk_synced_at = now
                    if adopted_temp:
                        counts["user_matched"] += 1
                        add("info", f"接管导入临时账号：{existing.username} → 钉钉成员 {name}")
                    elif changed:
                        counts["user_updated"] += 1
                        add("info", f"更新钉钉用户：{name}（{'+'.join(changed)}）")
                    if adopted_temp and existing.username in username_map:
                        pass
                    continue

                if not config.match_existing:
                    counts["user_skipped"] += 1
                    add("warning", f"{existing.username} 已匹配到钉钉成员但未开启匹配补全，跳过")
                    continue
                level = mutation_level(policy, "dingtalk", existing.source)
                if existing.dingtalk_userid != userid:
                    existing.dingtalk_userid = userid
                existing.dingtalk_synced_at = now
                if level == "skip":
                    counts["user_skipped"] += 1
                    add("info", f"按同步策略跳过钉钉用户更新：{existing.username}")
                    continue
                changed: list[str] = []
                if level == "fill_empty":
                    if not existing.real_name and name:
                        existing.real_name = name
                        changed.append("姓名")
                    if not existing.phone and mobile:
                        existing.phone = mobile
                        changed.append("电话")
                    if not existing.avatar and avatar:
                        existing.avatar = avatar
                        changed.append("头像")
                    if not existing.email and email:
                        resolved_email, conflict = self._claim_unique(
                            email_map, email, current=existing
                        )
                        if resolved_email:
                            existing.email = resolved_email.lower()
                            changed.append("邮箱")
                        if conflict:
                            add("warning", f"{existing.username} 的新邮箱 {email} 已被其他账号占用，已保留原邮箱")
                    if not existing.employee_no and job_number:
                        resolved_employee, conflict = self._claim_unique(
                            employee_map, job_number, current=existing
                        )
                        if resolved_employee:
                            existing.employee_no = resolved_employee
                            changed.append("工号")
                        if conflict:
                            add("warning", f"{existing.username} 的新工号 {job_number} 已被其他账号占用，已保留原工号")
                else:
                    if name and existing.real_name != name:
                        existing.real_name = name
                        changed.append("姓名")
                    if mobile and existing.phone != mobile:
                        existing.phone = mobile
                        changed.append("电话")
                    if email:
                        resolved_email, conflict = self._claim_unique(
                            email_map, email, current=existing
                        )
                        if resolved_email and (existing.email or "").lower() != resolved_email.lower():
                            existing.email = resolved_email.lower()
                            changed.append("邮箱")
                        if conflict:
                            add("warning", f"{existing.username} 的新邮箱 {email} 已被其他账号占用，已保留原邮箱")
                    if job_number:
                        resolved_employee, conflict = self._claim_unique(
                            employee_map, job_number, current=existing
                        )
                        if resolved_employee and existing.employee_no != resolved_employee:
                            existing.employee_no = resolved_employee
                            changed.append("工号")
                        if conflict:
                            add("warning", f"{existing.username} 的新工号 {job_number} 已被其他账号占用，已保留原工号")
                    if avatar and existing.avatar != avatar:
                        existing.avatar = avatar
                        changed.append("头像")
                    if position and existing.position != position:
                        existing.position = position
                        changed.append("职位")
                    if existing.dept_id != dept_id:
                        existing.dept_id = dept_id
                        changed.append("部门")
                    if existing.status != target_status:
                        if target_status == 0 and await self._is_last_super_admin(existing):
                            counts["user_skipped"] += 1
                            add("error", f"{existing.username} 是最后一名超级管理员，已跳过停用以保护系统")
                        else:
                            existing.status = target_status
                            if target_status == 0:
                                existing.token_version += 1
                                counts["user_disabled"] += 1
                                add("warning", f"钉钉成员已离职，系统账号同步停用：{existing.username}")
                            changed.append("状态")
                    if existing.source != "dingtalk":
                        existing.source = "dingtalk"
                        changed.append("来源")
                    if existing.must_change_password:
                        existing.must_change_password = False
                if level == "overwrite":
                    counts["user_updated"] += 1
                    add("info", f"更新钉钉用户：{existing.real_name}（{'+'.join(changed)}）")
                else:
                    counts["user_matched"] += 1
                    if changed:
                        add(
                            "info",
                            f"匹配现有用户并补充钉钉标识与空字段：{existing.real_name}（{existing.username}，{'+'.join(changed)}）",
                        )
                    else:
                        add("info", f"匹配现有用户并补充钉钉标识：{existing.real_name}（{existing.username}）")
                continue

            # 新建钉钉用户
            username = _normalize_username(job_number or "", f"dt_{userid}")
            if not job_number:
                username = f"dt_{userid}".lower()
                if not _USERNAME_RE.fullmatch(username):
                    username = _normalize_username(userid, userid)
            if username in username_map:
                counts["user_skipped"] += 1
                add("warning", f"用户名 {username} 已被占用，跳过钉钉成员 {name or userid}")
                continue
            resolved_email, email_conflict = self._claim_unique(email_map, email, current=None)
            resolved_phone, phone_conflict = self._claim_unique(phone_map, mobile, current=None)
            resolved_employee, employee_conflict = self._claim_unique(employee_map, job_number, current=None)
            if phone_conflict:
                resolved_phone = None
            user = User(
                username=username,
                password_hash=hash_password(pysecrets.token_urlsafe(24)),
                real_name=name or username,
                employee_no=resolved_employee,
                email=resolved_email.lower() if resolved_email else None,
                phone=resolved_phone,
                avatar=avatar,
                position=position,
                dept_id=dept_id,
                status=target_status,
                source="dingtalk",
                dingtalk_userid=userid,
                dingtalk_synced_at=now,
                must_change_password=False,
                remark="由钉钉通讯录同步自动创建",
            )
            if role is not None:
                user.roles = [role]
            self.session.add(user)
            username_map[username] = user
            if user.email:
                email_map[user.email.lower()] = user
            if user.phone:
                phone_map[user.phone] = user
            if user.employee_no:
                employee_map[user.employee_no] = user
            by_userid[userid] = user
            counts["user_created"] += 1
            if target_status == 0:
                counts["user_disabled"] += 1
            add("info", f"新增钉钉用户：{name or username}（{username}）")
            if email_conflict:
                add("warning", f"{username} 的邮箱 {email} 已被其他账号占用，已忽略")
            if phone_conflict:
                add("warning", f"{username} 的手机号 {mobile} 已被其他账号占用，已忽略")
            if employee_conflict:
                add("warning", f"{username} 的工号 {job_number} 已被其他账号占用，已忽略")
            if role is None and not role_warning:
                role_warning = True
                add("warning", "未找到默认角色或普通员工角色，新用户将没有角色")

        if config.disable_on_leave:
            for user in disable_candidates:
                if user.id in seen_ids or user.status == 0:
                    continue
                if await self._is_last_super_admin(user):
                    counts["user_skipped"] += 1
                    add("error", f"{user.username} 是最后一名超级管理员，已跳过停用以保护系统")
                    continue
                user.status = 0
                user.token_version += 1
                counts["user_disabled"] += 1
                add("warning", f"钉钉成员已不在名册，系统账号同步停用：{user.username}")
        else:
            missing = [user.username for user in disable_candidates if user.id not in seen_ids and user.status == 1]
            for username in missing[:20]:
                add("info", f"钉钉名册中已无 {username}，因未开启离职停用，账号保持启用")

    async def _sync_dept_managers(
        self,
        entries: list[dict[str, Any]],
        dept_by_key: dict[str, Dept],
        counts: dict[str, int],
        add,
    ) -> None:
        pending: list[tuple[Dept, str]] = []
        for entry in entries:
            dept = dept_by_key.get(str(entry.get("dept_id") or ""))
            if dept is None:
                continue
            managers = entry.get("manager_userids") or []
            if not managers:
                continue
            pending.append((dept, str(managers[0])))
        if not pending:
            return
        manager_ids = {userid for _, userid in pending}
        users = list(
            (
                await self.session.execute(
                    select(User).where(
                        User.dingtalk_userid.in_(manager_ids),
                        User.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_userid = {user.dingtalk_userid: user for user in users}
        for dept, userid in pending:
            if dept.manager_id is not None:
                continue
            manager = by_userid.get(userid)
            if manager is None or manager.status != 1:
                continue
            dept.manager_id = manager.id
            counts["dept_updated"] += 1
            add("info", f"同步部门负责人：{dept.name} → {manager.real_name}")

    async def _rebuild_dept_paths(self) -> None:
        depts = list((await self.session.execute(select(Dept))).scalars().all())
        by_id = {dept.id: dept for dept in depts}
        children: dict[int, list[Dept]] = {}
        roots: list[Dept] = []
        for dept in depts:
            if dept.parent_id and dept.parent_id in by_id and dept.parent_id != dept.id:
                children.setdefault(dept.parent_id, []).append(dept)
            else:
                roots.append(dept)

        def walk(dept: Dept, parent: Dept | None) -> None:
            dept.path = f"{parent.path if parent else '/'}{dept.id}/"
            dept.level = (parent.level + 1) if parent else 1
            for child in children.get(dept.id, []):
                walk(child, dept)

        for root in roots:
            walk(root, None)


async def get_active_dingtalk_config(session: AsyncSession) -> DingTalkConfig | None:
    config = (
        await session.execute(select(DingTalkConfig).order_by(DingTalkConfig.id).limit(1))
    ).scalar_one_or_none()
    if config is None or not config.enabled:
        return None
    return config
