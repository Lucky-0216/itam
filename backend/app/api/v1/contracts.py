from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_perm, require_perm
from app.core.database import get_db
from app.core.response import ok
from app.schemas.contract import (
    ContractCreate,
    ContractLinkPayload,
    ContractRenewPayload,
    ContractTerminatePayload,
    ContractUpdate,
)
from app.services.contract_service import ContractService
from app.services.permission_service import AuthContext

router = APIRouter(tags=["合同管理"])


@router.get("/contracts/options/assets", summary="可关联资产")
async def option_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    contract_id: int | None = Query(None, ge=1),
    context: AuthContext = Depends(
        require_any_perm(
            "asset:contract:view",
            "asset:contract:create",
            "asset:contract:edit",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).option_assets(
        context,
        keyword=keyword,
        contract_id=contract_id,
        page=page,
        page_size=page_size,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/contracts/options/departments", summary="合同可选部门")
async def option_departments(
    context: AuthContext = Depends(
        require_any_perm(
            "asset:contract:view",
            "asset:contract:create",
            "asset:contract:edit",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).option_departments(context)
    return ok(result)


@router.get("/contracts/options/owners", summary="合同负责人选项")
async def option_owners(
    keyword: str | None = Query(None, max_length=100),
    context: AuthContext = Depends(
        require_any_perm(
            "asset:contract:view",
            "asset:contract:create",
            "asset:contract:edit",
        )
    ),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).option_owners(context, keyword)
    return ok([item.model_dump(mode="json") for item in result])


@router.get("/contracts/summary", summary="合同概览")
async def contract_summary(
    context: AuthContext = Depends(require_perm("asset:contract:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).summary(context)
    return ok(result.model_dump(mode="json"))


@router.get("/contracts", summary="合同列表")
async def list_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    contract_type: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=20),
    dept_id: int | None = Query(None, ge=1),
    context: AuthContext = Depends(require_perm("asset:contract:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).list_contracts(
        context,
        page=page,
        page_size=page_size,
        keyword=keyword,
        contract_type=contract_type,
        status=status,
        dept_id=dept_id,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/contracts", summary="新建合同")
async def create_contract(
    payload: ContractCreate,
    context: AuthContext = Depends(require_perm("asset:contract:create")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).create_contract(payload, context)
    return ok(result.model_dump(mode="json"), message="合同已创建")


@router.get("/contracts/{contract_id}", summary="合同详情")
async def contract_detail(
    contract_id: int,
    context: AuthContext = Depends(require_perm("asset:contract:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).get_contract(contract_id, context)
    return ok(result.model_dump(mode="json"))


@router.put("/contracts/{contract_id}", summary="更新合同")
async def update_contract(
    contract_id: int,
    payload: ContractUpdate,
    context: AuthContext = Depends(require_perm("asset:contract:edit")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).update_contract(
        contract_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="合同已更新")


@router.post("/contracts/{contract_id}/terminate", summary="终止合同")
async def terminate_contract(
    contract_id: int,
    payload: ContractTerminatePayload,
    context: AuthContext = Depends(require_perm("asset:contract:terminate")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).terminate_contract(
        contract_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="合同已终止")


@router.post("/contracts/{contract_id}/renew", summary="续签合同")
async def renew_contract(
    contract_id: int,
    payload: ContractRenewPayload,
    context: AuthContext = Depends(require_perm("asset:contract:edit")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).renew_contract(
        contract_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="合同已续签")


@router.post("/contracts/{contract_id}/assets", summary="关联合同资产")
async def link_assets(
    contract_id: int,
    payload: ContractLinkPayload,
    context: AuthContext = Depends(require_perm("asset:contract:edit")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).link_assets(
        contract_id, payload, context
    )
    return ok(result.model_dump(mode="json"), message="资产已关联")


@router.delete(
    "/contracts/{contract_id}/assets/{asset_id}", summary="解除资产关联"
)
async def unlink_asset(
    contract_id: int,
    asset_id: int,
    context: AuthContext = Depends(require_perm("asset:contract:edit")),
    session: AsyncSession = Depends(get_db),
):
    result = await ContractService(session).unlink_asset(
        contract_id, asset_id, context
    )
    return ok(result.model_dump(mode="json"), message="资产关联已解除")
