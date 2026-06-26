"""Workflow 层 — 按研究类型路由的可组合研究流程。

架构(见 CLAUDE.md / docs/ARCHITECTURE.md):
  L0 路由(每类研究一条顶层命令:review-lit / empirical / meta / qualitative …)
  L1 流程 Workflow(本包:engine 按声明式 Step 列表跑,带 HITL + 门禁 + 总验收)
  L2 子功能 Step(可单独直接用,也可拼进任意 workflow)
  L3 实现(每个 Step 委托既有命令 / skill / MCP 干活)
  横切:每个 Step 带 gate(harness 前置约束);Memory 贯穿。
"""

from psyclaw.workflows.engine import Step, WorkflowContext, run_workflow
from psyclaw.workflows.registry import WORKFLOWS, get_workflow

__all__ = ["Step", "WorkflowContext", "run_workflow", "WORKFLOWS", "get_workflow"]
