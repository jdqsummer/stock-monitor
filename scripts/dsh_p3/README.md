# dsh_p3 — SDK 宿主（HTTP 触发端点）

`dsh-engine` 侧的 SDK 宿主服务：把 `DeepSeekHarness` + 事件解析封装为一个 FastAPI `POST /trigger`
端点，供 backend 的 `HttpDshRunner` 调用（部署拓扑「容器内 SDK 宿主 + HTTP 触发」，backend 不直接持 SDK）。

## 契约

- 请求/响应字段逐字对齐：`.dsh/docs/p3-http-trigger-contract.md`（P3 定稿）。
- 服务端：本目录 `sdk_host.py`（`POST /trigger`）。
- 客户端：`backend/agents/dsh_orchestrator.py` `HttpDshRunner.run_five_stage`。
- 事件解析复用 Task 2：`backend/agents/dsh_events.py`（`extract_five_stage_result`/`extract_model`/`extract_usage`）。

## 启动（真实 runtime，仅 linux/macos x64/arm64）

```bash
cd scripts/dsh_p3
DSH_CORDIS_CONFIG=<value-investor cordis> DSH_SESSION_ROOT=<session 目录> python sdk_host.py
# 默认 0.0.0.0:8001，可用 DSH_ENGINE_PORT 覆盖
```

联调（可选，需 WSL2/Docker linux runtime）：

```bash
curl -X POST http://127.0.0.1:8001/trigger -H 'Content-Type: application/json' \
  -d '{"code":"600519","name":"贵州茅台","context":{},"model":"deepseek-v4-flash","session_id":"600519-2026-08-14"}'
```

## Windows 本地联调三路径

1. **WSL2 linux runtime**：把仓库挂进 WSL，在 WSL 内按上述命令启动 sdk_host，backend 指向 `DSH_ENGINE_URL`。
2. **Docker linux runtime**：用 linux 镜像起 sdk_host 容器，经宿主端口暴露 `/trigger`。
3. **fake-runtime 协议级冒烟**（最轻，不拉起真实 runtime）：`scripts/dsh_p0/t6_sdk/fake_runtime.py`
   配合 SDK 做协议级联调；`scripts/dsh_p3/sdk_host_test.py` 用 `monkeypatch.run_harness` 测契约形状，
   不依赖真实进程。

## 测试

```bash
# rootdir 在仓库根，backend 可 import
python -m pytest scripts/dsh_p3/sdk_host_test.py -v
```

覆盖：契约响应形状（result/model/usage/degraded/error）+ 兜底路径（未找到五段 → `degraded=true`，
`error` 含「五段」，HTTP 仍 200）。

## 真实五段完成态验证状态

待验证。真实五段全链路完成态需 linux runtime + `value-investor` cordis 组合，纳入 P3 末 **Task 9
插件参数 + 冒烟** 一并验证；当前 Windows 开发机不编造成功，仅以 mock/fake 路径保证契约形状。
