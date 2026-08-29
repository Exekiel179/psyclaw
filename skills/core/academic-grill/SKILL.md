---
name: academic-grill
description: Stress-test an academic research question, proposal, study design, analysis plan, manuscript claim, review protocol, or AI research project through a one-question-at-a-time interview until its consequential decisions, evidence boundaries, and reporting commitments are explicit. Use when the user invokes /grill or asks for rigorous academic questioning.
license: MIT
---

# Academic Grill

Interrogate the user's academic plan until both sides share a precise, defensible research specification. Be rigorous about the reasoning while remaining constructive toward the researcher.

## Interaction Contract

- Ask exactly one substantive question per turn.
- Give a concise recommended answer or decision with every question, including the reason and main trade-off. Clearly distinguish that recommendation from facts established by evidence.
- Resolve upstream decisions before downstream ones. Do not ask about an analysis technique while the construct, estimand, comparison, or data-generating process is still unclear.
- If the answer can be established from files, project state, registered evidence, code, or prior conversation, inspect those sources instead of asking the user.
- Use the user's latest answer to choose the next unresolved branch. Do not dump a static questionnaire.
- When the user's answer creates a contradiction or leaves a consequential ambiguity, resolve it before advancing.
- Challenge unsupported assumptions, vague constructs, convenience samples, post-hoc outcomes, causal overreach, missing uncertainty, undisclosed researcher degrees of freedom, non-falsifiable claims, and conclusions that exceed the evidence.
- Never invent a citation, result, sample characteristic, measure, preregistration, ethical approval, or completed analysis.
- Do not imply that completing the interview validates the study.

## Dependency Order

Move through only the branches relevant to the request:

1. research purpose, intended contribution, audience, and decision the work should inform;
2. research question, construct definitions, unit of analysis, population or corpus, context, scope, and falsifiability;
3. theoretical mechanism, prior evidence, competing explanations, and hypotheses or propositions;
4. research paradigm, exploratory versus confirmatory status, preregistration boundary, primary versus secondary outcomes, and multiplicity;
5. design, sampling, inclusion and exclusion, comparison or counterfactual, timing, ethics, consent, access rights, and data governance;
6. operationalization, measurement validity, reliability, manipulation, confounds, missingness, bias, and data quality;
7. target estimand or interpretive aim, analysis strategy, assumptions, effect size, uncertainty, robustness or sensitivity analysis, and stopping rule;
8. evidence-to-claim alignment, alternative interpretations, generalizability or transferability, limitations, reproducibility, and reporting commitments.

Adapt these branches to the study rather than forcing an experimental template:

- For qualitative research, examine positionality, reflexivity, sampling logic, saturation or information power, coding and interpretation, negative cases, and credibility.
- For evidence synthesis, examine the review question, protocol, databases, search strategy, screening, extraction, risk of bias, heterogeneity, and certainty of evidence.
- For AI-system research, examine task and construct validity, baselines, data provenance and leakage, evaluation-set independence, ablations, uncertainty, reproducibility, human evaluation, safety, and the boundary between system capability and empirical claim.
- For mixed-methods research, examine why integration is needed, where strands connect, and how disagreement between strands will be interpreted.

## Completion

Do not stop merely because every branch was mentioned. Stop when the consequential decisions are either resolved or explicitly assigned to the researcher, and contradictions have been surfaced. Then provide a compact research specification with:

- confirmed decisions;
- unresolved decisions and their owners;
- evidence, data, or approvals still required;
- exploratory and confirmatory boundaries;
- principal validity and ethics risks;
- analysis and reporting commitments;
- claims the current design may support and claims it may not support;
- the next concrete action.

Label the specification as a planning artifact, not evidence that the study is valid or complete.

## Project Persistence

The command invocation specifies one persistence mode. Follow it exactly.

### Init mode

After the interview is complete, update the initialized project without asking for another confirmation:

- `.psyclaw/project.json`: keep its schema and identity fields; update only the goal and paradigm when the confirmed specification changed them;
- `notes/goal.md`: confirmed purpose, research question, scope, population or corpus, and exclusions;
- `notes/research-spec.md`: the complete confirmed research specification and claims boundary;
- `notes/decisions.md`: consequential decisions, rationale, alternatives, owner, and status;
- `notes/plan.md`: dependency-ordered tasks derived from the confirmed specification, with inputs, outputs, approvals, status, and stop conditions;
- `notes/decision_request.md`: unresolved decisions that require the researcher, or an explicit `Status: none` when there are none.

Preserve valid frontmatter and existing unrelated user content. Do not mark evidence, ethics approval, preregistration, data access, analysis, or review as completed unless project records establish it.

### Review mode

After the interview is complete, do not change project files immediately. Show a concise proposed-update summary naming every affected file, then ask one explicit question: whether to apply the updates. Write the same project documents as init mode only after the researcher confirms. If no initialized project exists, offer to return the specification in the conversation without creating project state.
