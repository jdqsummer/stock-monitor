# P5-C: Preset 形态（cordis yml）v0.1.2-alpha.2 实测

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（commit 0a53fb55）
> 结论标签：**additive**（新 `dsh_home` 机制，cordis yml 仍支持但改为 patches 路径）

## 1. cordis yml 在 v0.1.2-alpha.2 的角色

- rc.6：`DeepSeekHarnessConfig(cordis=path)` 直接把 cordis yml 路径喂给 SDK
- v0.1.2-alpha.2：`DeepSeekHarnessConfig(patches=(path,))` 改为 patches tuple 喂入

**核心变化**：cordis yml 本身**仍是合法格式**，只是 SDK 入口从 `cordis` 字段名改为 `patches` tuple。

## 2. 验证：canonical preset 形态

`examples/` 下查找 v0.1.2-alpha.2 shipped preset：
- 真实名：`.cordis.standalone.yml` 仍可作 patch 喂入
- `agent.cordis.yml` 仍是 5 段 preset 形态

## 3. 对项目的影响

### 3.1 `.dsh/agent-presets/value-investor/agent.cordis.yml`

- 内容是「裸插件行」（`@deepseek-ai/dsh-tool-skill` / `@deepseek-ai/dsh-skill` / `@deepseek-ai/dsh-agent-default-model` / `@deepseek-ai/dsh-mcp-client`）
- v0.1.2-alpha.2 仍支持裸插件行（**实测**：项目当前 4 个 npm 包都仍 published 到 0.1.2-alpha.2）

### 3.2 `.dsh/agent-presets/value-investor/cordis.standalone.yml`

- 同样内容，喂入方式从 `cordis=...` 改 `patches=(...)` **在 sdk_host.py 层处理**
- yml 文件本身**不需要改**

## 4. 升级建议

**不修改 .dsh/agent-presets/* 内容**。仅 sdk_host.py 的 `_build_config` 改字段名：
```python
patches = (os.getenv("DSH_CORDIS_CONFIG"),) if os.getenv("DSH_CORDIS_CONFIG") else ()
```

## 5. provider / model 路由（qwen/kimi/openrouter）

- rc.6：`provider="openai"` + env 透传 `LLM_API_KEY` / `LLM_API_BASE` 走 OpenAI 兼容端点
- v0.1.2-alpha.2：**待实测**。pi-ai 0.82.1 → 0.83+ 升级可能要求 provider 在 profile 里注册
- 阶段 3 dev 联调时必须验证 qwen/kimi/openrouter 任一模型能调通
- **降级方案**：如 OpenAI 兼容 provider 在 v0.1.2 失效，回退到 deepseek-only + openrouter（已用 OpenRouter 走 `minimax:free` 系列验证可行）
