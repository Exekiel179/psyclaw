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
    cmd("/init", "[--paradigm <id>] <goal>", c.white("初始化研究项目工作区")),
    cmd("/plan", "new|status|auto|confirm|run|…", c.white("分析方案（也可回复「可以」）")),
    cmd("/crosscheck", "list|kind|<id> verified|human …", c.white("AI 核查 + 人审（别名 /verify）")),
    cmd("/verify", "同 /crosscheck", c.white("AI 核查 + 人审别名")),
    cmd("/brainstorm", "[subject]", c.white("研究方向头脑风暴与问题澄清")),
    cmd("/grill", "[subject]", c.white("逐题压力测试研究方案")),
    cmd("/review", "", c.white("多角色模拟同行评审")),
    cmd("/panel", "", c.white("打开科研工作台")),
    cmd("/help", "", c.white("打开 Panel 使用速览（本页同步更新）")),
    cmd("/skill", "[status|enable|install|…]", c.white("Skill 管理（推荐 distill-scholar / distill-journal）")),
    cmd("/agents", "[--agent id] [task]", c.white("浏览或运行 Subagent")),
    cmd("/ars", "[status|doctor|start|full|stop]", c.white("学术模式入口")),
    cmd("/mcp", "", c.white("管理 MCP 服务器")),
    cmd("/plugin", "", c.white("打开 Plugin 推荐与管理页")),
    cmd("/provider", "[provider-id]", c.white("查看、配置或切换 Provider")),
    cmd("/export", "", c.white("导出会话")),
    cmd("/pet", "on|off|status", c.white("启动横幅宠物")),
    "",
    `  ${c.gray("快捷键：")} ${c.teal("Shift+Tab")} ${c.gray("模式 chat→analysis→academic")} ${c.darkGray("·")} ${c.teal("Ctrl+Shift+T")} ${c.gray("Thinking")}`,
    "",
    `  ${c.gray("终端：")} ${c.teal("psyclaw --continue")} ${c.darkGray("/")} ${c.teal("psyclaw -c")} ${c.gray("续接最近会话")}`,
    `          ${c.teal("psyclaw --continuously-work")} ${c.gray("持续自动推进（红字警告：费 token、不保质量）")}`,
    `          ${c.teal("psyclaw -v")} ${c.darkGray("/")} ${c.teal("psyclaw --version")} ${c.gray("版本号")}`,
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

/**
 * Compact human summary for `psyclaw update`. Full JSON is reserved for `--detail`.
 */
export function renderProductUpdateSummary(receipt: {
  ok: boolean;
  reasonCode: string;
  reason?: string;
  note?: string;
  commands: string[];
  psyclaw: { before?: string; after?: string; latest?: string };
}): string {
  const before = receipt.psyclaw.before;
  const after = receipt.psyclaw.after ?? receipt.psyclaw.latest;
  const arrow = before !== undefined && after !== undefined
    ? `${before} → ${after}`
    : after ?? before ?? "unknown";

  const noteLines = receipt.note
    ? receipt.note.split("\n").map((line) => `    ${c.darkGray("•")} ${c.gray(line)}`)
    : [];

  if (receipt.reasonCode === "update-applied") {
    return [
      renderSuccessCard("升级成功", { PsyClaw: arrow }).trimEnd(),
      ...noteLines,
      "",
    ].join("\n");
  }
  if (receipt.reasonCode === "already-up-to-date") {
    return renderSuccessCard("已是最新", { PsyClaw: after ?? before ?? "unknown" });
  }
  if (receipt.reasonCode === "update-skipped" && receipt.reason?.includes("source checkout")) {
    const lines = [
      `  ${c.yellow("➜")} ${c.bold("源码检出：跳过 npm 自覆盖")}`,
      `    ${c.darkGray("•")} ${c.gray("当前:")} ${c.white(before ?? "unknown")}`,
      `    ${c.darkGray("•")} ${c.gray("请先 Git 同步，再执行:")} ${c.white(receipt.commands.join(" && ") || "pnpm install && pnpm build")}`,
      "",
    ];
    return lines.join("\n");
  }
  if (receipt.reasonCode === "update-skipped" && receipt.reason?.startsWith("check only")) {
    return [
      `  ${c.yellow("➜")} ${c.bold("可升级（未执行）")}`,
      `    ${c.darkGray("•")} ${c.gray("PsyClaw:")} ${c.white(arrow)}`,
      ...(receipt.commands.length > 0
        ? [`    ${c.darkGray("•")} ${c.gray("命令:")} ${c.white(receipt.commands[0]!)}`]
        : []),
      "",
    ].join("\n");
  }
  if (receipt.ok) {
    return renderSuccessCard(receipt.reason ?? receipt.reasonCode, { PsyClaw: arrow });
  }
  return [
    `  ${c.red("✗")} ${c.bold("升级未完成")}`,
    `    ${c.darkGray("•")} ${c.gray("原因:")} ${c.white(receipt.reason ?? receipt.reasonCode)}`,
    `    ${c.darkGray("•")} ${c.gray("PsyClaw:")} ${c.white(arrow)}`,
    ...noteLines,
    "",
  ].join("\n");
}
