from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ConflictError
from app.models import Dept, OrgSyncPolicy, User
from app.schemas.org import OrgSyncPolicyOut, OrgSyncPolicyUpdate
from app.services.audit_service import AuditService
from app.services.txn import commit_or_conflict

SYNC_SOURCES = ("ldap", "dingtalk")
SOURCES = ("ldap", "dingtalk", "local")
CONFLICT_STRATEGIES = ("skip", "fill_empty", "overwrite")
DISABLE_SCOPES = ("own", "any")
DEFAULT_PRIORITY = "ldap,dingtalk,local"


def parse_priority(raw: str) -> list[str]:
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if sorted(parts) != sorted(SOURCES):
        raise BizError("主源优先级必须包含 ldap、dingtalk、local 三个来源且不重复")
    return parts


def mutation_level(policy: OrgSyncPolicy, sync_source: str, target_source: str) -> str:
    """同步源对已有目标（用户/部门）的更新等级：overwrite / fill_empty / skip。

    同源永远全量刷新；本地用户在保护开启时只补空；来自更高优先级来源的目标只补空；
    其余情况按全局冲突策略执行。
    """
    if sync_source not in SYNC_SOURCES:
        raise BizError(f"未知同步来源：{sync_source}")
    if target_source == sync_source:
        return "overwrite"
    priority = parse_priority(policy.source_priority)
    if policy.protect_local and target_source == "local":
        return "fill_empty"
    ranks = {source: index for index, source in enumerate(priority)}
    target_rank = ranks.get(target_source, len(priority))
    if target_rank < ranks[sync_source]:
        return "fill_empty"
    return policy.conflict_strategy


def can_disable_user(policy: OrgSyncPolicy, sync_source: str, user: User) -> bool:
    """同步源缺失/离职时，是否允许停用该用户。"""
    if user.source == sync_source:
        return True
    if policy.disable_scope != "any":
        return False
    if sync_source == "ldap":
        return bool(user.ldap_dn)
    if sync_source == "dingtalk":
        return bool(user.dingtalk_userid)
    return False


def can_disable_dept(policy: OrgSyncPolicy, sync_source: str, dept: Dept) -> bool:
    if dept.source == sync_source:
        return True
    if policy.disable_scope != "any":
        return False
    if sync_source == "ldap":
        return bool(dept.ldap_dn)
    if sync_source == "dingtalk":
        return bool(dept.dingtalk_dept_id)
    return False


class OrgSyncPolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def get_policy(self) -> OrgSyncPolicy:
        policy = (
            await self.session.execute(select(OrgSyncPolicy).limit(1))
        ).scalar_one_or_none()
        if policy is None:
            policy = OrgSyncPolicy(
                source_priority=DEFAULT_PRIORITY,
                conflict_strategy="fill_empty",
                protect_local=True,
                disable_scope="own",
            )
            self.session.add(policy)
            await self.session.flush()
        return policy

    async def get_policy_out(self) -> OrgSyncPolicyOut:
        policy = await self.get_policy()
        return self._out(policy)

    @staticmethod
    def _out(policy: OrgSyncPolicy) -> OrgSyncPolicyOut:
        return OrgSyncPolicyOut(
            source_priority=policy.source_priority,
            conflict_strategy=policy.conflict_strategy,
            protect_local=policy.protect_local,
            disable_scope=policy.disable_scope,
            version=policy.version,
        )

    async def save_policy(
        self,
        payload: OrgSyncPolicyUpdate,
        operator: User,
    ) -> OrgSyncPolicyOut:
        priority = parse_priority(payload.source_priority)
        if payload.conflict_strategy not in CONFLICT_STRATEGIES:
            raise BizError("冲突策略仅支持 skip、fill_empty、overwrite")
        if payload.disable_scope not in DISABLE_SCOPES:
            raise BizError("停用联动范围仅支持 own、any")

        policy = await self.get_policy()
        if policy.version != payload.version:
            raise ConflictError("同步策略已被他人修改，请刷新后重试")

        before = {
            "source_priority": policy.source_priority,
            "conflict_strategy": policy.conflict_strategy,
            "protect_local": policy.protect_local,
            "disable_scope": policy.disable_scope,
        }
        policy.source_priority = ",".join(priority)
        policy.conflict_strategy = payload.conflict_strategy
        policy.protect_local = payload.protect_local
        policy.disable_scope = payload.disable_scope

        await self.audit.record(
            action="org.sync_policy.update",
            module="组织管理",
            summary="更新组织同步策略",
            actor=operator,
            resource_type="org_sync_policy",
            resource_id=policy.id,
            before=before,
            after={
                "source_priority": policy.source_priority,
                "conflict_strategy": policy.conflict_strategy,
                "protect_local": policy.protect_local,
                "disable_scope": policy.disable_scope,
            },
        )
        await commit_or_conflict(self.session)
        return self._out(policy)
