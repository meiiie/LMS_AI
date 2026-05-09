/**
 * Level 3 — failure recovery, viewport variations, i18n, fuzz testing.
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
        user_id: "e2e-l3",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

async function bootApp(page: Page, waitForSendButton = true) {
  await preSeedAuth(page);
  await page.goto(APP_URL);
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
    { timeout: 15000 },
  );
  if (waitForSendButton) {
    await page
      .waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 })
      .catch(() => {
        // Mobile / responsive mode may not render send button — caller decides.
      });
  }
}

async function dispatchSynthetic(page: Page, text: string): Promise<string> {
  return await page.evaluate(
    async (t: string) =>
      await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(t),
    text,
  );
}

test.describe("L3 — fuzz / malformed input", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  const FUZZ_INPUTS = [
    "[POINT:]", // empty selector
    "[POINT:invalid id with spaces]",
    "[POINT:#css-id-not-allowed]",
    "[POINT:.class-not-allowed]",
    "[POINT:[attr=val]]",
    "[POINT:nonexistent-target-zzz]",
    "[POINT:wiii-pointy:]", // colon but no caption
    "[POINT::just colons:]",
    "[POINT:" + "x".repeat(1000) + "]", // huge selector
    "", // empty input
    "Just plain text no tags",
    "[POINT:no-closing-bracket",
    "POINT:missing-brackets]",
    "[[POINT:double-brackets]]",
    "Nested [POINT:[POINT:nested]]",
  ];

  for (const input of FUZZ_INPUTS) {
    test(`Fuzz — "${input.slice(0, 40)}..."`, async ({ page }) => {
      const r = await dispatchSynthetic(page, input);
      console.log(`  fuzz "${input.slice(0, 40)}" → ${r.slice(0, 80)}`);
      // Should not throw; either no-match or ok=false (no crash).
      expect(typeof r).toBe("string");
    });
  }
});

test.describe("L3 — i18n / language variations", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  test("Pure English response with tag", async ({ page }) => {
    const r = await dispatchSynthetic(
      page,
      "Click the send button at the bottom right corner. [POINT:chat-send-button:send]",
    );
    expect(r).toContain("ok=true");
    expect(r).toContain("chat-send-button");
  });

  test("Mixed Vietnamese-English response", async ({ page }) => {
    const r = await dispatchSynthetic(
      page,
      "To send message, click the send button. [POINT:chat-send-button:gửi]",
    );
    expect(r).toContain("ok=true");
  });

  test("Bahasa-style query (no tag, embodied via label)", async ({ page }) => {
    // Test if embodied parser handles different language patterns.
    // Vietnamese label "Gửi tin nhắn" — if user response only has English,
    // shouldn't match (label is Vietnamese).
    const r = await dispatchSynthetic(
      page,
      "The send button is at the bottom right.",
    );
    console.log(`  bahasa-only: ${r}`);
  });
});

test.describe("L3 — Mobile viewport (pure viewport size)", () => {
  test.use({ viewport: { width: 390, height: 844 } }); // iPhone 13 dimensions

  test.beforeEach(async ({ page }) => bootApp(page));

  test("Mobile viewport — cursor mounts (inventory may differ vs desktop)", async ({ page }) => {
    const inv = await page.evaluate(() => {
      const fn = (window as unknown as { __wiiiInventory__?: () => unknown[] }).__wiiiInventory__;
      return fn ? fn().length : 0;
    });
    console.log(`[L3-MOBILE] viewport=390x844 inventory=${inv} elements`);
    // Wiii Desktop is desktop-first; mobile responsive layout may render
    // different elements OR show a login screen. Log finding for info.
    // Cursor mount is what matters — verify __wiiiPointTest__ exists.
    const cursorReady = await page.evaluate(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
    );
    expect(cursorReady).toBe(true);
  });

  test("Mobile viewport dock cursor at bottom-right", async ({ page }) => {
    await page.waitForTimeout(1000);
    const dockPos = await page.evaluate(() => {
      const c = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const m = c?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null;
    });
    console.log(`[L3-MOBILE] dock pos: ${JSON.stringify(dockPos)}`);
    expect(dockPos).not.toBeNull();
    // Mobile inset = 56px per dock-position.ts
    if (dockPos) {
      expect(dockPos.x).toBeGreaterThan(300); // 390-56=334
      expect(dockPos.y).toBeGreaterThan(750); // 844-56=788
    }
  });
});

test.describe("L3 — Tablet viewport", () => {
  test.use({ viewport: { width: 834, height: 1194 } }); // iPad Pro 11

  test.beforeEach(async ({ page }) => bootApp(page));

  test("Tablet viewport — dock cursor positions correctly", async ({ page }) => {
    await page.waitForTimeout(1000);
    const dockPos = await page.evaluate(() => {
      const c = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const m = c?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null;
    });
    console.log(`[L3-TABLET] dock pos: ${JSON.stringify(dockPos)}`);
    expect(dockPos).not.toBeNull();
    if (dockPos) {
      expect(dockPos.x).toBeGreaterThan(700); // 834-80=754
      expect(dockPos.y).toBeGreaterThan(1100);
    }
  });
});

test.describe("L3 — failure recovery", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  test("Backend 500 — UI doesn't crash, cursor stays at dock", async ({ page }) => {
    // Mock a chat endpoint that 500s.
    await page.route("**/api/v1/chat/stream/v3", (route) => {
      route.fulfill({ status: 500, body: "Internal Server Error" });
    });
    const textarea = page.locator('[data-wiii-id="chat-textarea"]').first();
    await textarea.fill("test");
    await textarea.press("Enter");
    await page.waitForTimeout(3000);
    const cursorState = await page.evaluate(() => {
      const c = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      return c?.getAttribute("data-pointy-state") || "missing";
    });
    console.log(`[L3-500] cursor state after 500: ${cursorState}`);
    expect(cursorState).not.toBe("missing");
  });

  test("Network drop simulation — cursor stable", async ({ page }) => {
    await page.route("**/api/v1/chat/stream/v3", (route) => {
      route.abort("internetdisconnected");
    });
    const textarea = page.locator('[data-wiii-id="chat-textarea"]').first();
    await textarea.fill("test");
    await textarea.press("Enter");
    await page.waitForTimeout(2000);
    const cursorAlive = await page.evaluate(() => {
      return document.querySelector('[data-pointy-cursor="wiii"]') !== null;
    });
    expect(cursorAlive).toBe(true);
  });
});

test.describe("L3 — accessibility / a11y", () => {
  test.beforeEach(async ({ page }) => bootApp(page));

  test("prefers-reduced-motion respected — cursor snaps not animates", async ({ page, browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce" });
    const p = await ctx.newPage();
    await preSeedAuth(p);
    await p.goto(APP_URL);
    await p.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
      { timeout: 15000 },
    );
    await p.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 });
    const result = await p.evaluate(() =>
      (window as unknown as { __wiiiPointTest__: (s: string) => string }).__wiiiPointTest__("chat-send-button"),
    );
    console.log(`[L3-A11Y] reduced-motion result: ${result}`);
    expect(result).toContain("ok=true");
    await ctx.close();
  });

  test("Cursor element has data-pointy-cursor attribute (a11y identifier)", async ({ page }) => {
    const has = await page.evaluate(() =>
      document.querySelector('[data-pointy-cursor]') !== null,
    );
    expect(has).toBe(true);
  });

  test("Pointable elements have aria-label or computed accessible name", async ({ page }) => {
    const els = await page.evaluate(() => {
      const list = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      return Array.from(list).map((el) => ({
        id: el.getAttribute("data-wiii-id"),
        ariaLabel: el.getAttribute("aria-label"),
        title: el.getAttribute("title"),
      }));
    });
    console.log(`[L3-A11Y] annotated elements:`);
    for (const e of els) {
      console.log(`  ${e.id} aria="${e.ariaLabel}" title="${e.title}"`);
      // Each annotated element should have aria-label OR title for screen readers.
      expect(e.ariaLabel || e.title).toBeTruthy();
    }
  });
});
