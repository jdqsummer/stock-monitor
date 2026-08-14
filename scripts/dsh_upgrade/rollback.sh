#!/usr/bin/env bash
# DSH 快速回滚（DSH_UPSTREAM.md §5）：lockfile 回退 + 重装 + 验证
set -euo pipefail
TARGET_VERSION="${1:?用法: rollback.sh <old-version>}"
cd "$(git rev-parse --show-toplevel)"
echo "回滚到 ${TARGET_VERSION}："
git checkout HEAD -- dsh-engine/package.json dsh-engine/pnpm-lock.yaml
(cd dsh-engine && pnpm install --frozen-lockfile)
echo "重装完成。验证：docker compose up -d dsh-engine && docker compose logs dsh-engine | tail"
echo "并跑 python scripts/dsh_upgrade/regression.py --baseline ${TARGET_VERSION} 验证行为一致"
