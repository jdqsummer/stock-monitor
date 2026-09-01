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
    extract_compaction,
    extract_five_stage_result,
    extract_model,
    extract_usage,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="dsh-engine SDK 宿主")

# 模型 → 厂商映射（wire 名 = 真实模型名，用户确认）
MODEL_PROVIDER = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "Qwen3.7-Max": "qwen",
    "Qwen3.8-Max": "qwen",
    "Kimi-K2.6": "kimi",
    "Kimi-K2.7": "kimi",
    # OpenRouter 免费档（多供应商聚合；走 OpenAI 兼容 + OpenRouter 端点）
    "minimax/minimax-m2.7:free": "openrouter",
    "minimax/minimax-m3:free": "openrouter",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "openrouter",
}

# 厂商 → OpenAI 兼容 base_url（qwen/kimi/openrouter）；deepseek 走原生 provider
OPENAI_BASE = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# 厂商 → api_keys 字段名（snake_case，与后端 UserConfig / Task 9 生产者一致）
VENDOR_KEY_FIELD = {
    "deepseek": "deepseek_api_key",
    "qwen": "qwen_api_key",
    "kimi": "kimi_api_key",
    "openrouter": "openrouter_api_key",   # 当前未启用（key 走 OPENROUTER_API_KEY env 直读，不入用户配置表）
}


class TriggerRequest(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = ""
    context: dict = {}
    model: str = "deepseek-v4-flash"
    session_id: str = ""
    pe_low_override: float | None = None
    pe_high_override: float | None = None
    ralph_enabled: bool = False   # Q3 深度自审（V4-Pro 深度模式）
    api_keys: dict[str, str] = {}   # 厂商 key 透传：{deepseek_api_key|qwen_api_key|kimi_api_key: key}


class TriggerResponse(BaseModel):
    result: dict
    model: str
    usage: dict
    compaction: dict = {}   # D5 压缩监控（extract_compaction：是否触发 + 压缩比例近似）
    degraded: bool
    error: str | None = None


def _build_prompt(req: TriggerRequest) -> str:
    pe_hint = ""
    if req.pe_low_override is not None and req.pe_high_override is not None:
        pe_hint = (f"\n敏感性场景：请使用 PE 区间 {req.pe_low_override}-{req.pe_high_override} "
                   f"（覆盖 LLM 自设区间，仅本次敏感性重跑）。")
    ralph_hint = ""
    if req.ralph_enabled:
        ralph_hint = ("\n深度模式：请将 invest-five-stage 工具的 ralph_enabled 置为 true，"
                      "在五段结论后执行 Ralph 自审。")
    position_hint = ""
    if (req.context or {}).get("analysis_mode") == "position":
        position_hint = ("\n这是持仓卖出分析：请让 invest-five-stage 工具按持仓模式执行，"
                         "第 4 段给出卖出分析（4 条卖出原则判断 + 卖出PE区间），第 5 段给出"
                         "总结与建议（继续持有/建议卖出/立即卖出 + 行动建议）。")
    # context 以 JSON 字符串呈现（ensure_ascii=False），模型原样透传给工具的 context 参数
    #（工具参数已改为必填；Python dict repr 不是合法 JSON，模型无法可靠转发）。
    import json as _json
    context_json = _json.dumps(req.context, ensure_ascii=False)
    return (
        f"对 {req.code}（{req.name or ''}）执行价值投资五段式安全边际分析。\n"
        f"请调用 invest-five-stage 工具（stock_code={req.code}, stock_name={req.name or ''}），"
        f"必须把下面的只读上下文原样作为该工具的 context 参数传入（JSON 字符串，勿改字段）。\n"
        f"注入的只读上下文（由 Python collect_data 预聚合，勿自行读盘）：\n"
        f"{context_json}\n{pe_hint}{ralph_hint}{position_hint}"
    )


def run_harness(config, input_text: str, session_id: str):
    """包一层便于测试 monkeypatch。生产：DeepSeekHarness(config).run(...)。"""
    from deepseek_harness import DeepSeekHarness
    with DeepSeekHarness(config) as harness:
        return harness.run(input_text, session_id=session_id)


@app.get("/health")
async def health():
    """DSH 进程级健康检查：必备 env + 至少一个 LLM key 是否就绪。

    P0 验证建议：原 compose 用 /openapi.json 探活，仅验证 FastAPI 启动，无法判断
    DeepSeekHarness subprocess 与 cordis 插件树是否真就绪（P4 坑位 17：插件树
    激活失败时 /trigger 仍可响应但五段永不返回）。本端点至少把「DSH 必备 env 缺失」
    提前到 healthcheck 阶段暴露，避免 healthcheck 30s 绿但 /trigger 实际挂死。

    深度激活探测：可选的 `?probe=1` 会跑一次最小 DSH harness 调用（最快模型），
    用于在冷启动后确认 cordis 插件树真激活。默认关闭以免被 healthcheck 频繁触发。
    """
    cordis_ready = bool(os.getenv("DSH_CORDIS_CONFIG"))
    has_llm_key = bool(
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("KIMI_API_KEY")
    )
    ok = cordis_ready and has_llm_key
    payload = {
        "status": "ok" if ok else "degraded",
        "cordis_ready": cordis_ready,
        "has_llm_key": has_llm_key,
    }
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.post("/trigger", response_model=TriggerResponse)
async def trigger(req: TriggerRequest):
    session_id = req.session_id or f"{req.code}-default"
    try:
        config = _build_config(req)
        result = await _run_harness_async(config, _build_prompt(req), session_id)
        events = result.events or []
        five_stage = extract_five_stage_result(events)
        compaction = extract_compaction(events)
        if five_stage is None:
            return TriggerResponse(result={}, model=extract_model(events),
                                   usage=extract_usage(events), compaction=compaction,
                                   degraded=True,
                                   error="未找到 invest-five-stage 工具输出（五段未完成）")
        return TriggerResponse(result=five_stage, model=extract_model(events) or req.model,
                               usage=extract_usage(events), compaction=compaction,
                               degraded=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("trigger 失败")
        return TriggerResponse(result={}, model="", usage={}, degraded=True, error=str(exc))


def _build_config(req: TriggerRequest):
    """构造 DeepSeekHarnessConfig；按模型厂商注入对应 API Key（透传优先，env 兜底）。

    ⚠️ 字段集保持 rc.6 兼容：尽管 npm 升到 0.1.2-alpha.2（vendored 源码含 dsh_home/patches/profile 等
    新字段），PyPI 0.1.1rc1 实际仍是 rc.6 字段集（14 个字段，验证：dataclasses.fields() 无 dsh_home）。
    跨主版本错配下回退 rc.6 字段命名，待 PyPI 发 0.1.2 wheel 后再切到新字段。

    env 注入：DSH_CORDIS_CONFIG（value-investor 组合）由 DeepSeekHarness(cordis=...) 或
    DSH_CORDIS_CONFIG 环境变量承载（P0 T4：headless 默认 rosterless 不挂 preset）。

    qwen/kimi 走 provider="openai" + env 注入 {VENDOR}_API_KEY / LLM_API_KEY /
    LLM_API_BASE（= OPENAI_BASE[vendor]）。
    """
    from deepseek_harness import DeepSeekHarnessConfig
    vendor = MODEL_PROVIDER.get(req.model or "", "deepseek")
    key_field = VENDOR_KEY_FIELD.get(vendor, VENDOR_KEY_FIELD["deepseek"])
    key = (req.api_keys or {}).get(key_field) or os.getenv(f"{vendor.upper()}_API_KEY", "")
    env = dict(os.environ)
    env[f"{vendor.upper()}_API_KEY"] = key
    if key:
        env["LLM_API_KEY"] = key          # 兜底：兼容 SDK 通用 key 读取路径
    if vendor != "deepseek":
        env["LLM_API_BASE"] = OPENAI_BASE[vendor]   # qwen/kimi/openai 兼容 base_url
    # provider 字段映射到 DSH runtime 的 LLM route 名：deepseek → llm-deepseek
    # 自有 route；其他 → dsh-llm-pi-ai 的 catalog route（同 vendor 字符串）
    # 例如 vendor="openrouter" → provider="openrouter"（dsh-llm-pi-ai 的 openrouter route）
    return DeepSeekHarnessConfig(
        provider="deepseek-official" if vendor == "deepseek" else vendor,
        model=req.model or "deepseek-v4-flash",
        cordis=os.getenv("DSH_CORDIS_CONFIG"),
        session_root=os.getenv("DSH_SESSION_ROOT"),
        env=env,
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
