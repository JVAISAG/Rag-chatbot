import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: process.env.WORKSPACE_E2E_URL ?? "http://127.0.0.1:3000",
    headless: true,
    launchOptions: { executablePath: process.env.PLAYWRIGHT_BROWSER_EXECUTABLE || undefined },
    trace: "retain-on-failure",
  },
});
