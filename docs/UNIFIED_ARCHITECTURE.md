# PsyClaw Unified Architecture

## Purpose

PsyClaw is an evidence-driven durable agent runtime for social-science work.
The project has one execution path and four supporting planes:

```text
Research intent
    -> RunState / Execution Events
    -> Planner -> Scheduler -> Executor -> Verifier -> Finisher
    -> Capability Plane -> Policy Plane -> Evidence Plane
    -> deliverables/ (user artifacts)
```

The existing chat, run, auto-loop, workflow, MCP, literature, statistics, and
writing features are adapters or views over this path. They are not independent
execution engines.

## Ownership

| Concern | Canonical owner | Other modules |
|---|---|---|
| Durable execution state | `psyclaw/run_state.py` | `taskstate.py`, workflow checkpoints, `agent_runs.jsonl` are compatibility projections |
| Agent graph execution | `psyclaw/langgraph_runtime.py` | `agent_runtime.py` supplies task contracts and verifier helpers |
| Tool invocation | `psyclaw/toolloop.py` | adapters register capabilities; they do not own lifecycle state |
| Capability registration | `academic_tools.py`, `mcp/agent_tools.py`, plugins | all expose a descriptor and structured receipt |
| Trust, approval, budget, path policy | `sandbox.py` plus tool approval | no adapter may bypass this decision |
| Evidence and lineage | `RunState` receipts + artifact index | provenance/handoff files are projections until the evidence graph lands |
| User-facing artifacts | `deliverables/`, `analysis/`, `figures/`, `notes/` | `.psyclaw/` is internal state only |

## Durable Run Contract

Every run has one `RunState` containing:

- goal and conversation snapshot;
- confirmed facts and sources;
- task graph and dependency status;
- tool receipts, approval decisions and errors;
- artifact paths, hashes and validation results;
- pending actions, retry count and stop reason.

The append-only receipt stream is the execution audit trail. JSON state is a
materialized view for resume and compatibility. A future event-log migration
must preserve the current `RunState` schema and replay old runs.

## Capability and Policy Contract

Every tool capability must declare:

- input and output schema;
- side-effect level and idempotency key;
- allowed path/domain scope;
- required approval and trust domain;
- expected artifact and validation behavior.

The policy decision happens before execution. A tool may return a denial, a
degraded result, or a structured success; it must never claim completion through
free-form text alone.

## Artifact Contract

```text
deliverables/  final reports, manuscripts, DOCX/PDF, quality verdicts
analysis/      generated and rerunnable analysis code
data/clean/    cleaned datasets, profiles, manifests
figures/       figures and tables intended for delivery
notes/         human notes and handoff material
.psyclaw/      run state, receipts, caches, audit logs, checkpoints
```

`outputs/` is a legacy compatibility path. New prompts, tools, fixtures and
documentation must use the directories above. Existing explicit paths remain
readable/writable during migration and are not silently moved.

## Quality Contract

The quality gate has two levels:

1. **Execution validity:** required tool receipts, non-empty artifacts, script
   return code, hashes, and dependency completion.
2. **Research validity:** key uniqueness, missing-key behavior, duplicate
   observations, merge row-count audit, effect sizes and confidence intervals,
   clustering/fixed-effects requirements for panel data, and explicit
   exploratory/causal boundaries.

Passing level 1 never implies that level 2 is scientifically correct.

## Migration Order

1. Keep `RunState` as the only new source of execution facts; write compatibility
   projections for old workflow/task files.
2. Move all new user artifacts to the canonical directories above and update
   sandbox defaults, prompts and fixtures.
3. Add capability descriptors and route all tool calls through the policy
   decision before expanding MCP/plugin coverage.
4. Add merge/key/model checks to the research validity gate.
5. Build a queryable evidence lineage view from receipts and artifacts.
6. Remove legacy projections only after replay, resume and migration tests pass.

## Non-goals

- Do not introduce a second generic agent engine.
- Do not treat a model summary as evidence.
- Do not label a quality-gate pass as a published or causally valid finding.
- Do not move internal state into user deliverable directories.
