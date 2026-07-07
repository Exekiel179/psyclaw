---
name: paper-review-gates
description: Paper review and gatekeeping skill for PsyClaw outputs. Use for APA/JARS checks, peer-review simulation, Devil's Advocate critique, citation fidelity, provenance, figure honesty, and resolving blocking issues before final delivery.
category: quality
---

# Paper Review Gates

Use this skill for final-quality checks on drafts, reports, figures, and
workflow outputs.

## Workflow

1. Run targeted checks: `psyclaw check <draft>`, `psyclaw jars <draft>`,
   `psyclaw cite-check <draft>`, or `psyclaw provenance <artifact>`.
2. Run `psyclaw review <draft>` for panel-style critique.
3. Classify issues as blocking, warning, or accepted limitation.
4. Fix blocking issues first; do not polish around an unresolved design,
   citation, or reproducibility failure.
5. Re-run the relevant gate and cite the artifact path as evidence.

## Blocking Examples

- Unsupported causal language.
- Missing sample/exclusion/missing-data reporting.
- Unverifiable citation or orphan in-text citation.
- Statistical claim without effect size, interval, or reproducibility path.
- Figure that hides scale, uncertainty, or sample size.

