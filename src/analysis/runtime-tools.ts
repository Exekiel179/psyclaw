/**
 * Research execution tools. They save or run a script and return a bounded
 * summary. Statistical procedures stay in the R/Python script.
 */
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, readdir, realpath, writeFile } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { sha256File } from "../core/hash.js";
import { requirePython } from "../platform/python.js";
import { recallToolOutput } from "./output-log.js";

const execFileAsync = promisify(execFile);

const PROFILE_SCRIPT = "analysis/scripts/psyclaw_profile_data.py";
const LOOKUP_SCRIPT = "analysis/scripts/psyclaw_codebook_lookup.py";
const RUN_RECEIPT = "analysis/results/psyclaw-run-receipt.json";
const RUN_LOG = "analysis/results/psyclaw-run.log";
const RECEIPT_VERSION = "psyclaw/analysis-run/v1";
const ENTRY_CANDIDATES = [
  "analysis/scripts/run_all.R",
  "analysis/scripts/run_all.py",
  "results/analysis.R",
  "results/analysis.py",
  "analysis.R",
  "analysis.py",
] as const;
const RESULT_ROOTS = ["analysis/results", "results/tables", "results"] as const;
const PROFILE_COLUMN_CAP = 40;
const LOOKUP_MATCH_CAP = 60;
const RESULT_FILE_CAP = 3;
const RESULT_LINE_CAP = 40;
const RESULT_CHAR_CAP = 4_000;
const RUN_TAIL_CHARS = 4_000;
const DEFAULT_RUN_TIMEOUT_MS = 600_000;

const PROFILE_SOURCE = `import csv, json, sys
from pathlib import Path

path = Path(sys.argv[1])
missing_tokens = {"", "na", "nan", "null"}
with path.open(newline="", encoding="utf-8-sig") as handle:
    sample = handle.read(65536)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(handle, dialect=dialect)
    fields = list(reader.fieldnames or [])
    missing = {name: 0 for name in fields}
    rows = 0
    for row in reader:
        rows += 1
        for name in fields:
            value = (row.get(name) or "").strip().lower()
            if value in missing_tokens:
                missing[name] += 1
print(json.dumps({"rows": rows, "columns": [{"name": name, "missing": missing[name]} for name in fields]}, ensure_ascii=False))
`;

const LOOKUP_SOURCE = `import json, re, sys
from pathlib import Path

path = Path(sys.argv[1])
terms = [t.lower() for t in re.split(r"[,\\s]+", sys.argv[2]) if t] if len(sys.argv) > 2 else []
cap = int(sys.argv[3]) if len(sys.argv) > 3 else 60
try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl is not installed; this Python cannot read xlsx codebooks.")
book = openpyxl.load_workbook(path, read_only=True, data_only=True)
sheets, matches, total = [], [], 0
for sheet in book.worksheets:
    rows = 0
    header = ""
    for number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        text = " | ".join(" ".join(str(cell).split()) for cell in row if cell is not None and str(cell).strip())
        if not text:
            continue
        rows += 1
        if not header:
            header = text[:300]
        # A term matches at the start of a word, so "nce" finds nce1_T1 but not "vaccine".
        if terms and any(re.search(r"(?<![a-z0-9])" + re.escape(term), text.lower()) for term in terms):
            total += 1
            if len(matches) < cap:
                matches.append({"sheet": sheet.title, "row": number, "text": text[:300]})
    sheets.append({"name": sheet.title, "rows": rows, "header": header})
print(json.dumps({"sheets": sheets, "matches": matches, "total": total}, ensure_ascii=False))
`;

export interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

export type CommandRunner = (
  command: string,
  args: readonly string[],
  options: { cwd: string; timeoutMs: number },
) => Promise<CommandResult>;

interface RunReceipt {
  schemaVersion: typeof RECEIPT_VERSION;
  entrypoint: string;
  scriptDigest: string;
  exitCode: number;
  log: string;
  tail: string;
}

function toolText(text: string, isError = false): { content: [{ type: "text"; text: string }]; details: undefined; isError?: true } {
  return { content: [{ type: "text", text }], details: undefined, ...(isError ? { isError: true as const } : {}) };
}

export async function resolveProjectRead(root: string, target: string): Promise<{ absolute: string; relativePath: string }> {
  const rawTarget = target.trim();
  const normalizedTarget = rawTarget.replaceAll("\\", "/");
  if (normalizedTarget.startsWith("/") || /^[A-Za-z]:/.test(rawTarget) || /^\\\\/.test(rawTarget)) {
    throw new Error(`Path escapes project root: ${target}`);
  }
  const base = resolve(root);
  const candidate = resolve(base, normalizedTarget);
  const rel = relative(base, candidate).replaceAll("\\", "/");
  if (rel === "" || rel === ".." || rel.startsWith("../") || isAbsolute(rel)) {
    throw new Error(`Path escapes project root: ${target}`);
  }
  let stat;
  try {
    stat = await lstat(candidate);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") throw new Error(`File not found: ${rel}`);
    throw error;
  }
  if (stat.isSymbolicLink()) throw new Error(`Symlink is not readable: ${rel}`);
  if (!stat.isFile()) throw new Error(`Not a file: ${rel}`);
  const resolvedCandidate = await realpath(candidate);
  const resolvedBase = await realpath(base);
  const resolvedRel = relative(resolvedBase, resolvedCandidate).replaceAll("\\", "/");
  if (resolvedRel === ".." || resolvedRel.startsWith("../") || isAbsolute(resolvedRel)) {
    throw new Error(`Resolved path escapes project root: ${target}`);
  }
  return { absolute: candidate, relativePath: rel };
}

async function defaultRunner(command: string, args: readonly string[], options: { cwd: string; timeoutMs: number }): Promise<CommandResult> {
  try {
    const result = await execFileAsync(command, [...args], {
      cwd: options.cwd,
      timeout: options.timeoutMs,
      encoding: "utf8",
      maxBuffer: 8 * 1024 * 1024,
      windowsHide: true,
    });
    return { stdout: result.stdout ?? "", stderr: result.stderr ?? "", exitCode: 0 };
  } catch (error) {
    const err = error as NodeJS.ErrnoException & { stdout?: string; stderr?: string; code?: number | string };
    const exitCode = typeof err.code === "number" ? err.code : 127;
    return { stdout: err.stdout ?? "", stderr: err.stderr || err.message, exitCode };
  }
}

function clip(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars)}\n[truncated ${text.length - maxChars} chars]`;
}

function formatProfile(relativePath: string, payload: { rows: number; columns: { name: string; missing: number }[] }): string {
  const shown = payload.columns.slice(0, PROFILE_COLUMN_CAP);
  const lines = [
    `Profile of ${relativePath}`,
    `Rows: ${payload.rows}`,
    `Columns: ${payload.columns.length}${payload.columns.length > shown.length ? ` (showing ${shown.length})` : ""}`,
    "Missing means a blank cell, NA, NaN, or NULL.",
    `Script: ${PROFILE_SCRIPT}`,
    ...shown.map((column) => `- ${column.name}: missing ${column.missing}/${payload.rows}`),
  ];
  return lines.join("\n");
}

function queryTerms(query: string | undefined): string[] {
  return (query ?? "").split(/[,\s]+/).map((term) => term.trim().toLowerCase()).filter(Boolean);
}

function formatLookup(
  relativePath: string,
  terms: string[],
  payload: { sheets: { name: string; rows: number; header: string }[]; matches: { sheet: string; row: number; text: string }[]; total: number },
): string {
  if (terms.length === 0) {
    return [
      `Sheets in ${relativePath}`,
      `Script: ${LOOKUP_SCRIPT}`,
      ...payload.sheets.map((sheet) => `- ${sheet.name}: ${sheet.rows} rows; first row: ${sheet.header}`),
      "Pass query with variable names or keywords to get only the matching rows.",
    ].join("\n");
  }
  return [
    `Codebook rows in ${relativePath} matching: ${terms.join(", ")}`,
    `Matches: ${payload.total}${payload.total > payload.matches.length ? ` (showing ${payload.matches.length})` : ""}`,
    `Script: ${LOOKUP_SCRIPT}`,
    ...payload.matches.map((match) => `- [${match.sheet}] row ${match.row}: ${match.text}`),
  ].join("\n");
}

export async function profileDataset(
  root: string,
  dataPath: string,
  options: { query?: string; run?: CommandRunner; python?: { command: string; prefixArgs?: readonly string[] } } = {},
): Promise<string> {
  const file = await resolveProjectRead(root, dataPath);
  const terms = queryTerms(options.query);
  if (/\.(xlsx|xlsm)$/i.test(file.relativePath)) {
    const scriptPath = resolve(root, LOOKUP_SCRIPT);
    await mkdir(resolve(root, "analysis/scripts"), { recursive: true });
    await writeFile(scriptPath, LOOKUP_SOURCE, "utf8");
    const python = options.python ?? await requirePython();
    const run = options.run ?? defaultRunner;
    const result = await run(python.command, [...(python.prefixArgs ?? []), scriptPath, file.absolute, terms.join(","), String(LOOKUP_MATCH_CAP)], { cwd: root, timeoutMs: 60_000 });
    if (result.exitCode !== 0) {
      throw new Error(clip(result.stderr || result.stdout || "codebook lookup failed", 2_000));
    }
    const payload = JSON.parse(result.stdout) as Parameters<typeof formatLookup>[2];
    if (!Array.isArray(payload.sheets) || !Array.isArray(payload.matches)) throw new Error("Codebook lookup returned an unreadable summary.");
    return formatLookup(file.relativePath, terms, payload);
  }
  if (!/\.(csv|tsv)$/i.test(file.relativePath)) {
    throw new Error("psyclaw_data_profile reads CSV or TSV data files and xlsx codebooks.");
  }
  const scriptPath = resolve(root, PROFILE_SCRIPT);
  await mkdir(resolve(root, "analysis/scripts"), { recursive: true });
  await writeFile(scriptPath, PROFILE_SOURCE, "utf8");
  const python = options.python ?? await requirePython();
  const run = options.run ?? defaultRunner;
  const result = await run(python.command, [...(python.prefixArgs ?? []), scriptPath, file.absolute], { cwd: root, timeoutMs: 60_000 });
  if (result.exitCode !== 0) {
    throw new Error(clip(result.stderr || result.stdout || "profile script failed", 2_000));
  }
  const payload = JSON.parse(result.stdout) as { rows: number; columns: { name: string; missing: number }[] };
  if (!Number.isInteger(payload.rows) || !Array.isArray(payload.columns)) throw new Error("Profile script returned an unreadable summary.");
  if (terms.length > 0) {
    payload.columns = payload.columns.filter((column) => terms.some((term) => column.name.toLowerCase().includes(term)));
  }
  return formatProfile(file.relativePath, payload);
}

async function scriptDigest(root: string, entryRelative: string): Promise<string> {
  const files = new Set<string>([entryRelative]);
  const underScripts = entryRelative.startsWith("analysis/scripts/") || entryRelative.startsWith("analysis/configs/");
  if (underScripts) {
    for (const dir of ["analysis/scripts", "analysis/configs"]) {
      await collectScripts(resolve(root, dir), root, files);
    }
  }
  const parts: string[] = [];
  for (const rel of [...files].sort()) {
    parts.push(`${rel}\0${await sha256File(resolve(root, rel))}`);
  }
  return createHash("sha256").update(parts.join("\n"), "utf8").digest("hex");
}

async function collectScripts(dir: string, root: string, files: Set<string>): Promise<void> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  for (const entry of entries) {
    if (entry.isSymbolicLink() || entry.name === "node_modules") continue;
    const absolute = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      await collectScripts(absolute, root, files);
      continue;
    }
    if (/\.(r|py)$/i.test(entry.name)) files.add(relative(root, absolute).replaceAll("\\", "/"));
  }
}

async function findEntrypoint(root: string, requested?: string): Promise<string> {
  if (requested?.trim()) {
    const file = await resolveProjectRead(root, requested.trim());
    if (!/\.(r|py)$/i.test(file.relativePath)) throw new Error("Analysis entrypoint must be an R or Python script.");
    return file.relativePath;
  }
  for (const candidate of ENTRY_CANDIDATES) {
    try {
      const stat = await lstat(resolve(root, candidate));
      if (stat.isFile() && !stat.isSymbolicLink()) return candidate;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }
  throw new Error(`No analysis entrypoint found. Looked for ${ENTRY_CANDIDATES.join(", ")}.`);
}

function commandFor(entrypoint: string): { command: string; args: string[] } | undefined {
  if (/\.r$/i.test(entrypoint)) return { command: "Rscript", args: [entrypoint] };
  return undefined;
}

async function readReceipt(root: string): Promise<RunReceipt | undefined> {
  try {
    const parsed = JSON.parse(await readFile(resolve(root, RUN_RECEIPT), "utf8")) as RunReceipt;
    if (parsed.schemaVersion !== RECEIPT_VERSION || typeof parsed.scriptDigest !== "string") return undefined;
    return parsed;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    return undefined;
  }
}

export async function runAnalysisEntrypoint(
  root: string,
  options: { entrypoint?: string; force?: boolean; timeoutMs?: number; run?: CommandRunner } = {},
): Promise<string> {
  const entrypoint = await findEntrypoint(root, options.entrypoint);
  const digest = await scriptDigest(root, entrypoint);
  const previous = await readReceipt(root);
  if (!options.force && previous?.entrypoint === entrypoint && previous.scriptDigest === digest && previous.exitCode === 0) {
    return [
      `Cached run of ${entrypoint}`,
      "Script tree is unchanged since the last successful run, so it was not executed again.",
      `Log: ${previous.log}`,
      "Use psyclaw_read_results for a saved table.",
      previous.tail,
    ].join("\n");
  }
  const timeoutMs = options.timeoutMs ?? DEFAULT_RUN_TIMEOUT_MS;
  const runner = options.run ?? defaultRunner;
  let result: CommandResult;
  if (/\.py$/i.test(entrypoint)) {
    const python = await requirePython();
    result = await runner(python.command, [...python.prefixArgs, entrypoint], { cwd: root, timeoutMs });
  } else {
    const spec = commandFor(entrypoint);
    if (!spec) throw new Error("Analysis entrypoint must be an R or Python script.");
    result = await runner(spec.command, spec.args, { cwd: root, timeoutMs });
  }
  const combined = [result.stdout, result.stderr].filter(Boolean).join("\n");
  const tail = combined.length > RUN_TAIL_CHARS ? combined.slice(combined.length - RUN_TAIL_CHARS) : combined;
  await mkdir(resolve(root, "analysis/results"), { recursive: true });
  await writeFile(resolve(root, RUN_LOG), combined, "utf8");
  const receipt: RunReceipt = {
    schemaVersion: RECEIPT_VERSION,
    entrypoint,
    scriptDigest: digest,
    exitCode: result.exitCode,
    log: RUN_LOG,
    tail,
  };
  await writeFile(resolve(root, RUN_RECEIPT), JSON.stringify(receipt, null, 2), "utf8");
  const header = result.exitCode === 0
    ? `Ran ${entrypoint}`
    : `Ran ${entrypoint} (exit ${result.exitCode})`;
  return [header, "Values below are script output, not numbers computed by PsyClaw.", `Log: ${RUN_LOG}`, tail || "(no output)"].join("\n");
}

function resultScore(relativePath: string): number {
  const name = relativePath.toLowerCase();
  let score = 0;
  if (name.includes("confirmatory")) score += 5;
  if (name.includes("model") || name.includes("estimate") || name.includes("coef")) score += 3;
  if (name.endsWith(".csv") || name.endsWith(".tsv") || name.endsWith(".md")) score += 1;
  return score;
}

async function listResultFiles(root: string): Promise<string[]> {
  const found: string[] = [];
  for (const dir of RESULT_ROOTS) {
    await collectResultFiles(resolve(root, dir), root, found);
  }
  return found.filter((rel) => resultScore(rel) > 1 && !rel.endsWith("psyclaw-run-receipt.json") && !rel.endsWith("psyclaw-run.log"));
}

async function collectResultFiles(dir: string, root: string, found: string[]): Promise<void> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  for (const entry of entries) {
    if (entry.isSymbolicLink()) continue;
    const absolute = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      await collectResultFiles(absolute, root, found);
      continue;
    }
    if (/\.(csv|tsv|md)$/i.test(entry.name)) found.push(relative(root, absolute).replaceAll("\\", "/"));
  }
}

function previewTable(body: string): string {
  const lines = body.split(/\r?\n/).filter((line) => line.length > 0).slice(0, RESULT_LINE_CAP);
  return clip(lines.join("\n"), RESULT_CHAR_CAP);
}

export async function readAnalysisResults(root: string, requested?: string): Promise<string> {
  const files = requested?.trim()
    ? [ (await resolveProjectRead(root, requested.trim())).relativePath ]
    : (await listResultFiles(root)).sort((a, b) => resultScore(b) - resultScore(a) || a.localeCompare(b)).slice(0, RESULT_FILE_CAP);
  if (files.length === 0) {
    return "No saved confirmatory table found under analysis/results, results/tables, or results. Run the analysis script before reading results.";
  }
  const blocks = [`Saved tables (${files.length}). These rows are copied from files, not recomputed.`];
  for (const rel of files) {
    const body = await readFile(resolve(root, rel), "utf8");
    blocks.push(`## ${rel}`, previewTable(body));
  }
  return blocks.join("\n");
}

export function registerAnalysisRuntimeTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "psyclaw_data_profile",
    label: "Profile dataset",
    description: "Profile one CSV or TSV data file (row count, column names, missing counts), or look up an xlsx codebook. With query, a data file shows only the matching columns and a codebook returns only the matching rows with sheet and row number. Writes the script it runs under analysis/scripts/ and runs it with the system Python. Use this instead of python -c, head, grep, or dumping a codebook. Does not fit models.",
    parameters: Type.Object({
      path: Type.String({ description: "Project-relative CSV/TSV data file or xlsx codebook, for example data/OSF_Data_T1T2.csv or codebooks/W1.xlsx" }),
      query: Type.Optional(Type.String({ description: "Variable names or keywords, separated by commas or spaces, for example: NCE_T2, subgroup, cortisol" })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        return toolText(await profileDataset(ctx.cwd, params.path, params.query ? { query: params.query } : {}));
      } catch (error) {
        return toolText(error instanceof Error ? error.message : String(error), true);
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_run_analysis",
    label: "Run analysis entrypoint",
    description: "Run one project R or Python script, an exploration script or the full pipeline, and return the tail of its output; the whole output is saved to analysis/results/psyclaw-run.log. Defaults to analysis/scripts/run_all.R, results/analysis.R, or results/analysis.py when present. If the script tree is unchanged and the last run of that script succeeded, returns the saved tail without executing again. Pass force=true only after the script changed or the last run failed. Use this instead of running scripts through bash.",
    parameters: Type.Object({
      entrypoint: Type.Optional(Type.String({ description: "Project-relative R or Python script, for example analysis/scripts/explore_codebook.py. Omit to use the default entrypoint." })),
      force: Type.Optional(Type.Boolean({ description: "Run again even when the script tree is unchanged." })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        return toolText(await runAnalysisEntrypoint(ctx.cwd, {
          ...(params.entrypoint ? { entrypoint: params.entrypoint } : {}),
          ...(params.force ? { force: true } : {}),
        }));
      } catch (error) {
        return toolText(error instanceof Error ? error.message : String(error), true);
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_read_results",
    label: "Read saved results",
    description: "Read a saved confirmatory table from analysis/results, results/tables, or results. Returns a bounded preview of the file on disk. Use this instead of tail, sed, or grep on a log. Does not compute statistics.",
    parameters: Type.Object({
      path: Type.Optional(Type.String({ description: "Project-relative table path. Omit to preview the best-matching saved tables." })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        return toolText(await readAnalysisResults(ctx.cwd, params.path));
      } catch (error) {
        return toolText(error instanceof Error ? error.message : String(error), true);
      }
    },
  });

  pi.registerTool({
    name: "psyclaw_recall_output",
    label: "Recall tool output",
    description: "Read a line range from a saved tool-output log under .psyclaw/cache/tool-output. Use the path printed at the tail of a clipped bash or read result. Returns at most 80 lines and 1600 characters, so the slice can stay in context. Does not compute statistics.",
    parameters: Type.Object({
      path: Type.String({ description: "Project-relative log path from the output-log footer." }),
      startLine: Type.Optional(Type.Number({ description: "First line to return, counting from 1." })),
      lineCount: Type.Optional(Type.Number({ description: "How many lines to return, at most 80." })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      try {
        return toolText(await recallToolOutput(ctx.cwd, params.path, params.startLine, params.lineCount));
      } catch (error) {
        return toolText(error instanceof Error ? error.message : String(error), true);
      }
    },
  });
}
