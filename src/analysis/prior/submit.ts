/**
 * Persist a prior recall and, once the labeled script passes, the rendered plan.
 * The first clean submission returns reflect hints once and does not accept.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicWriteFile } from "../../project/jsonl.js";
import { assertSafeProjectPath } from "../../project/paths.js";
import { PLAN_RITUAL_PHRASE } from "../plan.js";
import { runAnalysisEntrypoint, type CommandRunner } from "../runtime-tools.js";
import { rewriteScriptFromChoices } from "./apply.js";
import { buildPriorMemory, PRIOR_MEMORY_REL, runFact } from "./memory.js";
import { checkPlanScript, checkRecall } from "./checks.js";
import { DEFAULT_CORE_N, formatCardInstructions, renderPriorPlan } from "./render.js";
import { reflectHints } from "./reflect.js";

export const PRIOR_RECALL_REL = ".psyclaw/prior/recall.md";
export const PRIOR_REFLECT_REL = ".psyclaw/prior/reflect.txt";
export const PRIOR_STATE_REL = ".psyclaw/prior/state.json";
export const PRIOR_APPROVAL_REL = ".psyclaw/prior/approval.json";
export const PRIOR_CONFIG_REL = ".psyclaw/prior.json";
export const PRIOR_PLAN_REL = "analysis/plans/plan.md";

export interface PriorSubmitResult {
  accepted: boolean;
  reflect: boolean;
  problems: string[];
  message: string;
  scriptPath?: string;
  planPath?: string;
}

function scriptPath(source: string): string {
  const looksR = /^\s*(library|require)\(|<-\s*function\b/m.test(source) && !/^\s*def\s+\w+\s*\(|^\s*import\s+\w+/m.test(source);
  return looksR ? "analysis/scripts/analysis.R" : "analysis/scripts/analysis.py";
}

export async function priorRecallExists(root: string): Promise<boolean> {
  try {
    await readFile(join(root, PRIOR_RECALL_REL), "utf8");
    return true;
  } catch {
    return false;
  }
}

export async function readCoreN(root: string): Promise<number> {
  try {
    const raw = JSON.parse(await readFile(join(root, PRIOR_CONFIG_REL), "utf8")) as { coreN?: unknown };
    if (typeof raw.coreN === "number" && Number.isInteger(raw.coreN) && raw.coreN >= 1 && raw.coreN <= 20) return raw.coreN;
  } catch { /* default */ }
  return DEFAULT_CORE_N;
}

export async function submitPriorRecall(root: string, recall: string): Promise<PriorSubmitResult> {
  const problems = checkRecall(recall);
  if (problems.length > 0) {
    return { accepted: false, reflect: false, problems, message: `Rejected. Fix the recall and submit again:\n${problems.join("\n")}` };
  }
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_RECALL_REL), `${recall.trim()}\n`);
  return {
    accepted: true,
    reflect: false,
    problems: [],
    message: "Recall recorded. You can now read the data and profile it. Do not call any skill and do not run outcome models. Write the labeled script and submit it with psyclaw_submit_plan_script.",
  };
}

export async function submitPriorScript(root: string, source: string): Promise<PriorSubmitResult> {
  let recall = "";
  try {
    recall = await readFile(join(root, PRIOR_RECALL_REL), "utf8");
  } catch {
    return {
      accepted: false,
      reflect: false,
      problems: ["Submit psyclaw_submit_recall before the script."],
      message: "Rejected. Submit psyclaw_submit_recall before the script.",
    };
  }
  const problems = checkPlanScript(source, recall);
  if (problems.length > 0) {
    return { accepted: false, reflect: false, problems, message: `Rejected. Fix these and submit again:\n${problems.map((problem) => `- ${problem}`).join("\n")}` };
  }
  const hints = reflectHints(source);
  let reflectSeen = false;
  try {
    await readFile(join(root, PRIOR_REFLECT_REL), "utf8");
    reflectSeen = true;
  } catch { /* first pass */ }
  if (hints.length > 0 && !reflectSeen) {
    await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_REFLECT_REL), `${hints.join("\n")}\n`);
    return {
      accepted: false,
      reflect: true,
      problems: [],
      message: `Recorded. Look again at these places, then submit again. Submit unchanged if nothing applies:\n${hints.join("\n")}`,
    };
  }
  const coreN = await readCoreN(root);
  const rendered = renderPriorPlan(source, coreN);
  const relativeScript = scriptPath(source);
  await atomicWriteFile(await assertSafeProjectPath(root, relativeScript), source.endsWith("\n") ? source : `${source}\n`);
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_PLAN_REL), rendered.markdown);
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_STATE_REL), `${JSON.stringify({
    schemaVersion: "psyclaw/prior-plan/v1",
    script: relativeScript,
    plan: PRIOR_PLAN_REL,
    coreN,
    findings: rendered.findings,
    cards: rendered.cards,
  }, null, 2)}\n`);
  if (!reflectSeen) await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_REFLECT_REL), "(none)\n");
  const findingNote = rendered.findings.length > 0
    ? `\nPlan check:\n${rendered.findings.map((finding) => `- ${finding}`).join("\n")}`
    : "";
  return {
    accepted: true,
    reflect: false,
    problems: [],
    scriptPath: relativeScript,
    planPath: PRIOR_PLAN_REL,
    message: [
      `Accepted. Wrote ${relativeScript} and ${PRIOR_PLAN_REL}. Do not call skills and do not run the script yourself.`,
      "Ask with psyclaw_wake_options.",
      formatCardInstructions(rendered.cards),
      `When those cards are settled, ask the researcher to type: ${PLAN_RITUAL_PHRASE}`,
      "That approval writes the chosen values into the script, runs it, and returns the session to plain chat. Skills are available only after that.",
      findingNote,
    ].filter(Boolean).join("\n\n"),
  };
}

export async function priorPlanExists(root: string): Promise<boolean> {
  try {
    await readFile(join(root, PRIOR_STATE_REL), "utf8");
    return true;
  } catch {
    return false;
  }
}

export async function priorApproved(root: string): Promise<boolean> {
  try {
    await readFile(join(root, PRIOR_APPROVAL_REL), "utf8");
    return true;
  } catch {
    return false;
  }
}

const FAILED_TAIL_LINES = 8;
const FAILED_TAIL_CHARS = 500;

/** A failed run is pasted into the user message, so later turns keep paying for it. Keep the exit line, the log path, and the error tail. */
export function briefFailedRun(output: string): { failed: boolean; text: string } {
  const lines = output.split("\n");
  const header = lines[0] ?? "";
  const failed = /\(exit (?!0\b)\d+\)/.test(header) || !header.startsWith("Ran ");
  if (!failed) return { failed: false, text: output };
  const log = lines.find((line) => line.startsWith("Log: "));
  let tail = lines.slice(-FAILED_TAIL_LINES).join("\n");
  if (tail.length > FAILED_TAIL_CHARS) tail = tail.slice(tail.length - FAILED_TAIL_CHARS);
  return {
    failed: true,
    text: [header, log, tail, "完整日志留在磁盘。不要读取日志，不要把报错复述进回复。"].filter((line): line is string => Boolean(line)).join("\n"),
  };
}

export async function recordPriorApproval(
  root: string,
  at = new Date().toISOString(),
  run?: CommandRunner,
): Promise<{ ok: boolean; handoff: boolean; runFailed: boolean; message: string }> {
  let state: { script?: unknown };
  try {
    state = JSON.parse(await readFile(await assertSafeProjectPath(root, PRIOR_STATE_REL), "utf8")) as { script?: unknown };
  } catch {
    return { ok: false, handoff: false, runFailed: false, message: "还没有通过检查的 prior 方案。先提交带标签的脚本。" };
  }
  const scriptRelative = typeof state.script === "string" ? state.script : "";
  let changes: string[] = [];
  if (scriptRelative) {
    try {
      const source = await readFile(join(root, scriptRelative), "utf8");
      changes = (await rewriteScriptFromChoices(root, scriptRelative, source)).changes;
    } catch {
      return { ok: false, handoff: false, runFailed: false, message: "方案脚本读不到，没有改代码，也没有开始执行。" };
    }
  }
  let output = "";
  try {
    output = await runAnalysisEntrypoint(root, {
      ...(scriptRelative ? { entrypoint: scriptRelative } : {}),
      force: true,
      ...(run ? { run } : {}),
    });
  } catch (error) {
    output = error instanceof Error ? error.message : String(error);
  }
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_APPROVAL_REL), `${JSON.stringify({
    schemaVersion: "psyclaw/prior-approval/v1",
    phrase: PLAN_RITUAL_PHRASE,
    at,
    changes,
  }, null, 2)}\n`);
  try {
    const planMarkdown = await readFile(join(root, PRIOR_PLAN_REL), "utf8");
    await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_MEMORY_REL), buildPriorMemory(planMarkdown, {
      script: scriptRelative,
      run: runFact(output),
    }));
  } catch {
    // The run still stands if the memory file cannot be written.
  }
  const edited = changes.length > 0 ? `已按确认结果改写：${changes.join("；")}。` : "确认结果与脚本当前取值一致，常量未改。";
  const brief = briefFailedRun(output);
  const lead = brief.failed
    ? `${edited}脚本已执行但未成功。后续分析以已定稿方案为准。会话回到普通对话。`
    : `${edited}脚本已执行。后续分析以已定稿方案为准。会话回到普通对话，此后可以使用 skill。`;
  return { ok: true, handoff: true, runFailed: brief.failed, message: `${lead}\n${brief.text}` };
}
