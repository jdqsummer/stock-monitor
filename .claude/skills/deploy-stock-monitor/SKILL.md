---
name: deploy-stock-monitor
description: 一键更新部署 stock-monitor 到腾讯云服务器 49.232.171.206。当用户提到"更新部署""部署到服务器""部署到腾讯云""同步部署""上线新代码""更新生产环境""刷新服务器上的代码""部署最新代码"，或涉及 49.232.171.206 / /home/ubuntu/stock-monitor / docker compose up / 服务器更新时，使用本 skill 完成 本地测试→打包→SFTP上传→compose重建→全量验证 的完整部署流程并汇报结果。
trigger: automatic
paths:
  - "D:/project/github/stock-monitor/**"
---

# Deploy Stock Monitor

将本地最新代码一键部署到腾讯云轻量服务器，并验证部署成功。核心思路：**tarball 覆盖 + docker compose 重建**，服务器数据（SQLite 卷、.env 密钥）全程不丢。

## 环境

- 服务器：`49.232.171.206`，用户 `ubuntu`（连接配置/凭据在 `scripts/config.json`）
- 代码路径：`/home/ubuntu/stock-monitor/`（服务器上**无 .git**，只能文件覆盖）
- 部署包：tarball → SFTP 上传 → 解压覆盖 → `docker compose up -d --build`
- 访问入口：http://49.232.171.206（nginx :80 → 前端静态 + `/api/` 反代 app:8000）

## 一键执行

```bash
# 在项目仓库任意位置，Python 3.13 + paramiko 已具备
python C:/Users/SXF-Admin/.claude/skills/deploy-stock-monitor/scripts/deploy.py
# 参数：--skip-tests 跳过本地 pytest；--dry-run 只打包不部署
```

`deploy.py` 自动完成：本地 pytest → 打包（排除 `.env/.git/*.db/缓存`）→ SFTP 上传 → 备份服务器 `.env` → 解压覆盖 → 补 `.env` 缺失键 → 后台 `docker compose up -d --build` → 轮询 app 健康 → 全量验证（容器/health/前端/迁移/新表/多渠道数据源冒烟）。

## 详细流程

1. **本地测试**：先跑 `pytest tests/ -q`（当前 338 tests 全过才允许部署），避免把坏代码推上生产。
2. **打包**：排除 `.env`（服务器密钥，绝不上传）、`*.db`（本地开发库）、`.git`、`node_modules`、缓存。解压时 `.env`/`deploy.log` 因不在包内而天然保留。
3. **上传与备份**：SFTP 传到 `/home/ubuntu/`，解压前先 `cp .env ~/.env.backup-日期` —— 改服务器配置前必须先备份。
4. **补环境变量**：`config.json` 的 `env_extra` 只在 `.env` **缺失**对应键时才追加，绝不覆盖已有值。当前默认 `DATA_PROVIDER_PRIORITY=tencent,eastmoney,mock`（启用真实行情，恒 mock 兜底）。
5. **重建**：`docker compose up -d --build`。app 启动命令先 `alembic upgrade head` 自动补齐新迁移，再起 uvicorn。
6. **轮询健康**：每 10s 查 `docker compose ps` 直到 app `healthy`；构建失败（日志含 `failed to solve`/`ERROR` 等）提前退出，避免空等。
7. **验证**：见下方清单。

## 验证清单（必须全部通过再汇报"部署成功"）

- [ ] `docker compose ps`：app healthy、nginx/redis 运行中
- [ ] `/api/health` 返回 200 `{"code":0,"data":{"status":"ok"}}`
- [ ] 前端首页 HTTP 200（`http://127.0.0.1/`，可选再验公网 IP）
- [ ] `alembic current` 到 head（新迁移已应用）
- [ ] 新表存在（`stock_snapshots`/`financials`/`analysis_snapshots`）
- [ ] 多渠道数据源冒烟：容器内 `fetch_quote('600519')` 返回真实腾讯行情 + `fetch_financials` 东财财报

若某步失败，用 `python .../scripts/remote.py '<command>'` 远程排查（如 `docker logs stock-monitor-app-1 --tail 50`、`tail deploy.log`）。

## 关键坑位（务必遵守）

1. **服务器无 .git** → 用 tarball 覆盖，不能用 git pull。包内文件覆盖旧版，包外文件（.env/deploy.log）保留。
2. **.env 不进包** → 部署后必须确认服务器 `.env` 仍在且含密钥（`DATABASE_URL=sqlite+aiosqlite:////app/data/stock_monitor.db`、REDIS_URL 用 `redis` 服务名）。
3. **nginx 缓存上游 IP** → 已用 `resolver 127.0.0.11 valid=10s` + `set $upstream` 变量修复，app 容器 recreate 换 IP 后 nginx 自动重解析，不会 502。
4. **SQLite 挂 named volume `app_data`** → 容器重建不丢数据。
5. **数据库迁移**：app 启动时 `alembic upgrade head` 自动跑；改模型需新增迁移文件并保证 revision 链线性（服务器旧库逐级升级）。
6. **构建耗时**：首次或依赖变更后 pip/npm 安装可能超 10 分钟 → deploy.py 用 nohup 后台构建 + 轮询，避免连接超时。
7. **Windows 环境**：SSH 用 Python paramiko（无 sshpass）。远程路径 `/home/ubuntu/...`，本地路径用 `D:/...` 正斜杠。

## 坑位详情

更多背景（迁移链、Provider 链 failover、上次部署发现的坑）见 `references/deployment.md`。遇到新坑时补充到该文件。
