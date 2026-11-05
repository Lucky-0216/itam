from sqlalchemy import func, select

from app.core.assets import AssetStatus
from app.core.database import AsyncSessionLocal
from app.models import Asset, AssetCategory, AssetHistory, AssetModel, AuditLog
from app.repositories.user_repo import UserRepository
from app.services.dingtalk_import_service import DingTalkImportService
from app.services.permission_service import PermissionService


def _payload() -> dict:
    return {
        "source": {
            "base_id": "test-base",
            "table_id": "test-table",
            "record_count": 5,
        },
        "categories": [
            {
                "name": "笔记本电脑",
                "code": "HW-LAPTOP",
                "category_type": "HARDWARE",
            },
            {
                "name": "测试专用分类",
                "code": "TEST-DT-CAT",
                "category_type": "ACCESSORY",
            },
        ],
        "models": [
            {
                "key": "model-1",
                "name": "测试型号",
                "code": "TEST-DT-M1",
                "brand": "测试品牌",
                "spec": "测试规格",
                "category_name": "测试专用分类",
            }
        ],
        "assets": [
            {
                "row": 1,
                "record_id": "rec-1",
                "asset_no": "DT-TEST-0001",
                "name": "测试在库资产",
                "category_name": "测试专用分类",
                "model_key": "model-1",
                "source_status": "闲置在库",
                "status": "IN_STOCK",
                "purchase_date": "2025-01-02",
                "remark": "备注内容",
                "detail": "详细规格",
            },
            {
                "row": 2,
                "record_id": "rec-2",
                "asset_no": "DT-TEST-0002",
                "name": "测试在用资产",
                "category_name": "笔记本电脑",
                "model_key": None,
                "source_status": "使用中",
                "status": "IN_USE",
                "purchase_date": None,
                "remark": None,
                "detail": None,
            },
            {
                "row": 3,
                "record_id": "rec-3",
                "asset_no": "DT-TEST-0001",
                "name": "重复编码资产",
                "category_name": "笔记本电脑",
                "model_key": None,
                "source_status": "使用中",
                "status": "IN_USE",
                "purchase_date": None,
                "remark": None,
                "detail": None,
            },
            {
                "row": 4,
                "record_id": "rec-4",
                "asset_no": None,
                "name": None,
                "category_name": None,
                "model_key": None,
                "source_status": None,
                "status": "IN_STOCK",
                "purchase_date": None,
                "remark": None,
                "detail": None,
            },
            {
                "row": 5,
                "record_id": "rec-5",
                "asset_no": "DT-TEST-0005",
                "name": "分类缺失资产",
                "category_name": "不存在的分类",
                "model_key": None,
                "source_status": "使用中",
                "status": "IN_USE",
                "purchase_date": None,
                "remark": None,
                "detail": None,
            },
        ],
    }


async def _import(payload: dict):
    session = AsyncSessionLocal()
    admin = await UserRepository(session).get_by_username("admin")
    context = await PermissionService(session).build_context(
        admin, access_jti="test-import", access_exp=0
    )
    service = DingTalkImportService(session, context)
    report = await service.run(
        payload,
        create_categories=True,
        create_models=True,
        dry_run=False,
    )
    await session.close()
    return report


async def test_dingtalk_import_statuses_duplicates_and_idempotency(client):
    async with AsyncSessionLocal() as check:
        category_base = await check.scalar(
            select(func.count()).select_from(AssetCategory)
        )
        model_base = await check.scalar(select(func.count()).select_from(AssetModel))

    report = await _import(_payload())
    assert report.total == 5
    assert report.created == 2
    assert report.skipped == 1
    assert report.failed == 2
    assert report.categories_created == 1
    assert report.models_created == 1
    assert report.status_counts == {"IN_STOCK": 1, "IN_USE": 1}

    async with AsyncSessionLocal() as check:
        first = (
            await check.execute(select(Asset).where(Asset.asset_no == "DT-TEST-0001"))
        ).scalar_one()
        assert first.status == AssetStatus.IN_STOCK
        assert first.purchase_date.isoformat() == "2025-01-02"
        assert first.remark == "备注内容；描述：详细规格"
        assert first.model is not None and first.model.code == "TEST-DT-M1"
        assert first.category.name == "测试专用分类"

        second = (
            await check.execute(select(Asset).where(Asset.asset_no == "DT-TEST-0002"))
        ).scalar_one()
        assert second.status == AssetStatus.IN_USE

        assert await check.scalar(select(func.count()).select_from(Asset)) == 2
        assert (
            await check.scalar(select(func.count()).select_from(AssetCategory))
            == category_base + 1
        )
        assert (
            await check.scalar(select(func.count()).select_from(AssetModel))
            == model_base + 1
        )
        histories = (
            (
                await check.execute(
                    select(AssetHistory).where(AssetHistory.action == "IMPORT")
                )
            )
            .scalars()
            .all()
        )
        assert len(histories) == 2
        assert all(item.from_status == item.to_status for item in histories)

    rerun = await _import(_payload())
    assert rerun.created == 0
    assert rerun.skipped == 3
    assert rerun.failed == 2
    assert rerun.categories_created == 0
    assert rerun.models_created == 0

    async with AsyncSessionLocal() as check:
        assert await check.scalar(select(func.count()).select_from(Asset)) == 2
        imports = await check.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "asset.import.dingtalk")
        )
        batches = await check.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "asset.import.dingtalk.batch")
        )
        assert imports == 2
        assert batches == 2
