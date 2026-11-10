/**
 * What's new: a short notice the first time an interactive session starts on a
 * new version. The last version shown is kept in the agent directory, so each
 * version is announced once per machine. Headless runs never show it.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

/** User-facing notes per version, newest first. Versions without an entry stay quiet. */
export const WHATS_NEW: Record<string, readonly string[]> = {
  "0.33.0": [
    "提供新的交互模式 prior。按 Shift+Tab 可切到先回忆；批准后的分析以已定稿方案为准",
  ],
  "0.32.0": [
    "新增 prior 模式：先按假设回忆，再解锁数据；分析方案由脚本开头的带标签常量生成",
    "按 Shift+Tab 可切到 prior。核心问题逐张问，技术设置一次确认；α、单双尾、多重比较和支持规则直接声明，不拿来问",
    "prior 里不调用 skill。批准后按你的选择改脚本并直接运行，然后回到普通对话，这时可以使用 skill",
    "批准后的对话只记已定稿方案。后续分析按这份方案走，不再重开回忆和选项卡",
  ],
  "0.31.3": [
    "修复任务超时问题：耗时计算先小规模计时，慢脚本只重跑改动部分，并提示重复的完整重跑",
    "优化学术决策细节：方案中逐项记录分析决策点及其依据，结果判定规则在跑结局模型前锁定；需要研究者意图的选择会先问你，无人审批时把替代方案作为敏感性分析一并报告",
  ],
};

export function formatWhatsNew(version: string, notes: readonly string[]): string {
  return [`PsyClaw 已更新到 v${version}：`, ...notes.map((note) => `· ${note}`)].join("\n");
}

/**
 * Notice text when `version` has notes and has not been shown yet; records the
 * version as seen either way so the notice appears at most once.
 */
export async function takeWhatsNew(
  version: string,
  statePath: string,
  notes: Record<string, readonly string[]> = WHATS_NEW,
): Promise<string | undefined> {
  let lastSeen: unknown;
  try {
    lastSeen = (JSON.parse(await readFile(statePath, "utf8")) as { lastSeenVersion?: unknown }).lastSeenVersion;
  } catch { /* first run or unreadable state */ }
  if (lastSeen === version) return undefined;
  try {
    await mkdir(dirname(statePath), { recursive: true });
    await writeFile(statePath, `${JSON.stringify({ lastSeenVersion: version }, null, 2)}\n`, "utf8");
  } catch {
    return undefined; // without a record the notice would repeat every session
  }
  const entry = notes[version];
  return entry && entry.length > 0 ? formatWhatsNew(version, entry) : undefined;
}
