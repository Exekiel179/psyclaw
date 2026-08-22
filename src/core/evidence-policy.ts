import type {
  Claim,
  ClaimEvidenceLink,
  Evidence,
  EvidenceLevel,
  EvidencePolicy,
  GateResult,
  ResearchParadigm,
} from "./contracts.js";

const LEVEL_RANK: Record<EvidenceLevel, number> = {
  metadata: 0,
  abstract: 1,
  snippet: 2,
  fulltext: 3,
  // User-provided material is an input to review, not independently
  // verified support. Keep it below every policy threshold by default.
  user: -1,
};

const DEFAULT_MINIMUM: Record<Claim["kind"], EvidenceLevel> = {
  existence: "metadata",
  definition: "abstract",
  method: "snippet",
  result: "fulltext",
  interpretation: "snippet",
};

export function defaultEvidencePolicy(
  paradigm: ResearchParadigm,
  claimKind: Claim["kind"],
): EvidencePolicy {
  return {
    paradigm,
    claimKind,
    minimumLevel: DEFAULT_MINIMUM[claimKind],
    locatorRequired: claimKind !== "existence",
    requiresIndependentSource: claimKind === "interpretation" || claimKind === "result",
    requiresArtifactRun: claimKind === "result",
  };
}

/**
 * The paradigm profile changes only the evidence thresholds and required
 * reporting, never the honesty/locator/source baseline. Qualitative and
 * ethnographic material is coded primary data: a theme does not need a second
 * independent source or a numeric artifact run, but it still needs a located,
 * non-user source. Absence of an effect size must not make a qualitative
 * finding invalid.
 */
export function policiesForParadigm(paradigm: ResearchParadigm): EvidencePolicy[] {
  const kinds: Claim["kind"][] = ["existence", "definition", "method", "result", "interpretation"];
  const policies = kinds.map((kind) => defaultEvidencePolicy(paradigm, kind));
  const policyFor = (kind: Claim["kind"]): EvidencePolicy => policies.find((item) => item.claimKind === kind)!;

  switch (paradigm) {
    case "qualitative-thematic":
    case "ethnographic":
      // Themes are coded primary data: a single located source suffices and no
      // numeric artifact run exists.
      policyFor("definition").requiresIndependentSource = false;
      policyFor("interpretation").requiresIndependentSource = false;
      policyFor("result").requiresIndependentSource = false;
      policyFor("result").requiresArtifactRun = false;
      break;
    case "historical-documentary":
    case "policy-legal":
      // Primary archives / statutes are themselves the source of truth.
      policyFor("result").requiresIndependentSource = false;
      policyFor("interpretation").requiresIndependentSource = false;
      policyFor("result").requiresArtifactRun = false;
      break;
    case "survey-observational":
      // Observational design keeps the interpretation independent-source gate
      // (overclaiming risk); no relaxation, so the baseline is left untouched.
      break;
    case "meta-analysis":
      // PRISMA-grade screening needs full text, not an abstract, for method
      // and pooled result claims.
      policyFor("method").minimumLevel = "fulltext";
      policyFor("result").minimumLevel = "fulltext";
      break;
    case "experimental":
    case "quasi-experimental":
    case "longitudinal-panel":
      // Confirmatory designs keep the strictest baseline: fulltext + two
      // independent sources + artifact run for results.
      break;
    case "mixed-methods":
      // Triangulation: interpretation already requires an independent source
      // under the baseline, so nothing is relaxed here.
      break;
  }
  return policies;
}

/** Required report sections per paradigm, beyond the universal honesty baseline. */
export const PARADIGM_REPORT_FIELDS: Record<ResearchParadigm, readonly string[]> = {
  "survey-observational": ["效应量与置信区间", "抽样方式与样本量", "缺失值处理", "共同方法偏差说明"],
  "qualitative-thematic": ["研究者立场与反身性", "编码轨迹与主题", "反例与负例", "主题饱和说明"],
  experimental: ["随机化与盲法", "主要结局预注册", "效应量与置信区间", "退出与流失", "违反方案说明"],
  "quasi-experimental": ["识别策略与混淆控制", "平行趋势或均衡性检验", "效应量与置信区间"],
  "longitudinal-panel": ["随访率与流失", "时变混杂处理", "缺失模式", "效应量与置信区间"],
  "meta-analysis": ["检索式与纳入排除标准", "PRISMA 流程", "异质性 I²/τ²", "发表偏倚", "效应量与置信区间"],
  ethnographic: ["田野与研究者立场", "参与者与研究关系", "三角验证", "伦理与匿名化"],
  "historical-documentary": ["史料来源与真伪", "年代与语境", "解读可复核"],
  "policy-legal": ["法条或判例出处", "管辖与时效", "解释立场"],
  "mixed-methods": ["定量与定性整合逻辑", "混合设计类型", "两部分各自的质量标准"],
};

function hasLocator(evidence: Evidence, policy: EvidencePolicy): boolean {
  if (evidence.level === "snippet") {
    if (!evidence.quote?.trim()) return false;
    if (!hasPreciseLocator(evidence, new Set(["page", "section", "offset"]))) return false;
    return true;
  }
  if (evidence.level === "fulltext") {
    if (!evidence.sha256 || !/^[a-f0-9]{64}$/i.test(evidence.sha256.trim())) return false;
    if (!hasPreciseLocator(evidence, new Set(["page", "section", "row"]))) return false;
    return true;
  }
  if (!policy.locatorRequired) return true;
  if (evidence.locators.length === 0) return false;
  return true;
}

function meetsLevel(evidence: Evidence, minimum: EvidenceLevel): boolean {
  // A user-supplied record must not become verified support merely because a
  // caller asks for a low minimum. A custom policy can still inspect it as an
  // input and mark the claim uncertain outside this default gate.
  if (evidence.level === "user" || evidence.source.kind === "user") return false;
  return evidence.accessStatus === "verified" && LEVEL_RANK[evidence.level] >= LEVEL_RANK[minimum];
}

type PreciseLocatorKind = "page" | "section" | "offset" | "row";

function hasPreciseLocator(evidence: Evidence, allowed: ReadonlySet<PreciseLocatorKind>): boolean {
  return evidence.locators.some(
    (locator) => allowed.has(locator.kind as PreciseLocatorKind) && locator.value.trim().length > 0,
  );
}

function normalizeDoi(value: string): string | undefined {
  let normalized = value.trim().toLowerCase();
  normalized = normalized.replace(/^(?:https?:\/\/)?(?:dx\.)?doi\.org\//, "");
  normalized = normalized.replace(/^doi:\s*/, "");
  normalized = normalized.replace(/[\s]+/g, "");
  normalized = normalized.replace(/[.,;:)}\]>]+$/, "");
  return normalized.startsWith("10.") && normalized.includes("/") ? normalized : undefined;
}

function sourceIdentityKeys(evidence: Evidence): string[] {
  const keys: string[] = [];
  const sha = evidence.sha256?.trim().toLowerCase();
  if (sha) keys.push(`sha256:${sha}`);

  const doi = normalizeDoi(evidence.source.locator);
  if (doi) keys.push(`doi:${doi}`);

  // A DOI can be embedded in a URL or a source label. This catches common
  // Crossref/publisher forms without treating arbitrary URLs as DOIs.
  if (!doi) {
    const embedded = evidence.source.locator.match(/10\.\d{4,9}\/[^\s"<>]+/i)?.[0];
    const embeddedDoi = embedded ? normalizeDoi(embedded) : undefined;
    if (embeddedDoi) keys.push(`doi:${embeddedDoi}`);
  }

  if (keys.length === 0) {
    const locator = evidence.source.locator.trim().replaceAll("\\", "/").toLowerCase();
    keys.push(`${evidence.source.kind}:${locator}`);
  }
  return keys;
}

function countIndependentSources(items: readonly Evidence[]): number {
  // Union evidence records when *any* stable identity agrees. This means two
  // PDF paths with the same SHA and two DOI spellings remain one source, even
  // if their other locators differ.
  const parent = new Map<string, string>();
  const find = (item: string): string => {
    const current = parent.get(item);
    if (!current) {
      parent.set(item, item);
      return item;
    }
    if (current === item) return item;
    const root = find(current);
    parent.set(item, root);
    return root;
  };
  const union = (left: string, right: string): void => {
    const leftRoot = find(left);
    const rightRoot = find(right);
    if (leftRoot !== rightRoot) parent.set(leftRoot, rightRoot);
  };

  for (const evidence of items) {
    const keys = sourceIdentityKeys(evidence);
    const first = keys[0];
    if (!first) continue;
    find(first);
    for (const key of keys.slice(1)) union(first, key);
  }
  const roots = new Set<string>();
  for (const evidence of items) {
    const first = sourceIdentityKeys(evidence)[0];
    if (first) roots.add(find(first));
  }
  return roots.size;
}

export interface EvidenceCheckContext {
  claims: readonly Claim[];
  evidence: readonly Evidence[];
  links: readonly ClaimEvidenceLink[];
  /** Explicit policies take precedence over the paradigm profile. */
  policies?: readonly EvidencePolicy[];
  /** Methodological paradigm; drives the profile when `policies` is absent. */
  paradigm?: ResearchParadigm;
  artifactRunClaimIds?: ReadonlySet<string>;
}

export function checkEvidenceSufficiency(ctx: EvidenceCheckContext): GateResult[] {
  const evidenceById = new Map(ctx.evidence.map((item) => [item.id, item]));
  const linksByClaim = new Map<string, ClaimEvidenceLink[]>();
  for (const link of ctx.links) {
    const bucket = linksByClaim.get(link.claimId) ?? [];
    bucket.push(link);
    linksByClaim.set(link.claimId, bucket);
  }

  const results: GateResult[] = [];
  const claimIds = new Set(ctx.claims.map((claim) => claim.id));
  const duplicateClaimIds = ctx.claims
    .map((claim) => claim.id)
    .filter((id, index, all) => all.indexOf(id) !== index);
  if (duplicateClaimIds.length > 0) {
    results.push({
      gateId: "ledger:duplicate-claim-ids",
      ok: false,
      severity: "block",
      reason: `账本包含重复 Claim ID: ${[...new Set(duplicateClaimIds)].join(", ")}`,
      claimIds: [...new Set(duplicateClaimIds)],
    });
  }

  for (const claim of ctx.claims) {
    const resolvedPolicies = ctx.policies ?? policiesForParadigm(ctx.paradigm ?? "survey-observational");
    const policy = resolvedPolicies.find(
      (candidate) => candidate.claimKind === claim.kind,
    ) ?? defaultEvidencePolicy("survey-observational", claim.kind);
    const links = linksByClaim.get(claim.id) ?? [];
    const supporting = links.filter((link) => link.relation === "supports");
    const contradictory = links.filter((link) => link.relation === "contradicts");
    const qualifying = supporting.filter((link) => {
      const evidence = evidenceById.get(link.evidenceId);
      return Boolean(evidence && meetsLevel(evidence, policy.minimumLevel) && hasLocator(evidence, policy));
    });

    const reasons: string[] = [];
    const declaredIds = new Set(claim.evidenceIds);
    const duplicateEvidenceIds = claim.evidenceIds.filter(
      (id, index, all) => all.indexOf(id) !== index,
    );
    if (duplicateEvidenceIds.length > 0) {
      reasons.push(`Claim.evidenceIds 包含重复 ID: ${[...new Set(duplicateEvidenceIds)].join(", ")}`);
    }
    const linkedIds = new Set(links.map((link) => link.evidenceId));
    const unlinkedDeclared = claim.evidenceIds.filter((id) => !linkedIds.has(id));
    if (unlinkedDeclared.length > 0) {
      reasons.push(`Claim 声明了未建立关系的 Evidence: ${[...new Set(unlinkedDeclared)].join(", ")}`);
    }
    const undeclaredLinked = [...linkedIds].filter((id) => !declaredIds.has(id));
    if (undeclaredLinked.length > 0) {
      reasons.push(`关系引用的 Evidence 未在 Claim.evidenceIds 声明: ${undeclaredLinked.join(", ")}`);
    }
    const duplicateLinks = links.filter((link, index, all) => {
      const key = `${link.evidenceId}\u0000${link.relation}`;
      return all.findIndex((candidate) => `${candidate.evidenceId}\u0000${candidate.relation}` === key) !== index;
    });
    if (duplicateLinks.length > 0) {
      reasons.push("同一 Claim 存在重复 Evidence 关系");
    }

    const missingEvidenceIds = [...new Set([
      ...claim.evidenceIds.filter((id) => !evidenceById.has(id)),
      ...links.map((link) => link.evidenceId).filter((id) => !evidenceById.has(id)),
    ])];
    if (missingEvidenceIds.length > 0) {
      reasons.push(`关系引用了不存在的 Evidence: ${missingEvidenceIds.join(", ")}`);
    }
    if (supporting.some((link) => evidenceById.get(link.evidenceId)?.accessStatus === "unavailable")) {
      reasons.push("支持关系引用了不可用来源");
    }
    if (supporting.some((link) => {
      const item = evidenceById.get(link.evidenceId);
      return item && item.accessStatus !== "verified";
    })) {
      reasons.push("支持关系引用了尚未核验的来源");
    }
    if (supporting.some((link) => {
      const item = evidenceById.get(link.evidenceId);
      return item?.level === "user" || item?.source.kind === "user";
    })) {
      reasons.push("用户提供的 Evidence 默认不能作为已验证支持");
    }
    if (qualifying.length === 0) reasons.push("没有达到当前 Claim 类型所需等级且可定位的支持证据");
    if (contradictory.length > 0) reasons.push("存在尚未处理的矛盾证据");
    const qualifyingEvidence = qualifying
      .map((link) => evidenceById.get(link.evidenceId))
      .filter((item): item is Evidence => item !== undefined);
    if (policy.requiresIndependentSource && countIndependentSources(qualifyingEvidence) < 2) {
      reasons.push("当前策略要求至少两个独立支持来源");
    }
    if (policy.requiresArtifactRun && !ctx.artifactRunClaimIds?.has(claim.id)) {
      reasons.push("结果型 Claim 缺少真实运行产物或结果哈希");
    }
    if (claim.status !== "supported" && qualifying.length > 0 && contradictory.length === 0) {
      reasons.push(`Claim 状态为 ${claim.status}，但已有满足策略的支持证据`);
    }

    results.push({
      gateId: `evidence:${claim.id}`,
      ok: reasons.length === 0,
      severity: reasons.length === 0 ? "warn" : "block",
      reason: reasons.length === 0 ? "证据关系满足当前 profile" : reasons.join("；"),
      claimIds: [claim.id],
      evidenceIds: links.map((link) => link.evidenceId),
    });
  }

  const orphanLinks = ctx.links.filter((link) => !claimIds.has(link.claimId));
  if (orphanLinks.length > 0) {
    results.push({
      gateId: "ledger:orphan-links",
      ok: false,
      severity: "block",
      reason: `Evidence 关系引用了不存在的 Claim: ${[...new Set(orphanLinks.map((link) => link.claimId))].join(", ")}`,
      claimIds: [...new Set(orphanLinks.map((link) => link.claimId))],
      evidenceIds: [...new Set(orphanLinks.map((link) => link.evidenceId))],
    });
  }
  return results;
}
