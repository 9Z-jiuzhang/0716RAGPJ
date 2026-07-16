"""V1 路由总入口。"""
from fastapi import APIRouter
from .auth import router as auth_router
from .roles import router as roles_router
from .users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
