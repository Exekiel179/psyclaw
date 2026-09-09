#!/usr/bin/env node
/**
 * Rebrand the bundled Pi runtime for PsyClaw.
 *
 * Curated Master Rotation Pool (Slanted Block Matrix removed):
 * 1. 紧凑型对称衬线 I 方块字 (Compact Linear with Serif-I: ▀█▀ / ▄█▄)
 * 2. 经典流线斜体 (Classic Slant Italic)
 * 3. 3D 侧影电路方块字 (3D Isometric Shadow Block: ██████╗)
 * 4. 学术罗马衬线体 (Academic Roman Serif: ╔══╗)
 *
 * Pets are opt-in via /pet and render below the primary wordmark.
 */
import { execFile } from "node:child_process";
import { readFile, rename, rm, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const NAME = "PsyClaw";
const LOCKED_PI_VERSION = "0.84.4";
// PsyClaw's own user config directory. Retained as the sole Pi config dir so
// models, themes, packages, and skills live under `~/.psyclaw` consistently
// with the project data directory name.
const CONFIG_DIR = `.psyclaw`;

function hexToRgb(hex) {
  const num = parseInt(hex.replace("#", ""), 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function interpolateRgb(c1, c2, t) {
  return [
    Math.round(c1[0] + (c2[0] - c1[0]) * t),
    Math.round(c1[1] + (c2[1] - c1[1]) * t),
    Math.round(c1[2] + (c2[2] - c1[2]) * t),
  ];
}

function gradientText(text, hexStops, totalCols) {
  const chars = Array.from(text);
  const total = totalCols || chars.length;
  if (total === 0) return "";
  const stops = hexStops.map(hexToRgb);

  return chars.map((char, col) => {
    if (char === " " || char === "\t") return char;
    const globalT = Math.min(1, Math.max(0, col / Math.max(1, total - 1)));
    const stopIndex = Math.min(Math.floor(globalT * (stops.length - 1)), stops.length - 2);
    const localT = (globalT * (stops.length - 1)) - stopIndex;
    const [r, g, b] = interpolateRgb(stops[stopIndex], stops[stopIndex + 1], localT);
    const escaped = char === "\\" ? "\\\\" : char;
    return `\\x1b[38;2;${r};${g};${b}m${escaped}\\x1b[0m`;
  }).join("");
}

const AURORA_STOPS = ["#38bdf8", "#60a5fa", "#818cf8", "#a855f7", "#ec4899", "#2dd4bf"];

// Colors
const WHITE = "\\x1b[1m\\x1b[38;2;255;255;255m";
const GLASSES = "\\x1b[1m\\x1b[38;2;56;189;248m";
const GOLD = "\\x1b[38;2;251;191;36m";
const RESET = "\\x1b[0m";

// Kaomoji Pups
const PUP_SCHOLAR_TOP = `${WHITE}( ᐡ ${RESET}${GLASSES}⌐■-■${RESET}${WHITE} ᐡ )${RESET} ${GOLD}✨${RESET}`;
const PUP_SCHOLAR_BOT = `${WHITE}c( づ 📜 づ )${RESET}`;

// 1. 紧凑型对称衬线 I 方块字 (2-Row Compact)
const FONT_2ROW_ROW0 = "█▀█ █▀▀ █ █ █▀▀ █    █▀█ █ █";
const FONT_2ROW_ROW1 = "█▀▀ ▄██  █  █▄▄ █▄▄ ▄█▀ █▀█";
const GRAD_2ROW_0 = gradientText(FONT_2ROW_ROW0, AURORA_STOPS, FONT_2ROW_ROW0.length);
const GRAD_2ROW_1 = gradientText(FONT_2ROW_ROW1, AURORA_STOPS, FONT_2ROW_ROW1.length);

// 2. 经典流线斜体 (Classic Slant Italic - 5-Row PsyClaw)
const FONT_SLANT_CLASSIC = [
  "  ____  ____  _   _  ____ _       ___ __      __",
  " |  _ \\/ ___|| | | |/ ___| |     / _ \\ \\    / / ",
  " | |_) \\___ \\| |_| | |   | |    | |_| \\ \\  / /  ",
  " |  __/ ___) |  _  | |___| |___ |  _  |\\ \\// /   ",
  " |_|   |____/|_| |_|\\____|_____|_| |_| \\__/    ",
];

// 3. 3D 侧影电路方块 (3D Isometric Shadow Block - 5-Row)
const FONT_3D_BLOCK = [
  " ██████╗ ███████╗██╗   ██╗ ██████╗██╗      █████╗ ██╗    ██╗",
  " ██╔══██╗██╔════╝╚██╗ ██╔╝██╔════╝██║     ██╔══██╗██║    ██║",
  " ██████╔╝███████╗ ╚████╔╝ ██║     ██║     ███████║██║ █╗ ██║",
  " ██╔═══╝ ╚════██║  ╚██╔╝  ██║     ██║     ██╔══██║██║███╗██║",
  " ██║     ███████║   ██║   ╚██████╗███████╗██║  ██║╚███╔███╔╝",
];

// 4. 学术罗马衬线体 (Academic Roman Serif - 3-Row)
const FONT_SERIF = [
  " ╔═══╗ ╔══╗  ╦ ╦  ╔══╗ ╦     ╔══╗ ╦ ╦",
  " ╠═══╝ ╚══╗  ╚╦╝  ║    ║     ╠══╣ ║║║",
  " ╩     ╚══╝   ╩   ╚══╝ ╚═══╝ ╩  ╩ ╚╩╝",
];

function buildCustomVariant(fontLines, dogLines = []) {
  const fontWidth = Math.max(...fontLines.map((line) => Array.from(line).length));
  const rows = fontLines.map((line, i) => {
    const paddedFont = line.padEnd(fontWidth, " ");
    const gradFont = `\\x1b[1m${gradientText(paddedFont, AURORA_STOPS, fontWidth)}\\x1b[0m`;
    const dog = dogLines[i] || "";
    return `    \`  ${gradFont}   ${dog}\``;
  });
  return `[\n${rows.join(",\n")}\n  ]`;
}

// Every default variant is pet-free. The pet is appended below the wordmark
// when enabled so it never forces PsyClaw's primary branding into a smaller
// layout.
const VAR_COMPACT = `[
    \`  \\x1b[1m${GRAD_2ROW_0}\\x1b[0m   \\x1b[38;2;148;163;184mv\${process.env.PSYCLAW_VERSION ?? this.version}\\x1b[0m\`,
    \`  \\x1b[1m${GRAD_2ROW_1}\\x1b[0m\`
  ]`;
const VAR_STACKED_PET = `[
    \`  ${PUP_SCHOLAR_TOP}\`,
    \`  ${PUP_SCHOLAR_BOT}\`
  ]`;
const VAR_SLANT_CLASSIC = buildCustomVariant(FONT_SLANT_CLASSIC);
const VAR_3D_BLOCK = buildCustomVariant(FONT_3D_BLOCK);
const VAR_SERIF = buildCustomVariant(FONT_SERIF);
const GRAD_PIPELINE = "\\x1b[38;2;45;212;191m• Pipeline  :\\x1b[0m \\x1b[1m\\x1b[38;2;56;189;248mintake\\x1b[0m \\x1b[38;2;99;102;241m➔\\x1b[0m \\x1b[1m\\x1b[38;2;129;140;248mevidence\\x1b[0m \\x1b[38;2;168;85;247m➔\\x1b[0m \\x1b[1m\\x1b[38;2;168;85;247mstats-plan\\x1b[0m \\x1b[38;2;236;72;153m➔\\x1b[0m \\x1b[1m\\x1b[38;2;244;63;94mmanuscript\\x1b[0m \\x1b[38;2;99;102;241m➔\\x1b[0m \\x1b[1m\\x1b[38;2;45;212;191mpeer-review\\x1b[0m";
const GRAD_PROTOCOL = "\\x1b[38;2;45;212;191m• Protocol  :\\x1b[0m \\x1b[1m\\x1b[38;2;52;211;153m✔ 2+ Cross-Check\\x1b[0m \\x1b[38;2;100;116;139m·\\x1b[0m \\x1b[1m\\x1b[38;2;45;212;191m✔ SHA-256 Ledger\\x1b[0m \\x1b[38;2;100;116;139m·\\x1b[0m \\x1b[1m\\x1b[38;2;168;85;247m✔ Non-Compromise Gates\\x1b[0m";
const GRAD_MODES = "\\x1b[38;2;45;212;191m• Modes     :\\x1b[0m \\x1b[1m\\x1b[38;2;56;189;248mShift+Tab\\x1b[0m \\x1b[38;2;148;163;184m⇄\\x1b[0m \\x1b[1mchat\\x1b[0m \\x1b[38;2;100;116;139m·\\x1b[0m \\x1b[1manalysis\\x1b[0m \\x1b[38;2;100;116;139m·\\x1b[0m \\x1b[1macademic (ARS)\\x1b[0m";
const GRAD_WORKBENCH = "\\x1b[38;2;45;212;191m• Workbench :\\x1b[0m \\x1b[1m\\x1b[38;2;56;189;248mhttp://127.0.0.1:3721\\x1b[0m \\x1b[38;2;168;85;247m(Interactive Panel Active)\\x1b[0m";

const PSYCLAW_DYNAMIC_BANNER = `const bannerCandidates = [
  ${VAR_COMPACT}, ${VAR_SLANT_CLASSIC}, ${VAR_3D_BLOCK}, ${VAR_SERIF},
];
const compactBanner = ${VAR_COMPACT};
const terminalColumns = process.stdout.columns ?? 80;
const ansiPattern = /\\x1b\\[[0-9;]*m/g;
const cellWidth = (text) => Array.from(text.replace(ansiPattern, "")).reduce((width, char) => {
  const code = char.codePointAt(0) ?? 0;
  const wide = code >= 0x1100 && (code <= 0x115f || code === 0x2329 || code === 0x232a ||
    (code >= 0x2e80 && code <= 0xa4cf) || (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) || (code >= 0xfe10 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) || (code >= 0x1f300 && code <= 0x1faff));
  return width + (wide ? 2 : 1);
}, 0);
const bannerWidth = (rows) => Math.max(...rows.map(cellWidth));
const fittingBanners = bannerCandidates.filter((rows) => bannerWidth(rows) <= terminalColumns - 4);
const tinyBanner = [terminalColumns >= 22
  ? \`  ψ PsyClaw v\${process.env.PSYCLAW_VERSION ?? this.version}\`
  : "  PsyClaw"];
const chosenBanner = fittingBanners.reduce((largest, candidate) => {
  if (!largest) return candidate;
  if (candidate.length !== largest.length) return candidate.length > largest.length ? candidate : largest;
  return bannerWidth(candidate) > bannerWidth(largest) ? candidate : largest;
}, undefined) ?? tinyBanner;
const petEnabled = process.env.PSYCLAW_PET === "1";
const stackedPet = petEnabled ? ${VAR_STACKED_PET} : [];
const detailLines = terminalColumns >= 86 ? [
  \`  ${GRAD_PIPELINE}\`,
  \`  ${GRAD_PROTOCOL}\`,
  \`  ${GRAD_MODES}\`,
] : [];
if (terminalColumns >= 76) detailLines.push(\`  ${GRAD_WORKBENCH}\`);
const logo = [
  "",
  ...chosenBanner,
  ...stackedPet,
  "",
  ...detailLines,
  "",
].join("\\n");`;

const GRAD_CORE_SKILLS = "\\x1b[1m\\x1b[38;2;56;189;248m✦ 核心证据链:\\x1b[0m \\x1b[1m\\x1b[38;2;56;189;248mresearch-intake\\x1b[0m \\x1b[38;2;99;102;241m➔\\x1b[0m \\x1b[1m\\x1b[38;2;129;140;248mevidence-capture\\x1b[0m \\x1b[38;2;168;85;247m➔\\x1b[0m \\x1b[1m\\x1b[38;2;168;85;247mcitation-audit\\x1b[0m";

const PSYCLAW_SKILLS_FORMATTER = `const skills = skillsResult.skills;
            if (skills.length > 0) {
                const groups = this.buildScopeGroups(skills.map((skill) => ({ path: skill.filePath, sourceInfo: skill.sourceInfo })));
                const skillList = this.formatScopeGroups(groups, {
                    formatPath: (item) => this.formatDisplayPath(item.path),
                    formatPackagePath: (item) => this.getShortPath(item.path, item.sourceInfo),
                });
                const CORE_PIPELINE = ["research-intake", "evidence-capture", "citation-audit"];
                const availableCore = CORE_PIPELINE.filter((name) => skills.some((s) => s.name === name));
                const otherSkills = skills.filter((s) => !CORE_PIPELINE.includes(s.name)).map((s) => s.name);
                const skillCompactList = \`  ${GRAD_CORE_SKILLS}\\n\${theme.fg("dim", \`  ⟡ 生态扩展 (\${otherSkills.length}): \${otherSkills.slice(0, 10).join(", ")}\${otherSkills.length > 10 ? " ... (按 Ctrl+O 展开全部)" : ""}\`)}\`;
                addLoadedSection("Skills", skillCompactList, skillList);
            }`;

const PSYCLAW_SKILL_DIAGNOSTICS = `const skillDiagnostics = skillsResult.diagnostics.filter((diagnostic) =>
                diagnostic.type === "error" &&
                !/skill path does not exist/i.test(diagnostic.message));
            if (skillDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(skillDiagnostics, sourceInfos);
                const expanded = \`${'${theme.fg("warning", "[Skill issues]")}'}\\n${'${warningLines}'}\`;
                if (warningLines.split("\\n").length > 6) {
                    const collapsed = \`${'${theme.fg("warning", "[Skill issues]")}'}\\n${'${theme.fg("dim", `  ${skillDiagnostics.length} issue(s) · Ctrl+O to expand`)}'}\`;
                    this.loadedResourcesContainer.addChild(new ExpandableText(() => collapsed, () => expanded, false, 0, 0));
                }
                else {
                    this.loadedResourcesContainer.addChild(new Text(expanded, 0, 0));
                }
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }`;

const MODE_PATCHES = [
  {
    old: 'Pi can explain its own features and look up its docs. Ask it how to use or extend Pi.',
    next: 'PsyClaw 可自解释研究范式、文献核验规则与证据账本。直接输入研究目标或向其提问即可。',
  },
  {
    old: 'PsyClaw can explain its own features and look up its docs. Ask it how to use or extend PsyClaw.',
    next: 'PsyClaw 可自解释研究范式、文献核验规则与证据账本。直接输入研究目标或向其提问即可。',
  },
  {
    old: 'theme.bold(theme.fg("accent", APP_NAME))',
    next: 'theme.bold(theme.fg("accent", `ψ ${APP_NAME}`))',
  },
  {
    old: `        // Add header with keybindings from config (unless silenced)
        if (this.options.verbose || !this.settingsManager.getQuietStartup()) {`,
    next: `        // Keep the PsyClaw banner even when quietStartup hides inventories.
        if (true) {`,
  },
  {
    old: `const skills = skillsResult.skills;
            if (skills.length > 0) {
                const groups = this.buildScopeGroups(skills.map((skill) => ({ path: skill.filePath, sourceInfo: skill.sourceInfo })));
                const skillList = this.formatScopeGroups(groups, {
                    formatPath: (item) => this.formatDisplayPath(item.path),
                    formatPackagePath: (item) => this.getShortPath(item.path, item.sourceInfo),
                });
                const skillCompactList = formatCompactList(skills.map((skill) => skill.name));
                addLoadedSection("Skills", skillCompactList, skillList);
            }`,
    next: PSYCLAW_SKILLS_FORMATTER,
  },
  {
    old: `const skillDiagnostics = skillsResult.diagnostics;
            if (skillDiagnostics.length > 0) {
                const warningLines = this.formatDiagnostics(skillDiagnostics, sourceInfos);
                this.loadedResourcesContainer.addChild(new Text(\`${'${theme.fg("warning", "[Skill conflicts]")}'}\\n${'${warningLines}'}\`, 0, 0));
                this.loadedResourcesContainer.addChild(new Spacer(1));
            }`,
    next: PSYCLAW_SKILL_DIAGNOSTICS,
  },
  {
    old: 'this.getStartupExpansionState(), 1, 0);',
    next: 'this.getStartupExpansionState(), 0, 0);',
  },
  {
    old: `// PsyClaw provides cross-platform Node search tools through its extension.
        this.setupKeyHandlers();
        this.setupEditorSubmitHandler();
        // File completion remains optional; startup never downloads from GitHub.`,
    next: `const [fdPath] = await Promise.all([
            ensureTool("fd", (status) => this.showManagedToolStatus(status)),
            ensureTool("rg", (status) => this.showManagedToolStatus(status)),
        ]);
        this.fdPath = fdPath;
        // Enable the remaining input handlers only after managed-tool setup completes.
        this.setupKeyHandlers();
        this.setupEditorSubmitHandler();`,
  },
  {
    old: 'this.ui.terminal.setTitle(`${APP_TITLE} - ${sessionName} - ${cwdBasename}`);',
    next: 'this.ui.terminal.setTitle(`ψ ${APP_TITLE} - ${sessionName} - ${cwdBasename}`);',
  },
  {
    old: 'this.ui.terminal.setTitle(`${APP_TITLE} - ${cwdBasename}`);',
    next: 'this.ui.terminal.setTitle(`ψ ${APP_TITLE} - ${cwdBasename}`);',
  },
  {
    old: 'then restart pi.',
    next: 'then restart PsyClaw.',
  },
  {
    old: `if (text === "/login" || text.startsWith("/login ")) {
                const providerRef = text.startsWith("/login ") ? text.slice(7).trim() : undefined;
                this.editor.setText("");
                await this.handleLoginCommand(providerRef);
                return;
            }`,
    next: `if (text === "/login" || text.startsWith("/login ")) {
                this.editor.setText("");
                this.showWarning("PsyClaw 已统一隐藏底层登录命令。请使用 /provider 配置或切换模型。");
                return;
            }`,
  },
  {
    old: `if (text === "/logout") {
                this.showOAuthSelector("logout");
                this.editor.setText("");
                return;
            }`,
    next: `if (text === "/logout") {
                this.editor.setText("");
                this.showWarning("PsyClaw 已统一隐藏底层退出命令。请使用 /provider 管理模型配置。");
                return;
            }`,
  },
];

async function patchPackageJson(pkgPath) {
  const pkg = JSON.parse(await readFile(pkgPath, "utf8"));
  if (pkg.version !== LOCKED_PI_VERSION) {
    throw new Error(`Unsupported Pi runtime ${String(pkg.version)}; expected ${LOCKED_PI_VERSION}`);
  }
  const existing = pkg.piConfig && typeof pkg.piConfig === "object" && !Array.isArray(pkg.piConfig)
    ? pkg.piConfig
    : {};
  if (existing.name === NAME && existing.configDir === CONFIG_DIR) {
    return { applied: false };
  }
  pkg.piConfig = { ...existing, name: NAME, configDir: CONFIG_DIR };
  await atomicReplace(pkgPath, `${JSON.stringify(pkg, null, "\t")}\n`);
  return { applied: true };
}

async function atomicReplace(path, content, checkJavaScript = false) {
  const suffix = `${process.pid}.${randomUUID()}`;
  const temporary = join(dirname(path), `.${basename(path)}.${suffix}.tmp${checkJavaScript ? ".mjs" : ""}`);
  const backup = join(dirname(path), `.${basename(path)}.${suffix}.bak`);
  let backedUp = false;
  await writeFile(temporary, content, { encoding: "utf8", flag: "wx" });
  try {
    if (checkJavaScript) {
      await new Promise((resolve, reject) => {
        execFile(process.execPath, ["--check", temporary], { windowsHide: true }, (error) => error ? reject(error) : resolve());
      });
    }
    try { await rename(temporary, path); }
    catch (error) {
      if (!new Set(["EEXIST", "EPERM", "EACCES"]).has(error?.code)) throw error;
      await rename(path, backup);
      backedUp = true;
      try { await rename(temporary, path); }
      catch (replaceError) {
        await rename(backup, path).catch(() => undefined);
        throw replaceError;
      }
    }
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
    if (backedUp) await rm(backup, { force: true }).catch(() => undefined);
  }
}

async function applyModePatches(modePath) {
  let content = await readFile(modePath, "utf8");
  const applied = [];

  // Replace the entire generated block. The greedy range also repairs a module
  // that a previous build appended to, instead of declaring the banner twice.
  const dynamicBannerRegex = /(?:const (?:bannerCandidates|wideBannerVariants|BANNER_VARIANTS)[\s\S]*?const logo = \[[\s\S]*?\]\.join\("\\n"\);|const logo = (?:`[\s\S]*?`|\[[\s\S]*?\]\.join\("\\n"\)|theme\.bold[^;]*);)/g;
  const matches = [...content.matchAll(dynamicBannerRegex)];
  if (matches.length !== 1) throw new Error(`Expected exactly one Pi startup banner, found ${matches.length}`);
  const currentMatch = matches[0];
  if (currentMatch && currentMatch[0] !== PSYCLAW_DYNAMIC_BANNER) {
    content = `${content.slice(0, currentMatch.index)}${PSYCLAW_DYNAMIC_BANNER}${content.slice(currentMatch.index + currentMatch[0].length)}`;
    applied.push("const logo = ... [Updated Curated 4-Style psyclaw Banner Rotation Pool]");
  }

  // 静态字符串替换
  for (const { old, next } of MODE_PATCHES) {
    if (content.includes(old)) {
      content = content.replace(old, next);
      applied.push(old.slice(0, 48));
    }
  }
  if (applied.length > 0) {
    await atomicReplace(modePath, content, true);
  }
  return applied;
}

/**
 * Collapse the model's thinking/reasoning blocks by default.  Pi renders them
 * expanded unless `hideThinkingBlock` is set; PsyClaw flips the default so a
 * long thinking trace does not dominate the terminal.  Users can still expand
 * a block with the `app.thinking.toggle` key binding, and an explicit
 * `hideThinkingBlock` value in settings.json always wins.
 */
const SETTINGS_PATCHES = [
  {
    old: "return this.settings.hideThinkingBlock ?? false;",
    next: "return this.settings.hideThinkingBlock ?? true;",
  },
];

// PsyClaw owns provider setup through /provider. Keep Pi's authentication
// implementation available underneath, but do not expose its lower-level
// /login and /logout commands in autocomplete or command help.
const HIDDEN_PI_COMMANDS = ["login", "logout"];

async function applySlashCommandPatches(slashCommandsPath) {
  let content = await readFile(slashCommandsPath, "utf8");
  const applied = [];
  for (const name of HIDDEN_PI_COMMANDS) {
    const commandPattern = new RegExp(
      `^\\s*\\{ name: "${name}", description: [^\\n]+\\},\\r?\\n`,
      "m",
    );
    if (commandPattern.test(content)) {
      content = content.replace(commandPattern, "");
      applied.push(`hide /${name}`);
    }
  }
  if (applied.length > 0) {
    await atomicReplace(slashCommandsPath, content, true);
  }
  return applied;
}

async function applySettingsPatches(settingsManagerPath) {
  let content = await readFile(settingsManagerPath, "utf8");
  const applied = [];
  for (const { old, next } of SETTINGS_PATCHES) {
    if (content.includes(old)) {
      content = content.replace(old, next);
      applied.push(old.slice(0, 48));
    }
  }
  if (applied.length > 0) {
    await atomicReplace(settingsManagerPath, content, true);
  }
  return applied;
}

export const FOOTER_PATCHES = [
  {
    old: `        else {
            contextPercentStr = contextPercentDisplay;
        }
        statsParts.push(contextPercentStr);
        if (areExperimentalFeaturesEnabled()) {`,
    next: `        else {
            contextPercentStr = contextPercentDisplay;
        }
        statsParts.push(contextPercentStr);
        const modeStatus = this.footerData.getExtensionStatuses().get("mode");
        if (modeStatus) {
            statsParts.push(sanitizeStatusText(modeStatus));
        }
        if (areExperimentalFeaturesEnabled()) {`,
  },
  {
    old: `        // Add extension statuses on a single line, sorted by key alphabetically
        const extensionStatuses = this.footerData.getExtensionStatuses();
        if (extensionStatuses.size > 0) {
            const sortedStatuses = Array.from(extensionStatuses.entries())
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([, text]) => sanitizeStatusText(text));
            const statusLine = sortedStatuses.join(" ");
            // Truncate to terminal width with dim ellipsis for consistency with footer style
            lines.push(truncateToWidth(statusLine, width, theme.fg("dim", "...")));
        }`,
    next: `        // Add extension statuses on a single line, sorted by key alphabetically
        const extensionStatuses = this.footerData.getExtensionStatuses();
        if (extensionStatuses.size > 0) {
            const sortedStatuses = Array.from(extensionStatuses.entries())
                .filter(([key]) => key !== "mode")
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([, text]) => sanitizeStatusText(text));
            if (sortedStatuses.length > 0) {
                const statusLine = sortedStatuses.join(" ");
                // Truncate to terminal width with dim ellipsis for consistency with footer style
                lines.push(truncateToWidth(statusLine, width, theme.fg("dim", "...")));
            }
        }`,
  },
];

export function applyFooterPatchesToContent(content) {
  let patched = content;
  let appliedCount = 0;
  const isCrlf = content.includes("\r\n");
  for (const { old, next } of FOOTER_PATCHES) {
    const targetOld = isCrlf ? old.replace(/\r?\n/g, "\r\n") : old;
    const targetNext = isCrlf ? next.replace(/\r?\n/g, "\r\n") : next;
    if (patched.includes(targetOld)) {
      patched = patched.replace(targetOld, targetNext);
      appliedCount++;
    }
  }
  return { content: patched, applied: appliedCount > 0, appliedCount };
}

async function applyFooterPatches(footerPath) {
  const content = await readFile(footerPath, "utf8");
  const result = applyFooterPatchesToContent(content);
  if (result.applied) {
    await atomicReplace(footerPath, result.content, true);
  }
  return result.appliedCount;
}

const MANAGED_TOOL_DOWNLOAD_GUARD = `    // PsyClaw supplies Node-based find/grep fallbacks. Keep PATH tools when
    // present, but never fetch optional binaries from GitHub during startup.
    return undefined;`;

/** Repair a runtime previously modified by PsyClaw 0.27.20. Fresh Pi installs are unchanged. */
export function restoreManagedToolDownloads(content) {
  if (!content.includes(MANAGED_TOOL_DOWNLOAD_GUARD)) return { content, applied: false };
  return { content: content.replace(`\n${MANAGED_TOOL_DOWNLOAD_GUARD}`, ""), applied: true };
}

async function restoreManagedToolManager(toolsManagerPath) {
  const current = await readFile(toolsManagerPath, "utf8");
  const result = restoreManagedToolDownloads(current);
  if (result.applied) await atomicReplace(toolsManagerPath, result.content, true);
  return result.applied;
}

export async function rebrandPiRuntime(options = {}) {
  const entry = import.meta.resolve("@earendil-works/pi-coding-agent");
  const pkgDir = dirname(dirname(fileURLToPath(entry)));
  const pkgPath = join(pkgDir, "package.json");
  const modePath = join(pkgDir, "dist", "modes", "interactive", "interactive-mode.js");
  const settingsManagerPath = join(pkgDir, "dist", "core", "settings-manager.js");
  const slashCommandsPath = join(pkgDir, "dist", "core", "slash-commands.js");
  const toolsManagerPath = join(pkgDir, "dist", "utils", "tools-manager.js");
  const footerPath = join(pkgDir, "dist", "modes", "interactive", "components", "footer.js");

  const pkgResult = await patchPackageJson(pkgPath);
  const applied = await applyModePatches(modePath);
  const settingsApplied = await applySettingsPatches(settingsManagerPath);
  const footerApplied = await applyFooterPatches(footerPath);
  const commandApplied = await applySlashCommandPatches(slashCommandsPath);
  const managedToolsRestored = await restoreManagedToolManager(toolsManagerPath);

  if (!options.quiet) {
    process.stdout.write(
      `psyclaw rebrand: piConfig ${pkgResult.applied ? "applied" : "already set"} · ${applied.length > 0 ? `patched ${applied.length} display string(s)` : "display strings already patched"} · ${settingsApplied.length > 0 ? `patched ${settingsApplied.length} setting default(s)` : "settings already patched"} · ${footerApplied > 0 ? `patched ${footerApplied} footer component(s)` : "footer already patched"} · ${commandApplied.length > 0 ? `hidden ${commandApplied.length} Pi command(s)` : "Pi commands already filtered"} · ${managedToolsRestored ? "restored managed-tool downloads" : "managed-tool downloads unchanged"} (${pkgDir})\n`,
    );
    if (applied.length > 0) {
      for (const label of applied) {
        process.stdout.write(`  - ${label}…\n`);
      }
    }
    if (settingsApplied.length > 0) {
      for (const label of settingsApplied) {
        process.stdout.write(`  - ${label}…\n`);
      }
    }
    if (footerApplied > 0) {
      process.stdout.write(`  - mode status inline with context auto indicator…\n`);
    }
    if (commandApplied.length > 0) {
      for (const label of commandApplied) {
        process.stdout.write(`  - ${label}…\n`);
      }
    }
  }
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  rebrandPiRuntime().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
