---
name: prior-plan
description: Prior-mode process skill — recall before data, then a plan made of labeled constants. Does not run outcome models.
license: MIT
---

# Prior plan

Use this skill only in **prior** mode. Analysis mode still runs scripts. This mode stops when the researcher types `我已审阅并批准本方案`.

## Order

1. Read only `BRIEF.md` or `psyclaw.md`. Do not open `data/`, a codebook, or a saved result.
2. Call `psyclaw_submit_recall`. For each hypothesis, in order: construct (how published studies usually score the instrument), internal validity (which comparison, whose data, what would make it misleading), statistical conclusion (what test the claim needs and what it assumes), dependence (whether this result should change another hypothesis). Put every approach you might use on its own line: `- id: description`. The id must later be an option of some constant.
3. After recall is accepted, profile the data once. Counts, ranges, missingness, and single-variable distributions are enough. Do not fit an outcome model.
4. Write `analysis/scripts/analysis.py` (or `.R`) and call `psyclaw_submit_plan_script` with the full script. It is checked, not run.

## Labels

Put every analysis choice in a top-level constant, under a short comment naming the hypotheses it affects (`# H1, H2`):

```
NAME = value  # @intent value | other — why the researcher must choose
NAME = value  # @declare — why this needs no question
NAME = value  # @pseudo — why the options cannot differ for any data
```

Sort each choice into one stage, then decide who settles it:

1. Analysis sample: who enters each hypothesis.
2. Variable construction: how each analysed variable is built.
3. Model specification: framework, covariates, which models are compared.
4. Inference and indices: estimator settings, tails, alpha, multiplicity, equivalence bounds, what counts as support, effect-size or fit-index definitions.

Use `@intent` only in stages 1–3, and only where there is no common practice: an adapted scale with no scoring rule, a sample boundary the materials leave to the researcher, or two common frameworks that test different things. `@intent` needs at least one other value and a reason. Order `@intent` constants by how much they could change a hypothesis verdict, largest first.

Stage 4 is always `@declare`. Do not ask about it.

If the options agree in this data set but could differ in another, use `@declare` and say they are equivalent in this data. That is not `@pseudo`. `@pseudo` is only for options that must agree for any data, such as the mean versus the sum of the same items when the test is invariant to that scaling.

Before labelling `@intent`, answer this: if the researcher picked the other option, which hypothesis verdict would change? If you cannot name it, use `@declare`. An `@intent` constant must be used by a hypothesis test in the script. A constant that appears only in a description, an exploration, or a covariate screen is `@declare`.

A choice that matters only when another constant has a given value says so in the reason: `(if PARENT == value)`.

## Cards

After the script is accepted, ask in the order the tool reports:

- Core questions: one card each.
- Technical settings: one card that confirms the current values together.
- Dependent questions: wait until the parent choice is known.

Use `psyclaw_wake_options`. Soft「可以」settles only the current card. The plan is approved only when the researcher types `我已审阅并批准本方案`. Then tell them to switch to analysis. Do not run the script here.
