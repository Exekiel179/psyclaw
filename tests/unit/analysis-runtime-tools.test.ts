import { mkdtemp, readFile, writeFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  profileDataset,
  readAnalysisResults,
  registerAnalysisRuntimeTools,
  runAnalysisEntrypoint,
  type CommandResult,
  type CommandRunner,
} from "../../src/analysis/runtime-tools.js";
import { sessionModePrompt } from "../../src/session/modes.js";

async function project(): Promise<string> {
  return mkdtemp(join(tmpdir(), "psyclaw-analysis-runtime-"));
}

function runner(result: CommandResult, calls: string[]): CommandRunner {
  return async (command, args) => {
    calls.push([command, ...args].join(" "));
    return result;
  };
}

describe("analysis runtime tools", () => {
  it("profiles a csv through the saved script and does not fit a model", async () => {
    const root = await project();
    await mkdir(join(root, "data"), { recursive: true });
    await writeFile(join(root, "data", "wave.csv"), "id,score\n1,2\n2,\n", "utf8");
    const calls: string[] = [];
    const text = await profileDataset(root, "data/wave.csv", {
      python: { command: "python3" },
      run: runner({
        exitCode: 0,
        stderr: "",
        stdout: JSON.stringify({ rows: 2, columns: [{ name: "id", missing: 0 }, { name: "score", missing: 1 }] }),
      }, calls),
    });
    expect(text).toContain("Rows: 2");
    expect(text).toContain("score: missing 1/2");
    expect(text).not.toMatch(/p =|regression|t-test/i);
    const script = await readFile(join(root, "analysis/scripts/psyclaw_profile_data.py"), "utf8");
    expect(script).toContain("csv");
    expect(script).not.toContain("pandas");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain("psyclaw_profile_data.py");
  });

  it("rejects a dataset path outside the project", async () => {
    const root = await project();
    await expect(profileDataset(root, "../wave.csv", { python: { command: "python3" }, run: async () => ({ stdout: "", stderr: "", exitCode: 0 }) })).rejects.toThrow(/escapes project root/);
  });

  it("runs an entrypoint once and reuses the saved output when scripts are unchanged", async () => {
    const root = await project();
    await mkdir(join(root, "analysis/scripts"), { recursive: true });
    await writeFile(join(root, "analysis/scripts/run_all.R"), "source('40.R')\n", "utf8");
    await writeFile(join(root, "analysis/scripts/40.R"), "cat(0.051)\n", "utf8");
    const calls: string[] = [];
    const run = runner({ exitCode: 0, stdout: "p = .010\n", stderr: "" }, calls);
    const first = await runAnalysisEntrypoint(root, { run });
    const second = await runAnalysisEntrypoint(root, { run });
    expect(first).toContain("Ran analysis/scripts/run_all.R");
    expect(first).toContain("p = .010");
    expect(second).toContain("Cached run");
    expect(calls).toEqual(["Rscript analysis/scripts/run_all.R"]);
  });

  it("reruns when a sourced script in the same tree changes", async () => {
    const root = await project();
    await mkdir(join(root, "analysis/scripts"), { recursive: true });
    await writeFile(join(root, "analysis/scripts/run_all.R"), "source('40.R')\n", "utf8");
    await writeFile(join(root, "analysis/scripts/40.R"), "cat(1)\n", "utf8");
    const calls: string[] = [];
    const run = runner({ exitCode: 0, stdout: "ok\n", stderr: "" }, calls);
    await runAnalysisEntrypoint(root, { run });
    await writeFile(join(root, "analysis/scripts/40.R"), "cat(2)\n", "utf8");
    const again = await runAnalysisEntrypoint(root, { run });
    expect(again).toContain("Ran analysis/scripts/run_all.R");
    expect(calls).toHaveLength(2);
  });

  it("previews the confirmatory table and leaves the rest of a long file unread", async () => {
    const root = await project();
    await mkdir(join(root, "results/tables"), { recursive: true });
    const lines = ["term,b", ...Array.from({ length: 50 }, (_, index) => `x${index},0.${index}`)];
    await writeFile(join(root, "results/tables/confirmatory_models.csv"), lines.join("\n"), "utf8");
    await writeFile(join(root, "results/tables/notes.md"), "not a model\n", "utf8");
    const text = await readAnalysisResults(root);
    expect(text).toContain("results/tables/confirmatory_models.csv");
    expect(text).toContain("term,b");
    expect(text).not.toContain("x49,0.49");
    expect(text).not.toContain("notes.md");
  });

  it("registers the three research execution tools and points analysis mode at them", () => {
    const names: string[] = [];
    registerAnalysisRuntimeTools({
      registerTool(definition: { name: string }) {
        names.push(definition.name);
      },
    } as ExtensionAPI);
    expect(names).toEqual(["psyclaw_data_profile", "psyclaw_run_analysis", "psyclaw_read_results", "psyclaw_recall_output"]);
    const prompt = sessionModePrompt("analysis");
    expect(prompt).toContain("psyclaw_data_profile");
    expect(prompt).toContain("psyclaw_run_analysis");
    expect(prompt).toContain("psyclaw_read_results");
    expect(prompt).toContain("Edit scripts with edit or write");
  });
});
