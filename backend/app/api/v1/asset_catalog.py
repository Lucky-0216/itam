from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_perm, require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.asset import (
    AssetDomainCreate,
    AssetDomainUpdate,
    CategoryCreate,
    CategoryFieldCreate,
    CategoryFieldUpdate,
    CategoryUpdate,
    ModelCreate,
    ModelUpdate,
)
from app.services.asset_catalog_service import (
    AssetDomainService,
    CategoryService,
    ModelService,
)
from app.services.permission_service import AuthContext

router = APIRouter(tags=["资产分类与型号"])


@router.get("/asset-domains", summary="资产域列表")
async def list_asset_domains(
    context: AuthContext = Depends(
        require_any_perm("asset:category:view", "system:role:view")
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetDomainService(session).list(context)
    return ok([item.model_dump(mode="json") for item in result])


@router.post("/asset-domains", summary="新增资产域")
async def create_asset_domain(
    payload: AssetDomainCreate,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetDomainService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="资产域创建成功")


@router.put("/asset-domains/{domain_id}", summary="编辑资产域")
async def update_asset_domain(
    domain_id: int,
    payload: AssetDomainUpdate,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await AssetDomainService(session).update(domain_id, payload, context)
    return ok(result.model_dump(mode="json"), message="资产域已更新")


@router.delete("/asset-domains/{domain_id}", summary="删除资产域")
async def delete_asset_domain(
    domain_id: int,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    await AssetDomainService(session).delete(domain_id, context)
    return ok(None, message="资产域已删除")


@router.get("/asset-categories/tree", summary="资产分类树")
async def category_tree(
    context: AuthContext = Depends(require_perm("asset:category:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await CategoryService(session).tree(context)
    return ok([item.model_dump(mode="json") for item in result])


@router.post("/asset-categories", summary="新增资产分类")
async def create_category(
    payload: CategoryCreate,
    context: AuthContext = Depends(require_perm("asset:category:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await CategoryService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="分类创建成功")


@router.put("/asset-categories/{category_id}", summary="编辑资产分类")
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await CategoryService(session).update(category_id, payload, context)
    return ok(result.model_dump(mode="json"), message="分类更新成功")


@router.delete("/asset-categories/{category_id}", summary="删除资产分类")
async def delete_category(
    category_id: int,
    context: AuthContext = Depends(require_perm("asset:category:delete")),
    session: AsyncSession = Depends(get_db),
):
    await CategoryService(session).delete(category_id, context)
    return ok(None, message="分类已删除")


@router.post("/asset-categories/{category_id}/fields", summary="新增自定义字段")
async def create_category_field(
    category_id: int,
    payload: CategoryFieldCreate,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await CategoryService(session).create_field(category_id, payload, context)
    return ok(result.model_dump(mode="json"), message="自定义字段已创建")


@router.put(
    "/asset-categories/{category_id}/fields/{field_id}",
    summary="编辑自定义字段",
)
async def update_category_field(
    category_id: int,
    field_id: int,
    payload: CategoryFieldUpdate,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await CategoryService(session).update_field(
        category_id, field_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="自定义字段已更新")


@router.delete(
    "/asset-categories/{category_id}/fields/{field_id}",
    summary="删除自定义字段",
)
async def delete_category_field(
    category_id: int,
    field_id: int,
    context: AuthContext = Depends(require_perm("asset:category:update")),
    session: AsyncSession = Depends(get_db),
):
    await CategoryService(session).delete_field(category_id, field_id, context)
    return ok(None, message="自定义字段已删除")


@router.get("/asset-models", summary="型号列表")
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category_id: int | None = Query(None, ge=1),
    include_child: bool = Query(True),
    keyword: str | None = Query(None, max_length=100),
    status: int | None = Query(None, ge=0, le=1),
    context: AuthContext = Depends(require_perm("asset:category:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await ModelService(session).list(
        context,
        category_id=category_id,
        include_child=include_child,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/asset-models", summary="新增型号")
async def create_model(
    payload: ModelCreate,
    context: AuthContext = Depends(require_perm("asset:model:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await ModelService(session).create(payload, context)
    return ok(result.model_dump(mode="json"), message="型号创建成功")


@router.put("/asset-models/{model_id}", summary="编辑型号")
async def update_model(
    model_id: int,
    payload: ModelUpdate,
    context: AuthContext = Depends(require_perm("asset:model:update")),
    session: AsyncSession = Depends(get_db),
):
    result = await ModelService(session).update(model_id, payload, context)
    return ok(result.model_dump(mode="json"), message="型号更新成功")


@router.delete("/asset-models/{model_id}", summary="删除型号")
async def delete_model(
    model_id: int,
    context: AuthContext = Depends(require_perm("asset:model:delete")),
    session: AsyncSession = Depends(get_db),
):
    await ModelService(session).delete(model_id, context)
    return ok(None, message="型号已删除")
