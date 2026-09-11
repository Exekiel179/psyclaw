import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const DEFAULT_CN_GITHUB_MIRRORS = ["https://gh-proxy.com/", "https://gh-proxy.org/"] as const;
const PROXY_NAMES = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"] as const;
const CN_REGISTRY_MARKERS = ["npmmirror.com", "registry.npm.taobao.org", "mirrors.cloud.tencent.com", "mirrors.aliyun.com"];

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

export function selectNetworkRoute(env: NodeJS.ProcessEnv, registry?: string): NetworkRoute {
  if (firstValue(env, PROXY_NAMES)) return { mode: "proxy" };
  const explicitMirror = env.PSYCLAW_GITHUB_MIRROR?.trim();
  const effectiveRegistry = env.PSYCLAW_REGISTRY?.trim() || env.npm_config_registry?.trim() || registry?.trim();
  if (explicitMirror) return { mode: "mirror", mirrors: [normalizeMirror(explicitMirror)] };
  if (effectiveRegistry && CN_REGISTRY_MARKERS.some((marker) => effectiveRegistry.toLocaleLowerCase().includes(marker))) {
    return { mode: "mirror", mirrors: [...DEFAULT_CN_GITHUB_MIRRORS] };
  }
  return { mode: "official" };
}

/** Resolve the active route from env + npmrc/package install provenance. */
export async function resolveNetworkRoute(env: NodeJS.ProcessEnv = process.env): Promise<NetworkRoute> {
  return selectNetworkRoute(env, await configuredRegistry());
}

/**
 * Git remotes to try when cloning a GitHub repo.
 * Mirror mode prefixes the canonical GitHub HTTPS URL with each configured
 * mainland mirror (same convention as createRoutedFetch). Proxy/official keep
 * the canonical URL so git can use HTTPS_PROXY / direct GitHub access.
 */
export function githubCloneUrlCandidates(sourceUrl: string, route: NetworkRoute): string[] {
  if (!sourceUrl.startsWith("https://github.com/")) {
    throw new Error(`GitHub clone URL must start with https://github.com/: ${sourceUrl}`);
  }
  if (route.mode !== "mirror") return [sourceUrl];
  return route.mirrors.map((mirror) => `${mirror}${sourceUrl}`);
}

/**
 * Canonical GitHub source-archive URL for a branch, tag, or commit.
 * Prefer this over git smart-HTTP through mirrors: archive downloads reuse the
 * same routed fetch path already proven for Release assets.
 */
export function githubArchiveUrl(sourceUrl: string, ref: string): string {
  if (!sourceUrl.startsWith("https://github.com/")) {
    throw new Error(`GitHub archive URL must start with https://github.com/: ${sourceUrl}`);
  }
  if (!ref.trim()) throw new Error("GitHub archive ref is required");
  const cleaned = sourceUrl.replace(/\.git$/i, "").replace(/\/$/, "");
  return `${cleaned}/archive/${encodeURIComponent(ref)}.tar.gz`;
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

function githubUrl(input: string | URL | Request): string | undefined {
  const raw = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
  return raw.startsWith("https://api.github.com/") || raw.startsWith("https://github.com/") ? raw : undefined;
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
