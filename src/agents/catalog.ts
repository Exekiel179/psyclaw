export type InstallMethod = "npm" | "brew" | "pipx" | "curl-script" | "native";

export interface AgentInstallSpec {
  method: InstallMethod;
  /** Command run by the installer after explicit approval. */
  installCommand: string;
  /** Canonical source reference recorded in the install receipt. */
  sourceRef: string;
  /**
   * Pinned version/ref. The literal `unpinned` is never treated as a verified
   * install; pin a real version/tag before any release claim.
   */
  ref: string;
}

export interface KnownAgent {
  id: string;
  name: string;
  /** Config directories relative to the home directory, first match wins. */
  configDirs: readonly string[];
  /** Skill/command directories relative to the home directory. */
  skillDirs: readonly string[];
  /** Credential files whose existence is noted but whose content is never read. */
  credentialFiles: readonly string[];
  install?: AgentInstallSpec;
}

/**
 * A curated, editable catalog of agents psyclaw can recognize. Discovery is
 * strictly read-only and never executes these install commands; the installer
 * is a separate, approval-gated step.
 */
export const KNOWN_AGENTS: readonly KnownAgent[] = [
  {
    id: "claude-code",
    name: "Claude Code",
    configDirs: [".claude", ".config/claude"],
    skillDirs: [".claude/skills", ".claude/commands", ".config/claude/skills"],
    credentialFiles: [".claude/.credentials.json", ".claude/settings.json"],
    install: {
      method: "npm",
      installCommand: "npm install -g @anthropic-ai/claude-code@2.1.232",
      sourceRef: "https://github.com/anthropics/claude-code",
      ref: "2.1.232",
    },
  },
  {
    id: "openai-codex",
    name: "OpenAI Codex",
    configDirs: [".codex", ".config/codex"],
    skillDirs: [".codex/skills", ".config/codex/skills"],
    credentialFiles: [".codex/auth.json", ".codex/config.toml"],
    install: {
      method: "npm",
      installCommand: "npm install -g @openai/codex@0.147.0",
      sourceRef: "https://github.com/openai/codex",
      ref: "0.147.0",
    },
  },
  {
    id: "gemini-cli",
    name: "Gemini CLI",
    configDirs: [".gemini", ".config/gemini"],
    skillDirs: [".gemini/skills", ".config/gemini/skills"],
    credentialFiles: [".gemini/settings.json", ".config/gemini/settings.json"],
    install: {
      method: "npm",
      installCommand: "npm install -g @google/gemini-cli@0.55.1",
      sourceRef: "https://github.com/google-gemini/gemini-cli",
      ref: "0.55.1",
    },
  },
  {
    id: "opencode",
    name: "opencode",
    configDirs: [".config/opencode", ".opencode"],
    skillDirs: [".config/opencode/skills", ".opencode/skills"],
    credentialFiles: [".config/opencode/auth.json"],
    install: {
      method: "npm",
      installCommand: "npm install -g opencode-ai@1.18.18",
      sourceRef: "https://github.com/sst/opencode",
      ref: "1.18.18",
    },
  },
  {
    id: "aider",
    name: "Aider",
    configDirs: [".aider"],
    skillDirs: [],
    credentialFiles: [".aider.conf.yml"],
    install: {
      method: "pipx",
      installCommand: "pipx install aider-chat==0.16.0",
      sourceRef: "https://github.com/Aider-AI/aider",
      ref: "0.16.0",
    },
  },
  {
    id: "cursor",
    name: "Cursor",
    configDirs: [".cursor"],
    skillDirs: [".cursor/skills"],
    credentialFiles: [".cursor/auth.json"],
    install: { method: "native", installCommand: "", sourceRef: "https://cursor.com", ref: "manual" },
  },
  {
    id: "windsurf",
    name: "Windsurf",
    configDirs: [".windsurf", ".config/windsurf"],
    skillDirs: [".windsurf/skills"],
    credentialFiles: [],
    install: { method: "native", installCommand: "", sourceRef: "https://windsurf.com", ref: "manual" },
  },
  {
    id: "continue",
    name: "Continue",
    configDirs: [".continue"],
    skillDirs: [".continue/skills"],
    credentialFiles: [".continue/config.json"],
    install: { method: "native", installCommand: "", sourceRef: "https://continue.dev", ref: "manual" },
  },
  {
    id: "orca",
    name: "Orca",
    configDirs: [".orca", "orca"],
    skillDirs: [".orca/skills", "orca/workspaces"],
    credentialFiles: [".orca/config.json"],
    install: { method: "native", installCommand: "", sourceRef: "https://github.com/evanw/orca", ref: "manual" },
  },
  {
    id: "copilot-cli",
    name: "GitHub Copilot CLI",
    configDirs: [".config/github-copilot"],
    skillDirs: [".config/github-copilot/skills"],
    credentialFiles: [".config/github-copilot/hosts.json"],
    install: {
      method: "npm",
      installCommand: "npm install -g @github/copilot@1.0.80",
      sourceRef: "https://github.com/github/copilot-cli",
      ref: "1.0.80",
    },
  },
];
