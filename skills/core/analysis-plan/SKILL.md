---
name: analysis-plan
description: Soft-takeover stats planning in analysis mode — light EDA, clarifying questions, structured proposal, soft confirm, review, then run now or later via local scripts (MCP only when needed).
license: MIT
---

# Analysis Plan

Use this skill only in **analysis** mode. Do not start academic/ARS writing from here.

## Stages

1. **Clarify + light EDA** — Inspect available data under `data/clean` (or documented paths). Write a short profile (shape, dtypes, missingness, key ranges) once; do not spam ad-hoc probes. Ask only high-value clarifying questions that change the estimand, sample treatment, or method family.
2. **Propose** — Produce a structured plan: goal, confirmatory vs exploratory, primary outcome, primary analysis, alternatives considered, missing-data / multiplicity / exclusion notes, and proposed script layout under `analysis/scripts/`.
3. **Soft confirm** — Present the proposal clearly and ask the researcher to confirm with `/plan confirm <method>` (or reject). Soft confirm is not an ARS checkpoint and not a hard `awaiting-human` safety gate.
4. **Review** — Run `/plan review` (or ask the user to). Fix warn/block findings before execution.
5. **Execute** — `/plan run` (now) or `/plan defer` (later). Default backend: **local reproducible scripts** using mature libraries (pandas / pingouin / statsmodels / scipy, or R equivalents). Use MCP only for special backends (SPSS / Mplus / MNE / Stata) or when the user explicitly asks.
6. **Handoff** — After results exist, update `analysis/HANDOFF.md` (`/plan handoff`) before the user switches to academic mode. Academic mode must consume the handoff and must not re-choose primary tests.

## Persistence

Keep durable state in `analysis/plans/` via `/plan` commands (`new`, `status`, `confirm`, `review`, `run`, `defer`, `handoff`). Prefer thin entrypoints (`run_all.py`) and reviewable modules; never invent numerical results.

## Boundaries

- Never overwrite `data/raw`.
- Never implement novel statistical algorithms inside PsyClaw core; call libraries or trusted MCP.
- Do not merge this plan with ARS stage planning.
- Label unverified claims; use `/verify` for human marks on critical fields.
