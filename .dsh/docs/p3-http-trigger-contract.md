# P3 HTTP 触发契约（dsh-engine ↔ backend Orchestrator）

> 状态：P3 定稿 · 日期：2026-08-14 · 载体：`scripts/dsh_p3/sdk_host.py`（服务端）与
> `backend/agents/dsh_orchestrator.py` `HttpDshRunner`（客户端）共用本契约。

## POST {DSH_ENGINE_URL}/trigger

请求 JSON：

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "context": {"quote": {}, "financials": [], "news": [], "industry_category": "白酒",
              "current_price": 1700.0, "total_market_cap": 21400.0,
              "total_shares": 12.56, "net_profit_parent": 74.0, "net_profit_deducted": 73.0},
  "model": "deepseek-v4-flash",
  "session_id": "600519-2026-08-14",
  "pe_low_override": null,
  "pe_high_override": null,
  "ralph_enabled": false,
  "api_keys": {"deepseek": "sk-...", "qwen": "sk-...", "kimi": "sk-..."}
}
```

响应 JSON：

```json
{
  "result": {
    "analyze_qualitative": {"qualitative_analysis": "...", "business_model": {...}},
    "run_reverse_checklist": {"conclusions": {...}, "major_risks": [...], "checklist_veto": false, "overall_assessment": "..."},
    "anchor_industry_pe": {"pe_low": 18.0, "pe_high": 22.0, "pe_rationale": "...", "annual_profit_low": 32.0, "distance_pct": 10.0, "signal": "yellow", "signal_label": "观察区"},
    "output_conclusion": {"conclusion": "...", "recommendation": "...", "final_rating": "🟡", "action_items": [...]}
  },
  "model": "deepseek-v4-flash",
  "usage": {"input_tokens": 1000, "output_tokens": 500, "prompt_cache_hit_tokens": 790},
  "compaction": {"triggered": false, "count": 0, "shadowed_tokens": 0,
                 "summary_output_tokens": 0, "ratio": null},
  "degraded": false,
  "error": null
}
```

字段语义：`result` = 五段 stage 键（与前端 stage_results 契约逐字一致）；`model` = 真实路由模型
（`request/context` 事件，非配置默认值，I6）；`usage` = `assistant/chunk` usage 累加（I7）；
`compaction` = D5 上下文压缩监控（`compaction/*` trace 事件提取，`triggered` 是否触发 +
`ratio` 压缩比例近似）；`degraded` = SDK 宿主内部降级（如 DSH 会话失败但宿主仍有兜底输出）；
`error` = 宿主捕获的错误文本。

`ralph_enabled`（P4 新增，缺省 `false`）：深度模式开关。Orchestrator 在 `model == "deepseek-v4-pro"` 时
置 `true`；`sdk_host` 经提示词透传给模型填 `invest-five-stage` 工具参数。开启时 `result` 附加**顶层键**
`ralph_review`（`{passed, issues, revision}`），不侵入 4 个 stage 键；关闭时 `result` 与上表完全一致。

`api_keys`（P4 新增，缺省空对象 `{}`）：后端透传的厂商 key（`{deepseek|qwen|kimi}`），DSH 引擎按
`model` 对应厂商取用；缺省空对象时回退引擎 env（`{VENDOR}_API_KEY`）。

> ⚠️ 上表请求/响应字段为**契约定稿**，Task 6 `sdk_host.py` 与 Task 3 `DshOrchestrator.analyze` 必须与之一致。
