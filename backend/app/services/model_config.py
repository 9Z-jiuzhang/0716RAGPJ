"""大模型配置服务。"""

from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import APIException, NotFoundException
from app.models.model_config import ModelConfig
from app.schemas.common import PageResponse
from app.schemas.model_config import (
    CreateModelConfigRequest,
    ModelConfigResponse,
    UpdateModelConfigRequest,
)


class ModelConfigService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_models(
        self,
        *,
        page: int,
        page_size: int,
        model_type: str | None = None,
    ) -> PageResponse[ModelConfigResponse]:
        conditions = []
        if model_type:
            conditions.append(ModelConfig.model_type == model_type)
        total = await self.db.scalar(
            select(func.count()).select_from(ModelConfig).where(*conditions)
        ) or 0
        stmt = select(ModelConfig).order_by(ModelConfig.model_type, ModelConfig.name)
        if conditions:
            stmt = stmt.where(*conditions)
        rows = list(
            (
                await self.db.scalars(
                    stmt.offset((page - 1) * page_size).limit(page_size)
                )
            ).all()
        )
        return PageResponse(
            items=[self._to_response(r) for r in rows],
            total=int(total),
            page=page,
            page_size=page_size,
        )

    async def create(self, data: CreateModelConfigRequest) -> ModelConfigResponse:
        row = ModelConfig(
            name=data.name,
            model_type=data.model_type,
            provider=data.provider,
            model_name=data.model_name,
            base_url=data.base_url,
            config=data.config or {},
            timeout_seconds=data.timeout_seconds,
            api_key_env=data.api_key_env,
            is_default=False,
            is_enabled=data.is_enabled,
        )
        self.db.add(row)
        await self.db.flush()
        if data.is_default:
            await self._set_default(row.id, row.model_type)
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_response(row)

    async def update(self, model_id: UUID, data: UpdateModelConfigRequest) -> ModelConfigResponse:
        row = await self._get(model_id)
        payload = data.model_dump(exclude_unset=True)
        for key, value in payload.items():
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_response(row)

    async def set_status(self, model_id: UUID, is_enabled: bool) -> ModelConfigResponse:
        row = await self._get(model_id)
        row.is_enabled = is_enabled
        if not is_enabled:
            row.is_default = False
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_response(row)

    async def set_default(self, model_id: UUID, is_default: bool = True) -> ModelConfigResponse:
        row = await self._get(model_id)
        if is_default:
            if not row.is_enabled:
                raise APIException(400, "禁用的模型不能设为默认", status_code=400)
            await self._set_default(row.id, row.model_type)
        else:
            row.is_default = False
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_response(row)

    async def _set_default(self, model_id: UUID, model_type: str) -> None:
        await self.db.execute(
            update(ModelConfig)
            .where(ModelConfig.model_type == model_type, ModelConfig.is_default.is_(True))
            .values(is_default=False)
        )
        row = await self._get(model_id)
        row.is_default = True

    async def _get(self, model_id: UUID) -> ModelConfig:
        row = await self.db.get(ModelConfig, model_id)
        if row is None:
            raise NotFoundException(f"模型配置不存在: {model_id}")
        return row

    @staticmethod
    def _to_response(row: ModelConfig) -> ModelConfigResponse:
        env_name = row.api_key_env
        has_key = bool(env_name and os.getenv(env_name))
        return ModelConfigResponse(
            id=row.id,
            name=row.name,
            model_type=row.model_type,  # type: ignore[arg-type]
            provider=row.provider,
            model_name=row.model_name,
            base_url=row.base_url,
            is_default=row.is_default,
            is_enabled=row.is_enabled,
            config=row.config or {},
            timeout_seconds=row.timeout_seconds,
            api_key_env=env_name,
            has_api_key=has_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
