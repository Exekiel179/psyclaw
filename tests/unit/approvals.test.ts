import { describe, expect, it } from "vitest";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  approvePrimaryDocument,
  PRIMARY_PLAN_DOCUMENTS,
  primaryPlanApprovalStatus,
  readApprovals,
} from "../../src/project/approvals.js";

describe("human approval records", () => {
  it("binds primary document approvals to the current file hash", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-approvals-"));
    await mkdir(join(root, ".psyclaw"), { recursive: true });
    await mkdir(join(root, "notes"), { recursive: true });
    for (const document of PRIMARY_PLAN_DOCUMENTS) {
      await writeFile(join(root, document.path), `${document.title}\n`, "utf8");
      await approvePrimaryDocument(root, document, "approved");
    }
    expect((await primaryPlanApprovalStatus(root)).ok).toBe(true);

    await writeFile(join(root, "notes", "plan.md"), "changed plan\n", "utf8");
    const changed = await primaryPlanApprovalStatus(root);
    expect(changed.ok).toBe(false);
    expect(changed.documents.find((item) => item.id === "plan")?.approved).toBe(false);
  });

  it("keeps rejected decisions in the append-only approval history", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-approval-reject-"));
    await mkdir(join(root, ".psyclaw"), { recursive: true });
    await mkdir(join(root, "notes"), { recursive: true });
    const document = PRIMARY_PLAN_DOCUMENTS[0];
    await writeFile(join(root, document.path), "goal\n", "utf8");
    await approvePrimaryDocument(root, document, "rejected");
    expect(await readApprovals(root)).toEqual([
      expect.objectContaining({ kind: "document", nodeId: "goal", decision: "rejected", actor: "human" }),
    ]);
  });
});
