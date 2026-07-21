"""认证与用户相关展示辅助（供 API 层复用）。"""

from app.core.config import settings
from app.core.seed_data import ROLE_DISPLAY_NAMES
from app.models import User
from app.schemas.identity import LoginResponse, TokenResponse, UserResponse

# 角色等级：越高权限越大。操作者仅可管理/删除等级严格低于自己的用户。
ROLE_RANK: dict[str, int] = {
    "super_admin": 100,
    "admin": 50,
    "staff": 20,
    "kb_admin": 20,
    "guest": 10,
    "user": 10,
}


def role_rank(name: str) -> int:
    return ROLE_RANK.get(name, 5)


def max_role_rank(user: User) -> int:
    names = [r.name for r in (user.roles or []) if r.is_enabled]
    if not names:
        return 0
    return max(role_rank(n) for n in names)


def permission_codes_for(user: User) -> list[str]:
    """汇总用户启用角色下的权限标识（去重排序）。"""
    codes = {p.code for role in user.roles if role.is_enabled for p in role.permissions}
    return sorted(codes)


def role_names_for(user: User) -> list[str]:
    return [r.name for r in user.roles if r.is_enabled]


def is_super_admin_user(user: User) -> bool:
    from app.core.super_admin_policy import is_fixed_super_account

    return is_fixed_super_account(user)


def is_platform_admin_user(user: User) -> bool:
    """超级管理员或普通管理员：平台级知识库/管理能力。"""
    names = {r.name for r in user.roles if r.is_enabled}
    if "super_admin" in names or "admin" in names:
        return True
    codes = permission_codes_for(user)
    return "*" in codes or "admin:*" in codes


def display_name_for_role(name: str) -> str:
    return ROLE_DISPLAY_NAMES.get(name, name)


def present_user(user: User) -> UserResponse:
    """ORM 用户 -> API 响应（含角色名与权限标识）。"""
    roles = role_names_for(user)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        status=user.status,
        roles=roles,
        role_labels=[display_name_for_role(n) for n in roles],
        permissions=permission_codes_for(user),
        department=getattr(user, "department", None),
        is_super_admin=is_super_admin_user(user),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def build_token_response(access_token: str, refresh_token: str) -> TokenResponse:
    """构造令牌响应，附带 access_token 有效秒数。"""
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def resolve_login_landing(user: User) -> tuple[str, str]:
    """统一登录后的前端分流：平台管理员进控制台，其余进问答端。"""
    if is_platform_admin_user(user):
        return "admin", "/admin/"
    return "app", "/#/chat"


def build_login_response(user: User, access_token: str, refresh_token: str) -> LoginResponse:
    """访客与管理员共用同一登录接口的完整响应。"""
    token = build_token_response(access_token, refresh_token)
    landing, landing_href = resolve_login_landing(user)
    return LoginResponse(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_type=token.token_type,
        expires_in=token.expires_in,
        user=present_user(user),
        landing=landing,
        landing_href=landing_href,
    )
