import { createHash } from "node:crypto";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ensureDefaultEcosystemFillers } from "../../src/workflows/ensure-default-fillers.js";
import {
  readRecommendationState,
  readRecommendedCatalog,
} from "../../src/skills/recommended.js";

const sha = (value: string): string => createHash("sha256").update(value).digest("hex");

async function managedFixture(root: string, id: string): Promise<void> {
  const catalog = await readRecommendedCatalog();
  const plan = catalog.installPrep.find((candidate) => candidate.id === id)!;
  const skillName = plan.skillName!;
  const directory = join(root, ".psyclaw", "imports", "recommended", skillName);
  const skill = `---\nname: ${skillName}\ndescription: Fixture\n---\n\n# Fixture\n`;
  const license = `${plan.license} fixture\n`;
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, "SKILL.md"), skill, "utf8");
  await writeFile(join(directory, "LICENSE"), license, "utf8");
  await writeFile(join(directory, "psyclaw-install.json"), `${JSON.stringify({
    schemaVersion: "psyclaw/recommended-skill-install/v1",
    id,
    skillName,
    source: { kind: "git", url: plan.sourceUrl, ref: plan.ref, path: plan.skillPath },
    license: { spdx: plan.license, evidence: "LICENSE", sha256: sha(license) },
    skillSha256: sha(skill),
    dependencies: plan.dependencies,
    installedAt: "2026-09-05T00:00:00.000Z",
  }, null, 2)}\n`, "utf8");
}

describe("ensureDefaultEcosystemFillers", () => {
  it("seeds recommendation state for default fillers without network when install=false", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-default-fillers-"));
    const result = await ensureDefaultEcosystemFillers(root, { install: false });
    expect(result.seeded).toEqual([
      "nature-figure",
      "nature-ref-verifier",
      "nature-polishing",
      "academic-paper-strategist",
      "academic-paper-composer",
    ]);
    expect(result.installed).toEqual([]);
    const state = await readRecommendationState(root);
    expect(state.skills).toEqual([...result.seeded].sort());
    for (const id of result.seeded) {
      expect(state.skillScopes?.[id]).toBe("project");
    }
  });

  it("treats already-valid managed installs as present", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-default-fillers-"));
    await managedFixture(root, "nature-figure");
    await managedFixture(root, "academic-paper-composer");
    const result = await ensureDefaultEcosystemFillers(root, {
      install: false,
      ids: ["nature-figure", "academic-paper-composer"],
    });
    expect(result.alreadyPresent.sort()).toEqual(["academic-paper-composer", "nature-figure"]);
    expect(result.failed).toEqual([]);
    const state = await readRecommendationState(root);
    expect(state.skills).toEqual(["academic-paper-composer", "nature-figure"]);
  });
});
