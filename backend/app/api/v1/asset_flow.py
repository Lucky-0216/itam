from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_perm, require_perm
from app.core.database import get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.schemas.asset_flow import (
    ApprovalConfigUpdate,
    AssetOutboundPayload,
    AssetRequestComment,
    AssetRequestCreate,
    AssetReturnConfirmPayload,
    AssetReturnCreate,
    DirectOutboundPayload,
)
from app.services.asset_flow_service import AssetFlowService
from app.services.permission_service import AuthContext

router = APIRouter(tags=["资产业务"])


@router.get("/asset-requests/available-categories", summary="可领用资产分类")
async def available_categories(
    context: AuthContext = Depends(require_perm("asset:requisition:create")),
    session: AsyncSession = Depends(get_db),
):
    items = await AssetFlowService(session).available_categories(context)
    return ok([item.model_dump(mode="json") for item in items])


@router.get("/asset-requests/category-options", summary="逐级获取可领用分类")
async def category_options(
    parent_id: int | None = Query(None, ge=1, description="上级分类ID，不传表示顶级"),
    context: AuthContext = Depends(require_perm("asset:requisition:create")),
    session: AsyncSession = Depends(get_db),
):
    items = await AssetFlowService(session).category_options(context, parent_id)
    return ok([item.model_dump(mode="json") for item in items])


def _parse_model_ids(raw: str | None) -> set[int] | None:
    if raw is None or not raw.strip():
        return None
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    try:
        model_ids = {int(token) for token in tokens}
    except ValueError as exc:
        raise BizError("型号筛选参数不正确") from exc
    if any(model_id < 0 for model_id in model_ids):
        raise BizError("型号筛选参数不正确")
    return model_ids


@router.get("/asset-requests/available-models", summary="可领用资产型号")
async def available_models(
    category_id: int = Query(..., ge=1),
    include_child: bool = Query(True),
    context: AuthContext = Depends(require_perm("asset:requisition:create")),
    session: AsyncSession = Depends(get_db),
):
    items = await AssetFlowService(session).available_models(
        context,
        category_id=category_id,
        include_child=include_child,
    )
    return ok([item.model_dump(mode="json") for item in items])


@router.get("/asset-requests/available-assets", summary="可领用/借用资产")
async def available_assets(
    category_id: int = Query(..., ge=1),
    include_child: bool = Query(True),
    model_ids: str | None = Query(
        None,
        max_length=500,
        description="逗号分隔的型号ID，0 表示未指定型号",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    context: AuthContext = Depends(require_perm("asset:requisition:create")),
    session: AsyncSession = Depends(get_db),
):
    items, total = await AssetFlowService(session).available_assets(
        context,
        category_id=category_id,
        include_child=include_child,
        model_ids=_parse_model_ids(model_ids),
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/asset-requests/mine", summary="我的业务申请")
async def my_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    request_type: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=24),
    context: AuthContext = Depends(require_perm("asset:requisition:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).list_requests(
        context,
        view="mine",
        keyword=keyword,
        request_type=request_type,
        status=status,
        pending_mine=False,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/asset-requests/review", summary="业务审批列表")
async def review_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    request_type: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=24),
    pending_mine: bool = Query(True, description="仅显示当前用户可处理的事项"),
    context: AuthContext = Depends(
        require_any_perm(
            "asset:request:review",
            "asset:request:approve",
            "asset:outbound:view",
            "asset:return:confirm:view",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).list_requests(
        context,
        view="review",
        keyword=keyword,
        request_type=request_type,
        status=status,
        pending_mine=pending_mine,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/asset-requests/review-summary", summary="业务待办统计")
async def review_summary(
    context: AuthContext = Depends(
        require_any_perm(
            "asset:request:review",
            "asset:requisition:view",
            "asset:request:approve",
            "asset:outbound:view",
            "asset:return:confirm:view",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).review_summary(context)
    return ok(result.model_dump(mode="json"))


@router.get("/asset-requests/scan", summary="扫码查询资产与业务单据")
async def scan_asset(
    code: str = Query(..., min_length=1, max_length=120),
    context: AuthContext = Depends(
        require_any_perm(
            "asset:requisition:view",
            "asset:request:review",
            "asset:request:approve",
            "asset:outbound:view",
            "asset:return:confirm:view",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).scan(code, context)
    return ok(result.model_dump(mode="json"))


@router.post("/asset-requests", summary="发起领用/借用申请")
async def create_request(
    payload: AssetRequestCreate,
    context: AuthContext = Depends(require_perm("asset:requisition:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).create_request(payload, context)
    return ok(result.model_dump(mode="json"), message="申请已提交")


@router.post("/asset-returns", summary="发起资产归还")
async def create_return(
    payload: AssetReturnCreate,
    context: AuthContext = Depends(require_perm("asset:return:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).create_return(payload, context)
    return ok(result.model_dump(mode="json"), message="归还申请已提交")


@router.get("/my-assets", summary="我的资产")
async def my_assets(
    context: AuthContext = Depends(require_perm("asset:mine:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).my_assets(context)
    return ok([item.model_dump(mode="json") for item in result])


@router.get("/asset-requests/approval-config", summary="审批流程配置")
async def approval_config(
    context: AuthContext = Depends(require_perm("asset:request:flow:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).approval_config()
    return ok(result.model_dump(mode="json"))


@router.put("/asset-requests/approval-config", summary="更新审批流程配置")
async def update_approval_config(
    payload: ApprovalConfigUpdate,
    context: AuthContext = Depends(require_perm("asset:request:flow:manage")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).update_approval_config(
        dept_approval_required=payload.dept_approval_required,
        version=payload.version,
        context=context,
    )
    return ok(result.model_dump(mode="json"), message="审批流程配置已更新")


@router.get("/asset-direct-outbound/categories", summary="直接出库可选分类")
async def direct_outbound_categories(
    context: AuthContext = Depends(require_perm("asset:outbound:direct")),
    session: AsyncSession = Depends(get_db),
):
    items = await AssetFlowService(session).direct_category_options(context)
    return ok([item.model_dump(mode="json") for item in items])


@router.get("/asset-direct-outbound/assets", summary="直接出库可选在库资产")
async def direct_outbound_assets(
    keyword: str | None = Query(None, max_length=100),
    category_id: int | None = Query(None, ge=1),
    include_child: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    context: AuthContext = Depends(require_perm("asset:outbound:direct")),
    session: AsyncSession = Depends(get_db),
):
    items, total = await AssetFlowService(session).direct_assets(
        context,
        keyword=keyword,
        category_id=category_id,
        include_child=include_child,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/asset-direct-outbound/users", summary="直接出库目标领用人")
async def direct_outbound_users(
    keyword: str | None = Query(None, max_length=100),
    context: AuthContext = Depends(require_perm("asset:outbound:direct")),
    session: AsyncSession = Depends(get_db),
):
    items = await AssetFlowService(session).direct_user_options(
        context, keyword=keyword
    )
    return ok([item.model_dump(mode="json") for item in items])


@router.post("/asset-direct-outbound", summary="管理员直接出库")
async def direct_outbound(
    payload: DirectOutboundPayload,
    context: AuthContext = Depends(require_perm("asset:outbound:direct")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).direct_outbound(payload, context)
    return ok(
        result.model_dump(mode="json"),
        message=f"已直接出库 {result.count} 台资产给 {result.user_name}",
    )


@router.get("/asset-requests/{request_id}", summary="业务单据详情")
async def request_detail(
    request_id: int,
    context: AuthContext = Depends(
        require_any_perm(
            "asset:requisition:view",
            "asset:mine:view",
            "asset:request:review",
            "asset:request:approve",
            "asset:outbound:view",
            "asset:return:confirm:view",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).get_request(request_id, context)
    return ok(result.model_dump(mode="json"))


@router.get(
    "/asset-requests/{request_id}/outbound-assets",
    summary="待出库可选资产",
)
async def outbound_assets(
    request_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    context: AuthContext = Depends(
        require_any_perm("asset:request:outbound", "asset:outbound:view")
    ),
    session: AsyncSession = Depends(get_db),
):
    items, total = await AssetFlowService(session).outbound_assets(
        request_id,
        context,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/asset-requests/{request_id}/approve", summary="审批通过")
async def approve_request(
    request_id: int,
    payload: AssetRequestComment,
    context: AuthContext = Depends(require_perm("asset:request:approve")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).approve(
        request_id, payload.comment, context
    )
    if result.approval_stage == "ASSET":
        message = "部门审批通过，已转资产管理员审批"
    elif result.flow_id and result.status == "PENDING_APPROVAL":
        message = f"审批通过，流转至「{result.current_step_name or '下一节点'}」"
    else:
        message = "审批通过，等待资产管理员分配出库"
    return ok(result.model_dump(mode="json"), message=message)


@router.post("/asset-requests/{request_id}/reject", summary="驳回申请")
async def reject_request(
    request_id: int,
    payload: AssetRequestComment,
    context: AuthContext = Depends(require_perm("asset:request:approve")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).reject(
        request_id, payload.comment, context
    )
    return ok(result.model_dump(mode="json"), message="申请已驳回")


@router.post("/asset-requests/{request_id}/cancel", summary="撤销申请")
async def cancel_request(
    request_id: int,
    context: AuthContext = Depends(require_perm("asset:requisition:cancel")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).cancel(request_id, context)
    return ok(result.model_dump(mode="json"), message="申请已撤销")


@router.post("/asset-requests/{request_id}/outbound", summary="确认出库")
async def confirm_outbound(
    request_id: int,
    payload: AssetOutboundPayload,
    context: AuthContext = Depends(require_perm("asset:request:outbound")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).confirm_outbound(
        request_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="出库完成，资产状态已同步")


@router.post("/asset-requests/{request_id}/return-confirm", summary="确认归还")
async def confirm_return(
    request_id: int,
    payload: AssetReturnConfirmPayload,
    context: AuthContext = Depends(require_perm("asset:return:confirm")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).confirm_return(
        request_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="归还完成，资产已入库")


@router.get("/assets/{asset_id}/history", summary="资产状态变更历史")
async def asset_history(
    asset_id: int,
    context: AuthContext = Depends(
        require_any_perm("asset:ledger:view", "asset:mine:view")
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetFlowService(session).asset_history(asset_id, context)
    return ok([item.model_dump(mode="json") for item in result])
