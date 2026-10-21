import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  acknowledgeBundledPiChangelog,
  ensurePsyClawTheme,
  ensureQuietStartup,
  PSYCLAW_IDENTITY_PROMPT,
} from "./branding.js";
import { ensureAcademicModeKeybindings } from "./ars/keybindings.js";
import { resolvePsyClawManifest } from "./updates/manifest.js";
import { maybeShowTelemetryNotice } from "./observability/index.js";
import { PROVIDER_PRESETS, readMacOsLaunchctlCredential } from "./setup.js";
import { withBundledWindowsTools } from "./bundled-tools.js";
import {
  CONTINUOUSLY_WORK_ENV,
  continuouslyWorkPrompt,
  continuouslyWorkWarningText,
} from "./session/continuously-work.js";
import { c } from "./style/cli-ui.js";

/** Convert a filesystem path to a Node `--import` specifier (file:// on all platforms). */
export function toImportSpecifier(modulePath: string): string {
  return pathToFileURL(modulePath).href;
}

/** Package root of the installed psyclaw package (dist/src/chat.js -> root). */
export function packageRoot(): string {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "..");
}

/** Resolve the bundled Pi CLI shipped as a dependency of psyclaw. */
export function resolvePiCli(): string {
  try {
    // The Pi package is ESM-only (its `exports` map has only an `import`
    // condition), so we resolve through `import.meta.resolve` rather than a
    // CommonJS require. The CLI (`dist/cli.js`) sits beside `dist/index.js`.
    const entryUrl = import.meta.resolve("@earendil-works/pi-coding-agent");
    return join(dirname(fileURLToPath(entryUrl)), "cli.js");
  } catch {
    throw new Error(
      "Cannot locate the bundled PsyClaw runtime. Run `pnpm install` or `npm install` first.",
    );
  }
}

async function applyRuntimeBranding(root: string): Promise<void> {
  const script = join(root, "scripts", "rebrand-pi.mjs");
  const exitCode = await new Promise<number>((resolve) => {
    const child = spawn(process.execPath, [script], {
      cwd: root,
      stdio: "ignore",
      shell: false,
    });
    child.on("error", () => resolve(1));
    child.on("close", (code) => resolve(code ?? 1));
  });
  if (exitCode !== 0) {
    throw new Error("Unable to prepare the bundled PsyClaw runtime. Reinstall psyclaw or run `psyclaw rebrand` from its package directory.");
  }
}

export const FULL_AGENT_TOOLS =
  "read,grep,find,ls,edit,write,bash,psyclaw_skill,psyclaw_workbench,psyclaw_mcp" as const;
export const READ_ONLY_AGENT_TOOLS = "read,grep,find,ls,psyclaw_skill,psyclaw_workbench,psyclaw_mcp" as const;

export interface AgentLaunchPrepareOptions {
  cwd?: string;
  extensionPath?: string;
  skillsPath?: string;
  continuouslyWork?: boolean;
  /** Restrict built-in mutating tools (eval safety cases). Default: full tools. */
  readOnly?: boolean;
  /** Show telemetry notice / branding side effects. Default true for interactive. */
  quietPrep?: boolean;
}

export interface PreparedAgentLaunch {
  piCli: string;
  cwd: string;
  root: string;
  agentDir: string;
  sessionDir: string;
  networkPreloadPath: string;
  /** Pi argv without trailing user messages / print flags. */
  baseArgs: string[];
  spawnEnv: NodeJS.ProcessEnv;
  identityPrompt: string;
  nodeArgvPrefix: string[];
}

/**
 * Shared runtime prep for interactive chat and headless `--print` eval runs.
 * Loads PsyClaw extensions, core skills, identity prompt, and provider env.
 */
export async function prepareAgentLaunch(options: AgentLaunchPrepareOptions = {}): Promise<PreparedAgentLaunch> {
  const piCli = resolvePiCli();
  const root = packageRoot();
  const networkPreloadPath = join(root, "dist", "src", "network-routing.js");
  const extensionPath = options.extensionPath ?? join(root, "dist", "src", "extension.js");
  const panelExtensionPath = join(root, "dist", "src", "panel", "extension.js");
  const skillsPath = options.skillsPath ?? join(root, "skills", "core");
  const cwd = options.cwd ?? process.cwd();
  await applyRuntimeBranding(root);

  const continuouslyWork = options.continuouslyWork === true;
  const toolAllowlist = options.readOnly === true ? READ_ONLY_AGENT_TOOLS : FULL_AGENT_TOOLS;
  let identityPrompt = PSYCLAW_IDENTITY_PROMPT;
  try {
    const supplement = (await readFile(join(cwd, ".psyclaw", "system-prompt.md"), "utf8")).trim();
    if (supplement) identityPrompt = `${identityPrompt}\n\n${supplement}`;
  } catch { /* no user supplement */ }
  if (continuouslyWork) {
    identityPrompt = `${identityPrompt}\n\n${continuouslyWorkPrompt()}`;
  }

  const baseArgs = [
    // Disable Pi's ambient Skill scan. PsyClaw's resources_discover handler
    // adds only existing, deduplicated Skill paths after core Skills.
    "--no-skills",
    "--extension", extensionPath,
    "--extension", panelExtensionPath,
    "--skill", skillsPath,
    "--tools", toolAllowlist,
    ...systemPromptLaunchArgs(identityPrompt),
  ];

  const quietPrep = options.quietPrep === true;
  const manifest = await resolvePsyClawManifest();
  if (!quietPrep) {
    await ensureQuietStartup();
    await ensurePsyClawTheme();
    await maybeShowTelemetryNotice();
    if (manifest?.piVersion !== undefined) {
      await acknowledgeBundledPiChangelog(manifest.piVersion);
    }
  }

  const agentDir = process.env.PSYCLAW_CODING_AGENT_DIR || join(homedir(), ".psyclaw", "agent");
  await ensureAcademicModeKeybindings(agentDir);
  const sessionDir = process.env.PSYCLAW_CODING_AGENT_SESSION_DIR || join(agentDir, "sessions");

  let spawnEnv: NodeJS.ProcessEnv = withBundledWindowsTools({
    ...process.env,
    PI_SKIP_VERSION_CHECK: process.env.PI_SKIP_VERSION_CHECK ?? "1",
    PSYCLAW_CODING_AGENT_DIR: agentDir,
    PSYCLAW_CODING_AGENT_SESSION_DIR: sessionDir,
    PI_CODING_AGENT_DIR: agentDir,
    PI_CODING_AGENT_SESSION_DIR: sessionDir,
    PSYCLAW_NETWORK_PRELOAD: "1",
    ...(continuouslyWork ? { [CONTINUOUSLY_WORK_ENV]: "1" } : {}),
  }, root);
  if (!continuouslyWork) delete spawnEnv[CONTINUOUSLY_WORK_ENV];
  if (process.platform === "darwin") {
    const missing = PROVIDER_PRESETS.filter((preset) => !spawnEnv[preset.apiKeyEnv]);
    const values = await Promise.all(missing.map((preset) => readMacOsLaunchctlCredential(preset.apiKeyEnv)));
    for (const [index, preset] of missing.entries()) {
      const value = values[index];
      if (value) spawnEnv[preset.apiKeyEnv] = value;
    }
  }
  if (manifest?.version !== undefined) spawnEnv.PSYCLAW_VERSION = manifest.version;
  try {
    const settings = JSON.parse(await readFile(join(getAgentDir(), "psyclaw-settings.json"), "utf8")) as { psyclawPet?: unknown };
    if (settings.psyclawPet === true) spawnEnv.PSYCLAW_PET = "1";
    else delete spawnEnv.PSYCLAW_PET;
  } catch {
    delete spawnEnv.PSYCLAW_PET;
  }

  return {
    piCli,
    cwd,
    root,
    agentDir,
    sessionDir,
    networkPreloadPath,
    baseArgs,
    spawnEnv,
    identityPrompt,
    nodeArgvPrefix: ["--import", toImportSpecifier(networkPreloadPath), piCli],
  };
}

export interface ChatLaunchOptions {
  /** Extra args forwarded verbatim to the Pi CLI. */
  args?: string[];
  cwd?: string;
  /** Override the psyclaw extension entry (defaults to the built extension). */
  extensionPath?: string;
  /** Override the psyclaw skill directory (defaults to the bundled skills). */
  skillsPath?: string;
  /** Test/development hook for launching the bundled runtime. */
  spawnProcess?: typeof spawn;
  /**
   * Launch-only continuously-work option (`psyclaw --continuously-work`).
   * Not a Shift+Tab mode; cannot be toggled mid-session.
   */
  continuouslyWork?: boolean;
}

/** Pi CLI args that install PsyClaw as the base identity (not an append on "pi"). */
export function systemPromptLaunchArgs(identityPrompt: string): string[] {
  return ["--system-prompt", identityPrompt];
}

/**
 * Launch the bundled Pi interactive chat with psyclaw's extension and skills
 * loaded explicitly. This is the "download psyclaw and talk" entrypoint: the
 * user gets Pi's full conversation TUI plus psyclaw's research workflow
 * commands and model-callable tools. Developer-only commands remain hidden.
 */
export async function launchChat(options: ChatLaunchOptions = {}): Promise<number> {
  const prepared = await prepareAgentLaunch({
    ...(options.cwd === undefined ? {} : { cwd: options.cwd }),
    ...(options.extensionPath === undefined ? {} : { extensionPath: options.extensionPath }),
    ...(options.skillsPath === undefined ? {} : { skillsPath: options.skillsPath }),
    ...(options.continuouslyWork === undefined ? {} : { continuouslyWork: options.continuouslyWork }),
  });
  if (options.continuouslyWork === true) {
    process.stderr.write(`${c.red(continuouslyWorkWarningText())}\n\n`);
  }
  const args = [...prepared.baseArgs, ...(options.args ?? [])];
  return new Promise<number>((resolve, reject) => {
    const child = (options.spawnProcess ?? spawn)(process.execPath, [...prepared.nodeArgvPrefix, ...args], {
      cwd: prepared.cwd,
      stdio: "inherit",
      shell: false,
      env: prepared.spawnEnv,
    });
    child.on("error", reject);
    child.on("close", (code) => resolve(code ?? 1));
  });
}
