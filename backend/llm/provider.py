"""LLM Provider 抽象层 — Plan-4 完整实现，Plan-5 使用 stub"""


class LLMProvider:
    """LLM Provider 基类"""

    async def chat(self, messages: list[dict]) -> str:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """模拟 LLM — 开发阶段使用"""

    async def chat(self, messages: list[dict]) -> str:
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = m.get("content", "")

        # 蒸馏场景：返回固定格式
        if "提取" in user_content and "category" in user_content:
            return "关注行业 | 半导体和白酒行业\n投资偏好 | 偏好大盘蓝筹"

        # L2 策略提取
        if "归纳" in user_content:
            return "用户偏好价值投资，选股重视 ROE 和护城河，交易习惯为左侧分批买入，决策偏数据驱动。"

        # L3 画像生成
        if "投资画像" in user_content:
            return (
                "投资风格标签：价值投资型\n"
                "风险承受度：稳健\n"
                "关注行业 Top 3：半导体、白酒、医药生物\n"
                "行为模式特征：左侧分批建仓，重视安全边际，不追涨\n"
                "需要警惕的认知偏差：锚定效应（容易锚定历史价格）"
            )

        return "Mock LLM response"


class LLMFactory:
    """LLM 工厂"""

    _providers = {"mock": MockLLMProvider}

    @classmethod
    def register(cls, model_id: str, provider_class):
        cls._providers[model_id] = provider_class

    @classmethod
    def create(cls, model_id: str) -> LLMProvider:
        provider_class = cls._providers.get(model_id)
        if provider_class:
            return provider_class()
        # 默认返回 Mock
        return MockLLMProvider()
