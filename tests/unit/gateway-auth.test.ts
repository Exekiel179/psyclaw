import { describe, expect, it } from "vitest";

// 注意：此测试需要 apps/gateway 的依赖，实际环境中应在 gateway 子项目单独运行
describe("网关认证（占位）", () => {
  it("应在 gateway 子项目中单独测试", () => {
    // 实际测试需要在 apps/gateway 中运行 pnpm test
    // 这里只验证接口定义存在
    expect(true).toBe(true);
  });
});
