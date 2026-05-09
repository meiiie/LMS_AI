/**
 * DOM audit — inventory ALL pointable elements in the live app
 * (data-wiii-id annotated, plus aria-label / title / id candidates).
 *
 * Output drives architectural decision: which UI elements need
 * data-wiii-id so Wiii can point at them.
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
        user_id: "audit",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

test("DOM audit — full inventory of interactive elements", async ({ page }) => {
  await preSeedAuth(page);
  await page.goto(APP_URL);
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
    { timeout: 15000 },
  );
  await page.waitForTimeout(3000); // let layout settle fully

  const audit = await page.evaluate(() => {
    const annotated: Array<{
      id: string;
      tag: string;
      ariaLabel: string;
      title: string;
      text: string;
      rect: { x: number; y: number; w: number; h: number };
    }> = [];
    const candidates: Array<{
      tag: string;
      ariaLabel: string;
      title: string;
      text: string;
      role: string;
      cssId: string;
      hasWiiiId: boolean;
      rect: { x: number; y: number; w: number; h: number };
    }> = [];

    const sniffRect = (el: Element) => {
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };

    // Annotated (already has data-wiii-id)
    document.querySelectorAll<HTMLElement>("[data-wiii-id]").forEach((el) => {
      annotated.push({
        id: el.getAttribute("data-wiii-id") || "",
        tag: el.tagName.toLowerCase(),
        ariaLabel: el.getAttribute("aria-label") || "",
        title: el.getAttribute("title") || "",
        text: el.textContent?.trim().slice(0, 60) || "",
        rect: sniffRect(el),
      });
    });

    // Candidates (interactive, NOT yet annotated)
    const interactiveSelectors = [
      "button:not([disabled])",
      "a[href]",
      'input:not([type="hidden"]):not([disabled])',
      "select:not([disabled])",
      "textarea:not([disabled])",
      '[role="button"]',
      '[role="link"]',
      '[role="menu"]',
      '[role="menuitem"]',
      '[role="tab"]',
    ].join(", ");
    document.querySelectorAll<HTMLElement>(interactiveSelectors).forEach((el) => {
      const ariaLabel = el.getAttribute("aria-label") || "";
      const title = el.getAttribute("title") || "";
      const text = el.textContent?.trim().slice(0, 40) || "";
      // Only include if has SOMETHING identifying it (label, title, or visible text).
      if (!ariaLabel && !title && !text) return;
      const r = el.getBoundingClientRect();
      // Visible elements only.
      if (r.width === 0 || r.height === 0) return;
      candidates.push({
        tag: el.tagName.toLowerCase(),
        ariaLabel,
        title,
        text,
        role: el.getAttribute("role") || "",
        cssId: el.id || "",
        hasWiiiId: el.hasAttribute("data-wiii-id"),
        rect: sniffRect(el),
      });
    });

    return { annotated, candidates };
  });

  console.log(`\n=== ANNOTATED (data-wiii-id) — ${audit.annotated.length} elements ===`);
  for (const a of audit.annotated) {
    console.log(`  ✓ id="${a.id}" tag=${a.tag} aria="${a.ariaLabel}" rect=${JSON.stringify(a.rect)}`);
  }

  console.log(`\n=== CANDIDATES (no data-wiii-id) — ${audit.candidates.length} elements ===`);
  for (const c of audit.candidates) {
    if (c.hasWiiiId) continue;
    const id = c.ariaLabel || c.title || c.text;
    console.log(`  ? "${id}" tag=${c.tag} role="${c.role}" rect=${JSON.stringify(c.rect)}`);
  }
});
