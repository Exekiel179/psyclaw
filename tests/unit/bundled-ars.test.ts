import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  ARS_ARCHIVE_SHA256,
  ARS_UPSTREAM_COMMIT,
  ARS_UPSTREAM_REF,
} from "../../src/ars/profile.js";

describe("bundled ARS package", () => {
  it("loads the locked wrapper, four skills, prompts, and license from the npm package manifest", async () => {
    const root = process.cwd();
    const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8")) as {
      pi: { extensions: string[]; skills: string[]; prompts: string[] };
    };
    expect(manifest.pi.extensions).toContain("./vendor/ars/pi/wrapper.js");
    expect(manifest.pi.skills.filter((path) => path.startsWith("./vendor/ars/"))).toHaveLength(4);
    expect(manifest.pi.prompts).toContain("./vendor/ars/commands");
    await expect(readFile(join(root, "vendor", "ars", "LICENSE"), "utf8")).resolves.toContain("Attribution-NonCommercial 4.0");
    await expect(readFile(join(root, "vendor", "ars", "pi", "wrapper.js"), "utf8")).resolves.toContain("Academic Research Skills compatibility for Pi");
    const source = JSON.parse(await readFile(join(root, "vendor", "ars", "PSYCLAW_SOURCE.json"), "utf8")) as {
      ref: string; commit: string; archiveSha256: string;
    };
    expect(source).toMatchObject({ ref: ARS_UPSTREAM_REF, commit: ARS_UPSTREAM_COMMIT, archiveSha256: ARS_ARCHIVE_SHA256 });
  });
});
