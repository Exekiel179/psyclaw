---
name: analysis-plan
description: Soft-takeover stats planning in analysis mode — light EDA, per-analysis human choices, typed ritual approval before execute, optional auto mode, then local scripts (MCP only when needed).
license: MIT
---

# Analysis Plan

Use this skill only in **analysis** mode. Do not start academic/ARS writing from here.

## Stages

1. **Clarify + light EDA** — Inspect `data/clean` once; write a compact profile. Ask only high-value clarifying questions.
2. **Per-analysis choices (required)** — Do **not** dump one mega-plan and stop. For **each** analysis you propose, present a short decision card:
   - Question (what this analysis answers)
   - Options: **first option must be a concrete new method**; you may add alternatives; put「已经足够，先执行已选」**last**, never as the default recommendation
   - Your recommendation with rationale
   - Wait for the user to pick (or say「可以」to accept the recommendation) before adding the next analysis
   - Soft「可以 / 确认」only settles the current card — it does **not** authorize scripts
3. **Overall ritual approval (required unless `/plan auto`)** — After every listed choice is decided, ask the user to type exactly:

   `我已审阅并批准本方案`

   Record that sentence as the approval ritual. Do not treat short tokens (可以 / ok / 继续) as execute authorization.
4. **Auto mode** — If the user said `/plan auto`, proceed without ritual, but every report/script summary must state **「未经人审批」**.
5. **Crosscheck / verify (human-gated)** — Do **not** start `/crosscheck` or `/verify` automatically. After scripts (or before a costly pass), ask whether to open that block; only run it after an explicit yes. Skipping must mark **「未经核对」**.
6. **Execute** — Local reproducible scripts under `analysis/scripts/` by default; MCP only for special backends or explicit request.
7. **Handoff** — Update `analysis/HANDOFF.md` before academic mode. Final Panel「核实」remains required for completion.

## Volume rule

Never tell the user “分析方法已经足够了” as a closing statement. If the plan is getting long, still offer **another concrete method as option 1**, and only then offer「已经足够」as an explicit selectable option.

## Persistence

Keep state in `analysis/plans/` (`/plan new|status|auto|human|run|defer|handoff`). Soft「可以」acknowledges a node; the typed ritual authorizes run when `approvalMode=human`.

## Boundaries

- Never overwrite `data/raw`.
- No novel stats algorithms in PsyClaw core.
- Do not merge with ARS planning.
- Model **proposes** crosschecks after asking; humans mark items — do not expect users to invent `/verify` ids themselves.
