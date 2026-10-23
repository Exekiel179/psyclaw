/**
 * Shrinks the tool-result trajectory sent to the model.
 *
 * Pi copies session messages and runs extension `context` handlers before each
 * provider call. The session transcript stays intact; only that copy changes.
 *
 * `maskToolObservations` is the sliding window: the newest results stay long,
 * and older ones are rewritten again as the window moves. That cuts characters
 * but changes bytes in the middle of the prompt, so a prefix cache stops there.
 *
 * `maskToolObservationsStable` is the comparison policy. Tool results after the
 * last assistant message stay long, because the model has not answered them yet.
 * A result that has already been answered is clipped once to a head and a tail;
 * later turns reproduce that same clip from the original text. A repeated
 * success stubs the new copy and leaves the earlier message unchanged.
 * Bounded research tools (profile, run, saved table, recall) stay intact so a
 * confirmatory number is not dropped from the middle on the next turn.
 */

const MARK = "[psyclaw:observation-masked";

export const OBSERVATION_MASK = {
  keepRecent: 6,
  recentChars: 12_000,
  staleHeadChars: 480,
  staleTailChars: 1_600,
} as const;

type ObservationMaskOptions = Partial<typeof OBSERVATION_MASK>;

export const OBSERVATION_EVIDENCE_TOOLS = new Set([
  "psyclaw_data_profile",
  "psyclaw_run_analysis",
  "psyclaw_read_results",
  "psyclaw_recall_output",
]);

export function observationSettledLimit(options?: ObservationMaskOptions): number {
  return (options?.staleHeadChars ?? OBSERVATION_MASK.staleHeadChars) + (options?.staleTailChars ?? OBSERVATION_MASK.staleTailChars);
}

export function isObservationEvidence(toolName: string | undefined): boolean {
  return toolName !== undefined && OBSERVATION_EVIDENCE_TOOLS.has(toolName);
}

/** Skill bodies are standing instructions, not observations; clipping their middle drops the stage rules. */
export const OBSERVATION_INSTRUCTION_TOOLS = new Set(["psyclaw_skill"]);

export function isInstructionResult(toolName: string | undefined): boolean {
  return toolName !== undefined && OBSERVATION_INSTRUCTION_TOOLS.has(toolName);
}

type ContentPart = { type?: string; text?: string };

export type MaskableMessage = {
  role: string;
  toolName?: string;
  isError?: boolean;
  content?: unknown;
};

function contentParts(message: MaskableMessage): ContentPart[] | undefined {
  if (!Array.isArray(message.content)) return undefined;
  return message.content.filter((part): part is ContentPart => typeof part === "object" && part !== null);
}

function textOf(parts: ContentPart[]): string {
  return parts.filter((part) => part.type === "text" && typeof part.text === "string").map((part) => part.text).join("\n");
}

function alreadyMasked(text: string): boolean {
  return text.includes(MARK);
}

function clip(text: string, headChars: number, tailChars: number): string {
  if (text.length <= headChars + tailChars) return text;
  const omitted = text.length - headChars - tailChars;
  return `${text.slice(0, headChars)}\n${MARK} omitted ${omitted} chars]\n${text.slice(text.length - tailChars)}`;
}

function withText<T extends MaskableMessage>(message: T, text: string): T {
  const parts = contentParts(message) ?? [];
  const rest = parts.filter((part) => part.type !== "text");
  return { ...message, content: [{ type: "text", text }, ...rest] };
}

export function maskToolObservations<T extends MaskableMessage>(
  messages: readonly T[],
  options?: ObservationMaskOptions,
): T[] {
  const keepRecent = options?.keepRecent ?? OBSERVATION_MASK.keepRecent;
  const recentChars = options?.recentChars ?? OBSERVATION_MASK.recentChars;
  const staleHeadChars = options?.staleHeadChars ?? OBSERVATION_MASK.staleHeadChars;
  const staleTailChars = options?.staleTailChars ?? OBSERVATION_MASK.staleTailChars;
  const recentHead = Math.floor(recentChars / 3);
  const recentTail = recentChars - recentHead;

  const indexes: number[] = [];
  const texts: string[] = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message || message.role !== "toolResult") continue;
    const parts = contentParts(message);
    if (!parts) continue;
    const text = textOf(parts);
    if (text.length === 0 || alreadyMasked(text)) continue;
    indexes.push(index);
    texts.push(text);
  }
  if (indexes.length === 0) return messages as T[];

  const latestOf = new Map<string, number>();
  for (let slot = indexes.length - 1; slot >= 0; slot -= 1) {
    const index = indexes[slot];
    const text = texts[slot];
    if (index === undefined || text === undefined || text.length === 0) continue;
    const message = messages[index];
    if (!message || message.isError) continue;
    const key = `${message.toolName ?? ""}\0${text}`;
    if (!latestOf.has(key)) latestOf.set(key, slot);
  }

  const duplicate = new Set<number>();
  for (let slot = 0; slot < indexes.length; slot += 1) {
    const index = indexes[slot];
    const text = texts[slot];
    if (index === undefined || text === undefined || text.length === 0) continue;
    const message = messages[index];
    if (!message || message.isError) continue;
    const key = `${message.toolName ?? ""}\0${text}`;
    if (latestOf.get(key) !== slot) duplicate.add(slot);
  }

  const recent = new Set<number>();
  for (let slot = indexes.length - 1; slot >= 0 && recent.size < keepRecent; slot -= 1) {
    if (!duplicate.has(slot)) recent.add(slot);
  }

  let changed = false;
  const next = messages.slice() as T[];
  for (let slot = 0; slot < indexes.length; slot += 1) {
    const text = texts[slot];
    const index = indexes[slot];
    if (text === undefined || index === undefined) continue;
    const message = messages[index];
    if (!message) continue;
    let replacement: string | undefined;
    if (duplicate.has(slot)) {
      replacement = `${MARK} duplicate ${message.toolName ?? "tool"} omitted ${text.length} chars; a later identical result is kept]`;
    } else if (recent.has(slot)) {
      const clipped = clip(text, recentHead, recentTail);
      if (clipped !== text) replacement = clipped;
    } else {
      const clipped = clip(text, staleHeadChars, staleTailChars);
      if (clipped !== text) replacement = clipped;
    }
    if (replacement !== undefined) {
      next[index] = withText(message, replacement);
      changed = true;
    }
  }
  return changed ? next : (messages as T[]);
}

/**
 * Cache-stable observation mask. `keepRecent` is ignored: only tool results
 * newer than the last assistant message stay at the recent cap.
 */
export function maskToolObservationsStable<T extends MaskableMessage>(
  messages: readonly T[],
  options?: ObservationMaskOptions,
): T[] {
  const recentChars = options?.recentChars ?? OBSERVATION_MASK.recentChars;
  const staleHeadChars = options?.staleHeadChars ?? OBSERVATION_MASK.staleHeadChars;
  const staleTailChars = options?.staleTailChars ?? OBSERVATION_MASK.staleTailChars;
  const recentHead = Math.floor(recentChars / 3);
  const recentTail = recentChars - recentHead;

  let lastAssistant = -1;
  for (let index = 0; index < messages.length; index += 1) {
    if (messages[index]?.role === "assistant") lastAssistant = index;
  }

  const indexes: number[] = [];
  const texts: string[] = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message || message.role !== "toolResult") continue;
    const parts = contentParts(message);
    if (!parts) continue;
    const text = textOf(parts);
    if (text.length === 0) continue;
    indexes.push(index);
    texts.push(text);
  }
  if (indexes.length === 0) return messages as T[];

  const earliest = new Map<string, number>();
  const duplicate = new Set<number>();
  for (let slot = 0; slot < indexes.length; slot += 1) {
    const index = indexes[slot];
    const text = texts[slot];
    if (index === undefined || text === undefined || alreadyMasked(text)) continue;
    const message = messages[index];
    if (!message || message.isError) continue;
    const key = `${message.toolName ?? ""}\0${text}`;
    if (!earliest.has(key)) earliest.set(key, slot);
    else duplicate.add(slot);
  }

  let changed = false;
  const next = messages.slice() as T[];
  for (let slot = 0; slot < indexes.length; slot += 1) {
    const text = texts[slot];
    const index = indexes[slot];
    if (text === undefined || index === undefined || alreadyMasked(text)) continue;
    const message = messages[index];
    if (!message) continue;
    const fresh = index > lastAssistant;
    let replacement: string | undefined;
    if (duplicate.has(slot)) {
      replacement = `${MARK} duplicate ${message.toolName ?? "tool"} omitted ${text.length} chars; the earlier identical result is unchanged]`;
    } else if (isInstructionResult(message.toolName)) {
      continue;
    } else if (isObservationEvidence(message.toolName) || fresh) {
      const clipped = clip(text, recentHead, recentTail);
      if (clipped !== text) replacement = clipped;
    } else {
      const clipped = clip(text, staleHeadChars, staleTailChars);
      if (clipped !== text) replacement = clipped;
    }
    if (replacement !== undefined) {
      next[index] = withText(message, replacement);
      changed = true;
    }
  }
  return changed ? next : (messages as T[]);
}
