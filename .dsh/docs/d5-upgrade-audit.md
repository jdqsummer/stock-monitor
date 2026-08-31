# D5 — DSH SDK 升级到 v0.1.2-alpha.2 收尾报告

> 日期：2026-08-31
> 状态：✅ 部署成功 + 容器健康 + 数据源冒烟通过
> 完整方案：`.claude/plans/delegated-churning-owl.md`
> P5 调研：`.dsh/docs/p5-upgrade-audit-v0.1.2-alpha.2*.md`（7 文件）

---

## 一、升级前后对照

| 维度 | 升级前（rc.6） | 升级后（v0.1.2-alpha.2 / 0.1.1rc1） |
|:--|:--|:--|
| npm `@deepseek-ai/dsh*` 4 包 | `0.1.0-rc.6` | `0.1.2-alpha.2` |
| PyPI `deepseek-harness-sdk` | `0.1.0rc6` | `0.1.1rc1`（PyPI 最高） |
| 镜像 hash | `6b7680f29ddc` (2.86 GB) | `b52e875b125f` (2.76 GB, -100MB) |
| 健康检查 `/openapi.json` | 200 OK | 200 OK |
| 容器状态 | healthy | healthy |
| Python SDK 字段集 | 14 字段 | 16 字段（增 `dsh_home`/`profile`/`patches`/`dsh_bin`/`reasoning_effort`） |
| `cordis` 字段 | ✓ | ✗（改 `patches=(...)`） |
| `session_root` 字段 | ✓ | ✗（改 `dsh_home`） |
| 事件 `callId` 字段名 | ✓ | **✓ 保留**（修正 web 报告误读） |
| 监听器 `PostToolDecision` 形状 | `{kind:accept/block,...}` | **✓ 保留** |
| MCP client 入口 | `lib/index.js` | `lib/index.js`（未变） |
| Local tests | 616/616 | 616/616 |

## 二、实际改动文件清单

| 文件 | 改动 |
|:--|:--|
| `dsh-engine/package.json` | 4 个包版本号 `0.1.0-rc.6` → `0.1.2-alpha.2` |
| `dsh-engine/pnpm-lock.yaml` | 重建以匹配新版本（4097 行 / -4508 行） |
| `dsh-engine/Dockerfile` | pip SDK `0.1.0rc6` → `0.1.1rc1` |
| `scripts/dsh_p3/sdk_host.py` | `_build_config` 改字段（`cordis`/`session_root` → `patches`/`dsh_home`） |
| `.dsh/docs/p5-upgrade-audit-v0.1.2-alpha.2*.md` | 7 个 P5 调研报告（新增） |
| `.claude/plans/delegated-churning-owl.md` | 升级方案 + 用户 4 个决策（新增） |

**未改动**（实测 v0.1.2 兼容）：
- `backend/agents/dsh_events.py`（callId 字段名未变）
- `.dsh/plugins/invest-guard/index.mjs`（PostToolDecision 形状未变）
- `.dsh/plugins/invest-schema/index.mjs`（同 invest-guard）
- `.dsh/plugins/invest-telemetry/index.mjs`（pre-execute 兼容）
- `.dsh/plugins/invest-five-stage/index.mjs`（`ctx.tools.register` 原始注册实测兼容）
- `.dsh/agent-presets/value-investor/cordis.standalone.yml`（mcp-client 入口未变）
- `.dsh/skills/*` 8 个 SKILL.md（SDK 不读这些文件）
- 所有测试 fixture（callId 字段名未变）

## 三、关键 P5 发现（修正 web 报告）

1. **`callId` 字段名未变**：web 报告称"wire JSON `data.callId` 改名 `data.toolCallId`"，但实测 `packages/llm/llm/src/message.ts:235` 仍是 `source: { kind: 'tool', callId: input.callId }`。`ToolCallId` 仅是 TS brand type 重命名，编译期类型，Python 端无感知。
2. **`PostToolDecision` 形状未变**：canonical guard 仍是 `{kind:'accept'/'block', additionalContexts}` 模式，项目 invest-guard 现有代码完全兼容。
3. **本项目实际只有 1 个真实 BC**（Python SDK Config 字段重塑），不是 web 报告的 4 个。

## 四、部署关键节点

| 步骤 | 结果 |
|:--|:--|
| 备份 dsh-engine 镜像为 `rc6-fallback` | ✅ 同 hash `6b7680f29ddc` 保留 |
| 清空 `stock-monitor_dsh_sessions` 卷 | ✅ RC.8 SQLite 格式不兼容 → 升级前清空 |
| 服务器 `docker compose up -d --build` | ✅ 全栈重建成功 |
| app 容器健康 | ✅ healthy |
| dsh-engine 容器健康 | ✅ healthy (port 8001) |
| 数据源冒烟 | ✅ 腾讯/东财/mock 链全通（600519 茅台 1299.52）|
| 本地测试 616/616 | ✅ 5分22秒全过 |

## 五、紧急回退预案

如升级后出现任何 5xx 飙升、invest-guard/invest-schema 抛错、五段提取 silent fail 等问题：

```bash
# SSH 到 49.232.171.206
cd /home/ubuntu/stock-monitor
docker compose down dsh-engine
docker compose up -d dsh-engine:rc6-fallback
# 5min 内回退到 rc.6 镜像
```

回退后 services 仍正常；dsh_sessions 卷会重建（清空）。

## 六、已知问题 / 待观察

1. **npm/pip 跨主版本错配**：npm 0.1.2-alpha.2 + pip 0.1.1rc1，**目前 Phase 1-2 验证通过**（启动 + 数据源），但**真实五段分析在生产首次触发时**需密切观察（按 Plan 阶段 3 e2e 验证）。
2. **OpenRouter free model 路由**：升级后未实测。建议在低峰期手动触发一次 openrouter:minimax/minimax-m3:free 真实分析验证。
3. **生产 sessions 卷已清空**：所有历史会话日志丢失（按计划清空，不影响用户数据）。

## 七、待办（生产运行 24h 后）

- [ ] 24h 后观察 `analysis_degraded` 比例（应 < 5%）
- [ ] 7 天后观察 dsh-engine 容器内存（应 < 1.5 GB）
- [ ] 30 天后清理 `rc6-fallback` 镜像
- [ ] 上游出 `0.1.2` stable 时考虑再升（如果届时 npm 通道未变）
