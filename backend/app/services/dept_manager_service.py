from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.models import Dept, User
from app.repositories.user_repo import UserRepository
from app.schemas.org import (
    DeptManagerResultOut,
    DeptManagerUpdate,
    DeptMemberOut,
    DeptMemberPageOut,
    DeptOut,
)
from app.services.audit_service import AuditService
from app.services.dept_service import DeptService
from app.services.permission_service import AuthContext
from app.services.scope_service import scoped_dept_tree_ids
from app.services.txn import commit_or_conflict

STATUS_CONFLICT_MESSAGE = "部门信息已被他人修改，请刷新后重试"


def _member_out(user: User, *, manager_id: int | None) -> DeptMemberOut:
    return DeptMemberOut(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        employee_no=user.employee_no,
        position=user.position,
        source=user.source,
        status=user.status,
        is_manager=user.id == manager_id,
    )


class DeptManagerService:
    """按来源维护部门负责人；只写本地 manager_id，不回写钉钉/域控。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def tree(self, context: AuthContext, source: str) -> list[DeptOut]:
        return await DeptService(self.session).tree(context, source=source)

    async def _get_dept(self, dept_id: int, source: str, context: AuthContext) -> Dept:
        dept = await self.session.get(Dept, dept_id)
        if dept is None:
            raise NotFoundError("部门不存在")
        if dept.source != source:
            raise BizError("部门来源与当前组织不一致，请刷新后重试")
        allowed = await scoped_dept_tree_ids(self.session, context)
        if allowed is not None and dept.id not in allowed:
            raise PermissionDenied("无权查看该部门")
        return dept

    async def _get_manager(self, dept: Dept) -> User | None:
        if dept.manager_id is None:
            return None
        manager = await self.session.get(User, dept.manager_id)
        if manager is None or manager.deleted_at is not None:
            return None
        return manager

    async def members(
        self,
        context: AuthContext,
        dept_id: int,
        *,
        source: str,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> DeptMemberPageOut:
        dept = await self._get_dept(dept_id, source, context)
        users, total = await self.users.list_paginated(
            page=page,
            page_size=page_size,
            keyword=keyword,
            dept_ids={dept.id},
            source=source,
        )
        manager = await self._get_manager(dept)
        return DeptMemberPageOut(
            items=[_member_out(user, manager_id=dept.manager_id) for user in users],
            total=total,
            page=page,
            page_size=page_size,
            manager=_member_out(manager, manager_id=dept.manager_id) if manager else None,
        )

    async def assign(
        self, dept_id: int, payload: DeptManagerUpdate, context: AuthContext
    ) -> DeptManagerResultOut:
        dept = await self._get_dept(dept_id, payload.source, context)
        if dept.version != payload.version:
            raise ConflictError(STATUS_CONFLICT_MESSAGE)

        manager: User | None = None
        if payload.manager_id is not None:
            manager = await self.session.get(User, payload.manager_id)
            if manager is None or manager.deleted_at is not None:
                raise NotFoundError("所选成员不存在")
            if manager.status != 1:
                raise BizError("所选成员已停用，无法设为负责人")
            if manager.dept_id != dept.id:
                raise BizError("只能选择该部门直属成员作为负责人")
            if manager.source != dept.source:
                raise BizError("不能跨来源指定部门负责人")

        before_manager = await self._get_manager(dept)
        before = {
            "manager_id": dept.manager_id,
            "manager_name": before_manager.real_name if before_manager else None,
        }
        dept.manager_id = manager.id if manager else None
        after_manager = manager

        if after_manager is None:
            summary = f"取消部门负责人：{dept.name}"
            if before["manager_name"]:
                summary += f"（{before['manager_name']}）"
            action = "org.dept.manager.clear"
        else:
            summary = f"指定部门负责人：{dept.name} {before['manager_name'] or '未设置'} → {after_manager.real_name}"
            action = "org.dept.manager.assign"

        await self.audit.record(
            action=action,
            module="组织管理",
            summary=summary,
            actor=context.user,
            resource_type="dept",
            resource_id=dept.id,
            before=before,
            after={
                "manager_id": dept.manager_id,
                "manager_name": after_manager.real_name if after_manager else None,
            },
        )
        await commit_or_conflict(self.session, message=STATUS_CONFLICT_MESSAGE)
        return DeptManagerResultOut(
            dept_id=dept.id,
            dept_name=dept.name,
            source=dept.source,
            manager_id=dept.manager_id,
            manager_name=after_manager.real_name if after_manager else None,
            version=dept.version,
        )
