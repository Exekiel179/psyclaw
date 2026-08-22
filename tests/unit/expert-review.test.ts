import { describe, expect, it } from "vitest";
import { aggregateExpertReview, validateExpertReviewContract } from "../../src/workflows/expert-review.js";

const contract = {
  schemaVersion: "psyclaw/expert-review/v1" as const,
  runId: "run-review",
  subject: { kind: "manuscript" as const, ref: "manuscript:v1" },
  inputRefs: ["artifact:manuscript"],
  experts: [
    { expertId: "method", role: "methodologist" as const, taskId: "review-method" },
    { expertId: "evidence", role: "evidence-critic" as const, taskId: "review-evidence" },
  ],
  requiredRoles: ["methodologist", "evidence-critic"] as const,
  minOpinions: 2,
  independent: true as const,
  output: { artifactPath: "review/expert-review.json", verdictPath: "review/verdict.json" },
};

const opinion = (expertId: string, role: "methodologist" | "evidence-critic", taskId: string, outcome: "complete" | "blocked" | "uncertain" = "complete") => ({
  schemaVersion: "psyclaw/expert-review-opinion/v1" as const,
  runId: "run-review",
  taskId,
  dispatchId: `dispatch-${expertId}`,
  expertId,
  role,
  outcome,
  summary: "reviewed",
  findings: [],
  evidenceRefs: ["artifact:manuscript"],
});

describe("expert review contract", () => {
  it("accepts independent required roles", () => {
    expect(aggregateExpertReview(contract, [
      opinion("method", "methodologist", "review-method"),
      opinion("evidence", "evidence-critic", "review-evidence"),
    ]).verdict).toBe("pass");
  });

  it("blocks missing roles and blocked opinions", () => {
    const result = aggregateExpertReview(contract, [opinion("method", "methodologist", "review-method", "blocked")]);
    expect(result.verdict).toBe("blocked");
    expect(result.blockReasons.join(" ")).toMatch(/missing required roles|expert blocked/);
  });

  it("rejects a contract without a configured required role", () => {
    expect(() => validateExpertReviewContract({ ...contract, requiredRoles: ["ethics-reviewer"] })).toThrow(/required role/);
  });
});
