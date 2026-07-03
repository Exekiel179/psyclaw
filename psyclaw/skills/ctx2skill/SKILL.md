---
name: ctx2skill
description: Ctx2Skill adapter for turning long project context, failed probes, workflow logs, and review findings into reusable natural-language skills. Use when evolving PsyClaw skills, mining rules from documents, building probe/rubric self-play, or synchronizing the upstream Ctx2Skill project.
category: meta-skill
---

# Ctx2Skill Adapter

Use this skill when PsyClaw needs to create or improve agent skills from context.
Keep the adapter thin: the upstream project structure belongs in `upstream/`,
and this `SKILL.md` only describes how PsyClaw should apply it.

## Sync

Run:

```bash
psyclaw skills --sync ctx2skill
```

The sync command clones or refreshes the original repository into
`psyclaw/skills/ctx2skill/upstream/` without flattening its files.

## PsyClaw Workflow

1. Select context: architecture docs, workflow registry, gates, recent logs,
   review blocking items, tests, and user-approved project memory.
2. Build probes: turn stable behaviors into easy probes and recent failures
   into hard probes.
3. Run a Ctx2Skill-style loop:
   Challenger creates tasks and rubrics; Reasoner solves them; Judge marks
   rubric pass/fail; Proposer identifies reusable lessons; Generator updates
   candidate skills.
4. Replay across time: evaluate candidate skills against both hard and easy
   probes. Prefer the candidate that improves hard cases without breaking
   stable cases.
5. Promote only reviewed output: write candidate skills to a staging area
   first, then merge into bundled or external `SKILL.md` after human or gate
   approval.

## Integration Points

- `psyclaw/skills/loader.py`: discover the promoted `SKILL.md`.
- `psyclaw/skills/recommend.py`: route evolved skills by research type.
- `psyclaw/context.py`: use generated skills as compact procedural context.
- `psyclaw/gates/`: convert recurring gate failures into hard probes.
- `tests/`: keep regression probes close to the behavior they protect.

## Boundaries

- Do not train a model in this skill. Ctx2Skill is inference-time skill
  augmentation.
- Do not overwrite existing bundled skills directly from self-play output.
  Stage, evaluate, and review first.
- Do not sync secrets, API keys, or local user memory into `upstream/`.
