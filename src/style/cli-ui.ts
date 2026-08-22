/**
 * High-end, lightweight CLI UI styling and ANSI utilities for psyclaw.
 * Zero external runtime dependencies, fast and cross-platform.
 */

import { PSYCLAW_VERSION } from "../branding.js";

const isColorSupported = !process.env.NO_COLOR && (process.stdout.isTTY || process.env.FORCE_COLOR === "1");

function wrap(code: string, text: string): string {
  return isColorSupported ? `${code}${text}\x1b[0m` : text;
}

export const c = {
  reset: isColorSupported ? "\x1b[0m" : "",
  bold: (t: string) => wrap("\x1b[1m", t),
  dim: (t: string) => wrap("\x1b[2m", t),
  italic: (t: string) => wrap("\x1b[3m", t),
  underline: (t: string) => wrap("\x1b[4m", t),

  // 24-bit Truecolor & ANSI colors
  teal: (t: string) => wrap("\x1b[38;2;46;196;182m", t),
  cyan: (t: string) => wrap("\x1b[38;2;56;189;248m", t),
  blue: (t: string) => wrap("\x1b[38;2;99;102;241m", t),
  green: (t: string) => wrap("\x1b[38;2;34;197;94m", t),
  yellow: (t: string) => wrap("\x1b[38;2;245;158;11m", t),
  red: (t: string) => wrap("\x1b[38;2;244;63;94m", t),
  gray: (t: string) => wrap("\x1b[38;2;142;155;178m", t),
  darkGray: (t: string) => wrap("\x1b[38;2;86;99;122m", t),
  white: (t: string) => wrap("\x1b[38;2;240;244;252m", t),

  bgTeal: (t: string) => wrap("\x1b[48;2;46;196;182;30m", t),
  badge: (label: string, tone: "teal" | "green" | "yellow" | "blue" = "teal") => {
    const tones = {
      teal: "\x1b[38;2;5;20;27;48;2;46;196;182m",
      green: "\x1b[38;2;5;20;10;48;2;34;197;94m",
      yellow: "\x1b[38;2;30;20;5;48;2;245;158;11m",
      blue: "\x1b[38;2;10;15;35;48;2;99;102;241m",
    };
    return isColorSupported ? `${tones[tone]} ${label} \x1b[0m` : `[${label}]`;
  },
};

/**
 * Render the branded psyclaw CLI header banner.
 */
export function renderCliBanner(): string {
  const line = c.darkGray("─".repeat(58));
  return [
    "",
    `  ${c.teal(c.bold("ψ PsyClaw"))} ${c.badge(`v${PSYCLAW_VERSION}`, "teal")} ${c.gray("· 社会科学科研智能体工作台")}`,
    `  ${c.darkGray("Evidence-Grounded Social Science Research Agent")}`,
    `  ${line}`,
  ].join("\n");
}

/**
 * Render structured, color-coded CLI usage documentation.
 */
export function formatCliUsage(): string {
  const banner = renderCliBanner();
  const sep = c.darkGray("│");

  const cmd = (name: string, args: string, desc: string) =>
    `  ${c.teal(name.padEnd(14))} ${c.gray(args.padEnd(30))} ${desc}`;

  return [
    banner,
    "",
    `  ${c.bold(c.white("使用方式 (Usage):"))}`,
    `  ${c.cyan("$")} psyclaw ${c.gray("<command> [options...]")}`,
    "",
    `  ${c.bold(c.cyan("🚀 核心交互 (Interactive & Chat)"))}`,
    cmd("psyclaw [chat]", "[pi args...]", c.white("启动交互研究智能体 (默认入口)")),
    cmd("psyclaw wizard", "", c.white("首次使用提供商配置向导")),
    cmd("psyclaw setup", "[--provider deepseek|...]", c.white("配置模型提供商与 API Key")),
    "",
    `  ${c.bold(c.cyan("🎯 课题生命周期 (Project Lifecycle)"))}`,
    cmd("psyclaw init", "<goal> [--paradigm <id>]", c.white("创建社科研究课题项目")),
    cmd("psyclaw hitl init", "", c.white("初始化人工裁决 (HITL) 检查点模板")),
    cmd("psyclaw handoff", "", c.white("生成 HANDOFF 研究移交备忘录")),
    "",
    `  ${c.bold(c.cyan("🔬 科研工作流 (Research Workflows)"))}`,
    cmd("psyclaw brief", "", c.white("生成离线证据简报 (Offline Brief)")),
    "",
    `  ${c.bold(c.cyan("📁 证据与沙盒 (Evidence & Ledger)"))}`,
    cmd("psyclaw evidence add", "<path> [--level fulltext|...]", c.white("登记只读文献与证据文件指纹")),
    "",
    `  ${c.bold(c.cyan("📊 看板与 TUI (Observability & UI)"))}`,
    cmd("psyclaw shell", "", c.white("启动终端 TUI 智能体管理界面")),
    cmd("/panel (对话内)", "", c.white("在 psyclaw 对话中输入 /panel 打开科研工作台")),
    "",
    `  ${c.bold(c.cyan("🧩 生态与更新 (Ecosystem & Updates)"))}`,
    cmd("psyclaw agents", "", c.white("扫描已安装的外部领域智能体")),
    cmd("psyclaw install", "<agent-id> [--yes]", c.white("安装受信任扩展与技能")),
    cmd("psyclaw import", "<agent-id> [--yes]", c.white("导入外部智能体技能")),
    cmd("psyclaw check-updates", "", c.white("检查运行时与生态更新报告")),
    cmd("psyclaw update", "[--yes] [--force]", c.white("升级底层 Pi 运行时")),
    "",
    `  ${c.darkGray("──────────────────────────────────────────────────────────")}`,
    `  ${c.gray("文档与源码:")} ${c.cyan(c.underline("https://github.com/Exekiel179/psyclaw"))}`,
    "",
  ].join("\n");
}

/**
 * Render a styled info card box.
 */
export function renderCard(title: string, fields: Array<{ label: string; value: string }>): string {
  const width = 56;
  const top = c.teal(`┌─ ${c.bold(title)} `.padEnd(width + 10, "─") + "┐");
  const bottom = c.teal("└" + "─".repeat(width - 2) + "┘");

  const rows = fields.map((f) => {
    const line = `  ${c.gray(f.label.padEnd(12))} ${c.white(f.value)}`;
    return c.teal("│") + line.padEnd(width - 2) + c.teal("│");
  });

  return ["", top, ...rows, bottom, ""].join("\n");
}

/**
 * Render a styled success card for command results.
 */
export function renderSuccessCard(title: string, details?: Record<string, string>): string {
  const lines = [`  ${c.green("✔")} ${c.bold(title)}`];
  if (details) {
    for (const [k, v] of Object.entries(details)) {
      lines.push(`    ${c.darkGray("•")} ${c.gray(k + ":")} ${c.white(v)}`);
    }
  }
  return lines.join("\n") + "\n";
}
