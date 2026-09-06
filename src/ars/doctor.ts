import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { ARS_REPOSITORY_URL, ARS_UPSTREAM_COMMIT, ARS_UPSTREAM_REF } from "./profile.js";

const execFileAsync = promisify(execFile);

async function probe(command: string, args: string[]): Promise<string | undefined> {
  try {
    const result = await execFileAsync(command, args, { timeout: 3000, encoding: "utf8" });
    const line = (result.stdout || result.stderr).trim().split("\n")[0];
    return line || "available";
  } catch {
    return undefined;
  }
}

export interface ArsDoctorInput {
  /** Absolute path to vendored ARS checkout inside the psyclaw package. */
  repositoryRoot: string;
  /** Active tool names from the current Pi session (optional). */
  activeTools?: readonly string[];
  /** Registered slash command names without leading slash (optional). */
  commands?: readonly string[];
  /** Whether a controlled /run is active in this project. */
  controlledRunActive?: boolean;
}

/**
 * PsyClaw-aware ARS capability report. Prefer this over upstream `/ars-pi-doctor`
 * so orchestration / hooks reflect real PsyClaw surfaces — and never inject the
 * slash text as a model prompt via sendUserMessage.
 */
export async function buildArsDoctorReport(input: ArsDoctorInput): Promise<string> {
  const tools = new Set((input.activeTools ?? []).map((name) => name.toLowerCase()));
  const commands = new Set((input.commands ?? []).map((name) => name.toLowerCase()));
  const hasMultiAgentTool = [...tools].some((name) =>
    name.includes("ars_multi_agent") || name.includes("multi_agent") || name.includes("multi-agent"));
  const hasAgentsCommand = commands.has("agents") || commands.has("create-subagent");
  const hasAnalysisHooks = true; // PsyClaw ships declarative analysis hooks + /create-hook
  const hasToolCallGate = input.controlledRunActive === true;

  const python = await probe("python3", ["--version"]);
  const pyyaml = await probe("python3", ["-c", "import yaml; print(f'PyYAML {yaml.__version__}')"]);
  const pandoc = await probe("pandoc", ["--version"]);

  const orchestration = hasMultiAgentTool || hasAgentsCommand
    ? [
        hasMultiAgentTool
          ? "psyclaw_ars_multi_agent ✓（Stage 3 五席进程隔离 / Stage 3′ 三门串行）"
          : undefined,
        hasAgentsCommand
          ? "/agents ✓（项目 Subagent，独立 Pi RPC worker）"
          : undefined,
      ].filter(Boolean).join("；")
    : "未发现 PsyClaw 编排入口（异常：应随包提供 psyclaw_ars_multi_agent 与 /agents）";

  const hooks = [
    "PsyClaw analysis hooks ✓（/create-hook、.psyclaw/analysis-hooks.json；/run 分析路径强制门禁）",
    hasToolCallGate
      ? "受控 /run tool_call 审批 ✓（高后果写入/外发需确认）"
      : "受控 /run tool_call 审批：当前未启用 /run（普通对话不拦截）",
    "Claude Code PreToolUse：Pi 不加载 Claude hooks.json；写入范围以 PsyClaw 门禁与提示约束为准，不冒充 Claude hook",
  ].join("\n   ");

  const lines = [
    "ARS Pi doctor（PsyClaw）",
    "──────────────────────────────────────────────────────────────",
    `Repository:    ${input.repositoryRoot}`,
    `               （上游 ${ARS_REPOSITORY_URL} @ ${ARS_UPSTREAM_REF} / ${ARS_UPSTREAM_COMMIT.slice(0, 12)}）`,
    `Python:        ${python ? `${python} ✓` : "未安装"}`,
    `PyYAML:        ${pyyaml ? `${pyyaml} ✓` : "未安装"}`,
    `Pandoc:        ${pandoc ? `${pandoc} ✓` : "未安装（DOCX/Markdown 转换可能受限）"}`,
    "PDF 引擎:      不预检 Tectonic；仅在你明确要求导出 PDF 时再按需安装",
    "──────────────────────────────────────────────────────────────",
    `编排能力:      ${orchestration}`,
    "               → 多智能体评审应调用 psyclaw_ars_multi_agent，禁止在主会话里假装分席",
    `门禁 / Hooks:`,
    `   ${hooks}`,
    "──────────────────────────────────────────────────────────────",
    "说明:          本报告由 PsyClaw 直接生成，不会把 /ars-pi-doctor 丢给模型执行。",
  ];
  return lines.join("\n");
}

export type PdfEngineKind = "tectonic" | "xelatex" | "pdflatex";

export interface EnsurePdfEngineResult {
  engine: PdfEngineKind | "none";
  status: "already-present" | "installed" | "missing" | "unsupported-platform";
  detail: string;
}

async function whichEngine(): Promise<PdfEngineKind | undefined> {
  if (await probe("tectonic", ["--version"])) return "tectonic";
  if (await probe("xelatex", ["--version"])) return "xelatex";
  if (await probe("pdflatex", ["--version"])) return "pdflatex";
  return undefined;
}

/**
 * Install a PDF engine only when the user explicitly needs PDF export.
 * Prefer tectonic via Homebrew on macOS; otherwise report a clear install hint.
 */
export async function ensurePdfEngineForExport(): Promise<EnsurePdfEngineResult> {
  const existing = await whichEngine();
  if (existing) {
    return { engine: existing, status: "already-present", detail: `${existing} 已可用` };
  }
  if (process.platform === "darwin") {
    const brew = await probe("brew", ["--version"]);
    if (brew) {
      try {
        await execFileAsync("brew", ["install", "tectonic"], { timeout: 600_000 });
        const after = await whichEngine();
        if (after) {
          return { engine: after, status: "installed", detail: `已通过 Homebrew 安装 ${after}` };
        }
      } catch (error) {
        return {
          engine: "none",
          status: "missing",
          detail: `Homebrew 安装 tectonic 失败：${error instanceof Error ? error.message : String(error)}`,
        };
      }
    }
    return {
      engine: "none",
      status: "missing",
      detail: "未找到 PDF 引擎。请先安装 Homebrew，或手动执行：brew install tectonic",
    };
  }
  if (process.platform === "linux") {
    return {
      engine: "none",
      status: "missing",
      detail: "未找到 PDF 引擎。可安装 tectonic，或 apt/yum 安装 texlive-xetex 后再导出。",
    };
  }
  return {
    engine: "none",
    status: "unsupported-platform",
    detail: "当前平台未配置自动安装 PDF 引擎；请手动安装 tectonic 或 xelatex。",
  };
}
