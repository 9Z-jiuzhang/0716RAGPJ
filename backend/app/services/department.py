"""部门管理服务。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    GUEST_DEPARTMENT_CODE,
    derive_visibility,
)
from app.models.department import Department
from app.models.identity import User
from app.models.knowledge_base import KnowledgeBase
from app.schemas.department import (
    DepartmentCreate,
    DepartmentDetail,
    DepartmentKbBrief,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentMemberBrief,
    DepartmentUpdate,
)


def _norm_code(code: str) -> str:
    return (code or "").strip().upper()


class DepartmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_departments(
        self, *, page: int = 1, page_size: int = 50
    ) -> DepartmentListResponse:
        total = await self.db.scalar(select(func.count()).select_from(Department)) or 0
        rows = (
            await self.db.scalars(
                select(Department)
                .order_by(Department.code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [await self._to_list_item(d) for d in rows]
        return DepartmentListResponse(
            items=items, total=int(total), page=page, page_size=page_size
        )

    async def get_department(self, dept_id: uuid.UUID) -> DepartmentDetail | None:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            return None
        return await self._to_detail(dept)

    async def create_department(self, data: DepartmentCreate) -> DepartmentDetail:
        code = _norm_code(data.code)
        if not code:
            raise ValueError("部门编码不能为空")
        exists = await self.db.scalar(
            select(Department.id).where(Department.code == code)
        )
        if exists:
            raise ValueError(f"部门编码已存在：{code}")
        dept = Department(
            code=code,
            name=data.name.strip(),
            description=(data.description or "").strip() or None,
            is_enabled=data.is_enabled,
        )
        self.db.add(dept)
        await self.db.commit()
        await self.db.refresh(dept)
        return await self._to_detail(dept)

    async def update_department(
        self, dept_id: uuid.UUID, data: DepartmentUpdate
    ) -> DepartmentDetail | None:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            return None

        old_code = dept.code
        if data.code is not None:
            new_code = _norm_code(data.code)
            if not new_code:
                raise ValueError("部门编码不能为空")
            if old_code == GUEST_DEPARTMENT_CODE and new_code != GUEST_DEPARTMENT_CODE:
                raise ValueError("“访客专用”为内置部门，不能修改其编码")
            if new_code != old_code:
                clash = await self.db.scalar(
                    select(Department.id).where(
                        Department.code == new_code, Department.id != dept_id
                    )
                )
                if clash:
                    raise ValueError(f"部门编码已存在：{new_code}")
                # 同步迁移用户与知识库上的字符串关联
                await self.db.execute(
                    update(User)
                    .where(User.department == old_code)
                    .values(department=new_code)
                )
                await self.db.execute(
                    update(KnowledgeBase)
                    .where(KnowledgeBase.department == old_code)
                    .values(department=new_code)
                )
                dept.code = new_code

        if data.name is not None:
            name = data.name.strip()
            if not name:
                raise ValueError("部门名称不能为空")
            dept.name = name
        if data.description is not None:
            dept.description = data.description.strip() or None
        if data.is_enabled is not None:
            dept.is_enabled = data.is_enabled

        await self.db.commit()
        await self.db.refresh(dept)
        return await self._to_detail(dept)

    async def delete_department(self, dept_id: uuid.UUID) -> bool:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            return False
        if dept.code == GUEST_DEPARTMENT_CODE:
            raise ValueError("“访客专用”为内置部门，不能删除")
        # 解除关联，保留用户/知识库记录；库解绑后回落为受限
        await self.db.execute(
            update(User)
            .where(User.department == dept.code)
            .values(department=None)
        )
        await self.db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.department == dept.code)
            .values(department=None, visibility=derive_visibility(None))
        )
        await self.db.delete(dept)
        await self.db.commit()
        return True

    async def add_members(
        self, dept_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> DepartmentDetail:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            raise ValueError("部门不存在")
        users = (
            await self.db.scalars(select(User).where(User.id.in_(user_ids)))
        ).all()
        if len(users) != len(set(user_ids)):
            raise ValueError("部分用户不存在")
        for u in users:
            u.department = dept.code
        await self.db.commit()
        return await self._to_detail(dept)

    async def remove_member(
        self, dept_id: uuid.UUID, user_id: uuid.UUID
    ) -> DepartmentDetail:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            raise ValueError("部门不存在")
        user = await self.db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")
        if (user.department or "").strip().upper() != dept.code:
            raise ValueError("该用户不属于此部门")
        user.department = None
        await self.db.commit()
        return await self._to_detail(dept)

    async def add_knowledge_bases(
        self, dept_id: uuid.UUID, kb_ids: list[uuid.UUID]
    ) -> DepartmentDetail:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            raise ValueError("部门不存在")
        kbs = (
            await self.db.scalars(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(kb_ids),
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).all()
        if len(kbs) != len(set(kb_ids)):
            raise ValueError("部分知识库不存在")
        for kb in kbs:
            kb.department = dept.code
            # 可见性由部门派生：归入访客专用即公开，其余为受限
            kb.visibility = derive_visibility(dept.code)
        await self.db.commit()
        return await self._to_detail(dept)

    async def remove_knowledge_base(
        self, dept_id: uuid.UUID, kb_id: uuid.UUID
    ) -> DepartmentDetail:
        dept = await self.db.get(Department, dept_id)
        if not dept:
            raise ValueError("部门不存在")
        kb = await self.db.get(KnowledgeBase, kb_id)
        if not kb or kb.deleted_at is not None:
            raise ValueError("知识库不存在")
        if (kb.department or "").strip().upper() != dept.code:
            raise ValueError("该知识库未关联此部门")
        kb.department = None
        kb.visibility = derive_visibility(None)
        await self.db.commit()
        return await self._to_detail(dept)

    async def _member_count(self, code: str) -> int:
        return int(
            await self.db.scalar(
                select(func.count()).select_from(User).where(User.department == code)
            )
            or 0
        )

    async def _kb_count(self, code: str) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(KnowledgeBase)
                .where(
                    KnowledgeBase.department == code,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def _to_list_item(self, dept: Department) -> DepartmentListItem:
        return DepartmentListItem(
            id=dept.id,
            code=dept.code,
            name=dept.name,
            description=dept.description,
            is_enabled=dept.is_enabled,
            member_count=await self._member_count(dept.code),
            kb_count=await self._kb_count(dept.code),
            created_at=dept.created_at,
            updated_at=dept.updated_at,
        )

    async def _to_detail(self, dept: Department) -> DepartmentDetail:
        members = (
            await self.db.scalars(
                select(User)
                .where(User.department == dept.code)
                .order_by(User.username)
            )
        ).all()
        kbs = (
            await self.db.scalars(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.department == dept.code,
                    KnowledgeBase.deleted_at.is_(None),
                )
                .order_by(KnowledgeBase.name)
            )
        ).all()
        base = await self._to_list_item(dept)
        return DepartmentDetail(
            **base.model_dump(),
            members=[
                DepartmentMemberBrief(
                    id=u.id,
                    username=u.username,
                    nickname=u.nickname,
                    email=u.email,
                    status=u.status,
                )
                for u in members
            ],
            knowledge_bases=[
                DepartmentKbBrief(
                    id=kb.id,
                    name=kb.name,
                    status=kb.status,
                    visibility=kb.visibility,
                    doc_count=None,
                )
                for kb in kbs
            ],
        )
