"""认证与用户相关展示辅助（供 API 层复用）。"""

from app.core.config import settings
from app.models import User
from app.schemas.identity import TokenResponse, UserResponse


def permission_codes_for(user: User) -> list[str]:
    """汇总用户启用角色下的权限标识（去重排序）。"""
    codes = {p.code for role in user.roles if role.is_enabled for p in role.permissions}
    return sorted(codes)


def present_user(user: User) -> UserResponse:
    """ORM 用户 -> API 响应（含角色名与权限标识）。"""
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        status=user.status,
        roles=[r.name for r in user.roles],
        permissions=permission_codes_for(user),
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
