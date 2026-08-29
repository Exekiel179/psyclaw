import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  acknowledgeBundledPiChangelog,
  ensurePsyClawTheme,
  ensureQuietStartup,
  PSYCLAW_IDENTITY_PROMPT,
} from "./branding.js";
import { resolvePsyClawManifest } from "./updates/manifest.js";
import { PROVIDER_PRESETS, readMacOsLaunchctlCredential } from "./setup.js";

/** Package root of the installed psyclaw package (dist/src/chat.js -> root). */
function packageRoot(): string {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "..");
}

/** Resolve the bundled Pi CLI shipped as a dependency of psyclaw. */
function resolvePiCli(): string {
  try {
    // The Pi package is ESM-only (its `exports` map has only an `import`
    // condition), so we resolve through `import.meta.resolve` rather than a
    // CommonJS require. The CLI (`dist/cli.js`) sits beside `dist/index.js`.
    const entryUrl = import.meta.resolve("@earendil-works/pi-coding-agent");
    return join(dirname(fileURLToPath(entryUrl)), "cli.js");
  } catch {
    throw new Error(
      "Cannot locate the bundled Pi CLI (@earendil-works/pi-coding-agent). Run `pnpm install` or `npm install` first.",
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
    throw new Error("Unable to prepare the bundled Pi runtime for PsyClaw. Reinstall psyclaw or run `psyclaw rebrand` from its package directory.");
  }
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
}

/**
 * Launch the bundled Pi interactive chat with psyclaw's extension and skills
 * loaded explicitly. This is the "download psyclaw and talk" entrypoint: the
 * user gets Pi's full conversation TUI plus psyclaw's research workflow
 * commands and model-callable tools. Developer-only commands remain hidden.
 */
export async function launchChat(options: ChatLaunchOptions = {}): Promise<number> {
  const piCli = resolvePiCli();
  const root = packageRoot();
  const extensionPath = options.extensionPath ?? join(root, "dist", "src", "extension.js");
  const panelExtensionPath = join(root, "dist", "src", "panel", "extension.js");
  const skillsPath = options.skillsPath ?? join(root, "skills", "core");
  const cwd = options.cwd ?? process.cwd();
  // Branding is applied on first launch, not during npm installation, so the
  // package install itself never mutates dependency files.
  await applyRuntimeBranding(root);
  const developerMode = process.env.PSYCLAW_DEVELOPER_COMMANDS === "1";
  const toolAllowlist = developerMode
    ? "read,grep,find,ls,edit,write,bash,psyclaw_skill,psyclaw_workbench"
    : "read,grep,find,ls,edit,write,bash,psyclaw_skill,psyclaw_workbench";
  // The base identity is fixed; the user may only append a project supplement
  // (managed from the panel), never rewrite the base.
  let identityPrompt = PSYCLAW_IDENTITY_PROMPT;
  try {
    const supplement = (await readFile(join(cwd, ".psyclaw", "system-prompt.md"), "utf8")).trim();
    if (supplement) identityPrompt = `${identityPrompt}\n\n${supplement}`;
  } catch { /* no user supplement */ }
  const args = [
    "--extension", extensionPath,
    "--extension", panelExtensionPath,
    "--skill", skillsPath,
    "--tools", toolAllowlist,
    "--append-system-prompt", identityPrompt,
    ...(options.args ?? []),
  ];

  // Brand the startup: psyclaw theme + native "ψ psyclaw v<psyclaw version>" header
  // (opt into a quiet screen with PSYCLAW_QUIET_STARTUP=1), and keep the model's
  // identity as psyclaw rather than "pi".
  const manifest = await resolvePsyClawManifest();
  await ensureQuietStartup();
  await ensurePsyClawTheme();
  if (manifest?.piVersion !== undefined) {
    await acknowledgeBundledPiChangelog(manifest.piVersion);
  }

  // The header banner renders psyclaw's own version (not the bundled pi 0.84.x).
  const spawnEnv: NodeJS.ProcessEnv = {
    ...process.env,
    PI_SKIP_VERSION_CHECK: process.env.PI_SKIP_VERSION_CHECK ?? "1",
  };
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

  return new Promise<number>((resolve, reject) => {
    const child = (options.spawnProcess ?? spawn)(process.execPath, [piCli, ...args], {
      cwd,
      stdio: "inherit",
      shell: false,
      // psyclaw owns the update surface (`psyclaw check-updates` / `psyclaw update`),
      // so silence Pi's own "new version available" banner to avoid a second
      // prompt. An explicit env override still wins.
      env: spawnEnv,
    });
    child.on("error", reject);
    child.on("close", (code) => resolve(code ?? 1));
  });
}
