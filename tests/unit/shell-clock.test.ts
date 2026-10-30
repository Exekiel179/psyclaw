import { describe, expect, it } from "vitest";
import { scriptInCommand, ShellClock } from "../../src/analysis/shell-timeout.js";

const MIN = 60_000;

function clockAt(start = 0) {
  let t = start;
  return { now: () => t, advance: (ms: number) => { t += ms; } };
}

describe("shell clock", () => {
  it("finds the script a command runs in full", () => {
    expect(scriptInCommand("cd /work && timeout 3000 Rscript results/analysis.R > /tmp/run3.log 2>&1")).toBe("results/analysis.R");
    expect(scriptInCommand("python3 -u results/analysis.py")).toBe("results/analysis.py");
    expect(scriptInCommand("Rscript -e 'summary(lm(y ~ x))'")).toBeUndefined();
  });

  it("stays quiet for single commands, however slow", () => {
    const c = clockAt();
    const clock = new ShellClock(c.now, undefined);
    clock.start("bash", "t1", "ls");
    c.advance(5_000);
    expect(clock.finish("t1")).toBeUndefined();
    clock.start("bash", "t3", "Rscript -e 'fit <- glmer(...)'");
    c.advance(9 * MIN);
    expect(clock.finish("t3")).toBeUndefined();
    clock.start("read", "t2", undefined);
    expect(clock.finish("t2")).toBeUndefined();
  });

  it("speaks up from the second slow full run of the same script", () => {
    const c = clockAt();
    const clock = new ShellClock(c.now, undefined);
    clock.start("bash", "t1", "Rscript results/analysis.R");
    c.advance(12 * MIN);
    expect(clock.finish("t1")).toBeUndefined();

    clock.start("bash", "t2", "cd /work && Rscript results/analysis.R > log 2>&1");
    c.advance(10 * MIN);
    const second = clock.finish("t2")!;
    expect(second).toContain("results/analysis.R has now run in full 2 times (22.0 min in total)");
    expect(second).toContain("rerun only the section you changed");
  });

  it("adds the remaining budget when one is set", () => {
    const c = clockAt();
    const clock = new ShellClock(c.now, 90);
    clock.start("bash", "t1", "Rscript fit.R");
    c.advance(20 * MIN);
    expect(clock.finish("t1")).toBeUndefined();
    clock.start("bash", "t2", "Rscript fit.R");
    c.advance(10 * MIN);
    expect(clock.finish("t2")).toContain("About 60 of 90 budget minutes remain.");
  });
});
