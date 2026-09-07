import { describe, expect, it } from "vitest";
import {
  createRoutedFetch,
  resolveNpmInstallRegistry,
  rewriteGithubHttpsThroughMirror,
  selectNetworkRoute,
} from "../../src/network-routing.js";

describe("runtime network routing", () => {
  it("keeps official GitHub URLs when a proxy is configured", () => {
    expect(selectNetworkRoute({ HTTPS_PROXY: "http://127.0.0.1:7890", PSYCLAW_REGISTRY: "https://registry.npmmirror.com" })).toEqual({ mode: "proxy" });
  });

  it("uses mainland mirrors for a mainland npm registry", () => {
    expect(selectNetworkRoute({}, "https://registry.npmmirror.com")).toEqual({
      mode: "mirror",
      mirrors: ["https://gh-proxy.com/", "https://gh-proxy.org/"],
    });
  });

  it("enables mainland mirrors when PSYCLAW_CN=1", () => {
    expect(selectNetworkRoute({ PSYCLAW_CN: "1" })).toEqual({
      mode: "mirror",
      mirrors: ["https://gh-proxy.com/", "https://gh-proxy.org/"],
    });
  });

  it("accepts a secure explicit mirror and otherwise uses official URLs", () => {
    expect(selectNetworkRoute({ PSYCLAW_GITHUB_MIRROR: "https://mirror.example/gh" })).toEqual({ mode: "mirror", mirrors: ["https://mirror.example/gh/"] });
    expect(selectNetworkRoute({}, "https://registry.npmjs.org/")).toEqual({ mode: "official" });
  });

  it("resolves npm install registry for mainland vs official", () => {
    expect(resolveNpmInstallRegistry({ PSYCLAW_REGISTRY: "https://registry.npmmirror.com/" })).toBe("https://registry.npmmirror.com/");
    expect(resolveNpmInstallRegistry({ PSYCLAW_CN: "1" })).toBe("https://registry.npmmirror.com/");
    expect(resolveNpmInstallRegistry({}, "https://registry.npmjs.org/")).toBe("https://registry.npmjs.org/");
  });

  it("rewrites GitHub clone URLs through the active mirror", () => {
    expect(rewriteGithubHttpsThroughMirror("https://github.com/a/b.git", { mode: "official" })).toBe("https://github.com/a/b.git");
    expect(rewriteGithubHttpsThroughMirror("https://github.com/a/b.git", {
      mode: "mirror",
      mirrors: ["https://gh-proxy.com/"],
    })).toBe("https://gh-proxy.com/https://github.com/a/b.git");
  });

  it("rejects insecure remote mirrors", () => {
    expect(() => selectNetworkRoute({ PSYCLAW_GITHUB_MIRROR: "http://mirror.example" })).toThrow(/must be HTTPS/);
  });

  it("tries only mainland mirrors when the first mirror cannot be reached", async () => {
    const urls: string[] = [];
    const fetchImpl = async (input: string | URL | Request): Promise<Response> => {
      const url = input instanceof Request ? input.url : input.toString();
      urls.push(url);
      if (url.startsWith("https://gh-proxy.com/")) throw new TypeError("fetch failed");
      return new Response('{"tag_name":"v10.5.0"}', { status: 200, headers: { "content-type": "application/json" } });
    };
    const routedFetch = createRoutedFetch(
      { mode: "mirror", mirrors: ["https://gh-proxy.com/", "https://gh-proxy.org/"] },
      fetchImpl as typeof fetch,
    );

    const response = await routedFetch("https://api.github.com/repos/sharkdp/fd/releases/latest");

    expect(await response.json()).toEqual({ tag_name: "v10.5.0" });
    expect(urls).toEqual([
      "https://gh-proxy.com/https://api.github.com/repos/sharkdp/fd/releases/latest",
      "https://gh-proxy.org/https://api.github.com/repos/sharkdp/fd/releases/latest",
    ]);
  });

  it("routes raw.githubusercontent.com through mirrors", async () => {
    const urls: string[] = [];
    const fetchImpl = async (input: string | URL | Request): Promise<Response> => {
      urls.push(input instanceof Request ? input.url : input.toString());
      return new Response("ok", { status: 200, headers: { "content-type": "text/plain" } });
    };
    const routedFetch = createRoutedFetch(
      { mode: "mirror", mirrors: ["https://gh-proxy.com/"] },
      fetchImpl as typeof fetch,
    );
    await routedFetch("https://raw.githubusercontent.com/owner/repo/main/file.txt");
    expect(urls).toEqual(["https://gh-proxy.com/https://raw.githubusercontent.com/owner/repo/main/file.txt"]);
  });

  it("rejects a mirror HTML page instead of passing it to Pi as a release archive", async () => {
    const urls: string[] = [];
    const fetchImpl = async (input: string | URL | Request): Promise<Response> => {
      const url = input instanceof Request ? input.url : input.toString();
      urls.push(url);
      if (url.startsWith("https://gh-proxy.com/")) {
        return new Response("<!doctype html><title>mirror unavailable</title>", {
          status: 200,
          headers: { "content-type": "text/html" },
        });
      }
      return new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
        status: 200,
        headers: { "content-type": "application/octet-stream" },
      });
    };
    const routedFetch = createRoutedFetch(
      { mode: "mirror", mirrors: ["https://gh-proxy.com/", "https://gh-proxy.org/"] },
      fetchImpl as typeof fetch,
    );

    const response = await routedFetch("https://github.com/example/tool/releases/download/v1/tool.zip");

    expect(Array.from(new Uint8Array(await response.arrayBuffer()))).toEqual([0x50, 0x4b, 0x03, 0x04]);
    expect(urls).toHaveLength(2);
    expect(urls.every((url) => !url.startsWith("https://github.com/"))).toBe(true);
  });

  it("leaves official GitHub URLs unchanged outside mirror mode", async () => {
    const urls: string[] = [];
    const fetchImpl = async (input: string | URL | Request): Promise<Response> => {
      urls.push(input instanceof Request ? input.url : input.toString());
      return new Response("ok");
    };
    const routedFetch = createRoutedFetch({ mode: "official" }, fetchImpl as typeof fetch);

    await routedFetch("https://github.com/example/tool/releases/download/v1/tool.zip");

    expect(urls).toEqual(["https://github.com/example/tool/releases/download/v1/tool.zip"]);
  });
});
