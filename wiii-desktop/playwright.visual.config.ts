import { defineConfig } from "@playwright/test";

const frontendPort = process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420";
const backendPort = process.env.WIII_PLAYWRIGHT_BACKEND_PORT || "8000";
const baseURL =
  process.env.WIII_PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${frontendPort}`;
const backendURL =
  process.env.WIII_PLAYWRIGHT_SERVER_URL || `http://127.0.0.1:${backendPort}`;

export default defineConfig({
  testDir: "./playwright",
  testMatch: [
    "chat-baseline-acceptance.spec.ts",
    "local-chat-harness.spec.ts",
    "visual-runtime.spec.ts",
    "code-studio-runtime.spec.ts",
  ],
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [["list"]],
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "node scripts/start-visual-backend.mjs",
      url: `${backendURL}/api/v1/health/live`,
      reuseExistingServer: true,
      timeout: 180_000,
    },
    {
      command: "node scripts/start-visual-frontend.mjs",
      url: baseURL,
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});
