import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { takeWhatsNew } from "../../src/updates/whats-new.js";

const NOTES = { "1.2.0": ["修复任务超时问题"] };

describe("what's new", () => {
  it("shows a version's notes once, then stays quiet until the next version", async () => {
    const state = join(await mkdtemp(join(tmpdir(), "psyclaw-whats-new-")), "nested", "whats-new.json");
    expect(await takeWhatsNew("1.2.0", state, NOTES)).toBe("PsyClaw 已更新到 v1.2.0：\n· 修复任务超时问题");
    expect(JSON.parse(await readFile(state, "utf8"))).toEqual({ lastSeenVersion: "1.2.0" });
    expect(await takeWhatsNew("1.2.0", state, NOTES)).toBeUndefined();
    expect(await takeWhatsNew("1.2.1", state, NOTES)).toBeUndefined();
    expect(JSON.parse(await readFile(state, "utf8"))).toEqual({ lastSeenVersion: "1.2.1" });
  });
});
