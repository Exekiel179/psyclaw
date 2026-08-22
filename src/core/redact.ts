/**
 * Deterministic secret redaction for log and projection surfaces.
 *
 * psyclaw never treats raw material or credentials as content to log. As
 * defense-in-depth, any free-form text that reaches an event log is scrubbed
 * of high-signal credential shapes before it is persisted. This is a
 * heuristic, not an OS boundary: callers must still avoid putting secrets in
 * log payloads in the first place.
 */

interface SecretKind {
  name: string;
  source: string;
  flags: string;
}

// Sources are kept separate from the RegExp objects so every invocation builds
// a fresh matcher and never shares the mutable `lastIndex` of a global regex.
const SECRET_KINDS: readonly SecretKind[] = [
  {
    name: "private-key",
    source: "-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----" +
      "[\\s\\S]*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    flags: "g",
  },
  { name: "aws-access-key", source: "\\bAKIA[0-9A-Z]{16}\\b", flags: "g" },
  { name: "google-api-key", source: "\\bAIza[0-9A-Za-z_-]{35}\\b", flags: "g" },
  { name: "openai-api-key", source: "\\bsk-[A-Za-z0-9_-]{20,}\\b", flags: "g" },
  { name: "github-token", source: "\\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\\b", flags: "g" },
  { name: "slack-token", source: "\\bxox[baprs]-[A-Za-z0-9-]{10,}\\b", flags: "g" },
  { name: "bearer-token", source: "\\bBearer\\s+[A-Za-z0-9._~+/-]{16,}\\b", flags: "gi" },
  {
    name: "credential-assignment",
    source: "\\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\\b" +
      "\\s*[:=]\\s*[\"']?[^\\s\"',;{}]+[\"']?",
    flags: "gi",
  },
];

export function redactSecrets(input: string): string {
  let output = input;
  for (const kind of SECRET_KINDS) {
    output = output.replace(new RegExp(kind.source, kind.flags), `[REDACTED:${kind.name}]`);
  }
  return output;
}

/** Return the distinct secret kinds detected in a string. */
export function findSecrets(input: string): string[] {
  const found: string[] = [];
  for (const kind of SECRET_KINDS) {
    if (new RegExp(kind.source, kind.flags).test(input)) found.push(kind.name);
  }
  return found;
}
