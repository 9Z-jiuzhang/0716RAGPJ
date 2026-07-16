"""FastAPI 应用入口与身份模块初始数据。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .api.v1.documents import router as documents_router
from .api.v1.knowledge_bases import router as knowledge_bases_router
from .api.v1.router import api_router
from .core.config import settings
from .core.database import SessionLocal, engine
from .core.logging import setup_logging
from .core.metrics import metrics_payload
from .core.security import hash_password
from .core.seed_data import BUILTIN_PERMISSIONS, BUILTIN_ROLES
from .middleware.access_log import ObservabilityMiddleware
from .models import Base, Permission, Role, User
from .services.langfuse_service import get_langfuse


async def _all_permissions(db: AsyncSession) -> list[Permission]:
    return list((await db.scalars(select(Permission))).all())


async def seed_identity_data() -> None:
    """创建内置权限、角色及演示管理员；已有记录不会被覆盖。"""
    async with SessionLocal() as db:
        existing_codes = {p.code for p in await _all_permissions(db)}
        for code, (name, scope) in BUILTIN_PERMISSIONS.items():
            if code not in existing_codes:
                db.add(Permission(code=code, name=name, description=name, scope=scope))
        await db.flush()

        all_perms = await _all_permissions(db)
        perm_by_code = {p.code: p for p in all_perms}
        roles = {
            r.name: r
            for r in (await db.scalars(select(Role).options(selectinload(Role.permissions)))).all()
        }
        newly_created: set[str] = set()

        for role_name, (description, codes) in BUILTIN_ROLES.items():
            if role_name not in roles:
                roles[role_name] = Role(name=role_name, description=description, is_builtin=True)
                db.add(roles[role_name])
                newly_created.add(role_name)
        await db.flush()

        # flush 后重新加载，避免访问未预加载的 permissions 触发懒加载
        roles = {
            r.name: r
            for r in (await db.scalars(select(Role).options(selectinload(Role.permissions)))).all()
        }

        for role_name, (_, codes) in BUILTIN_ROLES.items():
            role = roles[role_name]
            if role_name not in newly_created and role.permissions:
                continue
            if codes == ["*"]:
                role.permissions = list(all_perms)
            else:
                role.permissions = [perm_by_code[c] for c in codes if c in perm_by_code]

        if not await db.scalar(select(User).where(User.username == "admin")):
            db.add(
                User(
                    username="admin",
                    email="admin@example.com",
                    nickname="系统管理员",
                    hashed_password=hash_password("Admin123!"),
                    roles=[roles["admin"]],
                )
            )
        await db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    get_langfuse()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_identity_data()
    yield
    get_langfuse().flush()
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)
app.include_router(api_router)
app.include_router(knowledge_bases_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


@app.get("/metrics", tags=["系统监控"], summary="Prometheus 指标端点")
async def metrics() -> Response:
    """Prometheus 刮取入口（无 BaseResponse 包装）。"""
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)
