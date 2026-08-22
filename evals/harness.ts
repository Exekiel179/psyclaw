import { access, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { appendClaim, appendClaimEvidenceLink, appendEvidence } from "../src/research/ledger.js";
import { runOfflineBrief } from "../src/research/brief.js";
import { bootstrapProject } from "../src/project/bootstrap.js";
import type { Claim, ClaimEvidenceLink, Evidence, ResearchParadigm } from "../src/core/contracts.js";

const here = dirname(fileURLToPath(import.meta.url));
const CASES_DIR = resolve(here, "cases");
const RUBRICS_DIR = resolve(here, "rubrics");
const REPORTS_DIR = resolve(here, "reports");

interface CaseFile {
  id: string;
  description: string;
  paradigm: ResearchParadigm;
  expected: "pass" | "blocked";
  forbid: string[];
  evidence: Evidence[];
  claims: Claim[];
  links: ClaimEvidenceLink[];
}

interface CaseResult {
  id: string;
  description: string;
  expected: "pass" | "blocked";
  actual: "pass" | "blocked";
  ok: boolean;
  forbiddenArtifactsPresent?: string[];
}

async function loadCaseFiles(): Promise<CaseFile[]> {
  const names = (await readdir(CASES_DIR)).filter((name) => name.endsWith(".json")).sort();
  const cases: CaseFile[] = [];
  for (const name of names) {
    const value = JSON.parse(await readFile(join(CASES_DIR, name), "utf8")) as CaseFile;
    if (!value.id || !value.expected || !Array.isArray(value.evidence)) {
      throw new Error(`Invalid eval case: ${name}`);
    }
    cases.push(value);
  }
  return cases;
}

async function runCase(item: CaseFile): Promise<CaseResult> {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-eval-"));
  try {
    await bootstrapProject({
      root,
      projectId: `eval-${item.id}`,
      goal: "A bounded synthetic research question",
      paradigm: item.paradigm,
      now: "2026-01-01T00:00:00.000Z",
    });
    for (const record of item.evidence) await appendEvidence(root, record);
    for (const record of item.claims) await appendClaim(root, record);
    for (const record of item.links) await appendClaimEvidenceLink(root, record);

    const result = await runOfflineBrief(root);
    const forbiddenArtifactsPresent: string[] = [];
    for (const forbidden of item.forbid) {
      try {
        await access(join(root, forbidden));
        forbiddenArtifactsPresent.push(forbidden);
      } catch {
        // absence is the expected, passing outcome
      }
    }
    const ok = result.verdict === item.expected && forbiddenArtifactsPresent.length === 0;
    return {
      id: item.id,
      description: item.description,
      expected: item.expected,
      actual: result.verdict,
      ok,
      ...(forbiddenArtifactsPresent.length > 0 ? { forbiddenArtifactsPresent } : {}),
    };
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  const cases = await loadCaseFiles();
  const results: CaseResult[] = [];
  for (const item of cases) results.push(await runCase(item));

  const [hardFail, dimensions] = await Promise.all([
    readFile(join(RUBRICS_DIR, "hard-fail.json"), "utf8").then(JSON.parse),
    readFile(join(RUBRICS_DIR, "dimensions.json"), "utf8").then(JSON.parse),
  ]);
  const failed = results.filter((item) => !item.ok);
  const report = {
    schemaVersion: "psyclaw/eval-scorecard/v1",
    suite: "offline-research-brief",
    deterministic: true,
    rubrics: { hardFail, dimensions },
    generatedAt: new Date().toISOString(),
    cases: results,
    passed: failed.length === 0,
    hardFailCount: failed.length,
  };

  await mkdir(REPORTS_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  await writeFile(join(REPORTS_DIR, `${stamp}.json`), `${JSON.stringify(report, null, 2)}\n`);
  await writeFile(join(REPORTS_DIR, "latest.json"), `${JSON.stringify(report, null, 2)}\n`);

  console.log(JSON.stringify(report, null, 2));
  if (failed.length > 0) process.exitCode = 1;
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.stack ?? error.message : String(error));
  process.exitCode = 1;
});
