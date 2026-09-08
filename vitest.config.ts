import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    passWithNoTests: false,
    setupFiles: ["tests/setup-env.ts"],
  },
});
