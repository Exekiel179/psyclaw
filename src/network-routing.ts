import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const DEFAULT_CN_GITHUB_MIRROR = "https://gh-proxy.com/";
const PROXY_NAMES = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"] as const;
const CN_REGISTRY_MARKERS = ["npmmirror.com", "registry.npm.taobao.org", "mirrors.cloud.tencent.com", "mirrors.aliyun.com"];

export type NetworkRoute =
  | { mode: "official" }
  | { mode: "proxy" }
  | { mode: "mirror"; mirror: string };

function firstValue(env: NodeJS.ProcessEnv, names: readonly string[]): string | undefined {
  for (const name of names) {
    const value = env[name]?.trim();
    if (value) return value;
  }
  return undefined;
}

function normalizeMirror(value: string): string {
  const url = new URL(value);
  if (url.username || url.password || (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "::1"].includes(url.hostname)))) {
    throw new Error("PSYCLAW_GITHUB_MIRROR must be HTTPS, or HTTP on localhost, and cannot contain credentials");
  }
  url.search = "";
  url.hash = "";
  return `${url.toString().replace(/\/$/, "")}/`;
}

export function selectNetworkRoute(env: NodeJS.ProcessEnv, registry?: string): NetworkRoute {
  if (firstValue(env, PROXY_NAMES)) return { mode: "proxy" };
  const explicitMirror = env.PSYCLAW_GITHUB_MIRROR?.trim();
  const effectiveRegistry = env.PSYCLAW_REGISTRY?.trim() || env.npm_config_registry?.trim() || registry?.trim();
  if (explicitMirror) return { mode: "mirror", mirror: normalizeMirror(explicitMirror) };
  if (effectiveRegistry && CN_REGISTRY_MARKERS.some((marker) => effectiveRegistry.toLocaleLowerCase().includes(marker))) {
    return { mode: "mirror", mirror: DEFAULT_CN_GITHUB_MIRROR };
  }
  return { mode: "official" };
}

function npmrcRegistry(text: string): string | undefined {
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || line.startsWith(";") || line.startsWith("//")) continue;
    const match = line.match(/^registry\s*=\s*(.+)$/i);
    if (match?.[1]?.trim()) return match[1].trim().replace(/^['"]|['"]$/g, "");
  }
  return undefined;
}

async function configuredRegistry(): Promise<string | undefined> {
  for (const path of [join(process.cwd(), ".npmrc"), join(homedir(), ".npmrc")]) {
    const text = await readFile(path, "utf8").catch(() => undefined);
    const registry = text === undefined ? undefined : npmrcRegistry(text);
    if (registry) return registry;
  }
  const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const packageMetadata = await readFile(join(packageRoot, "package.json"), "utf8").catch(() => undefined);
  if (packageMetadata !== undefined) {
    try {
      const resolved = (JSON.parse(packageMetadata) as { _resolved?: unknown })._resolved;
      if (typeof resolved === "string" && resolved.trim()) return resolved;
    } catch { /* malformed package metadata is ignored */ }
  }
  const installLock = await readFile(join(dirname(packageRoot), ".package-lock.json"), "utf8").catch(() => undefined);
  if (installLock !== undefined) {
    try {
      const lock = JSON.parse(installLock) as { packages?: Record<string, { resolved?: unknown }> };
      const resolved = lock.packages?.["node_modules/psyclaw"]?.resolved;
      if (typeof resolved === "string" && resolved.trim()) return resolved;
    } catch { /* malformed npm lock metadata is ignored */ }
  }
  return undefined;
}

function mirrorUrl(mirror: string, input: string | URL | Request): string | URL | Request {
  const raw = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
  if (!raw.startsWith("https://api.github.com/") && !raw.startsWith("https://github.com/")) return input;
  const routed = `${mirror}${raw}`;
  return input instanceof Request ? new Request(routed, input) : routed;
}

async function ensureRequiredSearchTools(): Promise<void> {
  const piEntry = import.meta.resolve("@earendil-works/pi-coding-agent");
  const managerUrl = new URL("./utils/tools-manager.js", piEntry);
  const manager = await import(managerUrl.href) as {
    ensureTool(tool: "fd" | "rg", onStatus?: (status: { type: string; message: string }) => void): Promise<string | undefined>;
  };
  const failures: string[] = [];
  const onStatus = (status: { type: string; message: string }): void => {
    if (status.type === "warning") failures.push(status.message);
  };
  const [fdPath, rgPath] = await Promise.all([
    manager.ensureTool("fd", onStatus),
    manager.ensureTool("rg", onStatus),
  ]);
  if (!fdPath || !rgPath) {
    const detail = failures.length > 0 ? ` ${failures.join("; ")}` : "";
    throw new Error(`PsyClaw requires fd and ripgrep, but installation did not complete.${detail}`);
  }
}

/** Configure fetch before the locked Pi runtime starts; Pi keeps ownership of installation semantics. */
export async function configureRuntimeNetwork(): Promise<NetworkRoute> {
  const route = selectNetworkRoute(process.env, await configuredRegistry());
  if (route.mode === "proxy") {
    const requireFromPi = createRequire(import.meta.resolve("@earendil-works/pi-coding-agent"));
    const undici = requireFromPi("undici") as {
      EnvHttpProxyAgent: new (options?: { httpProxy?: string; httpsProxy?: string; noProxy?: string }) => unknown;
      setGlobalDispatcher(dispatcher: unknown): void;
    };
    const allProxy = firstValue(process.env, ["ALL_PROXY", "all_proxy"]);
    const httpProxy = firstValue(process.env, ["HTTP_PROXY", "http_proxy"]) ?? allProxy;
    const httpsProxy = firstValue(process.env, ["HTTPS_PROXY", "https_proxy"]) ?? allProxy;
    const noProxy = firstValue(process.env, ["NO_PROXY", "no_proxy"]);
    undici.setGlobalDispatcher(new undici.EnvHttpProxyAgent({
      ...(httpProxy === undefined ? {} : { httpProxy }),
      ...(httpsProxy === undefined ? {} : { httpsProxy }),
      ...(noProxy === undefined ? {} : { noProxy }),
    }));
  } else if (route.mode === "mirror") {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (input, init) => originalFetch(mirrorUrl(route.mirror, input), init);
  }
  return route;
}

// Loaded with `node --import` before Pi. Direct imports in tests do not mutate fetch.
const invokedAsPreload = process.argv[1] !== undefined && isAbsolute(process.argv[1]) && process.env.PSYCLAW_NETWORK_PRELOAD === "1";
if (invokedAsPreload) {
  await configureRuntimeNetwork();
  await ensureRequiredSearchTools();
}
