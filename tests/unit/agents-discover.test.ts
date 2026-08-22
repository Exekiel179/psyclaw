import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { discoverAgents } from "../../src/agents/discover.js";
import { KNOWN_AGENTS, type KnownAgent } from "../../src/agents/catalog.js";

const claude = KNOWN_AGENTS.find((agent) => agent.id === "claude-code") as KnownAgent;
const opencode = KNOWN_AGENTS.find((agent) => agent.id === "opencode") as KnownAgent;

describe("agent discovery", () => {
  it("recognizes configs, skills, and credentials without reading secrets", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-home-"));
    await mkdir(join(home, ".claude", "skills", "foo"), { recursive: true });
    await writeFile(join(home, ".claude", "skills", "foo", "SKILL.md"), "skill body", "utf8");
    await mkdir(join(home, ".claude", "commands"), { recursive: true });
    await writeFile(join(home, ".claude", "commands", "bar.md"), "# bar", "utf8");
    await writeFile(join(home, ".claude", ".credentials.json"), '{"token":"top-secret-value"}', "utf8");
    await mkdir(join(home, ".config", "opencode", "skills", "baz"), { recursive: true });

    const scans = await discoverAgents({ homeDir: home });
    const claudeScan = scans.find((scan) => scan.id === "claude-code")!;
    expect(claudeScan.found).toBe(true);
    expect(claudeScan.configPath).toBe(join(home, ".claude"));
    expect(claudeScan.skills.map((skill) => skill.name).sort()).toEqual(["bar", "foo"]);
    expect(claudeScan.hasCredentials).toBe(true);
    expect(claudeScan.credentialPaths).toEqual([join(home, ".claude", ".credentials.json")]);

    const opencodeScan = scans.find((scan) => scan.id === "opencode")!;
    expect(opencodeScan.found).toBe(true);
    expect(opencodeScan.skills.map((skill) => skill.name)).toEqual(["baz"]);

    // Credential contents must never leak into the scan.
    expect(JSON.stringify(scans)).not.toContain("top-secret-value");

    const aider = scans.find((scan) => scan.id === "aider")!;
    expect(aider.found).toBe(false);
  });

  it("treats a symlinked config directory as not found", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-home-sym-"));
    const real = await mkdtemp(join(tmpdir(), "psyclaw-real-"));
    const { symlink } = await import("node:fs/promises");
    await symlink(real, join(home, ".claude"), "junction");
    const scans = await discoverAgents({ homeDir: home });
    expect(scans.find((scan) => scan.id === "claude-code")?.found).toBe(false);
  });

  it("does not follow a symlinked ancestor of a catalog directory", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-home-ancestor-"));
    const outside = await mkdtemp(join(tmpdir(), "psyclaw-outside-ancestor-"));
    const { symlink } = await import("node:fs/promises");
    await mkdir(join(outside, ".claude", "skills", "escaped"), { recursive: true });
    await writeFile(join(outside, ".claude", "skills", "escaped", "SKILL.md"), "outside", "utf8");
    await symlink(outside, join(home, "linked-home"), "junction");
    const scans = await discoverAgents({
      homeDir: home,
      agents: [{
        ...claude,
        configDirs: ["linked-home/.claude"],
        skillDirs: ["linked-home/.claude/skills"],
        credentialFiles: ["linked-home/.claude/auth.json"],
      }],
    });
    expect(scans[0]?.found).toBe(false);
    expect(scans[0]?.skills).toEqual([]);
    expect(scans[0]?.hasCredentials).toBe(false);
  });

  it("rejects traversal in a caller-provided catalog", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-home-catalog-traversal-"));
    const scans = await discoverAgents({
      homeDir: home,
      agents: [{ ...claude, configDirs: ["../outside"], skillDirs: ["../outside/skills"], credentialFiles: ["../outside/auth"] }],
    });
    expect(scans[0]?.found).toBe(false);
    expect(scans[0]?.skills).toEqual([]);
    expect(scans[0]?.hasCredentials).toBe(false);
  });

  it("uses a restricted catalog when provided", async () => {
    const home = await mkdtemp(join(tmpdir(), "psyclaw-home-sub-"));
    await mkdir(join(home, ".claude"), { recursive: true });
    const scans = await discoverAgents({ homeDir: home, agents: [claude, opencode] });
    expect(scans).toHaveLength(2);
    expect(scans.map((scan) => scan.id)).toEqual(["claude-code", "opencode"]);
  });
});
