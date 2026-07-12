"""Workflow 注册表 — 研究类型 → 声明式流程定义。

每个 workflow 是纯数据(id/name/research_type/command/steps),steps 是 Step 列表。
高级用户可在此自由拼装/拆解步骤,或新建研究类型流程——这是"可组合"的落点。

四条研究流程由 `run <类型>` 公开路由;`*-loop` command 字段仅保留兼容映射:
  lit-review   → run literature
  meta         → run meta
  analysis     → run analysis
  qualitative  → run qualitative
"""

from __future__ import annotations

from psyclaw.workflows.engine import Step
from psyclaw.workflows.steps import (
    gate_clarify_complete,
    step_lit_search,
    step_review,
    step_screen,
    step_synthesize,
)
from psyclaw.workflows.steps_meta import (
    step_load_effects,
    step_meta_script,
    step_write_meta,
)
from psyclaw.workflows.steps_analysis import (
    step_analysis,
    step_design,
    step_inspect_data,
    step_write_analysis,
)
from psyclaw.workflows.steps_qual import (
    step_load_transcripts,
    step_qual_design,
    step_thematic_analysis,
    step_write_qual,
)

# 文献综述 / 系统综述
LIT_REVIEW = {
    "id": "lit-review",
    "name": "文献综述",
    "research_type": "文献综述 / 系统综述",
    "command": "lit-loop",
    "steps": [
        Step("clarify", "研究准备检查", run=lambda ctx: {},
             gate=gate_clarify_complete),
        Step("lit_search", "文献检索(PRISMA 识别)", run=step_lit_search),
        Step("screen", "筛选(PRISMA)", run=step_screen),
        Step("synthesize", "合成结构化综述", run=step_synthesize),
        Step("review", "同行评审", run=step_review, optional=True),
    ],
}

# 元分析(从效应量表起;统计计算外移到 statsmodels 脚本)
META = {
    "id": "meta",
    "name": "元分析",
    "research_type": "元分析 (meta-analysis)",
    "command": "meta-loop",
    "steps": [
        Step("clarify", "研究准备检查", run=lambda ctx: {},
             gate=gate_clarify_complete),
        Step("load_effects", "载入并校验效应量表", run=step_load_effects),
        Step("meta_script", "生成可复现元分析脚本(委托 statsmodels)",
             run=step_meta_script),
        Step("write", "写元分析稿", run=step_write_meta),
        Step("review", "同行评审", run=step_review, optional=True),
    ],
}

# 实证分析(从数据表起;统计计算外移到 pingouin/scipy 脚本)
ANALYSIS = {
    "id": "analysis",
    "name": "实证分析",
    "research_type": "实证研究 / 数据分析 (统计委托外部 pingouin/scipy)",
    "command": "analysis-loop",
    "steps": [
        Step("clarify", "研究准备检查", run=lambda ctx: {},
             gate=gate_clarify_complete),
        Step("inspect_data", "画像数据", run=step_inspect_data),
        Step("design", "研究/分析设计", run=step_design),
        Step("analysis", "推荐分析 + 生成可复现脚本(委托 pingouin/scipy)",
             run=step_analysis),
        Step("write", "写实证稿", run=step_write_analysis),
        Step("review", "同行评审", run=step_review, optional=True),
    ],
}

# 质性研究(从转录稿起;LLM 辅助编码/主题分析,研究者复核)
QUALITATIVE = {
    "id": "qualitative",
    "name": "质性研究",
    "research_type": "质性研究 (主题分析/扎根理论;LLM 辅助编码,研究者复核)",
    "command": "qual-loop",
    "steps": [
        Step("clarify", "研究准备检查", run=lambda ctx: {},
             gate=gate_clarify_complete),
        Step("load_transcripts", "载入转录稿", run=step_load_transcripts),
        Step("design", "质性研究设计", run=step_qual_design),
        Step("thematic_analysis", "主题分析(LLM 辅助,研究者复核)",
             run=step_thematic_analysis),
        Step("write", "写质性报告(COREQ)", run=step_write_qual),
        Step("review", "同行评审", run=step_review, optional=True),
    ],
}

WORKFLOWS: dict[str, dict] = {
    LIT_REVIEW["id"]: LIT_REVIEW,
    META["id"]: META,
    ANALYSIS["id"]: ANALYSIS,
    QUALITATIVE["id"]: QUALITATIVE,
}

# 顶层命令名 → workflow id(L0 路由:每类研究一条显式命令)
COMMAND_TO_WORKFLOW = {
    wf["command"]: wf["id"] for wf in WORKFLOWS.values() if wf.get("command")
}


def get_workflow(wid: str) -> dict | None:
    """按 workflow id 或顶层命令名取定义。"""
    if wid in WORKFLOWS:
        return WORKFLOWS[wid]
    return WORKFLOWS.get(COMMAND_TO_WORKFLOW.get(wid, ""))
