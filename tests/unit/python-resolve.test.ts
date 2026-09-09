import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("node:child_process", async () => {
  const actual = await vi.importActual<typeof import("node:child_process")>("node:child_process");
  return {
    ...actual,
    execFile: vi.fn(),
  };
});

import { execFile } from "node:child_process";
import { pythonCandidates, resetPythonCache, resolvePython } from "../../src/platform/python.js";

describe("python resolution", () => {
  afterEach(() => {
    resetPythonCache();
    vi.mocked(execFile).mockReset();
  });

  it("lists cross-platform candidates including the Windows launcher", () => {
    expect(pythonCandidates().map((item) => [item.command, ...item.prefixArgs].join(" "))).toEqual([
      "python3",
      "py -3",
      "python",
    ]);
  });

  it("falls back to py -3 when python3 is missing", async () => {
    vi.mocked(execFile).mockImplementation(((command: string, args: readonly string[], _opts: unknown, callback: (error: Error | null, stdout: string, stderr: string) => void) => {
      if (command === "python3") {
        callback(new Error("missing"), "", "");
        return {} as never;
      }
      if (command === "py" && args[0] === "-3" && args[1] === "--version") {
        callback(null, "Python 3.12.0\n", "");
        return {} as never;
      }
      callback(new Error(`unexpected ${command}`), "", "");
      return {} as never;
    }) as typeof execFile);

    await expect(resolvePython()).resolves.toEqual({ command: "py", prefixArgs: ["-3"] });
  });
});
