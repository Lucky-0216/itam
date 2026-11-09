from datetime import timedelta

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import RequestStatus
from app.core.asset_ops import InventoryStatus
from app.core.assets import AssetStatus
from app.core.config import settings
from app.core.contract import ContractStatus
from app.models import (
    Asset,
    AssetContract,
    AssetRequest,
    AuditLog,
    InventoryTask,
    LdapConfig,
)
from app.models.base import now_cst
from app.schemas.notification import NotificationItem, NotificationSummary
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_scope_conditions,
    category_domain_condition,
    contract_domain_condition,
    is_self_only,
    scoped_dept_ids,
)

_LEVEL_WEIGHT = {"danger": 0, "warning": 1, "info": 2}


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self, context: AuthContext) -> NotificationSummary:
        conditions = await asset_scope_conditions(self.session, context)
        if not context.has_permission("asset:ledger:view"):
            conditions.append(false())
        today = now_cst().date()
        now = now_cst()
        items: list[NotificationItem] = []

        warranty_assets = list(
            (
                await self.session.execute(
                    select(Asset.id, Asset.asset_no, Asset.name, Asset.warranty_end)
                    .where(
                        *conditions,
                        Asset.warranty_end.is_not(None),
                        Asset.warranty_end >= today,
                        Asset.warranty_end
                        <= today + timedelta(days=settings.WARRANTY_REMINDER_DAYS),
                        Asset.status != AssetStatus.SCRAPPED,
                    )
                    .order_by(Asset.warranty_end.asc(), Asset.id.asc())
                )
            ).all()
        )
        if warranty_assets:
            preview = "、".join(
                f"{name}（{warranty_end.strftime('%m-%d')}）"
                for _, _, name, warranty_end in warranty_assets[:3]
            )
            items.append(
                NotificationItem(
                    id="asset-warranty-30d",
                    category="asset",
                    level="warning",
                    title=f"{len(warranty_assets)} 台资产 {settings.WARRANTY_REMINDER_DAYS} 天内保修到期",
                    description=f"{preview}{' 等' if len(warranty_assets) > 3 else ''}，请及时安排续保或更换。",
                    occurred_at=now,
                    link=f"/assets/ledger?warranty={settings.WARRANTY_REMINDER_DAYS}",
                )
            )

        expired_warranty = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(
                    *conditions,
                    Asset.warranty_end.is_not(None),
                    Asset.warranty_end < today,
                    Asset.status != AssetStatus.SCRAPPED,
                )
            )
            or 0
        )
        if expired_warranty:
            items.append(
                NotificationItem(
                    id="asset-warranty-expired",
                    category="asset",
                    level="danger",
                    title=f"{expired_warranty} 台在用资产保修已到期",
                    description="资产已超过保修截止日期，请在提醒中心查看并安排续保或更换。",
                    occurred_at=now,
                    link="/assets/reminders?category=WARRANTY&level=DANGER",
                )
            )

        if context.has_permission("asset:contract:view"):
            allowed = await scoped_dept_ids(
                self.session, context, resource="contract"
            )
            contract_conditions: list = [
                AssetContract.status == ContractStatus.ACTIVE
            ]
            if is_self_only(context, "contract"):
                contract_conditions.append(
                    or_(
                        AssetContract.owner_id == context.user.id,
                        AssetContract.created_by_id == context.user.id,
                    )
                )
            elif allowed is not None:
                contract_conditions.append(
                    AssetContract.dept_id.in_(allowed) if allowed else false()
                )
            domain_condition = contract_domain_condition(context)
            if domain_condition is not None:
                contract_conditions.append(domain_condition)
            expiring_contracts = list(
                (
                    await self.session.execute(
                        select(AssetContract)
                        .where(
                            *contract_conditions,
                            AssetContract.end_date >= today,
                            AssetContract.end_date
                            <= today + timedelta(days=settings.CONTRACT_REMINDER_DAYS),
                        )
                        .order_by(AssetContract.end_date.asc())
                    )
                )
                .scalars()
                .all()
            )
            if expiring_contracts:
                preview = "、".join(
                    f"{item.name}（{item.end_date.strftime('%m-%d')}）"
                    for item in expiring_contracts[:3]
                )
                items.append(
                    NotificationItem(
                        id="contract-expiring-30d",
                        category="contract",
                        level="warning",
                        title=f"{len(expiring_contracts)} 份合同 {settings.CONTRACT_REMINDER_DAYS} 天内到期",
                        description=(
                            f"{preview}"
                            f"{' 等' if len(expiring_contracts) > 3 else ''}"
                            "，请及时安排续签或终止。"
                        ),
                        occurred_at=now,
                        link="/assets/contracts?status=EXPIRING",
                    )
                )
            expired_contracts = int(
                await self.session.scalar(
                    select(func.count(AssetContract.id)).where(
                        *contract_conditions,
                        AssetContract.end_date < today,
                    )
                )
                or 0
            )
            if expired_contracts:
                items.append(
                    NotificationItem(
                        id="contract-expired",
                        category="contract",
                        level="danger",
                        title=f"{expired_contracts} 份合同已到期未处理",
                        description="合同已超过结束日期，请尽快续签或办理终止。",
                        occurred_at=now,
                        link="/assets/contracts?status=EXPIRED",
                    )
                )

        status_counts = dict(
            (
                await self.session.execute(
                    select(Asset.status, func.count(Asset.id))
                    .where(*conditions)
                    .group_by(Asset.status)
                )
            ).all()
        )
        pending_stock = int(status_counts.get(AssetStatus.PENDING_STOCK, 0))
        if pending_stock:
            items.append(
                NotificationItem(
                    id="asset-pending-stock",
                    category="asset",
                    level="info",
                    title=f"{pending_stock} 台资产等待入库",
                    description="资产已完成采购登记但尚未入库，请确认实物后办理入库。",
                    occurred_at=now,
                    link="/assets/ledger?status=PENDING_STOCK",
                )
            )
        idle = int(status_counts.get(AssetStatus.IDLE, 0))
        if idle:
            items.append(
                NotificationItem(
                    id="asset-idle",
                    category="asset",
                    level="info",
                    title=f"{idle} 台资产处于闲置状态",
                    description="可在资产台账中查看闲置资产，并分配给有需要的部门或人员。",
                    occurred_at=now,
                    link="/assets/ledger?status=IDLE",
                )
            )
        pending_scrap = int(status_counts.get(AssetStatus.PENDING_SCRAP, 0))
        if pending_scrap:
            items.append(
                NotificationItem(
                    id="asset-pending-scrap",
                    category="asset",
                    level="warning",
                    title=f"{pending_scrap} 台资产待报废处理",
                    description="资产已提交报废申请，请尽快完成后续处置流程。",
                    occurred_at=now,
                    link="/assets/ledger?status=PENDING_SCRAP",
                )
            )

        due_borrow_conditions = [
            AssetRequest.status == RequestStatus.BORROWED,
            AssetRequest.expected_return_date.is_not(None),
            AssetRequest.expected_return_date
            <= today + timedelta(days=settings.BORROW_REMINDER_DAYS),
        ]
        if context.has_permission("asset:request:review") and not is_self_only(
            context, "requisition"
        ):
            allowed = await scoped_dept_ids(
                self.session, context, resource="requisition"
            )
            if allowed is not None:
                if allowed:
                    due_borrow_conditions.append(
                        or_(
                            AssetRequest.applicant_id == context.user.id,
                            AssetRequest.applicant_dept_id.in_(allowed),
                        )
                    )
                else:
                    due_borrow_conditions.append(
                        AssetRequest.applicant_id == context.user.id
                    )
        else:
            due_borrow_conditions.append(
                AssetRequest.applicant_id == context.user.id
            )
        domain_condition = category_domain_condition(
            AssetRequest.category_id, context, "requisition"
        )
        if domain_condition is not None:
            due_borrow_conditions.append(domain_condition)
        due_borrows = list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(*due_borrow_conditions)
                    .order_by(
                        AssetRequest.expected_return_date.asc(),
                        AssetRequest.id.asc(),
                    )
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        for request in due_borrows:
            overdue_days = (
                (today - request.expected_return_date).days
                if request.expected_return_date
                else 0
            )
            if request.applicant_id == context.user.id:
                link = "/assets/mine"
                target = "你借用"
            else:
                link = "/assets/review?status=BORROWED"
                target = f"{request.applicant_name} 借用"
            items.append(
                NotificationItem(
                    id=f"borrow-due-{request.id}",
                    category="asset",
                    level="danger" if overdue_days > 0 else "warning",
                    title=(
                        f"{request.asset_name} 已逾期 {overdue_days} 天未归还"
                        if overdue_days > 0
                        else f"{request.asset_name} 将于 "
                        f"{request.expected_return_date:%m-%d} 到期"
                    ),
                    description=(
                        f"{target}的 {request.asset_no}（{request.request_no}），"
                        "请及时办理归还。"
                    ),
                    occurred_at=now,
                    link=link,
                )
            )

        if context.has_permission("asset:inventory:view"):
            allowed = await scoped_dept_ids(
                self.session, context, resource="inventory"
            )
            inventory_conditions: list = [
                InventoryTask.status == InventoryStatus.IN_PROGRESS,
                InventoryTask.planned_date.is_not(None),
                InventoryTask.planned_date
                <= today + timedelta(days=settings.INVENTORY_REMINDER_DAYS),
            ]
            if is_self_only(context, "inventory"):
                inventory_conditions.append(
                    InventoryTask.created_by_id == context.user.id
                )
            elif allowed is not None:
                inventory_conditions.append(
                    InventoryTask.scope_dept_id.in_(allowed) if allowed else false()
                )
            domain_condition = category_domain_condition(
                InventoryTask.scope_category_id, context, "inventory"
            )
            if domain_condition is not None:
                inventory_conditions.append(domain_condition)
            inventory_total = int(
                await self.session.scalar(
                    select(func.count(InventoryTask.id)).where(
                        *inventory_conditions
                    )
                )
                or 0
            )
            inventory_overdue = int(
                await self.session.scalar(
                    select(func.count(InventoryTask.id)).where(
                        *inventory_conditions,
                        InventoryTask.planned_date < today,
                    )
                )
                or 0
            )
            if inventory_total:
                items.append(
                    NotificationItem(
                        id="inventory-due",
                        category="inventory",
                        level="danger" if inventory_overdue else "warning",
                        title=(
                            f"{inventory_overdue} 个盘点任务已逾期"
                            if inventory_overdue
                            else f"{inventory_total} 个盘点任务即将到期"
                        ),
                        description="请在到期提醒中心查看盘点任务计划日期，及时完成盘点核对。",
                        occurred_at=now,
                        link="/assets/reminders?category=INVENTORY",
                    )
                )

        if context.has_permission("system:ldap:view"):
            config = (
                await self.session.execute(
                    select(LdapConfig).order_by(LdapConfig.id).limit(1)
                )
            ).scalar_one_or_none()
            if config is not None and config.enabled:
                if config.last_sync_status == "FAILED":
                    items.append(
                        NotificationItem(
                            id=f"ldap-sync-{config.last_sync_at or config.id}",
                            category="ldap",
                            level="danger",
                            title="域控同步执行失败",
                            description=(config.last_sync_message or "请查看同步日志了解失败原因")[:180],
                            occurred_at=config.last_sync_at or now,
                            link="/system/ldap",
                        )
                    )
                elif config.last_sync_status == "PARTIAL":
                    items.append(
                        NotificationItem(
                            id=f"ldap-sync-{config.last_sync_at or config.id}",
                            category="ldap",
                            level="warning",
                            title="域控同步部分成功",
                            description=(config.last_sync_message or "部分数据同步失败，请查看同步日志")[:180],
                            occurred_at=config.last_sync_at or now,
                            link="/system/ldap",
                        )
                    )
                elif config.last_sync_status == "RUNNING":
                    items.append(
                        NotificationItem(
                            id="ldap-sync-running",
                            category="ldap",
                            level="info",
                            title="域控同步正在执行",
                            description="组织与人员数据正在同步，完成后可在域控同步页面查看结果。",
                            occurred_at=config.last_sync_at or now,
                            link="/system/ldap",
                        )
                    )

        if context.has_permission("system:audit:view"):
            since = now - timedelta(hours=24)
            security_conditions = [
                AuditLog.action == "auth.login",
                AuditLog.status == "FAILED",
                AuditLog.created_at >= since,
            ]
            if is_self_only(context):
                security_conditions.append(AuditLog.user_id == context.user.id)
            failed_logins = int(
                await self.session.scalar(
                    select(func.count(AuditLog.id)).where(*security_conditions)
                )
                or 0
            )
            if failed_logins >= 3:
                items.append(
                    NotificationItem(
                        id=f"security-login-failed-{today.isoformat()}",
                        category="security",
                        level="warning",
                        title=f"近 24 小时有 {failed_logins} 次登录失败",
                        description="存在连续登录失败记录，建议在审计日志中核查来源 IP 与账号。",
                        occurred_at=now,
                        link="/system/audit?action=auth.login&status=FAILED",
                    )
                )

        items.sort(key=lambda item: (_LEVEL_WEIGHT.get(item.level, 9), -item.occurred_at.timestamp()))
        return NotificationSummary(
            items=items,
            total=len(items),
            warning_count=sum(1 for item in items if item.level == "warning"),
            danger_count=sum(1 for item in items if item.level == "danger"),
            generated_at=now,
        )
