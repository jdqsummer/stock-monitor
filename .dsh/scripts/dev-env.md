# 开发环境联调命令清单

> 状态：P1 命令清单 · 日期：2026-08-14 · 配套方案：`.dsh/docs/i1-dev-env.md`
> 约定：✅ = P0 已验证、win32 直接可执行；🔶 = 方案示意，待 WSL2/Docker 落地后验证。涉及真实 LLM 的命令需先 `source scripts/dsh_p0/.env`（注入 `DEEPSEEK_API_KEY`）。

## 0. 公共环境变量

本机便携 node（`node@22.23.2`，系统 node 22.14.0 < 22.15 会因 zstd 崩溃）与 DSH 包目录（pnpm 隔离安装）：

```bash
# 便携 node（win32 直接可用）
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe

# DSH 包目录（含 lib/bin.js；find 避免硬编码 pnpm 哈希后缀）
D=$(find scripts/dsh_p0/node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
```

## 1. 路径③ fake-runtime 协议级单测 ✅

win32 直接跑，无需真实 exe / 真实 LLM。验证 SDK 的「进程内 spawn + stdio JSON-RPC + session_id 复用」调用契约。

```bash
cd /d/project/github/stock-monitor/scripts/dsh_p0/t6_sdk
python bridge_test.py
```

预期输出（四段）：

1. `DeepSeekHarnessConfig` 14 字段打印。
2. 进程内连接：`run#1 turn=1` → `run#2 turn=2`（同 session_id 复用延续）→ `run#3 turn=1`（新会话），收尾 `✅ SDK 进程内 spawn + stdio JSON-RPC + session_id 复用均验证通过`。
3. 进程外能力判定：默认 bundled runtime 启动失败（**预期**）——`FileNotFoundError: no bundled dsh-jsonrpc-agent executable ... supported: linux/macos on x64/arm64`。
4. 源码结论：唯一 transport = `subprocess.Popen` + stdio NDJSON JSON-RPC，`runtime_bin`/`launch_args_override` 只是 spawn argv 变体。

## 2. CLI headless 直跑 ✅

win32 直接跑（纯 Node 进程，不依赖 runtime exe）。P0 T2 已验证。用途：skill 加载自检 / 插件冒烟 / 真实 LLM 问答。

```bash
cd /d/project/github/stock-monitor/scripts/dsh_p0 && set -a && source ./.env && set +a
NODE22=/c/Users/SXF-Admin/AppData/Local/Temp/dsh-node22/node_modules/node/bin/node.exe
D=$(find node_modules/.pnpm -maxdepth 1 -type d -name "@deepseek-ai+dsh@*" | head -1)
"$NODE22" "$D/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile headless \
  "列出你能看到的 skill 名称（只调用 skill 工具，禁止读文件）" 2>&1 | tail -30
```

> `npx dsh --profile headless "..."` 是等价规范形式，但要求 node ≥ 22.15；本机系统 node 不满足，故 P0 固定用「便携 node + 直跑 bin.js」形式（上命令）。

## 3. 路径① WSL2 真实链路 🔶

在 WSL2（linux）内跑 SDK 真实链路（SDK + 真 runtime exe + 真 LLM），FastAPI/前端仍在 Windows 照常开发。

```bash
# WSL2 (Ubuntu) 内 —— 一次性环境准备
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt install -y nodejs   # Node ≥ 22.15
pip install deepseek-harness-sdk                                                      # Python SDK
export DEEPSEEK_API_KEY=...

# 真实链路宿主脚本（host.py，走默认 bundled exe，不覆写 runtime_bin）
cat > host.py <<'EOF'
from deepseek_harness import DeepSeekHarness
with DeepSeekHarness(provider="deepseek-official", model="deepseek-v4-flash") as h:
    r = h.run("分析 600519 的安全边际", session_id="600519-2026-08-14")
    print(r.final_response)
EOF
python host.py
```

## 4. 路径② Docker 生产同构 🔶

起 linux `dsh-engine` 容器复现生产拓扑（SDK 宿主 + runtime 同容器 + HTTP 触发），Windows 上 FastAPI 经 HTTP 触发容器端点。生产 compose 卷声明与双容器拓扑在 P4 落地（挂载结构见 `.dsh/docs/i3-script-tamper.md`，MCP transport 见 Task 10）。

```bash
# 本地联调（示意，P4 落地后替换为真实 compose 文件）
docker compose up dsh-engine   # Node 22(≥22.15) + deepseek-harness-sdk + @deepseek-ai/dsh@0.1.0-rc.6
```

容器关键门槛（P0 裁决，写镜像 Dockerfile 时遵守）：

- Node 生产镜像 ≥ 22.15.0（zstd 硬门槛）。
- `@deepseek-ai/dsh@0.1.0-rc.6` 精确锁定 + `pnpm-lock.yaml` + `frozen-lockfile`。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 经环境变量注入。
