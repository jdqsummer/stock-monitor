import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.provider import LLMFactory
from backend.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# ── 蒸馏 Prompt 模板 ──

L1_EXTRACTION_PROMPT = """从以下对话中提取用户的投资偏好和事实信息，每条一行：

对话内容：
{conversation_text}

提取规则：
- 只提取事实性信息和明确的偏好表述
- 格式：category | content
- category 可选：关注行业、关注股票、投资偏好、风险偏好、个人约束

输出示例：
关注行业 | 用户关注半导体、白酒、新能源行业
关注股票 | 用户持有贵州茅台，关注比亚迪
投资偏好 | 用户偏好大盘蓝筹股，重视 ROE 指标

请提取（无则输出"无"）："""

L2_STRATEGY_PROMPT = """从以下用户的投资行为和决策中，归纳投资策略模式：

对话内容：
{conversation_text}

请归纳：
1. 用户的选股模式（关注什么类型的公司/行业）
2. 用户的交易习惯（追涨/抄底/定投/分批）
3. 用户的决策风格（数据驱动/直觉驱动/跟风）
4. 用户的行为偏差（过度交易/锚定效应/损失厌恶/确认偏差）

输出一段简洁的策略总结（不超过 200 字）："""

L3_PROFILE_PROMPT = """基于以下用户所有 L1 偏好和 L2 策略信息，生成一份用户投资画像（不超过 300 字）：

L1 偏好信息：
{l1_memories}

L2 策略信息：
{l2_memories}

投资画像应包含：
1. 投资风格标签（价值/成长/均衡/投机）
2. 风险承受度（保守/稳健/激进）
3. 关注行业 Top 3
4. 行为模式特征
5. 需要警惕的认知偏差

输出："""


class DistillationPipeline:
    """
    异步蒸馏管道。

    工作流：
    1. 对话/分析结束 → 触发 distill_conversation()
    2. LLM 提取 L1 事实 + L2 策略
    3. 写入 L1/L2 记忆（upsert 去重）
    4. 定期（每周）触发 build_L3_profile()
    5. LLM 整合 L1 + L2 → 生成 L3 画像
    """

    def __init__(self, llm_model: str = "deepseek-chat"):
        self.llm_model = llm_model

    async def distill_conversation(
        self, db: AsyncSession, user_id: str, conversation_text: str
    ) -> dict[str, Any]:
        """从对话中蒸馏 L1 和 L2 记忆"""
        llm = LLMFactory.create(self.llm_model)
        result = {"L1": [], "L2": []}

        # ── 提取 L1 事实/偏好 ──
        try:
            l1_resp = await llm.chat([
                {"role": "user", "content": L1_EXTRACTION_PROMPT.format(conversation_text=conversation_text[:4000])}
            ])
            l1_text = l1_resp.content if hasattr(l1_resp, 'content') else str(l1_resp)

            for line in l1_text.strip().split("\n"):
                line = line.strip()
                if "|" in line and line != "无":
                    category, content = line.split("|", 1)
                    memory = await MemoryStore.upsert_memory_by_category(
                        db, user_id, "L1",
                        category=category.strip(),
                        content=content.strip(),
                        source="distillation",
                        confidence=0.7,
                    )
                    result["L1"].append({"category": category.strip(), "id": memory.id})
        except Exception as e:
            logger.error(f"L1 蒸馏失败: {e}")

        # ── 提取 L2 策略模式 ──
        try:
            l2_resp = await llm.chat([
                {"role": "user", "content": L2_STRATEGY_PROMPT.format(conversation_text=conversation_text[:4000])}
            ])
            l2_text = l2_resp.content if hasattr(l2_resp, 'content') else str(l2_resp)

            memory = await MemoryStore.upsert_memory_by_category(
                db, user_id, "L2",
                category="投资策略",
                content=l2_text.strip(),
                source="distillation",
                confidence=0.6,
            )
            result["L2"].append({"id": memory.id, "content": l2_text.strip()[:200]})
        except Exception as e:
            logger.error(f"L2 蒸馏失败: {e}")

        return result

    async def build_L3_profile(
        self, db: AsyncSession, user_id: str
    ) -> str:
        """整合 L1 + L2 → 生成 L3 用户画像"""
        l1_memories = await MemoryStore.get_memories(db, user_id, level="L1", limit=50)
        l2_memories = await MemoryStore.get_memories(db, user_id, level="L2", limit=20)

        l1_text = "\n".join(f"- [{m.category}] {m.content}" for m in l1_memories)
        l2_text = "\n".join(f"- {m.content}" for m in l2_memories)

        if not l1_text and not l2_text:
            logger.info(f"用户 {user_id} 无足够数据生成 L3 画像")
            return "暂无足够数据"

        llm = LLMFactory.create(self.llm_model)
        prompt = L3_PROFILE_PROMPT.format(l1_memories=l1_text, l2_memories=l2_text)

        try:
            profile_resp = await llm.chat([{"role": "user", "content": prompt}])
            profile_text = profile_resp.content if hasattr(profile_resp, 'content') else str(profile_resp)
            await MemoryStore.upsert_memory_by_category(
                db, user_id, "L3",
                category="投资画像",
                content=profile_text.strip(),
                source="L3_pipeline",
                confidence=0.8,
            )
            logger.info(f"用户 {user_id} 的 L3 画像已更新")
            return profile_text.strip()
        except Exception as e:
            logger.error(f"L3 画像生成失败: {e}")
            return ""
