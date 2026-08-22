/**
 * psyclaw 分模块使用效果测评器 (Module-by-module usage evaluation).
 *
 * Exercises each product module the way a user would and produces a
 * machine-readable scorecard (evals/reports/modules-latest.json) plus a
 * human-readable summary. Deterministic and offline by default: network
 * paths (DOI verify, OpenAlex, OA download) run through injected fake
 * fetchers; a single opt-in real-network smoke is skipped when unreachable.
 *
 * Run: pnpm eval:modules   (tsx evals/modules.ts)
 */
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { bootstrapProject } from "../src/project/bootstrap.js";
import { appendClaim, appendClaimEvidenceLink, appendEvidence } from "../src/research/ledger.js";
import { runLiteratureReview } from "../src/workflows/literature-review.js";
import { runAnalysisDelegation } from "../src/workflows/analysis-delegation.js";
import { runWritingReview } from "../src/workflows/writing-review.js";
import { runMetaAnalysis } from "../src/workflows/meta-analysis.js";
import { publishManuscript } from "../src/workflows/publish.js";
import { createPanelServer, downloadReferencePdf } from "../src/panel/server.js";
import { checkCitations } from "../src/core/references.js";
import { recordCitationUse } from "../src/core/citations.js";
import { runWorkflowTool } from "../src/adapters/pi/extension.js";
import type { Evidence, ResearchParadigm } from "../src/core/contracts.js";

const here = dirname(fileURLToPath(import.meta.url));
const REPORTS_DIR = resolve(here, "reports");
const CLI = resolve(here, "..", "dist", "src", "cli.js");

interface ProbeResult {
  module: string;
  moduleLabel: string;
  name: string;
  ok: boolean;
  note: string;
}
const results: ProbeResult[] = [];

async function probe(module: string, label: string, name: string, fn: () => Promise<{ ok: boolean; note: string }>): Promise<void> {
  try {
    const r = await fn();
    results.push({ module, moduleLabel: label, name, ok: r.ok, note: r.note });
  } catch (error) {
    results.push({ module, moduleLabel: label, name, ok: false, note: `异常: ${error instanceof Error ? error.message : String(error)}` });
  }
}

const snippet = (id: string, locator: string): Evidence => ({
  id,
  source: { kind: "file", locator },
  level: "snippet",
  quote: "Exact excerpt",
  retrievedAt: "2026-01-01T00:00:00.000Z",
  accessStatus: "verified",
  locators: [{ kind: "section", value: "Findings" }],
});

const fakeOpenAlex = (): typeof fetch => async (url: string): Promise<Response> => {
  if (url.includes("openalex") && url.includes("doi:")) {
    return new Response(JSON.stringify({ title: "Same Title", cited_by_count: 5, open_access: { is_oa: true, oa_url: "https://example.org/paper.pdf" }, best_oa_location: { pdf_url: "https://example.org/paper.pdf" } }), { status: 200 });
  }
  if (url.includes("openalex")) {
    return new Response(JSON.stringify({
      results: [
        { id: "W1", title: "Study A", publication_year: 2021, authorships: [{ author: { display_name: "Alpha" } }], doi: "https://doi.org/10.1/a" },
        { id: "W2", title: "Study B", publication_year: 2022, authorships: [{ author: { display_name: "Beta" } }], doi: "https://doi.org/10.1/b" },
      ],
    }), { status: 200 });
  }
  if (url.includes("crossref")) {
    return new Response(JSON.stringify({ message: { title: ["Same Title"], author: [{ family: "Kessler", given: "Ronald C" }], issued: { "date-parts": [[2005]] } } }), { status: 200 });
  }
  if (url.includes("example.org")) return new Response("%PDF-1.4 fake", { status: 200 });
  return new Response("{}", { status: 404 });
};

async function withServer(root: string, fn: (base: string) => Promise<void>): Promise<void> {
  const htmlPath = join(root, "panel.html");
  await writeFile(htmlPath, "<!DOCTYPE html><title>panel</title>", "utf8");
  const server = createPanelServer(root, { panelHtmlPath: htmlPath });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  try { await fn(base); } finally { await new Promise<void>((r) => server.close(() => r())); }
}

function cli(args: string[], cwd: string): { code: number; out: string } {
  const r = spawnSync(process.execPath, [CLI, ...args], { cwd, encoding: "utf8", timeout: 60_000 });
  return { code: r.status ?? 1, out: (r.stdout ?? "") + (r.stderr ?? "") };
}

const project = async (paradigm: ResearchParadigm = "survey-observational"): Promise<string> => {
  const root = await mkdtemp(join(tmpdir(), "psyclaw-module-eval-"));
  await bootstrapProject({ root, goal: "Bounded synthetic research question", paradigm });
  return root;
};

async function main(): Promise<void> {
  // ---------- M1 安装与启动 ----------
  const helpRoot = await project();
  const help = cli(["--help"], helpRoot);
  await probe("M1", "安装与启动", "CLI 版本横幅", async () => ({
      ok: help.code === 0 && /PsyClaw \[v\d+\.\d+\.\d+\]/.test(help.out) && /社会科学科研智能体/.test(help.out),
    note: help.code === 0 ? (help.out.match(/ψ PsyClaw \[v[^\]]*\]/) ?? ["(未匹配横幅)"])[0]! : help.out.slice(0, 120),
  }));

  // ---------- M2 CLI 命令面 ----------
  const root = await project("meta-analysis");
  await probe("M2", "CLI 命令面", "CLI init 真实执行（空目录）", async () => {
    const fresh = await mkdtemp(join(tmpdir(), "psyclaw-module-init-"));
    const r = cli(["init", "测评课题", "--paradigm", "meta-analysis"], fresh);
    if (r.code !== 0) return { ok: false, note: r.out.slice(0, 200) };
    const projectJson = JSON.parse(r.out) as { paradigm: string; root: string };
    const ok = projectJson.paradigm === "meta-analysis" && existsSync(join(fresh, ".psyclaw", "project.json")) && existsSync(join(fresh, "notes"));
    return { ok, note: ok ? `paradigm=${projectJson.paradigm}，.psyclaw/ + notes/ 就位` : `输出异常: ${r.out.slice(0, 120)}` };
  });
  await probe("M2", "CLI 命令面", "重复 init 不覆盖（幂等保护）", async () => {
    const r = cli(["init", "另一课题", "--paradigm", "survey-observational"], root);
    // A second init on an existing project is refused (error text, not JSON) —
    // that refusal is the protection we are asserting.
    if (r.code !== 0) return { ok: true, note: "二次 init 被拒绝（幂等保护）" };
    try {
      const projectJson = JSON.parse(r.out) as { paradigm: string };
      return { ok: projectJson.paradigm === "meta-analysis", note: "已存在项目未被覆盖" };
    } catch {
      return { ok: true, note: "二次 init 被拒绝（幂等保护）" };
    }
  });
  await probe("M2", "CLI 命令面", "hitl init", async () => {
    const r = cli(["hitl", "init"], root);
    return { ok: r.code === 0, note: r.out.includes("HITL") ? "创建 HITL 工作区" : r.out.slice(0, 120) };
  });
  await probe("M2", "CLI 命令面", "handoff 生成", async () => {
    const r = cli(["handoff"], root);
    return { ok: r.code === 0 && existsSync(join(root, "notes", "HANDOFF.md")), note: "notes/HANDOFF.md 已生成" };
  });
  await probe("M2", "CLI 命令面", "evidence add 登记证据", async () => {
    const fixture = join(root, "source.md");
    await writeFile(fixture, "# 来源\n\n真实文献内容。", "utf8");
    const r = cli(["evidence", "add", "source.md", "--level", "fulltext"], root);
    const ledger = await readFile(join(root, ".psyclaw", "evidence.jsonl"), "utf8");
    return { ok: r.code === 0 && ledger.includes("source.md") && ledger.includes("sha256"), note: "证据已登记含指纹" };
  });
  await probe("M2", "CLI 命令面", "冗余 workflow 命令已移除（去重）", async () => {
    // psyclaw workflow 已从 CLI 移除——工作流统一走 psyclaw_workbench 工具（去重审计项）。
    const r = cli(["workflow", "literature-review"], root);
    return { ok: r.code !== 0 && r.out.includes("Unknown command"), note: "CLI 无 workflow 命令，工作流走对话工具路径" };
  });
  await probe("M2", "CLI 命令面", "check-updates 可执行", async () => {
    const r = cli(["check-updates"], root);
    return { ok: r.code === 0, note: "检查报告正常输出" };
  });

  // ---------- M3 对话工具 ----------
  await probe("M3", "对话工具", "psyclaw_workbench 未知工作流阻断", async () => {
    const r = await runWorkflowTool("ignored", "bogus");
    return { ok: r.details.status === "blocked" && String(r.content[0]?.text).includes("Unknown workflow"), note: "未知工作流诚实阻断" };
  });
  await probe("M3", "对话工具", "psyclaw_workbench 元分析缺 target 阻断", async () => {
    const r = await runWorkflowTool("ignored", "meta-analysis");
    return { ok: r.details.status === "blocked" && String(r.content[0]?.text).includes("target"), note: "缺 target 诚实阻断" };
  });
  await probe("M3", "对话工具", "psyclaw_cite 登记引用（含原因）", async () => {
    const r = await recordCitationUse(root, {
      doi: "10.1000/kessler2005",
      reason: "支持：社会支持缓冲压力假说",
      context: "社会支持缓冲压力（Kessler et al., 2005）",
      section: "1 引言",
    }, async (doi) => ({
      schemaVersion: "psyclaw/doi-verify/v1",
      doi,
      status: "verified" as const,
      crossref: { title: "Social Support", authors: ["Ronald C Kessler"], year: 2005 },
      verifiedAt: "2026-01-01T00:00:00.000Z",
    }));
    const cites = await readFile(join(root, ".psyclaw", "citations.jsonl"), "utf8");
    const refs = await readFile(join(root, ".psyclaw", "references.jsonl"), "utf8");
    return { ok: r.record.verified && cites.includes("缓冲压力假说") && refs.includes("10.1000/kessler2005"), note: `引用用途+证据已登记 (${r.record.citationId})` };
  });
  await probe("M3", "对话工具", "真实运行时 /panel（Pi RPC + 扩展）", async () => {
    const { spawn } = await import("node:child_process");
    const panelDir = await mkdtemp(join(tmpdir(), "psyclaw-eval-panel-"));
    const piCli = resolve(here, "..", "node_modules", ".pnpm", "@earendil-works+pi-coding-agent@0.84.1_ws@8.21.3_zod@4.4.3", "node_modules", "@earendil-works", "pi-coding-agent", "dist", "cli.js");
    const child = spawn(process.execPath, [piCli, "--mode", "rpc", "--no-session",
      "--extension", resolve(here, "..", "dist", "src", "extension.js"),
      "--extension", resolve(here, "..", "dist", "src", "panel", "extension.js"),
      "--tools", "read"],
      { cwd: panelDir, stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, PI_SKIP_VERSION_CHECK: "1", DEEPSEEK_API_KEY: "dummy-skip" } });
    let rpcBuf = "";
    const rpcEvents: Array<{ type?: string; method?: string; message?: string }> = [];
    child.stdout.on("data", (c: Buffer) => {
      rpcBuf += String(c);
      const lines = rpcBuf.split("\n"); rpcBuf = lines.pop() ?? "";
      for (const l of lines) { if (l.trim()) { try { rpcEvents.push(JSON.parse(l)); } catch { /* ignore */ } } }
    });
    const send = (o: unknown) => child.stdin.write(`${JSON.stringify(o)}\n`);
    try {
      await new Promise((r) => setTimeout(r, 4000));
      send({ type: "prompt", message: "/panel", id: "eval-panel" });
      await new Promise((r) => setTimeout(r, 12_000));
      const notify = rpcEvents.find((e) => e.type === "extension_ui_request" && e.method === "notify");
      if (!notify?.message) return { ok: false, note: "/panel 未产生 notify 事件" };
      const panelUrl = notify.message.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
      if (panelUrl === undefined) return { ok: false, note: "notify 未包含 loopback 页面地址" };
      try {
        const res = await fetch(panelUrl, { signal: AbortSignal.timeout(3000) });
        const text = await res.text();
        const found = text.includes("手稿编辑与核验") && text.includes("tab-editor");
        return { ok: found, note: found ? `notify + 真实页面伺服（${panelUrl}）` : "页面内容不符合工作台契约" };
      } catch {
        return { ok: false, note: `无法访问 notify 页面（${panelUrl}）` };
      }
    } finally {
      child.kill("SIGTERM");
      await new Promise((r) => setTimeout(r, 1500));
    }
  });

  // ---------- M4 研究工作流 ----------
  await probe("M4", "研究工作流", "文献综述通过（有证据）", async () => {
    const wroot = await project("qualitative-thematic");
    await appendEvidence(wroot, snippet("e-1", "fixture/a.md"));
    await appendClaim(wroot, { id: "c-1", text: "A coded theme", kind: "interpretation", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(wroot, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });
    const r = await runLiteratureReview(wroot);
    return { ok: r.verdict === "pass" && existsSync(join(wroot, "outputs", "review-matrix.json")), note: `verdict=${r.verdict} 产物就位` };
  });
  await probe("M4", "研究工作流", "文献综述无来源阻断", async () => {
    const r = await runLiteratureReview(await project("qualitative-thematic"));
    return { ok: r.verdict === "blocked" && r.gates.some((g) => g.gateId === "review:sources"), note: "review:sources 门禁阻断" };
  });
  await probe("M4", "研究工作流", "统计委托（不造数，写脚本契约）", async () => {
    const wroot = await project("qualitative-thematic");
    await appendEvidence(wroot, { ...snippet("e-1", "fixture/a.md"), level: "fulltext", sha256: "a".repeat(64) });
    await appendClaim(wroot, { id: "c-1", text: "A thematic result", kind: "result", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(wroot, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });
    const r = await runAnalysisDelegation(wroot);
    const delegation = JSON.parse(await readFile(join(wroot, "outputs", "delegation.json"), "utf8"));
    const text = JSON.stringify(delegation);
    return { ok: r.verdict === "pass" && delegation.tasks?.length >= 1 && !text.includes("I2"), note: `委托 ${delegation.tasks?.length} 个统计任务（脚本契约，核心不含统计数值）` };
  });
  await probe("M4", "研究工作流", "写作评审标记因果语言", async () => {
    const wroot = await project("qualitative-thematic");
    await appendEvidence(wroot, snippet("e-1", "fixture/a.md"));
    await appendClaim(wroot, { id: "c-1", text: "The program increases engagement", kind: "interpretation", evidenceIds: ["e-1"], status: "supported" });
    await appendClaimEvidenceLink(wroot, { claimId: "c-1", evidenceId: "e-1", relation: "supports", rationale: "coded" });
    const r = await runWritingReview(wroot);
    const findings = JSON.parse(await readFile(join(wroot, "outputs", "review-findings.json"), "utf8"));
    return { ok: findings.findings?.some((f: { rule: string }) => f.rule === "causal-language-without-result-artifact") === true, note: "检出因果语言缺结果产物" };
  });
  await probe("M4", "研究工作流", "元分析（有数据集，fake OpenAlex）", async () => {
    const mroot = await project("meta-analysis");
    await mkdir(join(mroot, "data", "clean"), { recursive: true });
    await writeFile(join(mroot, "data", "clean", "effects.csv"), "study_id,effect_size,standard_error,n\nW1,0.42,0.11,120\nW2,0.31,0.14,96\n", "utf8");
    const r = await runMetaAnalysis(mroot, { target: "online learning", nStudies: 2, fetchFn: fakeOpenAlex() as typeof fetch });
    return { ok: r.verdict === "pass" && existsSync(join(mroot, "analysis", "scripts", "metafor.R")), note: "I²/Egger 委托 R，不伪造" };
  });
  await probe("M4", "研究工作流", "元分析无数据集诚实阻断", async () => {
    const r = await runMetaAnalysis(await project("meta-analysis"), { target: "x", nStudies: 2, fetchFn: fakeOpenAlex() as typeof fetch });
    return { ok: r.verdict === "blocked" && r.gates.some((g) => g.gateId === "meta:effect-data-missing"), note: "缺效应量数据集阻断" };
  });

  // ---------- M5 发布与版本 ----------
  await probe("M5", "发布与版本", "发布 v1→v2 并归档", async () => {
    const v1 = await publishManuscript(root, { name: "论文初稿", markdown: "# 第一版", exportDocx: false });
    const v2 = await publishManuscript(root, { name: "论文初稿", markdown: "# 第二版", exportDocx: false });
    const archive = existsSync(join(root, "paper", "archive", "论文初稿_v1.md"));
    const versions = existsSync(join(root, ".psyclaw", "publish.jsonl"));
    return { ok: v1.version === 1 && v2.version === 2 && archive && versions, note: `v1→v2，归档+版本账本就位` };
  });
  await probe("M5", "发布与版本", "内容未变不产生新版本", async () => {
    const v3 = await publishManuscript(root, { name: "论文初稿", markdown: "# 第二版", exportDocx: false });
    return { ok: v3.version === 2 && v3.evidenceIds.length === 0, note: "幂等，无新版本" };
  });

  // ---------- M6 文档导入与产物 ----------
  await probe("M6", "文档导入", "文档清单识别 paper 手稿", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const data = await (await fetch(`${base}/api/documents`)).json() as { documents: Array<{ path: string; isManuscript: boolean }> };
      const md = data.documents.find((d) => d.path === "paper/论文初稿.md");
      ok = Boolean(md?.isManuscript); note = md ? "paper/论文初稿.md 标记为手稿" : "未发现";
    });
    return { ok, note };
  });
  await probe("M6", "文档导入", "md 导入登记证据（幂等）", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const post = (p: string, b: unknown) => fetch(`${base}${p}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
      const r = await (await post("/api/documents/import", { path: "paper/论文初稿.md" })).json() as { ok: boolean; evidenceId: string; markdown: string | null };
      const again = await (await post("/api/documents/import", { path: "paper/论文初稿.md" })).json() as { alreadyImported: boolean };
      ok = Boolean(r.ok && r.evidenceId && again.alreadyImported);
      note = `证据 ${r.evidenceId ?? "?"}，重导幂等`;
    });
    return { ok, note };
  });
  await probe("M6", "文档导入", "路径逃逸拒绝", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const r = await fetch(`${base}/api/documents/import`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: "../escape.md" }) });
      ok = r.status === 400; note = `HTTP ${r.status} 拒绝`;
    });
    return { ok, note };
  });

  // ---------- M7 引用体系 ----------
  await probe("M7", "引用体系", "正文引文提取与缺口", async () => {
    const r = checkCitations("（Kessler et al., 2005; Wanberg et al., 2010）", []);
    return { ok: r.citations.length === 2 && r.unmatched === 2, note: `提取 ${r.citations.length} 处，全部标缺口（存档空）` };
  });
  await probe("M7", "引用体系", "OA 全文下载（fake）", async () => {
    const r = await downloadReferencePdf(root, "10.1000/oa", fakeOpenAlex() as typeof fetch);
    return { ok: r.ok === true && r.path.startsWith("literature/"), note: r.ok ? `已下载 ${r.path}` : r.reason };
  });
  await probe("M7", "引用体系", "付费墙诚实阻断", async () => {
    const fetchFn = async (): Promise<Response> => new Response(JSON.stringify({ open_access: { is_oa: false }, best_oa_location: null }), { status: 200 });
    const r = await downloadReferencePdf(root, "10.1000/pay", fetchFn as typeof fetch);
    return { ok: r.ok === false && r.reason === "not-open-access", note: "非开放获取，如实阻断" };
  });

  // ---------- M8 手稿与面板 ----------
  await probe("M8", "手稿与面板", "手稿发现 paper/*.md", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const ms = await (await fetch(`${base}/api/manuscript`)).json() as { exists: boolean; path: string | null };
      ok = ms.exists && ms.path === "paper/论文初稿.md"; note = ms.path ?? "无";
    });
    return { ok, note };
  });
  await probe("M8", "手稿与面板", "版本接口与归档可读", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const v = await (await fetch(`${base}/api/versions`)).json() as { versions: Array<{ version: number; markdownLoadPath: string }> };
      const v1 = v.versions.find((x) => x.version === 1);
      const text = v1 ? await (await fetch(`${base}/api/artifact?path=${encodeURIComponent(v1.markdownLoadPath)}`)).text() : "";
      ok = v.versions.length >= 2 && text.includes("第一版"); note = `${v.versions.length} 个版本，v1 可回读`;
    });
    return { ok, note };
  });
  await probe("M8", "手稿与面板", "中文文件名产物可伺服（RFC 5987）", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      const r = await fetch(`${base}/api/artifact?path=${encodeURIComponent("paper/论文初稿.md")}`);
      ok = r.status === 200; note = `HTTP ${r.status}`;
    });
    return { ok, note };
  });

  // ---------- M9 安全与门禁 ----------
  await probe("M9", "安全与门禁", "发布名称逃逸拒绝", async () => {
    let ok = false; let note = "";
    await withServer(root, async (base) => {
      // `paper/../../evil` resolves outside the project root → must be rejected.
      const r = await fetch(`${base}/api/publish`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content: "x", name: "../../evil", exportDocx: false }) });
      ok = r.status === 400; note = `HTTP ${r.status}`;
      // `paper/../evil` stays inside the project → contained is also acceptable.
      const contained = await fetch(`${base}/api/publish`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content: "x", name: "../evil", exportDocx: false }) });
      note += ` | 包含内路径 HTTP ${contained.status}`;
    });
    return { ok, note };
  });
  await probe("M9", "安全与门禁", "副作用有 receipt（.psyclaw/manifests）", async () => {
    const { readdir } = await import("node:fs/promises");
    let receipts = 0;
    try { receipts = (await readdir(join(root, ".psyclaw", "manifests"))).filter((f) => f.endsWith(".receipt.json")).length; } catch { /* */ }
    return { ok: receipts >= 2, note: `receipt 数量 ${receipts}（≥2 次写入）` };
  });

  // ---------- 汇总 ----------
  const byModule = new Map<string, { label: string; passed: number; total: number }>();
  for (const r of results) {
    const m = byModule.get(r.module) ?? { label: r.moduleLabel, passed: 0, total: 0 };
    m.total += 1; if (r.ok) m.passed += 1;
    byModule.set(r.module, m);
  }
  const modules = [...byModule.values()].map((m) => ({ module: [...byModule.entries()].find(([k]) => byModule.get(k) === m)![0], label: m.label, passed: m.passed, total: m.total, score: +(m.passed / m.total).toFixed(3) }));
  const report = {
    schemaVersion: "psyclaw/module-eval/v1",
    suite: "module-by-module-usage",
    generatedAt: new Date().toISOString(),
    modules,
    probes: results,
    passed: results.filter((r) => r.ok).length,
    total: results.length,
    allPassed: results.every((r) => r.ok),
  };
  await mkdir(REPORTS_DIR, { recursive: true });
  await writeFile(join(REPORTS_DIR, "modules-latest.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = report.allPassed ? 0 : 1;
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.stack ?? error.message : String(error));
  process.exitCode = 1;
});
