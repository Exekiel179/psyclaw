---
name: method-multilevel
description: Clustered and repeated observations — name the cluster, use a random intercept, and do not treat clustered rows as independent.
topics:
  - multilevel
license: MIT
---

# Multilevel and mixed models

Use this when rows are nested in people, groups, sites, or items.

- Name the clustering unit before fitting. Repeated observations on one person are not independent observations.
- Start with a random intercept for that cluster. Add a random slope only when the design and the number of clusters support estimating it. If the slope variance does not converge, say so and keep the random-intercept model.
- Repeated stimuli or items within participants: add a robustness model with a crossed random intercept for the stimulus. Without an explicit stimulus id, use the item or trial index and say that is what was used.
- Fixed effects of the predictors still follow the pooled-model rules. A mixed model does not replace the interaction test.
---
