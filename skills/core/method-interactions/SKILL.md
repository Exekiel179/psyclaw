---
name: method-interactions
description: Interactions and moderation — centering, pooled models, simple slopes, and why one significant subgroup is not a group difference.
topics:
  - interactions
license: MIT
---

# Interactions

Use this when the claim is that an effect differs by group, condition, or another measured variable.

- Mean-centre continuous predictors before forming a product. The interaction coefficient does not depend on centering; the lower-order terms do. Say which variables were centred.
- Fit one pooled model per outcome with every lower-order term that the product implies. Read each group's slope from that model. A separate regression per subgroup is a supplement, not the test of a difference.
- An effect that is significant in one group and not in another is not evidence that the groups differ (Gelman & Stern, 2006; Nieuwenhuis, Forstmann, & Wagenmakers, 2011). The interaction term is that test.
- A moderator together with a grouping factor needs the three-way term, so the moderation can differ by group.
- An exploratory variable gets its main effect and a product with each focal exposure or condition, each with one sentence of theoretical reason. It moderates the exposure, not only group membership.
- A measured predictor in a design with several conditions is crossed with each condition contrast, not only with a single pooled condition code.
- Several treatment arms: each arm against the reference is a primary contrast, including when the hypothesis names the arms together. A pooled arms-versus-reference contrast is supplementary and must be labelled as such.
- When an interaction is significant or marginal, report simple slopes or marginal effects (at the mean and one standard deviation above and below for a continuous moderator). Use a Johnson-Neyman interval when the question is the range of the moderator where the effect holds, not a single point.
---
