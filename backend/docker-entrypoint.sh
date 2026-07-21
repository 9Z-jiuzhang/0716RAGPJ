#!/bin/sh
# 容器启动入口：执行数据库迁移后启动 Uvicorn
set -e

cd /app

# Alembic 迁移（幂等；与 lifespan create_all 并存）
if [ -f "alembic.ini" ]; then
  echo "[entrypoint] 执行 Alembic 迁移..."
  alembic -c alembic.ini upgrade head || echo "[entrypoint] 迁移跳过或已是最新"
fi

echo "[entrypoint] 启动 FastAPI..."
# 透传 compose command（如 --workers 2）；无参数时单进程启动
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
