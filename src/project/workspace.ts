import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicWriteFile } from "../project/jsonl.js";
import { assertSafeProjectPath, ensureProjectDirectories, projectPaths } from "../project/paths.js";

export const PSYCLAW_MD = "psyclaw.md" as const;
export const ANALYSIS_HANDOFF = "analysis/HANDOFF.md" as const;

export function defaultPsyClawMarkdown(projectLabel = "未命名研究项目"): string {
  return [
    `# ${projectLabel}`,
    "",
    "本文件是项目上层约定（PsyClaw 0.29+）。Shift+Tab 在 `chat` → `analysis` → `academic` 间循环。",
    "",
    "## 目录",
    "",
    "- `data/raw/` — 原始数据（只读；指纹仅用于防篡改，不作学术核验）",
    "- `data/clean/` — 可分析派生数据",
    "- `analysis/scripts|configs|results|plans/` — 脚本、规格、结果、分析方案",
    "- `analysis/HANDOFF.md` — 分析→学术交接",
    "- `literature/` — 文献",
    "- `paper/` — 手稿与导出",
    "- `psyclaw.md` — 本说明（根目录）",
    "- `.psyclaw/` — 账本、agents、skills、系统交接、ars-runs",
    "",
    "## 流水线（软门禁）",
    "",
    "初始化仓库 → 澄清 → 审查 → 形成方案（`/plan`）→ 审查 → 分析（默认可复现脚本；特殊后端再用 MCP）→ 分析报告 → 审查 → academic/ARS（每阶段审查）。",
    "",
    "第一要务：把结果跑出来。第二：用 AI 语义核查核心字段 + 人用 `/verify` 勾选已核实。不把 SHA256 当学术过关证明。",
    "",
    "## 模式",
    "",
    "| 模式 | 用途 |",
    "| --- | --- |",
    "| chat | 普通对话 |",
    "| analysis | 数据分析与 `/plan` 统计方案 |",
    "| academic | ARS 写作审稿（消费 HANDOFF，不重选检验） |",
    "",
  ].join("\n");
}

export function defaultAnalysisHandoff(): string {
  return [
    "# Analysis → Academic handoff",
    "",
    "- Status: draft",
    "- Question / design:",
    "- Primary results paths:",
    "- Key numbers (N, effects):",
    "- Limits / unverified items:",
    "- Ready for academic: no",
    "",
  ].join("\n");
}

/**
 * Does not run academic-grill or force a separate run command.
 */
export async function scaffoldWorkspace(root: string, options?: { label?: string }): Promise<{
  root: string;
  psyclawMd: string;
  handoff: string;
}> {
  await ensureProjectDirectories(root);
  const paths = projectPaths(root);
  const psyclawMdPath = join(paths.root, PSYCLAW_MD);
  try {
    await readFile(psyclawMdPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    await writeFile(psyclawMdPath, defaultPsyClawMarkdown(options?.label), "utf8");
  }
  const handoffPath = await assertSafeProjectPath(root, ANALYSIS_HANDOFF);
  try {
    await readFile(handoffPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    await mkdir(join(root, "analysis"), { recursive: true });
    await atomicWriteFile(handoffPath, defaultAnalysisHandoff());
  }
  // Ensure paper/ exists for manuscripts.
  await mkdir(join(root, "paper"), { recursive: true });
  return { root, psyclawMd: PSYCLAW_MD, handoff: ANALYSIS_HANDOFF };
}
