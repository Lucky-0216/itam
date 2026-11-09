from __future__ import annotations

from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import RequestStatus
from app.core.asset_ops import SCRAP_ACTIVE_STATUSES, TRANSFER_ACTIVE_STATUSES
from app.core.assets import ASSET_STATUS_LABELS, AssetStatus
from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.core.maintenance import (
    MAINTENANCE_ACTIVE_STATUSES,
    MAINTENANCE_NO_PREFIX,
    MAINTENANCE_PRIORITY_LABELS,
    MAINTENANCE_PRIORITY_TAG_TYPES,
    MAINTENANCE_RECORD_TYPE_LABELS,
    MAINTENANCE_STATUS_LABELS,
    MAINTENANCE_STATUS_TAG_TYPES,
    MaintenanceRecordType,
    MaintenanceStatus,
    assert_maintenance_transition,
)
from app.models import (
    Asset,
    AssetHistory,
    AssetMaintenance,
    AssetMaintenanceRecord,
    AssetRequest,
    AssetScrap,
    AssetTransfer,
    Role,
    User,
    user_roles,
)
from app.models.base import now_cst
from app.schemas.maintenance import (
    MaintenanceAcceptPayload,
    MaintenanceApprovePayload,
    MaintenanceAssetOut,
    MaintenanceAssetPageOut,
    MaintenanceCancelPayload,
    MaintenanceComment,
    MaintenanceCompletePayload,
    MaintenanceCreate,
    MaintenanceOut,
    MaintenancePageOut,
    MaintenanceRecordCreate,
    MaintenanceRecordOut,
)
from app.services.asset_snapshot import asset_snapshot
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_domain_condition,
    category_domain_allowed,
    is_self_only,
    scoped_dept_ids,
)
from app.services.txn import commit_or_conflict

STATUS_CONFLICT_MESSAGE = "资产状态已变更，请刷新后重试"
REPAIRABLE_ASSET_STATUSES = (
    AssetStatus.IN_USE,
    AssetStatus.IN_STOCK,
    AssetStatus.BORROWED,
)
PENDING_REQUEST_STATUSES = (
    RequestStatus.PENDING_APPROVAL,
    RequestStatus.PENDING_OUTBOUND,
    RequestStatus.PENDING_RETURN,
)


def _user_name(user: User) -> str:
    return user.real_name or user.username


class MaintenanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _next_no(self, column, prefix: str) -> str:
        head = f"{prefix}-{now_cst():%Y%m}-"
        max_no = await self.session.scalar(
            select(func.max(column)).where(column.like(f"{head}%"))
        )
        sequence = 1
        if max_no:
            suffix = max_no[len(head) :]
            if suffix.isdigit():
                sequence = int(suffix) + 1
        return f"{head}{sequence:04d}"

    async def _get_asset(self, asset_id: int, *, for_update: bool = False) -> Asset:
        stmt = select(Asset).where(Asset.id == asset_id, Asset.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        asset = (await self.session.execute(stmt)).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("资产不存在")
        return asset

    async def _get_order(
        self, order_id: int, *, for_update: bool = False
    ) -> AssetMaintenance:
        stmt = select(AssetMaintenance).where(AssetMaintenance.id == order_id)
        if for_update:
            stmt = stmt.with_for_update()
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if item is None:
            raise NotFoundError("维修工单不存在")
        return item

    async def _allowed_depts(self, context: AuthContext) -> set[int] | None:
        return await scoped_dept_ids(self.session, context, resource="maintenance")

    @staticmethod
    def _order_domain_condition(context: AuthContext):
        domain_condition = asset_domain_condition(context, "maintenance")
        if domain_condition is None:
            return None
        return AssetMaintenance.asset_id.in_(
            select(Asset.id).where(domain_condition)
        )

    @staticmethod
    def _in_order_domain(item: AssetMaintenance, context: AuthContext) -> bool:
        return category_domain_allowed(
            item.asset.category, context, "maintenance"
        )

    @staticmethod
    def _in_scope(dept_id: int | None, allowed: set[int] | None) -> bool:
        return allowed is None or (dept_id is not None and dept_id in allowed)

    def _manager_scope(
        self, item: AssetMaintenance, context: AuthContext, allowed: set[int] | None
    ) -> bool:
        if not self._in_order_domain(item, context):
            return False
        if is_self_only(context, "maintenance"):
            return item.applicant_id == context.user.id
        return self._in_scope(item.from_dept_id, allowed)

    @staticmethod
    def _is_manager(context: AuthContext) -> bool:
        return context.has_permission("asset:maintenance:approve") or (
            context.has_permission("asset:maintenance:accept")
        )

    def _can_view(
        self, item: AssetMaintenance, context: AuthContext, allowed: set[int] | None
    ) -> bool:
        if context.is_superuser:
            return True
        if not self._in_order_domain(item, context):
            return False
        user_id = context.user.id
        if item.repairer_id == user_id:
            return True
        if self._is_manager(context):
            return self._manager_scope(item, context, allowed)
        if is_self_only(context, "maintenance"):
            return item.applicant_id == user_id
        return item.applicant_id == user_id or item.from_custodian_id == user_id

    async def _assert_view(
        self, item: AssetMaintenance, context: AuthContext
    ) -> set[int] | None:
        allowed = await self._allowed_depts(context)
        if not self._can_view(item, context, allowed):
            raise PermissionDenied("无权查看该维修工单")
        return allowed

    def _can_operate(
        self,
        item: AssetMaintenance,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> bool:
        if not context.has_permission("asset:maintenance:repair"):
            return False
        if not self._in_order_domain(item, context):
            return False
        if item.repairer_id == context.user.id:
            return True
        return context.has_permission(
            "asset:maintenance:accept"
        ) and self._manager_scope(item, context, allowed)

    def _can_cancel(
        self,
        item: AssetMaintenance,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> bool:
        if item.status not in (
            MaintenanceStatus.PENDING_APPROVAL,
            MaintenanceStatus.PENDING_REPAIR,
        ):
            return False
        if item.status == MaintenanceStatus.PENDING_APPROVAL and (
            item.applicant_id == context.user.id
        ):
            return True
        if context.has_permission("asset:maintenance:cancel"):
            return self._manager_scope(item, context, allowed)
        return context.has_permission(
            "asset:maintenance:approve"
        ) and self._manager_scope(item, context, allowed)

    def _order_out(
        self,
        item: AssetMaintenance,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> MaintenanceOut:
        asset = item.asset
        manager_scope = self._manager_scope(item, context, allowed)
        can_review = (
            item.status == MaintenanceStatus.PENDING_APPROVAL
            and context.has_permission("asset:maintenance:approve")
            and manager_scope
        )
        can_operate = self._can_operate(item, context, allowed)
        return MaintenanceOut(
            id=item.id,
            maintenance_no=item.maintenance_no,
            status=item.status,
            status_label=MAINTENANCE_STATUS_LABELS.get(item.status, item.status),
            status_tag_type=MAINTENANCE_STATUS_TAG_TYPES.get(item.status, "info"),
            priority=item.priority,
            priority_label=MAINTENANCE_PRIORITY_LABELS.get(item.priority, item.priority),
            priority_tag_type=MAINTENANCE_PRIORITY_TAG_TYPES.get(item.priority, "info"),
            asset_id=item.asset_id,
            asset_no=item.asset_no,
            asset_name=item.asset_name,
            asset_version=asset.version,
            asset_status=asset.status,
            asset_status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
            from_status=item.from_status,
            from_status_label=ASSET_STATUS_LABELS.get(item.from_status, item.from_status),
            from_dept_id=item.from_dept_id,
            from_dept_name=item.from_dept_name,
            from_custodian_id=item.from_custodian_id,
            from_custodian_name=item.from_custodian_name,
            from_location=item.from_location,
            fault_description=item.fault_description,
            expected_date=item.expected_date,
            applicant_id=item.applicant_id,
            applicant_name=item.applicant_name,
            applicant_dept_id=item.applicant_dept_id,
            applicant_dept_name=item.applicant_dept_name,
            approver_name=item.approver_name,
            approved_at=item.approved_at,
            approval_comment=item.approval_comment,
            repairer_id=item.repairer_id,
            repairer_name=item.repairer_name,
            assigned_at=item.assigned_at,
            started_at=item.started_at,
            finished_at=item.finished_at,
            repair_result=item.repair_result,
            total_cost=item.total_cost,
            accepted_by_name=item.accepted_by_name,
            accepted_at=item.accepted_at,
            acceptance_comment=item.acceptance_comment,
            cancelled_at=item.cancelled_at,
            cancel_reason=item.cancel_reason,
            records=[
                MaintenanceRecordOut(
                    id=record.id,
                    record_type=record.record_type,
                    record_type_label=MAINTENANCE_RECORD_TYPE_LABELS.get(
                        record.record_type, record.record_type
                    ),
                    content=record.content,
                    cost=record.cost,
                    operator_name=record.operator_name,
                    occurred_at=record.occurred_at,
                    created_at=record.created_at,
                )
                for record in item.records
            ],
            can_approve=can_review,
            can_reject=can_review,
            can_start=item.status == MaintenanceStatus.PENDING_REPAIR and can_operate,
            can_add_record=item.status == MaintenanceStatus.REPAIRING and can_operate,
            can_complete=item.status == MaintenanceStatus.REPAIRING and can_operate,
            can_accept=item.status == MaintenanceStatus.PENDING_ACCEPTANCE
            and context.has_permission("asset:maintenance:accept")
            and manager_scope,
            can_cancel=self._can_cancel(item, context, allowed),
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    async def _assert_asset_available(
        self, asset: Asset, *, exclude_order_id: int | None = None
    ) -> None:
        if asset.status not in REPAIRABLE_ASSET_STATUSES:
            raise BizError("该资产当前状态不允许报修")

        maintenance_conditions = [
            AssetMaintenance.asset_id == asset.id,
            AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES),
        ]
        if exclude_order_id is not None:
            maintenance_conditions.append(AssetMaintenance.id != exclude_order_id)
        if await self.session.scalar(
            select(AssetMaintenance.id).where(*maintenance_conditions).limit(1)
        ):
            raise BizError("该资产已有处理中的维修工单")

        if await self.session.scalar(
            select(AssetTransfer.id)
            .where(
                AssetTransfer.asset_id == asset.id,
                AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
            )
            .limit(1)
        ):
            raise BizError("该资产存在处理中的调拨单，暂不能报修")

        if await self.session.scalar(
            select(AssetScrap.id)
            .where(
                AssetScrap.asset_id == asset.id,
                AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
            )
            .limit(1)
        ):
            raise BizError("该资产存在处理中的报废单，暂不能报修")

        if await self.session.scalar(
            select(AssetRequest.id)
            .where(
                AssetRequest.asset_id == asset.id,
                AssetRequest.status.in_(PENDING_REQUEST_STATUSES),
            )
            .limit(1)
        ):
            raise BizError("该资产存在处理中的领用/借用/归还单据，暂不能报修")

    async def _assert_can_report(self, asset: Asset, context: AuthContext) -> None:
        if not category_domain_allowed(asset.category, context, "maintenance"):
            raise PermissionDenied("无权报修该分类下的资产")
        if is_self_only(context, "maintenance"):
            if context.user.id not in (asset.custodian_id, asset.created_by_id):
                raise PermissionDenied("只能报修本人持有或本人创建的资产")
            return
        allowed = await self._allowed_depts(context)
        if allowed is not None and asset.dept_id not in allowed:
            raise PermissionDenied("无权报修该部门的资产")

    async def option_assets(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> MaintenanceAssetPageOut:
        allowed = await self._allowed_depts(context)
        conditions: list = [
            Asset.deleted_at.is_(None),
            Asset.status.in_(REPAIRABLE_ASSET_STATUSES),
        ]
        domain_condition = asset_domain_condition(context, "maintenance")
        if domain_condition is not None:
            conditions.append(domain_condition)
        if is_self_only(context, "maintenance"):
            conditions.append(
                or_(
                    Asset.custodian_id == context.user.id,
                    Asset.created_by_id == context.user.id,
                )
            )
        elif allowed is not None:
            conditions.append(Asset.dept_id.in_(allowed) if allowed else false())
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Asset.asset_no.like(like),
                    Asset.name.like(like),
                    Asset.serial_no.like(like),
                )
            )
        if (
            not is_self_only(context, "maintenance")
            and not self._is_manager(context)
            and not context.has_permission("asset:maintenance:repair")
        ):
            conditions.append(
                or_(Asset.custodian_id == context.user.id, Asset.custodian_id.is_(None))
            )
        conditions.append(
            Asset.id.notin_(
                select(AssetMaintenance.asset_id).where(
                    AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES)
                )
            )
        )
        conditions.append(
            Asset.id.notin_(
                select(AssetTransfer.asset_id).where(
                    AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES)
                )
            )
        )
        conditions.append(
            Asset.id.notin_(
                select(AssetScrap.asset_id).where(
                    AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES)
                )
            )
        )
        conditions.append(
            Asset.id.notin_(
                select(AssetRequest.asset_id).where(
                    AssetRequest.status.in_(PENDING_REQUEST_STATUSES)
                )
            )
        )

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Asset).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return MaintenanceAssetPageOut(
            items=[
                MaintenanceAssetOut(
                    id=asset.id,
                    asset_no=asset.asset_no,
                    name=asset.name,
                    category_name=asset.category.name if asset.category else None,
                    model_name=asset.model.name if asset.model else None,
                    serial_no=asset.serial_no,
                    location=asset.location,
                    dept_id=asset.dept_id,
                    dept_name=asset.dept.name if asset.dept else None,
                    custodian_id=asset.custodian_id,
                    custodian_name=asset.custodian.real_name if asset.custodian else None,
                    status=asset.status,
                    status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
                    version=asset.version,
                )
                for asset in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def option_repairers(
        self, keyword: str | None
    ) -> list[dict[str, object]]:
        conditions: list = [
            User.status == 1,
            Role.code.in_(("REPAIRER", "ASSET_ADMIN", "SUPER_ADMIN")),
        ]
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    User.real_name.like(like),
                    User.username.like(like),
                    User.employee_no.like(like),
                )
            )
        rows = (
            (
                await self.session.execute(
                    select(User)
                    .join(user_roles, user_roles.c.user_id == User.id)
                    .join(Role, Role.id == user_roles.c.role_id)
                    .where(*conditions)
                    .distinct()
                    .order_by(User.id)
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": user.id,
                "name": _user_name(user),
                "username": user.username,
                "dept_id": user.dept_id,
                "dept_name": user.dept.name if user.dept else None,
            }
            for user in rows
        ]

    async def list_orders(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        status: str | None,
        priority: str | None,
        page: int,
        page_size: int,
    ) -> MaintenancePageOut:
        allowed = await self._allowed_depts(context)
        conditions: list = []
        user_id = context.user.id
        domain_condition = self._order_domain_condition(context)
        if domain_condition is not None:
            conditions.append(domain_condition)
        if is_self_only(context, "maintenance"):
            conditions.append(
                or_(
                    AssetMaintenance.applicant_id == user_id,
                    AssetMaintenance.repairer_id == user_id,
                )
            )
        elif self._is_manager(context):
            if allowed is not None:
                conditions.append(
                    AssetMaintenance.from_dept_id.in_(allowed)
                    if allowed
                    else false()
                )
        elif context.has_permission("asset:maintenance:repair"):
            conditions.append(
                or_(
                    AssetMaintenance.repairer_id == user_id,
                    AssetMaintenance.applicant_id == user_id,
                    AssetMaintenance.from_custodian_id == user_id,
                )
            )
        else:
            conditions.append(
                or_(
                    AssetMaintenance.applicant_id == user_id,
                    AssetMaintenance.from_custodian_id == user_id,
                )
            )
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetMaintenance.maintenance_no.like(like),
                    AssetMaintenance.asset_no.like(like),
                    AssetMaintenance.asset_name.like(like),
                    AssetMaintenance.applicant_name.like(like),
                    AssetMaintenance.repairer_name.like(like),
                )
            )
        if status:
            if status not in MAINTENANCE_STATUS_LABELS:
                raise BizError("工单状态取值不正确")
            conditions.append(AssetMaintenance.status == status)
        if priority:
            if priority not in MAINTENANCE_PRIORITY_LABELS:
                raise BizError("优先级取值不正确")
            conditions.append(AssetMaintenance.priority == priority)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AssetMaintenance).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await self.session.execute(
                    select(AssetMaintenance)
                    .where(*conditions)
                    .order_by(
                        AssetMaintenance.created_at.desc(), AssetMaintenance.id.desc()
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return MaintenancePageOut(
            items=[self._order_out(item, context, allowed) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_order(self, order_id: int, context: AuthContext) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        return self._order_out(item, context, allowed)

    async def create_order(
        self, payload: MaintenanceCreate, context: AuthContext
    ) -> MaintenanceOut:
        asset = await self._get_asset(payload.asset_id)
        await self._assert_can_report(asset, context)
        await self._assert_asset_available(asset)

        item = AssetMaintenance(
            maintenance_no=await self._next_no(
                AssetMaintenance.maintenance_no, MAINTENANCE_NO_PREFIX
            ),
            status=MaintenanceStatus.PENDING_APPROVAL,
            priority=payload.priority,
            asset_id=asset.id,
            asset_no=asset.asset_no,
            asset_name=asset.name,
            asset_version=asset.version,
            from_status=asset.status,
            from_dept_id=asset.dept_id,
            from_dept_name=asset.dept.name if asset.dept else None,
            from_custodian_id=asset.custodian_id,
            from_custodian_name=asset.custodian.real_name if asset.custodian else None,
            from_location=asset.location,
            fault_description=payload.fault_description,
            expected_date=payload.expected_date,
            applicant_id=context.user.id,
            applicant_name=_user_name(context.user),
            applicant_dept_id=context.user.dept_id,
            applicant_dept_name=context.user.dept.name if context.user.dept else None,
            records=[],
        )
        self.session.add(item)
        await self.session.flush()
        item.asset = asset
        await self.audit.record(
            action="asset.maintenance.create",
            module="asset",
            summary=f"发起报修：{asset.name}（{asset.asset_no}）",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={
                "status": item.status,
                "priority": item.priority,
                "fault": payload.fault_description,
            },
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, await self._allowed_depts(context))

    async def approve_order(
        self,
        order_id: int,
        payload: MaintenanceApprovePayload,
        context: AuthContext,
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if not self._manager_scope(item, context, allowed):
            raise PermissionDenied("无权审批该部门的维修工单")
        if item.status != MaintenanceStatus.PENDING_APPROVAL:
            raise BizError("当前维修工单不在待审批状态")

        repairer = await self.session.get(User, payload.repairer_id)
        if repairer is None or repairer.status != 1:
            raise BizError("指定的维修人员不存在或已停用")

        asset = await self._get_asset(item.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status not in REPAIRABLE_ASSET_STATUSES:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        await self._assert_asset_available(asset, exclude_order_id=item.id)

        before = asset_snapshot(asset)
        asset.status = AssetStatus.REPAIRING
        after = asset_snapshot(asset)

        assert_maintenance_transition(item.status, MaintenanceStatus.PENDING_REPAIR)
        item.status = MaintenanceStatus.PENDING_REPAIR
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = payload.comment
        item.repairer_id = repairer.id
        item.repairer_name = _user_name(repairer)
        item.assigned_at = item.approved_at
        if payload.expected_date is not None:
            item.expected_date = payload.expected_date

        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="REPAIR_APPROVED",
                action_label="送修审批通过",
                from_status=before["status"],
                to_status=asset.status,
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=_user_name(context.user),
                summary=(
                    f"维修单 {item.maintenance_no} 审批通过，指派"
                    f" {item.repairer_name} 维修"
                ),
            )
        )
        await self.session.flush()
        item.asset_version = asset.version
        await self.audit.record(
            action="asset.maintenance.approve",
            module="asset",
            summary=f"审批维修：{item.maintenance_no} → {item.repairer_name}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            before={"asset_status": before["status"]},
            after={"asset_status": asset.status, "repairer": item.repairer_name},
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def reject_order(
        self, order_id: int, payload: MaintenanceComment, context: AuthContext
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if not self._manager_scope(item, context, allowed):
            raise PermissionDenied("无权审批该部门的维修工单")
        if item.status != MaintenanceStatus.PENDING_APPROVAL:
            raise BizError("当前维修工单不在待审批状态")
        assert_maintenance_transition(item.status, MaintenanceStatus.REJECTED)
        item.status = MaintenanceStatus.REJECTED
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = payload.comment
        await self.audit.record(
            action="asset.maintenance.reject",
            module="asset",
            summary=f"驳回维修：{item.maintenance_no}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={"status": item.status, "comment": payload.comment},
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def start_repair(self, order_id: int, context: AuthContext) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if item.status != MaintenanceStatus.PENDING_REPAIR:
            raise BizError("当前维修工单不在待维修状态")
        if not self._can_operate(item, context, allowed):
            raise PermissionDenied("仅指派的维修人员可开始维修")
        assert_maintenance_transition(item.status, MaintenanceStatus.REPAIRING)
        item.status = MaintenanceStatus.REPAIRING
        item.started_at = now_cst()
        await self.audit.record(
            action="asset.maintenance.start",
            module="asset",
            summary=f"开始维修：{item.maintenance_no}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={"status": item.status},
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def add_record(
        self,
        order_id: int,
        payload: MaintenanceRecordCreate,
        context: AuthContext,
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if item.status != MaintenanceStatus.REPAIRING:
            raise BizError("仅维修中的工单可以登记维修记录")
        if not self._can_operate(item, context, allowed):
            raise PermissionDenied("仅指派的维修人员可登记维修记录")

        if payload.record_type == MaintenanceRecordType.EXPENSE:
            if payload.cost is None:
                raise BizError("费用记录必须填写金额")
            cost = payload.cost
        else:
            cost = None
        record = AssetMaintenanceRecord(
            record_type=payload.record_type,
            content=payload.content,
            cost=cost,
            operator_id=context.user.id,
            operator_name=_user_name(context.user),
            occurred_at=payload.occurred_at or now_cst(),
        )
        item.records.append(record)
        item.total_cost = sum(
            (row.cost or Decimal("0.00"))
            for row in item.records
            if row.record_type == MaintenanceRecordType.EXPENSE
        )
        await self.audit.record(
            action="asset.maintenance.record",
            module="asset",
            summary=(
                f"登记{MAINTENANCE_RECORD_TYPE_LABELS.get(payload.record_type, '维修')}"
                f"：{item.maintenance_no}"
            ),
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={
                "record_type": payload.record_type,
                "content": payload.content,
                "cost": str(cost) if cost is not None else None,
            },
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def complete_repair(
        self,
        order_id: int,
        payload: MaintenanceCompletePayload,
        context: AuthContext,
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if item.status != MaintenanceStatus.REPAIRING:
            raise BizError("当前维修工单不在维修中状态")
        if not self._can_operate(item, context, allowed):
            raise PermissionDenied("仅指派的维修人员可完成维修")
        assert_maintenance_transition(item.status, MaintenanceStatus.PENDING_ACCEPTANCE)
        item.status = MaintenanceStatus.PENDING_ACCEPTANCE
        item.finished_at = now_cst()
        item.repair_result = payload.repair_result
        await self.audit.record(
            action="asset.maintenance.complete",
            module="asset",
            summary=f"维修完成待验收：{item.maintenance_no}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={"status": item.status, "result": payload.repair_result},
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def accept_order(
        self,
        order_id: int,
        payload: MaintenanceAcceptPayload,
        context: AuthContext,
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if not self._manager_scope(item, context, allowed):
            raise PermissionDenied("无权验收该部门的维修工单")
        if item.status != MaintenanceStatus.PENDING_ACCEPTANCE:
            raise BizError("当前维修工单不在待验收状态")

        asset = await self._get_asset(item.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status != AssetStatus.REPAIRING:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)

        restore_status = (
            item.from_status
            if item.from_status in REPAIRABLE_ASSET_STATUSES
            else AssetStatus.IN_STOCK
        )
        before = asset_snapshot(asset)
        asset.status = restore_status
        after = asset_snapshot(asset)

        assert_maintenance_transition(item.status, MaintenanceStatus.COMPLETED)
        item.status = MaintenanceStatus.COMPLETED
        item.accepted_by_id = context.user.id
        item.accepted_by_name = _user_name(context.user)
        item.accepted_at = now_cst()
        item.acceptance_comment = payload.comment

        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="REPAIR_COMPLETED",
                action_label="维修验收完成",
                from_status=before["status"],
                to_status=asset.status,
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=_user_name(context.user),
                summary=(
                    f"维修单 {item.maintenance_no} 验收通过，资产恢复为"
                    f" {ASSET_STATUS_LABELS.get(restore_status, restore_status)}"
                ),
            )
        )
        await self.session.flush()
        item.asset_version = asset.version
        await self.audit.record(
            action="asset.maintenance.accept",
            module="asset",
            summary=f"验收维修：{item.maintenance_no}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            before=before,
            after=after,
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)

    async def cancel_order(
        self,
        order_id: int,
        payload: MaintenanceCancelPayload,
        context: AuthContext,
    ) -> MaintenanceOut:
        item = await self._get_order(order_id)
        allowed = await self._assert_view(item, context)
        if item.status not in (
            MaintenanceStatus.PENDING_APPROVAL,
            MaintenanceStatus.PENDING_REPAIR,
        ):
            raise BizError("仅待审批或待维修的工单可以取消")
        if not self._can_cancel(item, context, allowed):
            raise PermissionDenied("无权取消该维修工单")

        if item.status == MaintenanceStatus.PENDING_REPAIR:
            asset = await self._get_asset(item.asset_id, for_update=True)
            if asset.status != AssetStatus.REPAIRING:
                raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
            restore_status = (
                item.from_status
                if item.from_status in REPAIRABLE_ASSET_STATUSES
                else AssetStatus.IN_STOCK
            )
            before = asset_snapshot(asset)
            asset.status = restore_status
            after = asset_snapshot(asset)
            self.session.add(
                AssetHistory(
                    asset_id=asset.id,
                    action="REPAIR_CANCELLED",
                    action_label="维修取消",
                    from_status=before["status"],
                    to_status=asset.status,
                    before_snapshot=before,
                    after_snapshot=after,
                    operator_id=context.user.id,
                    operator_name=_user_name(context.user),
                    summary=f"维修单 {item.maintenance_no} 取消，资产恢复原状态",
                )
            )
            await self.session.flush()
            item.asset_version = asset.version

        assert_maintenance_transition(item.status, MaintenanceStatus.CANCELLED)
        item.status = MaintenanceStatus.CANCELLED
        item.cancelled_at = now_cst()
        item.cancel_reason = payload.reason
        await self.audit.record(
            action="asset.maintenance.cancel",
            module="asset",
            summary=f"取消维修：{item.maintenance_no}",
            actor=context.user,
            resource_type="asset_maintenance",
            resource_id=item.id,
            after={"status": item.status, "reason": payload.reason},
        )
        await commit_or_conflict(
            self.session, message=STATUS_CONFLICT_MESSAGE, code=40911
        )
        return self._order_out(item, context, allowed)
