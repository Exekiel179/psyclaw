import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    setupFiles: ["tests/setup.ts", "tests/setup-env.ts"],
    environment: "node",
    passWithNoTests: false,
  },
});
