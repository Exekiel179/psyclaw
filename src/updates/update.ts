import { access } from "node:fs/promises";
import { join } from "node:path";
import { PI_AI, PI_CODING_AGENT, resolvePsyClawManifest } from "./manifest.js";
import { type PiRelease, type RegistryClient } from "./registry.js";
import { compareSemver } from "./status.js";

/** A single side-effecting step for the injected executor to run. */
export interface PiUpdateStep {
  command: string;
  cwd: string;
}

export type PiUpdateExecutor = (step: PiUpdateStep) => Promise<{ exitCode: number }>;

export type PiUpdateReason =
  | "already-up-to-date"
  | "update-applied"
  | "update-failed"
  | "update-skipped";

export interface PiUpdateReceipt {
  schemaVersion: "psyclaw/pi-update/v1";
  ok: boolean;
  executed: boolean;
  reasonCode: PiUpdateReason;
  reason?: string;
  packageName: string;
  before?: string;
  after?: string;
  latest?: string;
  note?: string;
  command?: string;
  exitCode?: number;
  startedAt: string;
  finishedAt: string;
}

export interface UpdateBundledPiOptions {
  registry: RegistryClient;
  /** Explicit psyclaw package root (tests); defaults to walking up from here. */
  packageRoot?: string;
  force?: boolean;
  now?: () => string;
  /** When omitted, the call is a dry run and never mutates the workspace. */
  executor?: PiUpdateExecutor;
}

/** Reject anything that is not a plain, installable semver (guards the spawn). */
const SEMVER_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

function isSafeVersion(version: string): boolean {
  return SEMVER_PATTERN.test(version);
}

async function packageManagerAt(root: string): Promise<"pnpm" | "npm" | undefined> {
  const candidates = [
    ["pnpm", "pnpm-lock.yaml"],
    ["npm", "package-lock.json"],
  ] as const;
  for (const [manager, file] of candidates) {
    try {
      await access(join(root, file));
      return manager;
    } catch {
      // keep looking
    }
  }
  return undefined;
}

function buildCommand(manager: "pnpm" | "npm", version: string): string {
  const spec = `${PI_AI}@${version} ${PI_CODING_AGENT}@${version}`;
  return manager === "pnpm" ? `pnpm add --save-exact ${spec}` : `npm install --save-exact ${spec}`;
}

/**
 * Update the bundled Pi runtime by re-pinning both `@earendil-works/pi-*`
 * packages to the latest official release. This is the write-side counterpart
 * to `checkUpdates`: it is `--yes`/executor-gated, refuses non-semver versions,
 * and always returns a structured receipt. Without an executor it is a pure
 * plan (no workspace mutation).
 */
export async function updateBundledPi(options: UpdateBundledPiOptions): Promise<PiUpdateReceipt> {
  const now = options.now ?? (() => new Date().toISOString());
  const startedAt = now();
  const finish = (
    receipt: Omit<PiUpdateReceipt, "schemaVersion" | "startedAt" | "finishedAt">,
  ): PiUpdateReceipt => ({
    schemaVersion: "psyclaw/pi-update/v1",
    startedAt,
    finishedAt: now(),
    ...receipt,
  });

  const manifest = await resolvePsyClawManifest(options.packageRoot);
  if (manifest === undefined) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: "psyclaw package.json not found",
      packageName: PI_CODING_AGENT,
    });
  }

  let latest: PiRelease | undefined;
  try {
    latest = await options.registry.latestPiRelease();
  } catch {
    latest = undefined;
  }
  const before = manifest.piVersion;
  const base = {
    packageName: PI_CODING_AGENT,
    ...(before === undefined ? {} : { before }),
  };
  if (latest === undefined) {
    return finish({ ok: false, executed: false, reasonCode: "update-skipped", reason: "latest Pi release unavailable", ...base });
  }
  if (!isSafeVersion(latest.version)) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: `refusing unsafe Pi version: ${latest.version}`,
      latest: latest.version,
      ...base,
    });
  }

  const latestVersion = latest.version;
  const comparison = before === undefined ? null : compareSemver(before, latestVersion);
  const needsUpdate = options.force === true || comparison === null || comparison < 0;
  const withLatest = {
    ...base,
    latest: latestVersion,
    ...(latest.note === undefined ? {} : { note: latest.note }),
  };

  if (!needsUpdate) {
    return finish({ ok: true, executed: false, reasonCode: "already-up-to-date", after: latestVersion, ...withLatest });
  }

  const manager = await packageManagerAt(manifest.root);
  if (manager === undefined) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: "no pnpm-lock.yaml or package-lock.json found in the psyclaw package root",
      ...withLatest,
    });
  }
  const command = buildCommand(manager, latestVersion);

  if (options.executor === undefined) {
    return finish({
      ok: true,
      executed: false,
      reasonCode: "update-skipped",
      reason: "dry run: re-run with --yes to apply",
      command,
      after: latestVersion,
      ...withLatest,
    });
  }

  const { exitCode } = await options.executor({ command, cwd: manifest.root });
  const ok = Number.isInteger(exitCode) && exitCode === 0;
  return finish({
    ok,
    executed: true,
    reasonCode: ok ? "update-applied" : "update-failed",
    command,
    exitCode,
    ...(ok ? { after: latestVersion } : {}),
    ...withLatest,
  });
}
