from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.asset import (
    AssetBatchUpdate,
    AssetBatchVoidPayload,
    AssetCreate,
    AssetStockInPayload,
    AssetUpdate,
    AssetVoidPayload,
)
from app.services.asset_service import AssetService
from app.services.permission_service import AuthContext

router = APIRouter(tags=["资产台账"])


@router.get("/assets/custodian-options", summary="责任人候选项")
async def custodian_options(
    keyword: str | None = Query(None, max_length=100),
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).custodian_options(context, keyword=keyword)
    return ok([item.model_dump(mode="json") for item in result])


@router.get("/assets/dept-options", summary="部门候选项")
async def dept_options(
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).dept_options(context)
    return ok([item.model_dump(mode="json") for item in result])


@router.get("/assets", summary="资产台账列表")
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    category_id: int | None = Query(None, ge=1),
    include_child: bool = Query(True),
    status: str | None = Query(None, max_length=20),
    dept_id: int | None = Query(None, ge=1),
    custodian_id: int | None = Query(None, ge=1),
    warranty_days: int | None = Query(None, ge=1, le=3650),
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).list(
        context,
        keyword=keyword,
        category_id=category_id,
        include_child=include_child,
        status=status,
        dept_id=dept_id,
        custodian_id=custodian_id,
        warranty_days=warranty_days,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/assets/export", summary="导出资产台账")
async def export_assets(
    keyword: str | None = Query(None, max_length=100),
    category_id: int | None = Query(None, ge=1),
    include_child: bool = Query(True),
    status: str | None = Query(None, max_length=20),
    dept_id: int | None = Query(None, ge=1),
    custodian_id: int | None = Query(None, ge=1),
    warranty_days: int | None = Query(None, ge=1, le=3650),
    context: AuthContext = Depends(require_perm("asset:report:export")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).export(
        context,
        keyword=keyword,
        category_id=category_id,
        include_child=include_child,
        status=status,
        dept_id=dept_id,
        custodian_id=custodian_id,
        warranty_days=warranty_days,
    )
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Content-Disposition": (
                "attachment; filename=\"asset_ledger.xlsx\"; "
                f"filename*=UTF-8''{quote(result.filename)}"
            ),
            "Content-Length": str(len(result.content)),
            "X-Export-Rows": str(result.row_count),
            "X-Export-Truncated": "true" if result.truncated else "false",
        },
    )


@router.post("/assets/batch-update", summary="批量编辑资产")
async def batch_update_assets(
    payload: AssetBatchUpdate,
    context: AuthContext = Depends(require_perm("asset:ledger:update")),
    session: AsyncSession = Depends(get_db),
):
    updated = await AssetService(session).batch_update(payload, context)
    return ok({"updated": updated}, message=f"已批量更新 {updated} 项资产")


@router.post("/assets", summary="新增资产")
async def create_asset(
    payload: AssetCreate,
    context: AuthContext = Depends(require_perm("asset:ledger:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="资产已创建")


@router.get("/assets/{asset_id}", summary="资产详情")
async def asset_detail(
    asset_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).detail(asset_id, context)
    return ok(result.model_dump(mode="json"))


@router.put("/assets/{asset_id}", summary="编辑资产")
async def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    context: AuthContext = Depends(require_perm("asset:ledger:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).update(asset_id, payload, context)
    return ok(result.model_dump(mode="json"), message="资产已更新")


@router.post("/assets/batch-void", summary="批量作废资产")
async def batch_void_assets(
    payload: AssetBatchVoidPayload,
    context: AuthContext = Depends(require_perm("asset:ledger:delete")),
    session: AsyncSession = Depends(get_db),
):
    count = await AssetService(session).batch_void(payload, context)
    return ok({"voided": count}, message=f"已作废 {count} 项资产")


@router.post("/assets/{asset_id}/void", summary="作废资产并释放编码")
async def void_asset(
    asset_id: int,
    payload: AssetVoidPayload,
    context: AuthContext = Depends(require_perm("asset:ledger:delete")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).void(asset_id, payload, context)
    return ok(result.model_dump(mode="json"), message="资产已作废，编码已释放")


@router.post("/assets/{asset_id}/stock-in", summary="资产确认入库")
async def stock_in_asset(
    asset_id: int,
    payload: AssetStockInPayload,
    context: AuthContext = Depends(require_perm("asset:inbound:confirm")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).stock_in(asset_id, payload, context)
    return ok(result.model_dump(mode="json"), message="资产已入库")


@router.delete("/assets/{asset_id}", summary="删除资产")
async def delete_asset(
    asset_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:delete")),
    session: AsyncSession = Depends(get_db),
):
    await AssetService(session).delete(asset_id, context)
    return ok(None, message="资产已作废，编码已释放")


@router.get("/assets/{asset_id}/attachments", summary="资产附件列表")
async def list_asset_attachments(
    asset_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).list_attachments(asset_id, context)
    return ok([item.model_dump(mode="json") for item in result])


@router.post("/assets/{asset_id}/attachments", summary="上传资产附件")
async def upload_asset_attachment(
    asset_id: int,
    file: UploadFile = File(...),
    context: AuthContext = Depends(require_perm("asset:ledger:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).upload_attachment(asset_id, file, context)
    return ok(result.model_dump(mode="json"), message="附件已上传")


@router.get(
    "/assets/{asset_id}/attachments/{attachment_id}/download",
    summary="下载资产附件",
)
async def download_asset_attachment(
    asset_id: int,
    attachment_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    path, attachment = await AssetService(session).get_attachment_file(
        asset_id, attachment_id, context
    )
    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.file_name,
    )


@router.delete(
    "/assets/{asset_id}/attachments/{attachment_id}",
    summary="删除资产附件",
)
async def delete_asset_attachment(
    asset_id: int,
    attachment_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:update")),
    session: AsyncSession = Depends(get_db),
):
    await AssetService(session).delete_attachment(asset_id, attachment_id, context)
    return ok(None, message="附件已删除")


@router.get("/assets/{asset_id}/timeline", summary="资产操作时间线")
async def asset_timeline(
    asset_id: int,
    context: AuthContext = Depends(require_perm("asset:ledger:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetService(session).timeline(asset_id, context)
    return ok([item.model_dump(mode="json") for item in result])
