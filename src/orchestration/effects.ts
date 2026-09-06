import type { Effect } from "../core/contracts.js";

const EFFECT_ORDER: readonly Effect[] = ["read", "write", "network", "destructive"];
const EFFECT_SET = new Set<Effect>(EFFECT_ORDER);

/** Pi tools granted per effect class after explicit user approval. */
const TOOLS_BY_EFFECT: Record<Effect, readonly string[]> = {
  read: ["read", "grep", "find", "ls"],
  write: ["write", "edit"],
  network: ["bash"],
  destructive: ["bash"],
};

export function isEffect(value: unknown): value is Effect {
  return typeof value === "string" && EFFECT_SET.has(value as Effect);
}

/** Normalize declared effects: always include read, drop unknowns/duplicates, stable order. */
export function normalizeEffects(raw: readonly unknown[] | undefined): Effect[] {
  const selected = new Set<Effect>(["read"]);
  for (const item of raw ?? []) {
    if (isEffect(item)) selected.add(item);
  }
  return EFFECT_ORDER.filter((effect) => selected.has(effect));
}

export function elevatedEffects(effects: readonly Effect[]): Effect[] {
  return effects.filter((effect) => effect !== "read");
}

export function hasElevatedEffects(effects: readonly Effect[]): boolean {
  return elevatedEffects(effects).length > 0;
}

export function toolsForEffects(effects: readonly Effect[]): string[] {
  const tools = new Set<string>();
  for (const effect of normalizeEffects(effects)) {
    for (const tool of TOOLS_BY_EFFECT[effect]) tools.add(tool);
  }
  return [...tools];
}

export function formatEffects(effects: readonly Effect[]): string {
  return normalizeEffects(effects).join(", ");
}
