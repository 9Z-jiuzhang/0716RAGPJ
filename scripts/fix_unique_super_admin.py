"""
将非固定账号上的 super_admin 角色降级为 admin（若不存在 admin 角色则降为 guest）。

用法（容器内）:
  python -m scripts.fix_unique_super_admin

或:
  docker compose exec api python -m scripts.fix_unique_super_admin
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 允许直接 python scripts/xxx.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND = ROOT / "backend"
if BACKEND.exists() and str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.core.super_admin_policy import FIXED_SUPER_USERNAME, SUPER_ADMIN_ROLE
from app.models import Role, User


async def main() -> None:
    async with SessionLocal() as db:
        roles = {r.name: r for r in (await db.scalars(select(Role))).all()}
        super_role = roles.get(SUPER_ADMIN_ROLE)
        admin_role = roles.get("admin") or roles.get("guest")
        if not super_role:
            print("未找到 super_admin 角色，跳过")
            return

        users = (
            await db.scalars(select(User).options(selectinload(User.roles)).where(User.roles.any(Role.id == super_role.id)))
        ).all()
        changed = 0
        for user in users:
            if user.username == FIXED_SUPER_USERNAME:
                # 确保固定账号只保留超管角色（可叠加 admin 以外的不强制）
                if not any(r.name == SUPER_ADMIN_ROLE for r in user.roles):
                    user.roles = list(user.roles) + [super_role]
                    changed += 1
                continue
            remaining = [r for r in user.roles if r.name != SUPER_ADMIN_ROLE]
            if admin_role and not any(r.name == admin_role.name for r in remaining):
                remaining.append(admin_role)
            user.roles = remaining
            changed += 1
            print(f"已降级: {user.username} -> {[r.name for r in remaining]}")

        # 确保固定超管存在且绑超管角色
        fixed = await db.scalar(
            select(User).options(selectinload(User.roles)).where(User.username == FIXED_SUPER_USERNAME)
        )
        if fixed and super_role and not any(r.name == SUPER_ADMIN_ROLE for r in fixed.roles):
            fixed.roles = list(fixed.roles) + [super_role]
            changed += 1
            print("已为固定账号 super 补齐 super_admin 角色")

        await db.commit()
        print(f"完成，变更用户数={changed}")


if __name__ == "__main__":
    asyncio.run(main())
