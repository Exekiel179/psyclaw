"""Workflow 注册表 — 研究类型 → 声明式流程定义。

每个 workflow 是纯数据(id/name/research_type/steps),steps 是 Step 列表。
高级用户可在此自由拼装/拆解步骤,或新建研究类型流程——这是"可组合"的落点。

当前已实现:
  lit-review   文献综述/系统综述(clarify→检索→筛选→综述→评审)

规划中(待逐条灌通,验证引擎后批量加):
  empirical    实证研究(含实验设计;分析交外部统计/MCP)
  meta         元分析
  qualitative  质性研究
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

# 文献综述 / 系统综述
LIT_REVIEW = {
    "id": "lit-review",
    "name": "文献综述",
    "research_type": "文献综述 / 系统综述",
    "command": "review-lit",
    "steps": [
        Step("clarify", "澄清门禁", run=lambda ctx: {},
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
    "command": "meta",
    "steps": [
        Step("clarify", "澄清门禁", run=lambda ctx: {},
             gate=gate_clarify_complete),
        Step("load_effects", "载入并校验效应量表", run=step_load_effects),
        Step("meta_script", "生成可复现元分析脚本(委托 statsmodels)",
             run=step_meta_script),
        Step("write", "写元分析稿", run=step_write_meta),
        Step("review", "同行评审", run=step_review, optional=True),
    ],
}

WORKFLOWS: dict[str, dict] = {
    LIT_REVIEW["id"]: LIT_REVIEW,
    META["id"]: META,
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
