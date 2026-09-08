# 部署细节与坑位参考

## 服务器环境（腾讯云轻量）

- 公网 IP：49.232.171.206（80 端口已放行）
- 系统：Ubuntu 24.04 LTS，用户 `ubuntu`（1.9G 内存 + ~4G swap）
- Docker 29.7 + Compose v5.4；apt/npm/pip 均走腾讯云/国内镜像源（compose build-arg 注入）
- 代码：`/home/ubuntu/stock-monitor/`，`docker compose up -d --build` 启动

## 数据与配置持久化

- SQLite 库：named volume `app_data` → `/app/data/stock_monitor.db`，容器重建不丢
- 服务器 `.env`：**与仓库 `.env.example` 不同**，含生产密钥。改动前先备份 `~/.env.backup-YYYYMMDD`
  - `DATABASE_URL=sqlite+aiosqlite:////app/data/stock_monitor.db`
  - `REDIS_URL=redis://redis:6379/0`
  - DeepSeek LLM：`LLM_MODEL=deepseek:deepseek-chat` + `LLM_API_KEY`（记忆蒸馏兜底读 `DEEPSEEK_API_KEY`）
  - SMTP：QQ 邮箱 `smtp.qq.com:465` + SSL（aiosmtplib `use_tls=True` 隐式 SSL，**必须 465**）
  - `DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock`（2026-08-12 启用真实数据源）

## 容器拓扑（docker-compose.yml）

- `app`：FastAPI，`alembic upgrade head && uvicorn :8000`，healthcheck（python urllib，slim 无 curl）
- `frontend`：构建产物写共享卷 `frontend_dist` 后退出（`service_completed_successfully`）
- `nginx`：:80 → 前端静态 + `/api/` 反代 app:8000 + SSE（`/api/chat/stream` 关 buffering）
- `redis`：7-alpine

## Alembic 迁移链（必须保持线性）

```
e47556799a7f (initial) → a1b2c3d4e5f6 (watchlist 唯一约束) →
b3e5f7a8c9d1 (analysis_snapshots 数值化，drop 重建空壳表) →
c5d7e9f1a3b8 (stock_snapshots + financials) →
d9f1a3b5c7e1 (analysis_snapshots 定性列) →
f1a3b5c7d9e1 (analysis_snapshots checklist 三列) →
a7b8c9d0e1f2 (结论列 + unassessable + 风险字段透传)   ← 当前 head
```

服务器旧库会从当前 head 逐级升级，无需手工干预。新增迁移时 down_revision 指向当前 head。

## 多渠道数据源（Provider 链）

- 门面 `backend/data/westock_client.py`：按 `DATA_PROVIDER_PRIORITY` 优先级链尝试，**全部失败才兜底 mock**（永不阻断）
- 腾讯：行情/搜索（qt.gtimg.cn GBK 解析），无财报接口
- 东财：行情/搜索/F10 财报（push2 + searchapi）
- 财报自动 failover：腾讯无财报 → 东财 → mock

## 历史踩坑记录

1. **nginx 502**：app 容器 recreate 换 IP，nginx 启动时缓存旧 IP → 已用 `resolver` + 变量修复
2. **sse-starlette 版本冲突**：2.2.1 需 starlette>=0.41 与 fastapi 0.111 冲突 → 锁 1.8.2
3. **alembic 容器内导入失败**：缺 `prepend_sys_path=.` → 已修
4. **前端 tsc 类型拦截构建**：`getHistory` 返回 `role:string` 与 `ChatMessage[]` 不匹配 → 复用 `ConversationItem[]`
5. **React 19 + antd v5 静态方法失效**：`message/notification/Modal.confirm` 用 ReactDOM.render 被移除 → `@ant-design/v5-patch-for-react-19`
6. **axios 401 拦截吞错误**：登录失败报错被跳登录页吞掉 → 豁免 `/auth/` 前缀
7. **deploy.py start_build 误报失败**（2026-08-12）：`nohup docker compose up -d --build > log 2>&1 &` 后台进程继承 SSH 通道 stdin，paramiko `stdout.read()` 阻塞 30s 抛 PipeTimeout，deploy.py 提前退出。实际构建已在后台正常完成。修复：命令加 `< /dev/null` 断开 stdin。若再遇 `start_build` 超时，直接检查 `deploy.log` 与 `docker compose ps`——构建很可能已成功，手动续跑验证清单即可。
8. **搜索富化**（2026-08-12）：`/api/watchlist/search` 端点会对搜索结果逐只补拉实时行情（`asyncio.gather` + 失败保留元数据），provider 层 `search_stock` 仍返回零值元数据是预期——富化在端点层，不在 provider。
9. **模型与迁移不同步 → 生产缺列**（2026-08-12）：commit `2516bc0` 给模型 `AnalysisSnapshot` 新增 `checklist_results/checklist_veto/checklist_summary` 但**漏写 Alembic 迁移**。本地测试用 `Base.metadata.create_all`（conftest.py）从模型直接建表 → 全绿掩盖；生产走 alembic 逐级升级 → 表缺三列 → 看板接口查询 `AnalysisSnapshot` 抛 `OperationalError: no such column` → 自选股无法展示。教训：**改模型必须同步迁移文件**；部署验证只查表名不查列（旧 verify 的盲区）。已加 `tests/test_migrations.py`（重放迁移链断言列一致）+ deploy.py verify 改为"表与关键列"检查 checklist 三列。
10. **批量/自选股分析缺定性结论**（2026-08-13）：`AnalysisJobService._process_one` 用**无参 `AnalysisChain()`**（`llm_provider=None`）创建分析链 → `OpenHarnessAgent.has_real_llm=False` → 走纯规则子链，**不生成 `moat_assessment/risk_factors/checklist_summary`**。看板"立即分析"（`/watchlist/analyze`）与"加自选"（watchlist_add）全走此路径；`analyze/batch`、`report/{code}` 端点同样问题。单只 `analyze` 端点用 `create_analysis_chain()` 正常。修复：job svc + batch/report 统一改 `create_analysis_chain()`。**诊断线索**：快照 `pe_rationale` 是"行业锚定 X 25-45 倍"规则格式（而非 LLM 格式）+ moat/risk/checklist 全 NULL；容器内 `has_real_llm` 单独测是 True，但 job 实际构造无 LLM 链。教训：**LLM 注入必须经 `create_analysis_chain()`（内部 get_llm + 失败降级 None），直接 `AnalysisChain()` 恒为纯规则模式**；生产验证只查表不查内容（verify 盲区）。已加回归测试 `test_default_chain_uses_llm_aware_constructor`。
11. **依赖缺失 → LLM 分析静默降级规则子链**（2026-08-14）：requirements.txt 缺 vendored openharness 运行时依赖 **`croniter`+`mcp`**，生产 `harness_component` import 失败 → app 日志 `OpenHarness 组件分析失败，降级规则子链: No module named 'croniter'`，用户点"立即分析"返回 200 但无定性结论。**根因是本地/生产环境漂移**：本地全局环境（pydantic 2.12/httpx 0.28/openai 1.109...）测试全绿掩盖，requirements pin 旧版（pydantic 2.7.4/httpx 0.27.0/openai 1.35.3）无法安装新版依赖。**mcp 版本约束**：1.28.1 需 pydantic>=2.11/uvicorn>=0.31.1（本项目已升 pydantic 2.12.3/pydantic-settings 2.14.2/uvicorn 0.31.1/mcp 1.28.1）；**httpx 0.28 移除 `proxies` 参数 → 与 openai==1.35.3 运行时冲突**（`TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'`），必须 httpx==0.27.2；mcp 1.10.0 无 `streamable_http_client`（旧名 `streamablehttp_client` 且签名无 `http_client` 参数）与 vendored 不兼容。教训：**改 requirements 后必须 `pip install --dry-run` 验证可解析 + 容器内 import 冒烟 + 真实 `create_analysis_chain().analyze()` 端到端**（本地 pytest 用本地环境，不验证 requirements 可装性）。verify 盲区已补：容器内 `from backend.agents.harness_component import run_analysis_agent` + 真实 LLM 分析断言 moat/risk/checklist 非空。
12. **deploy.py wait_for_app_healthy 误报成功 + 冒烟脚本 bug**（2026-08-14）：build 失败（`ERROR: ResolutionImpossible`，deploy.log 含 `failed to solve`）但旧 app 容器仍 healthy 时，原逻辑 `if "healthy" in ps` 在 build 失败检查**之前** → 误报部署成功，实际镜像未变（生产继续跑旧镜像 + 临时 pip 依赖）。修复：先查 deploy.log 的 buildkit 致命标记（命中即 False），再查本次构建的 `app-1 Healthy` 标记。另 datasource_smoke 的 `fetch_financials` 已返回多期列表（financials_8p），脚本按单对象 `f.report_period` 访问崩溃 → 改 `fs[0].report_period`。
13. **start_build PipeTimeout 复发**（2026-08-14）：坑位 7 的 `< /dev/null` 修复**未根治**，paramiko `stdout.read()` 仍 30s 超时退出（4 次部署复发 3 次）。每次均在服务器后台正常构建，需按恢复流程：`grep -E "Image .*Built|app-1 Healthy|failed to solve" deploy.log` + `docker compose ps` 手动确认续跑验证。根治方向：start_build 改为不读 stdout（`exec_command` 后立即返回）或分两步（先 `docker build` 后台，再 `docker compose up`）。
14. **dsh-engine 构建：`pnpm@latest` 的 minimumReleaseAge 策略**（2026-08-15）：新版 pnpm 默认启用 `minimumReleaseAge`（24h）安全策略，拒绝 lockfile 中 24h 内新发布的传递依赖（@smithy/core@3.33.0 等），`pnpm install --frozen-lockfile` 构建失败（Dockerfile `RUN pnpm install`）。修复：Dockerfile 固定 `pnpm@10.22.0`（与本地生成 lockfile 版本一致），勿用 `@latest`。
15. **dsh-engine 构建：pip 直连 pypi.org 大 wheel 下载停滞**（2026-08-15）：dsh-engine Dockerfile 的 `pip install deepseek-harness-runtime-bin==0.1.0rc6`（57MB wheel）直连 pypi.org 时连接 ESTABLISHED 但 rxq=0 长期无数据（pip 默认无读超时，无限挂起，12+ 分钟无进展）。诊断：`/proc/<pip_pid>/net/tcp` 看 rxq=0。修复：docker-compose dsh-engine build args 传腾讯镜像 `PIP_INDEX_URL: https://mirrors.cloud.tencent.com/pypi/simple`（与 app 一致），57MB 47 秒装完。构建进程卡死时先杀 `docker-buildx bake` + 对应 pip 进程（不动运行中容器）。
16. **dsh-engine 插件树加载：value-investor 组合在 headless 下不完整**（2026-08-15）：sdk_host 经 `DSH_CORDIS_CONFIG` 传 cordis 时 runtime **替换**而非合并配置 → preset-plane 组合（缺核心 8 插件 + tools 服务）加载失败；`@deepseek-ai/dsh-agent-default-model`/`dsh-mcp-client`/`dsh-tools` 不在 runtime 内嵌 snapshot，包名引用报 `Cannot find package`；裸 `agent-default-model` 行缺 config 报 `$.provider missing required value`。修复：新增 `.dsh/agent-presets/value-investor/cordis.standalone.yml`（完整独立组合：核心 8 插件 + dsh-tools + agent-default-model(带 provider/model config) + skill + tool-skill + 自定义插件，snapshot 缺失包改 `file://` 引 /app/node_modules），Dockerfile `DSH_CORDIS_CONFIG` 指向它；package.json 加 `@deepseek-ai/dsh-agent-default-model`（file:// 传递依赖经 pnpm store 嵌套 node_modules 逐层解析，无需手工软链）。诊断技巧：`NODE_OPTIONS='--require=<preload 设 util.inspect.defaultOptions.depth=null>'` 可展开 runtime 的 `[errors]: [Array]` 拿到每个失败入口。
17. **dsh-engine 分析运行挂起（已解决，2026-08-15）**：根因 = `cordis.standalone.yml` 插件树激活失败但 fail-loud 进程存活 → initialize/session/prompt 永不响应。两个问题：
    - `invest-five-stage` 插件 `inject: ['tools','workflowEngine']` 需要 workflow 栈，组合没挂 → 报 `waiting for service: workflowEngine` → 1 entry did not activate → boot 抛错但 fail-loud 存活 → SDK 无限等 initialize。
    - `tools` 用 `file://` 挂 /app/node_modules 实例 vs agent-spine 内嵌 snapshot 实例：两实例 `TOOL_RUNTIME_SCHEDULER` 模块级 Symbol 不匹配 → 首次工具调用崩 `Cannot read properties of undefined (reading 'prepare')`。
    修复（commit 45793b6）：补 `dsh-subagent` + `dsh-subagent-spawn-in-process`(providerName: spawn) + `dsh-workflow-worker-thread`(provider: spawn)；**去掉 tools 的 file:// 行**（tools 服务由 agent-spine 内嵌 snapshot 提供，单实例）。
    诊断技巧（生产取证）：runtime 是 Node 单文件二进制，可 `kill -USR1 <pid>` 开 Node inspector（127.0.0.1:9229），用 `docker exec -i <ctr> node -` 写 `new WebSocket('ws://127.0.0.1:9229/...')` 连接，`Runtime.evaluate` 执行 `process._getActiveHandles()`（卡死时仅 stdio 3 个 Socket = 事件循环空闲等 stdin）、`process._getActiveRequests()`（空 = 无 I/O 待决）；session 文件在 dsh_sessions 卷（`/app/sessions/--app--/<id>/session.jsonl.zstd`，容器内 python zstandard 流式解压）可看 agent loop 走到哪一步（卡 preStep = turn/start 后无 step/start）。
    遗留（commit e91420c 部分缓解）：五段定性分析 ~10 分钟（deepseek-v4-flash 子代理探索/迭代 20-30 步），超过应用 HttpDshRunner 600s 超时 → app 仍会超时降级纯规则子链（不再挂起）。可用性修复：sdk_host context 改 JSON 呈现 + 工具 context 必填 + dataSummary 注入子代理（qualitative/reverse 2-3 步）+ invest-schema evidence 校验降级 notice 不 block。
18. **compose 服务名 app vs 代码注释的 backend 主机名**（2026-08-15）：DSH invest-data-mcp 按设计连 `http://backend:8000/mcp/investdata`（main.py 注释 + 组合），但 compose 服务名是 `app` → dsh-engine 内 DNS 解析失败。修复：docker-compose 给 `app` 服务加默认网络别名 `backend`。**遗留**：只修了 DNS 解析，未解决 FastMCP host 校验（见坑位 20）。
19. **DSH 五段可用性三连（2026-08-15，commit e91420c）**：见坑位 17 遗留段。三处插件/宿主修复：sdk_host._build_prompt context 改 `json.dumps(ensure_ascii=False)`（Python dict repr 非合法 JSON，模型无法可靠转发）+ 提示词要求原样传工具 context 参数；invest-five-stage context 改必填 + FIXED_SCRIPT 加 dataSummary 注入 qualitative/reverse 子代理（勿自行读盘）；invest-schema validateEvidence 兼容嵌套 evidence + 接受 context./calc. 前缀 + evidence 不命中降级 notice（避免整轮 workflow 重试循环）。验证：子代理拿到数据 2-3 步完成（原 31 步）、schema 校验失败 0。
20. **FastMCP DNS rebinding 保护拦截跨容器 MCP 通道**（2026-08-15）：`mcp 1.28.1` 的 `TransportSecurityMiddleware` 默认 `allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"]`，不含 `backend` → dsh-engine 以 `Host: backend:8000` 访问 `/mcp/investdata` 返回 **421 Invalid Host header**（`backend` 网络别名只解决 DNS，未过 host 校验层）。影响：`failOnStartupError:false` 不阻断主分析，但 `mcp__investdata__*` 工具不注册，DSH 辅助数据通道（补充财报/行业对比）不可用。修复（`backend/data/dsh_bridge.py`）：FastMCP 构造传 `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[..., "backend:*"])`，白名单外 Host 仍 421。回归测试 `tests/test_api/test_dsh_bridge_mount.py::TestInvestdataHostValidation`（localhost 放行 / backend 放行 / evil 拒绝）。**教训**：deploy.py verify 只查 app 侧，DSH 跨容器通道（dsh-engine→backend）须单独用容器内 MCP client 冒烟（见 dsh_mcp_full_verify.mjs：SDK 在 pnpm store，入口 `dist/esm/client/index.js`）。

21. **pip 镜像缺档 pin → 构建缓存掩盖（2026-08-25）**：`litellm==1.40.7` 不在腾讯镜像（1.40.2~1.40.19 全缺档），此前 `COPY requirements.txt` 未变 → pip 层缓存命中从未暴露。本次缓存失效全量重建 `No matching distribution`。**诊断**：服务器上 `docker run --rm -v /home/ubuntu/stock-monitor/requirements.txt:/req.txt:ro python:3.11-slim pip install --dry-run -r /req.txt --index-url https://mirrors.cloud.tencent.com/pypi/simple` 一次列全所有缺档 pin（当时仅 litellm）。**修复**：改镜像可用的同系列版本（1.40.31），并验证 fresh resolve 全绿再部署。
22. **SFTP 大文件上传中段 EOFError（2026-08-25）**：21MB tarball 上传连续两次在传输中段断开（paramiko `sftp.put` EOFError，残缺文件 884KB/7.4MB 大小不定），但短命令 exec 正常 → 到腾讯云链路对大流量不稳定。服务器 auth.log 无主动断开记录。**修复**：`remote.py` 的 `upload()` 加 3 次重试——捕获 `(EOFError, paramiko.SSHException, OSError, socket.error)` → close 旧连接 → 清远端残缺文件 → `time.sleep(5*attempt)` 指数退避后重连重试。

## 生产账号（验证用）

- `1140467720@qq.com` / **`da@7712025`**（2026-08-15 前端实测有效，登录成功；此密码与服务器 SSH 密码 `Da@7712025` 同源）
- 旧记录 `TestPass@2026` 已失效（bcrypt 哈希不匹配，2026-08-15 实测 401）

## 生产分析验证方式（2026-08-15 实操）

HTTP 层验证：
- `GET /api/analysis/health`：`llm_model:"configured"`、workflow_ready、6 约束
- `GET /api/analysis/quote/600519`：真实行情 + 东财多期财报，`data_complete:true`

容器内端到端（绕过认证，验证 LLM 定性结论——deploy.py verify 的盲区，见坑位 10/11）：
```bash
# 上传脚本到服务器后 docker cp 进 app 容器，再：
docker exec stock-monitor-app-1 sh -c 'cd /app && PYTHONPATH=/app python /tmp/e2e_verify.py > /tmp/e2e.log 2>&1 &'
# 脚本：create_analysis_chain().analyze("600519") → 断言 moat_assessment/risk_factors/checklist_summary 非空
# 注意 PYTHONPATH=/app（脚本在 /tmp 运行时 import backend 失败）
```
五段分析 ~10min（deepseek-v4-flash 子代理），2026-08-15 实测 PASS：moat 护城河多维描述 + 5 risks + 证伪清单（扣非 0.12% 差距）。落库确认：`analysis_snapshots`（列 `stock_code`，含 `analysis_model/analysis_degraded/stage_results`）——注意脚本直调 analyze 不走 save_snapshot，落库由 API 端点负责；库内已有历史快照（300750 击球区/完整定性字段）。
