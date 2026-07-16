"""FastAPI 应用入口与身份模块初始数据。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api.v1.knowledge_bases import router as knowledge_bases_router
from .api.v1.router import api_router
from .core.config import settings
from .core.database import SessionLocal, engine
from .core.security import hash_password
from .models import Base, Permission, Role, User


async def seed_identity_data() -> None:
    """创建内置角色、权限及演示超级管理员；已有数据不会被覆盖。"""
    async with SessionLocal() as db:
        permissions = {
            "user:read": "查看用户",
            "user:write": "管理用户",
            "role:read": "查看角色",
            "role:write": "管理角色",
            "snapshot:read": "查看快照历史",
            "snapshot:write": "创建/删除快照",
            "snapshot:restore": "执行快照回退",
            "audit:read": "查看操作审计日志",
            "kb:read": "查看知识库",
            "kb:write": "管理知识库",
            "kb:admin": "知识库管理员",
            "kb:upload": "上传文档到知识库",
            "kb:vectorize": "知识库重新向量化",
            "doc:read": "查看文档与分段",
            "doc:write": "删除/规范化文档",
            "doc:segment": "分段规则与重分段",
            "test:read": "查看命中率测试",
            "test:write": "管理命中率测试",
        }
        existing = {p.code for p in (await db.scalars(select(Permission))).all()}
        for code, name in permissions.items():
            if code not in existing:
                db.add(Permission(code=code, name=name, description=name))
        await db.flush()
        roles = {r.name: r for r in (await db.scalars(select(Role))).all()}
        for name, description in [("超级管理员", "拥有平台全部管理权限"), ("注册用户", "默认注册角色")]:
            if name not in roles:
                roles[name] = Role(name=name, description=description, is_builtin=True)
                db.add(roles[name])
        await db.flush()
        roles["超级管理员"].permissions = list((await db.scalars(select(Permission))).all())
        if not await db.scalar(select(User).where(User.username == "admin")):
            db.add(
                User(
                    username="admin",
                    email="admin@example.com",
                    nickname="超级管理员",
                    hashed_password=hash_password("Admin123!"),
                    roles=[roles["超级管理员"]],
                )
            )
        await db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_identity_data()
    yield
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(knowledge_bases_router, prefix="/api/v1")


@app.get("/api/v1/monitor/health", tags=["系统监控"])
async def health():
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/")
async def root():
    return {"message": f"{settings.APP_NAME} API", "version": settings.APP_VERSION}
