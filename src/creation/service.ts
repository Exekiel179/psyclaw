import { link, mkdir, open, readFile, unlink } from "node:fs/promises";
import { dirname, relative } from "node:path";
import { randomUUID } from "node:crypto";
import { parse as parseYaml } from "yaml";
import { sha256Text } from "../core/hash.js";
import { appendJsonl, atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";
import { preflightSkillBody } from "../skills/preflight.js";
import { readUserSkillState, setLocalSkillEnabled } from "../skills/user-skills.js";
import { isSafeUserHookPattern, type UserAnalysisHookFile } from "../analysis/hooks.js";
import { formatEffects, hasElevatedEffects, normalizeEffects } from "../orchestration/effects.js";
import type { CreationPreview, CreationReceipt, CreationRequest } from "./contracts.js";

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ROLES = new Set(["planner", "researcher", "analyst", "critic", "writer", "verifier"]);
const EVENTS = new Set(["before-plan", "before-analysis", "before-delegation", "before-write", "after-analysis", "before-report", "after-report"]);
const FORBIDDEN_ALWAYS = /(?:bypass|disable|ignore|skip|override).{0,30}(?:gate|approval|policy|audit)|(?:read|collect).{0,20}(?:secret|credential|token|api.?key)|external\s+(?:publish|submit)/i;
const FORBIDDEN_IMPLICIT_ELEVATION = /(?:allow|grant).{0,20}(?:write|network|shell|destructive)/i;

function clean(value: string, label: string, max = 8_000): string {
  const text = value.trim();
  if (!text || text.length > max || text.includes("\0")) throw new Error(`${label} is required and must be at most ${max} characters`);
  return text;
}

function yaml(value: string): string {
  return JSON.stringify(value);
}

async function existingHooks(root: string): Promise<UserAnalysisHookFile> {
  try {
    const safePath = await assertSafeProjectPath(root, ".psyclaw/analysis-hooks.json");
    const value = JSON.parse(await readFile(safePath, "utf8")) as UserAnalysisHookFile;
    if (value.schemaVersion !== "psyclaw/user-analysis-hooks/v1" || !Array.isArray(value.hooks)) throw new Error("invalid hook file");
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { schemaVersion: "psyclaw/user-analysis-hooks/v1", hooks: [] };
    throw error;
  }
}

async function render(root: string, request: CreationRequest): Promise<{ path: string; contents: string }> {
  const id = request.id.trim().toLowerCase();
  if (!ID.test(id)) throw new Error("id must use lowercase letters, numbers, and hyphens");
  const description = clean(request.description, "description", 1_024);
  const instructions = clean(request.instructions ?? description, "instructions");
  if (request.kind === "skill") {
    const finding = preflightSkillBody(instructions);
    if (finding.suspicious) throw new Error(`skill failed content preflight: ${finding.findings.join(", ")}`);
    return {
      path: `.psyclaw/skills/${id}/SKILL.md`,
      contents: `---
name: ${id}
description: ${yaml(description)}
risk: unknown
---

# ${id}

${instructions}
`,
    };
  }
  if (request.kind === "hook") {
    const event = request.event ?? "before-report";
    const severity = request.severity ?? "warn";
    if (!EVENTS.has(event) || (severity !== "warn" && severity !== "block")) throw new Error("invalid hook event or severity");
    if (request.pattern && !isSafeUserHookPattern(request.pattern)) throw new Error("hook pattern is outside the safe regular-expression subset");
    const current = await existingHooks(root);
    const hookId = id.startsWith("u-") ? id : `u-${id}`;
    if (current.hooks.some((hook) => hook.id === hookId)) throw new Error(`hook already exists: ${hookId}`);
    const hook = { id: hookId, event, severity, message: description, ...(request.pattern ? { pattern: request.pattern } : {}), ...(request.pathPrefix ? { pathPrefix: request.pathPrefix } : {}) };
    return { path: ".psyclaw/analysis-hooks.json", contents: `${JSON.stringify({ ...current, hooks: [...current.hooks, hook] }, null, 2)}
` };
  }
  if (FORBIDDEN_ALWAYS.test(`${description}\n${instructions}`)) throw new Error(`${request.kind} attempts to widen authority or bypass policy`);
  if (request.kind === "rule") {
    if (FORBIDDEN_IMPLICIT_ELEVATION.test(`${description}\n${instructions}`)) {
      throw new Error("rule attempts to widen authority or bypass policy");
    }
    return {
      path: `.psyclaw/rules/${id}.md`,
      contents: `---
schemaVersion: psyclaw/user-rule/v1
id: ${id}
description: ${yaml(description)}
enabled: true
---

# ${id}

${instructions}
`,
    };
  }
  const role = request.role ?? "researcher";
  if (!ROLES.has(role)) throw new Error("invalid subagent role");
  const effects = normalizeEffects(request.allowedEffects);
  if (!hasElevatedEffects(effects) && FORBIDDEN_IMPLICIT_ELEVATION.test(`${description}\n${instructions}`)) {
    throw new Error("subagent requests elevated effects without declaring allowedEffects; add write/network/destructive explicitly");
  }
  const effectLines = effects.map((effect) => `  - ${effect}`).join("\n");
  const effectNote = hasElevatedEffects(effects)
    ? `Declared effects: ${formatEffects(effects)}. Elevated tools require an interactive confirmation at each /agents run.`
    : "Default read-only. Do not write files, execute shell commands, access network services, or read credentials.";
  return {
    path: `.psyclaw/agents/custom/${id}.md`,
    contents: `---
schemaVersion: psyclaw/agent-persona/v1
id: ${id}
label: ${yaml(description)}
role: ${role}
allowedEffects:
${effectLines}
---

# ${id}

${instructions}

Return a structured psyclaw/worker-report/v1 result. ${effectNote}
`,
  };
}

export async function previewCreation(root: string, request: CreationRequest): Promise<CreationPreview> {
  const rendered = await render(root, request);
  const target = await assertSafeProjectPath(root, rendered.path);
  if (request.kind !== "hook") {
    try { await readFile(target); throw new Error(`target already exists: ${rendered.path}`); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  }
  return { schemaVersion: "psyclaw/creation-preview/v1", kind: request.kind, id: request.id.trim().toLowerCase(), path: rendered.path, contents: rendered.contents, sha256: sha256Text(rendered.contents), replacesExisting: false };
}

async function writeNoClobber(root: string, relativePath: string, contents: string): Promise<void> {
  const path = await assertSafeProjectPath(root, relativePath);
  await mkdir(dirname(path), { recursive: true });
  await assertSafeProjectPath(root, relativePath);
  const temporary = `${path}.tmp-${process.pid}-${randomUUID()}`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(contents, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    // A hard-link publishes the fully flushed inode atomically and fails if the
    // destination appeared after preview; unlike rename it never clobbers.
    await link(temporary, path);
  } finally {
    await unlink(temporary).catch(() => undefined);
  }
}

export async function applyCreation(root: string, request: CreationRequest, expectedSha256: string, approved: boolean): Promise<{ preview: CreationPreview; receipt: CreationReceipt }> {
  if (!approved) throw new Error("creation requires explicit preview approval");
  const startedAt = new Date().toISOString();
  const preview = await previewCreation(root, request);
  if (preview.sha256 !== expectedSha256) throw new Error("creation preview changed; review the new preview before applying");
  const target = await assertSafeProjectPath(root, preview.path);
  if (request.kind === "skill") {
    const state = await readUserSkillState(root);
    if (!state.disabled.includes(preview.id)) await setLocalSkillEnabled(root, preview.id, false);
  }
  if (request.kind === "hook") {
    // Re-render immediately before commit so a concurrent hook update cannot be
    // silently replaced by the approved snapshot.
    const current = await render(root, request);
    if (sha256Text(current.contents) !== expectedSha256) throw new Error("creation preview changed; review the new preview before applying");
    await atomicWriteFile(target, preview.contents);
  } else await writeNoClobber(root, preview.path, preview.contents);
  const finishedAt = new Date().toISOString();
  const receipt: CreationReceipt = {
    schemaVersion: "psyclaw/tool-receipt/v1", runId: `creation:${preview.kind}:${preview.id}`, taskId: preview.id,
    tool: "creation.apply", effect: "write", approval: "approved", idempotencyKey: `creation:${preview.kind}:${preview.id}:${preview.sha256}`,
    ok: true, resultHash: preview.sha256, startedAt, finishedAt, path: relative(root, target).replaceAll("\\", "/"), kind: preview.kind,
  };
  await appendJsonl(projectPaths(root).audit, receipt);
  return { preview, receipt };
}

export function parseCreatedFrontmatter(text: string): Record<string, unknown> {
  const match = text.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!match?.[1]) throw new Error("missing frontmatter");
  const value = parseYaml(match[1]);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid frontmatter");
  return value as Record<string, unknown>;
}
