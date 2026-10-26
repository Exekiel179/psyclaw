---
name: method-multilevel
description: Clustered and repeated observations — name the cluster, use the maximal random-effects structure the design justifies, and do not treat clustered rows as independent.
topics:
  - multilevel
license: MIT
---

# Multilevel and mixed models

Use this when rows are nested in people, groups, sites, or items.

- Name the clustering unit before fitting. Repeated observations on one person are not independent observations.
- Use the maximal random-effects structure the design justifies (Barr, Levy, Scheepers, & Tily, 2013): a random intercept for each clustering unit, and a random slope for every predictor that varies within that unit (a within-person condition or a person-centred daily score), with their correlations. A predictor that only varies between units (sex, a between-person condition) gets no random slope for that unit.
- A random-intercept-only model with within-unit predictors understates the standard errors of those fixed effects when the effects differ between units. Do not start there.
- If the maximal model does not converge or is singular, simplify in a stated order: drop the correlations between random effects first, then the slope with the smallest variance, one step at a time. Report each step and the final structure. Compare the fixed effects with the simpler model and say whether a conclusion depends on the random-effects choice.
- Repeated stimuli or items within participants: add a robustness model with a crossed random intercept for the stimulus. Without an explicit stimulus id, use the item or trial index and say that is what was used.
- Fixed effects of the predictors still follow the pooled-model rules. A mixed model does not replace the interaction test.
---
