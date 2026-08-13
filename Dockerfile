# stock-monitor/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# pip 镜像源：compose 以 build-arg 注入国内源；未注入时默认官方源
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 让 vendored openharness（/app/vendor）可被 backend 导入（生产运行 LLM 模式必需）
ENV PYTHONPATH=/app/vendor

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
