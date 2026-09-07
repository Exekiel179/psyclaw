import { randomUUID } from "node:crypto";
import { appendJsonl } from "../project/jsonl.js";
import { assertSafeProjectPath, projectPaths } from "../project/paths.js";

export const CHOICE_RECORD_SCHEMA = "psyclaw/choice-record/v1" as const;
export type ChoiceRecordSource = "tool" | "free-text";

export interface ChoiceRecordInput {
  prompt: string;
  originalResponse: string;
  selectedIds: string[];
  selectedLabels: string[];
  source: ChoiceRecordSource;
  context?: string;
}

export interface ChoiceRecord extends ChoiceRecordInput {
  schemaVersion: typeof CHOICE_RECORD_SCHEMA;
  id: string;
  recordedAt: string;
}

export async function appendChoiceRecord(root: string, input: ChoiceRecordInput): Promise<ChoiceRecord> {
  if (!input.prompt.trim() || !input.originalResponse.trim()) throw new Error("choice prompt and original response are required");
  if (input.source !== "tool" && input.source !== "free-text") throw new Error("invalid choice record source");
  const record: ChoiceRecord = {
    schemaVersion: CHOICE_RECORD_SCHEMA,
    id: `choice_${randomUUID().replaceAll("-", "")}`,
    prompt: input.prompt,
    originalResponse: input.originalResponse,
    selectedIds: [...input.selectedIds],
    selectedLabels: [...input.selectedLabels],
    source: input.source,
    ...(input.context === undefined ? {} : { context: input.context }),
    recordedAt: new Date().toISOString(),
  };
  const path = await assertSafeProjectPath(root, ".psyclaw/choices.jsonl");
  await appendJsonl(path, record);
  return record;
}
