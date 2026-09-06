/**
 * Academic soft-route intent eval.
 *
 * Metrics:
 * - primaryAccuracy: gold primary == predicted primary (incl. both-null)
 * - primaryRecall / primaryPrecision / primaryF1 over cases with a gold primary
 * - setRecall@k / setPrecision@k for multi (and singles with k=1)
 * - perSkillRecall / perDifficultyAccuracy
 * - negativePrecision: gold-null cases that stay null
 *
 * Run: pnpm eval:academic-route
 */
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  rankAcademicSoftRoutes,
  resolveAcademicSoftRoute,
  type AcademicSoftRouteSkill,
} from "../../src/ars/academic-router.js";
import {
  ACADEMIC_SOFT_ROUTE_EVAL_CASES,
  type SoftRouteDifficulty,
  type SoftRouteEvalCase,
} from "./cases.js";

const here = dirname(fileURLToPath(import.meta.url));
const REPORTS_DIR = resolve(here, "reports");
const TOP_K = 3;

interface CaseScore {
  id: string;
  kind: SoftRouteEvalCase["kind"];
  difficulty: SoftRouteDifficulty;
  text: string;
  expectedPrimary: AcademicSoftRouteSkill | null;
  predictedPrimary: AcademicSoftRouteSkill | null;
  expectedSkills: AcademicSoftRouteSkill[];
  predictedSkills: AcademicSoftRouteSkill[];
  primaryOk: boolean;
  modeHintOk: boolean;
  setRecallAtK: number;
  setPrecisionAtK: number;
}

function scoreCase(item: SoftRouteEvalCase): CaseScore {
  const ranked = rankAcademicSoftRoutes(item.text, TOP_K);
  const predictedPrimary = resolveAcademicSoftRoute(item.text)?.skill ?? null;
  const predictedSkills = ranked.map((row) => row.skill);
  const primaryOk = predictedPrimary === item.expectedPrimary;
  const predictedHint = ranked.find((row) => row.skill === item.expectedPrimary)?.modeHint
    ?? resolveAcademicSoftRoute(item.text)?.modeHint;
  const modeHintOk = item.expectedModeHint
    ? predictedHint === item.expectedModeHint
    : true;

  const expectedSet = new Set(item.expectedSkills);
  const predictedSet = predictedSkills.slice(0, TOP_K);
  const hit = predictedSet.filter((skill) => expectedSet.has(skill)).length;
  const setRecallAtK = expectedSet.size === 0
    ? (predictedSet.length === 0 ? 1 : 0)
    : hit / expectedSet.size;
  const setPrecisionAtK = predictedSet.length === 0
    ? (expectedSet.size === 0 ? 1 : 0)
    : hit / predictedSet.length;

  return {
    id: item.id,
    kind: item.kind,
    difficulty: item.difficulty,
    text: item.text,
    expectedPrimary: item.expectedPrimary,
    predictedPrimary,
    expectedSkills: item.expectedSkills,
    predictedSkills,
    primaryOk,
    modeHintOk,
    setRecallAtK,
    setPrecisionAtK,
  };
}

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function f1(precision: number, recall: number): number {
  if (precision + recall === 0) return 0;
  return (2 * precision * recall) / (precision + recall);
}

function main(): void {
  const scores = ACADEMIC_SOFT_ROUTE_EVAL_CASES.map(scoreCase);
  const withPrimary = scores.filter((row) => row.expectedPrimary !== null);
  const negatives = scores.filter((row) => row.expectedPrimary === null);
  const multis = scores.filter((row) => row.kind === "multi");

  const primaryHits = withPrimary.filter((row) => row.primaryOk).length;
  const primaryRecall = withPrimary.length === 0 ? 0 : primaryHits / withPrimary.length;
  // Precision among cases where router fired a primary
  const fired = scores.filter((row) => row.predictedPrimary !== null);
  const preciseHits = fired.filter((row) => row.primaryOk && row.expectedPrimary !== null).length;
  const primaryPrecision = fired.length === 0 ? 0 : preciseHits / fired.length;
  const negativePrecision = negatives.length === 0
    ? 1
    : negatives.filter((row) => row.predictedPrimary === null).length / negatives.length;

  const perSkill: Record<string, { support: number; recall: number }> = {};
  for (const skill of new Set(withPrimary.map((row) => row.expectedPrimary!))) {
    const rows = withPrimary.filter((row) => row.expectedPrimary === skill);
    const hits = rows.filter((row) => row.primaryOk).length;
    perSkill[skill] = { support: rows.length, recall: rows.length === 0 ? 0 : hits / rows.length };
  }

  const perDifficulty: Record<string, { support: number; primaryAccuracy: number; setRecallAtK: number }> = {};
  for (const difficulty of ["easy", "medium", "hard"] as SoftRouteDifficulty[]) {
    const rows = scores.filter((row) => row.difficulty === difficulty);
    perDifficulty[difficulty] = {
      support: rows.length,
      primaryAccuracy: mean(rows.map((row) => (row.primaryOk ? 1 : 0))),
      setRecallAtK: mean(rows.map((row) => row.setRecallAtK)),
    };
  }

  const failures = scores.filter((row) => !row.primaryOk || !row.modeHintOk || row.setRecallAtK < 1);
  const report = {
    schemaVersion: "psyclaw/academic-soft-route-eval/v1",
    suite: "academic-soft-route",
    generatedAt: new Date().toISOString(),
    caseCount: scores.length,
    topK: TOP_K,
    metrics: {
      primaryAccuracy: mean(scores.map((row) => (row.primaryOk ? 1 : 0))),
      primaryRecall,
      primaryPrecision,
      primaryF1: f1(primaryPrecision, primaryRecall),
      modeHintAccuracy: mean(withPrimary.map((row) => (row.modeHintOk ? 1 : 0))),
      setRecallAtK: mean(scores.map((row) => row.setRecallAtK)),
      setPrecisionAtK: mean(scores.map((row) => row.setPrecisionAtK)),
      multiSetRecallAtK: mean(multis.map((row) => row.setRecallAtK)),
      multiPrimaryAccuracy: mean(multis.map((row) => (row.primaryOk ? 1 : 0))),
      negativePrecision,
    },
    perSkill,
    perDifficulty,
    failures: failures.map((row) => ({
      id: row.id,
      kind: row.kind,
      difficulty: row.difficulty,
      text: row.text,
      expectedPrimary: row.expectedPrimary,
      predictedPrimary: row.predictedPrimary,
      expectedSkills: row.expectedSkills,
      predictedSkills: row.predictedSkills,
      modeHintOk: row.modeHintOk,
      setRecallAtK: row.setRecallAtK,
    })),
    cases: scores,
    passed: failures.length === 0
      && primaryRecall >= 0.9
      && primaryPrecision >= 0.9
      && negativePrecision >= 0.9,
  };

  void (async () => {
    await mkdir(REPORTS_DIR, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    await writeFile(join(REPORTS_DIR, `academic-route-${stamp}.json`), `${JSON.stringify(report, null, 2)}\n`);
    await writeFile(join(REPORTS_DIR, "academic-route-latest.json"), `${JSON.stringify(report, null, 2)}\n`);
    console.log(JSON.stringify({
      passed: report.passed,
      metrics: report.metrics,
      perSkill: report.perSkill,
      perDifficulty: report.perDifficulty,
      failureCount: report.failures.length,
      failures: report.failures,
    }, null, 2));
    if (!report.passed) process.exitCode = 1;
  })().catch((error: unknown) => {
    console.error(error instanceof Error ? error.stack ?? error.message : String(error));
    process.exitCode = 1;
  });
}

main();
