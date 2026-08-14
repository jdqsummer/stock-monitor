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
    for section in ["输出格式", "逆向", "亏损", "final_rating"]:
        assert section in text


STAGES = Path(__file__).resolve().parents[2] / "backend" / "agents" / "skills" / "stages"


def _frontmatter_keys(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    body = text.split("---")[1]
    return [line.split(":")[0].strip() for line in body.splitlines() if ":" in line]


def test_stages_exist_with_required_frontmatter():
    expected = {
        "qualitative": ["name", "type", "output_field", "order", "blocks_dir"],
        "reverse-checklist": ["name", "type", "output_field", "order"],
        "swing-zone": ["name", "type", "output_field", "order"],
        "conclusion": ["name", "type", "output_field", "order"],
    }
    for stage, keys in expected.items():
        p = STAGES / stage / "SKILL.md"
        assert p.exists(), f"缺少 {stage}/SKILL.md"
        for k in keys:
            assert k in _frontmatter_keys(p), f"{stage}/SKILL.md 缺 frontmatter: {k}"


def test_qualitative_blocks_exist():
    for block in ["business-model", "moat", "operating-quality"]:
        p = STAGES / "qualitative" / "blocks" / block / "SKILL.md"
        assert p.exists(), f"缺少 blocks/{block}/SKILL.md"
        for k in ["output_field", "title", "order"]:
            assert k in _frontmatter_keys(p), f"blocks/{block} 缺 frontmatter: {k}"
    op = (STAGES / "qualitative" / "blocks" / "operating-quality" / "SKILL.md").read_text(encoding="utf-8")
    assert "handler: dedicated_operating_quality" in op
