from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import RequestStatus, RequestType
from app.core.asset_ops import InventoryStatus
from app.core.assets import AssetStatus
from app.core.config import settings
from app.core.contract import ContractStatus
from app.core.reminder import (
    REMINDER_CATEGORY_LABELS,
    REMINDER_CATEGORY_LINKS,
    REMINDER_CATEGORY_ORDER,
    REMINDER_LEVEL_LABELS,
    REMINDER_LEVEL_ORDER,
    ReminderCategory,
    ReminderLevel,
)
from app.models import Asset, AssetContract, AssetRequest, AuditLog, InventoryTask, User
from app.models.base import now_cst
from app.schemas.reminder import (
    ReminderCategorySummary,
    ReminderItem,
    ReminderPage,
    ReminderScanOut,
    ReminderSummaryOut,
)
from app.services.audit_service import AuditService
from app.services.email_service import EmailNotifier
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_scope_conditions,
    category_domain_condition,
    contract_domain_condition,
    is_self_only,
    scoped_dept_ids,
)


@dataclass
class _Entry:
    key: str
    category: str
    level: str
    title: str
    description: str
    due_date: date | None
    days_left: int | None
    link: str
    source_no: str | None = None
    owner: str | None = None

    def to_item(self) -> ReminderItem:
        return ReminderItem(
            id=self.key,
            category=self.category,
            category_label=REMINDER_CATEGORY_LABELS.get(self.category, self.category),
            level=self.level,
            level_label=REMINDER_LEVEL_LABELS.get(self.level, self.level),
            title=self.title,
            description=self.description,
            due_date=self.due_date,
            days_left=self.days_left,
            source_no=self.source_no,
            owner=self.owner,
            link=self.link,
        )


def _sort_key(item: ReminderItem) -> tuple:
    return (
        REMINDER_LEVEL_ORDER.get(item.level, 9),
        item.due_date or date.max,
        REMINDER_CATEGORY_ORDER.get(item.category, 9),
        item.title,
    )


def _level_for_days(days_left: int, *, warn_within: int = 7) -> str:
    if days_left < 0:
        return ReminderLevel.DANGER
    if days_left <= warn_within:
        return ReminderLevel.WARNING
    return ReminderLevel.INFO


class ReminderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    def _allowed_categories(self, context: AuthContext) -> list[str]:
        categories: list[str] = []
        if context.has_permission("asset:ledger:view"):
            categories.append(ReminderCategory.WARRANTY)
        if context.has_permission("asset:contract:view"):
            categories.append(ReminderCategory.CONTRACT)
        categories.append(ReminderCategory.BORROW)
        if context.has_permission("asset:inventory:view"):
            categories.append(ReminderCategory.INVENTORY)
        return categories

    async def collect(self, context: AuthContext) -> list[ReminderItem]:
        today = now_cst().date()
        items: list[ReminderItem] = []
        if context.has_permission("asset:ledger:view"):
            items.extend(await self._warranty_items(context, today))
        if context.has_permission("asset:contract:view"):
            items.extend(await self._contract_items(context, today))
        items.extend(await self._borrow_items(context, today))
        if context.has_permission("asset:inventory:view"):
            items.extend(await self._inventory_items(context, today))
        items.sort(key=_sort_key)
        return items

    async def summary(self, context: AuthContext) -> ReminderSummaryOut:
        items = await self.collect(context)
        categories: list[ReminderCategorySummary] = []
        for category in self._allowed_categories(context):
            scoped = [item for item in items if item.category == category]
            categories.append(
                ReminderCategorySummary(
                    category=category,
                    label=REMINDER_CATEGORY_LABELS.get(category, category),
                    count=len(scoped),
                    danger_count=sum(
                        1 for item in scoped if item.level == ReminderLevel.DANGER
                    ),
                    warning_count=sum(
                        1 for item in scoped if item.level == ReminderLevel.WARNING
                    ),
                    info_count=sum(
                        1 for item in scoped if item.level == ReminderLevel.INFO
                    ),
                    link=REMINDER_CATEGORY_LINKS.get(category, "/assets/reminders"),
                )
            )
        return ReminderSummaryOut(
            total=len(items),
            danger_count=sum(
                1 for item in items if item.level == ReminderLevel.DANGER
            ),
            warning_count=sum(
                1 for item in items if item.level == ReminderLevel.WARNING
            ),
            info_count=sum(1 for item in items if item.level == ReminderLevel.INFO),
            categories=categories,
            email_enabled=settings.REMINDER_EMAIL_ENABLED,
            generated_at=now_cst(),
        )

    async def page(
        self,
        context: AuthContext,
        *,
        category: str | None,
        level: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> ReminderPage:
        items = await self.collect(context)
        if category:
            items = [item for item in items if item.category == category]
        if level:
            items = [item for item in items if item.level == level]
        needle = (keyword or "").strip().lower()
        if needle:
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    filter(
                        None,
                        (
                            item.title,
                            item.description,
                            item.source_no,
                            item.owner,
                            item.category_label,
                        ),
                    )
                ).lower()
            ]
        total = len(items)
        start = (page - 1) * page_size
        return ReminderPage(
            items=items[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _warranty_items(
        self, context: AuthContext, today: date
    ) -> list[ReminderItem]:
        conditions = await asset_scope_conditions(
            self.session, context, resource="asset"
        )
        limit_date = today + timedelta(days=settings.WARRANTY_REMINDER_DAYS)
        assets = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(
                        *conditions,
                        Asset.warranty_end.is_not(None),
                        Asset.warranty_end <= limit_date,
                        Asset.status != AssetStatus.SCRAPPED,
                    )
                    .order_by(Asset.warranty_end.asc(), Asset.id.asc())
                )
            )
            .scalars()
            .all()
        )
        items: list[ReminderItem] = []
        for asset in assets:
            if asset.warranty_end is None:
                continue
            days_left = (asset.warranty_end - today).days
            owner = (
                asset.custodian.real_name
                if asset.custodian
                else (asset.dept.name if asset.dept else None)
            )
            if days_left < 0:
                title = f"{asset.name} 保修已到期 {-days_left} 天"
                description = (
                    f"{asset.asset_no}（{asset.dept.name if asset.dept else '未归属部门'}）"
                    f"保修已于 {asset.warranty_end.isoformat()} 到期，请评估续保或更换。"
                )
            else:
                title = f"{asset.name} 将于 {days_left} 天后保修到期"
                description = (
                    f"{asset.asset_no}（{asset.dept.name if asset.dept else '未归属部门'}）"
                    f"保修截止 {asset.warranty_end.isoformat()}，请及时安排续保。"
                )
            items.append(
                _Entry(
                    key=f"warranty-asset-{asset.id}",
                    category=ReminderCategory.WARRANTY,
                    level=_level_for_days(days_left),
                    title=title,
                    description=description,
                    due_date=asset.warranty_end,
                    days_left=days_left,
                    link=f"/assets/ledger?keyword={quote(asset.asset_no)}",
                    source_no=asset.asset_no,
                    owner=owner,
                ).to_item()
            )
        return items

    async def _contract_items(
        self, context: AuthContext, today: date
    ) -> list[ReminderItem]:
        allowed = await scoped_dept_ids(self.session, context, resource="contract")
        conditions: list = [AssetContract.status == ContractStatus.ACTIVE]
        if is_self_only(context, "contract"):
            conditions.append(
                or_(
                    AssetContract.owner_id == context.user.id,
                    AssetContract.created_by_id == context.user.id,
                )
            )
        elif allowed is not None:
            conditions.append(
                AssetContract.dept_id.in_(allowed) if allowed else false()
            )
        domain_condition = contract_domain_condition(context)
        if domain_condition is not None:
            conditions.append(domain_condition)
        limit_date = today + timedelta(days=settings.CONTRACT_REMINDER_DAYS)
        contracts = list(
            (
                await self.session.execute(
                    select(AssetContract)
                    .where(*conditions, AssetContract.end_date <= limit_date)
                    .order_by(AssetContract.end_date.asc(), AssetContract.id.asc())
                )
            )
            .scalars()
            .all()
        )
        items: list[ReminderItem] = []
        for contract in contracts:
            days_left = (contract.end_date - today).days
            owner = (
                contract.owner.real_name
                if contract.owner
                else (contract.dept.name if contract.dept else contract.created_by_name)
            )
            if days_left < 0:
                title = f"合同「{contract.name}」已到期 {-days_left} 天"
                description = (
                    f"{contract.contract_no} 结束日期为 {contract.end_date.isoformat()}，"
                    "请尽快续签或办理终止。"
                )
            else:
                title = f"合同「{contract.name}」将于 {days_left} 天后到期"
                description = (
                    f"{contract.contract_no} 结束日期为 {contract.end_date.isoformat()}，"
                    "请提前安排续签或终止。"
                )
            items.append(
                _Entry(
                    key=f"contract-{contract.id}",
                    category=ReminderCategory.CONTRACT,
                    level=_level_for_days(days_left),
                    title=title,
                    description=description,
                    due_date=contract.end_date,
                    days_left=days_left,
                    link=f"/assets/contracts?keyword={quote(contract.contract_no)}",
                    source_no=contract.contract_no,
                    owner=owner,
                ).to_item()
            )
        return items

    async def _borrow_items(
        self, context: AuthContext, today: date
    ) -> list[ReminderItem]:
        limit_date = today + timedelta(days=settings.BORROW_REMINDER_DAYS)
        conditions: list = [
            AssetRequest.request_type == RequestType.BORROW,
            AssetRequest.status == RequestStatus.BORROWED,
            AssetRequest.expected_return_date.is_not(None),
            AssetRequest.expected_return_date <= limit_date,
        ]
        if context.has_permission("asset:request:review") and not is_self_only(
            context, "requisition"
        ):
            allowed = await scoped_dept_ids(
                self.session, context, resource="requisition"
            )
            if allowed is None:
                pass
            elif allowed:
                conditions.append(
                    or_(
                        AssetRequest.applicant_id == context.user.id,
                        AssetRequest.applicant_dept_id.in_(allowed),
                    )
                )
            else:
                conditions.append(AssetRequest.applicant_id == context.user.id)
        else:
            conditions.append(AssetRequest.applicant_id == context.user.id)
        domain_condition = category_domain_condition(
            AssetRequest.category_id, context, "requisition"
        )
        if domain_condition is not None:
            conditions.append(domain_condition)
        requests = list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(*conditions)
                    .order_by(
                        AssetRequest.expected_return_date.asc(),
                        AssetRequest.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        items: list[ReminderItem] = []
        for request in requests:
            if request.expected_return_date is None:
                continue
            days_left = (request.expected_return_date - today).days
            is_mine = request.applicant_id == context.user.id
            description = (
                f"{request.request_no} · {request.asset_no} · 借用人 {request.applicant_name}"
                f"（{request.applicant_dept_name or '未归属部门'}），"
                f"预计归还日期 {request.expected_return_date.isoformat()}。"
            )
            if days_left < 0:
                title = f"{request.asset_name} 已逾期 {-days_left} 天未归还"
            else:
                title = f"{request.asset_name} 将于 {days_left} 天后归还到期"
            items.append(
                _Entry(
                    key=f"borrow-{request.id}",
                    category=ReminderCategory.BORROW,
                    level=ReminderLevel.DANGER
                    if days_left < 0
                    else ReminderLevel.WARNING,
                    title=title,
                    description=description,
                    due_date=request.expected_return_date,
                    days_left=days_left,
                    link=(
                        "/assets/mine"
                        if is_mine
                        else "/assets/review?status=BORROWED"
                    ),
                    source_no=request.request_no,
                    owner=request.applicant_name,
                ).to_item()
            )
        return items

    async def _inventory_items(
        self, context: AuthContext, today: date
    ) -> list[ReminderItem]:
        allowed = await scoped_dept_ids(self.session, context, resource="inventory")
        conditions: list = [
            InventoryTask.status == InventoryStatus.IN_PROGRESS,
            InventoryTask.planned_date.is_not(None),
            InventoryTask.planned_date
            <= today + timedelta(days=settings.INVENTORY_REMINDER_DAYS),
        ]
        if is_self_only(context, "inventory"):
            conditions.append(InventoryTask.created_by_id == context.user.id)
        elif allowed is not None:
            conditions.append(
                InventoryTask.scope_dept_id.in_(allowed) if allowed else false()
            )
        domain_condition = category_domain_condition(
            InventoryTask.scope_category_id, context, "inventory"
        )
        if domain_condition is not None:
            conditions.append(domain_condition)
        tasks = list(
            (
                await self.session.execute(
                    select(InventoryTask)
                    .where(*conditions)
                    .order_by(InventoryTask.planned_date.asc(), InventoryTask.id.asc())
                )
            )
            .scalars()
            .all()
        )
        items: list[ReminderItem] = []
        for task in tasks:
            if task.planned_date is None:
                continue
            days_left = (task.planned_date - today).days
            if days_left < 0:
                title = f"盘点任务「{task.name}」已逾期 {-days_left} 天"
                level = ReminderLevel.DANGER
            elif days_left == 0:
                title = f"盘点任务「{task.name}」今天到期"
                level = ReminderLevel.WARNING
            else:
                title = f"盘点任务「{task.name}」将于 {days_left} 天后到期"
                level = ReminderLevel.INFO
            description = (
                f"{task.task_no} · 范围 {task.scope_dept_name or '全部部门'}"
                f" · 计划日期 {task.planned_date.isoformat()}，请及时完成盘点核对。"
            )
            items.append(
                _Entry(
                    key=f"inventory-{task.id}",
                    category=ReminderCategory.INVENTORY,
                    level=level,
                    title=title,
                    description=description,
                    due_date=task.planned_date,
                    days_left=days_left,
                    link=f"/assets/inventory?keyword={quote(task.task_no)}",
                    source_no=task.task_no,
                    owner=task.created_by_name,
                ).to_item()
            )
        return items

    async def _global_counts(self, today: date) -> dict[str, int]:
        warranty_limit = today + timedelta(days=settings.WARRANTY_REMINDER_DAYS)
        contract_limit = today + timedelta(days=settings.CONTRACT_REMINDER_DAYS)
        borrow_limit = today + timedelta(days=settings.BORROW_REMINDER_DAYS)
        inventory_limit = today + timedelta(days=settings.INVENTORY_REMINDER_DAYS)
        warranty = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(
                    Asset.deleted_at.is_(None),
                    Asset.warranty_end.is_not(None),
                    Asset.warranty_end <= warranty_limit,
                    Asset.status != AssetStatus.SCRAPPED,
                )
            )
            or 0
        )
        contract = int(
            await self.session.scalar(
                select(func.count(AssetContract.id)).where(
                    AssetContract.status == ContractStatus.ACTIVE,
                    AssetContract.end_date <= contract_limit,
                )
            )
            or 0
        )
        borrow = int(
            await self.session.scalar(
                select(func.count(AssetRequest.id)).where(
                    AssetRequest.request_type == RequestType.BORROW,
                    AssetRequest.status == RequestStatus.BORROWED,
                    AssetRequest.expected_return_date.is_not(None),
                    AssetRequest.expected_return_date <= borrow_limit,
                )
            )
            or 0
        )
        inventory = int(
            await self.session.scalar(
                select(func.count(InventoryTask.id)).where(
                    InventoryTask.status == InventoryStatus.IN_PROGRESS,
                    InventoryTask.planned_date.is_not(None),
                    InventoryTask.planned_date <= inventory_limit,
                )
            )
            or 0
        )
        return {
            ReminderCategory.WARRANTY: warranty,
            ReminderCategory.CONTRACT: contract,
            ReminderCategory.BORROW: borrow,
            ReminderCategory.INVENTORY: inventory,
        }

    async def _scan_warranty_audits(self, today: date) -> int:
        today_start = datetime.combine(today, datetime.min.time())
        limit_date = today + timedelta(days=settings.WARRANTY_REMINDER_DAYS)
        assets = list(
            (
                await self.session.execute(
                    select(Asset).where(
                        Asset.deleted_at.is_(None),
                        Asset.warranty_end.is_not(None),
                        Asset.warranty_end <= limit_date,
                        Asset.status != AssetStatus.SCRAPPED,
                    )
                )
            )
            .scalars()
            .all()
        )
        existing = set(
            (
                await self.session.execute(
                    select(AuditLog.resource_id).where(
                        AuditLog.action == "asset.warranty.due_reminder",
                        AuditLog.resource_type == "asset",
                        AuditLog.created_at >= today_start,
                    )
                )
            )
            .scalars()
            .all()
        )
        created = 0
        for asset in assets:
            if asset.warranty_end is None or str(asset.id) in existing:
                continue
            days_left = (asset.warranty_end - today).days
            if days_left < 0:
                summary = (
                    f"保修到期提醒：{asset.asset_no} {asset.name} 已到期 "
                    f"{-days_left} 天，请评估续保或更换"
                )
            else:
                summary = (
                    f"保修到期提醒：{asset.asset_no} {asset.name} 将于 "
                    f"{asset.warranty_end.isoformat()} 到期（剩余 {days_left} 天）"
                )
            await self.audit.record(
                action="asset.warranty.due_reminder",
                module="资产管理",
                summary=summary,
                actor_name="系统计划任务",
                resource_type="asset",
                resource_id=asset.id,
                after={
                    "asset_no": asset.asset_no,
                    "warranty_end": asset.warranty_end.isoformat(),
                    "days_to_expiry": days_left,
                },
            )
            created += 1
        return created

    async def _scan_inventory_audits(self, today: date) -> int:
        today_start = datetime.combine(today, datetime.min.time())
        tasks = list(
            (
                await self.session.execute(
                    select(InventoryTask).where(
                        InventoryTask.status == InventoryStatus.IN_PROGRESS,
                        InventoryTask.planned_date.is_not(None),
                        InventoryTask.planned_date <= today,
                    )
                )
            )
            .scalars()
            .all()
        )
        existing = set(
            (
                await self.session.execute(
                    select(AuditLog.resource_id).where(
                        AuditLog.action == "asset.inventory.due_reminder",
                        AuditLog.resource_type == "inventory_task",
                        AuditLog.created_at >= today_start,
                    )
                )
            )
            .scalars()
            .all()
        )
        created = 0
        for task in tasks:
            if task.planned_date is None or str(task.id) in existing:
                continue
            overdue_days = (today - task.planned_date).days
            if overdue_days > 0:
                summary = (
                    f"盘点到期提醒：{task.task_no} {task.name} 已逾期 "
                    f"{overdue_days} 天，请尽快完成盘点"
                )
            else:
                summary = f"盘点到期提醒：{task.task_no} {task.name} 今日到期，请及时完成"
            await self.audit.record(
                action="asset.inventory.due_reminder",
                module="资产盘点",
                summary=summary,
                actor_name="系统计划任务",
                resource_type="inventory_task",
                resource_id=task.id,
                after={
                    "task_no": task.task_no,
                    "planned_date": task.planned_date.isoformat(),
                    "overdue_days": max(overdue_days, 0),
                },
            )
            created += 1
        return created

    async def scan(self, actor: User | None = None) -> ReminderScanOut:
        now = now_cst()
        today = now.date()
        today_start = datetime.combine(today, datetime.min.time())
        counts = await self._global_counts(today)
        total = sum(counts.values())
        already_scanned = bool(
            await self.session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "asset.reminder.scan",
                    AuditLog.created_at >= today_start,
                )
            )
        )
        if already_scanned:
            return ReminderScanOut(
                warranty=counts[ReminderCategory.WARRANTY],
                contract=counts[ReminderCategory.CONTRACT],
                borrow=counts[ReminderCategory.BORROW],
                inventory=counts[ReminderCategory.INVENTORY],
                total=total,
                created=0,
                already_scanned=True,
                email_status="SKIPPED",
                generated_at=now,
            )

        created = await self._scan_warranty_audits(today)
        created += await self._scan_inventory_audits(today)

        email_status = "SKIPPED"
        notifier = EmailNotifier()
        if total and notifier.enabled:
            digest = "\n".join(
                [
                    "ITAM 到期提醒汇总",
                    f"统计日期：{today.isoformat()}",
                    "",
                    f"保修到期：{counts[ReminderCategory.WARRANTY]} 项",
                    f"合同到期：{counts[ReminderCategory.CONTRACT]} 项",
                    f"借用到期：{counts[ReminderCategory.BORROW]} 项",
                    f"盘点任务：{counts[ReminderCategory.INVENTORY]} 项",
                    "",
                    "请登录 ITAM 系统，在「到期提醒」中查看明细并处理。",
                ]
            )
            email_status = await notifier.send_digest(
                f"【ITAM】到期提醒汇总（{today.isoformat()}）", digest
            )

        await self.audit.record(
            action="asset.reminder.scan",
            module="到期提醒",
            summary=(
                f"到期提醒扫描：保修 {counts[ReminderCategory.WARRANTY]}、"
                f"合同 {counts[ReminderCategory.CONTRACT]}、"
                f"借用 {counts[ReminderCategory.BORROW]}、"
                f"盘点 {counts[ReminderCategory.INVENTORY]}；"
                f"邮件 {email_status}"
            ),
            actor=actor,
            actor_name=None if actor else "系统计划任务",
            resource_type="asset_reminder",
            resource_id="daily",
            after={
                "warranty": counts[ReminderCategory.WARRANTY],
                "contract": counts[ReminderCategory.CONTRACT],
                "borrow": counts[ReminderCategory.BORROW],
                "inventory": counts[ReminderCategory.INVENTORY],
                "created_audits": created,
                "email_status": email_status,
            },
        )
        await self.session.commit()
        return ReminderScanOut(
            warranty=counts[ReminderCategory.WARRANTY],
            contract=counts[ReminderCategory.CONTRACT],
            borrow=counts[ReminderCategory.BORROW],
            inventory=counts[ReminderCategory.INVENTORY],
            total=total,
            created=created,
            already_scanned=False,
            email_status=email_status,
            generated_at=now,
        )
