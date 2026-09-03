import { checkEvidenceSufficiency } from "../core/evidence-policy.js";
import { loadLedger, readProject } from "../research/ledger.js";
import { allParadigms, finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";
import { allocateProjectVersion } from "../project/versions.js";
import { readManuscript } from "../project/manuscript.js";
import { checkCitations, listReferences } from "../core/references.js";

export const writingReviewSpec: WorkflowSpec = {
  id: "writing-review",
  version: "1.0.0",
  description: "Audit drafted claims against evidence, honesty, and causal-language rules.",
  paradigms: allParadigms,
  steps: [
    { id: "read", role: "verifier", effect: "read", description: "load claims and evidence" },
    { id: "check", role: "critic", effect: "read", description: "honesty and causal-language heuristics" },
    { id: "write", role: "writer", effect: "write", description: "write findings report" },
  ],
  requiredArtifacts: ["writing-review.md", "review-findings.json", "review-suggestions.json"],
};

export interface ReviewFinding {
  severity: "block" | "warn";
  rule: string;
  claimId?: string;
  message: string;
}

export interface ReviewSuggestion { severity: "block" | "warn"; rule: string; claimId?: string; suggestion: string; }

const CAUSAL_PATTERN = /\b(?:causes?|leads? to|determines?|increases?|decreases?|drives?|improves?)\b/i;
const CONFIRMATORY_PATTERN = /\b(?:proves?|proven|established)\b/i;
const INTERNAL_PROSE_PATTERN = /\b(?:Claim|Evidence|ledger|gate|receipt|verifier|blocked outcome)\b|证据账本|受阻结局|门禁阻断|质量审计/iu;

function abstractText(markdown: string): string {
  const match = markdown.match(/(?:^|\n)#{1,3}\s*(?:摘要|Abstract)\s*\n([\s\S]*?)(?=\n#{1,3}\s|$)/i);
  return match?.[1]?.trim() ?? "";
}

export async function runWritingReview(root: string): Promise<WorkflowResult> {
  const project = await readProject(root);
  const ledger = await loadLedger(root);
  const [manuscript, references] = await Promise.all([readManuscript(root), listReferences(root)]);
  const gates = checkEvidenceSufficiency({ ...ledger, paradigm: project.paradigm });
  const version = await allocateProjectVersion(root, "manuscript-revision", `writing-review:${Date.now()}`);
  const gateByClaim = new Map(gates.map((gate) => [gate.claimIds?.[0], gate]));

  const findings: ReviewFinding[] = [];
  for (const claim of ledger.claims) {
    const gate = gateByClaim.get(claim.id);
    if (claim.status === "supported" && gate && !gate.ok) {
      findings.push({
        severity: "block",
        rule: "unsupported-claim-asserted-as-supported",
        claimId: claim.id,
        message: "这项研究陈述目前缺少足够且可定位的来源支持；请补充材料，或缩小表述范围并说明不确定性。",
      });
    }
    if (claim.kind !== "result" && CAUSAL_PATTERN.test(claim.text)) {
      findings.push({
        severity: "warn",
        rule: "causal-language-without-result-artifact",
        claimId: claim.id,
        message: "当前研究设计不足以支持因果表述；请改写为关联性描述，或补充能够支持因果推断的设计与分析依据。",
      });
    }
    if (claim.kind === "result" && CONFIRMATORY_PATTERN.test(claim.text)) {
      findings.push({
        severity: "warn",
        rule: "confirmatory-language",
        claimId: claim.id,
        message: "这项结果被写成了已经证实的事实；请结合效应大小、不确定性和研究设计边界调整措辞。",
      });
    }
  }

  if (manuscript.exists && manuscript.markdown.trim()) {
    const citationCheck = checkCitations(manuscript.markdown, references);
    if (citationCheck.unmatched > 0) {
      findings.push({
        severity: "warn",
        rule: "in-text-reference-mismatch",
        message: `正文中有 ${citationCheck.unmatched} 组作者—年份引文未能与已核验的参考文献记录对应；请逐项核对作者、年份、DOI 和文末条目。`,
      });
    }
    if (INTERNAL_PROSE_PATTERN.test(manuscript.markdown)) {
      findings.push({
        severity: "warn",
        rule: "internal-workflow-language-in-manuscript",
        message: "正文含有系统内部校验术语；请按学科语境改写为研究陈述、证据来源、质量检查、结果指标、所需软件或无法分析等自然表达。",
      });
    }
    const abstract = abstractText(manuscript.markdown);
    if (/SHA-?256|文件哈希|(?:缺失|损坏).{0,20}(?:列|字段).{0,40}(?:[,，、;；].*){2,}/iu.test(abstract)) {
      findings.push({
        severity: "warn",
        rule: "abstract-implementation-detail",
        message: "摘要包含文件指纹或较细的字段级数据质量信息；请只保留总体数据质量及其对分析的影响，并把完整诊断移至方法或补充材料。",
      });
    }
  }

  const report = {
    schemaVersion: "psyclaw/writing-review/v1",
    version,
    findings,
    blockCount: findings.filter((finding) => finding.severity === "block").length,
    suggestions: findings.map((finding): ReviewSuggestion => ({ severity: finding.severity, rule: finding.rule, ...(finding.claimId ? { claimId: finding.claimId } : {}), suggestion: finding.message })),
  };

  const markdown = [
    `# 写作评审 ${version}`,
    "",
    `研究目标：${project.goal}`,
    "",
    "## 修改建议",
    "",
    ...(findings.length ? findings.map((finding) => `- ${finding.severity === "block" ? "需优先修改" : "建议修改"}：${finding.message}`) : ["- 暂未发现需要修改的问题。"]),
    "",
  ].join("\n");

  return finalizeWorkflow(root, writingReviewSpec, {
    gates,
    outputs: [
      { path: "writing-review.md", contents: markdown },
      { path: "review-findings.json", contents: `${JSON.stringify(report, null, 2)}\n` },
      { path: "review-suggestions.json", contents: `${JSON.stringify({ schemaVersion: "psyclaw/review-suggestions/v1", version, suggestions: report.suggestions }, null, 2)}\n` },
      { path: `writing-review-${version}.md`, contents: markdown },
      { path: `review-findings-${version}.json`, contents: `${JSON.stringify(report, null, 2)}\n` },
    ],
    completed: ["claims loaded", "honesty heuristics applied", "findings reported"],
  });
}
