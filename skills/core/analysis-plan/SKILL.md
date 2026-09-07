---
name: analysis-plan
description: Soft-takeover stats planning in analysis mode — light EDA, per-analysis human choices, natural-language confirm, optional auto mode, then local scripts (MCP only when needed).
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
3. **Soft confirm** — Prefer natural language: ask the user to reply **「可以 / 确认」**. Do **not** insist on typing `/plan confirm`. Soft confirm ≠ ARS checkpoint ≠ hard awaiting-human.
4. **Auto mode** — If the user said `/plan auto`, proceed without waiting, but every report/script summary must state **「未经人审批」**.
5. **Pre-analysis crosscheck** — Before running scripts, propose checklist items (design/estimand, method choice, missingness). Prefer Panel `/panel` checklist; `/crosscheck` works in-terminal. Skipping is allowed only with **「未经核对」** labels.
6. **Execute** — Local reproducible scripts under `analysis/scripts/` by default; MCP only for special backends or explicit request.
7. **Post-analysis crosscheck** — After results: N, effects+CI, table–text, method–script match, claim language. Same Panel/skip rules.
8. **Handoff** — Update `analysis/HANDOFF.md` before academic mode.

## Volume rule

Never tell the user “分析方法已经足够了” as a closing statement. If the plan is getting long, still offer **another concrete method as option 1**, and only then offer「已经足够」as an explicit selectable option.

## Persistence

Keep state in `analysis/plans/` (`/plan new|status|auto|human|run|defer|handoff`). Natural-language「可以」confirms and runs when a plan is awaiting confirm.

## Boundaries

- Never overwrite `data/raw`.
- No novel stats algorithms in PsyClaw core.
- Do not merge with ARS planning.
- Model **initiates** crosschecks; humans mark items — do not expect users to invent `/verify` ids themselves.
