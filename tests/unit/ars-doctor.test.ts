import { describe, expect, it } from "vitest";
import { buildArsDoctorReport } from "../../src/ars/doctor.js";

describe("buildArsDoctorReport", () => {
  it("reports PsyClaw orchestration and hooks without probing Tectonic", async () => {
    const report = await buildArsDoctorReport({
      repositoryRoot: "/tmp/vendor/ars",
      activeTools: ["psyclaw_ars_multi_agent"],
      commands: ["agents", "create-subagent"],
      controlledRunActive: false,
    });
    expect(report).toContain("psyclaw_ars_multi_agent");
    expect(report).toContain("/agents");
    expect(report).toContain("PsyClaw analysis hooks");
    expect(report).toContain("不预检 Tectonic");
    expect(report).not.toContain("Tectonic:");
    expect(report).not.toContain("Claude hooks: unavailable");
    expect(report).not.toContain("降级模式");
  });
});
