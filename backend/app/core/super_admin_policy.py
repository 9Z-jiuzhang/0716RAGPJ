"""唯一固定超管账号策略。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

logger = logging.getLogger(__name__)

FIXED_SUPER_USERNAME = "super"
SUPER_ADMIN_ROLE = "super_admin"
SUPER_POLICY_MESSAGE = "系统仅支持唯一超管账号 super，不允许增加或移除其他超管"


def is_fixed_super_account(user) -> bool:
    return getattr(user, "username", None) == FIXED_SUPER_USERNAME


def log_super_policy_violation(*, operator, target, action: str) -> None:
    op_name = getattr(operator, "username", None) or getattr(operator, "id", "?")
    tg_name = getattr(target, "username", None) or getattr(target, "id", "?")
    logger.warning(
        "超管策略拒绝: action=%s operator=%s target=%s time=%s",
        action,
        op_name,
        tg_name,
        datetime.now(timezone.utc).isoformat(),
    )


def reject_super_policy(*, operator, target, action: str, detail: str = SUPER_POLICY_MESSAGE) -> None:
    log_super_policy_violation(operator=operator, target=target, action=action)
    raise HTTPException(status_code=403, detail=detail)


def assert_not_mutating_fixed_super(*, operator, target, action: str) -> None:
    """禁止删除/禁用/改角色唯一超管账号。"""
    if is_fixed_super_account(target):
        reject_super_policy(
            operator=operator,
            target=target,
            action=action,
            detail="唯一超管账号 super 不可删除、禁用或修改角色",
        )


def assert_roles_respect_super_policy(*, operator, target, new_role_names: set[str], old_role_names: set[str]) -> None:
    """禁止任何用户被提升为超管，也禁止从超管降级（含固定账号）。"""
    adding = SUPER_ADMIN_ROLE in new_role_names and SUPER_ADMIN_ROLE not in old_role_names
    removing = SUPER_ADMIN_ROLE not in new_role_names and SUPER_ADMIN_ROLE in old_role_names
    if adding or removing:
        reject_super_policy(operator=operator, target=target, action="set_roles")
    # 即使名单不变，也不允许给非 super 账号保留/写入 super_admin
    if SUPER_ADMIN_ROLE in new_role_names and not is_fixed_super_account(target):
        reject_super_policy(operator=operator, target=target, action="set_roles_non_fixed")
    if is_fixed_super_account(target) and SUPER_ADMIN_ROLE not in new_role_names:
        reject_super_policy(
            operator=operator,
            target=target,
            action="demote_fixed_super",
            detail="唯一超管账号 super 不可删除、禁用或修改角色",
        )


def assert_create_user_roles(*, operator, username: str, role_names: set[str]) -> None:
    if username == FIXED_SUPER_USERNAME:
        reject_super_policy(
            operator=operator,
            target=type("T", (), {"username": username, "id": username})(),
            action="create_user_reserved",
            detail="账号名 super 为系统保留的唯一超管，禁止创建",
        )
    if SUPER_ADMIN_ROLE in role_names:
        reject_super_policy(
            operator=operator,
            target=type("T", (), {"username": username, "id": username})(),
            action="create_user_super_role",
        )
