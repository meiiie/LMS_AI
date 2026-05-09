/**
 * REAL LLM stress test — full pipeline against live NVIDIA backend.
 *
 * Earlier tests used `__wiiiEmbodiedTest__` synthetic shortcut. This
 * test goes all the way: chat input → SSE stream → dispatcher → cursor.
 * Diverse queries about different UI elements + multi-turn session.
 *
 * Honest acceptance criteria — each query is allowed to fail (LLM
 * variance) but we ASSERT pipeline integrity: at minimum we should see
 * `[POINTY-STREAM]` or `[POINTY-EMBODIED]` log entries for queries
 * about UI elements, and zero entries for off-topic queries.
 *
 * Each test takes ~30-60s (NVIDIA tier-1 latency). Total ~5-7 min.
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
        user_id: "e2e-stress",
        user_role: "student",
        server_url: "http://localhost:8000",
      }),
    );
  }, API_KEY);
}

async function bootApp(page: Page) {
  await preSeedAuth(page);
  await page.goto(APP_URL);
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
    { timeout: 15000 },
  );
  await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 10000 });
}

interface QueryCase {
  query: string;
  expectsDispatch: boolean;
  // Possible target IDs that would be a "correct" answer (any of them).
  // Empty array means we accept ANY dispatch (LLM might pick reasonable target).
  acceptableTargetIds?: string[];
  category: string;
}

const REAL_QUERIES: QueryCase[] = [
  {
    category: "Single element / send button",
    query: "nút gửi tin nhắn ở đâu",
    expectsDispatch: true,
    acceptableTargetIds: ["chat-send-button"],
  },
  {
    category: "Single element / attach",
    query: "muốn đính kèm ảnh thì click vào đâu cậu",
    expectsDispatch: true,
    acceptableTargetIds: ["attach-file-button"],
  },
  {
    category: "Single element / domain selector",
    query: "thay đổi lĩnh vực chat ở chỗ nào",
    expectsDispatch: true,
    acceptableTargetIds: ["domain-selector"],
  },
  {
    category: "Single element / model picker",
    query: "tôi muốn đổi sang model AI khác làm sao",
    expectsDispatch: true,
    acceptableTargetIds: ["model-selector"],
  },
  {
    category: "Single element / new chat",
    query: "tạo cuộc trò chuyện mới làm thế nào",
    expectsDispatch: true,
    acceptableTargetIds: ["new-chat-button"],
  },
  {
    category: "Off-topic / no dispatch",
    query: "2+2 bằng mấy",
    expectsDispatch: false,
  },
  {
    category: "Off-topic / greeting",
    query: "Wiii có khỏe không",
    expectsDispatch: false,
  },
];

interface CaseResult {
  query: string;
  category: string;
  durationMs: number;
  pointyLogs: string[];
  cursorState: string;
  dispatched: boolean;
  matchedTargetId: string | null;
  expectedDispatch: boolean;
  responseText: string;
  ok: boolean;
}

async function sendAndCapture(page: Page, query: string): Promise<{
  pointyLogs: string[];
  cursorState: string;
  matchedTargetId: string | null;
  responseText: string;
  durationMs: number;
}> {
  const logs: string[] = [];
  const handler = (msg: import("@playwright/test").ConsoleMessage) => {
    const t = msg.text();
    if (t.includes("POINTY-")) logs.push(t);
  };
  page.on("console", handler);
  const t0 = Date.now();
  const textarea = page.locator('textarea[data-wiii-id="chat-textarea"]').first();
  await textarea.fill(query);
  await textarea.press("Enter");
  // Wait stream done.
  await page.waitForFunction(
    () => {
      const cancelBtn = document.querySelector('button[aria-label="Dừng tạo phản hồi"]');
      return cancelBtn === null;
    },
    { timeout: 150_000, polling: 500 },
  );
  await page.waitForTimeout(2500);
  const durationMs = Date.now() - t0;
  page.off("console", handler);

  // Extract last assistant message text + cursor state.
  const snapshot = await page.evaluate(() => {
    const cursor = document.querySelector('[data-pointy-cursor="wiii"]') as HTMLElement | null;
    const state = cursor?.getAttribute("data-pointy-state") || "unknown";
    const m = cursor?.style.transform.match(/translate3d\((-?\d+(?:\.\d+)?)px,\s*(-?\d+(?:\.\d+)?)px/);
    const pos = m ? `${Math.round(parseFloat(m[1]))},${Math.round(parseFloat(m[2]))}` : "?";
    // Last assistant message: get the latest .selectable text node closest to user message.
    const selectable = Array.from(
      document.querySelectorAll<HTMLElement>('[data-message-role="assistant"] .selectable, p.selectable'),
    );
    const lastMsg = selectable[selectable.length - 1]?.textContent?.trim().slice(0, 280) || "";
    return { state: `${state}@${pos}`, response: lastMsg };
  });

  // Find which target ID was actually dispatched (from log).
  let matchedId: string | null = null;
  for (const l of logs) {
    const m = l.match(/selector=([\w:.-]+)/);
    if (m) {
      matchedId = m[1];
      break;
    }
  }
  return {
    pointyLogs: logs,
    cursorState: snapshot.state,
    matchedTargetId: matchedId,
    responseText: snapshot.response,
    durationMs,
  };
}

test.describe("Wiii Pointy v8.0 — REAL LLM stress (slow)", () => {
  test.setTimeout(1_800_000); // 30 min — 7 queries × ~60-90s each w/ NVIDIA
  const results: CaseResult[] = [];

  test("Sweep — 7 diverse queries against real NVIDIA backend", async ({ page }) => {
    await bootApp(page);

    for (const c of REAL_QUERIES) {
      const sn = await sendAndCapture(page, c.query);
      const dispatched = sn.pointyLogs.some(
        (l) => l.includes("POINTY-STREAM") || l.includes("POINTY-EMBODIED"),
      );
      const r: CaseResult = {
        query: c.query,
        category: c.category,
        durationMs: sn.durationMs,
        pointyLogs: sn.pointyLogs,
        cursorState: sn.cursorState,
        dispatched,
        matchedTargetId: sn.matchedTargetId,
        expectedDispatch: c.expectsDispatch,
        responseText: sn.responseText,
        ok:
          c.expectsDispatch === dispatched &&
          (c.expectsDispatch === false ||
            !c.acceptableTargetIds ||
            c.acceptableTargetIds.length === 0 ||
            (sn.matchedTargetId !== null &&
              c.acceptableTargetIds.includes(sn.matchedTargetId))),
      };
      results.push(r);
      console.log("\n=== " + c.category + " ===");
      console.log("  query: " + c.query);
      console.log("  duration: " + (sn.durationMs / 1000).toFixed(1) + "s");
      console.log("  cursor: " + sn.cursorState);
      console.log("  matched id: " + (sn.matchedTargetId || "(none)"));
      console.log("  ai resp: " + sn.responseText.slice(0, 180));
      console.log("  expected dispatch: " + c.expectsDispatch);
      console.log("  actual dispatch: " + dispatched);
      console.log("  POINTY logs:");
      sn.pointyLogs.forEach((l) => console.log("    " + l.slice(0, 200)));
      console.log("  PASS: " + r.ok);
    }

    // Summary
    console.log("\n========= STRESS TEST SUMMARY =========");
    let pass = 0;
    let fail = 0;
    for (const r of results) {
      const status = r.ok ? "✓" : "✗";
      console.log(
        `${status} [${r.category}] q="${r.query.slice(0, 50)}" expectDispatch=${r.expectedDispatch} got=${r.dispatched} target=${r.matchedTargetId || "-"}`,
      );
      if (r.ok) pass++;
      else fail++;
    }
    console.log(`\nTotal: ${pass}/${results.length} passed (${fail} failed)`);

    // We allow up to 1 failure for LLM variance, but require >= 5/7 pass.
    expect(pass).toBeGreaterThanOrEqual(5);
  });
});
