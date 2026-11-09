from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_flow import ACTIVE_REQUEST_STATUSES
from app.core.asset_ops import (
    SCRAP_ACTIVE_STATUSES,
    SCRAP_NO_PREFIX,
    SCRAP_STATUS_LABELS,
    SCRAP_STATUS_TAG_TYPES,
    TRANSFER_ACTIVE_STATUSES,
    TRANSFER_NO_PREFIX,
    TRANSFER_STATUS_LABELS,
    TRANSFER_STATUS_TAG_TYPES,
    ScrapStatus,
    TransferStatus,
)
from app.core.assets import ASSET_STATUS_LABELS, AssetStatus
from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.core.maintenance import MAINTENANCE_ACTIVE_STATUSES
from app.models import (
    Asset,
    AssetCategory,
    AssetHistory,
    AssetMaintenance,
    AssetRequest,
    AssetScrap,
    AssetTransfer,
    AuditLog,
    Dept,
    User,
)
from app.models.base import now_cst
from app.schemas.asset_ops import (
    AssetScrapOut,
    AssetScrapPageOut,
    AssetTransferOut,
    AssetTransferPageOut,
    OpsAssetOut,
    OpsConfirmPayload,
    ScrapApprovePayload,
    ScrapCreate,
    TransferCreate,
)
from app.services.asset_snapshot import asset_snapshot
from app.services.audit_service import AuditService
from app.services import dingtalk_approval
from app.services.dingtalk_approval import LINK_RUNNING
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_domain_condition,
    category_domain_allowed,
    is_self_only,
    scoped_dept_ids,
)
from app.services.txn import commit_or_conflict

STATUS_CONFLICT_MESSAGE = "资产状态已变更，请刷新后重试"


def _user_name(user: User) -> str:
    return user.real_name or user.username


class AssetOpsService:
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

    async def _get_transfer(self, transfer_id: int) -> AssetTransfer:
        item = (
            await self.session.execute(
                select(AssetTransfer).where(AssetTransfer.id == transfer_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("调拨单不存在")
        return item

    async def _get_scrap(self, scrap_id: int) -> AssetScrap:
        item = (
            await self.session.execute(
                select(AssetScrap).where(AssetScrap.id == scrap_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("报废单不存在")
        return item

    async def _allowed_depts(
        self, context: AuthContext, resource: str
    ) -> set[int] | None:
        return await scoped_dept_ids(self.session, context, resource=resource)

    @staticmethod
    def _option_resources(context: AuthContext) -> list[str]:
        resources: list[str] = []
        if context.has_permission("asset:transfer:create"):
            resources.append("transfer")
        if context.has_permission("asset:scrap:create"):
            resources.append("scrap")
        if context.has_permission("asset:inventory:create"):
            resources.append("inventory")
        return resources or ["transfer"]

    async def _option_allowed_depts(
        self, context: AuthContext, resources: list[str]
    ) -> set[int] | None:
        merged: set[int] = set()
        for resource in resources:
            allowed = await self._allowed_depts(context, resource)
            if allowed is None:
                return None
            merged |= allowed
        return merged

    @staticmethod
    def _option_domains(
        context: AuthContext, resources: list[str]
    ) -> tuple[str, ...] | None:
        merged: set[str] = set()
        for resource in resources:
            domains = context.allowed_domains(resource)
            if domains is None:
                return None
            merged.update(domains)
        return tuple(sorted(merged))

    @staticmethod
    def _domain_condition(column, context: AuthContext, resource: str):
        domain_condition = asset_domain_condition(context, resource)
        if domain_condition is None:
            return None
        return column.in_(select(Asset.id).where(domain_condition))

    @staticmethod
    def _in_scope(dept_id: int | None, allowed: set[int] | None) -> bool:
        return allowed is None or (dept_id is not None and dept_id in allowed)

    @staticmethod
    def _in_record_domain(item, context: AuthContext, resource: str) -> bool:
        return category_domain_allowed(item.asset.category, context, resource)

    def _record_in_scope(
        self, item, context: AuthContext, resource: str, allowed: set[int] | None
    ) -> bool:
        if is_self_only(context, resource):
            return item.applicant_id == context.user.id
        return self._in_scope(item.from_dept_id, allowed)

    def _assert_record_domain(self, item, context: AuthContext, resource: str) -> None:
        if not self._in_record_domain(item, context, resource):
            raise PermissionDenied("无权操作该分类下的业务单据")

    async def _assert_asset_scope(
        self, asset: Asset, context: AuthContext, resource: str
    ) -> None:
        if not category_domain_allowed(asset.category, context, resource):
            raise PermissionDenied("无权操作该分类下的资产")
        if is_self_only(context, resource):
            if context.user.id not in (asset.custodian_id, asset.created_by_id):
                raise PermissionDenied("无权操作该资产")
            return
        allowed = await self._allowed_depts(context, resource)
        if allowed is not None and asset.dept_id not in allowed:
            raise PermissionDenied("无权操作该部门的资产")

    async def _assert_asset_operable(self, asset: Asset) -> None:
        if asset.status == AssetStatus.REPAIRING:
            raise BizError("该资产维修中，暂不能发起调拨或报废")
        if asset.status in (
            AssetStatus.SCRAPPED,
            AssetStatus.PENDING_STOCK,
            AssetStatus.PENDING_SCRAP,
        ):
            raise BizError("该资产当前状态不允许发起调拨或报废")

    async def _assert_no_active_business(self, asset_id: int) -> None:
        active_request = await self.session.scalar(
            select(AssetRequest.id)
            .where(
                AssetRequest.asset_id == asset_id,
                AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES),
            )
            .limit(1)
        )
        if active_request:
            raise BizError("该资产存在处理中的领用/借用单据，暂不能操作")
        active_maintenance = await self.session.scalar(
            select(AssetMaintenance.id)
            .where(
                AssetMaintenance.asset_id == asset_id,
                AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_maintenance:
            raise BizError("该资产存在处理中的维修工单，暂不能操作")

    async def _resolve_target(
        self,
        payload: TransferCreate,
        asset: Asset,
    ) -> tuple[int | None, str | None, int | None, str | None, str | None]:
        dept_id = payload.to_dept_id
        custodian = None
        if payload.to_custodian_id is not None:
            custodian = await self.session.get(User, payload.to_custodian_id)
            if custodian is None or custodian.status != 1:
                raise BizError("指定的责任人不存在或已停用")
            if dept_id is None:
                dept_id = custodian.dept_id

        dept_name = None
        if dept_id is not None:
            dept = await self.session.get(Dept, dept_id)
            if dept is None:
                raise BizError("指定的调入部门不存在")
            dept_name = dept.name

        custodian_name = _user_name(custodian) if custodian else None
        location = payload.to_location if payload.to_location is not None else asset.location
        return dept_id, dept_name, custodian.id if custodian else None, custodian_name, location

    def _transfer_out(
        self,
        item: AssetTransfer,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> AssetTransferOut:
        asset = item.asset
        in_scope = self._record_in_scope(
            item, context, "transfer", allowed
        ) and category_domain_allowed(asset.category, context, "transfer")
        can_review = context.has_permission("asset:transfer:approve") and in_scope
        dingtalk = item.__dict__.get("dingtalk_approval")
        dingtalk_running = bool(
            dingtalk is not None and dingtalk.status == LINK_RUNNING
        )
        can_cancel = False
        if item.status == TransferStatus.PENDING_APPROVAL:
            can_cancel = (
                item.applicant_id == context.user.id
                or context.has_permission("asset:transfer:cancel")
            )
        elif item.status == TransferStatus.PENDING_TRANSFER:
            can_cancel = context.has_permission("asset:transfer:approve") and in_scope
        return AssetTransferOut(
            id=item.id,
            transfer_no=item.transfer_no,
            status=item.status,
            status_label=TRANSFER_STATUS_LABELS.get(item.status, item.status),
            status_tag_type=TRANSFER_STATUS_TAG_TYPES.get(item.status, "info"),
            asset_id=item.asset_id,
            asset_no=item.asset_no,
            asset_name=item.asset_name,
            asset_version=asset.version,
            asset_status=asset.status,
            asset_status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
            from_dept_id=item.from_dept_id,
            from_dept_name=item.from_dept_name,
            from_custodian_id=item.from_custodian_id,
            from_custodian_name=item.from_custodian_name,
            from_location=item.from_location,
            to_dept_id=item.to_dept_id,
            to_dept_name=item.to_dept_name,
            to_custodian_id=item.to_custodian_id,
            to_custodian_name=item.to_custodian_name,
            to_location=item.to_location,
            reason=item.reason,
            applicant_id=item.applicant_id,
            applicant_name=item.applicant_name,
            applicant_dept_id=item.applicant_dept_id,
            applicant_dept_name=item.applicant_dept_name,
            approver_name=item.approver_name,
            approved_at=item.approved_at,
            approval_comment=item.approval_comment,
            dingtalk_instance_id=(
                dingtalk.process_instance_id if dingtalk is not None else None
            ),
            dingtalk_status=dingtalk.status if dingtalk is not None else None,
            dingtalk_result=dingtalk.result if dingtalk is not None else None,
            completed_by_name=item.completed_by_name,
            completed_at=item.completed_at,
            completion_comment=item.completion_comment,
            can_approve=item.status == TransferStatus.PENDING_APPROVAL
            and can_review
            and not dingtalk_running,
            can_reject=item.status == TransferStatus.PENDING_APPROVAL
            and can_review
            and not dingtalk_running,
            can_confirm=item.status == TransferStatus.PENDING_TRANSFER
            and context.has_permission("asset:transfer:confirm")
            and in_scope,
            can_cancel=can_cancel,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def _scrap_out(
        self,
        item: AssetScrap,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> AssetScrapOut:
        asset = item.asset
        in_scope = self._record_in_scope(
            item, context, "scrap", allowed
        ) and category_domain_allowed(asset.category, context, "scrap")
        can_review = context.has_permission("asset:scrap:approve") and in_scope
        can_cancel = (
            item.status == ScrapStatus.PENDING_APPROVAL
            and (
                item.applicant_id == context.user.id
                or context.has_permission("asset:scrap:cancel")
            )
        )
        return AssetScrapOut(
            id=item.id,
            scrap_no=item.scrap_no,
            status=item.status,
            status_label=SCRAP_STATUS_LABELS.get(item.status, item.status),
            status_tag_type=SCRAP_STATUS_TAG_TYPES.get(item.status, "info"),
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
            reason=item.reason,
            disposal_method=item.disposal_method,
            residual_value=(
                float(item.residual_value) if item.residual_value is not None else None
            ),
            applicant_id=item.applicant_id,
            applicant_name=item.applicant_name,
            applicant_dept_id=item.applicant_dept_id,
            applicant_dept_name=item.applicant_dept_name,
            approver_name=item.approver_name,
            approved_at=item.approved_at,
            approval_comment=item.approval_comment,
            completed_by_name=item.completed_by_name,
            completed_at=item.completed_at,
            completion_comment=item.completion_comment,
            can_approve=item.status == ScrapStatus.PENDING_APPROVAL and can_review,
            can_reject=item.status == ScrapStatus.PENDING_APPROVAL and can_review,
            can_confirm=item.status == ScrapStatus.PENDING_DISPOSAL
            and context.has_permission("asset:scrap:confirm")
            and in_scope,
            can_cancel=can_cancel,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    async def option_departments(self, context: AuthContext) -> list[dict[str, object]]:
        allowed = await self._option_allowed_depts(
            context, self._option_resources(context)
        )
        conditions: list = [Dept.status == 1]
        if allowed is not None:
            conditions.append(Dept.id.in_(allowed) if allowed else false())
        rows = list(
            (
                await self.session.execute(
                    select(Dept).where(*conditions).order_by(Dept.path, Dept.sort, Dept.id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": dept.id,
                "parent_id": dept.parent_id,
                "name": dept.name,
                "level": dept.level,
                "path": dept.path,
            }
            for dept in rows
        ]

    async def option_users(
        self, context: AuthContext, keyword: str | None
    ) -> list[dict[str, object]]:
        allowed = await self._option_allowed_depts(
            context, self._option_resources(context)
        )
        conditions: list = [User.status == 1]
        if allowed is not None:
            conditions.append(User.dept_id.in_(allowed) if allowed else false())
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    User.real_name.like(like),
                    User.username.like(like),
                    User.employee_no.like(like),
                )
            )
        rows = list(
            (
                await self.session.execute(
                    select(User).where(*conditions).order_by(User.id).limit(30)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": user.id,
                "name": user.real_name or user.username,
                "username": user.username,
                "dept_id": user.dept_id,
                "dept_name": user.dept.name if user.dept else None,
            }
            for user in rows
        ]

    async def option_categories(self, context: AuthContext) -> list[dict[str, object]]:
        domains = self._option_domains(
            context, self._option_resources(context)
        )
        conditions: list = [AssetCategory.status == 1]
        if domains is not None:
            conditions.append(AssetCategory.asset_domain.in_(domains))
        rows = list(
            (
                await self.session.execute(
                    select(AssetCategory)
                    .where(*conditions)
                    .order_by(AssetCategory.path, AssetCategory.sort, AssetCategory.id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": category.id,
                "parent_id": category.parent_id,
                "name": category.name,
                "level": category.level,
                "path": category.path,
            }
            for category in rows
        ]

    async def list_operable_assets(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        purpose: str,
        page: int,
        page_size: int,
    ) -> tuple[list[OpsAssetOut], int]:
        resource = "transfer" if purpose == "transfer" else "scrap"
        allowed = await self._allowed_depts(context, resource)
        conditions: list = [
            Asset.deleted_at.is_(None),
            Asset.status.notin_(
                (
                    AssetStatus.SCRAPPED,
                    AssetStatus.PENDING_STOCK,
                    AssetStatus.PENDING_SCRAP,
                    AssetStatus.REPAIRING,
                )
            ),
        ]
        domain_condition = asset_domain_condition(context, resource)
        if domain_condition is not None:
            conditions.append(domain_condition)
        if is_self_only(context, resource):
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
        active_request_assets = select(AssetRequest.asset_id).where(
            AssetRequest.status.in_(ACTIVE_REQUEST_STATUSES)
        )
        conditions.append(Asset.id.notin_(active_request_assets))
        conditions.append(
            Asset.id.notin_(
                select(AssetMaintenance.asset_id).where(
                    AssetMaintenance.status.in_(MAINTENANCE_ACTIVE_STATUSES)
                )
            )
        )
        if purpose == "transfer":
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
        items = [
            OpsAssetOut(
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
        ]
        return items, total

    async def list_transfers(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> AssetTransferPageOut:
        allowed = await self._allowed_depts(context, "transfer")
        conditions: list = []
        domain_condition = self._domain_condition(
            AssetTransfer.asset_id, context, "transfer"
        )
        if domain_condition is not None:
            conditions.append(domain_condition)
        if is_self_only(context, "transfer"):
            conditions.append(AssetTransfer.applicant_id == context.user.id)
        elif allowed is not None:
            conditions.append(
                AssetTransfer.from_dept_id.in_(allowed) if allowed else false()
            )
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetTransfer.transfer_no.like(like),
                    AssetTransfer.asset_no.like(like),
                    AssetTransfer.asset_name.like(like),
                    AssetTransfer.applicant_name.like(like),
                )
            )
        if status:
            conditions.append(AssetTransfer.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(AssetTransfer).where(*conditions)
        )
        rows = (
            (
                await self.session.execute(
                    select(AssetTransfer)
                    .where(*conditions)
                    .order_by(AssetTransfer.created_at.desc(), AssetTransfer.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return AssetTransferPageOut(
            items=[self._transfer_out(item, context, allowed) for item in rows],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def create_transfer(
        self, payload: TransferCreate, context: AuthContext
    ) -> AssetTransferOut:
        asset = await self._get_asset(payload.asset_id)
        await self._assert_asset_scope(asset, context, "transfer")
        await self._assert_asset_operable(asset)
        await self._assert_no_active_business(asset.id)
        active = await self.session.scalar(
            select(AssetTransfer.id)
            .where(
                AssetTransfer.asset_id == asset.id,
                AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active:
            raise BizError("该资产已有处理中的调拨单")
        active_scrap = await self.session.scalar(
            select(AssetScrap.id)
            .where(
                AssetScrap.asset_id == asset.id,
                AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_scrap:
            raise BizError("该资产存在处理中的报废单，暂不能调拨")

        dept_id, dept_name, custodian_id, custodian_name, location = (
            await self._resolve_target(payload, asset)
        )
        item = AssetTransfer(
            transfer_no=await self._next_no(
                AssetTransfer.transfer_no, TRANSFER_NO_PREFIX
            ),
            status=TransferStatus.PENDING_APPROVAL,
            asset_id=asset.id,
            asset_no=asset.asset_no,
            asset_name=asset.name,
            asset_version=asset.version,
            from_dept_id=asset.dept_id,
            from_dept_name=asset.dept.name if asset.dept else None,
            from_custodian_id=asset.custodian_id,
            from_custodian_name=asset.custodian.real_name if asset.custodian else None,
            from_location=asset.location,
            to_dept_id=dept_id,
            to_dept_name=dept_name,
            to_custodian_id=custodian_id,
            to_custodian_name=custodian_name,
            to_location=location,
            reason=payload.reason,
            applicant_id=context.user.id,
            applicant_name=_user_name(context.user),
            applicant_dept_id=context.user.dept_id,
            applicant_dept_name=context.user.dept.name if context.user.dept else None,
        )
        self.session.add(item)
        await self.session.flush()
        dingtalk_link = None
        config = await dingtalk_approval.get_approval_config(self.session)
        if dingtalk_approval.channel_enabled(
            config, dingtalk_approval.DOC_TYPE_TRANSFER, context.user
        ):
            dingtalk_link = await dingtalk_approval.create_instance(
                self.session,
                config,
                doc_type=dingtalk_approval.DOC_TYPE_TRANSFER,
                doc_no=item.transfer_no,
                title=f"IT资产调拨申请：{item.transfer_no}",
                originator_userid=context.user.dingtalk_userid,
                form_values=[
                    {"name": "申请人", "value": _user_name(context.user)},
                    {"name": "调出部门", "value": item.from_dept_name or ""},
                    {"name": "调入部门", "value": item.to_dept_name or ""},
                    {
                        "name": "资产",
                        "value": f"{asset.name}（{asset.asset_no}）",
                    },
                    {"name": "调拨事由", "value": payload.reason or ""},
                ],
                transfer_id=item.id,
            )
            item.dingtalk_approval = dingtalk_link
        item.asset = asset
        await self.audit.record(
            action="asset.transfer.create",
            module="asset",
            summary=(
                f"发起调拨：{asset.name}（{asset.asset_no}）"
                + ("（钉钉审批）" if dingtalk_link is not None else "")
            ),
            actor=context.user,
            resource_type="asset_transfer",
            resource_id=item.id,
            after={
                "status": item.status,
                "to_dept": dept_name,
                "to_custodian": custodian_name,
                "dingtalk_instance_id": (
                    dingtalk_link.process_instance_id
                    if dingtalk_link is not None
                    else None
                ),
            },
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._transfer_out(item, context, await self._allowed_depts(context, "transfer"))

    async def get_transfer(self, transfer_id: int, context: AuthContext) -> AssetTransferOut:
        item = await self._get_transfer(transfer_id)
        allowed = await self._allowed_depts(context, "transfer")
        self._assert_record_domain(item, context, "transfer")
        if not self._record_in_scope(item, context, "transfer", allowed):
            raise PermissionDenied("无权查看该调拨单")
        return self._transfer_out(item, context, allowed)

    async def approve_transfer(
        self, transfer_id: int, comment: str | None, context: AuthContext
    ) -> AssetTransferOut:
        item = await self._get_transfer(transfer_id)
        allowed = await self._allowed_depts(context, "transfer")
        if not self._record_in_scope(
            item, context, "transfer", allowed
        ) or not self._in_record_domain(
            item, context, "transfer"
        ):
            raise PermissionDenied("无权审批该调拨单")
        if item.status != TransferStatus.PENDING_APPROVAL:
            raise BizError("当前调拨单不在待审批状态")
        if await dingtalk_approval.has_running_link(
            self.session, transfer_id=item.id
        ):
            raise BizError("该调拨单已提交钉钉审批，请在钉钉中处理")
        item.status = TransferStatus.PENDING_TRANSFER
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = comment
        await self.audit.record(
            action="asset.transfer.approve",
            module="asset",
            summary=f"审批调拨：{item.transfer_no}",
            actor=context.user,
            resource_type="asset_transfer",
            resource_id=item.id,
            before={"status": TransferStatus.PENDING_APPROVAL},
            after={"status": item.status},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._transfer_out(item, context, allowed)

    async def reject_transfer(
        self, transfer_id: int, comment: str | None, context: AuthContext
    ) -> AssetTransferOut:
        item = await self._get_transfer(transfer_id)
        allowed = await self._allowed_depts(context, "transfer")
        if not self._record_in_scope(
            item, context, "transfer", allowed
        ) or not self._in_record_domain(
            item, context, "transfer"
        ):
            raise PermissionDenied("无权审批该调拨单")
        if item.status != TransferStatus.PENDING_APPROVAL:
            raise BizError("当前调拨单不在待审批状态")
        if await dingtalk_approval.has_running_link(
            self.session, transfer_id=item.id
        ):
            raise BizError("该调拨单已提交钉钉审批，请在钉钉中处理")
        item.status = TransferStatus.REJECTED
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = comment
        await self.audit.record(
            action="asset.transfer.reject",
            module="asset",
            summary=f"驳回调拨：{item.transfer_no}",
            actor=context.user,
            resource_type="asset_transfer",
            resource_id=item.id,
            after={"status": item.status, "comment": comment},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._transfer_out(item, context, allowed)

    async def cancel_transfer(
        self, transfer_id: int, context: AuthContext
    ) -> AssetTransferOut:
        item = await self._get_transfer(transfer_id)
        allowed = await self._allowed_depts(context, "transfer")
        self._assert_record_domain(item, context, "transfer")
        if not self._record_in_scope(item, context, "transfer", allowed):
            raise PermissionDenied("无权撤销该调拨单")
        if item.status == TransferStatus.PENDING_APPROVAL:
            if (
                item.applicant_id != context.user.id
                and not context.has_permission("asset:transfer:cancel")
            ):
                raise PermissionDenied("无权撤销该调拨单")
        elif item.status == TransferStatus.PENDING_TRANSFER:
            if not (
                context.has_permission("asset:transfer:approve")
                and self._record_in_scope(item, context, "transfer", allowed)
                and self._in_record_domain(item, context, "transfer")
            ):
                raise PermissionDenied("无权撤销已审批的调拨单")
        else:
            raise BizError("当前调拨单状态不允许撤销")
        previous = item.status
        item.status = TransferStatus.CANCELLED
        await self.audit.record(
            action="asset.transfer.cancel",
            module="asset",
            summary=f"撤销调拨：{item.transfer_no}",
            actor=context.user,
            resource_type="asset_transfer",
            resource_id=item.id,
            before={"status": previous},
            after={"status": item.status},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._transfer_out(item, context, allowed)

    async def confirm_transfer(
        self,
        transfer_id: int,
        payload: OpsConfirmPayload,
        context: AuthContext,
    ) -> AssetTransferOut:
        item = await self._get_transfer(transfer_id)
        allowed = await self._allowed_depts(context, "transfer")
        if not self._record_in_scope(
            item, context, "transfer", allowed
        ) or not self._in_record_domain(
            item, context, "transfer"
        ):
            raise PermissionDenied("无权操作该调拨单")
        if item.status != TransferStatus.PENDING_TRANSFER:
            raise BizError("当前调拨单不在待确认状态")

        asset = await self._get_asset(item.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status in (AssetStatus.SCRAPPED, AssetStatus.PENDING_STOCK):
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        await self._assert_no_active_business(asset.id)

        before = asset_snapshot(asset)
        target_dept = (
            await self.session.get(Dept, item.to_dept_id) if item.to_dept_id else None
        )
        target_custodian = (
            await self.session.get(User, item.to_custodian_id)
            if item.to_custodian_id
            else None
        )
        asset.dept = target_dept
        asset.dept_id = item.to_dept_id
        asset.custodian = target_custodian
        asset.custodian_id = item.to_custodian_id
        asset.location = item.to_location
        after = asset_snapshot(asset)

        item.status = TransferStatus.COMPLETED
        item.completed_by_id = context.user.id
        item.completed_by_name = _user_name(context.user)
        item.completed_at = now_cst()
        item.completion_comment = payload.comment
        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="TRANSFER",
                action_label="调拨完成",
                from_status=asset.status,
                to_status=asset.status,
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=_user_name(context.user),
                summary=(
                    f"调拨至 {item.to_dept_name or '原部门'} / "
                    f"{item.to_custodian_name or '无责任人'}"
                ),
            )
        )
        await self.session.flush()
        item.asset_version = asset.version
        await self.audit.record(
            action="asset.transfer.complete",
            module="asset",
            summary=f"完成调拨：{item.transfer_no}",
            actor=context.user,
            resource_type="asset_transfer",
            resource_id=item.id,
            before=before,
            after=after,
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._transfer_out(item, context, allowed)

    async def list_scraps(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> AssetScrapPageOut:
        allowed = await self._allowed_depts(context, "scrap")
        conditions: list = []
        domain_condition = self._domain_condition(
            AssetScrap.asset_id, context, "scrap"
        )
        if domain_condition is not None:
            conditions.append(domain_condition)
        if is_self_only(context, "scrap"):
            conditions.append(AssetScrap.applicant_id == context.user.id)
        elif allowed is not None:
            conditions.append(
                AssetScrap.from_dept_id.in_(allowed) if allowed else false()
            )
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetScrap.scrap_no.like(like),
                    AssetScrap.asset_no.like(like),
                    AssetScrap.asset_name.like(like),
                    AssetScrap.applicant_name.like(like),
                )
            )
        if status:
            conditions.append(AssetScrap.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(AssetScrap).where(*conditions)
        )
        rows = (
            (
                await self.session.execute(
                    select(AssetScrap)
                    .where(*conditions)
                    .order_by(AssetScrap.created_at.desc(), AssetScrap.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return AssetScrapPageOut(
            items=[self._scrap_out(item, context, allowed) for item in rows],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def create_scrap(
        self, payload: ScrapCreate, context: AuthContext
    ) -> AssetScrapOut:
        asset = await self._get_asset(payload.asset_id)
        await self._assert_asset_scope(asset, context, "scrap")
        await self._assert_asset_operable(asset)
        if asset.status == AssetStatus.PENDING_SCRAP:
            raise BizError("该资产已在待报废状态")
        await self._assert_no_active_business(asset.id)
        active_scrap = await self.session.scalar(
            select(AssetScrap.id)
            .where(
                AssetScrap.asset_id == asset.id,
                AssetScrap.status.in_(SCRAP_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_scrap:
            raise BizError("该资产已有处理中的报废单")
        active_transfer = await self.session.scalar(
            select(AssetTransfer.id)
            .where(
                AssetTransfer.asset_id == asset.id,
                AssetTransfer.status.in_(TRANSFER_ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active_transfer:
            raise BizError("该资产存在处理中的调拨单，暂不能报废")

        item = AssetScrap(
            scrap_no=await self._next_no(AssetScrap.scrap_no, SCRAP_NO_PREFIX),
            status=ScrapStatus.PENDING_APPROVAL,
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
            reason=payload.reason,
            disposal_method=payload.disposal_method,
            residual_value=(
                Decimal(str(payload.residual_value))
                if payload.residual_value is not None
                else None
            ),
            applicant_id=context.user.id,
            applicant_name=_user_name(context.user),
            applicant_dept_id=context.user.dept_id,
            applicant_dept_name=context.user.dept.name if context.user.dept else None,
        )
        self.session.add(item)
        await self.session.flush()
        item.asset = asset
        await self.audit.record(
            action="asset.scrap.create",
            module="asset",
            summary=f"发起报废：{asset.name}（{asset.asset_no}）",
            actor=context.user,
            resource_type="asset_scrap",
            resource_id=item.id,
            after={
                "status": item.status,
                "reason": payload.reason,
                "disposal_method": payload.disposal_method,
                "residual_value": (
                    str(item.residual_value) if item.residual_value is not None else None
                ),
            },
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._scrap_out(item, context, await self._allowed_depts(context, "scrap"))

    async def get_scrap(self, scrap_id: int, context: AuthContext) -> AssetScrapOut:
        item = await self._get_scrap(scrap_id)
        allowed = await self._allowed_depts(context, "scrap")
        self._assert_record_domain(item, context, "scrap")
        if not self._record_in_scope(item, context, "scrap", allowed):
            raise PermissionDenied("无权查看该报废单")
        return self._scrap_out(item, context, allowed)

    async def approve_scrap(
        self,
        scrap_id: int,
        payload: ScrapApprovePayload,
        context: AuthContext,
    ) -> AssetScrapOut:
        item = await self._get_scrap(scrap_id)
        allowed = await self._allowed_depts(context, "scrap")
        if not self._record_in_scope(
            item, context, "scrap", allowed
        ) or not self._in_record_domain(
            item, context, "scrap"
        ):
            raise PermissionDenied("无权审批该报废单")
        if item.status != ScrapStatus.PENDING_APPROVAL:
            raise BizError("当前报废单不在待审批状态")
        await self._assert_no_active_business(item.asset_id)

        asset = await self._get_asset(item.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status in (AssetStatus.SCRAPPED, AssetStatus.PENDING_SCRAP):
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)

        before = asset_snapshot(asset)
        asset.status = AssetStatus.PENDING_SCRAP
        after = asset_snapshot(asset)

        item.status = ScrapStatus.PENDING_DISPOSAL
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = payload.comment
        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="SCRAP_PENDING",
                action_label="报废审批通过",
                from_status=before["status"],
                to_status=asset.status,
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=_user_name(context.user),
                summary=f"报废单 {item.scrap_no} 审批通过，等待处置",
            )
        )
        await self.session.flush()
        item.asset_version = asset.version
        await self.audit.record(
            action="asset.scrap.approve",
            module="asset",
            summary=f"审批报废：{item.scrap_no}",
            actor=context.user,
            resource_type="asset_scrap",
            resource_id=item.id,
            before={"asset_status": before["status"]},
            after={"asset_status": asset.status},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._scrap_out(item, context, allowed)

    async def reject_scrap(
        self, scrap_id: int, comment: str | None, context: AuthContext
    ) -> AssetScrapOut:
        item = await self._get_scrap(scrap_id)
        allowed = await self._allowed_depts(context, "scrap")
        if not self._record_in_scope(
            item, context, "scrap", allowed
        ) or not self._in_record_domain(
            item, context, "scrap"
        ):
            raise PermissionDenied("无权审批该报废单")
        if item.status != ScrapStatus.PENDING_APPROVAL:
            raise BizError("当前报废单不在待审批状态")
        item.status = ScrapStatus.REJECTED
        item.approver_id = context.user.id
        item.approver_name = _user_name(context.user)
        item.approved_at = now_cst()
        item.approval_comment = comment
        await self.audit.record(
            action="asset.scrap.reject",
            module="asset",
            summary=f"驳回报废：{item.scrap_no}",
            actor=context.user,
            resource_type="asset_scrap",
            resource_id=item.id,
            after={"status": item.status, "comment": comment},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._scrap_out(item, context, allowed)

    async def cancel_scrap(
        self, scrap_id: int, context: AuthContext
    ) -> AssetScrapOut:
        item = await self._get_scrap(scrap_id)
        allowed = await self._allowed_depts(context, "scrap")
        self._assert_record_domain(item, context, "scrap")
        if not self._record_in_scope(item, context, "scrap", allowed):
            raise PermissionDenied("无权撤销该报废单")
        if item.status != ScrapStatus.PENDING_APPROVAL:
            raise BizError("仅待审批的报废单可以撤销")
        if (
            item.applicant_id != context.user.id
            and not context.has_permission("asset:scrap:cancel")
        ):
            raise PermissionDenied("无权撤销该报废单")
        item.status = ScrapStatus.CANCELLED
        await self.audit.record(
            action="asset.scrap.cancel",
            module="asset",
            summary=f"撤销报废：{item.scrap_no}",
            actor=context.user,
            resource_type="asset_scrap",
            resource_id=item.id,
            after={"status": item.status},
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._scrap_out(item, context, allowed)

    async def confirm_scrap(
        self,
        scrap_id: int,
        payload: OpsConfirmPayload,
        context: AuthContext,
    ) -> AssetScrapOut:
        item = await self._get_scrap(scrap_id)
        allowed = await self._allowed_depts(context, "scrap")
        if not self._record_in_scope(
            item, context, "scrap", allowed
        ) or not self._in_record_domain(
            item, context, "scrap"
        ):
            raise PermissionDenied("无权操作该报废单")
        if item.status != ScrapStatus.PENDING_DISPOSAL:
            raise BizError("当前报废单不在待处置状态")

        asset = await self._get_asset(item.asset_id, for_update=True)
        if payload.version != asset.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)
        if asset.status != AssetStatus.PENDING_SCRAP:
            raise ConflictError(STATUS_CONFLICT_MESSAGE, code=40911)

        before = asset_snapshot(asset)
        asset.status = AssetStatus.SCRAPPED
        asset.custodian = None
        asset.custodian_id = None
        after = asset_snapshot(asset)

        item.status = ScrapStatus.COMPLETED
        item.completed_by_id = context.user.id
        item.completed_by_name = _user_name(context.user)
        item.completed_at = now_cst()
        item.completion_comment = payload.comment
        self.session.add(
            AssetHistory(
                asset_id=asset.id,
                action="SCRAP_COMPLETED",
                action_label="确认报废",
                from_status=before["status"],
                to_status=asset.status,
                before_snapshot=before,
                after_snapshot=after,
                operator_id=context.user.id,
                operator_name=_user_name(context.user),
                summary=f"报废单 {item.scrap_no} 处置完成，资产已报废",
            )
        )
        await self.session.flush()
        item.asset_version = asset.version
        await self.audit.record(
            action="asset.scrap.complete",
            module="asset",
            summary=f"确认报废：{item.scrap_no}",
            actor=context.user,
            resource_type="asset_scrap",
            resource_id=item.id,
            before=before,
            after=after,
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE, code=40911)
        return self._scrap_out(item, context, allowed)
