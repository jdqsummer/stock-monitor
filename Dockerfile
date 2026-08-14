# stock-monitor/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# pip 镜像源：compose 以 build-arg 注入国内源；未注入时默认官方源
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 精确 COPY：backend 运行所需的最小顶层目录/文件（避免带入 .dsh/scripts/docs/frontend 等）
# - backend/：FastAPI 应用 + agents + data + services（main.py 内 import 全部落在 backend 包内）
# - alembic/ + alembic.ini：`alembic upgrade head` 迁移建表（compose command 首步）
COPY backend/ /app/backend/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
