import { readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { appendEvidence, readProject } from "../research/ledger.js";
import { assertSafeProjectPath } from "../project/paths.js";
import { crossCheckMetadata, detectFulltext, sha256Bytes } from "../literature/metadata.js";
import type { InstitutionalRequestPlan, LiteratureRequestMode, MetadataCandidate, VerifiedFulltextRecord } from "../literature/contracts.js";
import { allParadigms, finalizeWorkflow, type WorkflowResult, type WorkflowSpec } from "./spec.js";

export const institutionalFulltextSpec: WorkflowSpec = {
  id: "institutional-fulltext",
  version: "1.0.0",
  description: "Prepare an auditable, human-approved browser workflow for retrieving institutionally authorized full text.",
  paradigms: allParadigms,
  steps: [
    { id: "identify", role: "researcher", effect: "read", description: "normalize the DOI, publisher URL, or title supplied by the researcher" },
    { id: "browse", role: "researcher", effect: "read", description: "use the user's already authenticated browser session" },
    { id: "approve-download", role: "verifier", effect: "write", description: "ask for confirmation before downloading a licensed full text" },
    { id: "validate", role: "verifier", effect: "read", description: "verify PDF signature, title/DOI, size, and SHA-256" },
    { id: "ledger", role: "writer", effect: "write", description: "import the verified local PDF as evidence" },
  ],
  requiredArtifacts: ["institutional-fulltext-plan.json", "institutional-fulltext-plan.md"],
};

export async function runInstitutionalFulltext(root: string, identifier = ""): Promise<WorkflowResult> {
  const project = await readProject(root);
  const target = identifier.trim() || project.goal;
  const isUrl = /^https?:\/\//i.test(target);
  const isDoi = /^10\.\d{4,9}\//i.test(target);
  const plan = {
    schemaVersion: "psyclaw/institutional-fulltext-plan/v1",
    documentVersion: "1.0.0",
    target: { value: target, kind: isUrl ? "publisher-url" : isDoi ? "doi" : "title-or-query" },
    bridge: {
      adapter: "playwright-mcp",
      mode: "existing-chrome-tab",
      credentialPolicy: "user-authenticated-session-only",
      network: "publisher-domain-only",
    },
    steps: [
      { id: "identify", action: "resolve DOI/title and verify publisher page" },
      { id: "authenticate", action: "user completes institutional login, VPN, or proxy in the visible browser" },
      { id: "confirm", action: "human confirms the exact article and download action" },
      { id: "download", action: "save PDF under data/clean or an approved evidence staging path" },
      { id: "validate", action: "check PDF magic bytes, non-HTML content, title/DOI match, size, and SHA-256" },
      { id: "record", action: "import verified file with psyclaw evidence add and retain source receipt" },
    ],
    stopConditions: [
      "login page, CAPTCHA, or access denied",
      "publisher page does not match the requested work",
      "download is HTML, truncated, or hash changes",
      "the action would bypass access controls or violate the user's authorization",
    ],
    approval: { requiredBefore: ["download", "record"], actor: "human", status: "pending" },
  };
  const markdown = [
    "# Institutional Full Text Plan",
    "",
    `Target: ${target}`,
    `Bridge: ${plan.bridge.adapter} (${plan.bridge.mode})`,
    "",
    "## Human Gate",
    "",
    "The user must complete institutional authentication in the visible browser and confirm the exact article before download.",
    "",
    "## Steps",
    "",
    ...plan.steps.map((step, index) => `${index + 1}. **${step.id}** — ${step.action}`),
    "",
    "## Stop Conditions",
    "",
    ...plan.stopConditions.map((item) => `- ${item}`),
    "",
    "## Next Action",
    "",
    "Open the plan in the workbench, connect the approved browser bridge, and request human confirmation before the download step.",
    "",
  ].join("\n");
  return finalizeWorkflow(root, institutionalFulltextSpec, {
    gates: [{ gateId: "institutional-fulltext:human-approval", ok: false, severity: "block", reason: "human must confirm the authenticated article and download" }],
    outputs: [
      { path: "institutional-fulltext-plan.json", contents: `${JSON.stringify(plan, null, 2)}\n` },
      { path: "institutional-fulltext-plan.md", contents: markdown },
    ],
    completed: ["target normalized", "browser bridge and validation plan prepared"],
  });
}

export async function recordVerifiedInstitutionalFulltext(root: string, options: { path: string; expected: MetadataCandidate; observed: MetadataCandidate; approved: boolean; retrievedAt?: string }): Promise<VerifiedFulltextRecord> {
  if (!options.approved) throw new Error("human approval is required before ledger record");
  const safe = await assertSafeProjectPath(root, options.path);
  const bytes = await readFile(safe); const contentType = detectFulltext(bytes);
  if (contentType === "unknown") throw new Error("full text is neither PDF nor HTML");
  const crossCheck = crossCheckMetadata(options.expected, options.observed);
  if (!crossCheck.match) throw new Error(`metadata cross-check failed: ${crossCheck.reasons.join("; ")}`);
  const hash = sha256Bytes(bytes);
  const evidence = { id: `institutional:${hash.slice(0, 16)}`, source: { kind: "file" as const, locator: resolve(root, options.path), title: options.observed.title ?? basename(options.path) }, level: "fulltext" as const, retrievedAt: options.retrievedAt ?? new Date().toISOString(), sha256: hash, accessStatus: "verified" as const, locators: [{ kind: "file" as const, value: options.path }, ...(crossCheck.normalizedDoi ? [{ kind: "doi" as const, value: crossCheck.normalizedDoi }] : [])] };
  await appendEvidence(root, evidence);
  return { evidence, crossCheck, contentType, sha256: hash, approval: "approved" };
}

export function makeInstitutionalRequestPlan(target: string, options: { mode?: LiteratureRequestMode; apiUrl?: string; allowedDomains?: string[] } = {}): InstitutionalRequestPlan {
  const value = target.trim(); const doi = /^10\.\d{4,9}\//i.test(value); const url = /^https?:\/\//i.test(value); const mode = options.mode ?? "browser";
  const plan: InstitutionalRequestPlan = { schemaVersion: "psyclaw/institutional-request-plan/v1", mode, target: { value, kind: url ? "publisher-url" : doi ? "doi" : "title-or-query" }, allowedDomains: options.allowedDomains ?? [], approval: { required: true, before: ["network", "download", "ledger-record"], status: "pending" }, stopConditions: ["authentication, CAPTCHA, or access denied", "domain is not allowlisted", "request would bypass access controls", "response is HTML login page or metadata does not match"] };
  if (mode === "api") plan.api = { method: "GET", url: options.apiUrl ?? value, headers: { Accept: "application/pdf, text/html, application/json" }, response: "pdf-or-html" };
  return plan;
}
