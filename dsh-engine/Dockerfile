# dsh-engine/Dockerfile — DSH SDK 宿主容器（Node 22 + Python SDK host 同容器运行）
#
# 拓扑：sdk_host.py（FastAPI /trigger）在容器内 spawn DeepSeekHarness（Python SDK），
# SDK 再 spawn deepseek-harness-runtime-bin 的单文件 dsh-jsonrpc-agent exe —— 三者同容器，
# 不能拆成「backend + 独立 headless」两个容器（SDK 无远程连接能力，仅 stdio JSON-RPC）。
#
# 基座选 node:22（Debian bookworm / glibc 2.36）而非 node:22-alpine：
#   deepseek-harness-runtime-bin 0.1.0rc6 仅发布 manylinux_2_28_x86_64/aarch64 wheel，
#   需 glibc>=2.28（无 musllinux wheel）；且 requirements.txt 含 uvicorn[standard]
#   （uvloop/httptools/watchfiles）等编译型依赖，glibc 下走 manylinux wheel 免编译。
FROM node:22

WORKDIR /app

# 国内 npm 镜像（默认官方源，其他环境不受影响）
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY

# 国内 pip 镜像（默认官方源，其他环境不受影响）。
# 生产 compose 传入腾讯镜像：直连 pypi.org 的 57MB runtime-bin wheel 下载会长期停滞
# （连接 ESTABLISHED 但 rxq=0 无数据，pip 无读超时无限挂起），腾讯镜像下载秒级完成。
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL

# pnpm（corepack）—— 固定 10.22.0（与本地生成 lockfile 的版本一致）。
# 勿用 @latest：新版 pnpm 默认启用 minimumReleaseAge 策略，会拒绝 lockfile 中
# 24h 内新发布的传递依赖（如 @smithy/*），导致 frozen-lockfile 构建非确定性失败。
RUN corepack enable && corepack prepare pnpm@10.22.0 --activate

# 锁文件优先安装（frozen-lockfile，禁 ^/~ 漂移）
COPY dsh-engine/package.json dsh-engine/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Python 运行时：sdk_host.py 依赖 fastapi/pydantic/uvicorn + backend 包 + deepseek-harness SDK
# 用 venv 规避 Debian bookworm 的 PEP 668（externally-managed-environment）
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

# backend 依赖：sdk_host.py `from backend.agents.dsh_events import ...` 会触发
# backend/agents/__init__ 全量导入链（analysis_chain/constraints/data_agent/... → langgraph 等）
COPY requirements.txt ./requirements.txt
# deepseek-harness-sdk 提供 `deepseek_harness` 模块（sdk_host.py 的 import 目标），
# 并透传依赖 deepseek-harness-runtime-bin（单文件 runtime exe 载体）。精确锁 rc.6。
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/pip install --no-cache-dir "deepseek-harness-sdk==0.1.0rc6"

# backend 包（sdk_host.py 复用 backend/agents/dsh_events 纯函数）
COPY backend /app/backend

# 插件 + skills + agent-presets + 宿主脚本
COPY .dsh /app/.dsh
COPY scripts/dsh_p3 /app/scripts/dsh_p3
COPY dsh-engine/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 数据卷：skills 热更新 + 会话日志（S3 留存载体）。I3 只读挂载在 compose 中以 :ro 体现。
VOLUME ["/app/.dsh/skills", "/app/sessions"]

# sdk_host.py 以脚本运行（sys.path[0]=/app/scripts/dsh_p3），需 PYTHONPATH=/app 使 backend 可 import
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/app
ENV DSH_CORDIS_CONFIG=/app/.dsh/agent-presets/value-investor/agent.cordis.yml
ENV DSH_SESSION_ROOT=/app/sessions
EXPOSE 8001
CMD ["bash", "/app/entrypoint.sh"]
