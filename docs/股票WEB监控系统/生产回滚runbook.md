# 生产回滚 runbook（S6，P4）

> 适用：腾讯云 49.232.171.206 docker-compose 部署。DSH 引擎异常时的降级、告警、回滚全流程。

## 1. 健康检查与探针

- dsh-engine 容器 healthcheck：`GET /openapi.json`（每 30s，3 次失败标记 unhealthy；sdk_host 仅暴露 POST /trigger，无 /health，用 FastAPI 自动生成的 /openapi.json 探活）。
- backend 侧：`DshOrchestrator.is_available()`（DSH_ENABLED + DSH_ENGINE_URL 非空）。
- 熔断：连续 `DSH_CIRCUIT_BREAK_THRESHOLD`（默认 3）次失败 → 自动切 `_rule_based`，冷却 `DSH_CIRCUIT_COOLDOWN_SECONDS`（默认 300s）后重新探测。

## 2. 自动降级开关

| 场景 | 动作 |
|:--|:--|
| DSH 连续失败 ≥ 3 | 熔断开启 → 全部分析走 `_rule_based`（`analysis_source=rule-based` + 降级警示条） |
| dsh-engine 容器 unhealthy | compose `restart: unless-stopped` 自动重启；重启后熔断冷却期结束恢复 |
| DSH 单次失败 | `DSH_RETRY_COUNT=1` 重试 1 次后降级（已有） |

## 3. 告警

- 熔断触发 / 容器 unhealthy → 写结构化日志 + 前端降级警示条（P3 已实现）。
- 生产告警渠道接入：`logs/dsh_engine_errors.log` 行级告警（可按需挂 Grafana/云监控）。

## 4. 恢复

- 熔断冷却期后自动重新探测 DSH；健康 → 恢复 DSH 路径（`analysis_source=dsh-llm`）。
- 手动恢复：`docker compose restart dsh-engine` + 观察 `/openapi.json` 与熔断日志。

## 5. 版本回滚（DSH 引擎）

1. `bash scripts/dsh_upgrade/rollback.sh <旧版本>`（lockfile 回退 + 重装）。
2. `docker compose up -d dsh-engine` 重建容器。
3. `python scripts/dsh_upgrade/regression.py --baseline <旧版本>` 验证回归集一致。
4. 回滚期间 backend 不受影响（降级链兜底，永不阻断——硬约束 5）。

## 6. 全量回滚（整体切 OpenHarness 时代基线）

> P4 已退役 OpenHarness 资产。终极兜底从「切 OpenHarness 双轨」改为「DSH 版本回退 + 回归验证」。
> 方法论 Skill 资产（`.dsh/skills/`）为 anthropics/skills 格式，可在任何 DSH 版本复用。
