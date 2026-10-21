import { describe, expect, it } from "vitest";
import {
  classifyIrreversibleHostCommand,
  extractToolCommandText,
  irreversibleHostBlockReason,
} from "../../src/safety/irreversible-host-ops.js";

describe("irreversible host ops", () => {
  it("hard-blocks wsl --unregister (feedback: wiped bash host)", () => {
    const match = classifyIrreversibleHostCommand("wsl --unregister Ubuntu");
    expect(match?.id).toBe("wsl-unregister");
    expect(irreversibleHostBlockReason(match!)).toContain("不可逆主机操作");
    expect(irreversibleHostBlockReason(match!)).toContain("备份");
  });

  it("hard-blocks wsl.exe and PowerShell unregister forms", () => {
    expect(classifyIrreversibleHostCommand("wsl.exe --unregister Ubuntu")?.id).toBe("wsl-unregister");
    expect(classifyIrreversibleHostCommand("Unregister-WslDistribution -Name Ubuntu")?.id).toBe(
      "powershell-wsl-unregister",
    );
  });

  it("hard-blocks root/home rm -rf and disk format", () => {
    expect(classifyIrreversibleHostCommand("rm -rf /")?.id).toBe("rm-root-or-home");
    expect(classifyIrreversibleHostCommand("rm -rf $HOME")?.id).toBe("rm-root-or-home");
    expect(classifyIrreversibleHostCommand("format c:")?.id).toBe("disk-format");
  });

  it("allows ordinary research / cleanup listing commands", () => {
    expect(classifyIrreversibleHostCommand("wsl -l -v")).toBeUndefined();
    expect(classifyIrreversibleHostCommand("du -sh /mnt/c/*")).toBeUndefined();
    expect(classifyIrreversibleHostCommand("rm -rf ./analysis/tmp")).toBeUndefined();
    expect(classifyIrreversibleHostCommand("npm cache clean --force")).toBeUndefined();
  });

  it("extracts command text from bash tool payloads", () => {
    expect(extractToolCommandText("bash", { command: "wsl --unregister Ubuntu" })).toBe(
      "wsl --unregister Ubuntu",
    );
    expect(extractToolCommandText("write", { path: "a.txt", content: "x" })).toBeUndefined();
  });
});
