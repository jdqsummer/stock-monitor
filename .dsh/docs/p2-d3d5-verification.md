# D3 内置守卫 + D5 上下文压缩 验证结论（P2）

> 日期：2026-08-14 ｜ 依据：P0/P0-1 报告 + DSH 源码交叉验证（Explore 结果）

## D3 内置守卫（组④ P2）

设计文档「D3 内置守卫（循环卫生 + 工具超时，零依赖两行配置）」经源码核实：

| 设计名 | 真实 cordis 插件名 | npm 包名 | base 内置 |
|:--|:--|:--|:--|
| 循环卫生守卫 | `repeat-tool-reminder` | `@deepseek-ai/dsh-repeat-tool-reminder` | ✅ 已内置（thresholds [3,5,8]） |
| 工具超时守卫 | `timeout-policy` | `@deepseek-ai/dsh-tool-call-timeout-policy` | ✅ 已内置（从工具 timeoutMs 取预算） |

结论：**零自研代码**。两守卫已在 base preset 默认挂载，P2 仅需确认 + 文档。
repeat-tool-reminder 是 advisory（post-execute 注入模型上下文提醒重复调用，不否决）；
timeout-policy 超时返回 isError + code=TOOL_TIMEOUT（触发降级/重试）。

## D5 上下文压缩（组④ P2）

设计文档「D5 上下文压缩（窗口 80% 触发）」经源码核实：

| 层 | npm 包名 | cordis 插件名 | 默认 |
|:--|:--|:--|:--|
| 自动触发 | `@deepseek-ai/dsh-compaction-basic` | `compaction-basic` | ✅ 已内置，thresholdRatio=0.8 |
| 手动 | `@deepseek-ai/dsh-command-compact` | `command-compact` | 已内置 |
| 工具结果剪枝 | `@deepseek-ai/dsh-compaction-tool-result-pruner` | `tool-result-pruner` | 已内置 |

结论：**零自研代码**。窗口 80% 正好是 compaction-basic 默认 thresholdRatio=0.8。
若需显式覆盖（如收紧到 0.75），在 cordis.yml 给 compaction-basic 加
`config: { thresholdRatio: 0.75 }`；P2 维持默认。

## 验证命令与输出

验证命令（headless profile，config-only，不调用 LLM）：

```bash
cd scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless --dump-config 2>&1 | grep -iE "repeat-tool-reminder|timeout-policy|compaction-basic|tool-call-timeout|threshold"
```

实测输出（2026-08-14，grep 命中行；`--dump-config` 可用且未调用 LLM）：

```
- id: compaction-basic
  name: '@deepseek-ai/dsh-compaction-basic'
- id: command-compact
  name: '@deepseek-ai/dsh-command-compact'
- id: timeout-policy
  name: '@deepseek-ai/dsh-tool-call-timeout-policy'
- id: tool-result-pruner
  name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
- id: repeat-tool-reminder
  name: '@deepseek-ai/dsh-repeat-tool-reminder'
    thresholds:
      - 3
      - 5
      - 8
```

源码交叉验证（与 dump 一致，双证据）：

- base preset 挂载点：`scripts/dsh_p0/deepseek-harness/packages/bundle/base/cordis.patch.yml`
  L284-391，五个插件均以「无 config」行挂载 → 全部走默认值。
- `DEFAULT_THRESHOLD_RATIO = 0.8`：
  `packages/compaction/compaction-basic/src/config.ts:20`；
  L74 `const thresholdRatio = config.thresholdRatio ?? DEFAULT_THRESHOLD_RATIO`。
- `repeat-tool-reminder` 默认阈值由运行时 dump 直接给出 `[3, 5, 8]`（与设计文档一致）。

结论：`--dump-config` 实测 + vendored 源码双向确认五个插件已内置 base preset 且
维持默认值，P2 无需注册、无需显式 config 覆盖 → **零自研代码成立**。
