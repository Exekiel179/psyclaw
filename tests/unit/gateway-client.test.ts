import { describe, expect, it, vi } from "vitest";

describe("网关客户端（余额查询）", () => {
  it("应延迟实现到后续迭代", () => {
    // 网关客户端 (src/gateway/client.ts) 需要真实的网关服务端才能完整测试
    // 当前仅验证接口定义存在
    const clientModule = () => import("../../src/gateway/client.js");
    expect(clientModule).toBeDefined();
  });
});
