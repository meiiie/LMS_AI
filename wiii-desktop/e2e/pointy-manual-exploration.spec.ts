/**
 * Manual exploration — visual evidence Wiii Pointy works for diverse
 * realistic scenarios. Captures screenshots showing cursor at various
 * positions in response to different queries.
 *
 * Saves screenshots to test-results/manual-exploration/ for visual
 * inspection. Each test injects a synthetic AI response (skip backend
 * latency) and captures cursor position evidence.
 */

import { test, Page } from "@playwright/test";

const APP_URL = "http://localhost:1420";
const API_KEY = "local_validation_api_key_0123456789abcdef";

async function preSeedAuth(page: Page) {
  await page.addInitScript((apiKey) => {
    localStorage.setItem(
      "wiii:auth_state",
      JSON.stringify({ data: { authMode: "legacy", user: null, tokens: null } }),
    );
    localStorage.setItem(
      "wiii:app_settings",
      JSON.stringify({
        api_key: apiKey,
        user_id: "e2e-manual",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

interface Scene {
  name: string;
  syntheticResponse: string;
  expectedTargetIds: string[];
}

const SCENES: Scene[] = [
  {
    name: "01-baseline-dock",
    syntheticResponse: "", // no dispatch — capture dock state
    expectedTargetIds: [],
  },
  {
    name: "02-tag-single",
    syntheticResponse: "Đây nè cậu! [POINT:chat-send-button:nút gửi tin nhắn]",
    expectedTargetIds: ["chat-send-button"],
  },
  {
    name: "03-embodied-vi",
    syntheticResponse: "Nút gửi tin nhắn nằm ở góc dưới phải nè cậu, hình mũi tên xanh dương.",
    expectedTargetIds: ["chat-send-button"],
  },
  {
    name: "04-embodied-en",
    syntheticResponse: "Click on the Gửi tin nhắn button at the bottom right corner.",
    expectedTargetIds: ["chat-send-button"],
  },
  {
    name: "05-no-diacritic",
    syntheticResponse: "Nut gui tin nhan o goc duoi phai man hinh nha cau.",
    expectedTargetIds: ["chat-send-button"],
  },
  {
    name: "06-multistep-tags",
    syntheticResponse:
      "Bước 1: vào Cài đặt [POINT:settings-link:Cài đặt]. Bước 2: Gửi [POINT:chat-send-button:Gửi].",
    expectedTargetIds: ["settings-link", "chat-send-button"],
  },
  {
    name: "07-negative-greeting",
    syntheticResponse: "Chào cậu! Hôm nay cậu khỏe không?",
    expectedTargetIds: [], // expect cursor stays at dock
  },
  {
    name: "08-negative-explanation",
    syntheticResponse: "Tin nhắn là phương tiện giao tiếp text giữa hai người.",
    expectedTargetIds: [],
  },
  {
    name: "09-mixed-prose-then-tag",
    syntheticResponse:
      "Để gửi tin nhắn, cậu nhập text ở ô soạn rồi bấm nút mũi tên xanh ở góc phải. Đây nè cậu. [POINT:chat-send-button:đây]",
    expectedTargetIds: ["chat-send-button"],
  },
  {
    name: "10-very-long-response",
    syntheticResponse: `Cậu hỏi về cách gửi tin nhắn — mình giải thích chi tiết nha.

Trước hết, ô chat ở dưới cùng màn hình là nơi cậu nhập nội dung. Cậu có thể gõ tiếng Việt có dấu, nhấn Enter để xuống dòng (Shift+Enter), và đính kèm ảnh nếu cần.

Sau khi nhập xong, cậu nhìn sang góc phải dưới — Nút gửi tin nhắn ở đó với hình mũi tên xanh dương. Click vào nó để gửi.

Có gì cậu cần hỏi thêm không?`,
    expectedTargetIds: ["chat-send-button"],
  },
];

test.describe("Wiii Pointy v7.0 — manual exploration scenes", () => {
  test.beforeEach(async ({ page }) => {
    await preSeedAuth(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 });
    // Reset queue between scenes.
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue?: () => void }
        | undefined;
      queueMod?.clearDispatchQueue?.();
    });
  });

  for (const scene of SCENES) {
    test(`Scene ${scene.name}`, async ({ page }, testInfo) => {
      const logs: string[] = [];
      page.on("console", (msg) => {
        if (msg.text().includes("POINTY")) logs.push(msg.text());
      });

      // Dispatch the synthetic response.
      let dispatchResult = "";
      if (scene.syntheticResponse) {
        dispatchResult = await page.evaluate(
          async (text: string) =>
            await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(text),
          scene.syntheticResponse,
        );
      }

      // Wait for cursor animation to settle (min-jerk takes ~300-600ms).
      await page.waitForTimeout(2000);

      // Capture cursor state + position.
      const cursorState = await page.evaluate(() => {
        const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
        const m = el?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
        return {
          state: el?.getAttribute("data-pointy-state") || "unknown",
          pos: m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null,
          targetIds: Array.from(document.querySelectorAll<HTMLElement>("[data-wiii-id]")).map((el) =>
            el.getAttribute("data-wiii-id") || "",
          ),
        };
      });

      // Take screenshot.
      const screenshotPath = `test-results/manual-exploration/${scene.name}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: false });

      // Log + attach evidence.
      console.log(`\n=== Scene ${scene.name} ===`);
      console.log(`  response: "${scene.syntheticResponse.slice(0, 100)}..."`);
      console.log(`  dispatch: ${dispatchResult || "(no dispatch — baseline)"}`);
      console.log(`  cursor state: ${cursorState.state} @ ${JSON.stringify(cursorState.pos)}`);
      console.log(`  POINTY logs: ${logs.length} entries`);
      logs.forEach((l) => console.log(`    ${l.slice(0, 200)}`));
      console.log(`  screenshot: ${screenshotPath}`);

      // Attach to test report.
      await testInfo.attach("dispatch-result", {
        body: JSON.stringify({ dispatchResult, cursorState, logs }, null, 2),
        contentType: "application/json",
      });
    });
  }
});
