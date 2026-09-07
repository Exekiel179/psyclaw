#!/usr/bin/env node

import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { rebrandPiRuntime } from "./rebrand-pi.mjs";

try {
  // Keep PsyClaw's bundled runtime isolated from a separately installed Pi.
  // Set both names because the locked runtime derives its preferred variable
  // from the branded app name, while older/bundled entrypoints may still read
  // Pi's legacy variable. Neither path may fall back to ~/.pi.
  const agentDir = process.env.PSYCLAW_CODING_AGENT_DIR || join(homedir(), ".psyclaw", "agent");
  const sessionDir = process.env.PSYCLAW_CODING_AGENT_SESSION_DIR || join(agentDir, "sessions");
  process.env.PSYCLAW_CODING_AGENT_DIR = agentDir;
  process.env.PSYCLAW_CODING_AGENT_SESSION_DIR = sessionDir;
  process.env.PI_CODING_AGENT_DIR = agentDir;
  process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;

  // Pi reads its application name and config directory while its modules are
  // first imported. Prepare the locked runtime before loading PsyClaw's CLI so
  // a clean first launch cannot create the legacy ~/.pi directory.
  await rebrandPiRuntime({ quiet: true });
  // Use an explicit file:// URL so Windows absolute paths never reach the ESM
  // loader as protocol `c:` (ERR_UNSUPPORTED_ESM_URL_SCHEME).
  const cliUrl = pathToFileURL(join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "src", "cli.js")).href;
  await import(cliUrl);
} catch (error) {
  process.stderr.write(`PsyClaw could not start: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
