#!/bin/sh
# 容器启动入口：探测数据库 → Alembic 迁移 → 启动 Uvicorn
set -e

cd /app

echo "[entrypoint] 检查 PostgreSQL 连接..."
python - <<'PY'
import asyncio
import os
import sys

async def probe() -> None:
    import asyncpg

    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "kb_user")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "knowledge_base")
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=5,
        )
        await conn.close()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "password" in msg or "authentication failed" in msg or "invalidpassword" in msg:
            print("=" * 50, file=sys.stderr)
            print("PostgreSQL 密码认证失败！", file=sys.stderr)
            print("可能原因：.env 中 POSTGRES_PASSWORD 与数据卷中密码不一致", file=sys.stderr)
            print("", file=sys.stderr)
            print("解决方案（二选一）：", file=sys.stderr)
            print("1. 手动同步密码：", file=sys.stderr)
            print(
                f"   docker exec <postgres容器> psql -U {user} -d {database} "
                f"-c \"ALTER USER {user} PASSWORD '<新密码>';\"",
                file=sys.stderr,
            )
            print("2. 重置数据库（会丢失数据）：", file=sys.stderr)
            print("   docker compose down -v && docker compose up -d", file=sys.stderr)
            print("=" * 50, file=sys.stderr)
            sys.exit(1)
        print(f"[entrypoint] 数据库暂不可达：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

asyncio.run(probe())
print("[entrypoint] 数据库连接成功")
PY

# Alembic 迁移（幂等；与 lifespan create_all 并存）
if [ -f "alembic.ini" ]; then
  echo "[entrypoint] 执行 Alembic 迁移..."
  alembic -c alembic.ini upgrade head || echo "[entrypoint] 迁移跳过或已是最新"
fi

echo "[entrypoint] 启动 FastAPI..."
# 透传 compose command（如 --workers 2 / --reload）；无参数时单进程启动
exec uvicorn app.main:app --host 0.0.0.0 --port 9081 "$@"
