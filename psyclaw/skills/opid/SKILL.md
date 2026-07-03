---
name: opid
description: OPID adapter for extracting episode-level and step-level hindsight skills from completed agent trajectories. Use when mining PsyClaw workflow logs, review traces, or gate failures into persistent lessons, or when synchronizing the upstream OPID project for future RL distillation experiments.
category: meta-skill
---

# OPID Adapter

Use this skill when completed PsyClaw runs should become reusable trajectory
lessons. Keep OPID as an adapter unless a separate training environment is
explicitly requested; the upstream project is large and training-oriented.

## Sync

Run:

```bash
psyclaw skills --sync opid
```

The sync command clones or refreshes the original repository into
`psyclaw/skills/opid/upstream/` while preserving its layout.

## PsyClaw Workflow

1. Collect trajectories from completed runs:
   `logs/run_log.md`, `notes/workflow_summary.json`,
   `notes/pipeline_summary.json`, `notes/review_panel.json`, and gate output.
2. Extract hindsight skills:
   episode-level skills describe the whole research loop; step-level skills
   describe local decisions such as analysis selection, gate repair, or review
   response.
3. Store lessons as data first, not prompt text:
   use a JSONL staging artifact with source paths, pass/fail status, and the
   exact evidence that justified each lesson.
4. Promote stable lessons into `SKILL.md` only after replay or review shows
   they help future workflows.
5. Treat full OPID training as a later, separate track requiring a GPU/RL
   environment. PsyClaw's default value is trajectory-to-skill mining.

## Integration Points

- `psyclaw/workflows/engine.py`: source of step boundaries and artifacts.
- `psyclaw/review.py`: source of blocking/warning/approved feedback.
- `psyclaw/gates/checker.py`: source of machine-checkable failure signals.
- `progress.md` and `feature_list.json`: source of accepted project state.

## Boundaries

- Do not add vLLM, flash-attn, or RL dependencies to PsyClaw core.
- Do not treat a single successful trajectory as a general rule.
- Do not expose private project data when preparing trajectories for training.
