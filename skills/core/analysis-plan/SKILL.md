---
name: analysis-plan
description: Soft-takeover stats planning in analysis mode — light EDA, per-analysis human choices, typed ritual approval before execute, optional auto mode, then local scripts (MCP only when needed).
license: MIT
---

# Analysis Plan

Use this skill only in **analysis** mode. Do not start academic/ARS writing from here.

## Stages

1. **Clarify + light EDA** — Inspect `data/clean` once; write a compact profile. Ask only high-value clarifying questions.
2. **From hypotheses to models (required table)** — Before the cards, fill in the table under "Hypotheses to models" in `analysis/plans/plan.md` (the workspace template already has its header; keep the columns), one row per hypothesis and one per exploratory variable:

   | ID | Scope as worded | Outcome | Focal term | Implied tests | Status |
   | --- | --- | --- | --- | --- | --- |

   - **Scope as worded**: `whole sample`, `restricted to <group>` (wording such as "among X" or "no specific prediction for Y"), `moderation`, or `exploratory, no direction`.
   - **Implied tests**, by scope:
     - `restricted to <group>`: the within-group model, plus the pooled model with focal term × group and the slope in each group. An effect that is significant in X and not in Y is not shown to be specific to X until the difference itself is tested.
     - `moderation` in a design that also has a grouping factor: the three-way term (moderation × group), so you can tell whether the moderation holds in each group.
     - `exploratory, no direction`: the main effect, and the variable as a moderator of each focal exposure or condition, each with a one-sentence theoretical reason. An exploratory moderator interacts with the exposure, not only with group.
     - A measured predictor in a design with several conditions: the predictor × each condition contrast, not only × a pooled condition code.
     - Several treatment arms: each arm against the reference as the primary contrasts; a pooled arms-versus-reference contrast as a supplementary test, labelled as such.
     - Change between waves: name the primary specification (difference score or baseline-adjusted) and keep the other as a robustness check. Test the overall change first (intercept-only model of the difference score, or a paired test), then add group, then the remaining terms step by step.
   - Apply the implied tests to every outcome, and fit them together in one pooled model per outcome, with all lower-order terms and continuous predictors mean-centred. Read within-group slopes from that model; separate subgroup models are supplementary.
   - Repeated stimuli or items within participants: add a robustness model with a crossed random intercept for the stimulus.
   - Report every model term in the text with estimate, direction and p, covariates included, not only the focal terms.
   - **Status**: `confirmatory` or `exploratory`; every implied test enters the multiplicity plan.

   Re-read the table before writing the report and state, for each implied test, the result or why it was not run. These tests are the first candidates for the "concrete new method" option on the cards below, and the table goes into the plan you submit for approval.
3. **Per-analysis choices (required)** — Do **not** dump one mega-plan and stop. For **each** analysis you propose, present a short decision card:
   - Question (what this analysis answers)
   - Options: **first option must be a concrete new method**; you may add alternatives; put「已经足够，先执行已选」**last**, never as the default recommendation
   - Your recommendation with rationale
   - Wait for the user to pick (or say「可以」to accept the recommendation) before adding the next analysis
   - Soft「可以 / 确认」only settles the current card — it does **not** authorize scripts
4. **Overall ritual approval (required unless `/plan auto`)** — After every listed choice is decided, ask the user to type exactly:

   `我已审阅并批准本方案`

   Record that sentence as the approval ritual. Do not treat short tokens (可以 / ok / 继续) as execute authorization.

   When the approver can only pick from options (no free text), a two-option approve/revise card leaves you guessing what to change. Submit the plan, including the hypotheses-to-models table, as:
   - `approve` — approve the plan as written
   - `revise_<element>` — one option per element a reviewer might change (for example `revise_outcome`, `revise_covariates`, `revise_h2a_scope`), each stating the concrete alternative you would adopt

   If a revise option is chosen, apply that alternative and resubmit the same card once. Do not ask open follow-up questions about what to change.
5. **Auto mode** — If the user said `/plan auto`, proceed without ritual, but every report/script summary must state **「未经人审批」**.
6. **Crosscheck / verify (human-gated)** — Do **not** start `/crosscheck` or `/verify` automatically. After scripts (or before a costly pass), ask whether to open that block; only run it after an explicit yes. Skipping must mark **「未经核对」**.
7. **Execute** — Local reproducible scripts under `analysis/scripts/` by default; MCP only for special backends or explicit request.
8. **Handoff** — Update `analysis/HANDOFF.md` before academic mode. Final Panel「核实」remains required for completion.

## Volume rule

Never tell the user “分析方法已经足够了” as a closing statement. If the plan is getting long, still offer **another concrete method as option 1**, and only then offer「已经足够」as an explicit selectable option.

## Persistence

Keep state in `analysis/plans/` (`/plan new|status|auto|human|run|defer|handoff`). Soft「可以」acknowledges a node; the typed ritual authorizes run when `approvalMode=human`.

## Boundaries

- Never overwrite `data/raw`.
- No novel stats algorithms in PsyClaw core.
- Do not merge with ARS planning.
- Model **proposes** crosschecks after asking; humans mark items — do not expect users to invent `/verify` ids themselves.
