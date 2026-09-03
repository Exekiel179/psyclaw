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
  const cmd = (name: string, args: string, desc: string) =>
    `  ${c.teal(name.padEnd(10))} ${c.gray(args.padEnd(34))} ${desc}`;

  return [
    banner,
    "",
    `  ${c.bold(c.white("输入 psyclaw 进入对话，然后使用以下 / 命令："))}`,
    "",
    cmd("/init", "[--paradigm <id>] <research goal>", c.white("初始化研究项目并开始学术追问")),
    cmd("/run", "[auto] [--skills a,b] [objective]", c.white("启动受控研究流程")),
    cmd("/brief", "", c.white("生成离线证据门控简报")),
    cmd("/grill", "[subject]", c.white("逐题压力测试研究方案")),
    cmd("/review", "", c.white("运行多角色模拟同行评审")),
    cmd("/loop", "[objective|stop]", c.white("推进或停止当前有界研究循环")),
    cmd("/skill", "[status|enable|disable|install]", c.white("管理和安装 Skill")),
    cmd("/mcp", "", c.white("管理 MCP 服务器")),
    cmd("/plugin", "", c.white("打开 Plugin 推荐与管理页")),
    cmd("/install", "[skill|mcp] [id]", c.white("查看或安装推荐能力")),
    cmd("/provider", "[provider-id]", c.white("查看、配置或切换 Provider")),
    cmd("/panel", "", c.white("打开科研工作台")),
    cmd("/export", "", c.white("使用 Pi 内置命令导出会话")),
    cmd("/pet", "on|off|status", c.white("开启、关闭或查看启动横幅宠物")),
    cmd("/help", "", c.white("查看全部对话命令")),
    "",
    `  ${c.gray("终端：")} ${c.teal("psyclaw -v")} ${c.darkGray("/")} ${c.teal("psyclaw --version")} ${c.gray("查看版本号")}`,
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
