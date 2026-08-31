# P5-A: DeepSeekHarnessConfig 字段差异（rc.6 → v0.1.2-alpha.2）

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（已 checkout 到 dsh-v0.1.2-alpha.2 / commit 0a53fb55）
> 结论标签：**breaking**

## 1. 字段对照表

| 字段 | rc.6 | v0.1.2-alpha.2 | 差异 |
|:--|:--|:--|:--|
| `provider` | ✓ 默认 `deepseek-official` | ✓ 默认 `deepseek-official` | 保留 |
| `model` | ✓ | ✓ | 保留 |
| `max_tokens` | ✓ | ✓ | 保留 |
| `cwd` | ✓ | ✓ | 保留 |
| `runtime_cwd` | ✓ | ✓ | 保留 |
| `session_root` | ✓ | **✗ 删除** | **BC**：必须改用 `dsh_home` |
| `cordis` | ✓ | **✗ 删除** | **BC**：必须改用 `patches` |
| `runtime_bin` | ✓ | **✗ 删除** | **BC**：必须改用 `dsh_bin` |
| `launch_args_override` | ✓ | **✗ 删除** | **BC**：改用 `HarnessClient._launch_args`（private） |
| `request_timeout_seconds` | ✓ | ✓ | 保留 |
| `shutdown_timeout_seconds` | ✓ | ✓ 默认 1.0 | 保留 |
| `base_url` | ✓ | ✓ | 保留 |
| `api_key` | ✓ | ✓ | 保留 |
| `env` | ✓ | ✓ | 保留 |
| **新增** `reasoning_effort` | — | ✓ | v4-pro 深度模式可传 `low/medium/high/max` |
| **新增** `dsh_bin` | — | ✓ | 替换 `runtime_bin` |
| **新增** `profile` | — | ✓ 默认 `"sdk"` | profile 选择 |
| **新增** `patches` | — | ✓ 默认 `()` | tuple[str, ...]，patch YAML 列表 |
| **新增** `dsh_home` | — | ✓ | 必填语义，替代 `session_root` |
| **新增** `initialize_timeout_seconds` | — | ✓ 默认 30.0 | profile 握手独立超时 |

## 2. 对项目的影响

**文件**：`scripts/dsh_p3/sdk_host.py:145-171` 的 `_build_config()`

### 2.1 当前 rc.6 代码

```python
return DeepSeekHarnessConfig(
    provider="deepseek-official" if vendor == "deepseek" else "openai",
    model=req.model or "deepseek-v4-flash",
    cordis=os.getenv("DSH_CORDIS_CONFIG"),
    session_root=os.getenv("DSH_SESSION_ROOT"),
    env=env,
)
```

### 2.2 v0.1.2-alpha.2 改造后

```python
dsh_home = os.getenv("DSH_HOME") or "/app/sessions/.dsh-home"
cordis_path = os.getenv("DSH_CORDIS_CONFIG")  # 旧 env 保留兼容
patches = (cordis_path,) if cordis_path else ()

return DeepSeekHarnessConfig(
    provider="deepseek-official" if vendor == "deepseek" else "openai",
    model=req.model or "deepseek-v4-flash",
    dsh_home=dsh_home,                            # 必填
    patches=patches,                              # 替代 cordis
    profile=os.getenv("DSH_PROFILE", "sdk"),      # 默认 sdk
    reasoning_effort="max" if req.ralph_enabled else None,  # V4-Pro 深度模式
    env=env,
)
```

### 2.3 关键变化

- `cordis=...` → `patches=(...)`：rc.6 单文件 cordis yml，v0.1.2 改用 patches tuple
- `session_root=...` → `dsh_home=...`：SDK 自管 session 子目录
- `provider="openai"` + env 透传 qwen/kimi/openrouter：v0.1.2 起**可能失效**（待 P5-C 验证 pi-ai 路由）
- 新增 `reasoning_effort`：V4-Pro 深度模式显式传 `max`

## 3. `RunResult` 字段变化

| 字段 | rc.6 | v0.1.2-alpha.2 |
|:--|:--|:--|
| `session_id` | ✓ | ✓ |
| `final_response` | ✓ | ✓ |
| `finish_reason` | ✓ | ✓ |
| `events` | ✓ | ✓ |
| `notifications` | ✓ | ✓ |
| `session_root` | ✓ | **✗ 删除** |

**影响**：项目代码 `RunResult.session_root` 无人引用，**无影响**。
