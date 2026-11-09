from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models import Role, RoleFieldPermission, User, role_menus, user_roles
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_code(self, code: str) -> Role | None:
        stmt = select(Role).where(Role.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_with_relations(self, role_id: int) -> Role | None:
        stmt = (
            select(Role)
            .options(
                selectinload(Role.menus),
                selectinload(Role.depts),
                selectinload(Role.domain_grants),
            )
            .where(Role.id == role_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_enabled(self) -> list[Role]:
        stmt = select(Role).where(Role.status == 1).order_by(Role.sort, Role.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_by_ids(self, role_ids: list[int]) -> list[Role]:
        if not role_ids:
            return []
        stmt = (
            select(Role)
            .options(
                selectinload(Role.menus),
                selectinload(Role.domain_grants),
            )
            .where(Role.id.in_(role_ids))
            .order_by(Role.sort, Role.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        status: int | None = None,
    ) -> tuple[list[tuple[Role, int, int]], int]:
        conditions = []
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(or_(Role.name.like(pattern), Role.code.like(pattern)))
        if status is not None:
            conditions.append(Role.status == status)

        user_count_sq = (
            select(user_roles.c.role_id, func.count(func.distinct(User.id)).label("cnt"))
            .join(User, User.id == user_roles.c.user_id)
            .where(User.deleted_at.is_(None))
            .group_by(user_roles.c.role_id)
            .subquery()
        )
        menu_count_sq = (
            select(role_menus.c.role_id, func.count().label("cnt"))
            .group_by(role_menus.c.role_id)
            .subquery()
        )

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Role).where(*conditions)
            )
            or 0
        )
        stmt = (
            select(
                Role,
                func.coalesce(user_count_sq.c.cnt, 0),
                func.coalesce(menu_count_sq.c.cnt, 0),
            )
            .options(selectinload(Role.domain_grants))
            .outerjoin(user_count_sq, user_count_sq.c.role_id == Role.id)
            .outerjoin(menu_count_sq, menu_count_sq.c.role_id == Role.id)
            .where(*conditions)
            .order_by(Role.sort, Role.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], int(row[1]), int(row[2])) for row in rows], total

    async def count_users(self, role_id: int) -> int:
        stmt = (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(user_roles, user_roles.c.user_id == User.id)
            .where(user_roles.c.role_id == role_id, User.deleted_at.is_(None))
        )
        return int(await self.session.scalar(stmt) or 0)

    async def list_members(self, role_id: int) -> list[User]:
        stmt = (
            select(User)
            .options(selectinload(User.dept))
            .join(user_roles, user_roles.c.user_id == User.id)
            .where(user_roles.c.role_id == role_id, User.deleted_at.is_(None))
            .order_by(User.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_field_permissions(self, role_id: int) -> list[RoleFieldPermission]:
        stmt = (
            select(RoleFieldPermission)
            .where(RoleFieldPermission.role_id == role_id)
            .order_by(RoleFieldPermission.resource, RoleFieldPermission.field)
        )
        return list((await self.session.execute(stmt)).scalars().all())
