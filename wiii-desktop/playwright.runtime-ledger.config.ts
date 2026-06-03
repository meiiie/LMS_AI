import { defineConfig } from "@playwright/test";

const frontendPort = process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420";
const baseURL =
  process.env.WIII_PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./playwright",
  testMatch: ["runtime-ledger-panel.spec.ts"],
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [["list"]],
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    viewport: { width: 1440, height: 1100 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "node scripts/start-visual-frontend.mjs",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
