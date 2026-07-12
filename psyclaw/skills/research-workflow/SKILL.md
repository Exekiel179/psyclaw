---
name: research-workflow
description: PsyClaw research workflow coordinator. Use when choosing chat, run (literature/meta/analysis/qualitative), or auto; when enforcing prepare-first workflow, artifact evidence, review, checkpoints, and workflow summary discipline.
category: workflow
---

# Research Workflow

Use this skill to route a research task through PsyClaw's current workflow
system. This replaces the legacy all-in-one ARS mental model with small,
explicit loops.

## Route

- Literature or theory synthesis: `psyclaw run literature <topic>`.
- Meta-analysis from an effect table: `psyclaw run meta <effects.csv>`.
- Empirical data analysis planning: `psyclaw run analysis <data.csv>`.
- Interview/transcript work: `psyclaw run qualitative <path>`.
- General paper pipeline: `psyclaw research <topic>`.
- Repository-level autonomous progress: `psyclaw auto`.

## Rules

1. Run `psyclaw prepare` or check research preparation status before substantive work.
2. Treat workflow summaries and produced files as evidence; do not rely on chat
   memory as proof of completion.
3. Keep statistics delegated to generated scripts, MCP backends, or mature
   external libraries.
4. A run defaults to continuous execution; use `--confirm-each`, `--exploratory`, or
   `--resume` only for their explicit workflow semantics.
5. End with review or quality checks when the output is paper-facing.
