import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { asManifest } from "../../src/trust/manifest.js";
import { auditLicenses, buildSbom, loadLockedPackages, sbomSummaryHash } from "../../src/trust/sbom.js";

const LOCKFILE = [
  "lockfileVersion: '9.0'",
  "packages:",
  "  typebox@1.3.7: {}",
  "  '@earendil-works/pi-coding-agent@0.84.1': {}",
  "  yaml@2.9.0: {}",
  "",
].join("\n");

describe("manifest schema", () => {
  const valid = {
    schemaVersion: "psyclaw/manifest/v1",
    id: "nature-reader",
    version: "0.1.0",
    source: { kind: "git", ref: "abc123", url: "https://example.test/x" },
    contentSha256: "a".repeat(64),
    license: { spdx: "MIT", evidenceRef: "LICENSE" },
    dependencies: [{ name: "yaml", version: "2.9.0", license: "ISC" }],
    capabilities: ["read"],
    trust: "discover-only",
  };

  it("accepts a valid admission manifest", () => {
    expect(asManifest(valid).id).toBe("nature-reader");
  });

  it("rejects unknown fields, wrong version, and malformed hashes", () => {
    expect(() => asManifest({ ...valid, extra: true })).toThrow(/schema invalid/);
    expect(() => asManifest({ ...valid, schemaVersion: "psyclaw/manifest/v2" })).toThrow(/schema invalid/);
    expect(() => asManifest({ ...valid, contentSha256: "not-a-sha" })).toThrow(/schema invalid/);
  });
});

describe("CycloneDX SBOM", () => {
  it("extracts locked packages from a pnpm lockfile", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-sbom-"));
    await writeFile(join(root, "pnpm-lock.yaml"), LOCKFILE, "utf8");
    const locked = await loadLockedPackages(root);
    expect(locked.map((item) => `${item.name}@${item.version}`)).toEqual([
      "@earendil-works/pi-coding-agent@0.84.1",
      "typebox@1.3.7",
      "yaml@2.9.0",
    ]);
  });

  it("builds a parseable CycloneDX 1.5 bom with a stable summary hash", () => {
    const bom = buildSbom({
      name: "psyclaw",
      version: "0.1.0",
      components: [{ name: "typebox", version: "1.3.7" }, { name: "yaml", version: "2.9.0" }],
      now: () => "2026-01-01T00:00:00.000Z",
    });
    expect(bom.bomFormat).toBe("CycloneDX");
    expect(bom.specVersion).toBe("1.5");
    expect(bom.metadata.component.name).toBe("psyclaw");
    expect(bom.components.map((item) => item.name)).toEqual(["typebox", "yaml"]);
    expect(sbomSummaryHash(bom)).toMatch(/^[a-f0-9]{64}$/);
  });

  it("never upgrades an unreadable or undeclared license to known", async () => {
    const root = await mkdtemp(join(tmpdir(), "psyclaw-sbom-"));
    await mkdir(join(root, "node_modules", "typebox"), { recursive: true });
    await writeFile(join(root, "node_modules", "typebox", "package.json"), JSON.stringify({ license: "MIT" }), "utf8");
    const audit = await auditLicenses(root, [
      { name: "typebox", version: "1.3.7" },
      { name: "yaml", version: "2.9.0" },
      { name: "@missing/pkg", version: "1.0.0" },
    ]);
    expect(audit.total).toBe(3);
    expect(audit.declared).toBe(1);
    expect(audit.unknown).toBe(2);
    expect(audit.summaryHash).toMatch(/^[a-f0-9]{64}$/);
  });
});
