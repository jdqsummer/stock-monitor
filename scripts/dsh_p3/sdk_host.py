"""dsh-engine 容器内 SDK 宿主：HTTP 触发端点（P3 桥接，部署拓扑「容器内 SDK 宿主 + HTTP 触发」）。

契约见 .dsh/docs/p3-http-trigger-contract.md。服务端把「提示词 + 五段工具触发」封装为一次
POST /trigger：包 DeepSeekHarness 跑一轮会话，模型调用 invest-five-stage 工具，从会话事件
提取五段结构化结果（tool/result）与真实模型（request/context）、用量（assistant/chunk usage）。

运行环境：真实 DSH runtime exe 仅 linux/macos x64/arm64（P0 T6）。Windows 本地联调用
fake_runtime（scripts/dsh_p0/t6_sdk/fake_runtime.py）做协议级冒烟，真实五段需 WSL2/Docker
linux runtime（I1 开发环境三路径）。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

# 把 SDK 源码加到 sys.path（生产为 deepseek-harness-runtime-bin wheel 安装的 sdk 包；
# 本仓库开发期用 scripts/dsh_p0/deepseek-harness/python/sdk/src）
_HERE = Path(__file__).resolve().parent
_SDK_SRC = _HERE.parent / "dsh_p0" / "deepseek-harness" / "python" / "sdk" / "src"
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

from backend.agents.dsh_events import (  # noqa: E402
    extract_five_stage_result,
    extract_model,
    extract_usage,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="dsh-engine SDK 宿主")


class TriggerRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = ""
    context: dict = {}
    model: str = "deepseek-v4-flash"
    session_id: str = ""
    pe_low_override: float | None = None
    pe_high_override: float | None = None


class TriggerResponse(BaseModel):
    result: dict
    model: str
    usage: dict
    degraded: bool
    error: str | None = None


def _build_prompt(req: TriggerRequest) -> str:
    pe_hint = ""
    if req.pe_low_override is not None and req.pe_high_override is not None:
        pe_hint = (f"\n敏感性场景：请使用 PE 区间 {req.pe_low_override}-{req.pe_high_override} "
                   f"（覆盖 LLM 自设区间，仅本次敏感性重跑）。")
    return (
        f"对 {req.code}（{req.name or ''}）执行价值投资五段式安全边际分析。\n"
        f"请调用 invest-five-stage 工具（stock_code={req.code}, stock_name={req.name or ''}），"
        f"工具会注入只读上下文并跑固定五段 pipeline。\n"
        f"注入的只读上下文（由 Python collect_data 预聚合，勿自行读盘）：\n"
        f"{req.context}\n{pe_hint}"
    )


def run_harness(config, input_text: str, session_id: str):
    """包一层便于测试 monkeypatch。生产：DeepSeekHarness(config).run(...)。"""
    from deepseek_harness import DeepSeekHarness
    with DeepSeekHarness(config) as harness:
        return harness.run(input_text, session_id=session_id)


@app.post("/trigger", response_model=TriggerResponse)
async def trigger(req: TriggerRequest):
    session_id = req.session_id or f"{req.code}-default"
    try:
        config = _build_config(req)
        result = await _run_harness_async(config, _build_prompt(req), session_id)
        events = result.events or []
        five_stage = extract_five_stage_result(events)
        if five_stage is None:
            return TriggerResponse(result={}, model=extract_model(events),
                                   usage=extract_usage(events), degraded=True,
                                   error="未找到 invest-five-stage 工具输出（五段未完成）")
        return TriggerResponse(result=five_stage, model=extract_model(events) or req.model,
                               usage=extract_usage(events), degraded=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("trigger 失败")
        return TriggerResponse(result={}, model="", usage={}, degraded=True, error=str(exc))


def _build_config(req: TriggerRequest):
    """构造 DeepSeekHarnessConfig（含 cordis 组合 / model / session_root）。

    env 注入：DSH_CORDIS_CONFIG（value-investor 组合）由 DeepSeekHarness(cordis=...) 或
    DSH_CORDIS_CONFIG 环境变量承载（P0 T4：headless 默认 rosterless 不挂 preset）。
    """
    from deepseek_harness import DeepSeekHarnessConfig
    return DeepSeekHarnessConfig(
        provider="deepseek-official",
        model=req.model or "deepseek-v4-flash",
        cordis=os.getenv("DSH_CORDIS_CONFIG"),
        session_root=os.getenv("DSH_SESSION_ROOT"),
        env=dict(os.environ),
    )


async def _run_harness_async(config, input_text: str, session_id: str):
    """run_harness 是同步阻塞（subprocess stdio）；在 worker 线程跑，避免阻塞事件循环。

    兼容测试侧 async monkeypatch（fake_run 返回 coroutine，先在线程里产出再 await）与
    生产侧同步 run_harness（to_thread 直接返回 RunResult）两种形状。
    """
    import asyncio
    result = await asyncio.to_thread(run_harness, config, input_text, session_id)
    if asyncio.iscoroutine(result):
        return await result
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DSH_ENGINE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
