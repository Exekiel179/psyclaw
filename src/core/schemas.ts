import { Type, type Static, type TSchema } from "typebox";
import { Compile } from "typebox/compile";
import type { Claim, ClaimEvidenceLink, Evidence, Handoff, ResearchProject, ToolReceipt } from "./contracts.js";

const OptionalString = Type.Optional(Type.String({ minLength: 1 }));
const OptionalReasonCode = Type.Optional(Type.String({
  pattern: "^[a-z0-9][a-z0-9._-]{0,63}$",
}));
const LocatorSchema = Type.Object({
  kind: Type.Union([
    Type.Literal("doi"),
    Type.Literal("url"),
    Type.Literal("file"),
    Type.Literal("page"),
    Type.Literal("section"),
    Type.Literal("offset"),
    Type.Literal("row"),
  ]),
  value: Type.String({ minLength: 1 }),
});

export const ResearchProjectSchema = Type.Object({
  id: Type.String({ minLength: 1 }),
  root: Type.String({ minLength: 1 }),
  paradigm: Type.Union([
    Type.Literal("survey-observational"),
    Type.Literal("qualitative-thematic"),
    Type.Literal("experimental"),
    Type.Literal("quasi-experimental"),
    Type.Literal("longitudinal-panel"),
    Type.Literal("meta-analysis"),
    Type.Literal("ethnographic"),
    Type.Literal("historical-documentary"),
    Type.Literal("policy-legal"),
    Type.Literal("mixed-methods"),
  ]),
  goal: Type.String({ minLength: 1 }),
  policyVersion: Type.String({ minLength: 1 }),
  createdAt: Type.String({ minLength: 1 }),
}, { additionalProperties: false });

export const EvidenceSchema = Type.Object({
  id: Type.String({ minLength: 1 }),
  source: Type.Object({
    kind: Type.Union([
      Type.Literal("doi"),
      Type.Literal("url"),
      Type.Literal("file"),
      Type.Literal("user"),
      Type.Literal("mcp"),
    ]),
    locator: Type.String({ minLength: 1 }),
    title: OptionalString,
  }, { additionalProperties: false }),
  level: Type.Union([
    Type.Literal("metadata"),
    Type.Literal("abstract"),
    Type.Literal("snippet"),
    Type.Literal("fulltext"),
    Type.Literal("user"),
  ]),
  quote: OptionalString,
  retrievedAt: Type.String({ minLength: 1 }),
  sha256: Type.Optional(Type.String({ pattern: "^[a-f0-9]{64}$" })),
  accessStatus: Type.Union([Type.Literal("verified"), Type.Literal("partial"), Type.Literal("unavailable")]),
  locators: Type.Array(LocatorSchema),
}, { additionalProperties: false });

export const ClaimSchema = Type.Object({
  recordType: Type.Optional(Type.Literal("claim")),
  id: Type.String({ minLength: 1 }),
  text: Type.String({ minLength: 1 }),
  kind: Type.Union([
    Type.Literal("existence"),
    Type.Literal("definition"),
    Type.Literal("method"),
    Type.Literal("result"),
    Type.Literal("interpretation"),
  ]),
  evidenceIds: Type.Array(Type.String({ minLength: 1 })),
  status: Type.Union([Type.Literal("supported"), Type.Literal("uncertain"), Type.Literal("unsupported")]),
  uncertainty: OptionalString,
}, { additionalProperties: false });

export const ClaimEvidenceLinkSchema = Type.Object({
  recordType: Type.Optional(Type.Literal("claim-evidence-link")),
  claimId: Type.String({ minLength: 1 }),
  evidenceId: Type.String({ minLength: 1 }),
  relation: Type.Union([Type.Literal("supports"), Type.Literal("contradicts"), Type.Literal("context")]),
  locator: Type.Optional(LocatorSchema),
  rationale: Type.String({ minLength: 1 }),
}, { additionalProperties: false });

export const ToolReceiptSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/tool-receipt/v1"),
  runId: Type.String({ minLength: 1 }),
  taskId: Type.String({ minLength: 1 }),
  tool: Type.String({ minLength: 1 }),
  effect: Type.Union([Type.Literal("read"), Type.Literal("write"), Type.Literal("network"), Type.Literal("destructive")]),
  approval: Type.Union([Type.Literal("not-needed"), Type.Literal("approved"), Type.Literal("denied")]),
  idempotencyKey: OptionalString,
  ok: Type.Boolean(),
  reasonCode: OptionalReasonCode,
  resultHash: OptionalString,
  startedAt: Type.String({ minLength: 1 }),
  finishedAt: Type.String({ minLength: 1 }),
}, { additionalProperties: false });

export const HandoffSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/handoff/v1"),
  projectId: Type.String({ minLength: 1 }),
  runId: Type.String({ minLength: 1 }),
  goal: Type.String({ minLength: 1 }),
  completed: Type.Array(Type.String()),
  verified: Type.Array(Type.String()),
  blocked: Type.Array(Type.String()),
  nextSteps: Type.Array(Type.String()),
  verificationCommands: Type.Array(Type.String()),
  generatedAt: Type.String({ minLength: 1 }),
}, { additionalProperties: false });

export type ResearchProjectShape = Static<typeof ResearchProjectSchema>;
export type EvidenceShape = Static<typeof EvidenceSchema>;
export type ClaimShape = Static<typeof ClaimSchema>;
export type ToolReceiptShape = Static<typeof ToolReceiptSchema>;
export type HandoffShape = Static<typeof HandoffSchema>;

export interface SchemaValidator<T extends TSchema> {
  check(value: unknown): boolean;
  errors(value: unknown): string[];
}

function validator<T extends TSchema>(schema: T): SchemaValidator<T> {
  const compiled = Compile(schema);
  return {
    check: (value) => compiled.Check(value),
    errors: (value) => [...compiled.Errors(value)].map((error) => {
      const path = "path" in error && typeof error.path === "string" ? error.path : "/";
      return `${path}: ${error.message}`;
    }),
  };
}

export const validators = {
  researchProject: validator(ResearchProjectSchema),
  evidence: validator(EvidenceSchema),
  claim: validator(ClaimSchema),
  claimEvidenceLink: validator(ClaimEvidenceLinkSchema),
  toolReceipt: validator(ToolReceiptSchema),
  handoff: validator(HandoffSchema),
};

export function assertSchema<T>(value: unknown, schemaName: keyof typeof validators): asserts value is T {
  const result = validators[schemaName];
  if (!result.check(value)) throw new Error(`${schemaName} schema invalid: ${result.errors(value).join("; ")}`);
}

export function asProject(value: unknown): ResearchProject {
  assertSchema<ResearchProject>(value, "researchProject");
  return value;
}

export function asEvidence(value: unknown): Evidence {
  assertSchema<Evidence>(value, "evidence");
  return value;
}

export function asClaim(value: unknown): Claim {
  assertSchema<Claim>(value, "claim");
  return value;
}

export function asClaimEvidenceLink(value: unknown): ClaimEvidenceLink {
  assertSchema<ClaimEvidenceLink>(value, "claimEvidenceLink");
  return value;
}

export function asToolReceipt(value: unknown): ToolReceipt {
  assertSchema<ToolReceipt>(value, "toolReceipt");
  return value;
}

export function asHandoff(value: unknown): Handoff {
  assertSchema<Handoff>(value, "handoff");
  return value;
}
