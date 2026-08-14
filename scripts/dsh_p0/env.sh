#!/usr/bin/env bash
# 环境检查：Node / pnpm / DSH 可执行 / DeepSeek Key
set -euo pipefail
echo "node: $(node --version 2>/dev/null || echo MISSING)"
echo "pnpm: $(pnpm --version 2>/dev/null || echo MISSING)"
echo "npx dsh: $(npx --yes @deepseek-ai/dsh --version 2>/dev/null || echo MISSING)"
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "DEEPSEEK_API_KEY: MISSING"
else
  echo "DEEPSEEK_API_KEY: set (prefix ${DEEPSEEK_API_KEY:0:6}...)"
fi
