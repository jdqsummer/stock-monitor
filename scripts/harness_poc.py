"""PoC：用真实 DeepSeek 通过开源 harness 跑一次最小分析（手动运行）
用法: DEEPSEEK_API_KEY=xxx python scripts/harness_poc.py 600519
"""
import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)  # 使 `backend.*` 可导入
sys.path.insert(0, os.path.join(_ROOT, "vendor"))  # 使 `openharness.*` 可导入

from backend.agents.harness_component import collect_final_text, create_harness_engine, parse_output_json
from openharness.tools.base import ToolRegistry


SYSTEM_PROMPT = (
    "你是价值投资分析智能体。请用一段话分析输入股票的护城河与安全边际，"
    "最后以 ```json 输出 {\"final_rating\": \"🟢/🟡/🔴\", \"rationale\": \"一句话理由\"}。"
)


async def main(code: str) -> None:
    # 1) 构造 DeepSeek api_client —— 按 Task2 Step1 读到的 vendor 源码补全
    api_client = _build_deepseek_client()
    engine = create_harness_engine(
        api_client=api_client,
        tools=ToolRegistry(),                      # PoC 不注册工具，只验引擎
        model="deepseek-chat",
        system_prompt=SYSTEM_PROMPT,
        cwd=os.getcwd(),
        max_turns=5,
    )
    final_text, events = await collect_final_text(engine, f"分析股票 {code}")
    print("== 事件数:", len(events))
    print("== 最终文本:\n", final_text)
    print("== 解析:", parse_output_json(final_text))


def _build_deepseek_client():
    """构造 DeepSeek 的 OpenAI 兼容 api_client（base_url=https://api.deepseek.com/v1）。

    复用 vendor/openharness/api/openai_client.py 的 OpenAICompatibleClient：
    它实现 SupportsStreamingMessages 协议，是 AnthropicApiClient 的无头替代。
    """
    from openharness.api.openai_client import OpenAICompatibleClient

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 DEEPSEEK_API_KEY 环境变量")
    return OpenAICompatibleClient(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "600519"))
