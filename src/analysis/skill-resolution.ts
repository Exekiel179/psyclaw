/**
 * Which skills loaded, which same-name skills were skipped, and which
 * method bodies were injected. The session custom entry is the per-session
 * record. The JSON file is what a headless receipt can attach after the
 * child exits. Injection dedup is the session, not the file: a new process
 * injects again.
 */
import { readFile, stat } from "node:fs/promises";
import { basename, relative, resolve } from "node:path";
import { atomicWriteFile } from "../project/jsonl.js";
import { accessFor, loadDataAccess } from "../safety/data-access.js";
import { coreSkillNames, enabledRecommendedSkillPaths } from "../skills/recommended.js";
import { enabledLocalPromptPaths, enabledLocalSkillPaths, readSkillDocument } from "../skills/user-skills.js";
import {
  bundledCoreSkillsDir,
  loadCoreMethodSkills,
  METHOD_TOPICS,
  methodTopicsIn,
  renderMethodBlocks,
  userSkillWinsNote,
  type InjectionBlock,
  type MethodTopic,
} from "./method-rules.js";

export const SKILL_RESOLUTION_FILE = ".psyclaw/skill-resolution.json";
export const SKILL_PREFERENCES_FILE = ".psyclaw/skill-preferences.json";
export const SKILL_RESOLUTION_ENTRY = "psyclaw-skill-resolution";

export type SkillBodyChoice = "user" | "core" | "both";

export interface SkillResolutionLoaded {
  name: string;
  source: "core" | "recommended" | "local";
  path: string;
}

export interface SkillResolutionSkipped {
  name: string;
  path: string;
  reason: "core-name" | "duplicate";
  warning?: string;
}

export interface SkillResolutionInjected {
  topic: string;
  skill: string;
  path: string;
  source: "core" | "user" | "both" | "catalog";
  chars: number;
}

export interface SkillResolution {
  schemaVersion: "psyclaw/skill-resolution/v1";
  loaded: SkillResolutionLoaded[];
  skipped: SkillResolutionSkipped[];
  injected: SkillResolutionInjected[];
}

export interface SkillPreferences {
  schemaVersion: "psyclaw/skill-preferences/v1";
  choices: Record<string, SkillBodyChoice>;
}

const injectedTopicsByCwd = new Map<string, Set<string>>();
const resolutionStarted = new Set<string>();

export function resetInjectedTopicsForTests(): void {
  injectedTopicsByCwd.clear();
  resolutionStarted.clear();
}

export function preferenceKey(topic: string, skillName: string): string {
  return `${topic}::${skillName}`;
}

export function injectedTopicsFor(cwd: string, branch: readonly unknown[] = []): Set<string> {
  const seen = new Set(injectedTopicsByCwd.get(resolve(cwd)) ?? []);
  for (const entry of branch) {
    if (!isRecord(entry) || entry.type !== "custom" || entry.customType !== SKILL_RESOLUTION_ENTRY) continue;
    const data = isRecord(entry.data) ? entry.data : undefined;
    const injected = Array.isArray(data?.injected) ? data.injected : [];
    for (const row of injected) {
      if (isRecord(row) && typeof row.topic === "string" && row.source !== "catalog") seen.add(row.topic);
    }
  }
  return seen;
}

export function rememberInjectedTopic(cwd: string, topic: string): void {
  const key = resolve(cwd);
  const seen = injectedTopicsByCwd.get(key) ?? new Set<string>();
  seen.add(topic);
  injectedTopicsByCwd.set(key, seen);
}

export async function readSkillPreferences(cwd: string): Promise<SkillPreferences> {
  try {
    const parsed = JSON.parse(await readFile(resolve(cwd, SKILL_PREFERENCES_FILE), "utf8")) as unknown;
    if (!isRecord(parsed) || !isRecord(parsed.choices)) return emptyPreferences();
    const choices: Record<string, SkillBodyChoice> = {};
    for (const [key, value] of Object.entries(parsed.choices)) {
      if (value === "user" || value === "core" || value === "both") choices[key] = value;
    }
    return { schemaVersion: "psyclaw/skill-preferences/v1", choices };
  } catch {
    return emptyPreferences();
  }
}

export async function writeSkillPreferences(cwd: string, preferences: SkillPreferences): Promise<void> {
  await atomicWriteFile(resolve(cwd, SKILL_PREFERENCES_FILE), `${JSON.stringify(preferences, null, 2)}\n`);
}

export async function readSkillResolution(cwd: string): Promise<SkillResolution | undefined> {
  try {
    const parsed = JSON.parse(await readFile(resolve(cwd, SKILL_RESOLUTION_FILE), "utf8")) as unknown;
    if (!isRecord(parsed) || parsed.schemaVersion !== "psyclaw/skill-resolution/v1") return undefined;
    return parsed as unknown as SkillResolution;
  } catch {
    return undefined;
  }
}

export async function writeSkillResolution(cwd: string, resolution: SkillResolution): Promise<void> {
  await atomicWriteFile(resolve(cwd, SKILL_RESOLUTION_FILE), `${JSON.stringify(resolution, null, 2)}\n`);
}

export async function refreshSkillResolution(cwd: string): Promise<{
  recommendedPaths: string[];
  localPaths: string[];
  promptPaths: string[];
  resolution: SkillResolution;
}> {
  const recommended = await enabledRecommendedSkillPaths(cwd);
  const excluded = [...coreSkillNames(), ...await skillNamesOf(recommended.paths)];
  const local = await enabledLocalSkillPaths(cwd, { excludedNames: excluded });
  const bundled = bundledCoreSkillsDir();
  const skipped: SkillResolutionSkipped[] = local.skipped.filter((row) => !isInside(row.path, bundled));
  for (const warning of recommended.warnings) {
    if (!warning.includes("conflicts with a PsyClaw core Skill")) continue;
    skipped.push({ name: /Skill '([^']+)'/.exec(warning)?.[1] ?? warning, path: "", reason: "core-name", warning });
  }
  const loaded: SkillResolutionLoaded[] = [
    ...coreSkillNames().map((name) => ({ name, source: "core" as const, path: resolve(bundled, name) })),
    ...recommended.paths.map((path) => ({ name: basename(path), source: "recommended" as const, path })),
    ...local.loaded.map((skill) => ({ name: skill.name, source: "local" as const, path: skill.path })),
  ];
  const key = resolve(cwd);
  const firstInProcess = !resolutionStarted.has(key);
  resolutionStarted.add(key);
  const previous = firstInProcess ? undefined : await readSkillResolution(cwd);
  const resolution: SkillResolution = {
    schemaVersion: "psyclaw/skill-resolution/v1",
    loaded,
    skipped,
    injected: previous?.injected ?? [],
  };
  await writeSkillResolution(cwd, resolution);
  return {
    recommendedPaths: recommended.paths,
    localPaths: local.paths,
    promptPaths: await enabledLocalPromptPaths(cwd),
    resolution,
  };
}

export async function selectOrDefault(
  select: () => Promise<string | undefined>,
  timeoutMs: number,
): Promise<string | undefined> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<undefined>((resolveTimeout) => {
    timer = setTimeout(() => resolveTimeout(undefined), timeoutMs);
  });
  try {
    return await Promise.race([select(), timeout]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

export interface TopicConflict {
  topic: MethodTopic;
  skillName: string;
  skillPath: string;
  description: string;
  body: string;
  corePath: string;
  coreBody: string;
  coreName: string;
}

const CHOICE_LABELS: Record<SkillBodyChoice, string> = {
  user: "用户 skill（默认）",
  core: "核心细则",
  both: "两者都注入，冲突时以用户 skill 为准",
};

export async function resolveTopicChoice(
  cwd: string,
  conflict: TopicConflict,
  hasUI: boolean,
  select: ((title: string, labels: string[]) => Promise<string | undefined>) | undefined,
  timeoutMs = 60_000,
): Promise<SkillBodyChoice> {
  const preferences = await readSkillPreferences(cwd);
  const key = preferenceKey(conflict.topic, conflict.skillName);
  const saved = preferences.choices[key];
  if (saved !== undefined) return saved;
  // Only an explicit pick is remembered. The default (headless run, or a card that timed out)
  // applies to this turn and leaves the conflict open, so an interactive session still asks.
  let choice: SkillBodyChoice = "user";
  let picked: string | undefined;
  if (hasUI && select) {
    const labels = [CHOICE_LABELS.user, CHOICE_LABELS.core, CHOICE_LABELS.both];
    picked = await selectOrDefault(
      () => select(
        `方法主题 ${conflict.topic} 与用户 skill ${conflict.skillName} 冲突。本回合注入哪一份？`,
        labels,
      ),
      timeoutMs,
    );
    if (picked === CHOICE_LABELS.core) choice = "core";
    else if (picked === CHOICE_LABELS.both) choice = "both";
  }
  if (picked !== undefined && Object.values(CHOICE_LABELS).includes(picked)) {
    preferences.choices[key] = choice;
    await writeSkillPreferences(cwd, preferences);
  }
  return choice;
}

export async function recordInjection(cwd: string, rows: readonly SkillResolutionInjected[]): Promise<SkillResolution> {
  const current = (await readSkillResolution(cwd)) ?? {
    schemaVersion: "psyclaw/skill-resolution/v1" as const,
    loaded: [],
    skipped: [],
    injected: [],
  };
  const resolution: SkillResolution = { ...current, injected: [...current.injected, ...rows] };
  await writeSkillResolution(cwd, resolution);
  // A catalog line is not the body; the topic stays pending so a later turn can inject it.
  for (const row of rows) if (row.source !== "catalog") rememberInjectedTopic(cwd, row.topic);
  return resolution;
}

export async function userSkillsOutsideScriptOnly(cwd: string): Promise<Array<{
  name: string;
  path: string;
  description: string;
  topics: string[];
  body: string;
}>> {
  const rules = await loadDataAccess(cwd);
  const excluded = new Set(coreSkillNames().map((name) => name.toLocaleLowerCase()));
  const local = await enabledLocalSkillPaths(cwd, { excludedNames: excluded });
  const skills = [];
  for (const skill of local.loaded) {
    const rel = relative(cwd, skill.path);
    if (accessFor(rel, rules.entries) === "script-only") continue;
    const document = await readSkillDocument(skill.path);
    if (!document) continue;
    skills.push({
      name: document.name,
      path: skill.path,
      description: document.description,
      topics: document.topics,
      body: document.body,
    });
  }
  return skills;
}

const DOCUMENT_REF = /(?:^|[\s`'"(（])((?:[\w.-]+\/)*[\w.-]+\.(?:md|txt))(?=$|[\s`'"),.;:，。；：）])/gi;
const DOCUMENT_CHAR_CAP = 200_000;

/**
 * Method topics in the task documents a message names (for example "Read BRIEF.md").
 * A request often names the task file rather than the method, so detection on the
 * message alone misses the topic. Files outside the project or script-only are skipped.
 */
export async function referencedDocumentTopics(cwd: string, text: string): Promise<{ documents: string[]; topics: MethodTopic[] }> {
  const root = resolve(cwd);
  const rules = await loadDataAccess(cwd);
  const documents: string[] = [];
  const found = new Set<MethodTopic>();
  for (const match of text.matchAll(DOCUMENT_REF)) {
    const ref = match[1];
    if (!ref) continue;
    const absolute = resolve(root, ref);
    const rel = relative(root, absolute);
    if (rel.startsWith("..") || rel.startsWith("/") || documents.includes(rel)) continue;
    if (accessFor(rel, rules.entries) === "script-only") continue;
    const info = await stat(absolute).catch(() => undefined);
    if (!info?.isFile()) continue;
    const content = (await readFile(absolute, "utf8").catch(() => "")).slice(0, DOCUMENT_CHAR_CAP);
    documents.push(rel);
    for (const topic of methodTopicsIn(content)) found.add(topic);
  }
  return { documents, topics: METHOD_TOPICS.filter((topic) => found.has(topic)) };
}

async function skillNamesOf(paths: readonly string[]): Promise<string[]> {
  const names: string[] = [];
  for (const path of paths) {
    const document = await readSkillDocument(path);
    if (document) names.push(document.name);
  }
  return names;
}

function emptyPreferences(): SkillPreferences {
  return { schemaVersion: "psyclaw/skill-preferences/v1", choices: {} };
}

function isInside(path: string, parent: string): boolean {
  const rel = relative(resolve(parent), resolve(path));
  return rel === "" || (!rel.startsWith("..") && !rel.startsWith("/"));
}

export async function composeMethodInjection(options: {
  cwd: string;
  topics: readonly MethodTopic[];
  seen: ReadonlySet<string>;
  hasUI: boolean;
  select?: (title: string, labels: string[]) => Promise<string | undefined>;
  /** Test hook. Production loads enabled user skills. */
  userSkills?: Awaited<ReturnType<typeof userSkillsOutsideScriptOnly>>;
  choiceTimeoutMs?: number;
}): Promise<{ text: string; resolution?: SkillResolution }> {
  const pending = options.topics.filter((topic) => !options.seen.has(topic));
  if (pending.length === 0) return { text: "" };
  const coreByTopic = new Map((await loadCoreMethodSkills()).map((skill) => [skill.topic, skill]));
  const users = options.userSkills ?? await userSkillsOutsideScriptOnly(options.cwd);
  const blocks: InjectionBlock[] = [];
  for (const topic of pending) {
    const coreSkill = coreByTopic.get(topic);
    if (!coreSkill) continue;
    const user = users.find((skill) => skillMatchesTopic(skill, topic, coreSkill.name));
    if (!user) {
      blocks.push({ topic, skill: coreSkill.name, path: coreSkill.path, source: "core", body: coreSkill.body });
      continue;
    }
    const choice = await resolveTopicChoice(options.cwd, {
      topic,
      skillName: user.name,
      skillPath: user.path,
      description: user.description,
      body: user.body,
      corePath: coreSkill.path,
      coreBody: coreSkill.body,
      coreName: coreSkill.name,
    }, options.hasUI, options.select, options.choiceTimeoutMs ?? 60_000);
    const note = userSkillWinsNote(user.name, user.path, coreSkill.path);
    if (choice === "core") {
      blocks.push({ topic, skill: coreSkill.name, path: coreSkill.path, source: "core", body: coreSkill.body });
    } else if (choice === "both") {
      blocks.push({ topic, skill: user.name, path: user.path, source: "both", body: `${note}\n\n${user.body}\n\n${coreSkill.body}` });
    } else {
      blocks.push({ topic, skill: user.name, path: user.path, source: "user", body: `${note}\n\n${user.body}` });
    }
  }
  const rendered = renderMethodBlocks(blocks);
  if (!rendered.text) return { text: "" };
  const rows: SkillResolutionInjected[] = [
    ...rendered.included.map((topic) => {
      const block = blocks.find((item) => item.topic === topic)!;
      return { topic, skill: block.skill, path: block.path, source: block.source, chars: block.body.length };
    }),
    ...rendered.catalog.map((topic) => {
      const block = blocks.find((item) => item.topic === topic)!;
      return { topic, skill: block.skill, path: block.path, source: "catalog" as const, chars: 0 };
    }),
  ];
  return { text: rendered.text, resolution: await recordInjection(options.cwd, rows) };
}

function skillMatchesTopic(
  skill: { name: string; description: string; topics: readonly string[] },
  topic: MethodTopic,
  coreName: string,
): boolean {
  if (skill.topics.includes(topic) || skill.topics.includes(coreName)) return true;
  return methodTopicsIn(`${skill.name}\n${skill.description}`).includes(topic);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
