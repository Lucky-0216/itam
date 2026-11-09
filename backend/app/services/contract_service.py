from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import ASSET_STATUS_LABELS
from app.core.contract import (
    CONTRACT_EXPIRING_DAYS,
    CONTRACT_NO_PREFIX,
    CONTRACT_STATUS_LABELS,
    CONTRACT_STATUS_TAG_TYPES,
    CONTRACT_TYPE_LABELS,
    CONTRACT_TYPE_TAG_TYPES,
    ContractStatus,
    contract_effective_status,
)
from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.models import (
    Asset,
    AssetContract,
    AssetContractAsset,
    AuditLog,
    Dept,
    User,
)
from app.models.base import now_cst
from app.schemas.contract import (
    ContractAssetOption,
    ContractAssetOptionPage,
    ContractAssetOut,
    ContractCreate,
    ContractLinkPayload,
    ContractOut,
    ContractOwnerOption,
    ContractPageOut,
    ContractRenewPayload,
    ContractSummaryOut,
    ContractTerminatePayload,
    ContractUpdate,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    asset_domain_condition,
    asset_scope_conditions,
    category_domain_allowed,
    is_self_only,
    scoped_dept_ids,
)
from app.services.txn import commit_or_conflict

CONTRACT_CONFLICT_MESSAGE = "合同信息已变更，请刷新后重试"


def _user_name(user: User) -> str:
    return user.real_name or user.username


class ContractService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _next_no(self) -> str:
        head = f"{CONTRACT_NO_PREFIX}-{now_cst():%Y%m}-"
        max_no = await self.session.scalar(
            select(func.max(AssetContract.contract_no)).where(
                AssetContract.contract_no.like(f"{head}%")
            )
        )
        sequence = 1
        if max_no:
            suffix = max_no[len(head) :]
            if suffix.isdigit():
                sequence = int(suffix) + 1
        return f"{head}{sequence:04d}"

    async def _get_contract(
        self,
        contract_id: int,
        *,
        for_update: bool = False,
        populate_existing: bool = False,
    ) -> AssetContract:
        stmt = select(AssetContract).where(AssetContract.id == contract_id)
        if for_update:
            stmt = stmt.with_for_update()
        if populate_existing:
            stmt = stmt.execution_options(populate_existing=True)
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if item is None:
            raise NotFoundError("合同不存在")
        return item

    async def _allowed_depts(self, context: AuthContext) -> set[int] | None:
        return await scoped_dept_ids(self.session, context, resource="contract")

    async def _target_depts(self, context: AuthContext) -> set[int] | None:
        if is_self_only(context, "contract"):
            return {context.user.dept_id} if context.user.dept_id else set()
        return await self._allowed_depts(context)

    @staticmethod
    def _link_in_domain(asset: Asset | None, context: AuthContext) -> bool:
        return asset is not None and category_domain_allowed(
            asset.category, context, "contract"
        )

    def _contract_in_domain(
        self, contract: AssetContract, context: AuthContext
    ) -> bool:
        if context.allowed_domains("contract") is None:
            return True
        links = [link for link in contract.links if link.asset is not None]
        if not links:
            return False
        return any(self._link_in_domain(link.asset, context) for link in links)

    @classmethod
    def _domain_conditions(cls, context: AuthContext) -> list:
        if context.allowed_domains("contract") is None:
            return []
        domain_condition = asset_domain_condition(context, "contract")
        linked_ids = (
            select(AssetContractAsset.contract_id)
            .join(Asset, Asset.id == AssetContractAsset.asset_id)
            .where(domain_condition)
        )
        return [AssetContract.id.in_(linked_ids)]

    @staticmethod
    def _in_scope(
        contract: AssetContract,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> bool:
        if is_self_only(context, "contract"):
            return context.user.id in (contract.owner_id, contract.created_by_id)
        if allowed is None:
            return True
        return contract.dept_id is not None and contract.dept_id in allowed

    def _view_scope(
        self, contract: AssetContract, context: AuthContext, allowed: set[int] | None
    ) -> bool:
        return self._in_scope(contract, context, allowed)

    def _assert_view(
        self, contract: AssetContract, context: AuthContext, allowed: set[int] | None
    ) -> None:
        if not self._view_scope(contract, context, allowed):
            raise PermissionDenied("无权查看该合同")
        if not self._contract_in_domain(contract, context):
            raise PermissionDenied("无权查看该合同")

    def _assert_manage(
        self, contract: AssetContract, context: AuthContext, allowed: set[int] | None
    ) -> None:
        if contract.status == ContractStatus.TERMINATED:
            raise BizError("合同已终止，不能继续操作")
        if not self._in_scope(contract, context, allowed):
            raise PermissionDenied("无权操作该合同")
        if not self._contract_in_domain(contract, context):
            raise PermissionDenied("无权操作该合同")

    def _snapshot(self, item: AssetContract) -> dict[str, object]:
        return {
            "contract_no": item.contract_no,
            "name": item.name,
            "contract_type": item.contract_type,
            "status": item.status,
            "supplier": item.supplier,
            "amount": str(item.amount),
            "sign_date": item.sign_date.isoformat() if item.sign_date else None,
            "start_date": item.start_date.isoformat(),
            "end_date": item.end_date.isoformat(),
            "dept_id": item.dept_id,
            "owner_id": item.owner_id,
            "remark": item.remark,
        }

    def _contract_out(
        self,
        item: AssetContract,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> ContractOut:
        today = now_cst().date()
        effective = contract_effective_status(item.status, item.end_date, today)
        days = (item.end_date - today).days
        can_manage = (
            item.status != ContractStatus.TERMINATED
            and self._in_scope(item, context, allowed)
            and self._contract_in_domain(item, context)
            and context.has_permission("asset:contract:edit")
        )
        assets: list[ContractAssetOut] = []
        for link in item.links:
            asset = link.asset
            if asset is None or not self._link_in_domain(asset, context):
                continue
            if is_self_only(context, "contract"):
                if context.user.id not in (asset.custodian_id, asset.created_by_id):
                    continue
            elif allowed is not None and asset.dept_id not in allowed:
                continue
            assets.append(
                ContractAssetOut(
                    id=asset.id,
                    asset_no=asset.asset_no,
                    name=asset.name,
                    category_name=asset.category.name if asset.category else None,
                    model_name=asset.model.name if asset.model else None,
                    serial_no=asset.serial_no,
                    location=asset.location,
                    dept_name=asset.dept.name if asset.dept else None,
                    custodian_name=(
                        _user_name(asset.custodian) if asset.custodian else None
                    ),
                    status=asset.status,
                    status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
                    linked_at=link.linked_at,
                    linked_by_name=link.linked_by_name,
                )
            )
        return ContractOut(
            id=item.id,
            contract_no=item.contract_no,
            name=item.name,
            contract_type=item.contract_type,
            contract_type_label=CONTRACT_TYPE_LABELS.get(
                item.contract_type, item.contract_type
            ),
            contract_type_tag_type=CONTRACT_TYPE_TAG_TYPES.get(
                item.contract_type, "info"
            ),
            status=effective,
            status_label=CONTRACT_STATUS_LABELS.get(effective, effective),
            status_tag_type=CONTRACT_STATUS_TAG_TYPES.get(effective, "info"),
            supplier=item.supplier,
            amount=item.amount,
            sign_date=item.sign_date,
            start_date=item.start_date,
            end_date=item.end_date,
            days_to_expiry=days,
            dept_id=item.dept_id,
            dept_name=item.dept.name if item.dept else None,
            owner_id=item.owner_id,
            owner_name=_user_name(item.owner) if item.owner else None,
            remark=item.remark,
            terminated_at=item.terminated_at,
            terminate_reason=item.terminate_reason,
            created_by_name=item.created_by_name,
            assets=assets,
            asset_count=len(assets),
            can_edit=can_manage,
            can_terminate=can_manage
            and context.has_permission("asset:contract:terminate"),
            can_renew=can_manage,
            can_link_asset=can_manage,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    async def _validate(
        self,
        session: AsyncSession,
        payload: ContractCreate | ContractUpdate,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> None:
        if payload.end_date < payload.start_date:
            raise BizError("合同结束日期不能早于开始日期")
        if payload.sign_date is not None and payload.sign_date > payload.end_date:
            raise BizError("合同签订日期不能晚于结束日期")
        if payload.dept_id is None:
            if allowed is not None:
                raise BizError("请选择合同所属部门")
        else:
            dept = await session.get(Dept, payload.dept_id)
            if dept is None or dept.status != 1:
                raise BizError("合同所属部门不存在或已停用")
            if allowed is not None and payload.dept_id not in allowed:
                raise PermissionDenied("无权在该部门下维护合同")
        if is_self_only(context, "contract") and payload.owner_id not in (
            None,
            context.user.id,
        ):
            raise PermissionDenied("仅本人范围只能指定本人为合同负责人")
        if payload.owner_id is not None:
            owner = await session.get(User, payload.owner_id)
            if owner is None or owner.status != 1:
                raise BizError("合同负责人不存在或已停用")

    async def _assets_for_link(
        self, asset_ids: list[int], context: AuthContext
    ) -> list[Asset]:
        unique_ids = list(dict.fromkeys(asset_ids))
        if not unique_ids:
            return []
        conditions = await asset_scope_conditions(
            self.session, context, resource="contract"
        )
        rows = (
            (
                await self.session.execute(
                    select(Asset).where(*conditions, Asset.id.in_(unique_ids))
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != len(unique_ids):
            raise BizError("部分资产不存在或不在数据范围内")
        return list(rows)

    async def _add_links(
        self,
        item: AssetContract,
        assets: list[Asset],
        context: AuthContext,
    ) -> int:
        existing = {link.asset_id for link in item.links}
        added = 0
        now = now_cst()
        for asset in assets:
            if asset.id in existing:
                continue
            self.session.add(
                AssetContractAsset(
                    contract_id=item.id,
                    asset_id=asset.id,
                    linked_at=now,
                    linked_by_id=context.user.id,
                    linked_by_name=_user_name(context.user),
                )
            )
            added += 1
        return added

    async def option_assets(
        self,
        context: AuthContext,
        *,
        keyword: str | None = None,
        contract_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ContractAssetOptionPage:
        if contract_id is not None:
            contract = await self._get_contract(contract_id)
            allowed = await self._allowed_depts(context)
            self._assert_view(contract, context, allowed)
        conditions = await asset_scope_conditions(
            self.session, context, resource="contract"
        )
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Asset.asset_no.like(like),
                    Asset.name.like(like),
                    Asset.serial_no.like(like),
                )
            )
        total = int(
            await self.session.scalar(
                select(func.count(Asset.id)).where(*conditions)
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
        linked_ids: set[int] = set()
        if contract_id:
            linked_ids = set(
                (
                    await self.session.execute(
                        select(AssetContractAsset.asset_id).where(
                            AssetContractAsset.contract_id == contract_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        items = [
            ContractAssetOption(
                id=asset.id,
                asset_no=asset.asset_no,
                name=asset.name,
                category_name=asset.category.name if asset.category else None,
                model_name=asset.model.name if asset.model else None,
                serial_no=asset.serial_no,
                location=asset.location,
                dept_name=asset.dept.name if asset.dept else None,
                custodian_name=(
                    _user_name(asset.custodian) if asset.custodian else None
                ),
                status=asset.status,
                status_label=ASSET_STATUS_LABELS.get(asset.status, asset.status),
                linked=asset.id in linked_ids,
            )
            for asset in rows
        ]
        return ContractAssetOptionPage(
            items=items, total=total, page=page, page_size=page_size
        )

    async def option_departments(self, context: AuthContext) -> list[dict[str, object]]:
        allowed = await self._target_depts(context)
        conditions: list = [Dept.status == 1]
        if allowed is not None:
            conditions.append(Dept.id.in_(allowed) if allowed else false())
        rows = (
            (
                await self.session.execute(
                    select(Dept)
                    .where(*conditions)
                    .order_by(Dept.path, Dept.sort, Dept.id)
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

    async def option_owners(
        self, context: AuthContext, keyword: str | None
    ) -> list[ContractOwnerOption]:
        conditions: list = [User.status == 1]
        if is_self_only(context, "contract"):
            conditions.append(User.id == context.user.id)
        else:
            allowed = await self._allowed_depts(context)
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
        rows = (
            (
                await self.session.execute(
                    select(User)
                    .where(*conditions)
                    .order_by(User.id)
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [
            ContractOwnerOption(
                id=user.id,
                name=_user_name(user),
                username=user.username,
                dept_id=user.dept_id,
                dept_name=user.dept.name if user.dept else None,
            )
            for user in rows
        ]

    async def list_contracts(
        self,
        context: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        contract_type: str | None = None,
        status: str | None = None,
        dept_id: int | None = None,
    ) -> ContractPageOut:
        allowed = await self._allowed_depts(context)
        conditions = self._scope_conditions(context, allowed)
        conditions.extend(self._domain_conditions(context))
        today = now_cst().date()
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetContract.contract_no.like(like),
                    AssetContract.name.like(like),
                    AssetContract.supplier.like(like),
                )
            )
        if contract_type:
            conditions.append(AssetContract.contract_type == contract_type)
        if dept_id:
            conditions.append(AssetContract.dept_id == dept_id)
        if status == ContractStatus.ACTIVE:
            conditions.extend(
                [
                    AssetContract.status == ContractStatus.ACTIVE,
                    AssetContract.end_date
                    > today + timedelta(days=CONTRACT_EXPIRING_DAYS),
                ]
            )
        elif status == ContractStatus.EXPIRING:
            conditions.extend(
                [
                    AssetContract.status == ContractStatus.ACTIVE,
                    AssetContract.end_date >= today,
                    AssetContract.end_date
                    <= today + timedelta(days=CONTRACT_EXPIRING_DAYS),
                ]
            )
        elif status == ContractStatus.EXPIRED:
            conditions.extend(
                [
                    AssetContract.status == ContractStatus.ACTIVE,
                    AssetContract.end_date < today,
                ]
            )
        elif status == ContractStatus.TERMINATED:
            conditions.append(AssetContract.status == ContractStatus.TERMINATED)
        total = int(
            await self.session.scalar(
                select(func.count(AssetContract.id)).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await self.session.execute(
                    select(AssetContract)
                    .where(*conditions)
                    .order_by(AssetContract.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return ContractPageOut(
            items=[self._contract_out(item, context, allowed) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _scope_conditions(
        context: AuthContext, allowed: set[int] | None
    ) -> list:
        if is_self_only(context, "contract"):
            return [
                or_(
                    AssetContract.owner_id == context.user.id,
                    AssetContract.created_by_id == context.user.id,
                )
            ]
        if allowed is None:
            return []
        if not allowed:
            return [false()]
        return [AssetContract.dept_id.in_(allowed)]

    async def get_contract(
        self, contract_id: int, context: AuthContext
    ) -> ContractOut:
        allowed = await self._allowed_depts(context)
        item = await self._get_contract(contract_id)
        self._assert_view(item, context, allowed)
        return self._contract_out(item, context, allowed)

    async def create_contract(
        self, payload: ContractCreate, context: AuthContext
    ) -> ContractOut:
        allowed = await self._target_depts(context)
        await self._validate(self.session, payload, context, allowed)
        assets = await self._assets_for_link(payload.asset_ids, context)
        if context.allowed_domains("contract") is not None and not assets:
            raise BizError("受限资产域角色创建合同时必须关联至少一项授权域资产")
        item = AssetContract(
            contract_no=await self._next_no(),
            name=payload.name,
            contract_type=payload.contract_type,
            status=ContractStatus.ACTIVE,
            supplier=payload.supplier,
            amount=payload.amount,
            sign_date=payload.sign_date,
            start_date=payload.start_date,
            end_date=payload.end_date,
            dept_id=payload.dept_id,
            owner_id=payload.owner_id,
            remark=payload.remark,
            created_by_id=context.user.id,
            created_by_name=_user_name(context.user),
            links=[],
        )
        self.session.add(item)
        await self.session.flush()
        await self._add_links(item, assets, context)
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.create",
            module="合同管理",
            summary=f"新建合同：{item.contract_no} {item.name}",
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            after=self._snapshot(item),
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def update_contract(
        self, contract_id: int, payload: ContractUpdate, context: AuthContext
    ) -> ContractOut:
        allowed = await self._target_depts(context)
        item = await self._get_contract(contract_id, for_update=True)
        self._assert_view(item, context, allowed)
        self._assert_manage(item, context, allowed)
        if payload.version != item.version:
            raise ConflictError(CONTRACT_CONFLICT_MESSAGE, code=40911)
        await self._validate(self.session, payload, context, allowed)
        before = self._snapshot(item)
        item.name = payload.name
        item.contract_type = payload.contract_type
        item.supplier = payload.supplier
        item.amount = payload.amount
        item.sign_date = payload.sign_date
        item.start_date = payload.start_date
        item.end_date = payload.end_date
        item.dept_id = payload.dept_id
        item.owner_id = payload.owner_id
        item.remark = payload.remark
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.update",
            module="合同管理",
            summary=f"更新合同：{item.contract_no} {item.name}",
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            before=before,
            after=self._snapshot(item),
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def terminate_contract(
        self,
        contract_id: int,
        payload: ContractTerminatePayload,
        context: AuthContext,
    ) -> ContractOut:
        allowed = await self._allowed_depts(context)
        item = await self._get_contract(contract_id, for_update=True)
        self._assert_view(item, context, allowed)
        self._assert_manage(item, context, allowed)
        if payload.version != item.version:
            raise ConflictError(CONTRACT_CONFLICT_MESSAGE, code=40911)
        before = self._snapshot(item)
        item.status = ContractStatus.TERMINATED
        item.terminated_at = now_cst()
        item.terminate_reason = payload.reason
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.terminate",
            module="合同管理",
            summary=f"终止合同：{item.contract_no}，原因：{payload.reason}",
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            before=before,
            after=self._snapshot(item),
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def renew_contract(
        self,
        contract_id: int,
        payload: ContractRenewPayload,
        context: AuthContext,
    ) -> ContractOut:
        allowed = await self._allowed_depts(context)
        item = await self._get_contract(contract_id, for_update=True)
        self._assert_view(item, context, allowed)
        self._assert_manage(item, context, allowed)
        if payload.version != item.version:
            raise ConflictError(CONTRACT_CONFLICT_MESSAGE, code=40911)
        today = now_cst().date()
        if payload.end_date <= item.end_date:
            raise BizError("续签后的结束日期必须晚于原结束日期")
        if payload.end_date < today:
            raise BizError("续签后的结束日期不能早于今天")
        before = self._snapshot(item)
        old_end = item.end_date
        item.end_date = payload.end_date
        if payload.amount is not None:
            item.amount = payload.amount
        if payload.remark is not None:
            item.remark = payload.remark
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.renew",
            module="合同管理",
            summary=(
                f"续签合同：{item.contract_no}，"
                f"{old_end.isoformat()} → {item.end_date.isoformat()}"
            ),
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            before=before,
            after=self._snapshot(item),
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def link_assets(
        self,
        contract_id: int,
        payload: ContractLinkPayload,
        context: AuthContext,
    ) -> ContractOut:
        allowed = await self._allowed_depts(context)
        item = await self._get_contract(contract_id, for_update=True)
        self._assert_view(item, context, allowed)
        self._assert_manage(item, context, allowed)
        assets = await self._assets_for_link(payload.asset_ids, context)
        added = await self._add_links(item, assets, context)
        if added == 0:
            return self._contract_out(item, context, allowed)
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.link_assets",
            module="合同管理",
            summary=f"合同 {item.contract_no} 关联 {added} 项资产",
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            after={"asset_ids": [asset.id for asset in assets]},
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def unlink_asset(
        self, contract_id: int, asset_id: int, context: AuthContext
    ) -> ContractOut:
        allowed = await self._allowed_depts(context)
        item = await self._get_contract(contract_id, for_update=True)
        self._assert_view(item, context, allowed)
        self._assert_manage(item, context, allowed)
        await self._assets_for_link([asset_id], context)
        link = next((row for row in item.links if row.asset_id == asset_id), None)
        if link is None:
            raise NotFoundError("合同未关联该资产")
        item.links.remove(link)
        await self.session.flush()
        await self.audit.record(
            action="asset.contract.unlink_asset",
            module="合同管理",
            summary=f"合同 {item.contract_no} 解除资产关联（ID {asset_id}）",
            actor=context.user,
            resource_type="asset_contract",
            resource_id=item.id,
            before={"asset_id": asset_id},
        )
        await commit_or_conflict(
            self.session, message=CONTRACT_CONFLICT_MESSAGE, code=40911
        )
        item = await self._get_contract(item.id, populate_existing=True)
        return self._contract_out(item, context, allowed)

    async def summary(self, context: AuthContext) -> ContractSummaryOut:
        allowed = await self._allowed_depts(context)
        conditions = self._scope_conditions(context, allowed)
        conditions.extend(self._domain_conditions(context))
        today = now_cst().date()
        expiring_limit = today + timedelta(days=CONTRACT_EXPIRING_DAYS)

        async def count(*extra) -> int:
            return int(
                await self.session.scalar(
                    select(func.count(AssetContract.id)).where(
                        *conditions, *extra
                    )
                )
                or 0
            )

        active_count = await count(
            AssetContract.status == ContractStatus.ACTIVE,
            AssetContract.end_date > expiring_limit,
        )
        expiring_count = await count(
            AssetContract.status == ContractStatus.ACTIVE,
            AssetContract.end_date >= today,
            AssetContract.end_date <= expiring_limit,
        )
        expired_count = await count(
            AssetContract.status == ContractStatus.ACTIVE,
            AssetContract.end_date < today,
        )
        terminated_count = await count(
            AssetContract.status == ContractStatus.TERMINATED
        )
        total_amount = await self.session.scalar(
            select(func.coalesce(func.sum(AssetContract.amount), 0)).where(
                *conditions,
                AssetContract.status == ContractStatus.ACTIVE,
            )
        )
        asset_conditions = await asset_scope_conditions(
            self.session, context, resource="contract"
        )
        linked_asset_count = int(
            await self.session.scalar(
                select(func.count(func.distinct(AssetContractAsset.asset_id)))
                .select_from(AssetContractAsset)
                .join(
                    AssetContract,
                    AssetContract.id == AssetContractAsset.contract_id,
                )
                .join(Asset, Asset.id == AssetContractAsset.asset_id)
                .where(
                    *conditions,
                    *asset_conditions,
                    AssetContract.status == ContractStatus.ACTIVE,
                )
            )
            or 0
        )
        return ContractSummaryOut(
            active_count=active_count,
            expiring_count=expiring_count,
            expired_count=expired_count,
            terminated_count=terminated_count,
            total_amount=Decimal(total_amount or 0),
            linked_asset_count=linked_asset_count,
        )

    async def scan_due_reminders(self) -> int:
        today = now_cst().date()
        today_start = datetime.combine(today, datetime.min.time())
        contracts = (
            (
                await self.session.execute(
                    select(AssetContract)
                    .where(
                        AssetContract.status == ContractStatus.ACTIVE,
                        AssetContract.end_date
                        <= today + timedelta(days=CONTRACT_EXPIRING_DAYS),
                    )
                    .order_by(AssetContract.end_date.asc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
        created = 0
        for item in contracts:
            exists = await self.session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "asset.contract.due_reminder",
                    AuditLog.resource_type == "asset_contract",
                    AuditLog.resource_id == str(item.id),
                    AuditLog.created_at >= today_start,
                )
            )
            if exists:
                continue
            days = (item.end_date - today).days
            if days < 0:
                summary = (
                    f"合同到期提醒：{item.contract_no} {item.name} 已到期 "
                    f"{-days} 天，请尽快续签或终止"
                )
            else:
                summary = (
                    f"合同到期提醒：{item.contract_no} {item.name} 将于 "
                    f"{item.end_date.isoformat()} 到期（剩余 {days} 天）"
                )
            await self.audit.record(
                action="asset.contract.due_reminder",
                module="合同管理",
                summary=summary,
                actor_id=None,
                actor_name="系统计划任务",
                resource_type="asset_contract",
                resource_id=item.id,
                after={
                    "contract_no": item.contract_no,
                    "end_date": item.end_date.isoformat(),
                    "days_to_expiry": days,
                },
            )
            created += 1
        if created:
            await self.session.commit()
        return created

