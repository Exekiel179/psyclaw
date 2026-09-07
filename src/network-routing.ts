import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const DEFAULT_CN_GITHUB_MIRRORS = ["https://gh-proxy.com/", "https://gh-proxy.org/"] as const;
export const DEFAULT_CN_NPM_REGISTRY = "https://registry.npmmirror.com";
export const DEFAULT_OFFICIAL_NPM_REGISTRY = "https://registry.npmjs.org";
const PROXY_NAMES = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"] as const;
const CN_REGISTRY_MARKERS = ["npmmirror.com", "registry.npm.taobao.org", "mirrors.cloud.tencent.com", "mirrors.aliyun.com"];
const GITHUB_FETCH_PREFIXES = [
  "https://api.github.com/",
  "https://github.com/",
  "https://raw.githubusercontent.com/",
  "https://codeload.github.com/",
  "https://objects.githubusercontent.com/",
] as const;

export type NetworkRoute =
  | { mode: "official" }
  | { mode: "proxy" }
  | { mode: "mirror"; mirrors: string[] };

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

function isTruthyCnFlag(value: string | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim().toLocaleLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "cn";
}

function looksLikeCnRegistry(registry: string | undefined): boolean {
  if (!registry) return false;
  const lower = registry.toLocaleLowerCase();
  return CN_REGISTRY_MARKERS.some((marker) => lower.includes(marker));
}

export function selectNetworkRoute(env: NodeJS.ProcessEnv, registry?: string): NetworkRoute {
  if (firstValue(env, PROXY_NAMES)) return { mode: "proxy" };
  const explicitMirror = env.PSYCLAW_GITHUB_MIRROR?.trim();
  const effectiveRegistry = env.PSYCLAW_REGISTRY?.trim() || env.npm_config_registry?.trim() || registry?.trim();
  if (explicitMirror) return { mode: "mirror", mirrors: [normalizeMirror(explicitMirror)] };
  if (isTruthyCnFlag(env.PSYCLAW_CN) || looksLikeCnRegistry(effectiveRegistry)) {
    return { mode: "mirror", mirrors: [...DEFAULT_CN_GITHUB_MIRRORS] };
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

export async function configuredRegistry(): Promise<string | undefined> {
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

/**
 * Registry used for `psyclaw update` / check-updates install commands.
 * Mainland routes and PSYCLAW_REGISTRY prefer npmmirror; otherwise official npm.
 */
export function resolveNpmInstallRegistry(env: NodeJS.ProcessEnv = process.env, configured?: string): string {
  const explicit = env.PSYCLAW_REGISTRY?.trim() || env.npm_config_registry?.trim();
  if (explicit) return explicit.replace(/\/$/, "") + "/";
  const route = selectNetworkRoute(env, configured);
  if (route.mode === "mirror" || looksLikeCnRegistry(configured)) return `${DEFAULT_CN_NPM_REGISTRY}/`;
  return `${DEFAULT_OFFICIAL_NPM_REGISTRY}/`;
}

/** Rewrite a https://github.com/... URL through the first active GitHub mirror (for git clone). */
export function rewriteGithubHttpsThroughMirror(sourceUrl: string, route: NetworkRoute): string {
  if (route.mode !== "mirror" || route.mirrors.length === 0) return sourceUrl;
  if (!sourceUrl.startsWith("https://github.com/")) return sourceUrl;
  return `${route.mirrors[0]}${sourceUrl}`;
}

function mirrorUrl(mirror: string, input: string | URL | Request): string | URL | Request {
  const raw = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
  if (!GITHUB_FETCH_PREFIXES.some((prefix) => raw.startsWith(prefix))) return input;
  const routed = `${mirror}${raw}`;
  return input instanceof Request ? new Request(routed, input) : routed;
}

function githubUrl(input: string | URL | Request): string | undefined {
  const raw = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
  return GITHUB_FETCH_PREFIXES.some((prefix) => raw.startsWith(prefix)) ? raw : undefined;
}

function validMirrorResponse(sourceUrl: string, response: Response): boolean {
  if (!response.ok) return false;
  const contentType = response.headers.get("content-type")?.toLocaleLowerCase() ?? "";
  if (sourceUrl.startsWith("https://api.github.com/")) return contentType.includes("json");
  return !contentType.includes("text/html");
}

/** Route only GitHub management requests; Pi remains responsible for tool selection, extraction, and installation. */
export function createRoutedFetch(route: NetworkRoute, fetchImpl: typeof fetch = globalThis.fetch): typeof fetch {
  if (route.mode !== "mirror") return fetchImpl;
  return (async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const sourceUrl = githubUrl(input);
    if (sourceUrl === undefined) return fetchImpl(input, init);

    let lastResponse: Response | undefined;
    let lastError: unknown;
    for (const mirror of route.mirrors) {
      try {
        const response = await fetchImpl(mirrorUrl(mirror, input), init);
        if (validMirrorResponse(sourceUrl, response)) return response;
        lastResponse = response;
        await response.body?.cancel().catch(() => undefined);
      } catch (error) {
        lastError = error;
      }
    }
    if (lastResponse !== undefined) return lastResponse;
    throw lastError ?? new TypeError("All configured GitHub mirrors failed");
  }) as typeof fetch;
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
    globalThis.fetch = createRoutedFetch(route, globalThis.fetch);
  }
  return route;
}

// Loaded with `node --import` before Pi. Direct imports in tests do not mutate fetch.
const invokedAsPreload = process.argv[1] !== undefined && isAbsolute(process.argv[1]) && process.env.PSYCLAW_NETWORK_PRELOAD === "1";
if (invokedAsPreload) {
  await configureRuntimeNetwork();
  await ensureRequiredSearchTools();
}
