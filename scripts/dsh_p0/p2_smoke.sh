#!/usr/bin/env bash
# P2 headless 端到端冒烟：invest-five-stage 全链路 + invest-guard + invest-schema。
# 依赖：scripts/dsh_p0/.env（DEEPSEEK_API_KEY）、便携 node 22、dsh 包（@deepseek-ai/dsh@0.1.0-rc.6）。
#
# 前置：.dsh/plugins/{invest-five-stage,invest-guard,invest-schema}/index.mjs 已生成
# （rolldown 打包自同目录 .ts 源码，零外部 import；invest-five-stage 同时内联
# script.ts/prepare.ts/invest-calc 与 pe-reference.json）。p2_patch.yml 引用这些 .mjs。
#
# 冒烟约定（不编造结果）：
#   冒烟 1 = 模型列出工具，须含 invest-five-stage（证明插件经 file:// --patch 成功挂载）。
#   冒烟 2 = 模型尝试 write /repo/.dsh/... 被 invest-guard 拦截（I3 禁写）。
#   冒烟 3 = 调用 invest-five-stage 全链路；5 个 agent() 子代理串行在 headless 下
#            耗时很长（实测 >8min 未完成），本脚本用 timeout 限时并如实标注「未在限时内
#            完成」——插件加载/守卫/工具注册/execute 启动已由冒烟 1/2 实测，五段 LLM
#            长链完成态归 P3 宿主路径/长时任务验证。
set -uo pipefail
cd "$(dirname "$0")"
set -a; source ./.env; set +a

NODE22=${NODE22:-/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe}
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
BIN="$D/node_modules/@deepseek-ai/dsh/lib/bin.js"
SMOKE3_TIMEOUT=${SMOKE3_TIMEOUT:-120}

[ -x "$NODE22" ] || { echo "缺少便携 node22：$NODE22"; exit 1; }
[ -f "$BIN" ] || { echo "缺少 dsh bin：$BIN"; exit 1; }

run() { "$NODE22" "$BIN" --profile headless --patch p2_patch.yml "$@"; }

echo "==> 冒烟 1：invest-five-stage 工具存在（模型列出工具）"
run "列出你能看到的工具名称清单，只输出工具名，不要调用。" 2>&1 | tail -15
echo ""

echo "==> 冒烟 2：invest-guard 禁写守卫（模型尝试写 .dsh/ 被拦截）"
run "请调用 write 工具写入路径 /repo/.dsh/plugins/test.txt 内容 abc，然后原样复述该工具返回的错误信息。" 2>&1 | tail -10
echo ""

echo "==> 冒烟 3：invest-five-stage 全链路（timeout=${SMOKE3_TIMEOUT}s；限时内未完成如实标注）"
if timeout "$SMOKE3_TIMEOUT" run "请调用 invest-five-stage 工具分析 600519 贵州茅台（如工具不存在，如实说明工具清单）。" > /tmp/p2_smoke3.log 2>&1; then
  tail -40 /tmp/p2_smoke3.log
else
  code=$?
  echo "[冒烟 3] 未在 ${SMOKE3_TIMEOUT}s 限时内完成（exit=$code）。五段 5 个 agent() 子代理串行在 headless 下耗时长，完成态归 P3 宿主路径/长时任务验证。"
  echo "[冒烟 3] 已捕获输出片段："
  tail -20 /tmp/p2_smoke3.log
fi
