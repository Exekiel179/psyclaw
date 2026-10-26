---
name: method-change-scores
description: Change across waves — difference scores versus baseline-adjusted models, Lord's paradox, and testing overall change before covariates.
topics:
  - change-scores
license: MIT
---

# Change scores

Use this when an outcome is measured more than once and the claim is about change.

- A difference score (follow-up minus baseline) and a baseline-adjusted model (ANCOVA, or the follow-up outcome with the baseline as a covariate) answer different questions. Lord's paradox is the case where they disagree. Name which one is primary and keep the other as a robustness check. Do not average them or pick the one with the smaller p after seeing both.
- Test overall change first: an intercept-only model of the difference score, or a paired test with no predictors. Then add group, then the remaining terms one step at a time. A model that only reports a group effect has not shown that anyone changed.
- State the sign of the difference once (for example follow-up minus baseline). Check every verbal claim against that sign before writing it.
- Read group differences in change from a pooled model (group as a predictor of the difference, or the group term in the baseline-adjusted model). Separate per-group models do not test whether the groups differ.
---
