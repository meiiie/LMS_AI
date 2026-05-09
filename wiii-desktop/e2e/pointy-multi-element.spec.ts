/**
 * Multi-element + multi-step E2E coverage matrix.
 *
 * Tests cursor across 8 distinct UI elements with diverse query
 * phrasings + complex multi-step workflows ("Click X then Y then Z").
 * Replaces single-element hardcoded tests with breadth + depth.
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
        user_id: "e2e-multi",
        user_role: "student",
        server_url: "http://127.0.0.1:65535",
      }),
    );
  }, API_KEY);
}

interface ElementCase {
  targetId: string;
  // 4 phrasings per element — diverse intent phrases.
  syntheticResponses: string[];
}

// Per-element test matrix: 4 phrasings × 8 elements = 32 cases.
const PER_ELEMENT_MATRIX: ElementCase[] = [
  {
    targetId: "chat-send-button",
    syntheticResponses: [
      "Nút Gửi tin nhắn ở góc dưới phải nè cậu, hình mũi tên xanh.",
      "Cậu click vào Gửi tin nhắn để gửi message nha.",
      "Đây nè! Gửi tin nhắn nằm ngay đó.",
      "Click on the Gửi tin nhắn button at the bottom right.",
    ],
  },
  {
    targetId: "attach-file-button",
    syntheticResponses: [
      "Để đính kèm ảnh, cậu click vào Đính kèm file ở góc trái dưới chỗ chat.",
      "Nút Đính kèm file nằm ngay bên trái domain selector đó.",
      "Đây nè cậu, Đính kèm file ở đó.",
      "Click on Đính kèm file to add an image attachment.",
    ],
  },
  {
    targetId: "domain-selector",
    syntheticResponses: [
      "Chọn lĩnh vực nằm ở thanh dưới chat input, click vào để đổi domain.",
      "Để đổi domain, cậu click vào Chọn lĩnh vực nha.",
      "Đây rồi, Chọn lĩnh vực ngay đó.",
      "Click on Chọn lĩnh vực to switch domain.",
    ],
  },
  {
    targetId: "model-selector",
    syntheticResponses: [
      "Để đổi provider AI, cậu click vào Chọn model AI nằm cạnh domain selector.",
      "Chọn model AI ở đây nè cậu, click để đổi LLM.",
      "Đây nè, Chọn model AI ngay góc đó.",
      "Click on Chọn model AI to change the AI model.",
    ],
  },
  {
    targetId: "new-chat-button",
    syntheticResponses: [
      "Để bắt đầu hội thoại mới, click vào Tạo cuộc trò chuyện mới ở thanh sidebar bên trái.",
      "Tạo cuộc trò chuyện mới nằm ở góc trên sidebar nha cậu.",
      "Đây rồi, Tạo cuộc trò chuyện mới ngay đó.",
      "Click on Tạo cuộc trò chuyện mới to start a new chat.",
    ],
  },
  {
    targetId: "sidebar-toggle",
    syntheticResponses: [
      "Để ẩn sidebar, click vào Ẩn sidebar ở góc trên cùng.",
      "Ẩn sidebar nằm ngay đầu sidebar đó cậu.",
      "Đây nè cậu, Ẩn sidebar ngay đó.",
      "Click on Ẩn sidebar to collapse the side panel.",
    ],
  },
  {
    targetId: "conversation-search",
    syntheticResponses: [
      "Để tìm cuộc trò chuyện cũ, click vào Tìm kiếm cuộc trò chuyện ở sidebar.",
      "Tìm kiếm cuộc trò chuyện nằm ngay dưới nút tạo mới đó.",
      "Đây rồi, Tìm kiếm cuộc trò chuyện ngay đó.",
      "Click on Tìm kiếm cuộc trò chuyện to search past chats.",
    ],
  },
  {
    targetId: "chat-textarea",
    syntheticResponses: [
      "Khung soạn tin nhắn ở giữa màn hình — cậu gõ message vào đó.",
      "Cậu click vào Khung soạn tin nhắn rồi gõ nội dung nha.",
      "Đây nè, Khung soạn tin nhắn ngay đó.",
      "Click on Khung soạn tin nhắn to type your message.",
    ],
  },
];

test.describe("Wiii Pointy v7.0 — per-element coverage", () => {
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
    // Reset queue.
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue?: () => void }
        | undefined;
      queueMod?.clearDispatchQueue?.();
    });
  });

  for (const elem of PER_ELEMENT_MATRIX) {
    for (let i = 0; i < elem.syntheticResponses.length; i++) {
      const response = elem.syntheticResponses[i];
      test(`${elem.targetId} / phrasing #${i + 1}`, async ({ page }) => {
        // Skip if target not in current DOM.
        const present = await page.evaluate(
          (sel) => document.querySelector(`[data-wiii-id="${sel}"]`) !== null,
          elem.targetId,
        );
        if (!present) {
          test.skip();
          return;
        }
        // Reset queue per case so dedup doesn't cross-pollute.
        await page.evaluate(async () => {
          const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
            | { clearDispatchQueue?: () => void }
            | undefined;
          queueMod?.clearDispatchQueue?.();
        });
        const result = await page.evaluate(
          async (text: string) =>
            await (window as unknown as { __wiiiEmbodiedTest__: (t: string) => Promise<string> }).__wiiiEmbodiedTest__(text),
          response,
        );
        console.log(`  ${elem.targetId} #${i + 1}: ${result}`);
        expect(result).toContain(elem.targetId);
        expect(result).toContain("ok=true");
      });
    }
  }
});

test.describe("Wiii Pointy v7.0 — multi-step workflows", () => {
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

  test("Workflow 1 — change provider then send: model-selector → chat-send-button", async ({ page }) => {
    const hasModelSelector = await page.locator('[data-wiii-id="model-selector"]').count();
    test.skip(
      hasModelSelector === 0,
      "Model selector is hidden when provider catalog is unavailable in offline synthetic mode.",
    );
    // Reset queue.
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue: () => void };
      queueMod.clearDispatchQueue();
    });
    const queueResult = await page.evaluate(async () => {
      const [embodiedMod] = await Promise.all([
        import("/src/pointy-host/embodied-parser.ts" as string),
      ]);
      // DOM-direct query (avoids module-instance duplication when page.evaluate
      // loads fresh module that has no mounted scanner).
      const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      const targets = Array.from(els)
        .map((el) => ({
          id: el.getAttribute("data-wiii-id") || "",
          label: el.getAttribute("aria-label") || "",
          role: el.tagName.toLowerCase(),
        }))
        .filter((t) => t.id);
      const text =
        "Để đổi LLM rồi gửi: đầu tiên cậu click Chọn model AI để đổi model. Sau đó nhấn Gửi tin nhắn để test response mới.";
      const matches = (embodiedMod as { detectAllEmbodiedPoints: (t: string, ts: object[]) => { target: { id: string; label?: string }; score: number }[] }).detectAllEmbodiedPoints(text, targets);
      return matches.map((m) => ({ id: m.target.id, score: m.score }));
    });
    console.log(`  Workflow 1 matches: ${JSON.stringify(queueResult)}`);
    expect(queueResult.length).toBeGreaterThanOrEqual(2);
    expect(queueResult[0].id).toBe("model-selector");
    expect(queueResult[1].id).toBe("chat-send-button");
  });

  test("Workflow 2 — explore UI: sidebar → search → new chat", async ({ page }) => {
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue: () => void };
      queueMod.clearDispatchQueue();
    });
    const matches = await page.evaluate(async () => {
      const [embodiedMod] = await Promise.all([
        import("/src/pointy-host/embodied-parser.ts" as string),
      ]);
      const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      const targets = Array.from(els)
        .map((el) => ({
          id: el.getAttribute("data-wiii-id") || "",
          label: el.getAttribute("aria-label") || "",
          role: el.tagName.toLowerCase(),
        }))
        .filter((t) => t.id);
      const text =
        "Cậu mở Ẩn sidebar trước để xem. Sau đó click Tìm kiếm cuộc trò chuyện để lọc lịch sử. Cuối cùng nhấn Tạo cuộc trò chuyện mới khi muốn bắt đầu lại.";
      return (embodiedMod as { detectAllEmbodiedPoints: (t: string, ts: object[]) => { target: { id: string }; score: number }[] }).detectAllEmbodiedPoints(text, targets).map((m) => m.target.id);
    });
    console.log(`  Workflow 2 sequence: ${matches.join(" → ")}`);
    expect(matches).toEqual([
      "sidebar-toggle",
      "conversation-search",
      "new-chat-button",
    ]);
  });

  test("Workflow 3 — compose message: textarea → attach → domain → send", async ({ page }) => {
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue: () => void };
      queueMod.clearDispatchQueue();
    });
    const matches = await page.evaluate(async () => {
      const [embodiedMod] = await Promise.all([
        import("/src/pointy-host/embodied-parser.ts" as string),
      ]);
      const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      const targets = Array.from(els)
        .map((el) => ({
          id: el.getAttribute("data-wiii-id") || "",
          label: el.getAttribute("aria-label") || "",
          role: el.tagName.toLowerCase(),
        }))
        .filter((t) => t.id);
      const text =
        "Cậu gõ nội dung vào Khung soạn tin nhắn ở giữa. Để gửi kèm ảnh thì click Đính kèm file. Đổi Chọn lĩnh vực nếu hỏi maritime. Cuối cùng nhấn Gửi tin nhắn để gửi.";
      return (embodiedMod as { detectAllEmbodiedPoints: (t: string, ts: object[]) => { target: { id: string } }[] }).detectAllEmbodiedPoints(text, targets).map((m) => m.target.id);
    });
    console.log(`  Workflow 3 sequence: ${matches.join(" → ")}`);
    expect(matches).toEqual([
      "chat-textarea",
      "attach-file-button",
      "domain-selector",
      "chat-send-button",
    ]);
  });

  test("Workflow 4 — tag-based tour with 4 explicit POINT tags", async ({ page }) => {
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue: () => void };
      queueMod.clearDispatchQueue();
    });
    const result = await page.evaluate(async () => {
      const [tagMod, queueMod] = await Promise.all([
        import("/src/pointy-host/inline-tag-parser.ts" as string),
        import("/src/pointy-host/dispatch-queue.ts" as string),
      ]);
      const text =
        "Tour UI: bắt đầu [POINT:new-chat-button:tạo chat]. Sau đó [POINT:domain-selector:đổi domain]. Tiếp [POINT:attach-file-button:đính kèm]. Cuối cùng [POINT:chat-send-button:gửi].";
      const tags = (tagMod as { parseAllPointTags: (t: string) => { tags: { selector: string; caption: string }[] } }).parseAllPointTags(text).tags;
      const queued = (queueMod as { enqueuePoints: (p: { selector: string; caption?: string; durationMs: number }[]) => number }).enqueuePoints(
        tags.map((t) => ({ selector: t.selector, caption: t.caption, durationMs: 200 })),
      );
      const state = (queueMod as { dispatchQueueState: () => { depth: number; active: string | null; seen: number } }).dispatchQueueState();
      return { tagCount: tags.length, queued, state, ids: tags.map((t) => t.selector) };
    });
    console.log(`  Workflow 4: ${JSON.stringify(result)}`);
    expect(result.tagCount).toBe(4);
    expect(result.queued).toBe(4);
    expect(result.ids).toEqual([
      "new-chat-button",
      "domain-selector",
      "attach-file-button",
      "chat-send-button",
    ]);
  });

  test("Workflow 5 — mixed tag + embodied in one response", async ({ page }) => {
    await page.evaluate(async () => {
      const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as
        | { clearDispatchQueue: () => void };
      queueMod.clearDispatchQueue();
    });
    // Mixed: tags fire first (path 1), then embodied parser sees same content
    // → enqueue more (queue dedupes already-fired).
    const result = await page.evaluate(async () => {
      const [tagMod, embodiedMod, queueMod] = await Promise.all([
        import("/src/pointy-host/inline-tag-parser.ts" as string),
        import("/src/pointy-host/embodied-parser.ts" as string),
        import("/src/pointy-host/dispatch-queue.ts" as string),
      ]);
      const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
      const targets = Array.from(els)
        .map((el) => ({
          id: el.getAttribute("data-wiii-id") || "",
          label: el.getAttribute("aria-label") || "",
          role: el.tagName.toLowerCase(),
        }))
        .filter((t) => t.id);
      const text =
        "Để bắt đầu, click Tạo cuộc trò chuyện mới [POINT:new-chat-button]. Rồi nhập text vào Nhập tin nhắn để hỏi.";
      const tags = (tagMod as { parseAllPointTags: (t: string) => { tags: { selector: string; caption: string }[] } }).parseAllPointTags(text).tags;
      const tagsQueued = (queueMod as { enqueuePoints: (p: { selector: string; caption?: string; durationMs: number }[]) => number }).enqueuePoints(
        tags.map((t) => ({ selector: t.selector, caption: t.caption, durationMs: 200 })),
      );
      const embodied = (embodiedMod as { detectAllEmbodiedPoints: (t: string, ts: object[]) => { target: { id: string; label?: string } }[] }).detectAllEmbodiedPoints(text, targets);
      const embodiedQueued = (queueMod as { enqueuePoints: (p: { selector: string; caption?: string; durationMs: number }[]) => number }).enqueuePoints(
        embodied.map((m) => ({ selector: m.target.id, caption: m.target.label, durationMs: 200 })),
      );
      const state = (queueMod as { dispatchQueueState: () => { seen: number } }).dispatchQueueState();
      return { tagsQueued, embodiedQueued, totalSeen: state.seen };
    });
    console.log(`  Workflow 5: ${JSON.stringify(result)}`);
    // Tags: new-chat-button. Embodied: textarea + new-chat (dedup). So queue
    // ends up with at least 2 unique seen (new-chat + textarea).
    expect(result.totalSeen).toBeGreaterThanOrEqual(2);
  });
});
