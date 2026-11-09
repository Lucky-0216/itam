from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.permissions import SUPER_ADMIN_ROLE
from app.models import Role, User, user_roles
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    @staticmethod
    def _with_relations():
        return (
            selectinload(User.dept),
            selectinload(User.roles).selectinload(Role.menus),
            selectinload(User.roles).selectinload(Role.depts),
        )

    async def get_by_username(self, username: str) -> User | None:
        stmt = (
            select(User)
            .options(*self._with_relations())
            .where(User.username == username, User.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_with_relations(self, user_id: int) -> User | None:
        stmt = (
            select(User)
            .options(*self._with_relations())
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_detail(self, user_id: int) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.dept), selectinload(User.roles))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_conflict(
        self,
        *,
        username: str,
        employee_no: str | None,
        email: str | None,
        exclude_id: int | None = None,
    ) -> User | None:
        conditions = [User.username == username]
        if employee_no:
            conditions.append(User.employee_no == employee_no)
        if email:
            conditions.append(User.email == email)
        stmt = select(User).where(or_(*conditions))
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        dept_ids: set[int] | None = None,
        status: int | None = None,
        role_id: int | None = None,
        source: str | None = None,
        self_user_id: int | None = None,
    ) -> tuple[list[User], int]:
        conditions = [User.deleted_at.is_(None)]
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    User.username.like(pattern),
                    User.real_name.like(pattern),
                    User.employee_no.like(pattern),
                    User.email.like(pattern),
                    User.phone.like(pattern),
                )
            )
        if dept_ids is not None:
            if not dept_ids:
                return [], 0
            conditions.append(User.dept_id.in_(dept_ids))
        if status is not None:
            conditions.append(User.status == status)
        if role_id is not None:
            conditions.append(User.roles.any(Role.id == role_id))
        if source is not None:
            conditions.append(User.source == source)
        if self_user_id is not None:
            conditions.append(User.id == self_user_id)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(User).where(*conditions)
            )
            or 0
        )
        stmt = (
            select(User)
            .options(selectinload(User.dept), selectinload(User.roles))
            .where(*conditions)
            .order_by(User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        users = list((await self.session.execute(stmt)).scalars().all())
        return users, total

    async def list_by_ids(self, user_ids: list[int]) -> list[User]:
        if not user_ids:
            return []
        stmt = (
            select(User)
            .options(selectinload(User.dept), selectinload(User.roles))
            .where(User.id.in_(user_ids), User.deleted_at.is_(None))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_active_super_admins(self, *, exclude_user_id: int | None = None) -> int:
        conditions = [
            Role.code == SUPER_ADMIN_ROLE,
            User.status == 1,
            User.deleted_at.is_(None),
        ]
        if exclude_user_id is not None:
            conditions.append(User.id != exclude_user_id)
        stmt = (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(*conditions)
        )
        return int(await self.session.scalar(stmt) or 0)
