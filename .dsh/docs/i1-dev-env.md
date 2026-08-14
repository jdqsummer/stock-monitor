# I1 开发环境方案（WSL2 / Docker / fake-runtime 三路径）

> 状态：P1 方案定稿 · 日期：2026-08-14 · 计划：`2026-08-14-dsh-p1-assets-migration.md` 章节十四组③ I1
> 阶段定位：**P1 只定开发环境联调方案与命令清单**；生产双容器 compose 在 P4 落地。本文档固化三路径结论与可执行命令，配套命令清单见 `.dsh/scripts/dev-env.md`。

## 一、结论先行（P0 T6 事实，已固化）

DSH Python SDK 的 runtime 是**单文件 exe（`dsh-jsonrpc-agent`）**，官方仅发布 linux/macos x64/arm64 四种产物，**无 Windows（win32）产物**——本机 Windows 直接拉起默认 bundled runtime 抛 `FileNotFoundError`（实测报错原文：`no bundled dsh-jsonrpc-agent executable exists for this platform (sys.platform='win32', machine='AMD64'); supported: linux/macos on x64/arm64`）。

> **P0 T6 依据**（引用 `docs/superpowers/plans/2026-08-14-dsh-p0-report.md` 一/四节 + `scripts/dsh_p0/t6_sdk/bridge_test.py`）：
> - SDK 唯一 transport = `subprocess.Popen` + stdio **NDJSON JSON-RPC**（`JsonRpcLineTransport`），**无 TCP/HTTP/socket**，不存在「连接已运行进程（进程外）」的入口。
> - `runtime_bin` + `launch_args_override` 只是「SDK 自己 spawn 的子进程」的 **argv 变体**，不是独立连接方式。
> - `DeepSeekHarnessConfig` 14 字段：`provider / model / max_tokens / cwd / runtime_cwd / session_root / cordis / env / runtime_bin / launch_args_override / request_timeout_seconds / shutdown_timeout_seconds / base_url / api_key`。

由此派生的关键区分（Windows 可用性）：

| 能力 | Windows 可用性 | 依据 |
|:--|:--|:--|
| **CLI headless**（`npx dsh --profile headless`） | ✅ 可直接跑 | P0 T2 已验证（纯 Node 进程，不依赖 runtime exe） |
| **SDK runtime**（`DeepSeekHarness` spawn 单文件 exe） | ❌ 需 linux/macos | P0 T6：win32 `FileNotFoundError` |

即：**「用 DSH」有两条路**——CLI headless 在 Windows 直接可用；SDK（Python 集成面）需要 linux runtime。本机 Windows 联调 SDK 走下面三路径。

## 二、三路径总览

| 路径 | 用途 | 真实度 | 落地时点 |
|:--|:--|:--|:--|
| ① WSL2 内跑 DSH runtime | 真实链路（SDK + 真 runtime + 真 LLM） | 真实 | P1 起可用 |
| ② Docker linux 容器跑 `dsh-engine` | 生产同构（与 P4 双容器拓扑一致） | 真实 + 同构 | P3/P4 主线 |
| ③ win32 用 `fake_runtime.py` | 协议级单测（SDK 调用契约，无需真实 exe/LLM） | 模拟 | 已有（P0 建成） |

三路径互补、不互斥：③ 用于日常不依赖真实 LLM 的协议/契约单测；① 用于本机快速真实联调；② 用于验证生产同构拓扑（SDK 宿主 + 运行时同容器 + HTTP 触发）。

## 三、路径 ①：WSL2 内跑 DSH runtime（真实链路）

**原理**：SDK runtime exe 是 linux x64 产物，在 WSL2（Ubuntu 等 linux 发行版）内可直接运行。把「Python SDK 宿主 + `DeepSeekHarness` + 真 runtime exe + 真 LLM」整套放 WSL2 内，FastAPI/前端仍在 Windows 照常开发——本机快速真实联调的最小成本方案。

**真实链路组件**（与 bridge_test 同构，但去掉 `runtime_bin` 覆写、走默认 bundled exe）：

```python
# 在 WSL2 内运行（linux 环境，Node ≥ 22.15 + deepseek-harness-sdk 已装）
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-flash",
    api_key="<DEEPSEEK_API_KEY>",   # 或经环境变量注入
    base_url=None,                   # 走公共 API
) as harness:
    r = harness.run("分析 600519 的安全边际", session_id="600519-2026-08-14")
    print(r.final_response)
```

> 与路径 ③ 的差异：路径 ③ 用 `runtime_bin=sys.executable + launch_args_override=(python, fake_runtime.py)` 覆写 argv 指向本地假 runtime；路径 ① 不覆写，SDK 默认解析并 spawn 真实的 bundled `dsh-jsonrpc-agent` exe——这是「真实链路」与「协议级模拟」的本质区别。

**WSL2 内环境准备**（示意，待本机落地验证，关键门槛与生产一致）：

```bash
# WSL2 (Ubuntu) 内
# 1) Node ≥ 22.15（zstd 硬门槛，P0 裁决）
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt install -y nodejs
# 2) Python SDK（或复用本机 deepseek-harness 源码 clone，bridge_test 同款 sys.path 方式）
pip install deepseek-harness-sdk
# 3) 写入 API Key
export DEEPSEEK_API_KEY=...
```

## 四、路径 ②：Docker linux 容器跑 dsh-engine（生产同构）

**原理**：生产拓扑（P0 第四节已坐实）是「容器内 SDK 宿主 + HTTP 触发」——SDK 的 `HarnessClient.start()` 固定 `subprocess.Popen`，唯一 transport = stdio NDJSON JSON-RPC，**无进程外 transport**，故「SDK 宿主」与「dsh-engine 运行时」**天然同容器、不可拆**。本地开发起一个 linux 的 `dsh-engine` 容器即可复现生产拓扑。

**生产同构拓扑**（P0 第四节结论，P4 落地 compose，此处为结构示意）：

```
┌ backend 容器（FastAPI，Windows 本机直接跑，不依赖 DSH runtime）──────────┐
│  Orchestrator：HTTP 触发 dsh-engine 容器 → 收集结果 → 回填落库          │
└──────────────── HTTP 触发（无 SDK 跨容器连接）──────────────────────────┘
                        │
┌ dsh-engine 容器（Node 22 ≥ 22.15，SDK 宿主 + runtime 同容器）───────────┐
│  Python SDK host：DeepSeekHarness（spawn 单文件 exe）                   │
│   ├─ dsh-jsonrpc-agent（= headless 常驻，被 SDK 持有）                 │
│   ├─ 自定义 cordis.yml（value-investor 组合 + mcp-client）             │
│   └─ 对 backend 暴露一个 HTTP 触发端点                                  │
└────────────────────────────────────────────────────────────────────────┘
```

**容器化关键点**（P0 裁决，P4 落地时遵守）：

- Node 生产镜像须 **≥ 22.15.0**（`node:zlib` 的 zstd 导出硬门槛，本机 22.14.0 启动即崩）。
- `@deepseek-ai/dsh@0.1.0-rc.6` 精确锁定（禁 `^`/`~`）+ `pnpm-lock.yaml` + `frozen-lockfile`。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 经环境变量注入容器。
- DataBridge MCP 跨容器走 `streamable-http`（同容器 stdio 已实测跑通，见 Task 10 S1）。

> 本地联调用法：`docker compose up dsh-engine` 起容器后，Windows 上的 FastAPI 经 HTTP 触发容器端点，与生产拓扑一致。compose 卷声明（`.dsh/plugins/`、`.dsh/skills/` read-only）见 `.dsh/docs/i3-script-tamper.md`。

## 五、路径 ③：win32 用 fake_runtime.py（协议级单测）

**原理**：P0 已建成 `scripts/dsh_p0/t6_sdk/fake_runtime.py`——一个最小 stdio NDJSON JSON-RPC 运行时，只实现 SDK `HarnessClient` + `Session.run()` 依赖的最小线协议（`initialize` / `session/prompt` / `shutdown` + 通知 `session.event` / `session.status`），**无需真实 exe、无需真实 LLM**，证明：

1. SDK 是「进程内」模型——`HarnessClient.start()` 总是 `subprocess.Popen` 一个子进程，经 stdin/stdout 走 NDJSON JSON-RPC。
2. 线协议方法 = `initialize` / `session/prompt` / `shutdown` + 通知。
3. `session_id` 复用——同一 sessionId 连续两次 `session/prompt`，上下文延续（turn 计数递增）。

**驱动方式**（`bridge_test.py` 把 fake_runtime 作为 `runtime_bin` 拉起）：

```python
with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-flash",
    runtime_bin=sys.executable,
    launch_args_override=(sys.executable, fake_runtime_path),  # 覆写 argv → python fake_runtime.py
) as harness:
    r1 = harness.run("第一轮", session_id="p0-probe-1")
    r2 = harness.run("第二轮", session_id="p0-probe-1")   # 断言 turn=2（复用）
```

**可执行命令**（win32 直接跑，见 `.dsh/scripts/dev-env.md` 第 1 节）。

## 六、CLI headless（Windows 直跑，P0 T2 已验证）

区分「SDK runtime 需 linux」与「CLI headless 无需 linux」：**`npx dsh --profile headless` 是纯 Node 进程**，不依赖 runtime exe，Windows 直接可用（P0 T2 已验证）。P1 各任务的 skill 加载自检 / 插件冒烟都用它，无需 WSL2/Docker。

> ⚠️ 本机系统 node 为 22.14.0（< 22.15，zstd 硬门槛，启动即崩），P0 用便携 `node@22.23.2` 直跑 bin.js 绕过。可执行命令见 `.dsh/scripts/dev-env.md` 第 2 节。

## 七、附注：本地构建 exe（第四种可能，P0 T6 报错原文提及）

`FileNotFoundError` 的报错原文给出两条「拿到 linux exe 之外」的出路，供需要本机真实 runtime（不走 WSL2/Docker）时参考，**非 P1 主路径**：

1. **源码构建**：在 `deepseek-harness` checkout 里跑 `scripts/build-exe-for-python-sdk.ts`（经 tsx）构建 node closure。
2. **dev-only node carrier**：本地对 repo 源码构建时显式选 `DSH_RUNTIME_MODE=node`（或 `resolve_bundled_launch_args('node')`）走 node carrier 而非 bundled exe。

> 两者都需要 `deepseek-harness` 源码（本机已 clone 于 `scripts/dsh_p0/deepseek-harness/`），但构建/验证成本高于路径 ①③，P1 不展开，仅记录入口。

## 八、P1 交付边界（不动 `backend/`）

- 本文档只定开发环境方案与命令清单，**不实现** docker-compose（P4）、**不实现** Orchestrator HTTP 触发（P3）、**不改** `backend/` 任何代码。
- `fake_runtime.py` / `bridge_test.py` 已存在于 `scripts/dsh_p0/t6_sdk/`（P0 资产），本任务不修改、不移动，仅在本文档引用。
- 仅新增资产：本文档 + `.dsh/scripts/dev-env.md`。
