import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { GateResult } from "../core/contracts.js";
import { sha256Text } from "../core/hash.js";
import { appendJsonlIfMissing, atomicWriteFile } from "../project/jsonl.js";
import { projectPaths } from "../project/paths.js";
import { readProject } from "../research/ledger.js";
import { createStageRunner, type StageRunner } from "../run.js";
import { finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";

export const metaAnalysisSpec: WorkflowSpec = {
  id: "meta-analysis",
  version: "1.0.0",
  description: "Systematic meta-analysis: literature intake, effect-size dataset contract, R metafor audit, brief.",
  paradigms: ["meta-analysis"],
  steps: [
    { id: "intake", role: "researcher", effect: "read", description: "search OpenAlex for studies" },
    { id: "capture", role: "analyst", effect: "read", description: "bind the effect-size dataset contract" },
    { id: "audit", role: "analyst", effect: "write", description: "delegate metafor audit (I², Egger funnel)" },
    { id: "brief", role: "writer", effect: "write", description: "write the report and ledger entry" },
  ],
  requiredArtifacts: ["meta-analysis.json", "meta-analysis.md"],
};

export interface MetaStudy {
  id: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string;
  citations?: number;
}

/** Search OpenAlex for studies matching the target (real network; injectable for tests). */
export async function searchOpenAlex(target: string, nStudies: number, fetchFn: typeof fetch = fetch): Promise<MetaStudy[]> {
  const perPage = Math.min(50, Math.max(1, nStudies));
  const url = `https://api.openalex.org/works?search=${encodeURIComponent(target)}&per-page=${perPage}&mailto=psyclaw@example.org`;
  const response = await fetchFn(url, { signal: AbortSignal.timeout(15_000) });
  if (!response.ok) throw new Error(`OpenAlex 检索失败 (${response.status})`);
  const body = await response.json() as {
    results?: Array<{
      id?: string; title?: string; publication_year?: number;
      authorships?: Array<{ author?: { display_name?: string } }>;
      host_venue?: { display_name?: string }; doi?: string; cited_by_count?: number;
    }>;
  };
  return (body.results ?? []).slice(0, nStudies).map((item, index) => ({
    id: `study_${index + 1}`,
    title: item.title ?? "untitled",
    authors: (item.authorships ?? []).map((entry) => entry.author?.display_name ?? "?").slice(0, 10),
    ...(item.publication_year === undefined ? {} : { year: item.publication_year }),
    ...(item.host_venue?.display_name ? { venue: item.host_venue.display_name } : {}),
    ...(item.doi ? { doi: item.doi } : {}),
    ...(item.cited_by_count === undefined ? {} : { citations: item.cited_by_count }),
  }));
}

export interface EffectRow {
  studyId: string;
  effectSize: number;
  standardError: number;
  n?: number;
}

/** Parse a CSV with at least `study_id,effect_size,standard_error`. */
export function parseEffectCsv(text: string): EffectRow[] {
  const rows: EffectRow[] = [];
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length === 0) return rows;
  const header = lines[0]!.split(",").map((cell) => cell.trim().toLowerCase());
  // Accept the canonical names plus common shorthand (study, effect, se/g/d).
  const ALIASES: Record<string, string[]> = {
    study_id: ["study_id", "study", "id"],
    effect_size: ["effect_size", "effect", "es", "g", "d"],
    standard_error: ["standard_error", "se", "std_error", "std_err"],
  };
  const indexOf = (name: string): number => {
    const aliases = ALIASES[name] ?? [name];
    return header.findIndex((cell) => aliases.includes(cell) || cell.endsWith(name));
  };
  const studyIdx = indexOf("study_id");
  const effectIdx = indexOf("effect_size");
  const seIdx = indexOf("standard_error");
  if (studyIdx < 0 || effectIdx < 0 || seIdx < 0) return rows;
  for (const line of lines.slice(1)) {
    const cells = line.split(",").map((cell) => cell.trim());
    const effectSize = Number(cells[effectIdx]);
    const standardError = Number(cells[seIdx]);
    if (!Number.isFinite(effectSize) || !Number.isFinite(standardError) || standardError <= 0) continue;
    const n = Number(cells[header.indexOf("n")]);
    rows.push({
      studyId: cells[studyIdx] ?? `study_${rows.length + 1}`,
      effectSize,
      standardError,
      ...(Number.isFinite(n) && n > 0 ? { n } : {}),
    });
  }
  return rows;
}

export async function loadEffectDataset(root: string): Promise<EffectRow[] | undefined> {
  const candidates = ["data/clean/effects.csv", "analysis/outputs/effects.csv", "outputs/effects.csv"];
  for (const candidate of candidates) {
    try {
      const rows = parseEffectCsv(await readFile(join(root, candidate), "utf8"));
      if (rows.length > 0) return rows;
    } catch { /* try next */ }
  }
  return undefined;
}

/** R metafor script that computes the random-effects model, I², Egger's test, and the forest plot. */
export function metaforScript(datasetPath: string): string {
  return [
    "# metafor.R — 随机效应元分析（委托 R 执行；psyclaw 不在核心计算统计量）",
    "suppressMessages(library(metafor))",
    `d <- read.csv("${datasetPath.replaceAll("\\", "/")}", stringsAsFactors = FALSE)`,
    "fit <- rma(yi = d$effect_size, vi = d$standard_error^2, method = \"REML\")",
    'cat(sprintf("I2=%.1f%%\\n", fit$I2))',
    'cat(sprintf("k=%d\\n", fit$k))',
    'res <- regtest(fit, predictor = "sei")',
    'cat(sprintf("egger_p=%.3f\\n", res$pval))',
    'dir.create("outputs/figures", recursive = TRUE, showWarnings = FALSE)',
    'png("outputs/figures/forest.png", width = 800, height = 480, res = 110)',
    "forest(fit)",
    "dev.off()",
    'dir.create("analysis/outputs", recursive = TRUE, showWarnings = FALSE)',
    'saveRDS(fit, "analysis/outputs/meta_fit.rds")',
    "",
  ].join("\n");
}

export interface MetaAnalysisOptions {
  target: string;
  nStudies: number;
  fetchFn?: typeof fetch;
  runner?: StageRunner;
}

/**
 * Real meta-analysis pipeline. Statistics are never computed in core: the
 * audit stage writes an R (metafor) script and the brief records what was
 * found and what must run externally. Effect sizes come from the project's
 * dataset; without one the workflow blocks honestly instead of faking numbers.
 */
export async function runMetaAnalysis(root: string, options: MetaAnalysisOptions): Promise<WorkflowResult> {
  const runner = options.runner ?? createStageRunner();
  const project = await readProject(root);
  const gates: GateResult[] = [];

  const studies = await runner.stage(
    "intake",
    `检索 OpenAlex 数据库并提取 "${options.target}" 的实证研究`,
    async () => searchOpenAlex(options.target, options.nStudies, options.fetchFn ?? fetch),
    (found) => `命中 ${found.length} 项研究，登记为证据账本条目`,
  );
  if (studies.length < 2) {
    gates.push({ gateId: "meta:insufficient-studies", ok: false, severity: "block", reason: `需要至少 2 项研究，实际 ${studies.length}` });
  }

  const dataset = await runner.stage(
    "capture",
    "绑定效应量数据集（Hedges' g / SE）",
    async () => loadEffectDataset(root),
    (rows) => rows === undefined ? "未找到数据集，进入数据契约状态" : `解析 ${rows.length} 条效应量记录`,
  );
  if (dataset === undefined) {
    gates.push({ gateId: "meta:effect-data-missing", ok: false, severity: "block", reason: "缺少效应量数据集（data/clean/effects.csv：study_id,effect_size,standard_error）" });
  }

  const datasetPath = dataset === undefined ? null : `data/clean/effects.csv`;
  await runner.stage(
    "audit",
    "委托 R (metafor) 生成随机效应模型、I² 与 Egger 检验",
    async () => {
      const scriptPath = join(root, "analysis", "scripts", "metafor.R");
      await atomicWriteFile(scriptPath, metaforScript(datasetPath ?? "data/clean/effects.csv"));
      return scriptPath;
    },
    (path) => `已写入 ${path}；统计由 R 执行，psyclaw 不伪造 I²/Egger 数值`,
  );

  const auditNote = dataset === undefined
    ? "数据集缺失：I² 与 Egger 检验待 R 在有数据后执行"
    : `数据集就绪（${dataset.length} 条）：运行 analysis/scripts/metafor.R 得到 I² 与 Egger p 值`;

  await runner.stage(
    "brief",
    "生成元分析报告与账本条目",
    async () => {
      for (const study of studies) {
        await appendJsonlIfMissing(projectPaths(root).evidence, {
          id: `meta:${sha256Text(study.title).slice(0, 16)}`,
          source: { kind: "url", locator: study.doi ?? study.id, title: study.title },
          level: "metadata",
          retrievedAt: new Date().toISOString(),
          accessStatus: "partial",
          locators: [{ kind: "url", value: study.doi ?? "" }],
        }, (item) => item.id);
      }
      const summary = {
        schemaVersion: "psyclaw/meta-analysis/v1",
        target: options.target,
        nStudiesRequested: options.nStudies,
        studiesFound: studies.length,
        effectRows: dataset?.length ?? 0,
        audit: { delegatedTo: "R metafor", script: "analysis/scripts/metafor.R", note: auditNote },
        generatedAt: new Date().toISOString(),
      };
      const markdown = [
        `# Meta-Analysis: ${options.target}`,
        "",
        `- 检索：OpenAlex，目标 "${options.target}"，${studies.length} 项研究`,
        `- 效应量数据集：${dataset === undefined ? "缺失（需 data/clean/effects.csv）" : `${dataset.length} 条`}`,
        `- 统计：委托 R metafor（REML 随机效应、I²、Egger 漏斗回归、森林图）`,
        `- 审计：${auditNote}`,
        "",
        "## 研究清单",
        "",
        ...studies.map((study) => `- ${study.title}${study.year ? ` (${study.year})` : ""}${study.doi ? ` · ${study.doi}` : ""}`),
        "",
        "> 统计数值由 R (metafor) 在数据集就绪后计算，本文件不伪造任何效应量或检验结果。",
        "",
      ].join("\n");
      await atomicWriteFile(join(root, "analysis", "outputs", "meta-analysis.json"), `${JSON.stringify(summary, null, 2)}\n`);
      await atomicWriteFile(join(root, "analysis", "outputs", "meta-analysis.md"), markdown);
      return { studies: studies.length, rows: dataset?.length ?? 0 };
    },
    (result) => `签发 ${result.studies} 条研究账本条目，报告落盘`,
  );

  return finalizeWorkflow(root, metaAnalysisSpec, {
    gates,
    outputs: [
      { path: "meta-analysis.md", contents: `# Meta-Analysis: ${options.target}\n\n见 analysis/outputs/meta-analysis.md\n` },
      { path: "meta-analysis.json", contents: `${JSON.stringify({ target: options.target, studies: studies.length, effectRows: dataset?.length ?? 0 }, null, 2)}\n` },
    ],
    completed: ["literature intake", "effect-size contract", "metafor delegation", "report written"],
  });
}
