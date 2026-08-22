import type { Claim, ClaimEvidenceLink, Evidence } from "../core/contracts.js";

/**
 * Claim-centric literature context: for every claim, the sources that support,
 * contradict, or contextualize it, with their evidence level and locator. This
 * is the "文献脉络" view — where a claim came from and whether anything argues
 * against it.
 */
export interface ClaimLiteratureMap {
  schemaVersion: "psyclaw/literature-map/v1";
  generatedAt: string;
  claims: Array<{
    id: string;
    text: string;
    kind: Claim["kind"];
    status: Claim["status"];
    sources: Array<{
      relation: "supports" | "contradicts" | "context";
      evidenceId: string;
      title: string;
      locator?: string;
      level: Evidence["level"];
      sha256?: string;
    }>;
  }>;
}

export function buildClaimLiteratureMap(
  claims: readonly Claim[],
  evidence: readonly Evidence[],
  links: readonly ClaimEvidenceLink[],
  now = new Date().toISOString(),
): ClaimLiteratureMap {
  const evidenceById = new Map(evidence.map((item) => [item.id, item]));
  return {
    schemaVersion: "psyclaw/literature-map/v1",
    generatedAt: now,
    claims: claims.map((claim) => {
      const sources = links
        .filter((link) => link.claimId === claim.id)
        .map((link) => {
          const item = evidenceById.get(link.evidenceId);
          return {
            relation: link.relation,
            evidenceId: link.evidenceId,
            title: item?.source.title ?? item?.source.locator ?? link.evidenceId,
            ...(item?.source.locator === undefined ? {} : { locator: item.source.locator }),
            level: item?.level ?? ("metadata" as const),
            ...(item?.sha256 === undefined ? {} : { sha256: item.sha256 }),
          };
        })
        .sort((left, right) => {
          const order = { contradicts: 0, supports: 1, context: 2 } as const;
          return order[left.relation] - order[right.relation];
        });
      return {
        id: claim.id,
        text: claim.text,
        kind: claim.kind,
        status: claim.status,
        sources,
      };
    }),
  };
}
