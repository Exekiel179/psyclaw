---
name: research-workflow
description: PsyClaw research workflow coordinator. Use when choosing or running lit-loop, meta-loop, analysis-loop, qual-loop, research, or auto-loop; when enforcing clarify-first workflow, artifact evidence, HITL review, and workflow summary discipline.
category: workflow
---

# Research Workflow

Use this skill to route a research task through PsyClaw's current workflow
system. This replaces the legacy all-in-one ARS mental model with small,
explicit loops.

## Route

- Literature or theory synthesis: `psyclaw lit-loop <topic>`.
- Meta-analysis from an effect table: `psyclaw meta-loop <effects.csv>`.
- Empirical data analysis planning: `psyclaw analysis-loop <data.csv>`.
- Interview/transcript work: `psyclaw qual-loop <path>`.
- General paper pipeline: `psyclaw research <topic>`.
- Repository-level autonomous progress: `psyclaw auto-loop`.

## Rules

1. Run `psyclaw clarify` or check clarify status before substantive work.
2. Treat workflow summaries and produced files as evidence; do not rely on chat
   memory as proof of completion.
3. Keep statistics delegated to generated scripts, MCP backends, or mature
   external libraries.
4. End with review or gates when the output is paper-facing.

