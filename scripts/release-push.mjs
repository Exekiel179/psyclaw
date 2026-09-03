#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import fs from "node:fs";

const run = (command, args, options = {}) => {
  const output = execFileSync(command, args, {
    encoding: "utf8",
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    ...options,
  });
  return typeof output === "string" ? output.trim() : "";
};

const fail = (message) => {
  console.error(`release: ${message}`);
  process.exit(1);
};

const branch = run("git", ["branch", "--show-current"], { capture: true });
if (!branch || branch === "HEAD") fail("必须在命名分支上发布，不能在 detached HEAD 上运行");

const status = run("git", ["status", "--short"], { capture: true });
const trackedChanges = status
  .split("\n")
  .filter(Boolean)
  .filter((line) => !line.startsWith("??"));
if (trackedChanges.length === 0) fail("没有已跟踪文件的变更；未跟踪文件不会被自动加入发布");

const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
const [major, minor, patch] = packageJson.version.split(".").map(Number);
if (![major, minor, patch].every(Number.isInteger)) fail(`无法解析版本号: ${packageJson.version}`);
const previousVersion = packageJson.version;
const nextVersion = `${major}.${minor}.${patch + 1}`;

run("npm", ["version", nextVersion, "--no-git-tag-version", "--allow-same-version"]);
const readmePath = "README.md";
const readme = fs.readFileSync(readmePath, "utf8");
if (!readme.includes(previousVersion)) fail(`README.md 未包含当前版本 ${previousVersion}`);
fs.writeFileSync(readmePath, readme.replaceAll(previousVersion, nextVersion));

const changelogPath = "CHANGELOG.md";
const changelog = fs.readFileSync(changelogPath, "utf8");
const releaseNotes = (process.env.RELEASE_NOTES || "Updated PsyClaw research workflow and integrations.")
  .split("|")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => `- ${line}`)
  .join("\n");
const releaseDate = new Date().toISOString().slice(0, 10);
const changelogEntry = `## ${nextVersion} - ${releaseDate}\n\n${releaseNotes}\n\n`;
if (!changelog.startsWith("# Changelog\n\n")) fail("CHANGELOG.md 缺少标准标题");
fs.writeFileSync(changelogPath, changelog.replace("# Changelog\n\n", `# Changelog\n\n${changelogEntry}`));

run("git", ["add", "-u"]);
run("git", ["add", "package.json", readmePath, changelogPath]);
const tag = `v${nextVersion}`;
const subject = process.env.RELEASE_MESSAGE || `release: psyclaw ${nextVersion}`;
run("git", ["commit", "-m", subject]);
run("git", ["tag", "-a", tag, "-m", tag]);
run("git", ["push", "origin", branch]);
run("git", ["push", "origin", tag]);

console.log(`release: pushed ${branch} and ${tag}`);
console.log("release: GitHub Actions will run platform checks and publish the npm package");
