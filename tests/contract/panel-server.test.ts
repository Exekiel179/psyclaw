import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bootstrapProject } from "../../src/project/bootstrap.js";
import { RunEventLog } from "../../src/panel/events.js";
import { createPanelServer } from "../../src/panel/server.js";

describe("read-only panel server", () => {
  it("serves the run listing and a snapshot over narrow JSON endpoints", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-panel-"));
    await bootstrapProject({ root, goal: "Bounded", paradigm: "qualitative-thematic" });
    const log = new RunEventLog(root, "run-server");
    await log.append({ type: "planned", at: "2026-01-01T00:00:00.000Z" });
    await log.append({ type: "started", at: "2026-01-01T00:00:01.000Z" });

    const htmlPath = join(root, "panel.html");
    await writeFile(htmlPath, "<!DOCTYPE html><title>panel</title>", "utf8");

    const server = createPanelServer(root, { panelHtmlPath: htmlPath });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    const base = `http://127.0.0.1:${port}`;

    try {
      const runsRes = await fetch(`${base}/api/runs`);
      expect(runsRes.status).toBe(200);
      const listing = (await runsRes.json()) as { runs: { runId: string }[] };
      expect(listing.runs.map((item) => item.runId)).toEqual(["run-server"]);

      const snapshotRes = await fetch(`${base}/api/snapshot?runId=run-server`);
      expect(snapshotRes.status).toBe(200);
      const snapshot = (await snapshotRes.json()) as { runId: string; phase: string };
      expect(snapshot.runId).toBe("run-server");
      expect(snapshot.phase).toBe("executing");

      const previousKey = process.env.DEEPSEEK_API_KEY;
      process.env.DEEPSEEK_API_KEY = "panel-secret-must-not-leak";
      try {
        const catalogRes = await fetch(`${base}/api/catalog`);
        expect(catalogRes.status).toBe(200);
        const catalogText = await catalogRes.text();
        expect(catalogText).not.toContain("panel-secret-must-not-leak");
        const catalog = JSON.parse(catalogText) as {
          schemaVersion: string;
          agents: Array<{ source: string; ref: string; license: string; sha256: string | null; risk: string; configured: boolean; installPlan: { status: string; approval: string } }>;
          models: Array<{ source: string; ref: string; version: string; license: string; sha256: string | null; risk: string; configured: boolean; apiKeyEnv: string }>;
        };
        expect(catalog.schemaVersion).toBe("psyclaw/panel-catalog/v1");
        expect(catalog.agents.length).toBeGreaterThan(0);
        expect(catalog.agents[0]).toEqual(expect.objectContaining({ source: expect.any(String), ref: expect.any(String), license: expect.any(String), sha256: null, risk: expect.any(String), configured: expect.any(Boolean) }));
        expect(catalog.agents[0]!.installPlan).toEqual(expect.objectContaining({ status: "plan-only", approval: "required" }));
        expect(catalog.models).toEqual(expect.arrayContaining([
          expect.objectContaining({ provider: "deepseek", license: "provider-terms", sha256: null, risk: "network", configured: true, apiKeyEnv: "DEEPSEEK_API_KEY" }),
        ]));

        const planRes = await fetch(`${base}/api/install-plan?agentId=openai-codex`);
        expect(planRes.status).toBe(200);
        const plan = (await planRes.json()) as { status: string; approval: string; plan: { effect: string; command: string; projectRoot?: string } };
        expect(plan.status).toBe("plan-only");
        expect(plan.approval).toBe("required");
        expect(plan.plan.effect).toBe("write");
        expect(plan.plan.command).toContain("@openai/codex@");
        expect(plan.plan.projectRoot).toBeUndefined();
        expect((await fetch(`${base}/api/import-plan?agentId=does-not-exist`)).status).toBe(404);
      } finally {
        if (previousKey === undefined) delete process.env.DEEPSEEK_API_KEY;
        else process.env.DEEPSEEK_API_KEY = previousKey;
      }

      const htmlRes = await fetch(`${base}/`);
      expect(htmlRes.status).toBe(200);
      expect(await htmlRes.text()).toContain("panel");

      const writeRes = await fetch(`${base}/api/runs`, { method: "POST" });
      expect(writeRes.status).toBe(405);
      expect((await fetch(`${base}/api/catalog`, { method: "POST" })).status).toBe(405);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
