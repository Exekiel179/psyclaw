# CLAUDE.md - PsyClaw v0.24 development guide

PsyClaw v0.24 is a TypeScript/Node research agent built as a thin adapter and
extension layer over the pinned official Pi runtime. The Python runtime from
v0.23 remains available at tag `v0.23.0`; do not maintain a second runtime in
the v0.24 tree.

Read `AGENTS.md`, `docs/开工纪要.md`, `docs/架构蓝图.md`, and
`docs/评测框架.md` before implementation. Those files define the safety and
acceptance contracts.

Core commands:

```text
pnpm install
pnpm typecheck
pnpm build
pnpm test
pnpm eval
pnpm eval:modules
node dist/src/cli.js --help
```

Do not run verification commands until the user explicitly approves the exact
commands and scope, as required by `AGENTS.md`. Never push, tag, publish, alter
CI/CD, or access credentials without explicit authorization.

The product identity is `PsyClaw`; executable, package, state directory, and
schema identifiers are lowercase: `psyclaw`, `.psyclaw`, and `psyclaw/*`.
Statistical computation stays delegated to mature external libraries and
trusted MCPs. Claims, side effects, artifacts, and workflow completion require
structured evidence and receipts.
