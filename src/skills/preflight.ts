/**
 * Content preflight for skill bodies. This is a heuristic tripwire, not an OS
 * boundary: a body that instructs the agent to bypass gates or move data out
 * of the project is marked suspicious and the skill is never executable.
 */

export interface PreflightResult {
  suspicious: boolean;
  findings: string[];
}

interface SuspiciousPattern {
  name: string;
  source: string;
  flags: string;
}

const SUSPICIOUS_PATTERNS: readonly SuspiciousPattern[] = [
  {
    name: "bypass-gate",
    source: "\\b(?:bypass|circumvent|disable|skip|override|ignore|turn\\s+off)\\s+" +
      "(?:the\\s+)?(?:gate|integrity|verification|check|audit|policy|approval|allowlist)s?\\b",
    flags: "i",
  },
  {
    name: "exfiltrate-data",
    source: "\\b(?:upload|exfiltrate|send|transmit|forward|export)\\s+" +
      "(?:all|every|the|our)\\s+(?:files?|data|documents?|credentials|secrets|tokens)\\b",
    flags: "i",
  },
  {
    name: "collect-secrets",
    source: "\\b(?:read|collect|steal|harvest)\\s+" +
      "(?:credentials|secrets|tokens|api[ -]?keys|passwords|env(?:ironment)?)\\b",
    flags: "i",
  },
  {
    name: "disable-audit",
    source: "\\b(?:disable|suppress|turn\\s+off)\\s+(?:logging|audit(?:ing)?|tracing)\\b",
    flags: "i",
  },
];

export function preflightSkillBody(body: string): PreflightResult {
  const findings: string[] = [];
  for (const { name, source, flags } of SUSPICIOUS_PATTERNS) {
    if (new RegExp(source, flags).test(body)) findings.push(name);
  }
  return { suspicious: findings.length > 0, findings };
}
