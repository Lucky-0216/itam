from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import delete, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_ops import (
    INBOUND_NO_PREFIX,
    INBOUND_STATUS_LABELS,
    INBOUND_STATUS_TAG_TYPES,
    INBOUND_TYPE_LABELS,
    InboundStatus,
)
from app.core.assets import ASSET_STATUS_LABELS, AssetStatus
from app.core.config import settings
from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.models import (
    Asset,
    AssetCategory,
    AssetCodeSequence,
    AssetHistory,
    AssetInbound,
    AssetInboundCode,
    AssetInboundItem,
    AssetModel,
    Dept,
    User,
)
from app.models.base import now_cst
from app.repositories.asset_repo import AssetRepository
from app.schemas.inbound import (
    AssetInboundOut,
    AssetInboundPageOut,
    InboundAssetOut,
    InboundCancelPayload,
    InboundConfirmPayload,
    InboundCreate,
    InboundItemOut,
    InboundReversePayload,
    InboundUpdate,
)
from app.services.asset_snapshot import asset_snapshot
from app.services.asset_void import (
    apply_void,
    ensure_no_active_business,
)
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import (
    category_domain_allowed,
    is_self_only,
    scoped_dept_ids,
)
from app.services.txn import commit_or_conflict

INBOUND_CONFLICT_MESSAGE = "入库单状态已变更，请刷新后重试"
CODE_CONFLICT_MESSAGE = "资产编码已被占用，请修改后重新提交"
_BASE_ASSET_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


def _user_name(user: User) -> str:
    return user.real_name or user.username


class InboundService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def _next_no(self) -> str:
        head = f"{INBOUND_NO_PREFIX}-{now_cst():%Y%m}-"
        max_no = await self.session.scalar(
            select(func.max(AssetInbound.inbound_no)).where(
                AssetInbound.inbound_no.like(f"{head}%")
            )
        )
        sequence = 1
        if max_no:
            suffix = max_no[len(head) :]
            if suffix.isdigit():
                sequence = int(suffix) + 1
        return f"{head}{sequence:04d}"

    async def _asset_numbers(self, count: int) -> list[str]:
        now = now_cst()
        pattern = settings.ASSET_NO_PATTERN or "{prefix}-{year}{month}-{seq:04d}"
        seq_start = pattern.find("{seq")
        seq_end = pattern.find("}", seq_start)
        if seq_start < 0 or seq_end < 0:
            raise BizError("资产编号规则配置不正确")
        values = {
            "prefix": settings.ASSET_NO_PREFIX,
            "year": now.year,
            "month": f"{now.month:02d}",
        }
        head = pattern[:seq_start].format(**values)
        tail = pattern[seq_end + 1 :]
        max_no = await AssetRepository(self.session).max_asset_no(head)
        sequence = 1
        if max_no:
            middle = max_no[len(head) :]
            if tail and middle.endswith(tail):
                middle = middle[: -len(tail)]
            match = re.match(r"(\d+)", middle)
            if match:
                sequence = int(match.group(1)) + 1
        return [
            pattern.format(**values, seq=sequence + index)
            for index in range(count)
        ]

    async def _max_base_seq(self, base_no: str) -> int:
        pattern = re.compile(rf"^{re.escape(base_no)}-(\d+)$", re.IGNORECASE)
        prefix = f"{base_no.casefold()}-%"
        asset_stmt = select(Asset.asset_no).where(
            func.lower(Asset.asset_no).like(prefix)
        )
        code_stmt = select(AssetInboundCode.asset_no).where(
            func.lower(AssetInboundCode.asset_no).like(prefix)
        )
        sequences: list[int] = []
        for stmt in (asset_stmt, code_stmt):
            values = (await self.session.execute(stmt)).scalars().all()
            for value in values:
                match = pattern.match(value or "")
                if match:
                    sequences.append(int(match.group(1)))
        last_seq = await self.session.scalar(
            select(AssetCodeSequence.last_seq).where(
                AssetCodeSequence.base_key == base_no.casefold()
            )
        )
        if last_seq is not None:
            sequences.append(last_seq)
        return max(sequences, default=0)

    async def _lock_base_sequence(self, base_no: str) -> AssetCodeSequence:
        base_key = base_no.casefold()
        exists = await self.session.scalar(
            select(AssetCodeSequence.base_key).where(
                AssetCodeSequence.base_key == base_key
            )
        )
        if exists is None:
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        AssetCodeSequence(base_key=base_key, last_seq=0)
                    )
                    await self.session.flush()
            except IntegrityError:
                pass
        return (
            await self.session.execute(
                select(AssetCodeSequence)
                .where(AssetCodeSequence.base_key == base_key)
                .with_for_update()
            )
        ).scalar_one()

    async def _auto_codes(
        self, base_no: str, quantity: int, *, allocate: bool = False
    ) -> list[str]:
        max_seq = await self._max_base_seq(base_no)
        if allocate:
            sequence = await self._lock_base_sequence(base_no)
            max_seq = max(max_seq, sequence.last_seq)
            sequence.last_seq = max_seq + quantity
            await self.session.flush()
            start = max_seq + 1
        else:
            start = max_seq + 1
        codes = [f"{base_no}-{start + index}" for index in range(quantity)]
        if any(len(code) > 50 for code in codes):
            raise BizError("自动生成的资产编码超过 50 个字符，请缩短基准编码")
        return codes

    async def preview_codes(self, base_no: str, quantity: int) -> dict[str, object]:
        base_no = base_no.strip()
        if not _BASE_ASSET_NO_RE.fullmatch(base_no):
            raise BizError(
                "基准编码需以字母或数字开头，仅支持字母、数字、点、下划线、中划线，长度 1-40 位"
            )
        return {
            "base_asset_no": base_no,
            "codes": await self._auto_codes(base_no, quantity),
        }

    async def _code_lists(
        self, inbound_ids: list[int]
    ) -> dict[int, dict[int, list[str]]]:
        if not inbound_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(AssetInboundCode)
                    .where(AssetInboundCode.inbound_id.in_(inbound_ids))
                    .order_by(AssetInboundCode.id)
                )
            )
            .scalars()
            .all()
        )
        result: dict[int, dict[int, list[str]]] = {}
        for row in rows:
            result.setdefault(row.inbound_id, {}).setdefault(row.item_id, []).append(
                row.asset_no
            )
        return result

    async def _assert_codes_available(
        self,
        line_index: int,
        codes: list[str],
        *,
        exclude_inbound_id: int | None = None,
    ) -> None:
        if not codes:
            return
        keys = [code.casefold() for code in codes]
        asset_nos = set(
            (
                await self.session.execute(
                    select(Asset.asset_no).where(
                        func.lower(Asset.asset_no).in_(keys),
                        Asset.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        reserved_stmt = (
            select(AssetInboundCode.asset_no)
            .join(
                AssetInbound,
                AssetInbound.id == AssetInboundCode.inbound_id,
            )
            .where(
                func.lower(AssetInboundCode.asset_no).in_(keys),
                AssetInbound.status == InboundStatus.PENDING,
            )
        )
        if exclude_inbound_id is not None:
            reserved_stmt = reserved_stmt.where(
                AssetInboundCode.inbound_id != exclude_inbound_id
            )
        reserved = set(
            (await self.session.execute(reserved_stmt)).scalars().all()
        )
        existing = {value.casefold() for value in asset_nos | reserved}
        for code in codes:
            if code.casefold() in existing:
                raise ConflictError(
                    f"第 {line_index} 行最终编码「{code}」已存在，请修改后重新提交",
                    code=40902,
                )

    async def _conflicting_manual_code(
        self, explicit_codes: list[list[str] | None]
    ) -> str | None:
        codes = [code for group in explicit_codes if group for code in group]
        if not codes:
            return None
        keys = [code.casefold() for code in codes]
        asset_nos = set(
            (
                await self.session.execute(
                    select(Asset.asset_no).where(
                        func.lower(Asset.asset_no).in_(keys),
                        Asset.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        reserved = set(
            (
                await self.session.execute(
                    select(AssetInboundCode.asset_no)
                    .join(
                        AssetInbound,
                        AssetInbound.id == AssetInboundCode.inbound_id,
                    )
                    .where(
                        func.lower(AssetInboundCode.asset_no).in_(keys),
                        AssetInbound.status == InboundStatus.PENDING,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        existing = {value.casefold() for value in asset_nos | reserved}
        return next((code for code in codes if code.casefold() in existing), None)

    async def _allocate_codes(
        self,
        inbound: AssetInbound,
        lines: list[AssetInboundItem],
        explicit_codes: list[list[str] | None],
    ) -> None:
        try:
            async with self.session.begin_nested():
                seen: set[str] = set()
                for line, explicit in zip(lines, explicit_codes):
                    if explicit is not None:
                        codes = explicit
                    elif line.base_asset_no:
                        codes = await self._auto_codes(
                            line.base_asset_no,
                            line.quantity,
                            allocate=True,
                        )
                    else:
                        continue
                    for code in codes:
                        key = code.casefold()
                        if key in seen:
                            raise BizError(
                                f"最终编码「{code}」与同一入库单的其他编码重复，请调整基准编码或最终编码"
                            )
                        seen.add(key)
                    self.session.add_all(
                        [
                            AssetInboundCode(
                                inbound_id=inbound.id,
                                item_id=line.id,
                                asset_no=code,
                            )
                            for code in codes
                        ]
                    )
                    # autoflush 关闭，先落库使后续基准编码续号能看到本行占用
                    await self.session.flush()
        except IntegrityError as exc:
            conflict = await self._conflicting_manual_code(explicit_codes)
            if conflict is not None:
                raise ConflictError(
                    f"最终编码「{conflict}」已被占用，请修改后重新提交",
                    code=40902,
                ) from exc
            raise ConflictError(CODE_CONFLICT_MESSAGE, code=40902) from exc

    async def _allowed_depts(self, context: AuthContext) -> set[int] | None:
        return await scoped_dept_ids(self.session, context, resource="inbound")

    async def _target_depts(self, context: AuthContext) -> set[int] | None:
        if is_self_only(context, "inbound"):
            return {context.user.dept_id} if context.user.dept_id else set()
        return await self._allowed_depts(context)

    def _domain_condition(self, context: AuthContext):
        domains = context.allowed_domains("inbound")
        if domains is None:
            return None
        return AssetInbound.id.in_(
            select(AssetInboundItem.inbound_id)
            .join(AssetCategory, AssetCategory.id == AssetInboundItem.category_id)
            .where(AssetCategory.asset_domain.in_(domains))
        )

    async def _assert_domain_allowed(
        self, item: AssetInbound, context: AuthContext
    ) -> None:
        domains = context.allowed_domains("inbound")
        if domains is None:
            return
        rows = list(
            (
                await self.session.execute(
                    select(AssetCategory.asset_domain)
                    .join(
                        AssetInboundItem,
                        AssetInboundItem.category_id == AssetCategory.id,
                    )
                    .where(AssetInboundItem.inbound_id == item.id)
                )
            )
            .scalars()
            .all()
        )
        if any(domain not in domains for domain in rows):
            raise PermissionDenied("入库单包含无权操作的资产域")

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

    async def option_categories(
        self, context: AuthContext
    ) -> list[dict[str, object]]:
        conditions: list = [AssetCategory.status == 1]
        domains = context.allowed_domains("inbound")
        if domains is not None:
            conditions.append(AssetCategory.asset_domain.in_(domains))
        rows = (
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

    async def option_models(
        self, context: AuthContext, category_id: int | None
    ) -> list[dict[str, object]]:
        conditions: list = [AssetModel.status == 1]
        domains = context.allowed_domains("inbound")
        if category_id is not None:
            category = await self.session.get(AssetCategory, category_id)
            if category is None or not category_domain_allowed(
                category, context, "inbound"
            ):
                raise PermissionDenied("无权使用该资产分类")
            conditions.append(AssetModel.category_id == category_id)
        if domains is not None:
            conditions.append(
                AssetModel.category_id.in_(
                    select(AssetCategory.id).where(
                        AssetCategory.asset_domain.in_(domains)
                    )
                )
            )
        rows = (
            (
                await self.session.execute(
                    select(AssetModel)
                    .where(*conditions)
                    .order_by(AssetModel.name, AssetModel.id)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": model.id,
                "category_id": model.category_id,
                "name": model.name,
                "code": model.code,
                "brand": model.brand,
                "spec": model.spec,
                "unit": model.unit,
            }
            for model in rows
        ]

    @staticmethod
    def _in_scope(dept_id: int | None, allowed: set[int] | None) -> bool:
        return allowed is None or (dept_id is not None and dept_id in allowed)

    def _record_in_scope(
        self,
        item: AssetInbound,
        context: AuthContext,
        allowed: set[int] | None,
    ) -> bool:
        if is_self_only(context, "inbound"):
            return item.created_by_id == context.user.id
        return self._in_scope(item.dept_id, allowed)

    async def _assert_scope(
        self,
        item: AssetInbound,
        context: AuthContext,
        *,
        message: str = "无权操作该入库单",
    ) -> None:
        allowed = await self._allowed_depts(context)
        if not self._record_in_scope(item, context, allowed):
            raise PermissionDenied(message)

    async def _get_inbound(self, inbound_id: int, *, for_update: bool = False) -> AssetInbound:
        stmt = select(AssetInbound).where(AssetInbound.id == inbound_id)
        if for_update:
            stmt = stmt.with_for_update()
        item = (await self.session.execute(stmt)).scalar_one_or_none()
        if item is None:
            raise NotFoundError("入库单不存在")
        return item

    def _item_out(
        self, item: AssetInboundItem, asset_nos: list[str] | None = None
    ) -> InboundItemOut:
        unit_price = float(item.unit_price) if item.unit_price is not None else None
        return InboundItemOut(
            id=item.id,
            category_id=item.category_id,
            category_name=item.category_name,
            model_id=item.model_id,
            model_name=item.model_name,
            name=item.name,
            quantity=item.quantity,
            base_asset_no=item.base_asset_no,
            asset_nos=list(asset_nos or []),
            unit_price=unit_price,
            amount=(unit_price or 0) * item.quantity,
            warranty_end=item.warranty_end,
            remark=item.remark,
        )

    async def _assets_for_inbound(
        self, item: AssetInbound
    ) -> list[InboundAssetOut]:
        if item.status != InboundStatus.COMPLETED:
            return []
        code_maps = await self._code_lists([item.id])
        codes = [
            code
            for line_codes in code_maps.get(item.id, {}).values()
            for code in line_codes
        ]
        if not codes:
            return []
        rows = (
            (
                await self.session.execute(
                    select(Asset).where(
                        func.lower(Asset.asset_no).in_(
                            [code.casefold() for code in codes]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        by_no = {asset.asset_no.casefold(): asset for asset in rows}
        result: list[InboundAssetOut] = []
        for code in codes:
            asset = by_no.get(code.casefold())
            if asset is None:
                continue
            result.append(
                InboundAssetOut(
                    id=asset.id,
                    asset_no=asset.asset_no,
                    name=asset.name,
                    status=asset.status,
                    status_label=ASSET_STATUS_LABELS.get(
                        asset.status, asset.status
                    ),
                    can_reverse=(
                        asset.status == AssetStatus.IN_STOCK
                        and asset.deleted_at is None
                    ),
                )
            )
        return result

    def _inbound_out(
        self,
        item: AssetInbound,
        context: AuthContext,
        allowed: set[int] | None,
        code_map: dict[int, list[str]] | None = None,
        assets: list[InboundAssetOut] | None = None,
    ) -> AssetInboundOut:
        in_scope = self._record_in_scope(item, context, allowed)
        can_confirm = (
            item.status == InboundStatus.PENDING
            and context.has_permission("asset:inbound:confirm")
            and in_scope
        )
        can_cancel = item.status == InboundStatus.PENDING and in_scope and (
            item.created_by_id == context.user.id
            or context.has_permission("asset:inbound:cancel")
            or context.has_permission("asset:inbound:delete")
        )
        can_edit = (
            item.status == InboundStatus.PENDING
            and (
                context.has_permission("asset:inbound:update")
                or context.has_permission("asset:inbound:create")
            )
            and in_scope
        )
        asset_rows = assets or []
        can_reverse = (
            item.status == InboundStatus.COMPLETED
            and context.has_permission("asset:inbound:confirm")
            and in_scope
            and any(asset.can_reverse for asset in asset_rows)
        )
        can_supplement = (
            item.status == InboundStatus.COMPLETED
            and context.has_permission("asset:inbound:create")
            and in_scope
        )
        return AssetInboundOut(
            id=item.id,
            inbound_no=item.inbound_no,
            inbound_type=item.inbound_type,
            inbound_type_label=INBOUND_TYPE_LABELS.get(item.inbound_type, item.inbound_type),
            status=item.status,
            status_label=INBOUND_STATUS_LABELS.get(item.status, item.status),
            status_tag_type=INBOUND_STATUS_TAG_TYPES.get(item.status, "info"),
            source_inbound_id=item.source_inbound_id,
            supplier=item.supplier,
            purchase_date=item.purchase_date,
            location=item.location,
            dept_id=item.dept_id,
            dept_name=item.dept_name,
            total_quantity=item.total_quantity,
            total_amount=float(item.total_amount or 0),
            remark=item.remark,
            created_by_name=item.created_by_name,
            confirmed_by_name=item.confirmed_by_name,
            confirmed_at=item.confirmed_at,
            completion_comment=item.completion_comment,
            cancelled_at=item.cancelled_at,
            cancel_reason=item.cancel_reason,
            can_confirm=can_confirm,
            can_cancel=can_cancel,
            can_edit=can_edit,
            can_reverse=can_reverse,
            can_supplement=can_supplement,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
            items=[
                self._item_out(line, (code_map or {}).get(line.id))
                for line in item.items
            ],
            assets=asset_rows,
        )

    async def list_inbounds(
        self,
        context: AuthContext,
        *,
        keyword: str | None,
        status: str | None,
        inbound_type: str | None,
        page: int,
        page_size: int,
    ) -> AssetInboundPageOut:
        allowed = await self._allowed_depts(context)
        conditions: list = []
        if is_self_only(context, "inbound"):
            conditions.append(AssetInbound.created_by_id == context.user.id)
        elif allowed is not None:
            conditions.append(AssetInbound.dept_id.in_(allowed) if allowed else false())
        domain_condition = self._domain_condition(context)
        if domain_condition is not None:
            conditions.append(domain_condition)
        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AssetInbound.inbound_no.like(like),
                    AssetInbound.supplier.like(like),
                    AssetInbound.created_by_name.like(like),
                )
            )
        if status:
            conditions.append(AssetInbound.status == status)
        if inbound_type:
            conditions.append(AssetInbound.inbound_type == inbound_type)
        total = await self.session.scalar(
            select(func.count()).select_from(AssetInbound).where(*conditions)
        )
        rows = (
            (
                await self.session.execute(
                    select(AssetInbound)
                    .where(*conditions)
                    .order_by(AssetInbound.created_at.desc(), AssetInbound.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        code_maps = await self._code_lists([item.id for item in rows])
        return AssetInboundPageOut(
            items=[
                self._inbound_out(
                    item, context, allowed, code_maps.get(item.id, {})
                )
                for item in rows
            ],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def get_inbound(self, inbound_id: int, context: AuthContext) -> AssetInboundOut:
        item = await self._get_inbound(inbound_id)
        await self._assert_scope(item, context, message="无权查看该入库单")
        allowed = await self._allowed_depts(context)
        await self._assert_domain_allowed(item, context)
        code_maps = await self._code_lists([item.id])
        assets = await self._assets_for_inbound(item)
        return self._inbound_out(
            item, context, allowed, code_maps.get(item.id, {}), assets
        )

    async def _resolve_dept(self, dept_id: int | None) -> Dept | None:
        if dept_id is None:
            return None
        dept = await self.session.get(Dept, dept_id)
        if dept is None:
            raise NotFoundError("所属部门不存在")
        if dept.status != 1:
            raise BizError("所属部门已停用")
        return dept

    async def _resolve_line(
        self, line, index: int
    ) -> tuple[AssetCategory, AssetModel | None]:
        category = await self.session.get(AssetCategory, line.category_id)
        if category is None:
            raise NotFoundError(f"第 {index} 行资产分类不存在")
        if category.status != 1:
            raise BizError(f"第 {index} 行资产分类已停用")
        model = None
        if line.model_id is not None:
            model = await self.session.get(AssetModel, line.model_id)
            if model is None:
                raise NotFoundError(f"第 {index} 行资产型号不存在")
            if model.status != 1:
                raise BizError(f"第 {index} 行资产型号已停用")
            if model.category_id != category.id:
                raise BizError(f"第 {index} 行资产型号与分类不一致")
        return category, model

    async def _prepare_lines(
        self,
        payload: InboundCreate,
        allowed: set[int] | None,
        context: AuthContext,
        *,
        exclude_inbound_id: int | None = None,
    ) -> tuple[
        Dept | None,
        list[AssetInboundItem],
        list[list[str] | None],
        int,
        Decimal,
    ]:
        dept = await self._resolve_dept(payload.dept_id)
        if allowed is not None and (dept is None or dept.id not in allowed):
            raise PermissionDenied("无权在该部门下创建入库单")

        lines: list[AssetInboundItem] = []
        explicit_codes: list[list[str] | None] = []
        total_quantity = 0
        total_amount = Decimal("0")
        for index, current in enumerate(payload.items, start=1):
            category, model = await self._resolve_line(current, index)
            if not category_domain_allowed(category, context, "inbound"):
                raise PermissionDenied(
                    f"第 {index} 行资产分类不在当前资产域授权范围内"
                )
            if current.asset_nos is not None:
                await self._assert_codes_available(
                    index,
                    current.asset_nos,
                    exclude_inbound_id=exclude_inbound_id,
                )
            unit_price = (
                Decimal(str(current.unit_price))
                if current.unit_price is not None
                else None
            )
            total_quantity += current.quantity
            if unit_price is not None:
                total_amount += unit_price * current.quantity
            lines.append(
                AssetInboundItem(
                    category_id=category.id,
                    category_name=category.name,
                    model_id=model.id if model else None,
                    model_name=model.name if model else None,
                    name=current.name,
                    quantity=current.quantity,
                    base_asset_no=current.base_asset_no,
                    unit_price=unit_price,
                    warranty_end=current.warranty_end,
                    remark=current.remark,
                )
            )
            explicit_codes.append(current.asset_nos)
        return dept, lines, explicit_codes, total_quantity, total_amount

    async def create_inbound(
        self, payload: InboundCreate, context: AuthContext
    ) -> AssetInboundOut:
        allowed = await self._target_depts(context)
        dept, lines, explicit_codes, total_quantity, total_amount = (
            await self._prepare_lines(payload, allowed, context)
        )
        source = None
        if payload.source_inbound_id is not None:
            source = await self._get_inbound(payload.source_inbound_id)
            if source.status != InboundStatus.COMPLETED:
                raise BizError("仅已完成的入库单可以创建补录单")
            await self._assert_scope(source, context, message="无权补录该入库单")
            if source.dept_id != (dept.id if dept else None):
                raise BizError("补录单的所属部门需与原入库单一致")

        item = AssetInbound(
            inbound_no=await self._next_no(),
            inbound_type=payload.inbound_type,
            status=InboundStatus.PENDING,
            supplier=payload.supplier,
            purchase_date=payload.purchase_date or now_cst().date(),
            location=payload.location,
            dept_id=dept.id if dept else None,
            dept_name=dept.name if dept else None,
            total_quantity=total_quantity,
            total_amount=total_amount,
            remark=payload.remark,
            source_inbound_id=source.id if source else None,
            created_by_id=context.user.id,
            created_by_name=_user_name(context.user),
            items=lines,
        )
        item.dept = dept
        self.session.add(item)
        await self.session.flush()
        await self._allocate_codes(item, lines, explicit_codes)
        await self.audit.record(
            action="asset.inbound.create",
            module="asset",
            summary=f"创建入库单：{item.inbound_no}（{total_quantity} 件）",
            actor=context.user,
            resource_type="asset_inbound",
            resource_id=item.id,
            after={
                "status": item.status,
                "inbound_type": item.inbound_type,
                "total_quantity": total_quantity,
                "total_amount": float(total_amount),
            },
        )
        await commit_or_conflict(self.session)
        code_maps = await self._code_lists([item.id])
        return self._inbound_out(
            item, context, allowed, code_maps.get(item.id, {})
        )

    async def update_inbound(
        self,
        inbound_id: int,
        payload: InboundUpdate,
        context: AuthContext,
    ) -> AssetInboundOut:
        item = await self._get_inbound(inbound_id, for_update=True)
        await self._assert_scope(item, context)
        allowed = await self._target_depts(context)
        await self._assert_domain_allowed(item, context)
        if item.status != InboundStatus.PENDING:
            raise BizError("仅待确认的入库单可以修改")
        if payload.version != item.version:
            raise ConflictError(INBOUND_CONFLICT_MESSAGE, code=40911)

        before = {
            "status": item.status,
            "supplier": item.supplier,
            "purchase_date": (
                item.purchase_date.isoformat() if item.purchase_date else None
            ),
            "location": item.location,
            "dept_id": item.dept_id,
            "total_quantity": item.total_quantity,
            "total_amount": float(item.total_amount or 0),
            "items": [
                {"name": line.name, "quantity": line.quantity}
                for line in item.items
            ],
        }

        await self.session.execute(
            delete(AssetInboundCode).where(AssetInboundCode.inbound_id == item.id)
        )
        item.items = []
        await self.session.flush()

        dept, lines, explicit_codes, total_quantity, total_amount = (
            await self._prepare_lines(
                payload, allowed, context, exclude_inbound_id=item.id
            )
        )
        item.inbound_type = payload.inbound_type
        item.supplier = payload.supplier
        item.purchase_date = payload.purchase_date or now_cst().date()
        item.location = payload.location
        item.dept_id = dept.id if dept else None
        item.dept_name = dept.name if dept else None
        item.dept = dept
        item.total_quantity = total_quantity
        item.total_amount = total_amount
        item.remark = payload.remark
        item.items = lines
        await self.session.flush()
        await self._allocate_codes(item, lines, explicit_codes)
        await self.audit.record(
            action="asset.inbound.update",
            module="asset",
            summary=f"修改入库单：{item.inbound_no}（{total_quantity} 件）",
            actor=context.user,
            resource_type="asset_inbound",
            resource_id=item.id,
            before=before,
            after={
                "status": item.status,
                "total_quantity": total_quantity,
                "total_amount": float(total_amount),
            },
        )
        await commit_or_conflict(self.session, code=40911)
        code_maps = await self._code_lists([item.id])
        return self._inbound_out(
            item, context, allowed, code_maps.get(item.id, {})
        )

    async def reverse_assets(
        self,
        inbound_id: int,
        payload: InboundReversePayload,
        context: AuthContext,
    ) -> AssetInboundOut:
        item = await self._get_inbound(inbound_id, for_update=True)
        await self._assert_scope(item, context)
        allowed = await self._allowed_depts(context)
        await self._assert_domain_allowed(item, context)
        if item.status != InboundStatus.COMPLETED:
            raise BizError("仅已确认的入库单可以冲销")
        if payload.version != item.version:
            raise ConflictError(INBOUND_CONFLICT_MESSAGE, code=40911)

        keys = [code.casefold() for code in payload.asset_nos]
        owned = set(
            (
                await self.session.execute(
                    select(AssetInboundCode.asset_no).where(
                        AssetInboundCode.inbound_id == item.id,
                        func.lower(AssetInboundCode.asset_no).in_(keys),
                    )
                )
            )
            .scalars()
            .all()
        )
        owned_keys = {code.casefold() for code in owned}
        missing = [
            code for code in payload.asset_nos if code.casefold() not in owned_keys
        ]
        if missing:
            raise BizError(
                f"资产编码「{missing[0]}」不属于入库单 {item.inbound_no}，无法冲销"
            )

        rows = list(
            (
                await self.session.execute(
                    select(Asset)
                    .where(
                        func.lower(Asset.asset_no).in_(keys),
                        Asset.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        by_no = {asset.asset_no.casefold(): asset for asset in rows}
        missing_assets = [
            code for code in payload.asset_nos if code.casefold() not in by_no
        ]
        if missing_assets:
            raise BizError(
                f"资产「{missing_assets[0]}」不存在或已作废，请刷新后重试"
            )
        for code in payload.asset_nos:
            asset = by_no[code.casefold()]
            if asset.status != AssetStatus.IN_STOCK:
                status_label = ASSET_STATUS_LABELS.get(
                    asset.status, asset.status
                )
                raise BizError(
                    f"资产「{asset.asset_no}」当前为「{status_label}」，"
                    "无法直接冲销，请先归还或处理至在库状态"
                )
            await ensure_no_active_business(self.session, asset.id)

        reversed_nos: list[str] = []
        for code in payload.asset_nos:
            asset = by_no[code.casefold()]
            before, after = await apply_void(
                self.session,
                asset,
                reason=payload.reason,
                operator=context.user,
                action="INBOUND_REVERSAL",
                action_label="入库冲销",
                summary=(
                    f"入库单 {item.inbound_no} 冲销："
                    f"{asset.name}（{asset.asset_no}），原因：{payload.reason}"
                ),
            )
            reversed_nos.append(asset.asset_no)
            await self.audit.record(
                action="asset.inbound.reverse",
                module="asset",
                summary=(
                    f"入库冲销：{item.inbound_no} / "
                    f"{asset.name}（{asset.asset_no}）"
                ),
                actor=context.user,
                resource_type="asset",
                resource_id=asset.id,
                before=before,
                after=after,
            )
        await self.audit.record(
            action="asset.inbound.reverse",
            module="asset",
            summary=(
                f"冲销入库单：{item.inbound_no}，"
                f"作废 {len(reversed_nos)} 台/件资产"
            ),
            actor=context.user,
            resource_type="asset_inbound",
            resource_id=item.id,
            after={
                "reason": payload.reason,
                "asset_nos": reversed_nos,
            },
        )
        await commit_or_conflict(self.session, code=40911)
        code_maps = await self._code_lists([item.id])
        assets = await self._assets_for_inbound(item)
        return self._inbound_out(
            item, context, allowed, code_maps.get(item.id, {}), assets
        )

    async def confirm_inbound(
        self,
        inbound_id: int,
        payload: InboundConfirmPayload,
        context: AuthContext,
    ) -> AssetInboundOut:
        item = await self._get_inbound(inbound_id, for_update=True)
        await self._assert_scope(item, context)
        allowed = await self._allowed_depts(context)
        await self._assert_domain_allowed(item, context)
        if item.status != InboundStatus.PENDING:
            raise BizError("当前入库单不在待确认状态")
        if payload.version != item.version:
            raise ConflictError(INBOUND_CONFLICT_MESSAGE, code=40911)

        dept = await self._resolve_dept(item.dept_id)
        resolved: list[tuple[AssetInboundItem, AssetCategory, AssetModel | None]] = []
        for index, line in enumerate(item.items, start=1):
            category, model = await self._resolve_line(line, index)
            resolved.append((line, category, model))

        code_maps = await self._code_lists([item.id])
        item_codes = code_maps.get(item.id, {})
        stored_by_line: list[list[str] | None] = []
        legacy_count = 0
        for line, _, _ in resolved:
            stored = item_codes.get(line.id) or []
            if stored:
                if len(stored) != line.quantity:
                    raise BizError(
                        "入库单资产编码数量与入库数量不一致，请取消后重新创建"
                    )
                stored_by_line.append(stored)
            else:
                stored_by_line.append(None)
                legacy_count += line.quantity

        legacy_numbers = (
            iter(await self._asset_numbers(legacy_count)) if legacy_count else iter(())
        )
        codes_by_line: list[list[str]] = []
        all_codes: list[str] = []
        seen_codes: set[str] = set()
        for (line, _, _), stored in zip(resolved, stored_by_line):
            codes = (
                list(stored)
                if stored is not None
                else [next(legacy_numbers) for _ in range(line.quantity)]
            )
            for code in codes:
                key = code.casefold()
                if key in seen_codes:
                    raise BizError(
                        f"入库单资产编码「{code}」重复，请取消后重新创建"
                    )
                seen_codes.add(key)
            codes_by_line.append(codes)
            all_codes.extend(codes)

        if all_codes:
            existing_codes = set(
                (
                    await self.session.execute(
                        select(Asset.asset_no).where(
                            func.lower(Asset.asset_no).in_(
                                [code.casefold() for code in all_codes]
                            ),
                            Asset.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if existing_codes:
                duplicate = sorted(existing_codes)[0]
                raise ConflictError(
                    f"资产编号「{duplicate}」已存在，请取消入库单并调整编码后重新创建",
                    code=40902,
                )

        created: list[Asset] = []
        try:
            for (line, category, model), codes in zip(resolved, codes_by_line):
                for code in codes:
                    asset = Asset(
                        asset_no=code,
                        name=line.name,
                        category_id=category.id,
                        category=category,
                        model_id=model.id if model else None,
                        model=model,
                        purchase_date=item.purchase_date,
                        supplier=item.supplier,
                        purchase_price=line.unit_price,
                        warranty_end=line.warranty_end,
                        location=item.location,
                        dept_id=dept.id if dept else None,
                        dept=dept,
                        custodian_id=None,
                        custodian=None,
                        status=AssetStatus.PENDING_STOCK,
                        custom_fields=None,
                        remark=line.remark or item.remark,
                        created_by_id=item.created_by_id or context.user.id,
                        created_by_name=item.created_by_name
                        or _user_name(context.user),
                    )
                    self.session.add(asset)
                    await self.session.flush()
                    before = asset_snapshot(asset)
                    asset.status = AssetStatus.IN_STOCK
                    await self.session.flush()
                    after = asset_snapshot(asset)
                    self.session.add(
                        AssetHistory(
                            asset_id=asset.id,
                            action="INBOUND",
                            action_label="验收入库",
                            from_status=AssetStatus.PENDING_STOCK,
                            to_status=AssetStatus.IN_STOCK,
                            before_snapshot=before,
                            after_snapshot=after,
                            operator_id=context.user.id,
                            operator_name=_user_name(context.user),
                            summary=f"入库单 {item.inbound_no} 验收入库",
                        )
                    )
                    created.append(asset)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "资产编码已被占用，请取消入库单并调整编码后重新创建",
                code=40902,
            ) from exc

        item.status = InboundStatus.COMPLETED
        item.confirmed_by_id = context.user.id
        item.confirmed_by_name = _user_name(context.user)
        item.confirmed_at = now_cst()
        item.completion_comment = payload.comment
        await self.session.flush()
        await self.audit.record(
            action="asset.inbound.confirm",
            module="asset",
            summary=f"确认入库：{item.inbound_no}，新增 {len(created)} 台/件资产",
            actor=context.user,
            resource_type="asset_inbound",
            resource_id=item.id,
            before={"status": InboundStatus.PENDING},
            after={
                "status": item.status,
                "asset_count": len(created),
                "asset_nos": [asset.asset_no for asset in created[:20]],
            },
        )
        await commit_or_conflict(self.session, code=40911)
        assets = await self._assets_for_inbound(item)
        return self._inbound_out(
            item, context, allowed, code_maps.get(item.id, {}), assets
        )

    async def cancel_inbound(
        self,
        inbound_id: int,
        payload: InboundCancelPayload,
        context: AuthContext,
    ) -> AssetInboundOut:
        item = await self._get_inbound(inbound_id)
        await self._assert_scope(item, context)
        allowed = await self._allowed_depts(context)
        await self._assert_domain_allowed(item, context)
        if item.status != InboundStatus.PENDING:
            raise BizError("仅待确认的入库单可以取消")
        if (
            item.created_by_id != context.user.id
            and not context.has_permission("asset:inbound:cancel")
            and not context.has_permission("asset:inbound:delete")
        ):
            raise PermissionDenied("无权取消该入库单")
        item.status = InboundStatus.CANCELLED
        item.cancelled_at = now_cst()
        item.cancel_reason = payload.reason
        await self.session.execute(
            delete(AssetInboundCode).where(
                AssetInboundCode.inbound_id == item.id
            )
        )
        await self.audit.record(
            action="asset.inbound.cancel",
            module="asset",
            summary=f"取消入库单：{item.inbound_no}",
            actor=context.user,
            resource_type="asset_inbound",
            resource_id=item.id,
            after={"status": item.status, "reason": payload.reason},
        )
        await commit_or_conflict(self.session, code=40911)
        return self._inbound_out(item, context, allowed, {})
