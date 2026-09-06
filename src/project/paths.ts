import { lstat, mkdir, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

export const PSYCLAW_DIR = ".psyclaw" as const;

export function projectPaths(root: string) {
  const base = resolve(root);
  return {
    root: base,
    project: resolve(base, PSYCLAW_DIR, "project.json"),
    evidence: resolve(base, PSYCLAW_DIR, "evidence.jsonl"),
    claims: resolve(base, PSYCLAW_DIR, "claims.jsonl"),
    audit: resolve(base, PSYCLAW_DIR, "audit.jsonl"),
    versions: resolve(base, PSYCLAW_DIR, "versions.jsonl"),
    analysisHooks: resolve(base, PSYCLAW_DIR, "analysis-hooks.json"),
    verifyChecklist: resolve(base, PSYCLAW_DIR, "verify-checklist.json"),
    rules: resolve(base, PSYCLAW_DIR, "rules"),
    agents: resolve(base, PSYCLAW_DIR, "agents"),
    skills: resolve(base, PSYCLAW_DIR, "skills"),
    systemNotes: resolve(base, PSYCLAW_DIR, "notes"),
    arsRuns: resolve(base, PSYCLAW_DIR, "ars-runs"),
    trust: resolve(base, PSYCLAW_DIR, "trust.json"),
    runs: resolve(base, PSYCLAW_DIR, "runs"),
    plans: resolve(base, PSYCLAW_DIR, "plans"),
    memory: resolve(base, PSYCLAW_DIR, "memory"),
    manifests: resolve(base, PSYCLAW_DIR, "manifests"),
    /** Canonical raw data (immutable). Legacy `.psyclaw/data/raw` remains protected. */
    raw: resolve(base, "data", "raw"),
    legacyRaw: resolve(base, PSYCLAW_DIR, "data", "raw"),
    clean: resolve(base, "data", "clean"),
    analysis: resolve(base, "analysis"),
    analysisScripts: resolve(base, "analysis", "scripts"),
    analysisConfigs: resolve(base, "analysis", "configs"),
    analysisResults: resolve(base, "analysis", "results"),
    analysisOutputs: resolve(base, "analysis", "outputs"),
    analysisPlans: resolve(base, "analysis", "plans"),
    analysisHandoff: resolve(base, "analysis", "HANDOFF.md"),
    literature: resolve(base, "literature"),
    literaturePdfs: resolve(base, "literature", "pdfs"),
    paper: resolve(base, "paper"),
    notes: resolve(base, "notes"),
    outputs: resolve(base, "outputs"),
    logs: resolve(base, "logs"),
    psyclawMd: resolve(base, "psyclaw.md"),
    handoffMarkdown: resolve(base, PSYCLAW_DIR, "notes", "HANDOFF.md"),
    handoffJson: resolve(base, PSYCLAW_DIR, "notes", "handoff.json"),
  };
}

export async function ensureProjectDirectories(root: string): Promise<void> {
  const paths = projectPaths(root);
  const rootStat = await lstat(paths.root);
  if (rootStat.isSymbolicLink()) throw new Error(`Project root symlink is not allowed: ${paths.root}`);
  const directoryTargets = [
    PSYCLAW_DIR,
    `${PSYCLAW_DIR}/runs`,
    `${PSYCLAW_DIR}/plans`,
    `${PSYCLAW_DIR}/memory`,
    `${PSYCLAW_DIR}/manifests`,
    `${PSYCLAW_DIR}/rules`,
    `${PSYCLAW_DIR}/agents`,
    `${PSYCLAW_DIR}/agents/custom`,
    `${PSYCLAW_DIR}/skills`,
    `${PSYCLAW_DIR}/notes`,
    `${PSYCLAW_DIR}/ars-runs`,
    `${PSYCLAW_DIR}/data`,
    `${PSYCLAW_DIR}/data/raw`,
    "data",
    "data/raw",
    "data/clean",
    "analysis",
    "analysis/scripts",
    "analysis/configs",
    "analysis/results",
    "analysis/outputs",
    "analysis/plans",
    "literature",
    "literature/pdfs",
    "paper",
    "paper/archive",
    "notes",
    "outputs",
    "logs",
  ];
  for (const target of directoryTargets) {
    const candidate = resolve(paths.root, target);
    try {
      const stat = await lstat(candidate);
      if (stat.isSymbolicLink()) throw new Error(`Protected directory symlink: ${target}`);
      if (!stat.isDirectory()) throw new Error(`Expected directory: ${target}`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      await mkdir(candidate, { recursive: false });
    }
  }
}

/**
 * Verify a write target stays inside an approved project directory and is not
 * an existing symlink. This is an application boundary, not an OS sandbox.
 */
export async function assertSafeProjectPath(root: string, target: string): Promise<string> {
  const base = resolve(root);
  // `path.resolve` is platform-specific. Normalize separators and reject all
  // absolute/drive-prefixed inputs before resolving so a project created on
  // one platform cannot be escaped by a path form from another platform.
  const rawTarget = target.trim();
  const normalizedTarget = rawTarget.replaceAll("\\", "/");
  const isCrossPlatformAbsolute =
    normalizedTarget.startsWith("/") ||
    /^\\\\/.test(rawTarget) ||
    /^[A-Za-z]:/.test(rawTarget);
  if (isCrossPlatformAbsolute) {
    throw new Error(`Path escapes project root: ${target}`);
  }

  const candidate = resolve(base, normalizedTarget);
  const rel = relative(base, candidate);
  const normalizedRel = rel.replaceAll("\\", "/");
  if (
    normalizedRel === "" ||
    normalizedRel === ".." ||
    normalizedRel.startsWith("../") ||
    isAbsolute(rel) ||
    normalizedRel.startsWith("/")
  ) {
    throw new Error(`Path escapes project root: ${target}`);
  }
  const protectedRel = normalizedRel.toLowerCase();
  if (
    protectedRel === ".git" ||
    protectedRel.startsWith(".git/") ||
    protectedRel === "data/raw" ||
    protectedRel.startsWith("data/raw/") ||
    protectedRel === ".psyclaw/data/raw" ||
    protectedRel.startsWith(".psyclaw/data/raw/") ||
    protectedRel.includes("credential") ||
    protectedRel.includes("secret")
  ) {
    throw new Error(`Protected project path is not writable: ${target}`);
  }
  try {
    const stat = await lstat(candidate);
    if (stat.isSymbolicLink()) throw new Error(`Symlink target is not writable: ${target}`);
    const resolvedCandidate = await realpath(candidate);
    const resolvedBase = await realpath(base);
    const resolvedRel = relative(resolvedBase, resolvedCandidate);
    const normalizedResolvedRel = resolvedRel.replaceAll("\\", "/");
    if (
      normalizedResolvedRel === ".." ||
      normalizedResolvedRel.startsWith("../") ||
      isAbsolute(resolvedRel) ||
      normalizedResolvedRel.startsWith("/")
    ) {
      throw new Error(`Resolved path escapes project root: ${target}`);
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      // Resolve the nearest existing ancestor so a symlinked parent cannot
      // redirect a future write outside the project root.
      let ancestor = candidate;
      while (true) {
        try {
          const resolvedAncestor = await realpath(ancestor);
          const resolvedBase = await realpath(base);
          const ancestorRel = relative(resolvedBase, resolvedAncestor);
          const normalizedAncestorRel = ancestorRel.replaceAll("\\", "/");
          if (
            normalizedAncestorRel === ".." ||
            normalizedAncestorRel.startsWith("../") ||
            isAbsolute(ancestorRel) ||
            normalizedAncestorRel.startsWith("/")
          ) {
            throw new Error(`Resolved path escapes project root: ${target}`);
          }
          return candidate;
        } catch (ancestorError) {
          if ((ancestorError as NodeJS.ErrnoException).code !== "ENOENT") throw ancestorError;
          const parent = resolve(ancestor, "..");
          if (parent === ancestor) throw ancestorError;
          ancestor = parent;
        }
      }
    }
    throw error;
  }
  return candidate;
}
