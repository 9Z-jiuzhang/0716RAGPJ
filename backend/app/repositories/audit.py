"""审计日志数据访问层。"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from app.schemas.audit import AuditLogFilterParams


class AuditRepository:
    """审计日志 CRUD。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, log: AuditLog) -> AuditLog:
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def get_by_id(self, log_id: UUID) -> AuditLog | None:
        result = await self.db.execute(select(AuditLog).where(AuditLog.id == log_id))
        return result.scalar_one_or_none()

    async def resolve_user_name(self, user_id: UUID | None) -> str | None:
        """解析操作者展示名（昵称优先，其次账号）。"""
        if user_id is None:
            return None
        user = await self.db.get(User, user_id)
        if user is None:
            return None
        nickname = getattr(user, "nickname", None)
        username = getattr(user, "username", None)
        return nickname or username or str(user_id)

    async def list_filtered(
        self, params: AuditLogFilterParams
    ) -> tuple[Sequence[tuple[AuditLog, str | None]], int]:
        """分页筛选；附带操作者展示名，避免前端只能看到 UUID。"""
        conditions = []
        if params.user_id is not None:
            conditions.append(AuditLog.user_id == params.user_id)
        if params.action:
            conditions.append(AuditLog.action.ilike(f"{params.action}%"))
        if params.resource_type:
            conditions.append(AuditLog.resource_type == params.resource_type)
        if params.resource_id:
            conditions.append(AuditLog.resource_id == params.resource_id)
        if params.result:
            conditions.append(AuditLog.result == params.result)
        if params.start_date:
            conditions.append(AuditLog.created_at >= params.start_date)
        if params.end_date:
            conditions.append(AuditLog.created_at <= params.end_date)

        where_clause = and_(*conditions) if conditions else True
        count_result = await self.db.execute(select(func.count()).select_from(AuditLog).where(where_clause))
        total = int(count_result.scalar_one())
        display_name = func.coalesce(User.nickname, User.username)
        stmt = (
            select(AuditLog, display_name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(where_clause)
            .order_by(AuditLog.created_at.desc())
            .offset((params.page - 1) * params.page_size)
            .limit(params.page_size)
        )
        result = await self.db.execute(stmt)
        rows: list[tuple[AuditLog, str | None]] = []
        for log, name in result.all():
            rows.append((log, name))
        return rows, total
