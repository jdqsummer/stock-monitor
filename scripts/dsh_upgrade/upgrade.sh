#!/usr/bin/env bash
# DSH_UPSTREAM 六步升级流水线（对标 docs/股票WEB监控系统/DSH_UPSTREAM.md §2.3）
set -euo pipefail
TARGET_VERSION="${1:?用法: upgrade.sh <new-version> [--dry-run]}"
DRY="${2:-}"
cd "$(git rev-parse --show-toplevel)"

echo "① 备份：git tag + 会话日志基线导出"
[ "$DRY" = "--dry-run" ] || git tag "dsh-before-${TARGET_VERSION}" >/dev/null 2>&1 || true

echo "② 读变更：打开上游 changelog 人工审查（阻断点）"
echo "   请确认 DSH_UPSTREAM.md §3 冲突点清单逐项检查后再继续 [Enter]"
[ "$DRY" = "--dry-run" ] || read -r -p "回车继续 / Ctrl-C 中止: "

echo "③ 测试升级：测试环境精确版本 + frozen-lockfile"
if [ "$DRY" != "--dry-run" ]; then
  (cd dsh-engine && pnpm add "@deepseek-ai/dsh@${TARGET_VERSION}" --lockfile-only && pnpm install --frozen-lockfile)
fi

echo "④ 回归集：python scripts/dsh_upgrade/regression.py"
[ "$DRY" = "--dry-run" ] || python scripts/dsh_upgrade/regression.py --baseline "${TARGET_VERSION}"

echo "⑤ 双轨对比：python scripts/dsh_upgrade/dual_track.py"
[ "$DRY" = "--dry-run" ] || python scripts/dsh_upgrade/dual_track.py --new "${TARGET_VERSION}"

echo "⑥ 灰度/回滚：通过则切流；失败执行 scripts/dsh_upgrade/rollback.sh ${TARGET_VERSION}"
echo "完成。回填 DSH_UPSTREAM.md §6 版本追踪表。"
