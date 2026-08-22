"""聊天 persona 加载器 — TDD"""
from backend.services.chat_persona import load_chat_persona, DEFAULT_CHAT_PERSONA


def test_load_persona_returns_default_when_file_missing(monkeypatch):
    """文件缺失时返回内建默认 persona，不抛异常"""
    monkeypatch.setattr("backend.config.settings.CHAT_PERSONA_PATH", "./nonexistent/SKILL.md")
    persona = load_chat_persona()
    assert persona == DEFAULT_CHAT_PERSONA
    assert "投资" in persona


def test_load_persona_reads_file_body(tmp_path, monkeypatch):
    """文件存在时返回正文（剥离 frontmatter）"""
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: invest-chat\ndescription: persona\n---\n你是资深价值投资助手。\n引用数据来源。",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.config.settings.CHAT_PERSONA_PATH", str(skill))
    persona = load_chat_persona()
    assert "你是资深价值投资助手" in persona
    assert "name: invest-chat" not in persona   # frontmatter 剥离
