from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.repositories.user_repo import UserRepository
from app.services.dingtalk_import_service import DingTalkImportService
from app.services.permission_service import PermissionService


def _load_payload(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        raise SystemExit("导入文件格式不正确：缺少 assets 列表")
    return payload


async def _run(args: argparse.Namespace) -> int:
    payload = _load_payload(Path(args.file))
    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_username(args.actor)
        if admin is None:
            raise SystemExit(f"操作人「{args.actor}」不存在")
        context = await PermissionService(session).build_context(
            admin,
            access_jti="dingtalk-import",
            access_exp=0,
        )
        service = DingTalkImportService(session, context)
        report = await service.run(
            payload,
            create_categories=args.create_categories,
            create_models=args.create_models,
            dry_run=not args.execute,
        )

    data = report.as_dict()
    if args.report:
        Path(args.report).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {key: value for key, value in data.items() if key != "issues"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if data["issues"]:
        print(f"问题明细：{len(data['issues'])} 条（完整清单见 --report）")
        for item in data["issues"][:20]:
            print(
                f"  row={item['row']} action={item['action']} "
                f"asset_no={item['asset_no']} message={item['message']}"
            )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从钉钉 AI 表格只读导出的规范化数据导入 ITAM 资产台账"
    )
    parser.add_argument("--file", required=True, help="规范化导入 JSON 路径")
    parser.add_argument(
        "--execute", action="store_true", help="实际写入；缺省仅做 dry-run"
    )
    parser.add_argument(
        "--create-categories", action="store_true", help="缺少的分类按名称创建"
    )
    parser.add_argument(
        "--create-models", action="store_true", help="缺少的型号按编码创建"
    )
    parser.add_argument("--actor", default="admin", help="记录审计的操作人用户名")
    parser.add_argument("--report", help="完整报告输出路径")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
