#!/usr/bin/env bash
set -euo pipefail
# 启动 dsh-engine SDK 宿主（HTTP 触发端点，sdk_host.py）。容器重建不丢会话日志（dsh_sessions 卷）。
cd /app
export DSH_ENGINE_PORT="${DSH_ENGINE_PORT:-8001}"

# S3 会话日志留存清理：后台循环（缺省每 24h 一次），不阻塞 /trigger 服务。
# 用 --apply 实际删除；间隔经 DSH_CLEANUP_INTERVAL_SECONDS 可配（0 或负 = 仅单次）。
# 不在 compose 用 command: 覆盖（会跳过 entrypoint → 破坏 /trigger 服务），此处并入 entrypoint 启动。
DSH_SESSION_ROOT="${DSH_SESSION_ROOT:-/app/sessions}"
nohup python3 /app/scripts/dsh_p3/session_cleanup.py \
  --root "${DSH_SESSION_ROOT}" \
  --days "${DSH_SESSION_RETENTION_DAYS:-90}" \
  --max "${DSH_SESSION_MAX_COUNT:-10000}" \
  --apply \
  --interval "${DSH_CLEANUP_INTERVAL_SECONDS:-86400}" \
  > /app/session_cleanup.log 2>&1 &

exec python3 /app/scripts/dsh_p3/sdk_host.py
