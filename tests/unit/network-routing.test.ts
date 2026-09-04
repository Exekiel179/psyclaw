import { describe, expect, it } from "vitest";
import { selectNetworkRoute } from "../../src/network-routing.js";

describe("runtime network routing", () => {
  it("keeps official GitHub URLs when a proxy is configured", () => {
    expect(selectNetworkRoute({ HTTPS_PROXY: "http://127.0.0.1:7890", PSYCLAW_REGISTRY: "https://registry.npmmirror.com" })).toEqual({ mode: "proxy" });
  });

  it("uses one mirror for a mainland npm registry", () => {
    expect(selectNetworkRoute({}, "https://registry.npmmirror.com")).toEqual({ mode: "mirror", mirror: "https://gh-proxy.com/" });
  });

  it("accepts a secure explicit mirror and otherwise uses official URLs", () => {
    expect(selectNetworkRoute({ PSYCLAW_GITHUB_MIRROR: "https://mirror.example/gh" })).toEqual({ mode: "mirror", mirror: "https://mirror.example/gh/" });
    expect(selectNetworkRoute({}, "https://registry.npmjs.org/")).toEqual({ mode: "official" });
  });

  it("rejects insecure remote mirrors", () => {
    expect(() => selectNetworkRoute({ PSYCLAW_GITHUB_MIRROR: "http://mirror.example" })).toThrow(/must be HTTPS/);
  });
});
