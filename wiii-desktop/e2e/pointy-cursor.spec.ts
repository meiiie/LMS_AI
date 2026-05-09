/**
 * E2E Playwright test — Wiii Pointy v5.0 cursor dispatch.
 *
 * Tests 3 isolation levels for "cursor doesn't move" symptom:
 *   1. Motion engine (window.__wiiiPointTest__ direct dispatch)
 *   2. Inline tag parser (synthetic [POINT:...] tag injection)
 *   3. Embodied parser (real chat answer with intent + label)
 *
 * Captures all `console.warn` output to identify which layer breaks.
 */

import { test, expect, Page } from "@playwright/test";

const APP_URL = "http://localhost:1420";
const API_KEY = "local_validation_api_key_0123456789abcdef";

// Helper — pre-seed legacy auth so we skip OAuth flow.
// Storage shape verified by reading auth-store.ts + settings-store.ts:
//   - Auth: localStorage["wiii:auth_state"] = {"data": {authMode, user, tokens}}
//   - Settings: localStorage["wiii:app_settings"] = AppSettings (NOT nested)
async function preSeedAuth(page: Page) {
  await page.addInitScript((apiKey) => {
    const authStore = {
      data: { authMode: "legacy", user: null, tokens: null },
    };
    localStorage.setItem("wiii:auth_state", JSON.stringify(authStore));

    const settings = {
      api_key: apiKey,
      user_id: "e2e-user-fixed-id",
      user_role: "student",
      server_url: "http://127.0.0.1:65535",
    };
    localStorage.setItem("wiii:app_settings", JSON.stringify(settings));
  }, API_KEY);
}

// Helper — capture all console.warn so we can assert on diagnostic output.
function attachConsoleCapture(page: Page): { logs: string[] } {
  const logs: string[] = [];
  page.on("console", (msg) => {
    const text = `[${msg.type()}] ${msg.text()}`;
    logs.push(text);
  });
  return { logs };
}

test.describe("Wiii Pointy v5.0 — cursor dispatch isolation", () => {
  test.beforeEach(async ({ page }) => {
    await preSeedAuth(page);
  });

  test("01 — App boots, dock cursor mounted", async ({ page }) => {
    const { logs } = attachConsoleCapture(page);
    await page.goto(APP_URL);
    // Wait for pointy host to mount.
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
      { timeout: 15000 },
    );
    // Cursor element should exist.
    const cursorCount = await page.locator('[data-pointy-cursor="wiii"]').count();
    expect(cursorCount).toBe(1);
    console.log(`[E2E] cursor mounted. Recent console logs:\n${logs.slice(-10).join("\n")}`);
  });

  test("02 — Motion isolation: __wiiiPointTest__ moves cursor", async ({ page }) => {
    const { logs } = attachConsoleCapture(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
      { timeout: 15000 },
    );
    // Wait for chat-send-button to be in DOM.
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 5000 });
    // Capture cursor position BEFORE.
    const beforePos = await page.evaluate(() => {
      const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const m = el?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null;
    });
    // Trigger manual dispatch.
    const result = await page.evaluate(() => {
      return (window as unknown as { __wiiiPointTest__: (s: string) => string }).__wiiiPointTest__(
        "chat-send-button",
      );
    });
    console.log(`[E2E] dispatch result: ${result}`);
    // Wait for animation — cursor should reach target within 2s.
    await page.waitForTimeout(2000);
    const afterPos = await page.evaluate(() => {
      const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const m = el?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null;
    });
    // Get target rect for comparison.
    const targetRect = await page.evaluate(() => {
      const el = document.querySelector('[data-wiii-id="chat-send-button"]');
      const r = el?.getBoundingClientRect();
      return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
    });
    console.log(`[E2E] before pos: ${JSON.stringify(beforePos)}`);
    console.log(`[E2E] after pos:  ${JSON.stringify(afterPos)}`);
    console.log(`[E2E] target pos: ${JSON.stringify(targetRect)}`);
    console.log(`[E2E] POINTY logs:\n${logs.filter((l) => l.includes("POINTY")).join("\n")}`);

    // Cursor should have moved AWAY from dock toward target.
    expect(beforePos).not.toBeNull();
    expect(afterPos).not.toBeNull();
    expect(targetRect).not.toBeNull();
    if (beforePos && afterPos && targetRect) {
      // afterPos should be closer to targetRect than beforePos was.
      const distBefore = Math.hypot(beforePos.x - targetRect.x, beforePos.y - targetRect.y);
      const distAfter = Math.hypot(afterPos.x - targetRect.x, afterPos.y - targetRect.y);
      console.log(`[E2E] dist before=${distBefore.toFixed(0)} after=${distAfter.toFixed(0)}`);
      expect(distAfter).toBeLessThan(distBefore);
      // Within 100px of target (cursor tip offset + integer rounding).
      expect(distAfter).toBeLessThan(100);
    }
  });

  test("03 — Embodied parser isolation: synthetic onDone fires dispatch", async ({ page }) => {
    const { logs } = attachConsoleCapture(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 5000 });
    // Run via integration.ts-exposed __wiiiEmbodiedTest__ — uses SAME
    // module instance as production onDone path. Avoids module-dup
    // issues from raw `import("/src/.../api.ts")` in browser.
    const result = await page.evaluate(async () => {
      const fakeAnswer =
        "Nút gửi tin nhắn ở góc dưới bên phải màn hình nè cậu, hình mũi tên xanh dương đó.";
      return await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(fakeAnswer);
    });
    console.log(`[E2E] embodied dispatch result: ${result}`);
    expect(result).toContain("embodied");
    expect(result).toContain("ok=true");

    await page.waitForTimeout(2000);
    const targetCenter = await page.evaluate(() => {
      const el = document.querySelector('[data-wiii-id="chat-send-button"]');
      const r = el?.getBoundingClientRect();
      return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
    });
    const afterPos = await page.evaluate(() => {
      const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const m = el?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null;
    });
    console.log(`[E2E] cursor pos: ${JSON.stringify(afterPos)} target: ${JSON.stringify(targetCenter)}`);
    console.log(`[E2E] POINTY logs:\n${logs.filter((l) => l.includes("POINTY")).join("\n")}`);
    // Assert cursor reached near target.
    expect(afterPos).not.toBeNull();
    expect(targetCenter).not.toBeNull();
    if (afterPos && targetCenter) {
      const dist = Math.hypot(afterPos.x - targetCenter.x, afterPos.y - targetCenter.y);
      console.log(`[E2E] dist to target: ${dist.toFixed(0)}`);
      expect(dist).toBeLessThan(100);
    }
  });

  test("04 — Full E2E: chat 'nút gửi tin nhắn ở đâu' → cursor moves", async ({ page }) => {
    test.skip(
      process.env.WIII_RUN_LIVE_LLM !== "1",
      "Live backend/LLM smoke is opt-in; synthetic Pointy suites keep DOM/parser coverage deterministic.",
    );
    const { logs } = attachConsoleCapture(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 8000 });

    // Type message + send.
    const textarea = page.locator('textarea[data-wiii-id="chat-textarea"]').first();
    await textarea.fill("nút gửi tin nhắn ở đâu");
    await textarea.press("Enter");

    // Wait for streaming to finish. During streaming the send button
    // (data-wiii-id="chat-send-button") is replaced by a cancel button
    // without that attribute. When streaming ends + send button comes
    // back, isStreaming flips false. Detect by checking presence of
    // assistant message in DOM AND absence of cancel button.
    await page.waitForFunction(
      () => {
        const cancelBtn = document.querySelector(
          'button[aria-label="Dừng tạo phản hồi"]',
        );
        const sendBtn = document.querySelector(
          '[data-wiii-id="chat-send-button"]',
        );
        // Stream done: cancel gone + send reappeared (regardless of disabled).
        return cancelBtn === null && sendBtn !== null;
      },
      { timeout: 150000, polling: 500 },
    );
    await page.waitForTimeout(3000); // grace for onDone to fire + dispatch
    const pointyLogs = logs.filter((l) => l.includes("POINTY"));
    console.log(`[E2E] POINTY logs after full chat:\n${pointyLogs.join("\n")}`);

    // Get cursor position.
    const cursorPos = await page.evaluate(() => {
      const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      const state = el?.getAttribute("data-pointy-state");
      const m = el?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
      return {
        state,
        pos: m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : null,
      };
    });
    console.log(`[E2E] cursor end state: ${JSON.stringify(cursorPos)}`);
    console.log(`[E2E] all POINTY-* logs: ${pointyLogs.length}`);

    // Assert dispatcher pipeline ran (LLM variance: AI may or may not
    // produce pointing-related content). Either:
    //   - dispatch fired with ok=true (cursor moved), OR
    //   - parser ran but no match (AI didn't talk about UI element)
    const dispatched = pointyLogs.some(
      (l) =>
        l.includes("POINTY-EMBODIED") ||
        l.includes("POINTY-STREAM") ||
        l.includes("POINTY-INLINE"),
    );
    expect(dispatched).toBe(true);
  });

  test("05 — Streaming dispatch idempotent retry: DOM hidden then visible", async ({ page }) => {
    // Verify v6.0 F11 retry logic: if mid-stream pointAt fails (selector
    // not yet in DOM during streaming), onDone retries when button
    // comes back. Reproduces the bug: cancel button replaces send
    // button DURING stream → resolveSelector → null → ok=false. Retry
    // on onDone after stream end → button restored → ok=true.
    const { logs } = attachConsoleCapture(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 5000 });

    // Synthetic mid-stream: temporarily remove button, dispatch via
    // embodied test, then restore button + re-dispatch.
    const result1 = await page.evaluate(async () => {
      const btn = document.querySelector(
        '[data-wiii-id="chat-send-button"]',
      ) as HTMLElement | null;
      btn?.removeAttribute("data-wiii-id");
      const r1 = await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(
        "Nút gửi tin nhắn nằm ở góc phải nè cậu.",
      );
      return r1;
    });
    console.log(`[E2E] mid-stream dispatch (button hidden): ${result1}`);
    expect(result1).toContain("no-match"); // no targets found

    // Restore button, run dispatch again.
    const result2 = await page.evaluate(async () => {
      // Find any send button by aria-label (it's still in DOM, just no
      // data-wiii-id). Re-add the attribute.
      const sendBtn =
        document.querySelector('button[aria-label="Gửi tin nhắn"]') ||
        document.querySelector('[title*="Gửi"]');
      sendBtn?.setAttribute("data-wiii-id", "chat-send-button");
      return await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(
        "Nút gửi tin nhắn nằm ở góc phải nè cậu.",
      );
    });
    console.log(`[E2E] post-stream dispatch (button restored): ${result2}`);
    expect(result2).toContain("ok=true");

    await page.waitForTimeout(1500);
    const cursorState = await page.evaluate(() => {
      const el = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
      return {
        state: el?.getAttribute("data-pointy-state"),
      };
    });
    console.log(`[E2E] cursor state: ${JSON.stringify(cursorState)}`);
    expect(cursorState.state).toMatch(/moving|pointing/);
    console.log(`[E2E] POINTY logs:\n${logs.filter((l) => l.includes("POINTY")).join("\n")}`);
  });
});
