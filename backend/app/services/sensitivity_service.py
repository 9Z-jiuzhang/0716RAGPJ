"""敏感话题权限：密级比较、用户上限、审计与管理。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.identity import User
from app.models.sensitivity import (
    LEVEL_ORDER,
    ROLE_SENSITIVITY_MAPPING,
    SENSITIVITY_LEVELS,
    RoleSensitivityPermission,
    SensitivityAuditLog,
    UserSensitivityOverride,
    audit_row_dict,
    normalize_sensitivity_level,
)
from app.models.base import utcnow

logger = logging.getLogger(__name__)


class SensitivityService:
    """密级权限门面。"""

    def can_access_level(self, user_max_level: str, content_level: str) -> bool:
        return LEVEL_ORDER.get(normalize_sensitivity_level(content_level), 0) <= LEVEL_ORDER.get(
            normalize_sensitivity_level(user_max_level), 0
        )

    def max_level_from_role_names(self, role_names: list[str], *, db_role_map: dict[str, str] | None = None) -> str:
        mapping = {**ROLE_SENSITIVITY_MAPPING, **(db_role_map or {})}
        if not role_names:
            return "normal"
        rank = max(LEVEL_ORDER.get(mapping.get(name, "normal"), 0) for name in role_names)
        return SENSITIVITY_LEVELS[rank]

    async def load_role_permission_map(self, db: AsyncSession, *, tenant_id: str) -> dict[str, str]:
        rows = list(
            (
                await db.scalars(
                    select(RoleSensitivityPermission).where(RoleSensitivityPermission.tenant_id == tenant_id)
                )
            ).all()
        )
        return {r.role: normalize_sensitivity_level(r.max_sensitivity_level) for r in rows}

    async def get_user_override(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: uuid.UUID,
    ) -> UserSensitivityOverride | None:
        row = await db.scalar(
            select(UserSensitivityOverride).where(
                UserSensitivityOverride.tenant_id == tenant_id,
                UserSensitivityOverride.user_id == user_id,
            )
        )
        if row is None:
            return None
        if row.expires_at is not None:
            expires = row.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                return None
        return row

    async def resolve_user_max_level(
        self,
        db: AsyncSession,
        *,
        user: User | None,
        tenant_id: str | None = None,
    ) -> str:
        """访客/未登录 → normal；登录用户：多角色最高 + override 取 max。"""
        tenant = tenant_id or settings.FAQ_TENANT_ID
        if user is None:
            return "normal"
        role_names = [r.name for r in (user.roles or []) if getattr(r, "is_enabled", True)]
        db_map = await self.load_role_permission_map(db, tenant_id=tenant)
        base = self.max_level_from_role_names(role_names, db_role_map=db_map)
        override = await self.get_user_override(db, tenant_id=tenant, user_id=user.id)
        if override is None:
            return base
        override_level = normalize_sensitivity_level(override.max_sensitivity_level)
        if LEVEL_ORDER[override_level] >= LEVEL_ORDER[base]:
            return override_level
        return base

    async def log_access_denied(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: uuid.UUID | None,
        question: str,
        sensitivity_level: str,
        source: str,
        conversation_id: uuid.UUID | None = None,
        reason: str | None = None,
        commit: bool = False,
    ) -> None:
        db.add(
            SensitivityAuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                question=(question or "")[:2000],
                sensitivity_level=normalize_sensitivity_level(sensitivity_level),
                action="denied",
                source=source,
                reason=(reason or "需要更高权限")[:100],
            )
        )
        if commit:
            await db.commit()
        else:
            await db.flush()

    async def log_config_change(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: uuid.UUID | None,
        action: str,
        sensitivity_level: str,
        detail: dict[str, Any] | None = None,
        context: str = "update",
        commit: bool = False,
    ) -> None:
        """KB 默认密级变更 / 同步等配置类审计（进敏感审计表）。"""
        payload = dict(detail or {})
        payload.setdefault("context", context)
        db.add(
            SensitivityAuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=None,
                question="",
                sensitivity_level=normalize_sensitivity_level(sensitivity_level),
                action=action,
                source="kb",
                reason=None,
                detail=payload,
            )
        )
        if commit:
            await db.commit()
        else:
            await db.flush()

    async def ensure_default_role_permissions(self, db: AsyncSession, *, tenant_id: str) -> None:
        for role, level in ROLE_SENSITIVITY_MAPPING.items():
            stmt = insert(RoleSensitivityPermission).values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                role=role,
                max_sensitivity_level=level,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["tenant_id", "role"])
            await db.execute(stmt)
        await db.commit()

    async def list_role_permissions(self, db: AsyncSession, *, tenant_id: str) -> list[dict[str, Any]]:
        await self.ensure_default_role_permissions(db, tenant_id=tenant_id)
        rows = list(
            (
                await db.scalars(
                    select(RoleSensitivityPermission)
                    .where(RoleSensitivityPermission.tenant_id == tenant_id)
                    .order_by(RoleSensitivityPermission.role.asc())
                )
            ).all()
        )
        return [
            {
                "role": r.role,
                "max_sensitivity_level": r.max_sensitivity_level,
                "default_level": ROLE_SENSITIVITY_MAPPING.get(r.role, "normal"),
            }
            for r in rows
        ]

    async def update_role_permission(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        role: str,
        max_level: str,
    ) -> dict[str, Any]:
        level = normalize_sensitivity_level(max_level)
        row = await db.scalar(
            select(RoleSensitivityPermission).where(
                RoleSensitivityPermission.tenant_id == tenant_id,
                RoleSensitivityPermission.role == role,
            )
        )
        if row is None:
            row = RoleSensitivityPermission(tenant_id=tenant_id, role=role, max_sensitivity_level=level)
            db.add(row)
        else:
            row.max_sensitivity_level = level
            row.updated_at = utcnow()
        await db.commit()
        return {"role": role, "max_sensitivity_level": level}

    async def upsert_user_override(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: uuid.UUID,
        max_level: str,
        reason: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        level = normalize_sensitivity_level(max_level)
        row = await db.scalar(
            select(UserSensitivityOverride).where(
                UserSensitivityOverride.tenant_id == tenant_id,
                UserSensitivityOverride.user_id == user_id,
            )
        )
        if row is None:
            row = UserSensitivityOverride(
                tenant_id=tenant_id,
                user_id=user_id,
                max_sensitivity_level=level,
                reason=reason,
                expires_at=expires_at,
            )
            db.add(row)
        else:
            row.max_sensitivity_level = level
            row.reason = reason
            row.expires_at = expires_at
            row.updated_at = utcnow()
        await db.commit()
        return {
            "user_id": str(user_id),
            "max_sensitivity_level": level,
            "reason": reason,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    async def delete_user_override(self, db: AsyncSession, *, tenant_id: str, user_id: uuid.UUID) -> bool:
        row = await db.scalar(
            select(UserSensitivityOverride).where(
                UserSensitivityOverride.tenant_id == tenant_id,
                UserSensitivityOverride.user_id == user_id,
            )
        )
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
        return True

    async def list_audit(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        page: int = 1,
        size: int = 50,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        filters = [SensitivityAuditLog.tenant_id == tenant_id]
        if user_id is not None:
            filters.append(SensitivityAuditLog.user_id == user_id)
        from sqlalchemy import func

        total = int(await db.scalar(select(func.count()).select_from(SensitivityAuditLog).where(*filters)) or 0)
        rows = list(
            (
                await db.scalars(
                    select(SensitivityAuditLog)
                    .where(*filters)
                    .order_by(SensitivityAuditLog.created_at.desc())
                    .offset(max(0, (page - 1) * size))
                    .limit(size)
                )
            ).all()
        )
        return {"items": [audit_row_dict(r) for r in rows], "total": total, "page": page, "size": size}

    async def filter_hits_by_sensitivity(
        self,
        db: AsyncSession,
        hits: list[Any],
        *,
        user_max_level: str,
    ) -> tuple[list[Any], int]:
        """按 document_chunks.sensitivity_level 过滤检索命中；返回 (保留列表, 滤掉数量)。"""
        if not hits:
            return [], 0
        from app.models.document import DocumentChunk

        chunk_ids: list[uuid.UUID] = []
        for hit in hits:
            raw = getattr(hit, "chunk_id", None) or (hit.get("chunk_id") if isinstance(hit, dict) else None)
            if not raw:
                continue
            try:
                chunk_ids.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        if not chunk_ids:
            return list(hits), 0
        rows = list(
            (
                await db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
            ).all()
        )
        level_by_id = {str(r.id): normalize_sensitivity_level(getattr(r, "sensitivity_level", None)) for r in rows}
        kept = []
        dropped = 0
        for hit in hits:
            cid = str(getattr(hit, "chunk_id", None) or (hit.get("chunk_id") if isinstance(hit, dict) else "") or "")
            level = level_by_id.get(cid, "normal")
            if self.can_access_level(user_max_level, level):
                if hasattr(hit, "metadata") and isinstance(hit.metadata, dict):
                    hit.metadata["sensitivity_level"] = level
                kept.append(hit)
            else:
                dropped += 1
        return kept, dropped


sensitivity_service = SensitivityService()
