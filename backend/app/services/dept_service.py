from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, ConflictError, NotFoundError, PermissionDenied
from app.models import Dept, User
from app.repositories.dept_repo import DeptRepository
from app.schemas.org import DeptCreate, DeptOut, DeptUpdate
from app.services.audit_service import AuditService
from app.services.permission_service import AuthContext
from app.services.scope_service import scoped_dept_tree_ids
from app.services.txn import commit_or_conflict


def _snapshot(dept: Dept) -> dict[str, object]:
    return {
        "name": dept.name,
        "code": dept.code,
        "parent_id": dept.parent_id,
        "leader": dept.leader,
        "manager_id": dept.manager_id,
        "manager_name": dept.manager_name,
        "phone": dept.phone,
        "sort": dept.sort,
        "status": dept.status,
        "remark": dept.remark,
        "version": dept.version,
    }


class DeptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.depts = DeptRepository(session)
        self.audit = AuditService(session)

    async def tree(self, context: AuthContext, *, source: str | None = None) -> list[DeptOut]:
        depts = await self.depts.list_all()
        allowed_ids = await scoped_dept_tree_ids(self.session, context)
        if allowed_ids is not None:
            depts = [dept for dept in depts if dept.id in allowed_ids]
        if source is not None:
            depts = [dept for dept in depts if dept.source == source]
        counts = await self.depts.user_counts()

        nodes = {
            dept.id: DeptOut(
                id=dept.id,
                parent_id=dept.parent_id,
                name=dept.name,
                code=dept.code,
                leader=dept.leader,
                manager_id=dept.manager_id,
                manager_name=dept.manager_name,
                phone=dept.phone,
                path=dept.path,
                level=dept.level,
                sort=dept.sort,
                status=dept.status,
                remark=dept.remark,
                source=dept.source,
                ldap_dn=dept.ldap_dn,
                version=dept.version,
                user_count=counts.get(dept.id, 0),
            )
            for dept in depts
        }
        roots: list[DeptOut] = []
        for dept in depts:
            node = nodes[dept.id]
            if dept.parent_id and dept.parent_id in nodes:
                nodes[dept.parent_id].children.append(node)
            else:
                roots.append(node)
        self._sort_tree(roots)
        return roots

    @staticmethod
    def _sort_tree(nodes: list[DeptOut]) -> None:
        nodes.sort(key=lambda item: (item.sort, item.id))
        for node in nodes:
            DeptService._sort_tree(node.children)

    async def _get_manager(self, manager_id: int | None) -> User | None:
        if manager_id is None:
            return None
        manager = await self.session.get(User, manager_id)
        if manager is None or manager.deleted_at is not None:
            raise NotFoundError("部门负责人不存在")
        if manager.status != 1:
            raise BizError("所选部门负责人已停用")
        return manager

    async def create(self, payload: DeptCreate, context: AuthContext) -> DeptOut:
        if await self.depts.get_by_code(payload.code):
            raise ConflictError("部门编码已存在", code=40910)

        parent: Dept | None = None
        if payload.parent_id is not None:
            parent = await self.depts.get(payload.parent_id)
            if parent is None:
                raise NotFoundError("上级部门不存在")
            if parent.status != 1:
                raise BizError("上级部门已停用，无法新增下级部门")

        manager = await self._get_manager(payload.manager_id)
        dept = Dept(
            parent_id=parent.id if parent else None,
            name=payload.name,
            code=payload.code,
            leader=payload.leader,
            manager_id=manager.id if manager else None,
            phone=payload.phone,
            sort=payload.sort,
            status=payload.status,
            remark=payload.remark,
            path="",
            level=1,
        )
        self.session.add(dept)
        await self.session.flush()
        dept.path = f"{parent.path if parent else '/'}{dept.id}/"
        dept.level = (parent.level + 1) if parent else 1

        await self.audit.record(
            action="org.dept.create",
            module="组织管理",
            summary=f"新增部门：{dept.name}",
            actor=context.user,
            resource_type="dept",
            resource_id=dept.id,
            after=_snapshot(dept),
        )
        await commit_or_conflict(self.session)
        return DeptOut.model_validate(dept, from_attributes=True)

    async def update(self, dept_id: int, payload: DeptUpdate, context: AuthContext) -> DeptOut:
        dept = await self.depts.get(dept_id)
        if dept is None:
            raise NotFoundError("部门不存在")
        if dept.version != payload.version:
            raise ConflictError("部门信息已被他人修改，请刷新后重试")
        if dept.source != "local" and not context.is_superuser:
            raise PermissionDenied("外部来源部门由同步任务维护，仅超级管理员可修改")

        duplicate = await self.depts.get_by_code(payload.code)
        if duplicate is not None and duplicate.id != dept.id:
            raise ConflictError("部门编码已存在", code=40910)

        parent: Dept | None = None
        if payload.parent_id is not None:
            if payload.parent_id == dept.id:
                raise BizError("上级部门不能选择自身")
            parent = await self.depts.get(payload.parent_id)
            if parent is None:
                raise NotFoundError("上级部门不存在")
            self._assert_no_cycle(dept, parent)
            if parent.status != 1:
                raise BizError("上级部门已停用，无法挂载下级部门")

        before = _snapshot(dept)
        all_depts = await self.depts.list_all()
        old_path = dept.path
        old_level = dept.level
        manager = await self._get_manager(payload.manager_id)

        dept.parent_id = parent.id if parent else None
        dept.name = payload.name
        dept.code = payload.code
        dept.leader = payload.leader
        dept.manager_id = manager.id if manager else None
        dept.phone = payload.phone
        dept.sort = payload.sort
        dept.status = payload.status
        dept.remark = payload.remark
        dept.path = f"{parent.path if parent else '/'}{dept.id}/"
        dept.level = (parent.level + 1) if parent else 1

        if dept.path != old_path or dept.level != old_level:
            new_prefix = dept.path
            old_prefix = old_path
            level_delta = dept.level - old_level
            for item in all_depts:
                if item.id == dept.id or not item.path.startswith(old_prefix):
                    continue
                item.path = new_prefix + item.path[len(old_prefix) :]
                item.level = max(1, item.level + level_delta)

        await self.audit.record(
            action="org.dept.update",
            module="组织管理",
            summary=f"编辑部门：{dept.name}",
            actor=context.user,
            resource_type="dept",
            resource_id=dept.id,
            before=before,
            after=_snapshot(dept),
        )
        await commit_or_conflict(self.session)
        return DeptOut.model_validate(dept, from_attributes=True)

    @staticmethod
    def _assert_no_cycle(dept: Dept, new_parent: Dept) -> None:
        if new_parent.id == dept.id or new_parent.path.startswith(dept.path):
            raise BizError("上级部门不能选择当前部门的下级部门")

    async def delete(self, dept_id: int, context: AuthContext) -> None:
        dept = await self.depts.get(dept_id)
        if dept is None:
            raise NotFoundError("部门不存在")
        if dept.source != "local" and not context.is_superuser:
            raise PermissionDenied("外部来源部门由同步任务维护，仅超级管理员可删除")
        if await self.depts.count_children(dept.id):
            raise BizError("该部门存在下级部门，无法删除")
        if await self.depts.count_users(dept.id):
            raise BizError("该部门仍有用户，无法删除")
        if await self.depts.count_role_refs(dept.id):
            raise BizError("该部门已被角色数据权限引用，无法删除")

        before = _snapshot(dept)
        await self.session.delete(dept)
        await self.audit.record(
            action="org.dept.delete",
            module="组织管理",
            summary=f"删除部门：{before['name']}",
            actor=context.user,
            resource_type="dept",
            resource_id=dept_id,
            before=before,
        )
        await commit_or_conflict(self.session)
