import { describe, expect, it } from "vitest";
import { createServer } from "node:http";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createPanelServer } from "../../src/panel/server.js";
import { PanelHub, extractAssistantText, extractAssistantDelta } from "../../src/panel/hub.js";
import { buildWakePrompt, formatWakeResult, labelsFor } from "../../src/wake-options/runtime.js";

describe("panel hub + wake-options", () => {
  it("extracts assistant text and deltas", () => {
    expect(extractAssistantText({ role: "assistant", content: [{ type: "text", text: "你好" }] })).toBe("你好");
    expect(extractAssistantText({ role: "user", content: "x" })).toBe("");
    expect(extractAssistantDelta({ type: "text_delta", delta: "哈" })).toBe("哈");
  });

  it("builds wake prompts and formats results", () => {
    const prompt = buildWakePrompt({
      title: "下一步",
      mode: "choice",
      options: [
        { id: "a", label: "继续分析" },
        { id: "b", label: "写论文" },
      ],
    });
    expect(prompt.id.startsWith("wake_")).toBe(true);
    expect(prompt.options).toHaveLength(2);
    expect(labelsFor(prompt, ["b"])).toEqual(["写论文"]);
    expect(formatWakeResult({
      status: "answered",
      source: "panel",
      selectedIds: ["a"],
      selectedLabels: ["继续分析"],
      panelClients: 1,
    })).toContain("psyclaw/wake-options-result/v1");
  });

  it("serves SSE and resolves wake-options from Panel", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-wake-"));
    const htmlPath = join(root, "panel.html");
    await writeFile(htmlPath, "<!DOCTYPE html><title>panel</title>", "utf8");
    const hub = new PanelHub();
    const server = createPanelServer(root, { panelHtmlPath: htmlPath, hub });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    const base = `http://127.0.0.1:${port}`;

    try {
      const streamRes = await fetch(`${base}/api/assistant/stream`);
      expect(streamRes.status).toBe(200);
      expect(streamRes.headers.get("content-type")).toContain("text/event-stream");
      // Read first chunk then cancel so the test does not hang on the open SSE body.
      const reader = streamRes.body?.getReader();
      const first = reader ? await reader.read() : { done: true, value: undefined };
      expect(first.done).toBe(false);
      await reader?.cancel();

      const prompt = buildWakePrompt({
        title: "核对",
        mode: "checklist",
        options: [{ id: "n", label: "样本量" }, { id: "effect", label: "主效应" }],
        timeoutMs: 5_000,
      });
      const wait = hub.publishWake(prompt, 5_000);
      // Allow subscribe bookkeeping after stream open.
      await new Promise((r) => setTimeout(r, 20));

      const respond = await fetch(`${base}/api/wake-options/respond`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ promptId: prompt.id, selectedIds: ["n", "effect"] }),
      });
      expect(respond.status).toBe(200);
      const answer = await wait;
      expect(answer.source).toBe("panel");
      expect(answer.selectedIds).toEqual(["n", "effect"]);

      // crosscheck POST is allowlisted
      const cross = await fetch(`${base}/api/crosscheck`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: "n", status: "verified" }),
      });
      expect(cross.status).toBe(200);
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
