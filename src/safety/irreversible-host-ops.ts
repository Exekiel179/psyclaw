/**
 * Hard blocks for host-teardown commands that can destroy the agent's own
 * runtime (e.g. WSL unregister wiping the bash host on Windows).
 *
 * These must run even when the project is not /init'd — ordinary approval
 * gates only attach after project bootstrap.
 */

export type IrreversibleHostOpMatch = {
  id: string;
  /** Short label for UI / block reason. */
  label: string;
  /** What the user loses if this runs. */
  blastRadius: string;
};

const PATTERNS: ReadonlyArray<{ id: string; label: string; blastRadius: string; re: RegExp }> = [
  {
    id: "wsl-unregister",
    label: "wsl --unregister",
    blastRadius: "注销整个 WSL 发行版并删除其虚拟磁盘（含家目录与数据）；若 PsyClaw 的 bash 跑在该发行版内，工具通道会一并失效且通常不可恢复",
    // `--` is non-word; do not use \\b immediately before it.
    re: /\bwsl(?:\.exe)?\b(?:\s+|[\s\S]{0,200}?\s)(?:--)?unregister\b/i,
  },
  {
    id: "powershell-wsl-unregister",
    label: "Unregister-WslDistribution",
    blastRadius: "通过 PowerShell 注销 WSL 发行版，效果等同 wsl --unregister",
    re: /\bUnregister-(?:WslDistribution|Distro)\b/i,
  },
  {
    id: "disk-format",
    label: "format / diskpart clean",
    blastRadius: "格式化或清空磁盘分区，属于不可逆主机破坏操作",
    re: /(?:^|[;&|`]|\n)\s*(?:format\s+[a-z]:|diskpart\b[\s\S]{0,120}\bclean(?:\s+all)?\b)/i,
  },
  {
    id: "rm-root-or-home",
    label: "rm -rf / or $HOME",
    blastRadius: "递归删除根目录或整个家目录，会毁掉运行环境与用户数据",
    re: /\brm\s+-[rf]+\s+(?:\/(?:\s|$)|\/\*(?:\s|$)|~(?:\s|\/|$)|\$HOME(?:\s|\/|$)|\$\{?HOME\}?(?:\s|\/|$))/i,
  },
];

/** Extract a shell/command string from common tool payloads. */
export function extractToolCommandText(toolName: string, input: unknown): string | undefined {
  if (!/^(?:bash|shell|powershell|cmd|exec)$/i.test(toolName)) return undefined;
  if (!input || typeof input !== "object" || Array.isArray(input)) return undefined;
  const record = input as Record<string, unknown>;
  for (const key of ["command", "cmd", "script", "code"] as const) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return undefined;
}

/**
 * Classify a shell command as a hard-blocked host teardown, if matched.
 * Prefer the first match; callers should hard-block without model override.
 */
export function classifyIrreversibleHostCommand(command: string): IrreversibleHostOpMatch | undefined {
  const text = command.trim();
  if (!text) return undefined;
  for (const pattern of PATTERNS) {
    if (pattern.re.test(text)) {
      return { id: pattern.id, label: pattern.label, blastRadius: pattern.blastRadius };
    }
  }
  return undefined;
}

export function irreversibleHostBlockReason(match: IrreversibleHostOpMatch): string {
  return [
    `已拦截不可逆主机操作（${match.label}）。`,
    `爆炸半径：${match.blastRadius}。`,
    "此类操作不能由 PsyClaw 代为执行；请在会话外由用户自行评估，并在执行前完成备份/导出。",
  ].join("");
}
