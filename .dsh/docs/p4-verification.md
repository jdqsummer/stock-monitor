# P4 清理与加固 — 完成态验证记录

> 验证日期：2026-08-15 ｜ 验证人：DSH P4 Task 8（implementer） ｜ 分支：`feat/dsh-p0-verification`
> 判定结论：**P4 清理与加固已完成（本机可验证项全绿）**，真实容器化全链路（五段 e2e / Q3 Ralph 子代理 / calc_host Linux node 调用 / BuildKit 生效性）**待部署机（腾讯云）执行**——见文末「未验证项」。

## 一、验证基线

- Python：3.13.1（Windows 原生）
- Node / npm：前端 vite 8.2.1
- Docker：**本机无 Docker**（`docker: command not found`），compose 以 PyYAML 解析校验替代
- 分支基线提交：`2fd46b4`（Task 7 复审修复）

## 二、OpenHarness 资产删除清单（Task 1-2）

| 项 | 状态 | 说明 |
|:--|:--|:--|
| `vendor/openharness/` 源码 | ✅ 已删除 | `git ls-files vendor` 为空（不受版本控制）；磁盘仅残留 `__pycache__/*.pyc` 编译缓存（gitignore，无 `.py` 源文件） |
| `backend/agents/harness_component.py` | ✅ 已删除 | 无引用 |
| `backend/agents/stage_tools.py`（`_load_stages()` 工厂） | ✅ 已删除 | 方法论加载迁 `.dsh/skills/`（TS `prepare.ts scanBlocks`）+ `analysis_chain.py` 直读 |
| `OpenHarnessAgent` → `AnalysisAgent` | ✅ 已重构 | `analysis_agent.py` docstring 标注「P4 OpenHarness 语义退役」，LLM 模式经 `DshOrchestrator` 派发 |
| `main.py` vendor 引导 | ✅ 无 | `grep vendor backend/main.py` 无匹配 |
| `harness_poc.py` + `harness_poc_report.md` | ✅ 已删除 | 本任务删除残留报告文档 |

**残留说明（诚实）**：`backend/agents/*.py`（`constraints.py` / `workflow.py` / `analysis_chain.py` / `state.py` / `analysis_job_svc.py`）docstring/注释仍含「OpenHarness」字样（如「OpenHarness 约束引擎」「OpenHarness 时代」），属**历史语义描述**，非对已删模块的功能 import，不构成运行时依赖。清理这些注释需触碰 backend 功能代码，超出本任务（Task 8）「不触碰功能代码」边界，留待后续低优先清理。

## 三、Docker 双容器 + rc.6 锁定（Task 3）

- `docker-compose.yml` PyYAML 解析通过；服务清单：`app` / `frontend` / `nginx` / `redis` / **`dsh-engine`**。
- `app` 环境：`DSH_ENGINE_URL=${DSH_ENGINE_URL:-http://dsh-engine:8001}` ✅。
- `dsh-engine` 服务：`DSH_ENGINE_PORT=8001`、SDK 宿主 + dsh-jsonrpc-agent 同容器、S3 留存 env（`DSH_SESSION_RETENTION_DAYS=90` / `DSH_SESSION_MAX_COUNT=10000` / `DSH_CLEANUP_INTERVAL_SECONDS=86400`）、I3 只读挂载（`.dsh/skills` / `.dsh/plugins:ro`）、`dsh_sessions` 卷持久化 ✅。
- `dsh-engine/package.json` 精确锁定：`@deepseek-ai/dsh@0.1.0-rc.6` / `@deepseek-ai/dsh-tools@0.1.0-rc.6` / `@deepseek-ai/dsh-mcp-client@0.1.0-rc.6`；`pnpm-lock.yaml` 已提交 ✅。
- `dsh-engine/Dockerfile` + `Dockerfile.dockerignore` 就位 ✅（BuildKit 生效性本机无法验证，见未验证项）。

## 四、Q3 Ralph 深度自审循环（Task 4）

- `invest-five-stage` 支持 `ralph_enabled`；`ralph_review` 作为**顶层附加键**（`...(args.ralph_enabled ? { ralph_review } : {})`），不破坏 4 个 stage 键 ✅。
- 协议级验证：`scripts/dsh_p3/sdk_host_test.py` 中 `test_trigger_ralph_enabled_field_accepted` / `test_build_prompt_includes_ralph_hint_when_enabled` / `test_build_prompt_no_ralph_hint_by_default` 通过（5/5）✅。
- **未验证**：Q3 ralph 子代理内**真实**触发（需 dsh-engine Linux 容器 + 真实 DSH runtime）→ 待部署端。

## 五、I4 双实现收敛 / /calc 黄金数据（Task 5）

- 降级链主调 DSH TS `/calc`（`scripts/dsh_p3/calc_host.py`）+ Python 本地兜底（`estimate_annual_profit_node`）✅。
- 黄金数据集对照：`python -m pytest scripts/dsh_p3/calc_host_test.py` → **4 passed**（`test_calc_endpoint_contract` / `test_calc_endpoint_default_empty_input` / `test_calc_run_ts_calc_returns_parsed_json` / `test_health_endpoint`）✅。
- **未验证**：`calc_host` 在 dsh-engine Linux 容器内**真实 node 调用**（本机 `test_calc_run_ts_calc_returns_parsed_json` 为协议/解析级，非真实 `node` 进程）→ 待部署端。

## 六、S3 日志留存清理 + S6 回滚 runbook（Task 7）

- S3：`scripts/dsh_p3/session_cleanup.py`（90 天留存 + 10k 上限滚动）；`python -m pytest scripts/dsh_p3/session_cleanup_test.py` → **3 passed**（超期删除 / 上限滚动 / 超期+上限并存）✅。
- S6：`docs/股票WEB监控系统/生产回滚runbook.md` 就绪 ✅。
- DSH_UPSTREAM 六步升级流水线：`scripts/dsh_upgrade/upgrade.sh <ver> --dry-run` 六步全 echo（exit 0）、`regression.py --dry-run` 5 只股票（600519/601398/688111/002450/NO_LLM）echo（exit 0）✅。

## 七、全量回归结果

| 命令 | 结果 |
|:--|:--|
| `python -m pytest tests/ -v` | **355 passed**（11 warnings，无失败） |
| `python -m pytest scripts/dsh_p3/session_cleanup_test.py` | **3 passed** |
| `python -m pytest scripts/dsh_p3/calc_host_test.py` | **4 passed** |
| `python -m pytest scripts/dsh_p3/sdk_host_test.py` | **5 passed** |
| `cd .dsh/plugins && (每个插件 npx vitest run)` | invest-calc 44 + five-stage 9 + guard 11 + schema 14 + telemetry 3 = **81 passed** |
| `cd frontend && npx tsc --noEmit` | **exit 0** |
| `cd frontend && npm run build` | **exit 0**（vite 3066 modules，1.48s） |
| `docker compose config --quiet` | 本机无 Docker → **PyYAML 解析校验通过**（5 服务，含 dsh-engine） |

> 测试计数对账：`pytest tests/` = 355，加 `scripts/dsh_p3/` 下 3 个独立 pytest 文件（session_cleanup 3 + calc_host 4 + sdk_host 5）共 367 个 Python 用例全绿；DSH 插件 vitest 81 全绿。

## 八、未验证项（如实标注，不伪造）

| # | 未验证项 | 原因 | 待办 |
|:--|:--|:--|:--|
| 1 | 真实五段全链路容器化 e2e（茅台 600519：`analysis_source="dsh-llm"` + 4 stage 键 + `ralph_review`/降级三标记） | 本机无 Docker | 部署机（腾讯云）`docker compose up -d` 后触发 `/api/analysis/analyze` |
| 2 | Q3 ralph 子代理内真实触发 | 需 dsh-engine Linux 容器 + 真实 DSH runtime | 部署端深度模式（V4-Pro）验证 |
| 3 | calc_host 在 dsh-engine Linux 容器真实 `node` 调用 | 本机为协议/解析级冒烟 | 部署端容器内验证 |
| 4 | `dsh-engine/Dockerfile.dockerignore` BuildKit 生效性 | 本机无 Docker | 部署端构建时验证镜像体积与复制内容 |

## 九、陈旧文档清理（本任务）

- 删除 `scripts/harness_poc_report.md`（已删 `scripts/harness_poc.py` 的配套报告，引用已删 `harness_component.py` / `vendor/openharness/`）。
- 修订 `backend/agents/skills/stages/编写规范.md`：`stage_tools.py::_load_stages()` / `test_stage_tools.py` 引用更新为 P4 现状（方法论资产迁 `.dsh/skills/`，TS `prepare.ts scanBlocks`，Python 侧 `analysis_chain.py` 直读 + `test_skill_load.py` 校验）。

## 十、结论

P4 清理与加固的所有**本机可验证项**全部通过（Python 367 + TS 81 用例、前端 tsc/build、compose 结构校验、升级流水线 dry-run）。真实容器化全链路 4 项属**部署端验证**范畴，本机无 Docker/无真实 DSH runtime，如实标注为「待部署机执行」，未伪造任何验证结果。
