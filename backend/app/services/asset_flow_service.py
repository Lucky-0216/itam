from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import (
    ACTIVE_REQUEST_STATUSES,
    APPROVAL_ACTION_LABELS,
    APPROVAL_STAGE_LABELS,
    APPROVAL_STAGE_ROLES,
    ASSET_HISTORY_ACTION_LABELS,
    REQUEST_NO_PREFIXES,
    REQUEST_STATUS_LABELS,
    REQUEST_STATUS_TAG_TYPES,
    REQUEST_TYPE_LABELS,
    ApprovalAction,
    ApprovalStage,
    AssetHistoryAction,
    RequestStatus,
    RequestType,
    assert_transition,
)
from app.core.asset_ops import SCRAP_ACTIVE_STATUSES, TRANSFER_ACTIVE_STATUSES
from app.core.assets import ASSET_STATUS_LABELS, ASSET_STATUS_TAG_TYPES, AssetStatus
from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.core.maintenance import MAINTENANCE_ACTIVE_STATUSES
from app.core.permissions import DataScope
from app.models import (
    ApprovalTask,
    Asset,
    AssetCategory,
    AssetHistory,
    AssetMaintenance,
    AssetModel,
    AssetRequest,
    AssetRequestApproval,
    AssetRequestSetting,
    AssetScrap,
    AssetTransfer,
    AuditLog,
)
from app.models.base import now_cst
from app.schemas.asset_flow import (
    ApprovalConfigOut,
    ApprovalRecordOut,
    AssetHistoryOut,
    AssetRequestCreate,
    AssetRequestOut,
    AssetRequestPageOut,
    AssetRequestSummaryOut,
    AssetReturnConfirmPayload,
    AssetReturnCreate,
    AssetOutboundPayload,
    AvailableAssetOut,
    AvailableCategoryOut,
    AvailableModelOut,
    MyAssetOut,
    ScanAssetOut,
)
from app.services.approval_flow_service import ApprovalFlowService
from app.services.asset_snapshot import asset_snapshot as _asset_snapshot
from app.services.asset_snapshot import json_value as _json_value
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import is_self_only, scoped_dept_ids
from app.services.txn import commit_or_conflict

STATUS_CONFLICT_MESSAGE = "资产状态已变更，请刷新后重试"


class AssetFlowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _next_request_no(self, request_type: str) -> str:
        prefix = REQUEST_NO_PREFIXES[request_type]
        head = f"{prefix}-{now_cst():%Y%m}-"
        max_no = await self.session.scalar(
            select(func.max(AssetRequest.request_no)).where(
                AssetRequest.request_no.like(f"{head}%")
            )
        )
        sequence = 1
        if max_no:
            suffix = max_no[len(head) :]
            if suffix.isdigit():
                sequence = int(suffix) + 1
        return f"{head}{sequence:04d}"

    async def _get_asset(
        self,
        asset_id: int,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Asset:
        stmt = select(Asset).where(Asset.id == asset_id)
        if not include_deleted:
            stmt = stmt.where(Asset.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        asset = (await self.session.execute(stmt)).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("资产不存在")
        return asset

    async def _get_request(
        self, request_id: int, *, for_update: bool = False
    ) -> AssetRequest:
        stmt = select(AssetRequest).where(AssetRequest.id == request_id)
        if for_update:
            stmt = stmt.with_for_update()
        request = (await self.session.execute(stmt)).scalar_one_or_none()
        if request is None:
            raise NotFoundError("业务单据不存在")
        return request

    async def _find_active_request(
        self,
        asset_id: int,
        *,
        statuses: tuple[str, ...] = ACTIVE_REQUEST_STATUSES,
        exclude_id: int | None = None,
    ) -> AssetRequest | None:
        stmt = select(AssetRequest).where(
            AssetRequest.asset_id == asset_id,
            AssetRequest.status.in_(statuses),
        )
        if exclude_id is not None:
            stmt = stmt.where(AssetRequest.id != exclude_id)
        stmt = stmt.order_by(AssetRequest.id.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _allowed_depts(self, context: AuthContext) -> set[int] | None:
        return await scoped_dept_ids(self.session, context)

    @staticmethod
    def _in_scope(
        request: AssetRequest,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> bool:
        if context.is_superuser or allowed is None:
            return True
        if request.applicant_dept_id is None:
            return False
        return request.applicant_dept_id in allowed

    def _assert_review_scope(
        self,
        request: AssetRequest,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> None:
        if not self._in_scope(request, context, allowed):
            raise PermissionDenied("无权处理该部门的业务申请")

    @staticmethod
    def _role_codes(context: AuthContext) -> set[str]:
        return {role.code for role in context.roles}

    def _handled_stages(self, context: AuthContext) -> list[str]:
        if context.is_superuser:
            return [ApprovalStage.DEPT, ApprovalStage.ASSET]
        codes = self._role_codes(context)
        return [
            stage
            for stage, role_code in APPROVAL_STAGE_ROLES.items()
            if role_code in codes
        ]

    def _assert_stage_access(
        self,
        request: AssetRequest,
        context: AuthContext,
    ) -> str:
        stage = request.approval_stage or ApprovalStage.ASSET
        if stage not in self._handled_stages(context):
            stage_role = APPROVAL_STAGE_ROLES.get(stage, stage)
            raise PermissionDenied(f"当前审批节点需由 {stage_role} 角色处理")
        return stage

    def _can_configure(self, context: AuthContext) -> bool:
        return context.is_superuser or "ASSET_ADMIN" in self._role_codes(context)

    async def _get_settings(self, *, for_update: bool = False) -> AssetRequestSetting:
        stmt = (
            select(AssetRequestSetting)
            .order_by(AssetRequestSetting.id)
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        settings = (await self.session.execute(stmt)).scalar_one_or_none()
        if settings is None:
            settings = AssetRequestSetting(dept_approval_required=True)
            self.session.add(settings)
            await self.session.flush()
        return settings

    @staticmethod
    def _approval_out(record: AssetRequestApproval) -> ApprovalRecordOut:
        return ApprovalRecordOut(
            id=record.id,
            task_id=record.task_id,
            step_no=record.step_no,
            step_code=record.step_code,
            step_name=record.step_name,
            action=record.action,
            action_label=APPROVAL_ACTION_LABELS.get(record.action, record.action),
            approver_id=record.approver_id,
            approver_name=record.approver_name,
            comment=record.comment,
            operated_at=record.operated_at,
        )

    def _request_out(
        self,
        request: AssetRequest,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> AssetRequestOut:
        today = now_cst().date()
        days_to_due = (
            (request.expected_return_date - today).days
            if request.expected_return_date
            else None
        )
        asset = request.asset
        in_scope = self._in_scope(request, context, allowed)
        stage = request.approval_stage
        handled_stages = self._handled_stages(context)
        flow_description = (
            ApprovalFlowService.describe(request) if request.flow_id else None
        )
        if request.flow_id:
            can_review = (
                request.status == RequestStatus.PENDING_APPROVAL
                and context.has_permission("asset:request:approve")
                and ApprovalFlowService.user_can_act(request, context)
            )
        else:
            can_review = (
                request.status == RequestStatus.PENDING_APPROVAL
                and in_scope
                and context.has_permission("asset:request:approve")
                and (stage or ApprovalStage.ASSET) in handled_stages
            )
        approval_rows = request.__dict__.get("approvals") or []
        return AssetRequestOut(
            id=request.id,
            request_no=request.request_no,
            request_type=request.request_type,
            request_type_label=REQUEST_TYPE_LABELS.get(
                request.request_type, request.request_type
            ),
            status=request.status,
            status_label=REQUEST_STATUS_LABELS.get(request.status, request.status),
            status_tag_type=REQUEST_STATUS_TAG_TYPES.get(request.status, "info"),
            category_id=request.category_id,
            category_name=request.category_name,
            include_child=request.include_child,
            approval_stage=stage,
            approval_stage_label=(
                flow_description.current_step_name
                if flow_description and flow_description.current_step_name
                else (APPROVAL_STAGE_LABELS.get(stage, stage) if stage else None)
            ),
            dept_approval_required=request.dept_approval_required,
            flow_id=request.flow_id,
            flow_name=request.flow_name,
            current_step_no=(
                flow_description.current_step_no if flow_description else None
            ),
            current_step_name=(
                flow_description.current_step_name if flow_description else None
            ),
            current_approvers=(
                flow_description.current_approvers if flow_description else []
            ),
            total_steps=flow_description.total_steps if flow_description else 0,
            approval_steps=flow_description.steps if flow_description else [],
            asset_id=request.asset_id,
            asset_no=request.asset_no,
            asset_name=request.asset_name,
            asset_version=asset.version if asset else request.asset_version,
            asset_model_name=(
                asset.model.name if asset and asset.model else None
            ),
            asset_status=asset.status if asset else None,
            asset_status_label=(
                ASSET_STATUS_LABELS.get(asset.status, asset.status)
                if asset
                else None
            ),
            asset_location=asset.location if asset else None,
            asset_custodian_id=asset.custodian_id if asset else None,
            asset_custodian_name=(
                asset.custodian.real_name if asset and asset.custodian else None
            ),
            applicant_id=request.applicant_id,
            applicant_name=request.applicant_name,
            applicant_dept_id=request.applicant_dept_id,
            applicant_dept_name=request.applicant_dept_name,
            reason=request.reason,
            expected_return_date=request.expected_return_date,
            days_to_due=days_to_due,
            is_overdue=(
                request.status == RequestStatus.BORROWED
                and days_to_due is not None
                and days_to_due < 0
            ),
            source_request_id=request.source_request_id,
            approver_name=request.approver_name,
            approved_at=request.approved_at,
            approval_comment=request.approval_comment,
            approvals=[
                self._approval_out(row)
                for row in sorted(approval_rows, key=lambda item: item.step_no)
            ],
            outbound_by_name=request.outbound_by_name,
            outbound_at=request.outbound_at,
            outbound_location=request.outbound_location,
            return_requested_at=request.return_requested_at,
            confirm_by_name=request.confirm_by_name,
            confirmed_at=request.confirmed_at,
            confirm_comment=request.confirm_comment,
            can_approve=can_review,
            can_reject=can_review,
            can_outbound=(
                request.status == RequestStatus.PENDING_OUTBOUND
                and in_scope
                and context.has_permission("asset:request:outbound")
            ),
            can_configure=self._can_configure(context),
            can_cancel=(
                request.applicant_id == context.user.id
                and request.status
                in (
                    RequestStatus.PENDING_APPROVAL,
                    RequestStatus.PENDING_OUTBOUND,
                    RequestStatus.PENDING_RETURN,
                )
            ),
            can_confirm_return=(
                request.status == RequestStatus.PENDING_RETURN
                and in_scope
                and context.has_permission("asset:return:confirm")
            ),
            version=request.version,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )

    @staticmethod
    def _my_pending_task_condition(context: AuthContext):
        return exists(
            select(ApprovalTask.id).where(
                ApprovalTask.request_id == AssetRequest.id,
                ApprovalTask.approver_id == context.user.id,
                ApprovalTask.status == "PENDING",
            )
        )

    def _my_actionable_condition(self, context: AuthContext):
        handled_stages = self._handled_stages(context)
        actionable = []
        if context.is_superuser:
            actionable.append(
                and_(
                    AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                    AssetRequest.flow_id.is_not(None),
                )
            )
        else:
            actionable.append(
                and_(
                    AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                    AssetRequest.flow_id.is_not(None),
                    self._my_pending_task_condition(context),
                )
            )
        if ApprovalStage.DEPT in handled_stages:
            actionable.append(
                and_(
                    AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                    AssetRequest.flow_id.is_(None),
                    AssetRequest.approval_stage == ApprovalStage.DEPT,
                )
            )
        if ApprovalStage.ASSET in handled_stages:
            actionable.append(
                and_(
                    AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                    AssetRequest.flow_id.is_(None),
                    or_(
                        AssetRequest.approval_stage == ApprovalStage.ASSET,
                        AssetRequest.approval_stage.is_(None),
                    ),
                )
            )
        if context.has_permission("asset:request:outbound"):
            actionable.append(
                AssetRequest.status == RequestStatus.PENDING_OUTBOUND
            )
        if context.has_permission("asset:return:confirm"):
            actionable.append(AssetRequest.status == RequestStatus.PENDING_RETURN)
        return or_(*actionable)

    async def list_requests(
        self,
        context: AuthContext,
        *,
        view: str,
        keyword: str | None,
        request_type: str | None,
        status: str | None,
        pending_mine: bool,
        page: int,
        page_size: int,
    ) -> AssetRequestPageOut:
        conditions = []
        allowed: set[int] | None = None

        if view == "mine":
            conditions.append(AssetRequest.applicant_id == context.user.id)
        else:
            allowed = await self._allowed_depts(context)
            if is_self_only(context):
                conditions.append(
                    and_(
                        AssetRequest.flow_id.is_not(None),
                        self._my_pending_task_condition(context),
                    )
                )
            elif allowed is not None:
                scope_condition = (
                    AssetRequest.applicant_dept_id.in_(allowed)
                    if allowed
                    else false()
                )
                conditions.append(
                    or_(
                        scope_condition,
                        and_(
                            AssetRequest.flow_id.is_not(None),
                            self._my_pending_task_condition(context),
                        ),
                    )
                )
            if pending_mine:
                conditions.append(self._my_actionable_condition(context))

        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetRequest.request_no.like(pattern),
                    AssetRequest.asset_no.like(pattern),
                    AssetRequest.asset_name.like(pattern),
                    AssetRequest.category_name.like(pattern),
                    AssetRequest.applicant_name.like(pattern),
                )
            )
        if request_type:
            if request_type not in REQUEST_TYPE_LABELS:
                raise BizError("单据类型取值不正确")
            conditions.append(AssetRequest.request_type == request_type)
        if status:
            if status not in REQUEST_STATUS_LABELS:
                raise BizError("单据状态取值不正确")
            conditions.append(AssetRequest.status == status)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(AssetRequest).where(*conditions)
            )
            or 0
        )
        rows = list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(*conditions)
                    .order_by(AssetRequest.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return AssetRequestPageOut(
            items=[self._request_out(item, context, allowed) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def review_summary(self, context: AuthContext) -> AssetRequestSummaryOut:
        scope_conditions = []
        if not context.has_permission("asset:request:review"):
            scope_conditions.append(AssetRequest.applicant_id == context.user.id)
        elif is_self_only(context):
            scope_conditions.append(
                and_(
                    AssetRequest.flow_id.is_not(None),
                    self._my_pending_task_condition(context),
                )
            )
        else:
            allowed = await self._allowed_depts(context)
            if allowed is not None:
                scope_conditions.append(
                    AssetRequest.applicant_dept_id.in_(allowed) if allowed else false()
                )

        async def count(*conditions) -> int:
            return int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(AssetRequest)
                    .where(*scope_conditions, *conditions)
                )
                or 0
            )

        async def count_status(status: str) -> int:
            return await count(AssetRequest.status == status)

        handled_stages = self._handled_stages(context)
        stage_conditions = []
        if ApprovalStage.DEPT in handled_stages:
            stage_conditions.append(
                and_(
                    AssetRequest.flow_id.is_(None),
                    AssetRequest.approval_stage == ApprovalStage.DEPT,
                )
            )
        if ApprovalStage.ASSET in handled_stages:
            stage_conditions.append(
                and_(
                    AssetRequest.flow_id.is_(None),
                    or_(
                        AssetRequest.approval_stage == ApprovalStage.ASSET,
                        AssetRequest.approval_stage.is_(None),
                    ),
                )
            )
        legacy_pending_approval = (
            await count(
                AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                or_(*stage_conditions),
            )
            if stage_conditions
            else 0
        )
        flow_pending_condition = (
            AssetRequest.flow_id.is_not(None)
            if context.is_superuser
            else and_(
                AssetRequest.flow_id.is_not(None),
                self._my_pending_task_condition(context),
            )
        )
        flow_pending_approval = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AssetRequest)
                .where(
                    AssetRequest.status == RequestStatus.PENDING_APPROVAL,
                    flow_pending_condition,
                )
            )
            or 0
        )
        my_pending_approval = legacy_pending_approval + flow_pending_approval
        my_pending_outbound = (
            await count_status(RequestStatus.PENDING_OUTBOUND)
            if context.has_permission("asset:request:outbound")
            else 0
        )
        my_pending_return = (
            await count_status(RequestStatus.PENDING_RETURN)
            if context.has_permission("asset:return:confirm")
            else 0
        )

        mine_pending = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AssetRequest)
                .where(
                    AssetRequest.applicant_id == context.user.id,
                    AssetRequest.status.in_(
                        (
                            RequestStatus.PENDING_APPROVAL,
                            RequestStatus.PENDING_OUTBOUND,
                            RequestStatus.PENDING_RETURN,
                        )
                    ),
                )
            )
            or 0
        )
        return AssetRequestSummaryOut(
            pending_approval=await count_status(RequestStatus.PENDING_APPROVAL),
            pending_outbound=await count_status(RequestStatus.PENDING_OUTBOUND),
            pending_return=await count_status(RequestStatus.PENDING_RETURN),
            borrowed=await count_status(RequestStatus.BORROWED),
            mine_pending=mine_pending,
            my_pending_approval=my_pending_approval,
            my_pending_outbound=my_pending_outbound,
            my_pending_return=my_pending_return,
        )

    @staticmethod
    def _available_conditions() -> list:
        return [
            Asset.deleted_at.is_(None),
            Asset.status == AssetStatus.IN_STOCK,
            Asset.id.notin_(
                select(AssetMaintenance.asset_id).where(
                    AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES)
                )
            ),
        ]

    async def _category_availability(
        self,
    ) -> tuple[
        list[AssetCategory],
        dict[int, AssetCategory],
        dict[int | None, list[AssetCategory]],
        dict[int, int],
    ]:
        categories = list(
            (
                await self.session.execute(
                    select(AssetCategory)
                    .where(AssetCategory.status == 1)
                    .order_by(AssetCategory.sort, AssetCategory.id)
                )
            )
            .scalars()
            .all()
        )
        all_children: dict[int | None, list[AssetCategory]] = {}
        for category in categories:
            all_children.setdefault(category.parent_id, []).append(category)

        # 只保留从启用根分类可达的节点，避免停用父分类下的子分类变成孤立节点
        reachable: list[AssetCategory] = []
        queue = list(all_children.get(None, []))
        while queue:
            category = queue.pop(0)
            reachable.append(category)
            queue.extend(all_children.get(category.id, []))

        by_id = {category.id: category for category in reachable}
        children: dict[int | None, list[AssetCategory]] = {}
        for category in reachable:
            children.setdefault(category.parent_id, []).append(category)

        rows = (
            await self.session.execute(
                select(Asset.category_id, func.count(Asset.id))
                .where(*self._available_conditions())
                .group_by(Asset.category_id)
            )
        ).all()
        direct_counts = {
            int(category_id): int(count)
            for category_id, count in rows
            if category_id is not None
        }

        subtree_counts: dict[int, int] = {}
        for category in reachable:
            count = direct_counts.get(category.id, 0)
            if count <= 0 or children.get(category.id):
                continue
            node: AssetCategory | None = category
            while node is not None:
                subtree_counts[node.id] = subtree_counts.get(node.id, 0) + count
                node = by_id.get(node.parent_id) if node.parent_id else None
        return reachable, by_id, children, subtree_counts

    @staticmethod
    def _category_node(
        category: AssetCategory,
        children: dict[int | None, list[AssetCategory]],
        subtree_counts: dict[int, int],
    ) -> AvailableCategoryOut:
        return AvailableCategoryOut(
            id=category.id,
            parent_id=category.parent_id,
            name=category.name,
            available_count=subtree_counts.get(category.id, 0),
            has_children=bool(children.get(category.id)),
        )

    async def category_options(
        self, parent_id: int | None
    ) -> list[AvailableCategoryOut]:
        _, by_id, children, subtree_counts = await self._category_availability()
        if parent_id is not None and parent_id not in by_id:
            raise NotFoundError("资产分类不存在或已停用")
        return [
            self._category_node(category, children, subtree_counts)
            for category in children.get(parent_id, [])
        ]

    async def available_categories(self) -> list[AvailableCategoryOut]:
        categories, _, children, subtree_counts = await self._category_availability()
        nodes = {
            category.id: self._category_node(category, children, subtree_counts)
            for category in categories
        }
        roots: list[AvailableCategoryOut] = []
        for category in categories:
            node = nodes.get(category.id)
            if node is None:
                continue
            parent = nodes.get(category.parent_id) if category.parent_id else None
            if parent is not None:
                parent.children.append(node)
            else:
                roots.append(node)
        return roots

    @staticmethod
    def _category_conditions(category: AssetCategory, include_child: bool) -> list:
        if include_child:
            return [
                Asset.category_id.in_(
                    select(AssetCategory.id).where(
                        AssetCategory.status == 1,
                        AssetCategory.path.like(f"{category.path}%"),
                    )
                )
            ]
        return [Asset.category_id == category.id]

    async def _get_available_category(self, category_id: int) -> AssetCategory:
        category = await self.session.get(AssetCategory, category_id)
        if category is None or category.status != 1:
            raise NotFoundError("资产分类不存在或已停用")
        return category

    async def _assert_leaf_category(self, category: AssetCategory) -> None:
        child_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AssetCategory)
                .where(
                    AssetCategory.parent_id == category.id,
                    AssetCategory.status == 1,
                )
            )
            or 0
        )
        if child_count > 0:
            raise BizError(
                f"分类「{category.name}」下还有子分类，请继续选择最终一级分类后再提交"
            )

    async def available_models(
        self,
        *,
        category_id: int,
        include_child: bool,
    ) -> list[AvailableModelOut]:
        category = await self._get_available_category(category_id)
        conditions = [
            *self._available_conditions(),
            *self._category_conditions(category, include_child),
        ]
        rows = (
            await self.session.execute(
                select(Asset.model_id, func.count(Asset.id))
                .where(*conditions)
                .group_by(Asset.model_id)
            )
        ).all()

        counts: dict[int, int] = {}
        unmodeled_count = 0
        for model_id, count in rows:
            if model_id is None:
                unmodeled_count = int(count)
            else:
                counts[int(model_id)] = int(count)

        models: dict[int, AssetModel] = {}
        if counts:
            models = {
                model.id: model
                for model in (
                    (
                        await self.session.execute(
                            select(AssetModel).where(AssetModel.id.in_(counts))
                        )
                    )
                    .scalars()
                    .all()
                )
            }

        items: list[AvailableModelOut] = []
        for model_id, count in counts.items():
            model = models.get(model_id)
            if model is None:
                continue
            items.append(
                AvailableModelOut(
                    model_id=model.id,
                    model_name=model.name,
                    model_code=model.code,
                    brand=model.brand,
                    spec=model.spec,
                    unit=model.unit,
                    category_name=model.category.name if model.category else None,
                    available_count=count,
                )
            )
        if unmodeled_count:
            items.append(
                AvailableModelOut(
                    model_id=0,
                    model_name="未指定型号",
                    category_name=category.name,
                    available_count=unmodeled_count,
                )
            )
        items.sort(
            key=lambda item: (
                -item.available_count,
                item.model_id == 0,
                item.model_name,
            )
        )
        return items

    async def available_assets(
        self,
        *,
        category_id: int,
        include_child: bool,
        model_ids: set[int] | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[AvailableAssetOut], int]:
        category = await self._get_available_category(category_id)

        conditions = [
            *self._available_conditions(),
            *self._category_conditions(category, include_child),
        ]
        if model_ids is not None:
            real_model_ids = sorted(model_id for model_id in model_ids if model_id > 0)
            model_conditions = []
            if real_model_ids:
                model_conditions.append(Asset.model_id.in_(real_model_ids))
            if 0 in model_ids:
                model_conditions.append(Asset.model_id.is_(None))
            if not model_conditions:
                conditions.append(false())
            elif len(model_conditions) == 1:
                conditions.append(model_conditions[0])
            else:
                conditions.append(or_(*model_conditions))

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Asset).where(*conditions)
            )
            or 0
        )
        rows = list(
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
        return [self._available_out(asset) for asset in rows], total

    @staticmethod
    def _available_out(asset: Asset) -> AvailableAssetOut:
        return AvailableAssetOut(
            id=asset.id,
            asset_no=asset.asset_no,
            name=asset.name,
            category_name=asset.category.name if asset.category else None,
            model_id=asset.model_id,
            model_name=asset.model.name if asset.model else None,
            serial_no=asset.serial_no,
            location=asset.location,
            dept_id=asset.dept_id,
            dept_name=asset.dept.name if asset.dept else None,
            status=asset.status,
            status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
            version=asset.version,
        )

    async def my_assets(self, context: AuthContext) -> list[MyAssetOut]:
        assets = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(
                        Asset.deleted_at.is_(None),
                        Asset.custodian_id == context.user.id,
                        Asset.status.in_((AssetStatus.IN_USE, AssetStatus.BORROWED)),
                    )
                    .order_by(Asset.updated_at.desc(), Asset.id.desc())
                )
            )
            .scalars()
            .all()
        )
        if not assets:
            return []

        borrow_rows = list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(
                        AssetRequest.applicant_id == context.user.id,
                        AssetRequest.status == RequestStatus.BORROWED,
                        AssetRequest.asset_id.in_([asset.id for asset in assets]),
                    )
                    .order_by(AssetRequest.id.desc())
                )
            )
            .scalars()
            .all()
        )
        borrow_by_asset: dict[int, AssetRequest] = {}
        for row in borrow_rows:
            borrow_by_asset.setdefault(row.asset_id, row)

        asset_ids = [asset.id for asset in assets]
        pending_returns = list(
            (
                await self.session.execute(
                    select(AssetRequest).where(
                        AssetRequest.applicant_id == context.user.id,
                        AssetRequest.request_type == RequestType.RETURN,
                        AssetRequest.status == RequestStatus.PENDING_RETURN,
                        AssetRequest.asset_id.in_(asset_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        pending_return_by_asset = {row.asset_id: row for row in pending_returns}
        today = now_cst().date()
        result: list[MyAssetOut] = []
        for asset in assets:
            borrow = borrow_by_asset.get(asset.id)
            pending_return = pending_return_by_asset.get(asset.id)
            days_to_due = (
                (borrow.expected_return_date - today).days
                if borrow and borrow.expected_return_date
                else None
            )
            result.append(
                MyAssetOut(
                    asset_id=asset.id,
                    asset_no=asset.asset_no,
                    name=asset.name,
                    category_name=asset.category.name if asset.category else None,
                    model_name=asset.model.name if asset.model else None,
                    serial_no=asset.serial_no,
                    location=asset.location,
                    dept_name=asset.dept.name if asset.dept else None,
                    status=asset.status,
                    status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
                    status_tag_type=ASSET_STATUS_TAG_TYPES.get(asset.status, "info"),
                    request_id=borrow.id if borrow else None,
                    request_type=borrow.request_type if borrow else None,
                    borrowed_at=borrow.outbound_at if borrow else None,
                    expected_return_date=(
                        borrow.expected_return_date if borrow else None
                    ),
                    days_to_due=days_to_due,
                    is_overdue=days_to_due is not None and days_to_due < 0,
                    return_pending=pending_return is not None,
                    return_request_id=pending_return.id if pending_return else None,
                    version=asset.version,
                )
            )
        return result

    async def create_request(
        self,
        payload: AssetRequestCreate,
        context: AuthContext,
    ) -> AssetRequestOut:
        category = await self._get_available_category(payload.category_id)
        await self._assert_leaf_category(category)
        available_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Asset)
                .where(
                    *self._available_conditions(),
                    Asset.category_id == category.id,
                )
            )
            or 0
        )
        if available_count <= 0:
            raise BizError(
                f"分类「{category.name}」下暂无可用的在库资产，请选择其他分类"
            )

        engine = ApprovalFlowService(self.session)
        flow = await engine.resolve_flow(context.user.dept_id)
        if flow is None:
            settings = await self._get_settings()
            stage = (
                ApprovalStage.DEPT
                if settings.dept_approval_required
                else ApprovalStage.ASSET
            )
            dept_approval_required = settings.dept_approval_required
        else:
            stage = None
            dept_approval_required = False
        request = AssetRequest(
            request_no=await self._next_request_no(payload.request_type),
            request_type=payload.request_type,
            status=RequestStatus.PENDING_APPROVAL,
            category_id=category.id,
            category_name=category.name,
            include_child=False,
            approval_stage=stage,
            dept_approval_required=dept_approval_required,
            applicant_id=context.user.id,
            applicant_name=context.user.real_name,
            applicant_dept_id=context.user.dept_id,
            applicant_dept_name=context.user.dept.name if context.user.dept else None,
            reason=payload.reason,
            expected_return_date=payload.expected_return_date,
        )
        self.session.add(request)
        await self.session.flush()
        start_result = None
        if flow is not None:
            start_result = await engine.start_flow(
                request,
                flow,
                applicant_id=context.user.id,
                applicant_dept_id=context.user.dept_id,
            )
            if start_result.auto_skipped:
                assert_transition(
                    request.request_type,
                    request.status,
                    RequestStatus.PENDING_OUTBOUND,
                )
                request.status = RequestStatus.PENDING_OUTBOUND
                request.approved_at = now_cst()
                request.approval_comment = "审批流程所有节点自动跳过"
        request.asset = None
        await self.audit.record(
            action="asset.request.create",
            module="资产领用" if payload.request_type == RequestType.REQUISITION else "资产借用",
            summary=(
                f"提交{REQUEST_TYPE_LABELS[payload.request_type]}申请："
                f"{category.name}"
                + (f"（审批流程：{flow.name}）" if flow is not None else "")
            ),
            actor=context.user,
            resource_type="asset_request",
            resource_id=request.id,
            after={
                "request_no": request.request_no,
                "request_type": request.request_type,
                "status": request.status,
                "category_name": request.category_name,
                "include_child": request.include_child,
                "approval_stage": request.approval_stage,
                "flow_name": request.flow_name,
                "current_step_no": request.current_step_no,
                "current_approvers": (
                    start_result.current_approvers if start_result else []
                ),
                "applicant_name": request.applicant_name,
                "reason": request.reason,
                "expected_return_date": _json_value(request.expected_return_date),
            },
        )
        await commit_or_conflict(self.session)
        allowed = await self._allowed_depts(context)
        return self._request_out(request, context, allowed)

    async def approve(
        self,
        request_id: int,
        comment: str | None,
        context: AuthContext,
    ) -> AssetRequestOut:
        request = await self._get_request(request_id, for_update=True)
        if request.request_type not in (RequestType.REQUISITION, RequestType.BORROW):
            raise BizError("归还单无需审批")
        if request.status != RequestStatus.PENDING_APPROVAL:
            raise BizError("当前单据不在待审批状态")
        allowed = await self._allowed_depts(context)
        module = (
            "资产领用"
            if request.request_type == RequestType.REQUISITION
            else "资产借用"
        )
        if request.flow_id:
            outcome = await ApprovalFlowService(self.session).approve(
                request, comment, context
            )
            now = now_cst()
            before = {
                "status": request.status,
                "flow_name": request.flow_name,
                "current_step_no": outcome.step_no,
            }
            if outcome.finished:
                assert_transition(
                    request.request_type,
                    request.status,
                    RequestStatus.PENDING_OUTBOUND,
                )
                request.status = RequestStatus.PENDING_OUTBOUND
                request.approval_stage = None
                request.approver_id = context.user.id
                request.approver_name = context.user.real_name
                request.approved_at = now
                request.approval_comment = comment
                summary = (
                    f"审批流程完成：{request.request_no}，待分配资产出库"
                )
            else:
                summary = (
                    f"审批通过：{request.request_no}，流转至"
                    f"「{outcome.next_step_name or '下一节点'}」"
                )
            await self.audit.record(
                action="asset.request.approve",
                module=module,
                summary=summary,
                actor=context.user,
                resource_type="asset_request",
                resource_id=request.id,
                before=before,
                after={
                    "status": request.status,
                    "flow_name": request.flow_name,
                    "current_step_no": request.current_step_no,
                    "step_no": outcome.step_no,
                    "step_code": outcome.step_code,
                    "step_name": outcome.step_name,
                    "next_step_no": outcome.next_step_no,
                    "next_step_name": outcome.next_step_name,
                    "admin_override": outcome.admin_override,
                    "request_no": request.request_no,
                    "approver_name": context.user.real_name,
                    "comment": comment,
                },
            )
            await commit_or_conflict(self.session)
            return self._request_out(request, context, allowed)

        self._assert_review_scope(request, context, allowed)
        stage = self._assert_stage_access(request, context)
        now = now_cst()
        step_no = len(request.approvals) + 1
        request.approvals.append(
            AssetRequestApproval(
                request_id=request.id,
                step_no=step_no,
                step_code=stage,
                step_name=APPROVAL_STAGE_LABELS[stage],
                action=ApprovalAction.APPROVE,
                approver_id=context.user.id,
                approver_name=context.user.real_name,
                comment=comment,
                operated_at=now,
            )
        )
        before = {"status": request.status, "approval_stage": stage}
        if stage == ApprovalStage.DEPT:
            request.approval_stage = ApprovalStage.ASSET
            summary = f"部门审批通过：{request.request_no}，转资产管理员审批"
        else:
            assert_transition(
                request.request_type, request.status, RequestStatus.PENDING_OUTBOUND
            )
            request.status = RequestStatus.PENDING_OUTBOUND
            request.approval_stage = None
            request.approver_id = context.user.id
            request.approver_name = context.user.real_name
            request.approved_at = now
            request.approval_comment = comment
            summary = f"资产审批通过：{request.request_no}，待分配资产出库"
        await self.audit.record(
            action="asset.request.approve",
            module=module,
            summary=summary,
            actor=context.user,
            resource_type="asset_request",
            resource_id=request.id,
            before=before,
            after={
                "status": request.status,
                "approval_stage": request.approval_stage,
                "step_no": step_no,
                "step_code": stage,
                "request_no": request.request_no,
                "approver_name": context.user.real_name,
                "comment": comment,
            },
        )
        await commit_or_conflict(self.session)
        return self._request_out(request, context, allowed)

    async def reject(
        self,
        request_id: int,
        comment: str | None,
        context: AuthContext,
    ) -> AssetRequestOut:
        request = await self._get_request(request_id, for_update=True)
        if request.request_type not in (RequestType.REQUISITION, RequestType.BORROW):
            raise BizError("归还单无需审批")
        if request.status != RequestStatus.PENDING_APPROVAL:
            raise BizError("当前单据不在待审批状态")
        if not comment:
            raise BizError("请填写驳回原因")
        allowed = await self._allowed_depts(context)
        module = (
            "资产领用"
            if request.request_type == RequestType.REQUISITION
            else "资产借用"
        )
        if request.flow_id:
            outcome = await ApprovalFlowService(self.session).reject(
                request, comment, context
            )
            assert_transition(
                request.request_type, request.status, RequestStatus.REJECTED
            )
            now = now_cst()
            before = {
                "status": request.status,
                "flow_name": request.flow_name,
                "current_step_no": outcome.step_no,
            }
            request.status = RequestStatus.REJECTED
            request.approval_stage = None
            request.current_step_no = None
            request.approver_id = context.user.id
            request.approver_name = context.user.real_name
            request.approved_at = now
            request.approval_comment = comment
            await self.audit.record(
                action="asset.request.reject",
                module=module,
                summary=(
                    f"驳回申请：{request.request_no}"
                    f"（{request.flow_name or '审批流程'} · {outcome.step_name}）"
                ),
                actor=context.user,
                resource_type="asset_request",
                resource_id=request.id,
                before=before,
                after={
                    "status": request.status,
                    "flow_name": request.flow_name,
                    "step_no": outcome.step_no,
                    "step_code": outcome.step_code,
                    "step_name": outcome.step_name,
                    "admin_override": outcome.admin_override,
                    "request_no": request.request_no,
                    "approver_name": context.user.real_name,
                    "comment": comment,
                },
            )
            await commit_or_conflict(self.session)
            return self._request_out(request, context, allowed)

        self._assert_review_scope(request, context, allowed)
        stage = self._assert_stage_access(request, context)
        assert_transition(request.request_type, request.status, RequestStatus.REJECTED)
        now = now_cst()
        step_no = len(request.approvals) + 1
        request.approvals.append(
            AssetRequestApproval(
                request_id=request.id,
                step_no=step_no,
                step_code=stage,
                step_name=APPROVAL_STAGE_LABELS[stage],
                action=ApprovalAction.REJECT,
                approver_id=context.user.id,
                approver_name=context.user.real_name,
                comment=comment,
                operated_at=now,
            )
        )
        before = {"status": request.status, "approval_stage": stage}
        request.status = RequestStatus.REJECTED
        request.approval_stage = None
        request.approver_id = context.user.id
        request.approver_name = context.user.real_name
        request.approved_at = now
        request.approval_comment = comment
        await self.audit.record(
            action="asset.request.reject",
            module=module,
            summary=f"驳回申请：{request.request_no}（{APPROVAL_STAGE_LABELS[stage]}）",
            actor=context.user,
            resource_type="asset_request",
            resource_id=request.id,
            before=before,
            after={
                "status": request.status,
                "step_no": step_no,
                "step_code": stage,
                "request_no": request.request_no,
                "approver_name": context.user.real_name,
                "comment": comment,
            },
        )
        await commit_or_conflict(self.session)
        return self._request_out(request, context, allowed)

    async def approval_config(self) -> ApprovalConfigOut:
        settings = await self._get_settings()
        return ApprovalConfigOut(
            dept_approval_required=settings.dept_approval_required,
            version=settings.version,
            updated_by_name=settings.updated_by_name,
            updated_at=settings.updated_at,
        )

    async def update_approval_config(
        self,
        *,
        dept_approval_required: bool,
        version: int,
        context: AuthContext,
    ) -> ApprovalConfigOut:
        if not self._can_configure(context):
            raise PermissionDenied("仅资产管理员可以调整审批流程")
        settings = await self._get_settings(for_update=True)
        if settings.version != version:
            raise ConflictError("审批配置已被他人修改，请刷新后重试", code=40901)
        before = {"dept_approval_required": settings.dept_approval_required}
        settings.dept_approval_required = dept_approval_required
        settings.updated_by_id = context.user.id
        settings.updated_by_name = context.user.real_name
        await self.audit.record(
            action="asset.request.config.update",
            module="资产领用",
            summary=(
                "开启部门管理员审批"
                if dept_approval_required
                else "关闭部门管理员审批"
            ),
            actor=context.user,
            resource_type="asset_request_setting",
            resource_id=settings.id,
            before=before,
            after={"dept_approval_required": dept_approval_required},
        )
        await commit_or_conflict(self.session)
        return ApprovalConfigOut(
            dept_approval_required=settings.dept_approval_required,
            version=settings.version,
            updated_by_name=settings.updated_by_name,
            updated_at=settings.updated_at,
        )

    async def cancel(self, request_id: int, context: AuthContext) -> AssetRequestOut:
        request = await self._get_request(request_id, for_update=True)
        if request.applicant_id != context.user.id and not context.is_superuser:
            raise PermissionDenied("只能撤销本人提交的申请")
        if request.status not in (
            RequestStatus.PENDING_APPROVAL,
            RequestStatus.PENDING_OUTBOUND,
            RequestStatus.PENDING_RETURN,
        ):
            raise BizError("当前状态不允许撤销")
        assert_transition(request.request_type, request.status, RequestStatus.CANCELLED)
        if request.flow_id:
            await ApprovalFlowService(self.session).skip_open_tasks(
                request, comment="申请人撤销"
            )
        before_status = request.status
        request.status = RequestStatus.CANCELLED
        request.approval_stage = None
        request.confirmed_at = now_cst()
        request.confirm_comment = "申请人撤销"
        await self.audit.record(
            action="asset.request.cancel",
            module="资产领用",
            summary=f"撤销申请：{request.request_no}",
            actor=context.user,
            resource_type="asset_request",
            resource_id=request.id,
            before={"status": before_status},
            after={"status": RequestStatus.CANCELLED},
        )
        await commit_or_conflict(self.session)
        allowed = await self._allowed_depts(context)
        return self._request_out(request, context, allowed)

    def _asset_in_request_category(
        self,
        asset: Asset,
        request: AssetRequest,
    ) -> bool:
        if request.include_child:
            category_path = request.category.path if request.category else ""
            return bool(
                category_path
                and asset.category
                and asset.category.path.startswith(category_path)
            )
        return asset.category_id == request.category_id

    async def outbound_assets(
        self,
        request_id: int,
        context: AuthContext,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[AvailableAssetOut], int]:
        request = await self._get_request(request_id)
        if request.request_type not in (RequestType.REQUISITION, RequestType.BORROW):
            raise BizError("该单据不支持出库操作")
        if request.status != RequestStatus.PENDING_OUTBOUND:
            raise BizError("当前单据不在待出库状态")
        allowed = await self._allowed_depts(context)
        self._assert_review_scope(request, context, allowed)
        if request.category is None:
            raise BizError("申请分类已不存在，无法选择出库资产")

        conditions = [
            *self._available_conditions(),
            *self._category_conditions(request.category, request.include_child),
            Asset.id.notin_(
                select(AssetRequest.asset_id).where(
                    AssetRequest.asset_id.is_not(None),
                    AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES),
                    AssetRequest.id != request.id,
                )
            ),
            Asset.id.notin_(
                select(AssetTransfer.asset_id).where(
                    AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES)
                )
            ),
            Asset.id.notin_(
                select(AssetScrap.asset_id).where(
                    AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES)
                )
            ),
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Asset).where(*conditions)
            )
            or 0
        )
        rows = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(*conditions)
                    .order_by(Asset.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [self._available_out(asset) for asset in rows], total

    async def confirm_outbound(
        self,
        request_id: int,
        payload: AssetOutboundPayload,
        context: AuthContext,
    ) -> AssetRequestOut:
        request = await self._get_request(request_id)
        if request.request_type not in (RequestType.REQUISITION, RequestType.BORROW):
            raise BizError("该单据不支持出库操作")
        if request.status != RequestStatus.PENDING_OUTBOUND:
            raise BizError("当前单据不在待出库状态")
        allowed = await self._allowed_depts(context)
        self._assert_review_scope(request, context, allowed)

        if (
            request.asset_id is not None
            and payload.asset_id is not None
            and request.asset_id != payload.asset_id
        ):
            raise BizError("该申请已绑定资产，不能更换出库资产")
        asset_id = request.asset_id or payload.asset_id
        if asset_id is None:
            raise BizError("请选择要出库的具体资产")
        if request.category is None:
            raise BizError("申请分类已不存在，无法出库")

        asset = await self._get_asset(asset_id, for_update=True)
        if not self._asset_in_request_category(asset, request):
            raise BizError(f"所选资产不属于申请分类「{request.category_name}」")
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status != AssetStatus.IN_STOCK:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        active_transfer = await self.session.scalar(
            select(AssetTransfer.id)
            .where(
                AssetTransfer.asset_id == asset.id,
                AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_transfer:
            raise ConflictError(
                "该资产存在处理中的调拨单，请刷新后重试", code=40911
            )
        active_scrap = await self.session.scalar(
            select(AssetScrap.id)
            .where(
                AssetScrap.asset_id == asset.id,
                AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_scrap:
            raise ConflictError(
                "该资产存在处理中的报废单，请刷新后重试", code=40911
            )
        active_maintenance = await self.session.scalar(
            select(AssetMaintenance.id)
            .where(
                AssetMaintenance.asset_id == asset.id,
                AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_maintenance:
            raise ConflictError(
                "该资产存在处理中的维修工单，请刷新后重试", code=40911
            )
        other = await self._find_active_request(asset.id, exclude_id=request.id)
        if other is not None:
            raise ConflictError(
                "该资产存在其他进行中的单据，请刷新后重试", code=40911
            )

        target_asset_status = (
            AssetStatus.IN_USE
            if request.request_type == RequestType.REQUISITION
            else AssetStatus.BORROWED
        )
        target_request_status = (
            RequestStatus.COMPLETED
            if request.request_type == RequestType.REQUISITION
            else RequestStatus.BORROWED
        )
        assert_transition(request.request_type, request.status, target_request_status)

        before = _asset_snapshot(asset)
        request.asset_id = asset.id
        request.asset_no = asset.asset_no
        request.asset_name = asset.name
        request.asset_version = asset.version
        request.asset = asset
        asset.status = target_asset_status
        asset.custodian_id = request.applicant_id
        asset.custodian = request.applicant
        asset.dept_id = request.applicant_dept_id
        asset.dept = request.applicant_dept
        if payload.location:
            asset.location = payload.location
        after = _asset_snapshot(asset)
        after["custodian_name"] = request.applicant_name
        after["dept_name"] = request.applicant_dept_name

        request.status = target_request_status
        request.outbound_by_id = context.user.id
        request.outbound_by_name = context.user.real_name
        request.outbound_at = now_cst()
        request.outbound_location = payload.location or asset.location
        request.confirm_comment = payload.comment

        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                request_id=request.id,
                action=AssetHistoryAction.OUTBOUND,
                action_label=ASSET_HISTORY_ACTION_LABELS[
                    AssetHistoryAction.OUTBOUND
                ],
                from_status=before["status"],
                to_status=after["status"],
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=context.user.real_name,
                summary=(
                    f"{REQUEST_TYPE_LABELS[request.request_type]}出库给"
                    f" {request.applicant_name}（{request.request_no}）"
                ),
            )
        )
        await self.audit.record(
            action="asset.request.outbound",
            module="资产领用",
            summary=(
                f"确认出库：{request.asset_no} {request.asset_name} → "
                f"{request.applicant_name}"
            ),
            actor=context.user,
            resource_type="asset",
            resource_id=asset.id,
            before=before,
            after=after,
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE)
        return self._request_out(request, context, allowed)

    async def create_return(
        self,
        payload: AssetReturnCreate,
        context: AuthContext,
    ) -> AssetRequestOut:
        asset = await self._get_asset(payload.asset_id, for_update=True)
        if asset.status not in (AssetStatus.IN_USE, AssetStatus.BORROWED):
            raise BizError("当前资产不在用，无需归还")
        if asset.custodian_id != context.user.id:
            raise PermissionDenied("仅当前责任人可以发起归还")
        pending = await self._find_active_request(
            asset.id, statuses=(RequestStatus.PENDING_RETURN,)
        )
        if pending is not None:
            raise BizError(f"该资产已有待确认的归还单（{pending.request_no}）")

        source = (
            await self.session.execute(
                select(AssetRequest)
                .where(
                    AssetRequest.asset_id == asset.id,
                    AssetRequest.applicant_id == context.user.id,
                    AssetRequest.request_type.in_(
                        (RequestType.REQUISITION, RequestType.BORROW)
                    ),
                    AssetRequest.status.in_(
                        (RequestStatus.COMPLETED, RequestStatus.BORROWED)
                    ),
                )
                .order_by(AssetRequest.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        request = AssetRequest(
            request_no=await self._next_request_no(RequestType.RETURN),
            request_type=RequestType.RETURN,
            status=RequestStatus.PENDING_RETURN,
            category_id=asset.category_id,
            category_name=asset.category.name if asset.category else "",
            include_child=False,
            asset_id=asset.id,
            asset_no=asset.asset_no,
            asset_name=asset.name,
            asset_version=asset.version,
            applicant_id=context.user.id,
            applicant_name=context.user.real_name,
            applicant_dept_id=context.user.dept_id,
            applicant_dept_name=context.user.dept.name if context.user.dept else None,
            reason=payload.reason,
            source_request_id=source.id if source else None,
            return_requested_at=now_cst(),
        )
        self.session.add(request)
        await self.session.flush()
        request.asset = asset
        await self.audit.record(
            action="asset.request.return.create",
            module="资产归还",
            summary=f"发起归还：{asset.name}（{asset.asset_no}）",
            actor=context.user,
            resource_type="asset",
            resource_id=asset.id,
            after={
                "request_no": request.request_no,
                "status": request.status,
                "applicant_name": request.applicant_name,
                "reason": request.reason,
            },
        )
        await commit_or_conflict(self.session)
        allowed = await self._allowed_depts(context)
        return self._request_out(request, context, allowed)

    async def confirm_return(
        self,
        request_id: int,
        payload: AssetReturnConfirmPayload,
        context: AuthContext,
    ) -> AssetRequestOut:
        request = await self._get_request(request_id)
        if request.request_type != RequestType.RETURN:
            raise BizError("该单据不是归还单")
        if request.status != RequestStatus.PENDING_RETURN:
            raise BizError("当前单据不在待归还确认状态")
        allowed = await self._allowed_depts(context)
        self._assert_review_scope(request, context, allowed)

        asset = await self._get_asset(request.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status not in (AssetStatus.IN_USE, AssetStatus.BORROWED):
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.custodian_id != request.applicant_id:
            raise ConflictError("资产责任人已变更，请刷新后重试", code=40911)
        assert_transition(
            RequestType.RETURN, request.status, RequestStatus.COMPLETED
        )

        before = _asset_snapshot(asset)
        asset.status = AssetStatus.IN_STOCK
        asset.custodian_id = None
        asset.custodian = None
        if payload.location:
            asset.location = payload.location
        after = _asset_snapshot(asset)
        after["custodian_name"] = None

        request.status = RequestStatus.COMPLETED
        request.confirm_by_id = context.user.id
        request.confirm_by_name = context.user.real_name
        request.confirmed_at = now_cst()
        request.confirm_comment = payload.comment
        request.outbound_location = payload.location or request.outbound_location

        if request.source_request_id:
            source = (
                await self.session.execute(
                    select(AssetRequest).where(
                        AssetRequest.id == request.source_request_id
                    )
                )
            ).scalar_one_or_none()
            if source is not None and source.status == RequestStatus.BORROWED:
                assert_transition(
                    RequestType.BORROW,
                    source.status,
                    RequestStatus.COMPLETED,
                )
                source.status = RequestStatus.COMPLETED
                source.confirmed_at = now_cst()
                source.confirm_by_id = context.user.id
                source.confirm_by_name = context.user.real_name
                source.confirm_comment = f"由归还单 {request.request_no} 完成"

        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                request_id=request.id,
                action=AssetHistoryAction.RETURN,
                action_label=ASSET_HISTORY_ACTION_LABELS[AssetHistoryAction.RETURN],
                from_status=before["status"],
                to_status=after["status"],
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=context.user.real_name,
                summary=f"确认归还入库（{request.request_no}）",
            )
        )
        await self.audit.record(
            action="asset.request.return.confirm",
            module="资产归还",
            summary=f"确认归还：{request.asset_no} {request.asset_name} 已入库",
            actor=context.user,
            resource_type="asset",
            resource_id=asset.id,
            before=before,
            after=after,
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE)
        return self._request_out(request, context, allowed)

    async def get_request(self, request_id: int, context: AuthContext) -> AssetRequestOut:
        request = await self._get_request(request_id)
        allowed = await self._allowed_depts(context)
        if request.applicant_id != context.user.id and not context.is_superuser:
            is_task_approver = bool(request.flow_id) and (
                ApprovalFlowService.has_task_for_user(request, context.user.id)
            )
            if not is_task_approver:
                if not context.has_permission("asset:request:review"):
                    raise PermissionDenied("无权查看该业务单据")
                self._assert_review_scope(request, context, allowed)
        return self._request_out(request, context, allowed)

    async def scan(self, code: str, context: AuthContext) -> ScanAssetOut:
        normalized = code.strip()
        if not normalized:
            raise BizError("请输入资产编号或扫描二维码")
        asset = (
            await self.session.execute(
                select(Asset)
                .where(
                    Asset.deleted_at.is_(None),
                    or_(
                        Asset.asset_no == normalized,
                        Asset.serial_no == normalized,
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("未找到匹配的资产，请检查二维码或资产编号")
        requests = list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(
                        AssetRequest.asset_id == asset.id,
                        AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES),
                    )
                    .order_by(AssetRequest.id.desc())
                )
            )
            .scalars()
            .all()
        )
        allowed = await self._allowed_depts(context)
        return ScanAssetOut(
            asset=self._available_out(asset),
            requests=[
                self._request_out(item, context, allowed) for item in requests
            ],
        )

    async def asset_history(
        self,
        asset_id: int,
        context: AuthContext,
    ) -> list[AssetHistoryOut]:
        asset = await self._get_asset(asset_id, include_deleted=True)
        allowed = await self._allowed_depts(context)
        if not context.is_superuser:
            if context.data_scope == DataScope.SELF:
                if asset.custodian_id != context.user.id:
                    raise NotFoundError("资产不存在或无权访问")
            elif allowed is not None and asset.dept_id not in allowed:
                raise NotFoundError("资产不存在或无权访问")

        rows = list(
            (
                await self.session.execute(
                    select(AssetHistory)
                    .where(AssetHistory.asset_id == asset.id)
                    .order_by(AssetHistory.created_at.desc(), AssetHistory.id.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return [
            AssetHistoryOut(
                id=row.id,
                asset_id=row.asset_id,
                request_id=row.request_id,
                action=row.action,
                action_label=row.action_label,
                from_status=row.from_status,
                from_status_label=ASSET_STATUS_LABELS.get(
                    row.from_status, row.from_status
                ),
                to_status=row.to_status,
                to_status_label=ASSET_STATUS_LABELS.get(row.to_status, row.to_status),
                before_snapshot=row.before_snapshot,
                after_snapshot=row.after_snapshot,
                operator_name=row.operator_name,
                summary=row.summary,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def due_borrows(self, *, within_days: int = 3) -> list[AssetRequest]:
        today = now_cst().date()
        return list(
            (
                await self.session.execute(
                    select(AssetRequest)
                    .where(
                        AssetRequest.status == RequestStatus.BORROWED,
                        AssetRequest.expected_return_date.is_not(None),
                        AssetRequest.expected_return_date
                        <= today + timedelta(days=within_days),
                    )
                    .order_by(
                        AssetRequest.expected_return_date.asc(),
                        AssetRequest.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def record_due_reminders(self) -> int:
        """Celery 每日扫描：按单据+日期去重后写入审计提醒，便于追溯。"""
        today = now_cst().date()
        created = 0
        for request in await self.due_borrows():
            exists = await self.session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "asset.request.due_reminder",
                    AuditLog.resource_type == "asset",
                    AuditLog.resource_id == str(request.asset_id),
                    AuditLog.summary.like(f"%{request.request_no}%"),
                    AuditLog.created_at >= datetime.combine(today, datetime.min.time()),
                )
            )
            if exists:
                continue
            overdue_days = (
                (today - request.expected_return_date).days
                if request.expected_return_date
                else 0
            )
            summary = (
                f"借用到期提醒：{request.request_no} {request.asset_name}，"
                + (f"已逾期 {overdue_days} 天" if overdue_days > 0 else "即将到期")
            )
            await self.audit.record(
                action="asset.request.due_reminder",
                module="资产借用",
                summary=summary,
                actor_id=None,
                actor_name="系统计划任务",
                resource_type="asset",
                resource_id=request.asset_id,
                after={
                    "request_no": request.request_no,
                    "expected_return_date": _json_value(request.expected_return_date),
                    "applicant_name": request.applicant_name,
                    "overdue_days": max(overdue_days, 0),
                },
            )
            created += 1
        if created:
            await self.session.commit()
        return created
