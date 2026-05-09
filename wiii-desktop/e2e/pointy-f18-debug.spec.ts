/**
 * F18 debug — dumps EVERY console + EventSource SSE event for one
 * single query so we can pinpoint why pointy_action SSE arrives at
 * backend but doesn't dispatch on the frontend.
 */
import { test, expect, Page } from "@playwright/test";

const APP_URL = "http://localhost:1420";
const API_KEY = "local_validation_api_key_0123456789abcdef";

async function preSeedAuth(page: Page) {
  await page.addInitScript(({ apiKey }) => {
    localStorage.setItem(
      "wiii:auth_state",
      JSON.stringify({ data: { authMode: "legacy", user: null, tokens: null } }),
    );
    localStorage.setItem(
      "wiii:app_settings",
      JSON.stringify({
        api_key: apiKey,
        user_id: "e2e-f18-debug",
        user_role: "student",
        server_url: "http://localhost:8000",
        pointy_mode: false,
      }),
    );
  }, { apiKey: API_KEY });
}

test("F18 debug — single query, dump everything", async ({ page }) => {
  test.setTimeout(300_000);
  await preSeedAuth(page);

  const allConsole: string[] = [];
  page.on("console", (msg) => {
    allConsole.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    allConsole.push(`[pageerror] ${err.message}`);
  });

  // Capture network — log SSE response chunks for /chat/stream/v3
  const sseChunks: string[] = [];
  page.on("response", async (resp) => {
    if (resp.url().includes("/chat/stream")) {
      console.log(`[NETWORK] ${resp.status()} ${resp.url()}`);
    }
  });

  await page.goto(APP_URL);
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
    { timeout: 15000 },
  );
  await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 });

  const textarea = page.locator('textarea[data-wiii-id="chat-textarea"]').first();
  await textarea.fill("@wiii-pointy nút gửi tin nhắn ở đâu");
  await textarea.press("Enter");

  await page.waitForFunction(
    () => document.querySelector('button[aria-label="Dừng tạo phản hồi"]') === null,
    { timeout: 150_000, polling: 500 },
  );
  await page.waitForTimeout(3000);

  console.log("\n========= ALL CONSOLE OUTPUT =========");
  for (const line of allConsole) {
    console.log(line);
  }
  console.log(`\nTotal: ${allConsole.length} log lines`);
  console.log(`POINTY logs: ${allConsole.filter((l) => l.includes("POINTY")).length}`);
  console.log(`SSE logs: ${allConsole.filter((l) => l.toLowerCase().includes("sse")).length}`);

  expect(true).toBe(true); // dummy assertion
});
