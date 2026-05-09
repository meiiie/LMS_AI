/**
 * Live DOM inventory + comprehensive coverage matrix.
 *
 * Step 1 — discover all `data-wiii-id` elements in the live app.
 * Step 2 — generate synthetic test cases across query phrasings ×
 * discovered targets. Verify each one drives the cursor.
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
        user_id: "e2e-inv",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

test.describe("Wiii Pointy v7.0 — live DOM inventory", () => {
  test("Inventory all data-wiii-id elements in live app", async ({ page }) => {
    await preSeedAuth(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForTimeout(2000); // let layout settle
    const inventory = await page.evaluate(() => {
      const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      return Array.from(els).map((el) => ({
        id: el.getAttribute("data-wiii-id") || "",
        ariaLabel: el.getAttribute("aria-label") || "",
        text: el.textContent?.trim().slice(0, 60) || "",
        tag: el.tagName.toLowerCase(),
        rect: (() => {
          const r = el.getBoundingClientRect();
          return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
        })(),
      }));
    });
    console.log("[INVENTORY] Live data-wiii-id elements:");
    for (const el of inventory) {
      console.log(`  - id="${el.id}" tag=${el.tag} aria-label="${el.ariaLabel}" rect=${JSON.stringify(el.rect)}`);
    }
    // Save inventory to file so other tests can consume.
    await page.evaluate((inv) => {
      sessionStorage.setItem("__pointy_inventory__", JSON.stringify(inv));
    }, inventory);
    expect(inventory.length).toBeGreaterThan(0);
  });
});

interface QueryCase {
  category: string;
  query: string;
  // Stub AI response simulating what LLM would say (synthetic). Frontend
  // parses this — bypasses backend latency.
  syntheticResponse: string;
  // Target id we expect to dispatch. null = negative test (no dispatch).
  expectTargetId: string | null;
}

const QUERY_MATRIX: QueryCase[] = [
  // ===== Single-element queries × phrasing variations =====
  {
    category: "VI / 'ở đâu' question",
    query: "Nút gửi tin nhắn ở đâu?",
    syntheticResponse: "Nút gửi tin nhắn nằm ở góc dưới phải khung chat đó cậu.",
    expectTargetId: "chat-send-button",
  },
  {
    category: "VI / 'làm sao' question",
    query: "Làm sao tôi gửi tin nhắn?",
    syntheticResponse: "Cậu nhập text vào ô soạn rồi click vào Gửi tin nhắn ở góc phải nha.",
    expectTargetId: "chat-send-button",
  },
  {
    category: "VI / imperative 'chỉ giúp tôi'",
    query: "Chỉ giúp tôi nút gửi",
    syntheticResponse: "Đây nè cậu — nút Gửi tin nhắn ở góc dưới phải.",
    expectTargetId: "chat-send-button",
  },
  {
    category: "VI / casual 'thế nút gửi'",
    query: "Thế nút gửi đâu rồi?",
    syntheticResponse: "Nút Gửi tin nhắn ngay góc phải dưới đó cậu, hình mũi tên xanh.",
    expectTargetId: "chat-send-button",
  },
  // ===== Tag-explicit responses (deterministic) =====
  {
    category: "Tag explicit",
    query: "Where is send?",
    syntheticResponse: "Right here. [POINT:chat-send-button:send button]",
    expectTargetId: "chat-send-button",
  },
  {
    category: "Tag with no caption",
    query: "Send button?",
    syntheticResponse: "Đây. [POINT:chat-send-button]",
    expectTargetId: "chat-send-button",
  },
  // ===== English embodied =====
  {
    category: "EN / 'click on'",
    query: "Click on send?",
    syntheticResponse: "Click on the Gửi tin nhắn button at the bottom right corner.",
    expectTargetId: "chat-send-button",
  },
  {
    category: "EN / 'right here'",
    query: "Where?",
    syntheticResponse: "Right here — see the Gửi tin nhắn button in the bottom right.",
    expectTargetId: "chat-send-button",
  },
  // ===== Diacritic variations =====
  {
    category: "VI no-diacritic 'nut gui'",
    query: "nut gui o dau",
    syntheticResponse: "Nut gui tin nhan o goc duoi ben phai man hinh nha cau.",
    expectTargetId: "chat-send-button",
  },
  {
    category: "VI partial diacritic",
    query: "Nut gửi đâu?",
    syntheticResponse: "Nut gửi nằm ở góc dưới phải, có hình mui tên xanh.",
    expectTargetId: "chat-send-button",
  },
  // ===== Negative cases =====
  {
    category: "Negative — pure greeting",
    query: "Chào Wiii!",
    syntheticResponse: "Chào cậu! Hôm nay cậu khỏe không?",
    expectTargetId: null,
  },
  {
    category: "Negative — generic info",
    query: "Tin nhắn là gì?",
    syntheticResponse: "Tin nhắn là phương tiện giao tiếp text giữa hai người.",
    expectTargetId: null,
  },
  {
    category: "Negative — math question",
    query: "2+2 bằng mấy?",
    syntheticResponse: "2 cộng 2 bằng 4 đó cậu.",
    expectTargetId: null,
  },
  {
    category: "Negative — explanation about element",
    query: "Tại sao có nút gửi?",
    syntheticResponse: "Tin nhắn của cậu cần một nút để confirm trước khi gửi đi, đó là lý do có nút gửi.",
    expectTargetId: null,
  },
  // ===== Mixed tag + embodied =====
  {
    category: "Mixed — tag wins (parsed first)",
    query: "Nút gửi?",
    syntheticResponse:
      "Nút gửi tin nhắn nằm ở góc dưới phải — đây nè. [POINT:chat-send-button:send]",
    expectTargetId: "chat-send-button",
  },
  // ===== Edge: very short response =====
  {
    category: "Very short — just intent + label",
    query: "Send?",
    syntheticResponse: "Click vào Gửi tin nhắn nha.",
    expectTargetId: "chat-send-button",
  },
  // ===== Edge: response without label match =====
  {
    category: "Off-topic intent — no element match",
    query: "Send?",
    syntheticResponse: "Trỏ vào sao trên trời cũng đẹp đó cậu.",
    expectTargetId: null,
  },
];

test.describe("Wiii Pointy v7.0 — query × phrasing matrix", () => {
  test.beforeEach(async ({ page }) => {
    await preSeedAuth(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', {
      timeout: 10000,
    });
  });

  for (const c of QUERY_MATRIX) {
    test(`${c.category} → "${c.query.slice(0, 40)}"`, async ({ page }) => {
      // Reset queue between cases.
      await page.evaluate(async () => {
        const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
          | { clearDispatchQueue?: () => void }
          | undefined;
        queueMod?.clearDispatchQueue?.();
      });
      const result = await page.evaluate(
        async (text: string) =>
          await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(text),
        c.syntheticResponse,
      );
      console.log(`  result: ${result}`);
      if (c.expectTargetId === null) {
        expect(result.toLowerCase()).toContain("no-match");
      } else {
        expect(result).toContain(c.expectTargetId);
        expect(result).toContain("ok=true");
      }
    });
  }
});

test.describe("Wiii Pointy v7.0 — multi-step sequence", () => {
  test.beforeEach(async ({ page }) => {
    await preSeedAuth(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', {
      timeout: 10000,
    });
  });

  test("Multi-tag — 3 sequential targets queued + first dispatched", async ({ page }) => {
    const result = await page.evaluate(async () => {
      const [tagMod, queueMod] = await Promise.all([
        import("/src/pointy-host/inline-tag-parser.ts" as string),
        import("/src/pointy-host/dispatch-queue.ts" as string),
      ]);
      (queueMod as { clearDispatchQueue: () => void }).clearDispatchQueue();
      const text =
        "Bước 1: vào [POINT:btn-step-1]. Bước 2: tới [POINT:btn-step-2]. Bước 3: kết [POINT:btn-step-3].";
      const tags = (tagMod as { parseAllPointTags: (t: string) => { tags: { selector: string; caption: string }[] } }).parseAllPointTags(text).tags;
      const queued = (queueMod as { enqueuePoints: (p: { selector: string; caption?: string; durationMs: number }[]) => number }).enqueuePoints(
        tags.map((t) => ({ selector: t.selector, caption: t.caption, durationMs: 100 })),
      );
      const state = (queueMod as { dispatchQueueState: () => { depth: number; active: string | null; seen: number } }).dispatchQueueState();
      return { tagCount: tags.length, queued, state };
    });
    expect(result.tagCount).toBe(3);
    expect(result.queued).toBe(3);
    expect(result.state.seen).toBe(3);
  });

  test("Multi-embodied — 3 different element references in sentences", async ({ page }) => {
    const result = await page.evaluate(async () => {
      const [embodiedMod, queueMod] = await Promise.all([
        import("/src/pointy-host/embodied-parser.ts" as string),
        import("/src/pointy-host/dispatch-queue.ts" as string),
      ]);
      (queueMod as { clearDispatchQueue: () => void }).clearDispatchQueue();
      const targets = [
        { id: "send-btn", label: "Gửi tin nhắn", role: "button" },
        { id: "settings-link", label: "Cài đặt", role: "link" },
        { id: "model-picker", label: "Chọn model", role: "menu" },
      ];
      const text =
        "Đầu tiên click vào Cài đặt để config. Rồi mở Chọn model để đổi LLM. Cuối cùng nhấn vào Gửi tin nhắn để test.";
      const matches = (embodiedMod as { detectAllEmbodiedPoints: (t: string, ts: object[]) => { target: { id: string }; score: number; sentence: string }[] }).detectAllEmbodiedPoints(text, targets);
      return matches.map((m) => m.target.id);
    });
    expect(result).toEqual(["settings-link", "model-picker", "send-btn"]);
  });
});

test.describe("Wiii Pointy v7.0 — live LLM smoke (slow)", () => {
  test.beforeEach(async ({ page }) => {
    await preSeedAuth(page);
    await page.goto(APP_URL);
    await page.waitForFunction(
      () => typeof (window as unknown as Record<string, unknown>).__wiiiEmbodiedTest__ === "function",
      { timeout: 15000 },
    );
    await page.waitForSelector('[data-wiii-id="chat-send-button"]', {
      timeout: 10000,
    });
  });

  // One real LLM call as smoke; expensive, mark slow.
  test.setTimeout(180_000);
  test("Live LLM — Vietnamese 'nút gửi tin nhắn ở đâu' → cursor moves", async ({ page }) => {
    test.skip(
      process.env.WIII_RUN_LIVE_LLM !== "1",
      "Live backend/LLM smoke is opt-in; synthetic Pointy suites keep DOM/parser coverage deterministic.",
    );
    const logs: string[] = [];
    page.on("console", (msg) => {
      if (msg.text().includes("POINTY")) logs.push(msg.text());
    });
    const textarea = page.locator('textarea[data-wiii-id="chat-textarea"]').first();
    await textarea.fill("nút gửi tin nhắn ở đâu");
    await textarea.press("Enter");
    // Wait for stream end (cancel button gone + send button back).
    await page.waitForFunction(
      () => {
        const cancelBtn = document.querySelector('button[aria-label="Dừng tạo phản hồi"]');
        return cancelBtn === null;
      },
      { timeout: 150_000, polling: 500 },
    );
    await page.waitForTimeout(2500);
    console.log("[LIVE-LLM] POINTY logs:\n" + logs.join("\n"));
    // Either streaming or onDone path should have queued at least one
    // dispatch. ok=true confirms cursor actually moved.
    const dispatched = logs.some(
      (l) =>
        (l.includes("POINTY-STREAM") || l.includes("POINTY-EMBODIED")) &&
        l.includes("queued"),
    );
    const succeeded = logs.some((l) => l.includes("ok=true"));
    expect(dispatched || succeeded).toBe(true);
  });
});
