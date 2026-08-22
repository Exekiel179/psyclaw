import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";

export interface SbomComponent {
  type: "library";
  name: string;
  version: string;
  purl?: string;
}

export interface CycloneDxBom {
  bomFormat: "CycloneDX";
  specVersion: "1.5";
  serialNumber: string;
  version: 1;
  metadata: {
    timestamp: string;
    component: { type: "application"; name: string; version: string };
  };
  components: SbomComponent[];
}

export interface SbomOptions {
  name: string;
  version: string;
  components: { name: string; version: string }[];
  now?: () => string;
}

/** Build a minimal, parseable CycloneDX 1.5 JSON SBOM from a component list. */
export function buildSbom(options: SbomOptions): CycloneDxBom {
  const components = options.components
    .map(({ name, version }) => ({
      type: "library" as const,
      name,
      version,
      purl: `pkg:npm/${name}@${version}`,
    }))
    .sort((left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version));
  return {
    bomFormat: "CycloneDX",
    specVersion: "1.5",
    serialNumber: `urn:uuid:${randomUUID()}`,
    version: 1,
    metadata: {
      timestamp: (options.now ?? (() => new Date().toISOString()))(),
      component: { type: "application", name: options.name, version: options.version },
    },
    components,
  };
}

/** Stable digest over the sorted component identity list. */
export function sbomSummaryHash(bom: CycloneDxBom): string {
  const canonical = JSON.stringify(bom.components.map((component) => [component.name, component.version]));
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

interface LockfileShape {
  packages?: Record<string, unknown>;
}

/** Extract the locked `name@version` entries from a pnpm lockfile. */
export async function loadLockedPackages(root: string): Promise<{ name: string; version: string }[]> {
  const lockText = await readFile(join(root, "pnpm-lock.yaml"), "utf8");
  const lock = parseYaml(lockText) as LockfileShape;
  const packages = lock.packages ?? {};
  const result: { name: string; version: string }[] = [];
  for (const key of Object.keys(packages)) {
    const at = key.lastIndexOf("@");
    if (at <= 0) continue;
    const name = key.slice(0, at);
    const version = key.slice(at + 1).split("(")[0] ?? "";
    if (name.length === 0 || version.length === 0) continue;
    result.push({ name, version });
  }
  return result.sort((left, right) => `${left.name}@${left.version}`.localeCompare(`${right.name}@${right.version}`));
}

export interface LicenseAudit {
  total: number;
  declared: number;
  unknown: number;
  summaryHash: string;
}

/**
 * Best-effort license audit over installed packages. A package whose
 * `package.json` is unreadable or whose `license` is not a non-empty string is
 * counted as `unknown`, never silently upgraded.
 */
export async function auditLicenses(
  root: string,
  components: readonly { name: string; version: string }[],
): Promise<LicenseAudit> {
  let declared = 0;
  let unknown = 0;
  for (const component of components) {
    try {
      const text = await readFile(join(root, "node_modules", component.name, "package.json"), "utf8");
      const manifest = JSON.parse(text) as { license?: unknown };
      if (typeof manifest.license === "string" && manifest.license.trim().length > 0) declared += 1;
      else unknown += 1;
    } catch {
      unknown += 1;
    }
  }
  const total = components.length;
  const summaryHash = createHash("sha256")
    .update(`${total}:${declared}:${unknown}`)
    .digest("hex");
  return { total, declared, unknown, summaryHash };
}
