---
name: method-mediation
description: Mediation — the indirect effect is a product with an interval, not two significant paths.
topics:
  - mediation
license: MIT
---

# Mediation

Use this when a claim says one variable carries the effect of another.

- The indirect effect is the product of the component paths. Two significant component paths are not an indirect effect. Report the product with a bootstrap or Monte Carlo interval.
- Say what the indirect path identifies. A covariate that is caused by the treatment is a candidate mediator, not "just a control". A variable that causes both the treatment and the outcome is a confounder, not a mediator.
- Do not call the path causal unless the design supports that wording. "Associated through" is the default for observational data.
- A mediator added only after seeing the direct effect, and then reported as confirmatory, is exploratory. Label it that way.
---
