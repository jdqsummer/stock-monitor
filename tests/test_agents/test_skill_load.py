"""SKILL.md 存在且结构完整"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "backend" / "agents" / "skills" / "investment-framework" / "SKILL.md"


def test_skill_exists_and_has_frontmatter():
    assert SKILL.exists()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name:" in text and "description:" in text


def test_skill_covers_core_sections():
    text = SKILL.read_text(encoding="utf-8")
    for section in ["输出格式", "逆向投资", "亏损", "final_rating"]:
        assert section in text
