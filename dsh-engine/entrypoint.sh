#!/usr/bin/env bash
set -euo pipefail
# 启动 dsh-engine SDK 宿主（HTTP 触发端点，sdk_host.py）。容器重建不丢会话日志（dsh_sessions 卷）。
cd /app
export DSH_ENGINE_PORT="${DSH_ENGINE_PORT:-8001}"
exec python3 /app/scripts/dsh_p3/sdk_host.py
