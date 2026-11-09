from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets as pysecrets
import time
from dataclasses import dataclass
from typing import Any

from ldap3 import Connection, Server, SUBTREE
from ldap3.core.exceptions import LDAPException
from ldap3.utils.dn import parse_dn
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BizError, ConflictError, NotFoundError
from app.core.permissions import SUPER_ADMIN_ROLE
from app.core.security import hash_password
from app.core.secrets import decrypt_secret, encrypt_secret
from app.models import Dept, LdapConfig, LdapSyncLog, OrgSyncPolicy, Role, User
from app.models.base import now_cst
from app.repositories.user_repo import UserRepository
from app.schemas.ldap import (
    LdapConfigOut,
    LdapConfigPayload,
    LdapDeptOption,
    LdapOptionsOut,
    LdapRoleOption,
    LdapSyncLogOut,
    LdapTestResult,
)
from app.services.audit_service import AuditService
from app.services.org_policy_service import (
    OrgSyncPolicyService,
    can_disable_user,
    mutation_level,
)
from app.services.permission_service import AuthContext
from app.services.txn import commit_or_conflict

logger = logging.getLogger("itam.ldap")

_MANUAL = "MANUAL"
_SCHEDULED = "SCHEDULED"
_RUNNING_STALE_SECONDS = 1800
_MAX_DETAILS = 300
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
DEFAULT_USER_FILTER = "(&(objectCategory=person)(objectClass=user))"
DEFAULT_DEPT_FILTER = "(objectClass=organizationalUnit)"


@dataclass(slots=True)
class LdapSettings:
    server_host: str
    server_port: int
    use_ssl: bool
    start_tls: bool
    base_dn: str
    bind_dn: str
    bind_password: str
    user_filter: str
    dept_filter: str
    username_attribute: str
    real_name_attribute: str
    email_attribute: str
    phone_attribute: str
    employee_no_attribute: str


@dataclass(slots=True)
class LdapProbeResult:
    success: bool
    message: str
    server: str
    dept_sample: int
    user_sample: int
    elapsed_ms: int


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("latin-1", errors="ignore")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _attr(attributes: dict[str, Any], name: str) -> Any:
    if name in attributes:
        return attributes[name]
    lowered = name.lower()
    for key, value in attributes.items():
        if str(key).lower() == lowered:
            return value
    return None


def _split_dn(dn: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in dn:
        if char == "\\" and not escaped:
            escaped = True
            current.append(char)
            continue
        if char == "," and not escaped:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            escaped = False
            continue
        escaped = False
        current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _parent_dn(dn: str) -> str:
    parts = _split_dn(dn)
    return ",".join(parts[1:]) if len(parts) > 1 else ""


def _dn_depth(dn: str) -> int:
    return len(_split_dn(dn))


def _normalize_dn(dn: str | None) -> str:
    return " ".join(part.strip() for part in _split_dn(dn or "")).lower()


def _unescape_rdn(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def _rdn_value(dn: str) -> str:
    parts = _split_dn(dn)
    if not parts:
        return ""
    _, _, value = parts[0].partition("=")
    return _unescape_rdn(value.strip())


def _ldap_result_message(connection: Connection) -> str:
    result = connection.result or {}
    description = result.get("description")
    message = result.get("message")
    if description or message:
        return " / ".join(str(item) for item in (description, message) if item)
    return "未知错误"


def _build_server(settings: LdapSettings) -> Server:
    return Server(
        settings.server_host,
        port=settings.server_port,
        use_ssl=settings.use_ssl,
        connect_timeout=6,
        get_info=None,
    )


def _open_bind(settings: LdapSettings, *, user: str | None = None, password: str = "") -> Connection:
    connection = Connection(
        _build_server(settings),
        user=user if user is not None else settings.bind_dn,
        password=password if user is not None else settings.bind_password,
        auto_bind=False,
        receive_timeout=30,
        raise_exceptions=False,
    )
    try:
        if settings.start_tls:
            if not connection.open():
                raise BizError(f"无法连接域控服务器：{_ldap_result_message(connection)}")
            if not connection.start_tls():
                raise BizError(f"StartTLS 协商失败：{_ldap_result_message(connection)}")
        if not connection.bind():
            raise BizError(f"域控绑定失败：{_ldap_result_message(connection)}")
        return connection
    except BizError:
        connection.unbind()
        raise
    except LDAPException as exc:
        connection.unbind()
        raise BizError(f"无法连接域控服务器：{exc}") from exc


def _iter_entries(
    connection: Connection,
    *,
    base_dn: str,
    search_filter: str,
    attributes: list[str],
    limit: int | None = None,
):
    raw_attributes = list(dict.fromkeys(attributes))
    collected = 0
    try:
        entries = connection.extend.standard.paged_search(
            search_base=base_dn,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=raw_attributes,
            paged_size=500,
            generator=True,
        )
        for item in entries:
            if item.get("type") != "searchResEntry":
                continue
            yield {
                "dn": str(item.get("dn") or ""),
                "attributes": dict(item.get("attributes") or {}),
            }
            collected += 1
            if limit is not None and collected >= limit:
                return
    except LDAPException as exc:
        logger.warning("Paged LDAP search failed, falling back to plain search: %s", exc)
        ok = connection.search(
            base_dn,
            search_filter,
            search_scope=SUBTREE,
            attributes=raw_attributes,
            size_limit=limit or 0,
        )
        if not ok:
            raise BizError(f"域控检索失败：{_ldap_result_message(connection)}") from exc
        for entry in connection.entries:
            yield {
                "dn": str(entry.entry_dn),
                "attributes": {
                    str(key): entry[key].value for key in entry.entry_attributes
                },
            }
            collected += 1
            if limit is not None and collected >= limit:
                return


def _settings_from_payload(
    payload: LdapConfigPayload,
    *,
    bind_password: str,
) -> LdapSettings:
    return LdapSettings(
        server_host=payload.server_host,
        server_port=payload.server_port,
        use_ssl=payload.use_ssl,
        start_tls=payload.start_tls,
        base_dn=payload.base_dn,
        bind_dn=payload.bind_dn,
        bind_password=bind_password,
        user_filter=payload.user_filter or DEFAULT_USER_FILTER,
        dept_filter=payload.dept_filter or DEFAULT_DEPT_FILTER,
        username_attribute=payload.username_attribute,
        real_name_attribute=payload.real_name_attribute,
        email_attribute=payload.email_attribute,
        phone_attribute=payload.phone_attribute,
        employee_no_attribute=payload.employee_no_attribute,
    )


def _settings_from_config(config: LdapConfig) -> LdapSettings:
    if not config.bind_password_encrypted:
        raise BizError("尚未配置域控绑定密码")
    return LdapSettings(
        server_host=config.server_host,
        server_port=config.server_port,
        use_ssl=config.use_ssl,
        start_tls=config.start_tls,
        base_dn=config.base_dn,
        bind_dn=config.bind_dn,
        bind_password=decrypt_secret(config.bind_password_encrypted),
        user_filter=config.user_filter or DEFAULT_USER_FILTER,
        dept_filter=config.dept_filter or DEFAULT_DEPT_FILTER,
        username_attribute=config.username_attribute,
        real_name_attribute=config.real_name_attribute,
        email_attribute=config.email_attribute,
        phone_attribute=config.phone_attribute,
        employee_no_attribute=config.employee_no_attribute,
    )


def _probe(settings: LdapSettings) -> LdapProbeResult:
    started = time.monotonic()
    connection = _open_bind(settings)
    try:
        dept_entries = list(
            _iter_entries(
                connection,
                base_dn=settings.base_dn,
                search_filter=settings.dept_filter,
                attributes=["ou", "name"],
                limit=10,
            )
        )
        user_entries = list(
            _iter_entries(
                connection,
                base_dn=settings.base_dn,
                search_filter=settings.user_filter,
                attributes=[
                    settings.username_attribute,
                    settings.real_name_attribute,
                    "userAccountControl",
                ],
                limit=10,
            )
        )
    finally:
        connection.unbind()
    elapsed = int((time.monotonic() - started) * 1000)
    return LdapProbeResult(
        success=True,
        message=(
            f"连接成功，绑定账号认证通过；抽样读取部门 {len(dept_entries)} 条、"
            f"用户 {len(user_entries)} 条"
        ),
        server=f"{settings.server_host}:{settings.server_port}",
        dept_sample=len(dept_entries),
        user_sample=len(user_entries),
        elapsed_ms=elapsed,
    )


def _fetch_directory(settings: LdapSettings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    connection = _open_bind(settings)
    try:
        dept_entries = list(
            _iter_entries(
                connection,
                base_dn=settings.base_dn,
                search_filter=settings.dept_filter,
                attributes=["ou", "name", "description", "managedBy"],
            )
        )
        user_attributes = [
            settings.username_attribute,
            settings.real_name_attribute,
            settings.email_attribute,
            settings.phone_attribute,
            settings.employee_no_attribute,
            "userAccountControl",
            "cn",
            "distinguishedName",
            "userPrincipalName",
        ]
        user_entries = list(
            _iter_entries(
                connection,
                base_dn=settings.base_dn,
                search_filter=settings.user_filter,
                attributes=user_attributes,
            )
        )
    finally:
        connection.unbind()
    return dept_entries, user_entries


def authenticate_ldap_user(
    config: LdapConfig,
    user: User,
    password: str,
) -> tuple[bool, str, bool]:
    """Return (authenticated, message, service_unavailable)."""
    if not password or not password.strip():
        return False, "用户名或密码错误", False
    try:
        settings = _settings_from_config(config)
    except BizError as exc:
        return False, exc.message, True
    candidates: list[str] = []
    if user.ldap_dn:
        candidates.append(user.ldap_dn)
    dc_parts = [
        part.split("=", 1)[1]
        for part in _split_dn(settings.base_dn)
        if part.upper().startswith("DC=") and "=" in part
    ]
    if dc_parts:
        candidates.append(f"{user.username}@{'.'.join(dc_parts)}")
    if not candidates:
        return False, "域控账号未关联目录 DN，请联系管理员重新同步", True

    last_message = "用户名或密码错误"
    for candidate in candidates:
        connection = Connection(
            _build_server(settings),
            user=candidate,
            password=password,
            auto_bind=False,
            receive_timeout=15,
            raise_exceptions=False,
        )
        try:
            if settings.start_tls:
                if not connection.open():
                    last_message = _ldap_result_message(connection)
                    continue
                if not connection.start_tls():
                    last_message = _ldap_result_message(connection)
                    continue
            if connection.bind():
                return True, "", False
            description = str((connection.result or {}).get("description") or "")
            last_message = _ldap_result_message(connection)
            if "invalidCredentials" not in description and "invalid credentials" not in last_message.lower():
                return False, f"域控认证失败：{last_message}", True
        except LDAPException as exc:
            return False, f"域控服务不可用：{exc}", True
        finally:
            connection.unbind()
    return False, "用户名或密码错误", False


class LdapSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def get_config(self) -> LdapConfig | None:
        return (
            await self.session.execute(select(LdapConfig).order_by(LdapConfig.id).limit(1))
        ).scalar_one_or_none()

    async def get_config_out(self) -> LdapConfigOut:
        config = await self.get_config()
        if config is None:
            return LdapConfigOut(
                id=0,
                enabled=False,
                server_host="",
                server_port=389,
                use_ssl=False,
                start_tls=False,
                base_dn="",
                bind_dn="",
                has_password=False,
                user_filter=DEFAULT_USER_FILTER,
                dept_filter=DEFAULT_DEPT_FILTER,
                username_attribute="sAMAccountName",
                real_name_attribute="displayName",
                email_attribute="mail",
                phone_attribute="telephoneNumber",
                employee_no_attribute="employeeID",
                sync_interval_minutes=60,
                version=1,
            )
        return await self._serialize_config(config)

    async def _serialize_config(self, config: LdapConfig) -> LdapConfigOut:
        role = await self.session.get(Role, config.default_role_id) if config.default_role_id else None
        dept = await self.session.get(Dept, config.root_dept_id) if config.root_dept_id else None
        return LdapConfigOut(
            id=config.id,
            enabled=config.enabled,
            server_host=config.server_host,
            server_port=config.server_port,
            use_ssl=config.use_ssl,
            start_tls=config.start_tls,
            base_dn=config.base_dn,
            bind_dn=config.bind_dn,
            has_password=bool(config.bind_password_encrypted),
            user_filter=config.user_filter,
            dept_filter=config.dept_filter,
            username_attribute=config.username_attribute,
            real_name_attribute=config.real_name_attribute,
            email_attribute=config.email_attribute,
            phone_attribute=config.phone_attribute,
            employee_no_attribute=config.employee_no_attribute,
            default_role_id=config.default_role_id,
            default_role_name=role.name if role else None,
            root_dept_id=config.root_dept_id,
            root_dept_name=dept.name if dept else None,
            sync_interval_minutes=config.sync_interval_minutes,
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

    async def save_config(
        self,
        payload: LdapConfigPayload,
        context: AuthContext,
    ) -> LdapConfigOut:
        version = getattr(payload, "version", None)
        config = await self.get_config()
        if config is not None and version is not None and config.version != version:
            raise ConflictError("域控配置已被他人修改，请刷新后重试")

        if payload.default_role_id is not None:
            role = await self.session.get(Role, payload.default_role_id)
            if role is None or role.status != 1:
                raise BizError("默认角色不存在或已停用")
        if payload.root_dept_id is not None:
            dept = await self.session.get(Dept, payload.root_dept_id)
            if dept is None:
                raise BizError("默认归属部门不存在")
        if payload.enabled:
            if not payload.bind_password and not (config and config.bind_password_encrypted):
                raise BizError("启用同步前请填写域控绑定密码")

        before = self._config_snapshot(config) if config else None
        if config is None:
            config = LdapConfig()
            self.session.add(config)

        config.enabled = payload.enabled
        config.server_host = payload.server_host
        config.server_port = payload.server_port
        config.use_ssl = payload.use_ssl
        config.start_tls = payload.start_tls
        config.base_dn = payload.base_dn
        config.bind_dn = payload.bind_dn
        if payload.bind_password:
            config.bind_password_encrypted = encrypt_secret(payload.bind_password)
        config.user_filter = payload.user_filter or DEFAULT_USER_FILTER
        config.dept_filter = payload.dept_filter or DEFAULT_DEPT_FILTER
        config.username_attribute = payload.username_attribute
        config.real_name_attribute = payload.real_name_attribute
        config.email_attribute = payload.email_attribute
        config.phone_attribute = payload.phone_attribute
        config.employee_no_attribute = payload.employee_no_attribute
        config.default_role_id = payload.default_role_id
        config.root_dept_id = payload.root_dept_id
        config.sync_interval_minutes = payload.sync_interval_minutes

        await self.session.flush()
        await self.audit.record(
            action="ldap.config.save",
            module="域控同步",
            summary="保存域控同步配置",
            actor=context.user,
            resource_type="ldap_config",
            resource_id=config.id,
            before=before,
            after=self._config_snapshot(config),
        )
        await commit_or_conflict(self.session)
        return await self._serialize_config(config)

    @staticmethod
    def _config_snapshot(config: LdapConfig | None) -> dict[str, Any] | None:
        if config is None:
            return None
        return {
            "enabled": config.enabled,
            "server": f"{config.server_host}:{config.server_port}",
            "use_ssl": config.use_ssl,
            "start_tls": config.start_tls,
            "base_dn": config.base_dn,
            "bind_dn": config.bind_dn,
            "user_filter": config.user_filter,
            "dept_filter": config.dept_filter,
            "default_role_id": config.default_role_id,
            "root_dept_id": config.root_dept_id,
            "sync_interval_minutes": config.sync_interval_minutes,
            "has_password": bool(config.bind_password_encrypted),
            "version": config.version,
        }

    async def test_config(
        self,
        payload: LdapConfigPayload,
        context: AuthContext,
    ) -> LdapTestResult:
        config = await self.get_config()
        password = payload.bind_password
        if not password and config and config.bind_password_encrypted:
            try:
                password = decrypt_secret(config.bind_password_encrypted)
            except BizError:
                password = None
        if not password:
            raise BizError("请填写域控绑定密码后再测试")
        if not payload.server_host or not payload.base_dn or not payload.bind_dn:
            raise BizError("请填写服务器地址、Base DN 与绑定账号后再测试")
        if payload.use_ssl and payload.start_tls:
            raise BizError("SSL 与 StartTLS 不能同时启用")

        settings = _settings_from_payload(payload, bind_password=password)
        try:
            result = await asyncio.to_thread(_probe, settings)
            audit_status = "SUCCESS"
        except Exception as exc:  # noqa: BLE001 - surface any LDAP failure to the UI
            message = exc.message if isinstance(exc, BizError) else str(exc)
            result = LdapProbeResult(
                success=False,
                message=message or "连接失败",
                server=f"{payload.server_host}:{payload.server_port}",
                dept_sample=0,
                user_sample=0,
                elapsed_ms=0,
            )
            audit_status = "FAILED"

        checked_at = now_cst()
        if config is not None:
            config.last_test_at = checked_at
            config.last_test_status = "SUCCESS" if result.success else "FAILED"
            config.last_test_message = result.message[:1000]
        await self.audit.record(
            action="ldap.config.test",
            module="域控同步",
            summary=f"测试域控连接：{'成功' if result.success else '失败'}",
            actor=context.user,
            resource_type="ldap_config",
            resource_id=config.id if config else None,
            status=audit_status,
            after={"server": result.server, "message": result.message[:500]},
        )
        await self.session.commit()
        return LdapTestResult(
            success=result.success,
            message=result.message,
            server=result.server,
            dept_sample=result.dept_sample,
            user_sample=result.user_sample,
            elapsed_ms=result.elapsed_ms,
            checked_at=checked_at,
        )

    async def options(self) -> LdapOptionsOut:
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
            (await self.session.execute(select(Dept).order_by(Dept.level, Dept.sort, Dept.id)))
            .scalars()
            .all()
        )
        ldap_depts = int(
            await self.session.scalar(
                select(func.count(Dept.id)).where(Dept.source == "ldap")
            )
            or 0
        )
        ldap_users = int(
            await self.session.scalar(
                select(func.count(User.id)).where(
                    User.source == "ldap", User.deleted_at.is_(None)
                )
            )
            or 0
        )
        local_users = int(
            await self.session.scalar(
                select(func.count(User.id)).where(
                    User.source == "local", User.deleted_at.is_(None)
                )
            )
            or 0
        )
        return LdapOptionsOut(
            roles=[
                LdapRoleOption(id=role.id, code=role.code, name=role.name)
                for role in roles
            ],
            depts=[
                LdapDeptOption(
                    id=dept.id,
                    parent_id=dept.parent_id,
                    name=dept.name,
                    level=dept.level,
                    status=dept.status,
                )
                for dept in depts
            ],
            ldap_dept_count=ldap_depts,
            ldap_user_count=ldap_users,
            local_user_count=local_users,
        )

    async def list_logs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> tuple[list[LdapSyncLogOut], int]:
        conditions = []
        if status:
            conditions.append(LdapSyncLog.status == status)
        total = int(
            await self.session.scalar(
                select(func.count(LdapSyncLog.id)).where(*conditions)
            )
            or 0
        )
        logs = list(
            (
                await self.session.execute(
                    select(LdapSyncLog)
                    .where(*conditions)
                    .order_by(LdapSyncLog.started_at.desc(), LdapSyncLog.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [LdapSyncLogOut.model_validate(log) for log in logs], total

    async def get_log(self, log_id: int) -> LdapSyncLogOut:
        log = await self.session.get(LdapSyncLog, log_id)
        if log is None:
            raise NotFoundError("同步日志不存在")
        return LdapSyncLogOut.model_validate(log)

    async def run_sync(
        self,
        *,
        config_id: int | None = None,
        trigger_type: str = _MANUAL,
        operator_id: int | None = None,
        operator_name: str | None = None,
    ) -> LdapSyncLog:
        config = (
            await self.session.get(LdapConfig, config_id)
            if config_id is not None
            else await self.get_config()
        )
        if config is None:
            raise NotFoundError("尚未配置域控同步")
        if not config.enabled:
            raise BizError("域控同步未启用")
        now = now_cst()
        if (
            config.last_sync_status == "RUNNING"
            and config.last_sync_at is not None
            and (now - config.last_sync_at).total_seconds() < _RUNNING_STALE_SECONDS
        ):
            raise BizError("已有同步任务正在执行，请稍后刷新日志")

        log = LdapSyncLog(
            config_id=config.id,
            trigger_type=trigger_type,
            status="RUNNING",
            started_at=now,
            operator_id=operator_id,
            operator_name=operator_name or ("系统计划任务" if trigger_type == _SCHEDULED else None),
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
            settings = _settings_from_config(config)
            dept_entries, user_entries = await asyncio.to_thread(_fetch_directory, settings)
            counts, details, errors = await self._apply_directory(
                config, dept_entries, user_entries
            )
            finished = now_cst()
            duration_ms = int((time.monotonic() - started) * 1000)
            status = "PARTIAL" if errors else "SUCCESS"
            message = (
                f"同步完成：部门 +{counts['dept_created']}/~{counts['dept_updated']}，"
                f"用户 +{counts['user_created']}/~{counts['user_updated']}/停用{counts['user_disabled']}"
            )
            if errors:
                message += f"，{errors} 项异常"
            log = await self._require_log(log_id)
            log.status = status
            log.finished_at = finished
            log.duration_ms = duration_ms
            log.error_count = errors
            log.message = message
            log.details = details
            for key, value in counts.items():
                setattr(log, key, value)
            config = await self.session.get(LdapConfig, config_pk)
            if config is not None:
                config.last_sync_at = finished
                config.last_sync_status = status
                config.last_sync_message = message
            await self.audit.record(
                action="ldap.sync",
                module="域控同步",
                summary=message,
                actor_id=operator_id,
                actor_name=operator_name,
                resource_type="ldap_config",
                resource_id=config.id if config is not None else config_pk,
                status="SUCCESS" if status == "SUCCESS" else "FAILED",
                after={
                    **counts,
                    "trigger": trigger_type,
                    "duration_ms": duration_ms,
                },
            )
            await self.session.commit()
            return log
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded
            logger.exception("LDAP sync failed")
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

    async def _require_log(self, log_id: int) -> LdapSyncLog:
        log = await self.session.get(LdapSyncLog, log_id)
        if log is None:
            raise BizError("同步日志记录丢失")
        return log

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
    ) -> LdapSyncLog:
        message = error.message if isinstance(error, BizError) else (str(error) or "同步失败")
        message = message[:1000]
        finished = now_cst()
        log = await self.session.get(LdapSyncLog, log_id)
        if log is None:
            log = LdapSyncLog(
                config_id=config_id,
                trigger_type=trigger_type,
                status="FAILED",
                started_at=finished,
                operator_id=operator_id,
                operator_name=operator_name,
            )
            self.session.add(log)
        log.status = "FAILED"
        log.finished_at = finished
        log.duration_ms = duration_ms
        log.error_count = 1
        log.message = f"同步失败：{message}"
        log.error_message = message
        log.details = [{"level": "error", "message": message}]
        config = await self.session.get(LdapConfig, config_id)
        if config is not None:
            config.last_sync_at = finished
            config.last_sync_status = "FAILED"
            config.last_sync_message = message
            resource_id = config.id
        else:
            resource_id = config_id
        await self.audit.record(
            action="ldap.sync",
            module="域控同步",
            summary=f"同步失败：{message}",
            actor_id=operator_id,
            actor_name=operator_name,
            resource_type="ldap_config",
            resource_id=resource_id,
            status="FAILED",
            after={"trigger": trigger_type, "duration_ms": duration_ms},
        )
        await self.session.commit()
        return log

    async def _apply_directory(
        self,
        config: LdapConfig,
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
        dept_by_dn = await self._sync_departments(
            config, policy, dept_entries, counts, add, details
        )
        await self._sync_users(
            config, policy, user_entries, dept_by_dn, counts, add, details
        )
        await self.session.flush()
        await self._sync_dept_managers(dept_entries, dept_by_dn, counts, add)
        await self.session.flush()
        await self._rebuild_dept_paths()
        errors = sum(1 for item in details if item["level"] == "error")
        return counts, details, errors

    async def _sync_departments(
        self,
        config: LdapConfig,
        policy,
        entries: list[dict[str, Any]],
        counts: dict[str, int],
        add,
        details: list[dict[str, str]],
    ) -> dict[str, Dept]:
        base_key = _normalize_dn(config.base_dn)
        unique_entries: dict[str, dict[str, Any]] = {}
        for entry in entries:
            dn = str(entry.get("dn") or "").strip()
            if not dn or _normalize_dn(dn) == base_key:
                continue
            unique_entries.setdefault(_normalize_dn(dn), entry)
        counts["dept_total"] = len(unique_entries)

        existing = list((await self.session.execute(select(Dept))).scalars().all())
        by_dn: dict[str, Dept] = {
            _normalize_dn(dept.ldap_dn): dept for dept in existing if dept.ldap_dn
        }
        codes = {dept.code for dept in existing}
        root_dept = (
            await self.session.get(Dept, config.root_dept_id)
            if config.root_dept_id
            else None
        )
        if config.root_dept_id and root_dept is None:
            add("warning", f"默认归属部门 ID={config.root_dept_id} 已不存在，用户将不分配部门")

        ordered = sorted(unique_entries.values(), key=lambda item: _dn_depth(str(item["dn"])))
        for entry in ordered:
            dn = str(entry["dn"]).strip()
            attrs = entry.get("attributes") or {}
            name = _as_text(_attr(attrs, "ou")) or _as_text(_attr(attrs, "name"))
            if not name:
                name = _rdn_value(dn)
            if not name:
                add("warning", f"跳过无名称的组织单位：{dn}")
                continue

            parent_dn = _parent_dn(dn)
            parent_key = _normalize_dn(parent_dn)
            parent_dept: Dept | None = None
            if parent_key and parent_key != base_key:
                parent_dept = by_dn.get(parent_key)
            if parent_dept is None and parent_key == base_key:
                parent_dept = root_dept
            if parent_dept is None and parent_key:
                parent_dept = root_dept
            parent_id = parent_dept.id if parent_dept else None

            dept = by_dn.get(_normalize_dn(dn))
            if dept is None:
                dept = Dept(
                    parent_id=parent_id,
                    name=name,
                    code=self._unique_dept_code(dn, codes),
                    path="",
                    level=1,
                    sort=0,
                    status=1,
                    source="ldap",
                    ldap_dn=dn,
                    ldap_synced_at=now_cst(),
                )
                codes.add(dept.code)
                self.session.add(dept)
                await self.session.flush()
                by_dn[_normalize_dn(dn)] = dept
                counts["dept_created"] += 1
                add("info", f"新增部门：{name}")
                continue

            target_parent_id = parent_id
            if target_parent_id == dept.id:
                target_parent_id = None
            level = mutation_level(policy, "ldap", dept.source)
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
                if dept.source != "ldap":
                    dept.source = "ldap"
                    changed = True
            elif level == "fill_empty":
                if dept.parent_id is None and target_parent_id is not None:
                    dept.parent_id = target_parent_id
                    changed = True
            else:
                counts["dept_skipped"] += 1
                add("info", f"按同步策略跳过域控部门更新：{dept.name}")
            dept.ldap_synced_at = now_cst()
            if changed:
                counts["dept_updated"] += 1
                add("info", f"更新部门：{name}")
        return by_dn

    @staticmethod
    def _unique_dept_code(dn: str, codes: set[str]) -> str:
        digest = hashlib.sha1(dn.lower().encode("utf-8")).hexdigest().upper()
        for length in (10, 16, 24):
            candidate = f"LDAP-{digest[:length]}"
            if candidate not in codes:
                return candidate
        counter = 1
        while f"LDAP-{digest[:24]}-{counter}" in codes:
            counter += 1
        return f"LDAP-{digest[:24]}-{counter}"

    async def _sync_users(
        self,
        config: LdapConfig,
        policy: OrgSyncPolicy,
        entries: list[dict[str, Any]],
        dept_by_dn: dict[str, Dept],
        counts: dict[str, int],
        add,
        details: list[dict[str, str]],
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
        ldap_by_dn: dict[str, User] = {
            _normalize_dn(user.ldap_dn): user for user in users if user.ldap_dn
        }
        ldap_by_uid: dict[str, User] = {
            (user.ldap_uid or "").lower(): user
            for user in users
            if user.source == "ldap" and user.ldap_uid
        }
        username_map: dict[str, User] = {user.username: user for user in users}
        email_map: dict[str, User] = {
            (user.email or "").lower(): user for user in users if user.email
        }
        employee_map: dict[str, User] = {
            user.employee_no: user for user in users if user.employee_no
        }
        disable_candidates = [
            user
            for user in users
            if user.deleted_at is None and can_disable_user(policy, "ldap", user)
        ]
        if disable_candidates and not entries:
            raise BizError("域控未返回任何用户，已中止同步以避免误停用账号")

        role = await self._default_role(config)
        role_warning = False
        seen_ids: set[int] = set()
        counts["user_total"] = len(entries)
        now = now_cst()

        for entry in entries:
            dn = str(entry.get("dn") or "").strip()
            attrs = entry.get("attributes") or {}
            uid_raw = _as_text(_attr(attrs, config.username_attribute))
            if not uid_raw:
                uid_raw = _as_text(_attr(attrs, "cn"))
            existing = ldap_by_dn.get(_normalize_dn(dn)) if dn else None
            if existing is not None:
                seen_ids.add(existing.id)
            if not uid_raw:
                counts["user_skipped"] += 1
                add("warning", f"跳过无账号属性的用户：{dn or '未知 DN'}")
                continue
            uid = uid_raw.strip()
            if existing is None:
                existing = ldap_by_uid.get(uid.lower())
                if existing is not None:
                    seen_ids.add(existing.id)
            username = self._normalize_username(uid, dn)
            if existing is None:
                same_name = username_map.get(username)
                if same_name is not None and same_name.source != "ldap":
                    counts["user_skipped"] += 1
                    add(
                        "warning",
                        f"用户名 {username} 已被本地账号占用，跳过域控用户 {dn}",
                    )
                    continue
                existing = same_name

            real_name = (
                _as_text(_attr(attrs, config.real_name_attribute))
                or _as_text(_attr(attrs, "cn"))
                or uid
            )
            email = _as_text(_attr(attrs, config.email_attribute))
            phone = _as_text(_attr(attrs, config.phone_attribute))
            employee_no = _as_text(_attr(attrs, config.employee_no_attribute))
            uac = _as_text(_attr(attrs, "userAccountControl"))
            disabled = False
            if uac is not None:
                try:
                    disabled = bool(int(uac) & 2)
                except (TypeError, ValueError):
                    disabled = False
            target_status = 0 if disabled else 1
            dept_id = self._resolve_user_dept(dn, dept_by_dn, config.root_dept_id)

            if existing is None:
                resolved_email, email_conflict = self._claim_unique(
                    email_map, email, current=None
                )
                resolved_employee, employee_conflict = self._claim_unique(
                    employee_map, employee_no, current=None
                )
                user = User(
                    username=username,
                    password_hash=hash_password(pysecrets.token_urlsafe(24)),
                    real_name=real_name,
                    employee_no=resolved_employee,
                    email=resolved_email.lower() if resolved_email else None,
                    phone=phone,
                    dept_id=dept_id,
                    status=target_status,
                    source="ldap",
                    ldap_dn=dn or None,
                    ldap_uid=uid,
                    ldap_synced_at=now,
                    must_change_password=False,
                    remark="由域控同步自动创建",
                )
                if role is not None:
                    user.roles = [role]
                self.session.add(user)
                username_map[username] = user
                if user.email:
                    email_map[user.email.lower()] = user
                if user.employee_no:
                    employee_map[user.employee_no] = user
                if dn:
                    ldap_by_dn[_normalize_dn(dn)] = user
                ldap_by_uid[uid.lower()] = user
                counts["user_created"] += 1
                if disabled:
                    counts["user_disabled"] += 1
                add("info", f"新增域控用户：{real_name}（{username}）")
                if email_conflict:
                    add("warning", f"{username} 的邮箱 {email} 已被其他账号占用，已忽略")
                if employee_conflict:
                    add("warning", f"{username} 的工号 {employee_no} 已被其他账号占用，已忽略")
                if role is None and not role_warning:
                    role_warning = True
                    add("warning", "未找到默认角色或普通员工角色，新用户将没有角色")
                continue

            seen_ids.add(existing.id)
            level = mutation_level(policy, "ldap", existing.source)
            changed: list[str] = []
            if level == "overwrite":
                if real_name and existing.real_name != real_name:
                    existing.real_name = real_name
                    changed.append("姓名")
                if email:
                    resolved_email, conflict = self._claim_unique(
                        email_map, email, current=existing
                    )
                    if resolved_email and (existing.email or "").lower() != resolved_email.lower():
                        existing.email = resolved_email.lower()
                        changed.append("邮箱")
                    if conflict:
                        add("warning", f"{username} 的新邮箱 {email} 已被其他账号占用，已保留原邮箱")
                if employee_no:
                    resolved_employee, conflict = self._claim_unique(
                        employee_map, employee_no, current=existing
                    )
                    if resolved_employee and existing.employee_no != resolved_employee:
                        existing.employee_no = resolved_employee
                        changed.append("工号")
                    if conflict:
                        add("warning", f"{username} 的新工号 {employee_no} 已被其他账号占用，已保留原工号")
                if phone and existing.phone != phone:
                    existing.phone = phone
                    changed.append("电话")
                if existing.dept_id != dept_id:
                    existing.dept_id = dept_id
                    changed.append("部门")
                if existing.status != target_status:
                    if target_status == 0 and await self._is_last_super_admin(existing):
                        counts["user_skipped"] += 1
                        add("error", f"{username} 是最后一名超级管理员，已跳过停用以保护系统")
                    else:
                        existing.status = target_status
                        if target_status == 0:
                            existing.token_version += 1
                            counts["user_disabled"] += 1
                            add("warning", f"域控账号已停用，系统账号同步停用：{username}")
                        changed.append("状态")
                if existing.source != "ldap":
                    existing.source = "ldap"
                    changed.append("来源")
                if existing.must_change_password:
                    existing.must_change_password = False
            elif level == "fill_empty":
                if not existing.real_name and real_name:
                    existing.real_name = real_name
                    changed.append("姓名")
                if not existing.email and email:
                    resolved_email, conflict = self._claim_unique(
                        email_map, email, current=existing
                    )
                    if resolved_email:
                        existing.email = resolved_email.lower()
                        changed.append("邮箱")
                    if conflict:
                        add("warning", f"{username} 的新邮箱 {email} 已被其他账号占用，已保留原邮箱")
                if not existing.employee_no and employee_no:
                    resolved_employee, conflict = self._claim_unique(
                        employee_map, employee_no, current=existing
                    )
                    if resolved_employee:
                        existing.employee_no = resolved_employee
                        changed.append("工号")
                    if conflict:
                        add("warning", f"{username} 的新工号 {employee_no} 已被其他账号占用，已保留原工号")
                if not existing.phone and phone:
                    existing.phone = phone
                    changed.append("电话")
            else:
                counts["user_skipped"] += 1
                add("info", f"按同步策略跳过域控用户更新：{username}")
            if existing.ldap_dn != (dn or None):
                existing.ldap_dn = dn or None
            if existing.ldap_uid != uid:
                existing.ldap_uid = uid
            existing.ldap_synced_at = now
            if changed:
                counts["user_updated"] += 1
                add("info", f"更新域控用户：{real_name}（{'+'.join(changed)}）")

        for user in disable_candidates:
            if user.id in seen_ids:
                continue
            if user.status == 0:
                continue
            if await self._is_last_super_admin(user):
                counts["user_skipped"] += 1
                add("error", f"{user.username} 是最后一名超级管理员，已跳过停用以保护系统")
                continue
            user.status = 0
            user.token_version += 1
            counts["user_disabled"] += 1
            add("warning", f"域控账号已不存在，系统账号同步停用：{user.username}")

    async def _sync_dept_managers(
        self,
        entries: list[dict[str, Any]],
        dept_by_dn: dict[str, Dept],
        counts: dict[str, int],
        add,
    ) -> None:
        pending: list[tuple[Dept, str]] = []
        for entry in entries:
            dn = _normalize_dn(str(entry.get("dn") or ""))
            dept = dept_by_dn.get(dn)
            attrs = entry.get("attributes") or {}
            manager_dn = _as_text(_attr(attrs, "managedBy"))
            if dept is None or not manager_dn:
                continue
            pending.append((dept, _normalize_dn(manager_dn)))
        if not pending:
            return

        manager_dns = {manager_dn for _, manager_dn in pending}
        users = list(
            (
                await self.session.execute(
                    select(User).where(
                        User.ldap_dn.is_not(None), User.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        by_dn = {
            _normalize_dn(user.ldap_dn): user
            for user in users
            if user.ldap_dn and _normalize_dn(user.ldap_dn) in manager_dns
        }
        for dept, manager_dn in pending:
            if dept.manager_id is not None:
                continue
            manager = by_dn.get(manager_dn)
            if manager is None or manager.status != 1:
                continue
            dept.manager_id = manager.id
            counts["dept_updated"] += 1
            add("info", f"同步部门负责人：{dept.name} → {manager.real_name}")

    async def _default_role(self, config: LdapConfig) -> Role | None:
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
    def _normalize_username(raw: str, dn: str) -> str:
        value = raw.strip().lower()
        value = re.sub(r"[^a-z0-9._-]", ".", value)
        value = re.sub(r"\.{2,}", ".", value).strip("._-")
        if len(value) < 3:
            value = f"u.{value}".strip("._-")
        if len(value) > 50:
            value = value[:50].rstrip("._-")
        if not _USERNAME_RE.fullmatch(value):
            digest = hashlib.sha1((dn or raw).lower().encode("utf-8")).hexdigest()
            value = f"ldap.{digest[:16]}"
        return value

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

    @staticmethod
    def _resolve_user_dept(
        dn: str,
        dept_by_dn: dict[str, Dept],
        root_dept_id: int | None,
    ) -> int | None:
        parent = _parent_dn(dn)
        while parent:
            dept = dept_by_dn.get(_normalize_dn(parent))
            if dept is not None:
                return dept.id
            parent = _parent_dn(parent)
        return root_dept_id

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


def due_for_sync(config: LdapConfig, now) -> bool:
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


async def get_active_ldap_config(session: AsyncSession) -> LdapConfig | None:
    config = (
        await session.execute(select(LdapConfig).order_by(LdapConfig.id).limit(1))
    ).scalar_one_or_none()
    if config is None or not config.enabled:
        return None
    return config
