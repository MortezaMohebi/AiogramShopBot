import { defineConfig } from "@playwright/test";

/** Test only the loopback-published, internal-CA HTTPS development lab. */
export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  retries: 0,
  timeout: 45_000,
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.LAB_BROWSER_BASE_URL ?? "https://localhost:8443",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    browserName: "chromium",
  },
  projects: [
    {
      name: "mobile-320",
      use: { viewport: { width: 320, height: 800 } },
    },
    {
      name: "tablet-768",
      use: { viewport: { width: 768, height: 1024 } },
    },
    {
      name: "desktop-1440",
      use: { viewport: { width: 1440, height: 900 } },
    },
  ],
});
