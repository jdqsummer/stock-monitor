#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1 依赖校验：直读 .dsh/skills/**/SKILL.md 的 frontmatter（不经 DSH skill 机制）。

断言：
  ① 每个顶层 skill 的 `consumes` 字段有上游 `provides` 覆盖（或属于 pipeline 注入的基础数据）；
  ② 无 `provides` 字段重名冲突；
  ③ block 级 `name` 不含下划线。

校验失败 exit 1，成功 exit 0（打印 "E1 deps OK"）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# repo 根 = 本脚本上两级（scripts/dsh_p1/ -> scripts/ -> repo root）
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".dsh" / "skills"

# pipeline 前置步骤注入的基础数据字段（read_context + 确定性计算节点），
# 由 investment-framework 的 `context` 语义覆盖，非任何 skill 的 `provides` 产出。
# 这些字段不会被断言①当作"缺失上游"报错。
BASE_INPUTS = {
    "financials",
    "current_price",
    "total_market_cap",
    "total_shares",
    "pe_dynamic",
    "industry_category",
    "net_profit_deducted",
    "annual_profit_low",
    "annual_profit_high",
}


def parse_frontmatter(text: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter（首个 --- 与第二个 --- 之间）。"""
    if not text.startswith("---"):
        return {}
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}
    fm_text = rest[:end]
    data = yaml.safe_load(fm_text)
    return data if isinstance(data, dict) else {}


def is_block_path(rel: Path) -> bool:
    """block = .dsh/skills/<skill>/blocks/<block>/SKILL.md（parts[1] == "blocks"）。"""
    parts = rel.parts
    return len(parts) >= 4 and parts[1] == "blocks"


def main() -> int:
    skill_files = sorted(SKILLS_DIR.rglob("SKILL.md"))
    if not skill_files:
        print(f"ERROR: 未在 {SKILLS_DIR} 找到任何 SKILL.md")
        return 1

    top_level = []   # (name, provides, consumes, relpath)
    blocks = []      # (name, relpath)
    errors = []

    for f in skill_files:
        rel = f.relative_to(SKILLS_DIR)
        fm = parse_frontmatter(f.read_text(encoding="utf-8"))
        name = fm.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"[frontmatter] {rel}: 缺少必填 name")
            continue
        if is_block_path(rel):
            blocks.append((name, rel))
        else:
            provides = fm.get("provides") or []
            consumes = fm.get("consumes") or []
            top_level.append((name, provides, consumes, rel))

    # 断言③：block 级 name 不含下划线
    for name, rel in blocks:
        if "_" in name:
            errors.append(f"[断言③] block {rel}: name 含下划线 -> {name!r}")

    # 断言②：无 provides 字段重名冲突
    field_provider: dict[str, str] = {}
    for name, provides, _consumes, rel in top_level:
        for field in provides:
            if field in field_provider:
                errors.append(
                    f"[断言②] provides 重名冲突: {field!r} 同时由 "
                    f"{field_provider[field]} 与 {name} ({rel}) 提供"
                )
            else:
                field_provider[field] = name

    # 断言①：每个 consumes 字段有上游 provides 覆盖（或属于基础数据）
    for name, _provides, consumes, rel in top_level:
        for field in consumes:
            if field not in field_provider and field not in BASE_INPUTS:
                errors.append(
                    f"[断言①] {rel} ({name}) 消费字段 {field!r} 无上游 provides 覆盖"
                )

    if errors:
        print("E1 deps FAILED")
        for e in errors:
            print("  -", e)
        return 1

    print(f"E1 deps OK  ({len(top_level)} 顶层 skill, {len(blocks)} block, "
          f"{len(field_provider)} 字段已映射)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
