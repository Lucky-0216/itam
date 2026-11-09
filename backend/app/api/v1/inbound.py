from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_perm, require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.inbound import (
    InboundCancelPayload,
    InboundConfirmPayload,
    InboundCreate,
    InboundReversePayload,
    InboundUpdate,
)
from app.services.inbound_service import InboundService
from app.services.permission_service import AuthContext
from app.services.stock_service import StockService

router = APIRouter(tags=["资产入库与库存"])


@router.get("/inbounds/options/departments", summary="入库单可选部门")
async def inbound_departments(
    context: AuthContext = Depends(require_perm("asset:inbound:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).option_departments(context)
    return ok(result)


@router.get("/inbounds/options/categories", summary="入库单可选分类")
async def inbound_categories(
    context: AuthContext = Depends(require_perm("asset:inbound:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).option_categories(context)
    return ok(result)


@router.get("/inbounds/options/models", summary="入库单可选型号")
async def inbound_models(
    category_id: int | None = Query(None, gt=0),
    context: AuthContext = Depends(require_perm("asset:inbound:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).option_models(context, category_id)
    return ok(result)


@router.get("/inbounds/options/next-codes", summary="预览基准编码的下一批资产编码")
async def inbound_next_codes(
    base_no: str = Query(..., min_length=1, max_length=40),
    quantity: int = Query(1, ge=1, le=200),
    context: AuthContext = Depends(require_perm("asset:inbound:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).preview_codes(base_no, quantity)
    return ok(result)


@router.get("/inbounds", summary="入库单列表")
async def list_inbounds(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    status: str | None = Query(None, max_length=24),
    inbound_type: str | None = Query(None, max_length=20),
    context: AuthContext = Depends(require_perm("asset:inbound:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).list_inbounds(
        context,
        keyword=keyword,
        status=status,
        inbound_type=inbound_type,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/inbounds", summary="创建入库单")
async def create_inbound(
    payload: InboundCreate,
    context: AuthContext = Depends(require_perm("asset:inbound:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).create_inbound(payload, context)
    return ok(result.model_dump(mode="json"), message="入库单已创建，确认后生成资产台账")


@router.get("/inbounds/{inbound_id}", summary="入库单详情")
async def inbound_detail(
    inbound_id: int,
    context: AuthContext = Depends(require_perm("asset:inbound:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).get_inbound(inbound_id, context)
    return ok(result.model_dump(mode="json"))


@router.put("/inbounds/{inbound_id}", summary="修改待确认入库单")
async def update_inbound(
    inbound_id: int,
    payload: InboundUpdate,
    context: AuthContext = Depends(
        require_any_perm("asset:inbound:update", "asset:inbound:create")
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).update_inbound(
        inbound_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="入库单已更新")


@router.post("/inbounds/{inbound_id}/reverse-assets", summary="冲销已入库资产")
async def reverse_inbound_assets(
    inbound_id: int,
    payload: InboundReversePayload,
    context: AuthContext = Depends(require_perm("asset:inbound:confirm")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).reverse_assets(
        inbound_id, payload, context
    )
    return ok(
        result.model_dump(mode="json"),
        message="所选资产已冲销作废，编码已释放",
    )


@router.post("/inbounds/{inbound_id}/confirm", summary="确认入库")
async def confirm_inbound(
    inbound_id: int,
    payload: InboundConfirmPayload,
    context: AuthContext = Depends(require_perm("asset:inbound:confirm")),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).confirm_inbound(
        inbound_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="入库完成，资产已生成并进入在库状态")


@router.post("/inbounds/{inbound_id}/cancel", summary="取消入库单")
async def cancel_inbound(
    inbound_id: int,
    payload: InboundCancelPayload,
    context: AuthContext = Depends(
        require_any_perm(
            "asset:inbound:cancel",
            "asset:inbound:delete",
            "asset:inbound:create",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await InboundService(session).cancel_inbound(
        inbound_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="入库单已取消")


@router.get("/stock/overview", summary="库存总览与低库存预警")
async def stock_overview(
    location: str | None = Query(None, max_length=120),
    context: AuthContext = Depends(require_perm("asset:stock:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await StockService(session).overview(context, location=location)
    return ok(result.model_dump(mode="json"))


@router.get("/stock/items", summary="在库资产明细")
async def stock_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    category_id: int | None = Query(None, gt=0),
    include_child: bool = Query(True),
    location: str | None = Query(None, max_length=120),
    context: AuthContext = Depends(require_perm("asset:stock:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await StockService(session).list_items(
        context,
        keyword=keyword,
        category_id=category_id,
        include_child=include_child,
        location=location,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/stock/categories", summary="库存筛选分类")
async def stock_categories(
    context: AuthContext = Depends(require_perm("asset:stock:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await StockService(session).categories(context)
    return ok(result)
