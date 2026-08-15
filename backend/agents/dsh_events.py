# stock-monitor/backend/agents/dsh_events.py
"""DSH 会话事件解析纯函数 —— 从 SDK RunResult.events 提取五段结果/真实模型/用量。

事件形状以 scripts/dsh_p0/_session_decomp.jsonl 实测为准（见 Global Constraints）。
全部为纯函数：输入 events list，输出提取值，零副作用，可单测。
"""
from __future__ import annotations

import json
from typing import Any


def extract_five_stage_result(events: list[dict]) -> dict | None:
    """找到 invest-five-stage 工具的 tool/result，解析其文本内容为五段 JSON。

    tool/result 不含工具名，须先由 tool/call 的 data.callId ↔ data.message.source.callId 关联。
    """
    call_ids: set[str] = set()
    for ev in events:
        if ev.get("type") != "tool/call":
            continue
        data = ev.get("data") or {}
        if data.get("name") == "invest-five-stage":
            call_ids.add(data.get("callId"))
    if not call_ids:
        return None
    for ev in events:
        if ev.get("type") != "tool/result":
            continue
        source = ((ev.get("data") or {}).get("message") or {}).get("source") or {}
        if source.get("kind") != "tool" or source.get("callId") not in call_ids:
            continue
        content = ((ev.get("data") or {}).get("message") or {}).get("content") or []
        for block in content:
            inner = (block.get("content") if isinstance(block, dict) else None) or []
            for text_block in inner:
                if isinstance(text_block, dict) and text_block.get("type") == "text":
                    try:
                        parsed = json.loads(text_block.get("text") or "")
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, TypeError):
                        continue
    return None


def extract_model(events: list[dict]) -> str:
    """真实路由模型：request/context 事件 data.model（回传 analysis_model 用，非配置默认值）。"""
    for ev in events:
        if ev.get("type") == "request/context":
            data = ev.get("data") or {}
            if data.get("model"):
                return str(data["model"])
    return ""


def extract_usage(events: list[dict]) -> dict:
    """用量汇总：assistant/chunk 的 usage 块累加（I7 成本监控输入）。"""
    total = {"input_tokens": 0, "output_tokens": 0, "prompt_cache_hit_tokens": 0}
    for ev in events:
        if ev.get("type") != "assistant/chunk":
            continue
        chunk = (ev.get("data") or {}).get("chunk") or {}
        if chunk.get("type") != "usage":
            continue
        usage = chunk.get("usage") or {}
        total["input_tokens"] += int(usage.get("inputTokens") or 0)
        total["output_tokens"] += int(usage.get("outputTokens") or 0)
        total["prompt_cache_hit_tokens"] += int(usage.get("cacheReadTokens") or 0)
    return total


def extract_compaction(events: list[dict]) -> dict:
    """D5 上下文压缩监控：统计 compression/* trace 事件。

    rc.6 会话事件流含压缩 trace 事件（@deepseek-ai/dsh-compaction/types.ts，log-only 不进 surface）：
      - compaction/start    {compactionId, sourceCommandId?, turn}  标记一次压缩开始
      - compaction/summary  {summary, shadowedRange, shadowedSeqs, shadowedTokenCount,
                             provider, model, maxTokens?, usage?}   shadowedTokenCount=压缩前 token 估计
      - compaction/end      {compactionId, error?}                  压缩结束（error 记录失败）
      - compaction/prune    {shadowedRange, shadowedSeqs, shadowedTokenCount}  模型无关剪枝 shadow price

    「是否触发」= compaction/start 计数>0；「压缩比例」无单一直接字段，用
    shadowedTokenCount（压缩前）与 summary.usage.outputTokens（压缩后摘要规模，近似）推导，
    两者缺一记为 None（诚实标注近似，非精确比例）。
    """
    total = {
        "triggered": False,
        "count": 0,
        "shadowed_tokens": 0,
        "summary_output_tokens": 0,
        "ratio": None,
    }
    for ev in events:
        ev_type = ev.get("type")
        data = ev.get("data") or {}
        if ev_type == "compaction/start":
            total["count"] += 1
        elif ev_type in ("compaction/summary", "compaction/prune"):
            total["shadowed_tokens"] += int(data.get("shadowedTokenCount") or 0)
            if ev_type == "compaction/summary":
                usage = data.get("usage") or {}
                total["summary_output_tokens"] += int(usage.get("outputTokens") or 0)
    total["triggered"] = total["count"] > 0
    if total["shadowed_tokens"] > 0 and total["summary_output_tokens"] > 0:
        total["ratio"] = round(1 - total["summary_output_tokens"] / total["shadowed_tokens"], 4)
    return total
