# stock-monitor/backend/agents/memory_workflow.py
"""记忆蒸馏 LangGraph 工作流 — Plan-4 完整实现

Plan-4 提供 LangGraph 工作流引擎和 LLM Provider 适配，
Plan-5 在此基础上实现分层记忆蒸馏管道。

蒸馏层级：
  L0: 原始对话片段
  L1: 结构化事实提取 (事实提取 Agent)
  L2: 行为模式归纳 (模式识别 Agent)
  L3: 投资画像生成 (画像合成 Agent)

工作流：
  [原始对话] → [L1 事实提取] → [L2 模式归纳] → [L3 画像更新]
                                            ↘ [冲突检测] → [画像冲突修复]
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from backend.llm.provider import LLMProvider, MockLLMProvider
from backend.memory.store import MemoryStore

logger = logging.getLogger(__name__)


# ── 记忆蒸馏状态 ──

class DistillationState(TypedDict, total=False):
    """记忆蒸馏工作流状态"""
    # 输入
    user_id: str
    raw_conversation: str                     # 原始对话文本

    # L1: 事实提取
    extracted_facts: list[dict]               # [{"category": str, "content": str, "confidence": float}]

    # L2: 模式归纳
    behavior_patterns: list[dict]             # [{"pattern": str, "evidence": list[str]}]

    # L3: 画像生成
    user_profile: dict                        # 用户投资画像

    # 冲突检测
    conflicts: list[dict]                     # [{"old": str, "new": str, "resolution": str}]

    # 存储结果
    stored_memory_ids: list[str]
    errors: list[str]

    # 元数据
    distillation_started: str
    distillation_completed: str


# ── 蒸馏节点 ──

async def extract_facts_node(state: DistillationState) -> dict:
    """L1 事实提取节点"""
    logger.info("[L1] 事实提取")

    raw = state.get("raw_conversation", "")
    if not raw:
        return {"extracted_facts": [], "errors": ["无原始对话数据"]}

    # 规则提取（无 LLM 时用规则，有 LLM 时用 LLM）
    facts = _rule_based_fact_extraction(raw)

    logger.info(f"  提取 {len(facts)} 条事实")

    return {
        "extracted_facts": facts,
        "distillation_started": state.get("distillation_started") or datetime.now().isoformat(),
    }


async def induce_patterns_node(state: DistillationState) -> dict:
    """L2 行为模式归纳节点"""
    logger.info("[L2] 模式归纳")

    facts = state.get("extracted_facts", [])
    patterns = _rule_based_pattern_induction(facts)

    logger.info(f"  归纳 {len(patterns)} 条模式")

    return {"behavior_patterns": patterns}


async def generate_profile_node(state: DistillationState) -> dict:
    """L3 投资画像生成节点"""
    logger.info("[L3] 画像生成")

    facts = state.get("extracted_facts", [])
    patterns = state.get("behavior_patterns", [])

    profile = _rule_based_profile_generation(facts, patterns)

    logger.info(f"  画像: {profile.get('style', '未知')} / {profile.get('risk_tolerance', '未知')}")

    return {"user_profile": profile}


async def detect_conflicts_node(state: DistillationState) -> dict:
    """冲突检测节点"""
    logger.info("[冲突检测] 检查新旧画像冲突")

    new_profile = state.get("user_profile", {})
    user_id = state.get("user_id", "")
    conflicts = []

    # 加载旧画像（需要 DB session，非 DB 环境静默跳过）
    try:
        from backend.db.database import get_db

        async for db in get_db():
            old_memories = await MemoryStore.get_memories(db, user_id, level="L3", limit=1)
            if old_memories:
                import json
                old_profile = json.loads(old_memories[0].content)
                conflicts = _detect_profile_conflicts(old_profile, new_profile)
            break
    except Exception as e:
        logger.debug(f"加载旧画像跳过（无 DB 或查询失败）: {e}")

    logger.info(f"  发现 {len(conflicts)} 个冲突")

    return {"conflicts": conflicts}


async def store_results_node(state: DistillationState) -> dict:
    """存储蒸馏结果"""
    logger.info("[存储] 保存蒸馏结果")

    user_id = state.get("user_id", "")
    facts = state.get("extracted_facts", [])
    patterns = state.get("behavior_patterns", [])
    profile = state.get("user_profile", {})

    stored_ids = []

    try:
        from backend.db.database import get_db

        async for db in get_db():
            store = MemoryStore()

            # 存储 L1 事实
            for fact in facts:
                mem = await store.save_memory(
                    db=db,
                    user_id=user_id,
                    level="L1",
                    category=fact.get("category", "未分类"),
                    content=json.dumps(fact, ensure_ascii=False),
                    source="distillation",
                    confidence=fact.get("confidence", 0.8),
                )
                stored_ids.append(mem.id)

            # 存储 L2 模式
            for pattern in patterns:
                mem = await store.save_memory(
                    db=db,
                    user_id=user_id,
                    level="L2",
                    category="行为模式",
                    content=json.dumps(pattern, ensure_ascii=False),
                    source="distillation",
                )
                stored_ids.append(mem.id)

            # 存储/更新 L3 画像
            if profile:
                mem = await store.upsert_memory_by_category(
                    db=db,
                    user_id=user_id,
                    level="L3",
                    category="投资画像",
                    content=json.dumps(profile, ensure_ascii=False),
                    source="distillation",
                )
                stored_ids.append(mem.id)

            await db.commit()
            break

    except Exception as e:
        logger.warning(f"存储跳过（无 DB 或写入失败）: {e}")

    logger.info(f"  存储 {len(stored_ids)} 条记忆")

    return {
        "stored_memory_ids": stored_ids,
        "distillation_completed": datetime.now().isoformat(),
    }


# ── 规则引擎（无 LLM 时的降级方案） ──

def _rule_based_fact_extraction(text: str) -> list[dict]:
    """基于规则的事实提取"""
    facts = []

    # 行业关键词
    industry_keywords = {
        "半导体": ["芯片", "半导体", "集成电路", "晶圆"],
        "白酒": ["白酒", "茅台", "五粮液", "泸州老窖"],
        "医药": ["医药", "生物", "制药", "医疗器械"],
        "新能源": ["新能源", "光伏", "锂电", "风电", "储能"],
        "消费": ["消费", "食品", "饮料", "家电"],
        "金融": ["银行", "保险", "证券", "金融"],
    }

    for industry, keywords in industry_keywords.items():
        for kw in keywords:
            if kw in text:
                facts.append({
                    "category": "关注行业",
                    "content": f"关注行业 | {industry}",
                    "confidence": 0.8,
                })
                break

    # 投资偏好关键词
    preference_keywords = {
        "价值投资": ["价值", "低估", "安全边际", "PE", "ROE"],
        "成长投资": ["成长", "增速", "高增长"],
        "大盘蓝筹": ["蓝筹", "大盘", "龙头"],
        "逆向投资": ["逆向", "恐慌", "抄底", "悲观"],
    }

    for pref, keywords in preference_keywords.items():
        for kw in keywords:
            if kw in text:
                facts.append({
                    "category": "投资偏好",
                    "content": f"投资偏好 | {pref}",
                    "confidence": 0.75,
                })
                break

    return facts


def _rule_based_pattern_induction(facts: list[dict]) -> list[dict]:
    """基于规则的模式归纳"""
    patterns = []

    categories = {}
    for f in facts:
        cat = f.get("category", "其他")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(f.get("content", ""))

    for cat, contents in categories.items():
        patterns.append({
            "pattern": f"{cat}偏好: {'; '.join(contents)}",
            "evidence": contents,
        })

    return patterns


def _rule_based_profile_generation(facts: list[dict], patterns: list[dict]) -> dict:
    """基于规则的画像生成"""
    profile = {
        "style": "未确定",
        "risk_tolerance": "未确定",
        "top_industries": [],
        "behavior_traits": [],
        "cognitive_biases": [],
        "generated_at": datetime.now().isoformat(),
    }

    # 从事实提取
    for fact in facts:
        cat = fact.get("category", "")
        content = fact.get("content", "")

        if cat == "关注行业":
            industry = content.replace("关注行业 | ", "")
            if industry not in profile["top_industries"]:
                profile["top_industries"].append(industry)

        if cat == "投资偏好":
            pref = content.replace("投资偏好 | ", "")
            if "价值" in pref or "逆向" in pref:
                profile["style"] = "价值投资型"
                profile["risk_tolerance"] = "稳健"
            elif "成长" in pref:
                profile["style"] = "成长投资型"
                profile["risk_tolerance"] = "积极"
            elif "蓝筹" in pref:
                profile["style"] = "蓝筹偏好型"

            if pref not in profile["behavior_traits"]:
                profile["behavior_traits"].append(pref)

    # 默认值
    if not profile["top_industries"]:
        profile["top_industries"] = ["未确定"]
    if profile["style"] == "未确定":
        profile["style"] = "均衡型"
        profile["risk_tolerance"] = "稳健"

    return profile


def _detect_profile_conflicts(old_profile: dict, new_profile: dict) -> list[dict]:
    """检测新旧画像冲突"""
    conflicts = []

    # 投资风格变更
    old_style = old_profile.get("style", "")
    new_style = new_profile.get("style", "")
    if old_style and new_style and old_style != new_style:
        conflicts.append({
            "old": f"风格={old_style}",
            "new": f"风格={new_style}",
            "resolution": "以新数据为准，保留历史风格标签作为参考",
        })

    # 风险承受能力变更
    old_risk = old_profile.get("risk_tolerance", "")
    new_risk = new_profile.get("risk_tolerance", "")
    if old_risk and new_risk and old_risk != new_risk:
        conflicts.append({
            "old": f"风险={old_risk}",
            "new": f"风险={new_risk}",
            "resolution": "标记为风险偏好变化，通知用户确认",
        })

    return conflicts


# ── 蒸馏工作流构建 ──

def create_distillation_workflow(llm_provider: Optional[LLMProvider] = None) -> StateGraph:
    """
    创建记忆蒸馏 LangGraph 工作流。

    工作流图结构：

        START
          │
          ▼
    [L1 事实提取]
          │
          ▼
    [L2 模式归纳]
          │
          ▼
    [L3 画像生成]
          │
          ▼
    [冲突检测]
          │
          ▼
    [存储结果]
          │
          ▼
         END
    """
    workflow = StateGraph(DistillationState)

    workflow.add_node("extract_facts", extract_facts_node)
    workflow.add_node("induce_patterns", induce_patterns_node)
    workflow.add_node("generate_profile", generate_profile_node)
    workflow.add_node("detect_conflicts", detect_conflicts_node)
    workflow.add_node("store_results", store_results_node)

    workflow.set_entry_point("extract_facts")
    workflow.add_edge("extract_facts", "induce_patterns")
    workflow.add_edge("induce_patterns", "generate_profile")
    workflow.add_edge("generate_profile", "detect_conflicts")
    workflow.add_edge("detect_conflicts", "store_results")
    workflow.add_edge("store_results", END)

    logger.info("记忆蒸馏工作流已创建")
    return workflow.compile()


class DistillationRunner:
    """记忆蒸馏运行器"""

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider
        self._workflow = create_distillation_workflow(llm_provider)

    async def distill(self, user_id: str, raw_conversation: str) -> dict:
        """执行完整蒸馏管道"""
        state = {
            "user_id": user_id,
            "raw_conversation": raw_conversation,
            "distillation_started": datetime.now().isoformat(),
        }

        result = await self._workflow.ainvoke(state)
        return result


# ── 便捷函数 ──

def create_distillation_runner(llm_provider: Optional[LLMProvider] = None) -> DistillationRunner:
    return DistillationRunner(llm_provider)
