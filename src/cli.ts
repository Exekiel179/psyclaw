#!/usr/bin/env node
import { spawn } from "node:child_process";
import { lstat, readFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import {
  asProject,
  assertEvidenceImportable,
  bootstrapProject,
  discoverAgents,
  FileInstallLedger,
  hasConfiguredProvider,
  importAgentSkills,
  KNOWN_AGENTS,
  launchChat,
  planAgentInstall,
  projectPaths,
  runInstall,
  runOfflineBrief,
  setupProviders,
  sha256File,
  writeHandoff,
  initializeHitlWorkspace,
  PSYCLAW_VERSION,
} from "./index.js";
import { appendJsonlIfMissing } from "./project/jsonl.js";
import { access } from "node:fs/promises";
import type { ResearchParadigm } from "./core/contracts.js";
import { formatCliUsage, renderSuccessCard, c } from "./style/cli-ui.js";

const PARADIGMS = new Set<ResearchParadigm>([
  "survey-observational",
  "qualitative-thematic",
  "experimental",
  "quasi-experimental",
  "longitudinal-panel",
  "meta-analysis",
  "ethnographic",
  "historical-documentary",
  "policy-legal",
  "mixed-methods",
]);

function usage(): string {
  return formatCliUsage();
}

function option(args: string[], name: string, fallback?: string): string | undefined {
  const index = args.indexOf(name);
  if (index < 0) return fallback;
  const value = args[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`Option ${name} requires a value`);
  return value;
}

const INSTALL_ENV_NAMES = ["PATH", "Path", "SystemRoot", "WINDIR", "ComSpec", "TEMP", "TMP", "PATHEXT"] as const;

function installEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const name of INSTALL_ENV_NAMES) {
    const value = process.env[name];
    if (value !== undefined) env[name] = value;
  }
  return env;
}

function spawnCommand(command: string, inherit: boolean): Promise<{ exitCode: number }> {
  const [bin, ...rest] = command.split(/\s+/).filter(Boolean);
  return new Promise((resolve) => {
    const child = spawn(bin!, rest, { stdio: inherit ? "inherit" : "ignore", shell: false, env: installEnvironment() });
    child.on("error", () => resolve({ exitCode: 1 }));
    child.on("close", (code) => resolve({ exitCode: code ?? 1 }));
  });
}

/**
 * Run a package-manager command in a fixed directory. Unlike `spawnCommand`,
 * this one sets `cwd` and — on Windows only — uses a shell so `pnpm`/`npm`
 * resolve through their `.cmd` shims. The command string is built by
 * `updateBundledPi` from a strictly-validated semver and hardcoded package
 * names, so shell interpretation is safe.
 */
function runPackageManager(command: string, cwd: string): Promise<{ exitCode: number }> {
  const [bin, ...rest] = command.split(/\s+/).filter(Boolean);
  return new Promise((resolve) => {
    const child = spawn(bin!, rest, {
      cwd,
      stdio: "inherit",
      shell: process.platform === "win32",
      env: installEnvironment(),
    });
    child.on("error", () => resolve({ exitCode: 1 }));
    child.on("close", (code) => resolve({ exitCode: code ?? 1 }));
  });
}

function assertKnownOptions(args: readonly string[], allowed: readonly string[]): void {
  const allowedSet = new Set(allowed);
  for (const [index, arg] of args.entries()) {
    if (!arg.startsWith("--")) continue;
    if (!allowedSet.has(arg)) throw new Error(`Unknown option: ${arg}`);
    if (index + 1 >= args.length || args[index + 1]?.startsWith("--")) {
      throw new Error(`Option ${arg} requires a value`);
    }
  }
}

async function addEvidence(root: string, args: string[]): Promise<void> {
  await access(projectPaths(root).project);
  assertKnownOptions(args, ["--level"]);
  const source = args[0];
  if (!source) throw new Error("Usage: psyclaw evidence add <path> [--level fulltext|user]");
  // Evidence imports are read-only and may point outside the project; the
  // symlink check below prevents silently following an indirection.
  const sourcePath = resolve(root, source);
  const stat = await lstat(sourcePath);
  if (stat.isSymbolicLink()) throw new Error("Evidence symlinks are rejected; import the real file explicitly");
  if (!stat.isFile()) throw new Error("Evidence source must be a regular file");
  const level = option(args, "--level", "user");
  if (level !== "fulltext" && level !== "user") throw new Error(`Unsupported evidence level: ${level}`);
  const optionTail = args.slice(1);
  if (optionTail.length !== 0 && (optionTail.length !== 2 || optionTail[0] !== "--level")) {
    throw new Error("Usage: psyclaw evidence add <path> [--level fulltext|user]");
  }
  // Reject HTML/binary/empty content masquerading as a full-text document.
  await assertEvidenceImportable(sourcePath, level);
  const digest = await sha256File(sourcePath);
  const evidence = {
    id: `evidence_${digest.slice(0, 16)}`,
    source: { kind: "file" as const, locator: sourcePath, title: basename(sourcePath) },
    level,
    retrievedAt: new Date().toISOString(),
    sha256: digest,
    // A user-supplied file is provenance, not independent verification. A
    // full-text level is only promotable after a parser records precise
    // page/section/row locators and a separate verification step approves it.
    accessStatus: "partial" as const,
    locators: [{ kind: "file" as const, value: sourcePath }],
  };
  const evidencePath = projectPaths(root).evidence;
  await appendJsonlIfMissing(evidencePath, evidence, (item) => item.id);
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
}

async function ensureConfiguredThenChat(args: string[]): Promise<void> {
  if (!(await hasConfiguredProvider())) {
    const { runWizard } = await import("./wizard.js");
    const result = await runWizard();
    if (!result.completed) return;
    if (result.provider && result.modelId) {
      args = ["--provider", result.provider, "--model", result.modelId, ...args];
    }
  }
  await launchChat({ args });
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const command = args.shift();
  const root = process.cwd();
  if (command === "--help" || command === "-h") {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  // Bare `psyclaw` is the primary entrypoint: guide the user through first-run
  // setup when no provider is configured, then launch the conversation.
  if (!command) {
    await ensureConfiguredThenChat(args);
    return;
  }
  if (command === "chat") {
    await ensureConfiguredThenChat(args);
    return;
  }
  if (command === "wizard") {
    const { runWizard } = await import("./wizard.js");
    await runWizard();
    return;
  }
  if (command === "setup") {
    assertKnownOptions(args, ["--provider"]);
    const provider = option(args, "--provider");
    const result = await setupProviders(provider === undefined ? {} : { providers: [provider] });
    process.stdout.write(`${JSON.stringify({ path: result.path, providers: result.providers }, null, 2)}\n`);
    return;
  }
  if (command === "init") {
    assertKnownOptions(args, ["--paradigm"]);
    const paradigm = option(args, "--paradigm", "survey-observational");
    if (!paradigm || !PARADIGMS.has(paradigm as ResearchParadigm)) {
      throw new Error(`Unsupported paradigm: ${paradigm}`);
    }
    const optionIndexes = new Set<number>();
    for (const [index, arg] of args.entries()) {
      if (arg === "--paradigm") {
        optionIndexes.add(index);
        optionIndexes.add(index + 1);
      }
    }
    const goal = args.filter((_arg, index) => !optionIndexes.has(index)).join(" ").trim();
    if (!goal) throw new Error("Usage: psyclaw init <goal> [--paradigm <profile>]");
    const project = await bootstrapProject({
      root,
      goal,
      paradigm: paradigm as ResearchParadigm,
    });
    process.stdout.write(`${JSON.stringify(project, null, 2)}\n`);
    return;
  }
  if (command === "evidence" && args.shift() === "add") {
    await addEvidence(root, args);
    return;
  }
  if (command === "handoff") {
    const project = asProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")));
    await writeHandoff(root, {
      projectId: project.id,
      runId: `run_${Date.now()}`,
      goal: project.goal,
      completed: ["project bootstrap"],
      verified: ["project.json exists"],
      blocked: ["claim-evidence audit pending"],
      nextSteps: ["import and audit evidence"],
      verificationCommands: ["pnpm typecheck", "pnpm test"],
      generatedAt: new Date().toISOString(),
    });
    process.stdout.write(renderSuccessCard("已生成 HANDOFF 研究移交备忘录", {
      "Markdown 产物": "notes/HANDOFF.md",
      "JSON 结构化快照": "notes/handoff.json",
    }));
    return;
  }
  if (command === "hitl") {
    const action = args.shift();
    if (action !== "init" || args.length > 0) throw new Error("Usage: psyclaw hitl init");
    const project = asProject(JSON.parse(await readFile(projectPaths(root).project, "utf8")));
    await initializeHitlWorkspace(root, project.goal);
    process.stdout.write(renderSuccessCard("已初始化人类裁决 (HITL) 工作区模板", {
      "位置": "notes/ 与 logs/",
      "状态": "待研究者确认节点已就绪",
    }));
    return;
  }
  if (command === "brief") {
    const result = await runOfflineBrief(root);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (result.verdict === "blocked") process.exitCode = 2;
    return;
  }
  if (command === "agents" || command === "scan") {
    const scans = await discoverAgents();
    process.stdout.write(`${JSON.stringify(scans, null, 2)}\n`);
    return;
  }
  if (command === "install") {
    const id = args.shift();
    if (!id) throw new Error("Usage: psyclaw install <agent-id> [--yes]");
    const agent = KNOWN_AGENTS.find((candidate) => candidate.id === id);
    if (!agent) throw new Error(`Unknown agent: ${id}`);
    const plan = planAgentInstall(agent);
    if (!args.includes("--yes")) {
      process.stdout.write(`${JSON.stringify(plan, null, 2)}\n`);
      process.stdout.write(c.yellow("\n➜ 请附加 --yes 参数确认并执行安装。\n"));
      return;
    }
    const receipt = await runInstall(
      plan,
      { approved: true, actor: "cli", reason: "--yes" },
      (command) => spawnCommand(command, true),
      { ledger: new FileInstallLedger(root) },
    );
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
    if (!receipt.ok) process.exitCode = 1;
    return;
  }
  if (command === "import") {
    const id = args.shift();
    if (!id) throw new Error("Usage: psyclaw import <agent-id> [--yes]");
    const scans = await discoverAgents();
    const agent = scans.find((candidate) => candidate.id === id && candidate.found);
    if (!agent) throw new Error(`Agent not found or not configured: ${id}`);
    if (!args.includes("--yes")) {
      process.stdout.write(`${JSON.stringify(agent, null, 2)}\n`);
      process.stdout.write(c.yellow("\n➜ 请附加 --yes 参数确认并导入技能。\n"));
      return;
    }
    const result = await importAgentSkills({
      root,
      agent,
      approval: { approved: true, actor: "cli", reason: "--yes" },
    });
    process.stdout.write(`${JSON.stringify({ manifestPath: result.manifestPath, importedCount: result.importedCount }, null, 2)}\n`);
    return;
  }
  if (command === "shell") {
    const { runTui } = await import("./tui/app.js");
    runTui(root);
    return;
  }
  if (command === "check-updates") {
    const { checkUpdates } = await import("./updates/check.js");
    const { createHttpRegistry } = await import("./updates/registry.js");
    const report = await checkUpdates({ registry: createHttpRegistry(), cwd: root });
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return;
  }
  if (command === "update") {
    for (const arg of args) {
      if (arg.startsWith("--") && arg !== "--yes" && arg !== "--force") {
        throw new Error(`Unknown option: ${arg}`);
      }
    }
    const { updateBundledPi } = await import("./updates/update.js");
    const { createHttpRegistry } = await import("./updates/registry.js");
    const receipt = await updateBundledPi({
      registry: createHttpRegistry(),
      force: args.includes("--force"),
      ...(args.includes("--yes") ? { executor: (step) => runPackageManager(step.command, step.cwd) } : {}),
    });
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
    if (!receipt.ok) {
      process.exitCode = 1;
    } else if (receipt.reasonCode === "update-skipped" && receipt.command !== undefined) {
      process.stdout.write(c.yellow("\n➜ 请附加 --yes 参数确认并应用更新。\n"));
    }
    return;
  }
  throw new Error(`Unknown command: ${command}\n\n${usage()}`);
}

main().catch((error: unknown) => {
  process.stderr.write(`${c.red("✗ Error:")} ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
