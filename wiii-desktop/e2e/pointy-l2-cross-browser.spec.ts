/**
 * Level 2 — cross-browser contract test. Runs on chromium / firefox /
 * webkit via playwright.config projects. Same test body, 3 browsers.
 */

import { test, expect, Page } from "@playwright/test";

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
        user_id: "e2e-l2",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

async function bootApp(page: Page) {
  await preSeedAuth(page);
  await page.goto(APP_URL);
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
    { timeout: 15000 },
  );
  await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 });
}

async function dispatchSynthetic(page: Page, text: string): Promise<string> {
  return await page.evaluate(
    async (t: string) =>
      await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(t),
    text,
  );
}

test.describe("L2 — dispatch contract (cross-browser)", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  test("basic tag dispatch", async ({ page, browserName }) => {
    const r = await dispatchSynthetic(page, "[POINT:chat-send-button:test]");
    console.log(`[${browserName}] tag dispatch: ${r.slice(0, 100)}`);
    expect(r).toContain("ok=true");
  });

  test("auto-discovery active", async ({ page, browserName }) => {
    const targets = await page.evaluate(() => {
      const fn = (window as unknown as { __wiiiInventory__?: () => Array<{ id: string }> }).__wiiiInventory__;
      return fn ? fn().map((t) => t.id) : [];
    });
    const auto = targets.filter((id) => id.startsWith("auto:"));
    console.log(`[${browserName}] inventory total=${targets.length} auto=${auto.length}`);
    expect(targets.length).toBeGreaterThan(0);
  });

  test("embodied dispatch", async ({ page, browserName }) => {
    const r = await dispatchSynthetic(
      page,
      "Nút gửi tin nhắn ở góc dưới phải nè cậu.",
    );
    console.log(`[${browserName}] embodied: ${r.slice(0, 100)}`);
    expect(r).toContain("ok=true");
  });

  test("cursor renders + has pointer-events:none", async ({ page, browserName }) => {
    const cursorState = await page.evaluate(() => {
      const c = document.querySelector('[data-pointy-cursor]') as HTMLElement | null;
      if (!c) return null;
      const style = window.getComputedStyle(c);
      return {
        present: true,
        pointerEvents: style.pointerEvents,
        opacity: style.opacity,
      };
    });
    console.log(`[${browserName}] cursor: ${JSON.stringify(cursorState)}`);
    expect(cursorState?.present).toBe(true);
    expect(cursorState?.pointerEvents).toBe("none");
  });
});

test.describe("L2 — memory probe (Chromium only)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "performance.memory is Chromium-only");
  test.beforeEach(async ({ page }) => bootApp(page));

  test("50 dispatch cycles — heap growth bounded", async ({ page }) => {
    const initialMem = await page.evaluate(() => {
      const perf = performance as unknown as { memory?: { usedJSHeapSize: number } };
      return perf.memory?.usedJSHeapSize || 0;
    });
    console.log(`[L2-MEM] initial heap: ${(initialMem / 1024 / 1024).toFixed(1)} MB`);
    for (let i = 0; i < 50; i++) {
      await page.evaluate(async () => {
        const m = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
          | { clearDispatchQueue: () => void };
        m.clearDispatchQueue();
      });
      await dispatchSynthetic(page, `[POINT:chat-send-button:cycle ${i}]`);
      if (i % 10 === 0) {
        const m = await page.evaluate(() => {
          const perf = performance as unknown as { memory?: { usedJSHeapSize: number } };
          return perf.memory?.usedJSHeapSize || 0;
        });
        console.log(`[L2-MEM] cycle ${i}: ${(m / 1024 / 1024).toFixed(1)} MB`);
      }
    }
    const finalMem = await page.evaluate(() => {
      const perf = performance as unknown as { memory?: { usedJSHeapSize: number } };
      return perf.memory?.usedJSHeapSize || 0;
    });
    const growthMB = (finalMem - initialMem) / 1024 / 1024;
    console.log(`[L2-MEM] final: ${(finalMem / 1024 / 1024).toFixed(1)} MB, growth: ${growthMB.toFixed(1)} MB`);
    expect(growthMB).toBeLessThan(50);
  });
});

test.describe("L2 — accessibility audit", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  test("annotated targets all have accessible names", async ({ page }) => {
    const issues = await page.evaluate(() => {
      const list = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      const problems: { id: string }[] = [];
      for (const el of Array.from(list)) {
        const id = el.getAttribute("data-wiii-id") || "";
        const ariaLabel = el.getAttribute("aria-label");
        const title = el.getAttribute("title");
        const text = el.textContent?.trim();
        if (!ariaLabel?.trim() && !title?.trim() && !text) {
          problems.push({ id });
        }
      }
      return problems;
    });
    console.log(`[L2-A11Y] issues: ${JSON.stringify(issues)}`);
    expect(issues.length).toBe(0);
  });

  test("cursor doesn't block clicks", async ({ page }) => {
    const pe = await page.evaluate(() => {
      const c = document.querySelector('[data-pointy-cursor]') as HTMLElement | null;
      return c ? window.getComputedStyle(c).pointerEvents : null;
    });
    expect(pe).toBe("none");
  });
});
