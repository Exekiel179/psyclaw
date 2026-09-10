/**
 * Launch-only continuously-work flag (`psyclaw --continuously-work`).
 * Not a Shift+Tab session mode — cannot be toggled mid-session.
 *
 * `--continue-work` and `--continuous-work` are accepted aliases: production
 * users typed the shorter form, which was previously treated as a positional
 * command name.
 */

export const CONTINUOUSLY_WORK_FLAG = "--continuously-work" as const;
export const CONTINUOUSLY_WORK_ENV = "PSYCLAW_CONTINUOUSLY_WORK" as const;
export const CONTINUOUSLY_WORK_ALIASES = ["--continue-work", "--continuous-work"] as const;

const CONTINUOUSLY_WORK_FLAGS = new Set<string>([CONTINUOUSLY_WORK_FLAG, ...CONTINUOUSLY_WORK_ALIASES]);

export function isContinuouslyWorkFlag(arg: string): boolean {
  return CONTINUOUSLY_WORK_FLAGS.has(arg);
}

/** Peel boolean flag from argv; never forward it to the Pi CLI. */
export function peelContinuouslyWorkFlag(args: readonly string[]): {
  enabled: boolean;
  args: string[];
} {
  let enabled = false;
  const next: string[] = [];
  for (const arg of args) {
    if (isContinuouslyWorkFlag(arg)) {
      enabled = true;
      continue;
    }
    next.push(arg);
  }
  return { enabled, args: next };
}

export function isContinuouslyWorkEnabled(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  return env[CONTINUOUSLY_WORK_ENV] === "1";
}

/** Red-text warning for stderr / TUI (high token use, quality not guaranteed). */
export function continuouslyWorkWarningText(): string {
  return [
    "⚠ continuously-work 已启用（仅 CLI：psyclaw --continuously-work）",
    "将持续自动推进分析与步骤，中途尽量不询问「是否继续」。",
    "警告：可能消耗大量 token，且不确保产出物质量。真正阻断（权限/缺数据/跑数失败等）才会停。",
    "Shift+Tab 的 chat/analysis/academic 模式仍可切换；本开关不能在会话内开关。",
  ].join("\n");
}

/** Appended to the system prompt when the launch flag is set. */
export function continuouslyWorkPrompt(): string {
  return [
    "## PsyClaw launch option: continuously-work",
    "Enabled only via CLI `psyclaw --continuously-work` (not Shift+Tab).",
    "Keep advancing analysis and bounded research steps without asking whether to continue.",
    "Pause only for true blockers: missing data access/consent, failed delegated stats, safety refusals, or qualifying research decisions that require the researcher.",
    "Do not invent numerical results, citations, or completed analyses. Still delegate statistics externally.",
    "Soft guidance only — no hard gates that block ordinary progress.",
    "Remind the researcher that this option can consume many tokens and does not guarantee artifact quality.",
  ].join("\n");
}
