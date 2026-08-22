import { Type, type Static } from "typebox";
import { Compile } from "typebox/compile";

/**
 * Versioned admission manifest. Unknown fields are rejected, and every field
 * that matters for supply-chain trust (source ref, content hash, SPDX license,
 * dependency pins, SBOM reference) is required or explicitly validated.
 */
export const ManifestSchema = Type.Object({
  schemaVersion: Type.Literal("psyclaw/manifest/v1"),
  id: Type.String({ minLength: 1 }),
  version: Type.String({ minLength: 1 }),
  source: Type.Object({
    kind: Type.Union([Type.Literal("git"), Type.Literal("workspace"), Type.Literal("file")]),
    ref: Type.String({ minLength: 1 }),
    url: Type.Optional(Type.String({ minLength: 1 })),
  }, { additionalProperties: false }),
  contentSha256: Type.String({ pattern: "^[a-f0-9]{64}$" }),
  license: Type.Object({
    spdx: Type.String({ minLength: 1 }),
    evidenceRef: Type.Optional(Type.String({ minLength: 1 })),
  }, { additionalProperties: false }),
  dependencies: Type.Array(Type.Object({
    name: Type.String({ minLength: 1 }),
    version: Type.String({ minLength: 1 }),
    license: Type.Optional(Type.String({ minLength: 1 })),
    sha256: Type.Optional(Type.String({ pattern: "^[a-f0-9]{64}$" })),
  }, { additionalProperties: false })),
  sbom: Type.Optional(Type.Object({
    format: Type.Literal("CycloneDX"),
    specVersion: Type.Literal("1.5"),
    path: Type.String({ minLength: 1 }),
    sha256: Type.String({ pattern: "^[a-f0-9]{64}$" }),
  }, { additionalProperties: false })),
  capabilities: Type.Array(Type.String({ minLength: 1 })),
  trust: Type.Union([Type.Literal("discover-only"), Type.Literal("approved"), Type.Literal("blocked")]),
  contract: Type.Optional(Type.Object({
    inputSchema: Type.Optional(Type.String({ minLength: 1 })),
    outputSchema: Type.Optional(Type.String({ minLength: 1 })),
    fixtures: Type.Array(Type.String({ minLength: 1 })),
  }, { additionalProperties: false })),
}, { additionalProperties: false });

export type ManifestShape = Static<typeof ManifestSchema>;

const compiled = Compile(ManifestSchema);

export function asManifest(value: unknown): ManifestShape {
  if (!compiled.Check(value)) {
    const errors = [...compiled.Errors(value)].map((error) => {
      const path = "path" in error && typeof error.path === "string" ? error.path : "/";
      return `${path}: ${error.message}`;
    });
    throw new Error(`manifest schema invalid: ${errors.join("; ")}`);
  }
  return value as ManifestShape;
}
