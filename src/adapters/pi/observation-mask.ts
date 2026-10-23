/**
 * Shrinks the tool-result trajectory sent to the model.
 *
 * Pi copies session messages and runs extension `context` handlers before each
 * provider call. The session transcript stays intact; only that copy changes.
 * Recent tool results stay available. Older ones keep a head and a tail.
 * An earlier exact duplicate is replaced by a one-line stub so a repeated
 * identical call is not paid for again on every later turn.
 */

const MARK = "[psyclaw:observation-masked";

export const OBSERVATION_MASK = {
  keepRecent: 6,
  recentChars: 12_000,
  staleHeadChars: 480,
  staleTailChars: 1_600,
} as const;

type ObservationMaskOptions = Partial<typeof OBSERVATION_MASK>;

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
