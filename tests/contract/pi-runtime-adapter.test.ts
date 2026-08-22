import { describe, expect, it } from "vitest";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import {
  PiModelGateway,
  deepSeekProviderSpec,
  toOpenAICompatibleProviderConfig,
} from "../../src/adapters/pi/model.js";
import { createPiResourceLoader, loadPiSkillBody, snapshotPiResources } from "../../src/adapters/pi/resources.js";
import { openPiSession } from "../../src/adapters/pi/session.js";
import { PiRpcClient } from "../../src/adapters/pi/rpc.js";
import { createPiReadOnlyExecutor } from "../../src/orchestration/pi-executor.js";

async function fakePiScript(root: string, report = false): Promise<string> {
  const script = join(root, "fake-pi.mjs");
  const body = report
    ? `process.stdin.setEncoding("utf8");
let buffer = "";
process.stdin.on("data", chunk => { buffer += chunk; let i; while ((i = buffer.indexOf("\\n")) >= 0) { const line = buffer.slice(0, i); buffer = buffer.slice(i + 1); if (!line.trim()) continue; const request = JSON.parse(line); if (request.type === "prompt") { const report = { schemaVersion: "psyclaw/worker-report/v1", taskId: "task-1", dispatchId: "dispatch-1", outcome: "succeeded", summary: "read-only inspection complete", filesModified: [], verification: [], blockers: [] }; process.stdout.write(JSON.stringify({ type: "response", id: request.id, command: "prompt", success: true }) + "\\n"); process.stdout.write(JSON.stringify({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: JSON.stringify(report) }] } }) + "\\n"); process.stdout.write(JSON.stringify({ type: "agent_settled" }) + "\\n"); } else { process.stdout.write(JSON.stringify({ type: "response", id: request.id, command: request.type, success: true, data: {} }) + "\\n"); } } });`
    : `process.stdin.setEncoding("utf8");
let buffer = "";
process.stdin.on("data", chunk => { buffer += chunk; let i; while ((i = buffer.indexOf("\\n")) >= 0) { const line = buffer.slice(0, i); buffer = buffer.slice(i + 1); if (!line.trim()) continue; const request = JSON.parse(line); process.stdout.write(JSON.stringify({ type: "response", id: request.id, command: request.type, success: true, data: {} }) + "\\n"); if (request.type === "prompt") { process.stdout.write(JSON.stringify({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "ok" }] } }) + "\\n"); process.stdout.write(JSON.stringify({ type: "agent_settled" }) + "\\n"); } } });`;
  await writeFile(script, body, "utf8");
  return script;
}

describe("Pi runtime adapters", () => {
  it("builds an OpenAI-compatible config with an env reference only", () => {
    const config = toOpenAICompatibleProviderConfig(deepSeekProviderSpec());
    expect(config.apiKey).toBe("$DEEPSEEK_API_KEY");
    expect(JSON.stringify(config)).not.toContain("sk-");
    expect(config.baseUrl).toBe("https://api.deepseek.com/v1");
  });

  it("rejects provider URLs carrying credentials", () => {
    expect(() => toOpenAICompatibleProviderConfig({
      ...deepSeekProviderSpec(),
      baseUrl: "https://user:secret@example.test/v1",
    })).toThrow(/credentials/);
  });

  it("lists and resolves models without network refresh", async () => {
    const runtime = await ModelRuntime.create({ modelsPath: null, refreshOnCreate: false, allowModelNetwork: false });
    const gateway = new PiModelGateway(runtime);
    expect(() => gateway.resolve({ provider: "missing", id: "model" })).toThrow(/not found/);
    expect(Array.isArray(gateway.list())).toBe(true);
  });

  it("discovers resource metadata and loads one skill body on demand", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-resources-"));
    const skillDir = join(root, "skills", "reader");
    const { mkdir } = await import("node:fs/promises");
    await mkdir(skillDir, { recursive: true });
    await writeFile(join(skillDir, "SKILL.md"), "---\nname: reader\ndescription: Read sources\n---\nOnly cite checked evidence.\n", "utf8");
    const loader = await createPiResourceLoader({
      cwd: root,
      agentDir: join(root, "agent"),
      additionalSkillPaths: [join(root, "skills")],
      noExtensions: true,
      noContextFiles: true,
    });
    const snapshot = snapshotPiResources(loader);
    expect(snapshot.skills.map((skill) => skill.name)).toContain("reader");
    expect(await loadPiSkillBody(loader, "reader")).toContain("Only cite checked evidence");
  });

  it("does not load ambient resources unless explicitly opted in", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-resources-defaults-"));
    const skillDir = join(root, ".agents", "skills", "ambient");
    const { mkdir } = await import("node:fs/promises");
    await mkdir(skillDir, { recursive: true });
    await writeFile(join(skillDir, "SKILL.md"), "---\nname: ambient\ndescription: ambient\n---\n", "utf8");
    const loader = await createPiResourceLoader({ cwd: root, agentDir: join(root, "agent") });
    expect(loader.getSkills().skills.map((skill) => skill.name)).not.toContain("ambient");
  });

  it("opens an in-memory Pi session with explicit read-only tools", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-session-"));
    const runtime = await ModelRuntime.create({ modelsPath: null, refreshOnCreate: false, allowModelNetwork: false });
    const handle = await openPiSession({
      cwd: root,
      agentDir: join(root, "agent"),
      modelRuntime: runtime,
      noExtensions: true,
      noSkills: true,
      noContextFiles: true,
    });
    expect(handle.session.sessionId).toBeTruthy();
    expect(handle.session.getActiveToolNames()).toEqual(["read", "grep", "find", "ls"]);
    handle.dispose();
  });

  it("speaks strict JSONL RPC and executes a structured read-only worker", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-rpc-"));
    const script = await fakePiScript(root, true);
    const client = new PiRpcClient({ cwd: root, cliPath: script, agentDir: join(root, "agent") });
    await client.start();
    const events = await client.promptAndWait("inspect");
    expect(events.some((event) => event.type === "agent_settled")).toBe(true);
    await client.stop();

    const executor = createPiReadOnlyExecutor({ cwd: root, cliPath: script, agentDir: join(root, "agent") });
    const result = await executor({
      id: "task-1",
      role: "researcher",
      objective: "inspect",
      deps: [],
      ownedPaths: ["notes"],
      parallelSafe: true,
      inputs: [],
      outputs: [],
      completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
    }, {
      runId: "run-1",
      dispatchId: "dispatch-1",
      attempt: 1,
      task: {
        id: "task-1",
        role: "researcher",
        objective: "inspect",
        deps: [],
        ownedPaths: ["notes"],
        parallelSafe: true,
        inputs: [],
        outputs: [],
        completionContract: { requiredArtifacts: [], requiredReceiptEffects: [], mustPassGates: [] },
      },
      readOnly: true,
      signal: new AbortController().signal,
    });
    expect(result.report.outcome).toBe("succeeded");
  });
});
