from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.core.database import get_db
from app.core.response import ok
from app.services.dashboard_service import DashboardService
from app.services.permission_service import AuthContext

router = APIRouter(tags=["工作台"])


@router.get("/dashboard/summary", summary="工作台指标与图表数据")
async def dashboard_summary(
    scope: str = Query("personal", pattern="^(personal|org)$", description="统计口径：个人/组织"),
    dept_id: int | None = Query(None, ge=1, description="按部门（含下级）过滤"),
    months: int = Query(12, description="趋势区间：0=全部，3/6/12 个月"),
    context: AuthContext = Depends(require_perm("dashboard:view")),
    session: AsyncSession = Depends(get_db),
):
    result = await DashboardService(session).summary(
        context,
        dept_id=dept_id,
        months=months,
        scope=scope,
    )
    return ok(result.model_dump(mode="json"))
