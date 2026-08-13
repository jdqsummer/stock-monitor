"""通用阶段工具 — skill 目录驱动（stage 级扩展，定性 skills 化）

每个 stage 是一个 SKILL.md（frontmatter 声明 name/type/output_field/order/
depends_on/blocks_dir）。工厂扫描 stages/ 生成对应 StageTool；stage 内若有
blocks/ 子目录，则遍历每个子块独立 LLM 定性（frontmatter 可选 handler:
dedicated_* 走专用处理函数）。

新增分析阶段 = 在 stages/ 下新建 SKILL.md；新增定性子块 = 在 stage 的
blocks/ 下新建 SKILL.md。均不改代码。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)

_STAGES_DIR = Path(__file__).resolve().parent / "skills" / "stages"

# 专用处理函数注册表：output_field → handler（含确定性逻辑的 block）
_HANDLERS = {
    "operating_quality": "_handle_operating_quality",
}


@dataclass
class BlockDef:
    name: str
    output_field: str
    title: str
    order: int
    handler: str | None
    skill_content: str


@dataclass
class StageDef:
    name: str
    description: str
    type: str
    output_field: str
    order: int
    depends_on: list[str]
    blocks_dir: str | None
    skill_content: str
    blocks: list[BlockDef] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md frontmatter，返回 (frontmatter dict, 正文)"""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end])
                return (fm if isinstance(fm, dict) else {}), text[end + 5 :].lstrip("\n")
            except yaml.YAMLError:
                logger.warning("frontmatter 解析失败，按无 frontmatter 处理")
    return {}, text


def _load_stages() -> list[StageDef]:
    stages: list[StageDef] = []
    if not _STAGES_DIR.is_dir():
        return stages
    for stage_dir in sorted(_STAGES_DIR.iterdir()):
        skill_path = stage_dir / "SKILL.md"
        if not stage_dir.is_dir() or not skill_path.exists():
            continue
        fm, body = _parse_frontmatter(skill_path.read_text(encoding="utf-8"))
        if not fm.get("name"):
            continue
        blocks: list[BlockDef] = []
        blocks_dir = fm.get("blocks_dir")
        if blocks_dir:
            blocks_root = stage_dir / blocks_dir
            if blocks_root.is_dir():
                for bdir in sorted(blocks_root.iterdir()):
                    bpath = bdir / "SKILL.md"
                    if not bpath.exists():
                        continue
                    bfm, bbody = _parse_frontmatter(bpath.read_text(encoding="utf-8"))
                    if not bfm.get("output_field"):
                        continue
                    blocks.append(BlockDef(
                        name=bfm.get("name", bdir.name),
                        output_field=bfm["output_field"],
                        title=bfm.get("title", bdir.name),
                        order=int(bfm.get("order", 99)),
                        handler=bfm.get("handler"),
                        skill_content=f"{bbody}\n\n（子块元信息：output_field={bfm['output_field']}，title={bfm.get('title')}）",
                    ))
                blocks.sort(key=lambda b: b.order)
        stages.append(StageDef(
            name=fm["name"],
            description=fm.get("description", ""),
            type=fm.get("type", "qualitative"),
            output_field=fm.get("output_field", fm["name"]),
            order=int(fm.get("order", 99)),
            depends_on=fm.get("depends_on", []) or [],
            blocks_dir=blocks_dir,
            skill_content=body,
            blocks=blocks,
        ))
    stages.sort(key=lambda s: s.order)
    return stages


class StageTool(BaseTool):
    """通用阶段工具：注入 stage skill + 依赖数据 → LLM/混合执行 → 写回 state"""

    def __init__(self, stage: StageDef, llm_provider=None):
        self.stage = stage
        self.llm = llm_provider
        self.name = stage.name
        self.description = stage.description
        self.output_field = stage.output_field
        self.order = stage.order
        self.blocks = stage.blocks
        self.input_model = _EmptyInput

    async def execute(self, arguments, context: ToolExecutionContext) -> ToolResult:
        st = context.metadata["analysis_state"]
        if self.stage.type == "qualitative":
            updates = await self._run_qualitative(context, st)
        elif self.stage.type == "hybrid":
            updates = await self._run_hybrid(context, st)
        else:
            updates = {}
        _merge(context, updates)
        text = f"{self.name} 完成: {self.output_field}"
        return ToolResult(output=text, metadata={"state_updates": updates})

    # ── qualitative：遍历 blocks 或单次定性 ──

    async def _run_qualitative(self, context, st: dict) -> dict:
        llm = context.metadata.get("llm_provider")
        results: dict[str, dict] = {}
        if self.blocks:
            for block in self.blocks:
                if block.handler and block.handler in _HANDLERS:
                    handler = globals()[_HANDLERS[block.handler]]
                    block_updates = await handler(context, st, block.skill_content)
                elif llm is not None:
                    block_updates = await self._llm_block(context, st, block)
                else:
                    block_updates = {"text": f"（无 LLM，{block.title} 未评估）", "title": block.title}
                results[block.output_field] = {"title": block.title, **block_updates}
                st.update(block_updates)  # 兼容顶层字段
        else:
            if llm is None:
                results = {"text": "（无 LLM，定性分析未执行）"}
            else:
                results = await self._llm_single(context, st)
        return {"stage_results": {self.name: {"title": self.name, **results}}, self.output_field: results}

    async def _llm_block(self, context, st: dict, block: BlockDef) -> dict:
        llm = context.metadata["llm_provider"]
        data = _inject(st, self.stage.depends_on)
        prompt = (
            f"{block.skill_content}\n\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}\n"
            f"数据: {data}\n"
            f'请以 JSON 返回 {{"text": "{block.title} 结论（100-200 字）"}}'
        )
        resp = await llm.json_chat([{"role": "user", "content": prompt}])
        return {"text": resp.get("text", "") if isinstance(resp, dict) else str(resp)}

    async def _llm_single(self, context, st: dict) -> dict:
        llm = context.metadata["llm_provider"]
        data = _inject(st, self.stage.depends_on)
        prompt = (
            f"{self.stage.skill_content}\n\n"
            f"股票: {st.get('stock_name', '')}({st.get('stock_code', '')})，行业: {st.get('industry_category', '未知')}\n"
            f"数据: {data}\n"
            f"请给出本阶段结论，以 JSON 对象返回（字段含义见 skill 内输出说明）。"
        )
        resp = await llm.json_chat([{"role": "user", "content": prompt}])
        return resp if isinstance(resp, dict) else {"text": str(resp)}

    # ── hybrid：LLM 定 PE 区间 + 引导确定性工具（Task 5 细化）──

    async def _run_hybrid(self, context, st: dict) -> dict:
        return {}


class _EmptyInput(BaseModel):
    """无需参数的只读工具的统一空入参模型（mirror harness_tools._EmptyInput）"""
    pass


def _merge(context: ToolExecutionContext, updates: dict) -> None:
    context.metadata["analysis_state"].update(updates)


def _inject(st: dict, depends_on: list[str]) -> dict:
    """按 depends_on 提取 state 数据（financials 只保留 8 期摘要）"""
    out = {}
    for key in depends_on:
        val = st.get(key)
        if key == "financials" and val:
            out[key] = [{"period": f.report_period, "revenue": f.revenue,
                         "net_profit_parent": f.net_profit_parent,
                         "net_profit_deducted": f.net_profit_deducted} for f in val[:8]]
        else:
            out[key] = val
    return out


def build_stage_tools(llm_provider) -> list[StageTool]:
    """扫描 stages/ 目录生成全部阶段工具"""
    return [StageTool(stage, llm_provider=llm_provider) for stage in _load_stages()]
