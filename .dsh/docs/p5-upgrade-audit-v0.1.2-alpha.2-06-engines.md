# P5-F: engines / models 兼容性（v0.1.2-alpha.2 实测）

> 调研日期：2026-08-31
> 源码来源：vendored `scripts/dsh_p0/deepseek-harness`（commit 0a53fb55）
> 结论标签：**additive**（引擎要求未变；model 路由待实测）

## 1. Node engines

- rc.6 隐式要求 Node ≥ 22（项目 `dsh-engine/package.json` 锁 `>=22.15.0`）
- v0.1.2-alpha.2 显式要求 Node ≥ 22.x（实测 `packages/sdk/client/package.json` 与 `packages/bundle/sdk-app/package.json`）
- 项目当前 lockfile Node 22.15.0 **仍兼容**

## 2. Python SDK engines

- v0.1.2-alpha.2（PyPI `0.1.1rc1`）`requires_python = ">=3.10"`，需 pydantic < 3, >= 2.12
- 项目 requirements.txt 锁 `pydantic==2.12.3` **兼容**

## 3. pi-ai 模型目录（v0.1.2-alpha.2 实测）

`packages/llm/llm-pi-ai/` 包含 model provider 注册：
- `deepseek-official` adapter
- `openai` 兼容 provider（含 qwen/kimi/openrouter）
- v0.1.2-alpha.2 升级 pi-ai 0.82.1 → 0.83+（changelog 显示）

**风险**：
- openrouter free model ID 列表可能漂移（项目用 `minimax/minimax-m3:free` 等）
- qwen/kimi 走 OpenAI 兼容端点可能需要 `LLM_API_KEY` + `LLM_API_BASE` 显式注册

## 4. 对项目的影响

### 4.1 `scripts/dsh_p3/sdk_host.py` 的 `MODEL_PROVIDER` 字典

```python
MODEL_PROVIDER = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "Qwen3.7-Max": "qwen",
    "Qwen3.8-Max": "qwen",
    "Kimi-K2.6": "kimi",
    "Kimi-K2.7": "kimi",
    "minimax/minimax-m2.7:free": "openrouter",
    "minimax/minimax-m3:free": "openrouter",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "openrouter",
}
```

v0.1.2-alpha.2 应仍识别 `deepseek-v4-flash` / `deepseek-v4-pro`（实测 v0.1.2 仍支持 deepseek-official provider）。

**qwen/kimi/openrouter 走 OpenAI 兼容 provider 路径**：
- rc.6：`provider="openai"` + env 透传 `LLM_API_KEY` + `LLM_API_BASE`
- v0.1.2-alpha.2：可能仍 work（pi-ai 0.83+ 仍含 openai 兼容 provider），**但**显式 base_url 注入可能要求走 `pi-ai` 适配器而非裸 OpenAI

**降级方案**：如 v0.1.2 实测 qwen/kimi 失效，回退 deepseek-only 走 OpenRouter 跑 free model（项目已用 `minimax:free` 系列验证）。

## 5. 升级建议

- **不修改** sdk_host.py 的 `MODEL_PROVIDER` 字典
- 阶段 3 dev 联调时**必跑** OpenRouter free model 验证（无需 API key 余额）
- 如 qwen/kimi 走 OpenAI 兼容失效，记录到 `.dsh/docs/d5-upgrade-audit.md`

## 6. 验证

```bash
# 阶段 3 验证：触发 openrouter free model 分析
curl -X POST http://localhost:8000/api/analysis/analyze \
  -d '{"stock_code":"600519","model":"openrouter:minimax/minimax-m3:free"}'
# 期望: 落库 analysis_model = "minimax/minimax-m3:free"
```
