# FastAPI 后端镜像
# 业务代码实现后，将 app 目录放入镜像并启动 uvicorn
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 构建上下文为项目根目录
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app

EXPOSE 8000

# 注意：框架阶段尚无 app.main，实现后端入口后此命令方可正常启动
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
