/**
 * Persist a prior recall and, once the labeled script passes, the rendered plan.
 * The first clean submission returns reflect hints once and does not accept.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicWriteFile } from "../../project/jsonl.js";
import { assertSafeProjectPath } from "../../project/paths.js";
import { PLAN_RITUAL_PHRASE } from "../plan.js";
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
    message: "Recall recorded. You can now read the data and profile it. Do not run outcome models. Write the labeled script and submit it with psyclaw_submit_plan_script.",
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
      `Accepted. Wrote ${relativeScript} and ${PRIOR_PLAN_REL}.`,
      "Ask with psyclaw_wake_options. Do not run outcome models in prior mode.",
      formatCardInstructions(rendered.cards),
      `When those cards are settled, ask the researcher to type: ${PLAN_RITUAL_PHRASE}`,
      "Execution waits until they switch to analysis.",
      findingNote,
    ].filter(Boolean).join("\n\n"),
  };
}

export async function recordPriorApproval(root: string, at = new Date().toISOString()): Promise<{ ok: boolean; message: string }> {
  try {
    await readFile(await assertSafeProjectPath(root, PRIOR_STATE_REL), "utf8");
  } catch {
    return { ok: false, message: "还没有通过检查的 prior 方案。先提交带标签的脚本。" };
  }
  await atomicWriteFile(await assertSafeProjectPath(root, PRIOR_APPROVAL_REL), `${JSON.stringify({
    schemaVersion: "psyclaw/prior-approval/v1",
    phrase: PLAN_RITUAL_PHRASE,
    at,
  }, null, 2)}\n`);
  return { ok: true, message: "已记录 prior 方案批准。执行请按 Shift+Tab 切到 analysis。prior 不跑结局模型。" };
}
