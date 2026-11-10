from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    String,
    and_,
    cast,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from app.core.asset_flow import (
    ACTIVE_REQUEST_STATUSES,
    APPROVAL_STAGE_ROLES,
    REQUEST_STATUS_LABELS,
    REQUEST_TYPE_LABELS,
    ApprovalStage,
    RequestStatus,
)
from app.core.asset_ops import (
    INBOUND_STATUS_LABELS,
    INBOUND_TYPE_LABELS,
    INVENTORY_ADJUSTMENT_STATUS_LABELS,
    INVENTORY_STATUS_LABELS,
    SCRAP_ACTIVE_STATUSES,
    SCRAP_STATUS_LABELS,
    TRANSFER_ACTIVE_STATUSES,
    TRANSFER_STATUS_LABELS,
    InboundStatus,
    InventoryAdjustmentStatus,
    InventoryStatus,
    ScrapStatus,
    TransferStatus,
)
from app.core.config import settings
from app.core.exceptions import BizError
from app.core.maintenance import (
    MAINTENANCE_ACTIVE_STATUSES,
    MAINTENANCE_STATUS_LABELS,
    MaintenanceStatus,
)
from app.core.todos import (
    MY_BUSINESS_PATHS,
    TODO_CATEGORY_LABELS,
    TODO_CATEGORY_ORDER,
    TODO_TYPE_CATEGORY,
    TODO_TYPE_LABELS,
    TODO_TYPE_ORDER,
    TODO_TYPE_PATHS,
    TodoCategory,
    TodoType,
)
from app.models import (
    ApprovalTask,
    Asset,
    AssetCategory,
    AssetInbound,
    AssetInboundItem,
    AssetMaintenance,
    AssetRequest,
    AssetScrap,
    AssetTransfer,
    InventoryAdjustment,
    InventoryTask,
)
from app.models.base import now_cst
from app.schemas.todo import (
    TodoCategoryOut,
    TodoItemOut,
    TodoPageOut,
    TodoSummaryOut,
    TodoTypeCountOut,
)
from app.services import dingtalk_approval
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_domain_condition,
    is_self_only,
    scoped_dept_ids,
)

REQUEST_KINDS = ("REQUISITION", "BORROW", "RETURN")


class TodoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 通用条件 ----------

    @staticmethod
    def _scope_condition(column, allowed: set[int] | None):
        if allowed is None:
            return true()
        return column.in_(allowed) if allowed else false()

    def _record_scope(
        self,
        context: AuthContext,
        resource: str,
        column,
        allowed: set[int] | None,
        domain,
        self_column,
    ):
        scope = (
            self_column == context.user.id
            if is_self_only(context, resource)
            else self._scope_condition(column, allowed)
        )
        return and_(scope, domain)

    @staticmethod
    def _request_domain_condition(context: AuthContext):
        domains = context.allowed_domains("requisition")
        if domains is None:
            return true()
        return AssetRequest.category_id.in_(
            select(AssetCategory.id).where(AssetCategory.asset_domain.in_(domains))
        )

    @staticmethod
    def _asset_domain_condition(column, context: AuthContext, resource: str):
        condition = asset_domain_condition(context, resource)
        if condition is None:
            return true()
        return column.in_(select(Asset.id).where(condition))

    @staticmethod
    def _inventory_domain_condition(context: AuthContext):
        domains = context.allowed_domains("inventory")
        if domains is None:
            return true()
        return InventoryTask.scope_category_id.in_(
            select(AssetCategory.id).where(AssetCategory.asset_domain.in_(domains))
        )

    @staticmethod
    def _inbound_domain_condition(context: AuthContext):
        domains = context.allowed_domains("inbound")
        if domains is None:
            return true()
        return AssetInbound.id.in_(
            select(AssetInboundItem.inbound_id)
            .join(AssetCategory, AssetCategory.id == AssetInboundItem.category_id)
            .where(AssetCategory.asset_domain.in_(domains))
        )

    @staticmethod
    def _pending_task_exists(context: AuthContext):
        return exists(
            select(ApprovalTask.id).where(
                ApprovalTask.request_id == AssetRequest.id,
                ApprovalTask.approver_id == context.user.id,
                ApprovalTask.status == "PENDING",
            )
        )

    @staticmethod
    def _handled_stages(context: AuthContext) -> list[str]:
        if context.is_superuser:
            return [ApprovalStage.DEPT, ApprovalStage.ASSET]
        codes = {role.code for role in context.roles}
        return [
            stage
            for stage, role_code in APPROVAL_STAGE_ROLES.items()
            if role_code in codes
        ]

    def _request_approval_condition(self, context: AuthContext, allowed: set[int] | None):
        if not context.has_permission("asset:request:approve"):
            return false()
        flow_condition = and_(
            AssetRequest.flow_id.is_not(None),
            true() if context.is_superuser else self._pending_task_exists(context),
        )
        handled = self._handled_stages(context)
        legacy_parts = []
        if ApprovalStage.DEPT in handled:
            legacy_parts.append(
                and_(
                    AssetRequest.flow_id.is_(None),
                    AssetRequest.approval_stage == ApprovalStage.DEPT,
                )
            )
        if ApprovalStage.ASSET in handled:
            legacy_parts.append(
                and_(
                    AssetRequest.flow_id.is_(None),
                    or_(
                        AssetRequest.approval_stage == ApprovalStage.ASSET,
                        AssetRequest.approval_stage.is_(None),
                    ),
                )
            )
        legacy_condition = (
            and_(
                or_(*legacy_parts),
                self._scope_condition(AssetRequest.applicant_dept_id, allowed),
            )
            if legacy_parts and not is_self_only(context, "requisition")
            else false()
        )
        return and_(
            AssetRequest.status == RequestStatus.PENDING_APPROVAL,
            ~dingtalk_approval.running_link_exists(request_id=AssetRequest.id),
            or_(flow_condition, legacy_condition),
            self._request_domain_condition(context),
        )

    def _request_operation_scope(self, context: AuthContext, allowed):
        scope = (
            AssetRequest.applicant_id == context.user.id
            if is_self_only(context, "requisition")
            else self._scope_condition(AssetRequest.applicant_dept_id, allowed)
        )
        return and_(scope, self._request_domain_condition(context))

    def _request_outbound_condition(self, context: AuthContext, allowed):
        if not context.has_permission("asset:request:outbound"):
            return false()
        return and_(
            AssetRequest.status == RequestStatus.PENDING_OUTBOUND,
            self._request_operation_scope(context, allowed),
        )

    def _request_return_condition(self, context: AuthContext, allowed):
        if not context.has_permission("asset:return:confirm"):
            return false()
        return and_(
            AssetRequest.status == RequestStatus.PENDING_RETURN,
            self._request_operation_scope(context, allowed),
        )

    # ---------- UNION 列定义 ----------

    @staticmethod
    def _row_select(
        *,
        todo_type: str,
        ref_id,
        doc_no,
        subject,
        status,
        occurred_at,
        detail=None,
        related_name=None,
        dept_name=None,
        due_date=None,
        kind=None,
        quantity=None,
    ) -> Select:
        detail_col = (
            cast(detail, String(500))
            if detail is not None
            else cast(literal(None), String(500))
        )
        related_col = (
            cast(related_name, String(120))
            if related_name is not None
            else cast(literal(None), String(120))
        )
        dept_col = (
            cast(dept_name, String(120))
            if dept_name is not None
            else cast(literal(None), String(120))
        )
        due_col = due_date if due_date is not None else cast(literal(None), Date)
        kind_col = (
            cast(kind, String(40))
            if kind is not None
            else cast(literal(None), String(40))
        )
        quantity_col = (
            cast(quantity, Integer)
            if quantity is not None
            else cast(literal(None), Integer)
        )
        return select(
            literal(todo_type, String(40)).label("todo_type"),
            cast(ref_id, BigInteger).label("ref_id"),
            cast(doc_no, String(80)).label("doc_no"),
            cast(subject, String(255)).label("subject"),
            detail_col.label("detail"),
            cast(status, String(40)).label("status"),
            related_col.label("related_name"),
            dept_col.label("dept_name"),
            occurred_at.label("occurred_at"),
            due_col.label("due_date"),
            kind_col.label("kind"),
            quantity_col.label("quantity"),
        )

    def _request_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=AssetRequest.id,
            doc_no=AssetRequest.request_no,
            subject=func.coalesce(AssetRequest.asset_name, AssetRequest.category_name),
            status=AssetRequest.status,
            occurred_at=AssetRequest.created_at,
            detail=AssetRequest.reason,
            related_name=AssetRequest.applicant_name,
            dept_name=AssetRequest.applicant_dept_name,
            due_date=AssetRequest.expected_return_date,
            kind=AssetRequest.request_type,
        ).where(condition)

    def _transfer_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=AssetTransfer.id,
            doc_no=AssetTransfer.transfer_no,
            subject=AssetTransfer.asset_name,
            status=AssetTransfer.status,
            occurred_at=AssetTransfer.created_at,
            detail=func.coalesce(
                AssetTransfer.to_dept_name, AssetTransfer.to_custodian_name
            ),
            related_name=AssetTransfer.applicant_name,
            dept_name=AssetTransfer.from_dept_name,
            kind=literal("TRANSFER", String(40)),
        ).where(condition)

    def _scrap_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=AssetScrap.id,
            doc_no=AssetScrap.scrap_no,
            subject=AssetScrap.asset_name,
            status=AssetScrap.status,
            occurred_at=AssetScrap.created_at,
            detail=AssetScrap.reason,
            related_name=AssetScrap.applicant_name,
            dept_name=AssetScrap.from_dept_name,
            kind=literal("SCRAP", String(40)),
        ).where(condition)

    def _maintenance_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=AssetMaintenance.id,
            doc_no=AssetMaintenance.maintenance_no,
            subject=AssetMaintenance.asset_name,
            status=AssetMaintenance.status,
            occurred_at=AssetMaintenance.created_at,
            detail=AssetMaintenance.fault_description,
            related_name=AssetMaintenance.applicant_name,
            dept_name=AssetMaintenance.from_dept_name,
            due_date=AssetMaintenance.expected_date,
            kind=literal("MAINTENANCE", String(40)),
        ).where(condition)

    def _inventory_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=InventoryTask.id,
            doc_no=InventoryTask.task_no,
            subject=InventoryTask.name,
            status=InventoryTask.status,
            occurred_at=InventoryTask.created_at,
            detail=InventoryTask.scope_category_name,
            related_name=InventoryTask.created_by_name,
            dept_name=InventoryTask.scope_dept_name,
            due_date=InventoryTask.planned_date,
            kind=literal("INVENTORY", String(40)),
        ).where(condition)

    def _adjustment_select(self, todo_type: str, condition):
        return (
            self._row_select(
                todo_type=todo_type,
                ref_id=InventoryAdjustment.task_id,
                doc_no=InventoryAdjustment.adjustment_no,
                subject=InventoryAdjustment.task_name,
                status=InventoryAdjustment.status,
                occurred_at=InventoryAdjustment.requested_at,
                detail=InventoryAdjustment.reason,
                related_name=InventoryAdjustment.requested_by_name,
                dept_name=InventoryTask.scope_dept_name,
                kind=literal("INVENTORY_ADJUSTMENT", String(40)),
            )
            .select_from(InventoryAdjustment)
            .join(InventoryTask, InventoryTask.id == InventoryAdjustment.task_id)
            .where(condition)
        )

    def _inbound_select(self, todo_type: str, condition):
        return self._row_select(
            todo_type=todo_type,
            ref_id=AssetInbound.id,
            doc_no=AssetInbound.inbound_no,
            subject=func.coalesce(AssetInbound.supplier, AssetInbound.inbound_no),
            status=AssetInbound.status,
            occurred_at=AssetInbound.created_at,
            detail=AssetInbound.remark,
            related_name=AssetInbound.created_by_name,
            dept_name=AssetInbound.dept_name,
            kind=AssetInbound.inbound_type,
            quantity=AssetInbound.total_quantity,
        ).where(condition)

    # ---------- 待办分支 ----------

    async def _build_branches(
        self, context: AuthContext, scopes: dict[str, set[int] | None]
    ) -> list[Select]:
        request_scope = scopes.get("requisition")
        transfer_scope = scopes.get("transfer")
        scrap_scope = scopes.get("scrap")
        maintenance_scope = scopes.get("maintenance")
        inventory_scope = scopes.get("inventory")
        inbound_scope = scopes.get("inbound")
        user_id = context.user.id
        today = now_cst().date()
        due_limit = today + timedelta(days=settings.BORROW_REMINDER_DAYS)
        branches: list[Select] = []

        if context.has_permission("asset:request:approve"):
            branches.append(
                self._request_select(
                    TodoType.REQUEST_APPROVAL,
                    self._request_approval_condition(context, request_scope),
                )
            )
        if context.has_permission("asset:transfer:approve"):
            branches.append(
                self._transfer_select(
                    TodoType.TRANSFER_APPROVAL,
                    and_(
                        AssetTransfer.status == TransferStatus.PENDING_APPROVAL,
                        ~dingtalk_approval.running_link_exists(
                            transfer_id=AssetTransfer.id
                        ),
                        self._record_scope(
                            context,
                            "transfer",
                            AssetTransfer.from_dept_id,
                            transfer_scope,
                            self._asset_domain_condition(
                                AssetTransfer.asset_id, context, "transfer"
                            ),
                            AssetTransfer.applicant_id,
                        ),
                    ),
                )
            )
        if context.has_permission("asset:scrap:approve"):
            branches.append(
                self._scrap_select(
                    TodoType.SCRAP_APPROVAL,
                    and_(
                        AssetScrap.status == ScrapStatus.PENDING_APPROVAL,
                        self._record_scope(
                            context,
                            "scrap",
                            AssetScrap.from_dept_id,
                            scrap_scope,
                            self._asset_domain_condition(
                                AssetScrap.asset_id, context, "scrap"
                            ),
                            AssetScrap.applicant_id,
                        ),
                    ),
                )
            )
        if context.has_permission("asset:maintenance:approve"):
            branches.append(
                self._maintenance_select(
                    TodoType.MAINTENANCE_APPROVAL,
                    and_(
                        AssetMaintenance.status
                        == MaintenanceStatus.PENDING_APPROVAL,
                        self._record_scope(
                            context,
                            "maintenance",
                            AssetMaintenance.from_dept_id,
                            maintenance_scope,
                            self._asset_domain_condition(
                                AssetMaintenance.asset_id, context, "maintenance"
                            ),
                            AssetMaintenance.applicant_id,
                        ),
                    ),
                )
            )

        if context.has_permission("asset:inventory:approve"):
            branches.append(
                self._adjustment_select(
                    TodoType.INVENTORY_APPROVAL,
                    and_(
                        InventoryAdjustment.status
                        == InventoryAdjustmentStatus.PENDING,
                        self._record_scope(
                            context,
                            "inventory",
                            InventoryTask.scope_dept_id,
                            inventory_scope,
                            self._inventory_domain_condition(context),
                            InventoryAdjustment.requested_by_id,
                        ),
                    ),
                )
            )

        if context.has_permission("asset:request:outbound"):
            branches.append(
                self._request_select(
                    TodoType.REQUEST_OUTBOUND,
                    self._request_outbound_condition(context, request_scope),
                )
            )
        if context.has_permission("asset:return:confirm"):
            branches.append(
                self._request_select(
                    TodoType.REQUEST_RETURN,
                    self._request_return_condition(context, request_scope),
                )
            )
        if context.has_permission("asset:transfer:confirm"):
            branches.append(
                self._transfer_select(
                    TodoType.TRANSFER_CONFIRM,
                    and_(
                        AssetTransfer.status == TransferStatus.PENDING_TRANSFER,
                        self._record_scope(
                            context,
                            "transfer",
                            AssetTransfer.from_dept_id,
                            transfer_scope,
                            self._asset_domain_condition(
                                AssetTransfer.asset_id, context, "transfer"
                            ),
                            AssetTransfer.applicant_id,
                        ),
                    ),
                )
            )
        if context.has_permission("asset:scrap:confirm"):
            branches.append(
                self._scrap_select(
                    TodoType.SCRAP_CONFIRM,
                    and_(
                        AssetScrap.status == ScrapStatus.PENDING_DISPOSAL,
                        self._record_scope(
                            context,
                            "scrap",
                            AssetScrap.from_dept_id,
                            scrap_scope,
                            self._asset_domain_condition(
                                AssetScrap.asset_id, context, "scrap"
                            ),
                            AssetScrap.applicant_id,
                        ),
                    ),
                )
            )
        if context.has_permission("asset:inbound:confirm"):
            branches.append(
                self._inbound_select(
                    TodoType.INBOUND_CONFIRM,
                    and_(
                        AssetInbound.status == InboundStatus.PENDING,
                        self._record_scope(
                            context,
                            "inbound",
                            AssetInbound.dept_id,
                            inbound_scope,
                            self._inbound_domain_condition(context),
                            AssetInbound.created_by_id,
                        ),
                    ),
                )
            )

        if context.has_permission("asset:maintenance:repair"):
            repair_scope = self._record_scope(
                context,
                "maintenance",
                AssetMaintenance.from_dept_id,
                maintenance_scope,
                self._asset_domain_condition(
                    AssetMaintenance.asset_id, context, "maintenance"
                ),
                AssetMaintenance.applicant_id,
            )
            operate_condition = and_(
                self._asset_domain_condition(
                    AssetMaintenance.asset_id, context, "maintenance"
                ),
                or_(
                    AssetMaintenance.repairer_id == user_id,
                    and_(
                        context.has_permission("asset:maintenance:accept"),
                        repair_scope,
                    ),
                ),
            )
            branches.append(
                self._maintenance_select(
                    TodoType.MAINTENANCE_REPAIR,
                    and_(
                        AssetMaintenance.status.in_(
                            (
                                MaintenanceStatus.PENDING_REPAIR,
                                MaintenanceStatus.REPAIRING,
                            )
                        ),
                        operate_condition,
                    ),
                )
            )
        if context.has_permission("asset:maintenance:accept"):
            branches.append(
                self._maintenance_select(
                    TodoType.MAINTENANCE_ACCEPT,
                    and_(
                        AssetMaintenance.status
                        == MaintenanceStatus.PENDING_ACCEPTANCE,
                        self._record_scope(
                            context,
                            "maintenance",
                            AssetMaintenance.from_dept_id,
                            maintenance_scope,
                            self._asset_domain_condition(
                                AssetMaintenance.asset_id, context, "maintenance"
                            ),
                            AssetMaintenance.applicant_id,
                        ),
                    ),
                )
            )
        if context.has_permission("asset:inventory:manage"):
            branches.append(
                self._inventory_select(
                    TodoType.INVENTORY,
                    and_(
                        InventoryTask.status == InventoryStatus.IN_PROGRESS,
                        self._record_scope(
                            context,
                            "inventory",
                            InventoryTask.scope_dept_id,
                            inventory_scope,
                            self._inventory_domain_condition(context),
                            InventoryTask.created_by_id,
                        ),
                    ),
                )
            )

        # 我发起且仍在处理中的单据，排除已轮到我处理的事项，避免重复提醒
        request_actionable = or_(
            self._request_approval_condition(context, request_scope),
            self._request_outbound_condition(context, request_scope),
            self._request_return_condition(context, request_scope),
        )
        borrow_due_soon = and_(
            AssetRequest.status == RequestStatus.BORROWED,
            AssetRequest.expected_return_date.is_not(None),
            AssetRequest.expected_return_date <= due_limit,
        )
        branches.append(
            self._request_select(
                TodoType.MY_BUSINESS,
                and_(
                    AssetRequest.applicant_id == user_id,
                    AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES),
                    ~or_(request_actionable, borrow_due_soon),
                ),
            )
        )

        transfer_actionable_parts = []
        if context.has_permission("asset:transfer:approve"):
            transfer_actionable_parts.append(
                and_(
                    AssetTransfer.status == TransferStatus.PENDING_APPROVAL,
                    ~dingtalk_approval.running_link_exists(
                        transfer_id=AssetTransfer.id
                    ),
                    self._record_scope(
                        context,
                        "transfer",
                        AssetTransfer.from_dept_id,
                        transfer_scope,
                        self._asset_domain_condition(
                            AssetTransfer.asset_id, context, "transfer"
                        ),
                        AssetTransfer.applicant_id,
                    ),
                )
            )
        if context.has_permission("asset:transfer:confirm"):
            transfer_actionable_parts.append(
                and_(
                    AssetTransfer.status == TransferStatus.PENDING_TRANSFER,
                    self._record_scope(
                        context,
                        "transfer",
                        AssetTransfer.from_dept_id,
                        transfer_scope,
                        self._asset_domain_condition(
                            AssetTransfer.asset_id, context, "transfer"
                        ),
                        AssetTransfer.applicant_id,
                    ),
                )
            )
        branches.append(
            self._transfer_select(
                TodoType.MY_BUSINESS,
                and_(
                    AssetTransfer.applicant_id == user_id,
                    AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
                    ~(
                        or_(*transfer_actionable_parts)
                        if transfer_actionable_parts
                        else false()
                    ),
                ),
            )
        )

        scrap_actionable_parts = []
        if context.has_permission("asset:scrap:approve"):
            scrap_actionable_parts.append(
                and_(
                    AssetScrap.status == ScrapStatus.PENDING_APPROVAL,
                    self._record_scope(
                        context,
                        "scrap",
                        AssetScrap.from_dept_id,
                        scrap_scope,
                        self._asset_domain_condition(
                            AssetScrap.asset_id, context, "scrap"
                        ),
                        AssetScrap.applicant_id,
                    ),
                )
            )
        if context.has_permission("asset:scrap:confirm"):
            scrap_actionable_parts.append(
                and_(
                    AssetScrap.status == ScrapStatus.PENDING_DISPOSAL,
                    self._record_scope(
                        context,
                        "scrap",
                        AssetScrap.from_dept_id,
                        scrap_scope,
                        self._asset_domain_condition(
                            AssetScrap.asset_id, context, "scrap"
                        ),
                        AssetScrap.applicant_id,
                    ),
                )
            )
        branches.append(
            self._scrap_select(
                TodoType.MY_BUSINESS,
                and_(
                    AssetScrap.applicant_id == user_id,
                    AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
                    ~(
                        or_(*scrap_actionable_parts)
                        if scrap_actionable_parts
                        else false()
                    ),
                ),
            )
        )

        maintenance_actionable_parts = []
        if context.has_permission("asset:maintenance:approve"):
            maintenance_actionable_parts.append(
                and_(
                    AssetMaintenance.status == MaintenanceStatus.PENDING_APPROVAL,
                    self._record_scope(
                        context,
                        "maintenance",
                        AssetMaintenance.from_dept_id,
                        maintenance_scope,
                        self._asset_domain_condition(
                            AssetMaintenance.asset_id, context, "maintenance"
                        ),
                        AssetMaintenance.applicant_id,
                    ),
                )
            )
        if context.has_permission("asset:maintenance:repair"):
            maintenance_actionable_parts.append(
                and_(
                    AssetMaintenance.status.in_(
                        (
                            MaintenanceStatus.PENDING_REPAIR,
                            MaintenanceStatus.REPAIRING,
                        )
                    ),
                    and_(
                        self._asset_domain_condition(
                            AssetMaintenance.asset_id, context, "maintenance"
                        ),
                        or_(
                            AssetMaintenance.repairer_id == user_id,
                            and_(
                                context.has_permission("asset:maintenance:accept"),
                                self._record_scope(
                                    context,
                                    "maintenance",
                                    AssetMaintenance.from_dept_id,
                                    maintenance_scope,
                                    self._asset_domain_condition(
                                        AssetMaintenance.asset_id,
                                        context,
                                        "maintenance",
                                    ),
                                    AssetMaintenance.applicant_id,
                                ),
                            ),
                        ),
                    ),
                )
            )
        if context.has_permission("asset:maintenance:accept"):
            maintenance_actionable_parts.append(
                and_(
                    AssetMaintenance.status
                    == MaintenanceStatus.PENDING_ACCEPTANCE,
                    self._record_scope(
                        context,
                        "maintenance",
                        AssetMaintenance.from_dept_id,
                        maintenance_scope,
                        self._asset_domain_condition(
                            AssetMaintenance.asset_id, context, "maintenance"
                        ),
                        AssetMaintenance.applicant_id,
                    ),
                )
            )
        branches.append(
            self._maintenance_select(
                TodoType.MY_BUSINESS,
                and_(
                    AssetMaintenance.applicant_id == user_id,
                    AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES),
                    ~(
                        or_(*maintenance_actionable_parts)
                        if maintenance_actionable_parts
                        else false()
                    ),
                ),
            )
        )

        inventory_actionable = (
            and_(
                InventoryTask.status == InventoryStatus.IN_PROGRESS,
                self._record_scope(
                    context,
                    "inventory",
                    InventoryTask.scope_dept_id,
                    inventory_scope,
                    self._inventory_domain_condition(context),
                    InventoryTask.created_by_id,
                ),
            )
            if context.has_permission("asset:inventory:manage")
            else false()
        )
        branches.append(
            self._inventory_select(
                TodoType.MY_BUSINESS,
                and_(
                    InventoryTask.created_by_id == user_id,
                    InventoryTask.status == InventoryStatus.IN_PROGRESS,
                    ~inventory_actionable,
                ),
            )
        )

        adjustment_actionable = (
            and_(
                InventoryAdjustment.status == InventoryAdjustmentStatus.PENDING,
                self._record_scope(
                    context,
                    "inventory",
                    InventoryTask.scope_dept_id,
                    inventory_scope,
                    self._inventory_domain_condition(context),
                    InventoryAdjustment.requested_by_id,
                ),
            )
            if context.has_permission("asset:inventory:approve")
            else false()
        )
        branches.append(
            self._adjustment_select(
                TodoType.MY_BUSINESS,
                and_(
                    InventoryAdjustment.requested_by_id == user_id,
                    InventoryAdjustment.status == InventoryAdjustmentStatus.PENDING,
                    ~adjustment_actionable,
                ),
            )
        )

        inbound_actionable = (
            and_(
                AssetInbound.status == InboundStatus.PENDING,
                self._record_scope(
                    context,
                    "inbound",
                    AssetInbound.dept_id,
                    inbound_scope,
                    self._inbound_domain_condition(context),
                    AssetInbound.created_by_id,
                ),
            )
            if context.has_permission("asset:inbound:confirm")
            else false()
        )
        branches.append(
            self._inbound_select(
                TodoType.MY_BUSINESS,
                and_(
                    AssetInbound.created_by_id == user_id,
                    AssetInbound.status == InboundStatus.PENDING,
                    ~inbound_actionable,
                ),
            )
        )

        return_request = aliased(AssetRequest)
        pending_return_exists = exists(
            select(return_request.id).where(
                return_request.source_request_id == AssetRequest.id,
                return_request.status == RequestStatus.PENDING_RETURN,
            )
        )
        borrow_due_condition = and_(
            AssetRequest.status == RequestStatus.BORROWED,
            AssetRequest.expected_return_date.is_not(None),
            AssetRequest.expected_return_date <= due_limit,
            or_(
                AssetRequest.applicant_id == user_id,
                Asset.custodian_id == user_id,
            ),
            ~pending_return_exists,
        )
        branches.append(
            self._row_select(
                todo_type=TodoType.BORROW_DUE,
                ref_id=AssetRequest.id,
                doc_no=AssetRequest.request_no,
                subject=func.coalesce(
                    AssetRequest.asset_name,
                    Asset.name,
                    AssetRequest.category_name,
                ),
                status=AssetRequest.status,
                occurred_at=AssetRequest.created_at,
                detail=AssetRequest.reason,
                related_name=AssetRequest.applicant_name,
                dept_name=AssetRequest.applicant_dept_name,
                due_date=AssetRequest.expected_return_date,
                kind=AssetRequest.request_type,
            )
            .select_from(AssetRequest)
            .outerjoin(Asset, Asset.id == AssetRequest.asset_id)
            .where(borrow_due_condition)
        )
        return branches

    # ---------- 查询 ----------

    async def _union(self, context: AuthContext):
        scopes: dict[str, set[int] | None] = {}
        for resource in (
            "requisition",
            "transfer",
            "scrap",
            "maintenance",
            "inventory",
            "inbound",
        ):
            scopes[resource] = await scoped_dept_ids(
                self.session, context, resource=resource
            )
        branches = await self._build_branches(context, scopes)
        return union_all(*branches).subquery("todo_union")

    async def _type_counts(self, union) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(union.c.todo_type, func.count().label("total")).group_by(
                    union.c.todo_type
                )
            )
        ).all()
        counts = {todo_type: 0 for todo_type in TODO_TYPE_ORDER}
        for row in rows:
            counts[row.todo_type] = int(row.total)
        return counts

    async def summary(
        self, context: AuthContext, *, per_type: int = 5
    ) -> TodoSummaryOut:
        union = await self._union(context)
        counts = await self._type_counts(union)
        ranked = select(
            *union.c,
            func.row_number()
            .over(
                partition_by=union.c.todo_type,
                order_by=(union.c.occurred_at.desc(), union.c.ref_id.desc()),
            )
            .label("row_no"),
        ).subquery("todo_ranked")
        rows = (
            await self.session.execute(
                select(ranked)
                .where(ranked.c.row_no <= per_type)
                .order_by(ranked.c.occurred_at.desc(), ranked.c.ref_id.desc())
            )
        ).all()

        items_by_type: dict[str, list[TodoItemOut]] = {
            todo_type: [] for todo_type in TODO_TYPE_ORDER
        }
        for row in rows:
            items_by_type[row.todo_type].append(self._item(row))

        categories: list[TodoCategoryOut] = []
        for category in TODO_CATEGORY_ORDER:
            types = [
                todo_type
                for todo_type in TODO_TYPE_ORDER
                if TODO_TYPE_CATEGORY[todo_type] == category
            ]
            items = [item for todo_type in types for item in items_by_type[todo_type]]
            items.sort(
                key=lambda item: (item.occurred_at or datetime.min, item.key),
                reverse=True,
            )
            categories.append(
                TodoCategoryOut(
                    category=category,
                    label=TODO_CATEGORY_LABELS[category],
                    count=sum(counts[todo_type] for todo_type in types),
                    types=[
                        TodoTypeCountOut(
                            todo_type=todo_type,
                            label=TODO_TYPE_LABELS[todo_type],
                            category=category,
                            count=counts[todo_type],
                        )
                        for todo_type in types
                    ],
                    items=items,
                )
            )
        return TodoSummaryOut(
            total=sum(counts.values()),
            categories=categories,
            generated_at=now_cst(),
        )

    async def list_items(
        self,
        context: AuthContext,
        *,
        category: str | None,
        todo_type: str | None,
        page: int,
        page_size: int,
        sort: str,
    ) -> TodoPageOut:
        if category and category not in TODO_CATEGORY_LABELS:
            raise BizError("待办分类取值不正确")
        if todo_type and todo_type not in TODO_TYPE_LABELS:
            raise BizError("待办类型取值不正确")
        if sort not in ("asc", "desc"):
            raise BizError("排序方式取值不正确")

        selected_types: list[str] | None = None
        if todo_type:
            selected_types = [todo_type]
        elif category:
            selected_types = [
                item
                for item in TODO_TYPE_ORDER
                if TODO_TYPE_CATEGORY[item] == category
            ]

        union = await self._union(context)
        conditions = []
        if selected_types is not None:
            conditions.append(union.c.todo_type.in_(selected_types))

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(union).where(*conditions)
            )
            or 0
        )
        ordering = (
            union.c.occurred_at.asc()
            if sort == "asc"
            else union.c.occurred_at.desc()
        )
        id_ordering = union.c.ref_id.asc() if sort == "asc" else union.c.ref_id.desc()
        rows = (
            await self.session.execute(
                select(union)
                .where(*conditions)
                .order_by(ordering, id_ordering, union.c.todo_type.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return TodoPageOut(
            items=[self._item(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    # ---------- 结果映射 ----------

    @staticmethod
    def _brief(value: str | None, limit: int = 60) -> str | None:
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        return text if len(text) <= limit else f"{text[: limit - 1]}…"

    @staticmethod
    def _as_date(value) -> date | None:
        if value is None or isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    @staticmethod
    def _status_label(kind: str | None, status: str) -> str:
        if kind in REQUEST_KINDS:
            return REQUEST_STATUS_LABELS.get(status, status)
        if kind == "TRANSFER":
            return TRANSFER_STATUS_LABELS.get(status, status)
        if kind == "SCRAP":
            return SCRAP_STATUS_LABELS.get(status, status)
        if kind == "MAINTENANCE":
            return MAINTENANCE_STATUS_LABELS.get(status, status)
        if kind == "INVENTORY":
            return INVENTORY_STATUS_LABELS.get(status, status)
        if kind == "INVENTORY_ADJUSTMENT":
            return INVENTORY_ADJUSTMENT_STATUS_LABELS.get(status, status)
        if kind in INBOUND_TYPE_LABELS:
            return INBOUND_STATUS_LABELS.get(status, status)
        return status

    @staticmethod
    def _title(todo_type: str, kind: str | None, subject: str | None, doc_no: str) -> str:
        text = (subject or doc_no).strip()
        if todo_type == TodoType.MY_BUSINESS:
            prefix = {
                "REQUISITION": "领用申请",
                "BORROW": "借用申请",
                "RETURN": "归还申请",
                "TRANSFER": "资产调拨",
                "SCRAP": "资产报废",
                "MAINTENANCE": "维修工单",
                "INVENTORY": "盘点任务",
                "INVENTORY_ADJUSTMENT": "盘点盈亏处理",
                "PURCHASE": "采购入库",
                "OTHER": "其他入库",
            }.get(kind or "", "业务单据")
            return f"{prefix} · {text}"
        if todo_type == TodoType.INBOUND_CONFIRM:
            return f"{INBOUND_TYPE_LABELS.get(kind or '', '入库')} · {text}"
        if todo_type == TodoType.INVENTORY_APPROVAL:
            return f"盘点盈亏审批 · {text}"
        if kind in REQUEST_KINDS:
            return f"{REQUEST_TYPE_LABELS.get(kind, '业务申请')} · {text}"
        return text

    def _subtitle(self, row, status_label: str) -> str | None:
        todo_type = row.todo_type
        detail = self._brief(row.detail)
        related = row.related_name
        dept = row.dept_name
        if todo_type == TodoType.BORROW_DUE:
            due = self._as_date(row.due_date)
            if due:
                return f"应归还日期：{due.isoformat()}"
            return "借用资产即将到期"
        if todo_type in (
            TodoType.REQUEST_APPROVAL,
            TodoType.REQUEST_OUTBOUND,
            TodoType.REQUEST_RETURN,
        ):
            return f"申请人：{related}" if related else detail
        if todo_type in (TodoType.TRANSFER_APPROVAL, TodoType.TRANSFER_CONFIRM):
            if dept or detail:
                return f"{dept or '—'} → {detail or '—'}"
            return f"申请人：{related}" if related else None
        if todo_type in (TodoType.SCRAP_APPROVAL, TodoType.SCRAP_CONFIRM):
            return detail or (f"申请人：{related}" if related else None)
        if todo_type in (
            TodoType.MAINTENANCE_APPROVAL,
            TodoType.MAINTENANCE_REPAIR,
            TodoType.MAINTENANCE_ACCEPT,
        ):
            return detail or (f"申请人：{related}" if related else None)
        if todo_type == TodoType.INVENTORY:
            scope = dept or "全部部门"
            category = detail or "全部分类"
            text = f"范围：{scope} · {category}"
            planned = self._as_date(row.due_date)
            if planned:
                text += f" · 计划 {planned.isoformat()}"
            return text
        if todo_type == TodoType.INBOUND_CONFIRM:
            text = f"{row.quantity or 0} 件资产待入库"
            if detail:
                text += f" · {detail}"
            return text
        if todo_type == TodoType.INVENTORY_APPROVAL:
            text = f"处理单：{row.doc_no}"
            if related:
                text += f" · 提交人：{related}"
            return text
        if todo_type == TodoType.MY_BUSINESS:
            return f"当前进度：{status_label}"
        return detail

    @staticmethod
    def _link(todo_type: str, kind: str | None, ref_id: int) -> str:
        if todo_type == TodoType.BORROW_DUE:
            return TODO_TYPE_PATHS[todo_type]
        path = (
            MY_BUSINESS_PATHS.get(kind or "")
            if todo_type == TodoType.MY_BUSINESS
            else TODO_TYPE_PATHS[todo_type]
        )
        return f"{path or '/todos'}?focus={ref_id}"

    def _item(self, row) -> TodoItemOut:
        kind = row.kind
        category = TODO_TYPE_CATEGORY[row.todo_type]
        status_label = self._status_label(kind, row.status)
        due = self._as_date(row.due_date)
        today: date = now_cst().date()
        days_to_due = (due - today).days if due else None
        return TodoItemOut(
            key=f"{row.todo_type}:{kind or '-'}:{row.ref_id}",
            category=category,
            category_label=TODO_CATEGORY_LABELS[category],
            todo_type=row.todo_type,
            todo_type_label=TODO_TYPE_LABELS[row.todo_type],
            title=self._title(row.todo_type, kind, row.subject, row.doc_no),
            subtitle=self._subtitle(row, status_label),
            doc_no=row.doc_no,
            status=row.status,
            status_label=status_label,
            related_name=row.related_name,
            dept_name=row.dept_name,
            occurred_at=row.occurred_at,
            due_date=due,
            days_to_due=days_to_due,
            is_overdue=(
                row.todo_type == TodoType.BORROW_DUE
                and days_to_due is not None
                and days_to_due < 0
            ),
            link=self._link(row.todo_type, kind, row.ref_id),
        )
