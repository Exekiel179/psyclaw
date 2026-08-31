import { access } from "node:fs/promises";
import { dirname, join } from "node:path";
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
  /** When omitted, the library call is a dry run and never mutates the workspace. */
  executor?: PiUpdateExecutor;
}

export interface ProductVersionUpdate {
  packageName: string;
  before?: string;
  after?: string;
  latest?: string;
}

export interface PsyClawUpdateReceipt {
  schemaVersion: "psyclaw/product-update/v1";
  ok: boolean;
  executed: boolean;
  reasonCode: PiUpdateReason;
  reason?: string;
  psyclaw: ProductVersionUpdate;
  runtime: ProductVersionUpdate;
  commands: string[];
  exitCode?: number;
  startedAt: string;
  finishedAt: string;
}

export type UpdatePsyClawOptions = UpdateBundledPiOptions;

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
  return manager === "pnpm"
    ? `pnpm add --save-exact ${spec} --registry=https://registry.npmjs.org/`
    : `npm install --save-exact --omit=dev --legacy-peer-deps ${spec} --registry=https://registry.npmjs.org/`;
}

function buildProductCommand(version: string): string {
  return `npm install --global psyclaw@${version} --registry=https://registry.npmjs.org/`;
}

async function hasSourceLockfile(root: string): Promise<boolean> {
  for (const file of ["pnpm-lock.yaml", "package-lock.json"]) {
    try {
      await access(join(root, file));
      return true;
    } catch {
      // keep looking
    }
  }
  return false;
}

/**
 * Update the installed PsyClaw product together with the exact Pi runtime
 * declared by that release. Updating the whole product keeps PsyClaw's code,
 * extensions, banner and tested runtime in one user-facing operation.
 * Source checkouts are deliberately not overwritten; developers update them
 * through Git and rebuild explicitly.
 */
export async function updatePsyClaw(options: UpdatePsyClawOptions): Promise<PsyClawUpdateReceipt> {
  const now = options.now ?? (() => new Date().toISOString());
  const startedAt = now();
  const finish = (
    receipt: Omit<PsyClawUpdateReceipt, "schemaVersion" | "startedAt" | "finishedAt">,
  ): PsyClawUpdateReceipt => ({
    schemaVersion: "psyclaw/product-update/v1",
    startedAt,
    finishedAt: now(),
    ...receipt,
  });

  const manifest = await resolvePsyClawManifest(options.packageRoot);
  const emptyRuntime = { packageName: PI_CODING_AGENT };
  if (manifest === undefined) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: "psyclaw package.json not found",
      psyclaw: { packageName: "psyclaw" },
      runtime: emptyRuntime,
      commands: [],
    });
  }

  const psyclaw = { packageName: "psyclaw", before: manifest.version };
  const runtime = {
    packageName: PI_CODING_AGENT,
    ...(manifest.piVersion === undefined ? {} : { before: manifest.piVersion }),
  };

  if (await hasSourceLockfile(manifest.root)) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: "source checkout detected; update with Git, then run pnpm install and pnpm build",
      psyclaw,
      runtime,
      commands: [],
    });
  }

  const publishedPsyClawVersion = await options.registry.latestNpm("psyclaw");
  const latestDependencies = publishedPsyClawVersion === undefined
    ? undefined
    : await options.registry.npmDependencies("psyclaw", publishedPsyClawVersion);
  const publishedPiVersion = latestDependencies?.[PI_CODING_AGENT];
  if (publishedPsyClawVersion === undefined || publishedPiVersion === undefined) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: publishedPsyClawVersion === undefined
        ? "latest PsyClaw release unavailable"
        : "latest PsyClaw dependency manifest unavailable",
      psyclaw: { ...psyclaw, ...(publishedPsyClawVersion === undefined ? {} : { latest: publishedPsyClawVersion }) },
      runtime: { ...runtime, ...(publishedPiVersion === undefined ? {} : { latest: publishedPiVersion }) },
      commands: [],
    });
  }
  const latestPsyClaw = publishedPsyClawVersion;
  const latestPi = publishedPiVersion;
  if (!isSafeVersion(latestPsyClaw) || !isSafeVersion(latestPi)) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: !isSafeVersion(latestPsyClaw)
        ? `refusing unsafe PsyClaw version: ${latestPsyClaw}`
        : `refusing unsafe bundled runtime version: ${latestPi}`,
      psyclaw: { ...psyclaw, latest: latestPsyClaw },
      runtime: { ...runtime, latest: latestPi },
      commands: [],
    });
  }

  const selfComparison = compareSemver(manifest.version, latestPsyClaw);
  const runtimeComparison = manifest.piVersion === undefined ? null : compareSemver(manifest.piVersion, latestPi);
  const selfNeedsUpdate = options.force === true || selfComparison === null || selfComparison < 0;
  const runtimeNeedsRepair = selfComparison === 0 && runtimeComparison !== 0;
  const commands: string[] = [];
  // Reinstalling the product also installs its tested, exact Pi dependency.
  // Force can repair a locally drifted runtime without composing an untested
  // PsyClaw/Pi version pair.
  if (selfNeedsUpdate || runtimeNeedsRepair) {
    commands.push(buildProductCommand(latestPsyClaw));
  }

  const versions = {
    psyclaw: { ...psyclaw, latest: latestPsyClaw },
    runtime: { ...runtime, latest: latestPi },
  };
  if (commands.length === 0) {
    return finish({
      ok: true,
      executed: false,
      reasonCode: "already-up-to-date",
      psyclaw: { ...versions.psyclaw, after: latestPsyClaw },
      runtime: { ...versions.runtime, after: manifest.piVersion ?? latestPi },
      commands,
    });
  }
  if (options.executor === undefined) {
    return finish({
      ok: true,
      executed: false,
      reasonCode: "update-skipped",
      reason: "check only: no changes applied",
      ...versions,
      commands,
    });
  }

  for (const command of commands) {
    // Do not keep the updater's cwd inside the package npm is replacing. This
    // matters on Windows, where an in-use directory cannot be removed.
    const { exitCode } = await options.executor({ command, cwd: dirname(manifest.root) });
    if (exitCode !== 0) {
      return finish({
        ok: false,
        executed: true,
        reasonCode: "update-failed",
        reason: `update command failed: ${command}`,
        psyclaw: versions.psyclaw,
        runtime: versions.runtime,
        commands,
        exitCode,
      });
    }
  }

  return finish({
    ok: true,
    executed: true,
    reasonCode: "update-applied",
    psyclaw: { ...versions.psyclaw, after: latestPsyClaw },
    runtime: { ...versions.runtime, after: latestPi },
    commands,
    exitCode: 0,
  });
}

/**
 * Update the bundled Pi runtime by re-pinning both `@earendil-works/pi-*`
 * packages to the latest official release. This is the write-side counterpart
 * to `checkUpdates`: it is executor-gated, refuses non-semver versions, and
 * always returns a structured receipt. Without an executor it is a pure plan
 * (no workspace mutation).
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
    return finish({ ok: false, executed: false, reasonCode: "update-skipped", reason: "latest bundled runtime release unavailable", ...base });
  }
  if (!isSafeVersion(latest.version)) {
    return finish({
      ok: false,
      executed: false,
      reasonCode: "update-skipped",
      reason: `refusing unsafe bundled runtime version: ${latest.version}`,
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
  // npm packages intentionally omit lockfiles. Updating Pi in place can leave
  // old PsyClaw code paired with a new runtime, so repair the whole product.
  const command = manager === undefined
    ? "npm install --global psyclaw@latest"
    : buildCommand(manager, latestVersion);

  if (options.executor === undefined) {
    return finish({
      ok: true,
      executed: false,
      reasonCode: "update-skipped",
      reason: "dry run: no executor provided",
      command,
      after: latestVersion,
      ...withLatest,
    });
  }

  const { exitCode } = await options.executor({ command, cwd: manager === undefined ? dirname(manifest.root) : manifest.root });
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
