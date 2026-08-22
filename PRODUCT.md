# PsyClaw Product

Version 0.24.0 adopts the audited 0.4.1 predecessor Node/Pi baseline as an
independent PsyClaw product with the `.psyclaw` project contract. Version
0.23.0 remains available through its immutable tag and existing release assets.

## Register

product

## Users

Social-science researchers running PsyClaw research runs on their own machine. They open the panel in a browser between writing and analysis sessions to check what the agent is doing right now, whether anything needs their decision, and what has been produced. They are researchers, not operators: the panel should feel like a quiet desk, not a control room.

## Product Purpose

The PsyClaw panel is the calm, mostly read-only observability surface for a local research run: current run state, what the model is working on at this moment, evidence coverage, gates, artifacts, and anything waiting on a human decision. Its job is to make the background agent legible and trustworthy without ever feeling like an alert wall.

## Brand Personality

calm, clear, restrained, direct. Three words: quiet, legible, local.

## Anti-references

- Ops dashboards that scream: red alert walls, flashing statuses, urgent-looking everything.
- Dense SaaS tables that require reading every row to understand anything.
- Opaque status: a panel that hides what the model is doing; silence that reads as failure.
- Anything implying data leaves the machine.

## Design Principles

1. **Show the work.** The panel must make it obvious that the model is working and on what. Silence reads as failure.
2. **Calm status language.** Phases and gates speak in neutral, forward words ("需要处理" over "blocked"); color is a soft hint, never an alarm.
3. **Clear zones.** Each section answers one question: 在做什么 / 产出了什么 / 需要我做什么 / 怎么连接.
4. **Local and private.** Everything is read-only except explicit researcher actions; the trust note is part of the layout.
5. **Restrained surface.** One accent, generous whitespace, low density; the interface disappears into the task.

## Accessibility & Inclusion

- WCAG AA contrast for text and status labels.
- Status never communicated by color alone, always paired with a word.
- `prefers-reduced-motion` respected; no layout-animating motion.
