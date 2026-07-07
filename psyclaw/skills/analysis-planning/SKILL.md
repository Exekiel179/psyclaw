---
name: analysis-planning
description: Psychology empirical analysis planning skill. Use when inspecting a dataset, selecting analysis families, declaring tests, generating reproducible external-library scripts, checking assumptions, effect sizes, confidence intervals, and preregistration boundaries.
category: research
---

# Analysis Planning

Use this skill when a user has data or a planned empirical study. PsyClaw
coordinates analysis decisions and reproducible scripts; it does not implement
statistics in core.

## Workflow

1. Inspect variables, measurement level, missingness, clustering/repeated
   structure, and planned contrasts.
2. Separate confirmatory tests from exploratory analyses.
3. Recommend an analysis family with assumptions and robust alternatives.
4. Generate or route to an external script/backend: pingouin, scipy,
   statsmodels, SPSS, Mplus, Stata, or MNE.
5. Require effect sizes, confidence intervals, assumption diagnostics, and a
   reproducibility trail.

## Defaults

- Two independent groups: prefer Welch unless design knowledge says otherwise.
- Mediation: bootstrap interval; do not imply causality from cross-sectional
  mediation.
- Repeated observations: identify subject/session nesting before choosing a
  simple test.
- Confirmatory claims need preregistration or an explicit exploratory label.

