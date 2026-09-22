import { defineConfig } from "@playwright/test";

/**
 * Playwright Electron E2E. Tests launch the BUILT app
 * (pnpm build first) with `args: ['out/main/index.js']`.
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    trace: "off",
  },
});
