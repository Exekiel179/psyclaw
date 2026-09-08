// Tests must not emit product telemetry. Individual observability tests pass an
// explicit `env` object when they need the default-on path.
process.env.PSYCLAW_TELEMETRY ??= "0";
process.env.PSYCLAW_SKIP_TELEMETRY_NOTICE ??= "1";
