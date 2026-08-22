# stock-monitor/backend/services/chat_persona.py
"""聊天 persona 加载 — 从 invest-chat/SKILL.md 读取正文注入 system prompt（热更新）

方案C：backend 直调 LLM，不依赖 DSH 运行时。SKILL.md 挂 volume 只读，
改 .md + 重启生效（或下次加载生效）。文件缺失/解析失败 → 内建默认 persona，永不抛异常。
"""
import logging
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

DEFAULT_CHAT_PERSONA = """你是「AI 投资小助手」，一名资深 A 股价值投资分析师，信奉安全边际与逆向投资。
对话纪律：先结论后建议；引用具体数据与来源；信息不足坦诚指出；分析仅供参考，不构成投资建议。"""


def _strip_frontmatter(text: str) -> str:
    """剥离 SKILL.md 的 YAML frontmatter（--- 到 --- 之间的头），返回正文。"""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:]).strip()
    return text.strip()


def load_chat_persona() -> str:
    """读取 CHAT_PERSONA_PATH 指向的 SKILL.md 正文；缺失/异常返回默认 persona。"""
    try:
        raw = Path(settings.CHAT_PERSONA_PATH).read_text(encoding="utf-8")
        body = _strip_frontmatter(raw)
        if body:
            return body
        logger.warning("persona 文件正文为空，回退默认")
    except FileNotFoundError:
        logger.info(f"persona 文件不存在 {settings.CHAT_PERSONA_PATH}，使用默认 persona")
    except Exception as e:
        logger.warning(f"persona 加载失败，回退默认: {e}")
    return DEFAULT_CHAT_PERSONA
