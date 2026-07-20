"""FastAPI 应用入口：生命周期、种子数据、可观测性与模块路由挂载。"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .api.v1.documents import router as documents_router
from .api.v1.knowledge_bases import router as knowledge_bases_router
from .api.v1.router import api_router
from .core.chroma import close_chroma, init_chroma
from .core.config import settings
from .core.constants import (
    GUEST_DEPARTMENT_CODE,
    GUEST_DEPARTMENT_DESC,
    GUEST_DEPARTMENT_NAME,
    VISIBILITY_PUBLIC,
    VISIBILITY_RESTRICTED,
)
from .core.database import (
    SessionLocal,
    engine,
    ensure_postgres_extensions,
    ensure_schema_patches,
)
from .core.logging import setup_logging
from .core.metrics import metrics_payload
from .core.redis import close_redis, init_redis
from .core.security import hash_password
from .core.seed_data import BUILTIN_PERMISSIONS, BUILTIN_ROLES
from .middleware.access_log import ObservabilityMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .models import Base, Permission, Role, User
from .models.department import Department
from .models.knowledge_base import KnowledgeBase
from .models.model_config import ModelConfig
from .services.embedding import embedding_service
from .services.history_retention import history_retention_loop
from .services.langfuse_service import get_langfuse
from .services.llm import guard_llm_service, llm_service, query_processing_llm_service
from .services.query_processing import ensure_query_processing_config
from .services.role_cache import ensure_role_cache_configs, role_cache_loop
from .services.session_expiry import session_expiry_loop


async def _all_permissions(db: AsyncSession) -> list[Permission]:
    return list((await db.scalars(select(Permission))).all())


async def seed_identity_data() -> None:
    """创建/同步内置权限、角色及管理员账号；内置角色权限每次启动对齐种子。"""
    async with SessionLocal() as db:
        existing_codes = {p.code for p in await _all_permissions(db)}
        for code, (name, scope) in BUILTIN_PERMISSIONS.items():
            if code not in existing_codes:
                db.add(Permission(code=code, name=name, description=name, scope=scope))
        await db.flush()

        all_perms = await _all_permissions(db)
        perm_by_code = {p.code: p for p in all_perms}
        roles = {r.name: r for r in (await db.scalars(select(Role).options(selectinload(Role.permissions)))).all()}

        for role_name, (description, codes) in BUILTIN_ROLES.items():
            if role_name not in roles:
                roles[role_name] = Role(name=role_name, description=description, is_builtin=True)
                db.add(roles[role_name])
        await db.flush()

        roles = {r.name: r for r in (await db.scalars(select(Role).options(selectinload(Role.permissions)))).all()}

        # 内置角色权限与描述对齐种子（区分超管/管理员）
        for role_name, (description, codes) in BUILTIN_ROLES.items():
            role = roles.get(role_name)
            if not role:
                continue
            role.description = description
            role.is_builtin = True
            if codes == ["*"]:
                role.permissions = list(all_perms)
            else:
                role.permissions = [perm_by_code[c] for c in codes if c in perm_by_code]

        if not await db.scalar(select(User).where(User.username == "super")):
            db.add(
                User(
                    username="super",
                    email="super@example.com",
                    nickname="超级管理员",
                    hashed_password=hash_password("Super123!"),
                    roles=[roles["super_admin"]],
                )
            )
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
        else:
            # 若旧库 admin 误绑超管能力：保持用户名 admin，角色纠正为 admin（不强制覆盖已有多角色）
            admin_user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.username == "admin"))
            if admin_user and not any(r.name == "admin" for r in admin_user.roles):
                if "admin" in roles:
                    admin_user.roles = [roles["admin"]]

        # 演示员工：带部门，便于上传隔离联调
        if "staff" in roles:
            for uname, email, nick, dept in (
                ("staff_a", "staff_a@example.com", "A部门员工", "A"),
                ("staff_b", "staff_b@example.com", "B部门员工", "B"),
            ):
                existing = await db.scalar(select(User).options(selectinload(User.roles)).where(User.username == uname))
                if not existing:
                    db.add(
                        User(
                            username=uname,
                            email=email,
                            nickname=nick,
                            department=dept,
                            hashed_password=hash_password("Staff123!"),
                            roles=[roles["staff"]],
                        )
                    )
                else:
                    existing.department = existing.department or dept
                    if not any(r.name == "staff" for r in existing.roles):
                        existing.roles = [roles["staff"]]

        # 废弃旧「user」角色：迁移到 guest 后删除（与访客功能重复）
        legacy_user_role = await db.scalar(select(Role).where(Role.name == "user"))
        if legacy_user_role and "guest" in roles:
            from .models.identity import user_roles

            bound_user_ids = (
                await db.scalars(select(user_roles.c.user_id).where(user_roles.c.role_id == legacy_user_role.id))
            ).all()
            for uid in bound_user_ids:
                u = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == uid))
                if not u:
                    continue
                remaining = [r for r in u.roles if r.name != "user"]
                if not any(r.name == "guest" for r in remaining):
                    remaining.append(roles["guest"])
                u.roles = remaining or [roles["guest"]]
            await db.delete(legacy_user_role)

        # 废弃旧「kb_admin」角色：迁移到 staff 后删除（与员工功能重复）
        legacy_kb_admin = await db.scalar(select(Role).where(Role.name == "kb_admin"))
        if legacy_kb_admin and "staff" in roles:
            from .models.identity import user_roles

            bound_user_ids = (
                await db.scalars(select(user_roles.c.user_id).where(user_roles.c.role_id == legacy_kb_admin.id))
            ).all()
            for uid in bound_user_ids:
                u = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == uid))
                if not u:
                    continue
                remaining = [r for r in u.roles if r.name != "kb_admin"]
                if not any(r.name == "staff" for r in remaining):
                    remaining.append(roles["staff"])
                u.roles = remaining or [roles["staff"]]
            await db.delete(legacy_kb_admin)

        await db.commit()


async def seed_departments() -> None:
    """幂等写入固定“访客专用”部门与演示部门 A / B，并迁移历史 public 库。"""
    defaults = (
        (
            GUEST_DEPARTMENT_CODE,
            GUEST_DEPARTMENT_NAME,
            GUEST_DEPARTMENT_DESC,
        ),
        ("A", "A 部门", "负责业务线 A 相关制度与日常协作。"),
        ("B", "B 部门", "负责业务线 B 相关制度与日常协作。"),
    )
    async with SessionLocal() as db:
        for code, name, description in defaults:
            exists = await db.scalar(select(Department).where(Department.code == code))
            if exists:
                if not exists.description:
                    exists.description = description
                if not exists.name:
                    exists.name = name
                continue
            db.add(
                Department(
                    code=code,
                    name=name,
                    description=description,
                    is_enabled=True,
                )
            )
        await db.flush()

        # 迁移：历史 public 知识库归入“访客专用”部门（部门驱动的统一访问控制）
        await db.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.visibility == VISIBILITY_PUBLIC,
                KnowledgeBase.department.is_distinct_from(GUEST_DEPARTMENT_CODE),
            )
            .values(department=GUEST_DEPARTMENT_CODE)
        )
        # 归一化：确保 visibility 与部门一致（GUEST -> public，其余 -> restricted）
        await db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.department == GUEST_DEPARTMENT_CODE)
            .values(visibility=VISIBILITY_PUBLIC)
        )
        await db.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.department.is_distinct_from(GUEST_DEPARTMENT_CODE),
                KnowledgeBase.visibility == VISIBILITY_PUBLIC,
            )
            .values(visibility=VISIBILITY_RESTRICTED)
        )
        await db.commit()


async def seed_model_configs() -> None:
    """从 .env 分类型登记默认模型配置（幂等，不覆盖管理员已有配置）。

    旧实现只要表中存在任意模型就直接返回，因此升级前已经登记 LLM/Embedding 的
    数据库永远不会出现 Rerank。现在按模型类型分别补齐，兼容已有生产数据。
    """
    async with SessionLocal() as db:
        existing_types = set((await db.scalars(select(ModelConfig.model_type).distinct())).all())
        defaults: list[ModelConfig] = []
        if "llm" not in existing_types:
            defaults.append(
                ModelConfig(
                    name="默认 LLM",
                    model_type="llm",
                    provider=settings.LLM_PROVIDER,
                    model_name=settings.LLM_MODEL,
                    base_url=settings.LLM_BASE_URL or None,
                    is_default=True,
                    is_enabled=True,
                    config={"max_tokens": settings.LLM_MAX_TOKENS},
                    timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
                    api_key_env="LLM_API_KEY",
                )
            )
        if "embedding" not in existing_types:
            defaults.append(
                ModelConfig(
                    name="默认 Embedding",
                    model_type="embedding",
                    provider=settings.EMBEDDING_PROVIDER,
                    model_name=settings.EMBEDDING_MODEL_NAME,
                    base_url=settings.EMBEDDING_API_BASE or None,
                    is_default=True,
                    is_enabled=True,
                    config={},
                    timeout_seconds=settings.EMBEDDING_TIMEOUT_SECONDS,
                    api_key_env="EMBEDDING_API_KEY",
                )
            )
        if "rerank" not in existing_types:
            defaults.append(
                ModelConfig(
                    name="Cohere Rerank（默认）",
                    model_type="rerank",
                    provider=settings.RERANK_PROVIDER or "cohere",
                    model_name=settings.RERANK_MODEL or "rerank-v4.0-pro",
                    base_url=settings.RERANK_BASE_URL or "https://api.cohere.ai",
                    is_default=True,
                    is_enabled=True,
                    config={"candidate_multiplier": settings.RERANK_CANDIDATE_MULTIPLIER},
                    timeout_seconds=settings.RERANK_TIMEOUT_SECONDS,
                    api_key_env="RERANK_API_KEY",
                )
            )
        for row in defaults:
            db.add(row)
        await db.commit()


async def seed_role_cache_configs() -> None:
    """为当前所有角色创建默认 7 天周期的缓存知识库配置。"""
    async with SessionLocal() as db:
        await ensure_role_cache_configs(db, commit=True)


async def seed_query_processing_config() -> None:
    """创建全局 Query 预处理默认策略，默认仅启用低成本改写。"""
    async with SessionLocal() as db:
        await ensure_query_processing_config(db, commit=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    get_langfuse()
    # CI/裸库需先装扩展，再 create_all（否则 gin_trgm_ops 索引会失败）
    await ensure_postgres_extensions()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await ensure_schema_patches()
    await seed_identity_data()
    await seed_departments()
    await seed_model_configs()
    await seed_role_cache_configs()
    await seed_query_processing_config()
    await init_redis()
    try:
        init_chroma()
    except Exception:
        # Chroma 暂不可用时不阻断 API 启动（健康检查会标记 degraded）
        pass

    stop_expiry = asyncio.Event()
    expiry_task: asyncio.Task | None = None
    retention_task: asyncio.Task | None = None
    role_cache_task: asyncio.Task | None = None
    # 测试环境不启后台扫描，避免干扰用例与连接生命周期
    if "pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST"):
        expiry_task = asyncio.create_task(session_expiry_loop(stop_expiry), name="session-expiry")
        retention_task = asyncio.create_task(
            history_retention_loop(stop_expiry),
            name="history-retention",
        )
        role_cache_task = asyncio.create_task(
            role_cache_loop(stop_expiry),
            name="role-cache-scheduler",
        )

    yield

    stop_expiry.set()
    if expiry_task is not None:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass
    if retention_task is not None:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
    if role_cache_task is not None:
        role_cache_task.cancel()
        try:
            await role_cache_task
        except asyncio.CancelledError:
            pass

    get_langfuse().flush()
    await llm_service.aclose()
    # 三个模型客户端拥有独立连接池，应用退出时必须分别释放。
    await guard_llm_service.aclose()
    await query_processing_llm_service.aclose()
    await embedding_service.aclose()
    await close_redis()
    close_chroma()
    # pytest 函数级 event loop 下 dispose 全局 engine 会导致后续用例 Event loop is closed
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        await engine.dispose()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.include_router(api_router)
app.include_router(knowledge_bases_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


@app.get("/metrics", tags=["系统监控"], summary="Prometheus 指标端点")
async def metrics() -> Response:
    """Prometheus 刮取入口（无 BaseResponse 包装）。"""
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.get("/", include_in_schema=False)
async def root():
    """根路径重定向到 Swagger 文档。"""
    return RedirectResponse(url="/docs")


@app.get("/api", include_in_schema=False)
async def api_index():
    """API 入口说明。"""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/monitor/health",
        "qa_ask": "POST /api/v1/qa/ask",
    }
