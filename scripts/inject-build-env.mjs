#!/usr/bin/env node
/**
 * Inject build-time environment variables into compiled JavaScript.
 *
 * Environment variables that may be embedded in release artifacts:
 *   LANGFUSE_RELAY_URL - Public Langfuse relay endpoint (optional)
 *
 * Usage:
 *   LANGFUSE_RELAY_URL=https://relay.example.com pnpm build
 *
 * This script runs after TypeScript compilation and rewrites compiled
 * constants in dist/ to reflect build-time env vars. It never touches
 * secrets (LANGFUSE_SECRET_KEY, API keys, etc.).
 */

import { readFile, writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const publicKeysPath = join(root, "dist", "src", "observability", "public-keys.js");

function trimEnv(value) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

async function injectPublicKeys() {
  const langfuseRelayUrl = trimEnv(process.env.LANGFUSE_RELAY_URL);

  let content = await readFile(publicKeysPath, "utf8");
  let injected = [];

  // Replace PUBLIC_LANGFUSE_RELAY_URL if set at build time
  if (langfuseRelayUrl !== undefined) {
    const pattern = /export const PUBLIC_LANGFUSE_RELAY_URL = undefined;/;
    if (pattern.test(content)) {
      const replacement = `export const PUBLIC_LANGFUSE_RELAY_URL = "${langfuseRelayUrl.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}";`;
      content = content.replace(pattern, replacement);
      injected.push(`LANGFUSE_RELAY_URL="${langfuseRelayUrl}"`);
    }
  }

  if (injected.length > 0) {
    await writeFile(publicKeysPath, content, "utf8");
    console.log(`inject-build-env: embedded ${injected.join(", ")}`);
  } else {
    console.log("inject-build-env: no build-time env vars set; public keys unchanged");
  }
}

injectPublicKeys().catch((error) => {
  console.error(`inject-build-env error: ${error.message}`);
  process.exitCode = 1;
});
