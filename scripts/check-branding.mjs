#!/usr/bin/env node

import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative, resolve, sep } from "node:path";
import process from "node:process";

const root = resolve(import.meta.dirname, "..");
const legacyName = `psy${"pi"}`;
const scanRoots = [
  "apps",
  "docs",
  "evals",
  "scripts",
  "skills",
  "src",
  "tests",
];
const rootFiles = [
  "AGENTS.md",
  "CHANGELOG.md",
  "CLAUDE.md",
  "LICENSE",
  "PRODUCT.md",
  "README.md",
  "package.json",
  "package.json.psyclaw",
  "pnpm-lock.yaml",
  "tsconfig.json",
  "vitest.config.ts",
];
const skippedDirectories = new Set([
  ".git",
  ".obsidian",
  "coverage",
  "dist",
  "node_modules",
  "raw",
]);
const skippedExtensions = new Set([
  ".docx",
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".pdf",
  ".png",
  ".webp",
  ".zip",
]);
const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
const governance = JSON.parse(await readFile(join(root, "package.json.psyclaw"), "utf8"));

function displayPath(path) {
  return relative(root, path).split(sep).join("/");
}

function isAllowedProvenance(path, line) {
  if (displayPath(path) !== "package.json.psyclaw") return false;
  const provenance = new RegExp(
    `^\\s*"ref"\\s*:\\s*"${legacyName}@[0-9a-f]{40}"\\s*$`,
    "i",
  );
  return provenance.test(line);
}

async function collectFiles(path) {
  const entries = await readdir(path, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink()) continue;
    const child = join(path, entry.name);
    if (entry.isDirectory()) {
      if (!skippedDirectories.has(entry.name)) {
        files.push(...await collectFiles(child));
      }
      continue;
    }
    if (entry.isFile() && !skippedExtensions.has(extname(entry.name).toLowerCase())) {
      files.push(child);
    }
  }
  return files;
}

const candidates = rootFiles.map((path) => join(root, path));
for (const path of scanRoots) {
  candidates.push(...await collectFiles(join(root, path)));
}

const forbidden = [];
const allowed = [];
const contractFailures = [];
for (const path of candidates) {
  const content = await readFile(path, "utf8");
  for (const [index, line] of content.split(/\r?\n/u).entries()) {
    if (!line.toLowerCase().includes(legacyName)) continue;
    const match = `${displayPath(path)}:${index + 1}`;
    if (isAllowedProvenance(path, line)) {
      allowed.push(match);
    } else {
      forbidden.push(match);
    }
  }
}

if (manifest.name !== "psyclaw") contractFailures.push("package.json name must be psyclaw");
if (manifest.bin?.psyclaw !== "dist/src/cli.js") {
  contractFailures.push("package.json must expose the psyclaw CLI bin");
}
if (manifest.scripts?.postinstall !== undefined) {
  contractFailures.push("package.json must not mutate dependencies during postinstall");
}
if (manifest.publishConfig?.registry !== "https://registry.npmjs.org/") {
  contractFailures.push("package.json publishConfig must use the official npm registry");
}
if (manifest.publishConfig?.access !== "public") {
  contractFailures.push("package.json publishConfig must declare public access");
}
const expectedExtensions = ["./dist/src/extension.js", "./dist/src/panel/extension.js"];
if (JSON.stringify(manifest.pi?.extensions) !== JSON.stringify(expectedExtensions)) {
  contractFailures.push("package.json Pi extensions must point to packaged dist files");
}
if (governance.id !== "psyclaw") contractFailures.push("package governance id must be psyclaw");
if (governance.schemaVersion !== "psyclaw/package-governance/v1") {
  contractFailures.push("package governance schema must use the psyclaw namespace");
}
if (governance.apiVersion !== manifest.version.replace(/\.0$/u, "")) {
  contractFailures.push("package governance apiVersion must match the package major/minor version");
}

const versionSurfaces = [
  ["README.md", `v${manifest.version}`],
  ["PRODUCT.md", `Version ${manifest.version}`],
  ["CHANGELOG.md", `## v${manifest.version}`],
  ["docs/使用白皮书.md", `| 版本 | ${manifest.version}`],
  ["apps/website/index.html", `PsyClaw v${manifest.version}`],
];
for (const [path, marker] of versionSurfaces) {
  const content = await readFile(join(root, path), "utf8");
  if (!content.includes(marker)) contractFailures.push(`${path} is missing ${marker}`);
}

if (allowed.length !== 1) {
  contractFailures.push(`expected one pinned predecessor provenance ref, found ${allowed.length}`);
}
if (forbidden.length > 0) {
  contractFailures.push("legacy product identifier found in release sources");
  contractFailures.push(...forbidden.map((match) => `legacy identifier at ${match}`));
}

if (contractFailures.length > 0) {
  process.stderr.write("branding check failed:\n");
  for (const failure of contractFailures) process.stderr.write(`  - ${failure}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(
    `branding check passed: PsyClaw ${manifest.version}; retained provenance: ${allowed[0]}\n`,
  );
}
