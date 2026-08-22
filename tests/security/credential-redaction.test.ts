import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { findSecrets, redactSecrets } from "../../src/core/redact.js";
import { RunEventLog } from "../../src/panel/events.js";

describe("secret redaction", () => {
  it("redacts known credential shapes", () => {
    const input = [
      "key=sk-abcdefghijklmnopqrstuvwx",
      "token ghp_0123456789abcdefghijklmnopqrstuv",
      "aws AKIAIOSFODNN7EXAMPLE",
      "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
      "password: hunter2",
      "-----BEGIN PRIVATE KEY----- abc -----END PRIVATE KEY-----",
    ].join("\n");
    const output = redactSecrets(input);
    expect(output).not.toContain("sk-abcdefghijklmnopqrstuvwx");
    expect(output).not.toContain("ghp_");
    expect(output).not.toContain("AKIAIOSFODNN7EXAMPLE");
    expect(output).not.toContain("hunter2");
    expect(output).not.toContain("PRIVATE KEY----- abc");
    expect(output).toContain("[REDACTED:openai-api-key]");
    expect(output).toContain("[REDACTED:github-token]");
    expect(output).toContain("[REDACTED:credential-assignment]");
  });

  it("reports the distinct secret kinds it detects", () => {
    const kinds = findSecrets("key=sk-abcdefghijklmnopqrstuvwx and token=abc123");
    expect(kinds).toContain("openai-api-key");
    expect(kinds).toContain("credential-assignment");
  });

  it("scrubs credentials from the run event log before persistence", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-redact-"));
    const log = new RunEventLog(root, "run-redact");
    await log.append({
      type: "started",
      at: "2026-01-01T00:00:00.000Z",
      message: "agent returned key=sk-abcdefghijklmnopqrstuvwx",
    });
    const [event] = await log.snapshot();
    expect(event?.message).toBe("agent returned key=[REDACTED:openai-api-key]");
    expect(JSON.stringify(await log.snapshot())).not.toContain("sk-abcdefghijklmnopqrstuvwx");
  });
});
