# stock-monitor/backend/agents/__init__.py
"""Plan-4 AI Agent 系统 — LangGraph + DSH + 9 步分析链"""

from backend.agents.analysis_chain import (
    AnalysisChain,
    AnalysisReport,
    create_analysis_chain,
    run_reverse_checklist,
)
from backend.agents.constraints import (
    Constraint,
    ConstraintEngine,
    ConservativeAnnualizationConstraint,
    DisciplineRedlineConstraint,
    FalsificationPriorityConstraint,
    IndustryPEAnchorConstraint,
    ProfitQualityConstraint,
    RatingConsistencyConstraint,
    create_constraint_engine,
)
from backend.agents.data_agent import (
    DataAgent,
    data_to_state,
)
from backend.agents.state import (
    AgentMessage,
    AnalysisReport as AnalysisReportState,
    AnalysisState,
    ConstraintResult,
    DataCollectionState,
    ToolCall,
)
from backend.agents.analysis_agent import AnalysisAgent
from backend.agents.workflow import (
    NodeName,
    WorkflowRunner,
    create_analysis_workflow,
    create_data_collection_workflow,
)

__all__ = [
    # 分析链
    "AnalysisChain",
    "AnalysisReport",
    "create_analysis_chain",
    "run_reverse_checklist",
    # 约束引擎
    "Constraint",
    "ConstraintEngine",
    "ConservativeAnnualizationConstraint",
    "DisciplineRedlineConstraint",
    "FalsificationPriorityConstraint",
    "IndustryPEAnchorConstraint",
    "ProfitQualityConstraint",
    "RatingConsistencyConstraint",
    "create_constraint_engine",
    # 数据采集
    "DataAgent",
    "data_to_state",
    # 状态
    "AgentMessage",
    "AnalysisState",
    "AnalysisReportState",
    "ConstraintResult",
    "DataCollectionState",
    "ToolCall",
    # 分析智能体
    "AnalysisAgent",
    # 工作流
    "NodeName",
    "WorkflowRunner",
    "create_analysis_workflow",
    "create_data_collection_workflow",
]
