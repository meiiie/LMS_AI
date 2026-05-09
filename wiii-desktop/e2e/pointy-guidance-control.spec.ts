import { expect, test, type Page } from "@playwright/test";

const APP_URL = "http://127.0.0.1:1420";

async function bootPointy(page: Page) {
  await page.goto(APP_URL);
  await page.waitForTimeout(1000);
  const devLogin = page.locator('[data-testid="dev-login-button"]');
  if (await devLogin.count()) {
    await devLogin.click();
  }
  await page.waitForFunction(
    () => typeof (window as unknown as Record<string, unknown>).__wiiiPointTest__ === "function",
    { timeout: 15_000 },
  );
  await page.waitForSelector('[data-wiii-id="chat-send-button"]', { timeout: 15_000 });
  await page.waitForSelector('[data-wiii-id="attach-file-button"]', { timeout: 15_000 });
}

async function enqueueGuidance(page: Page, points: Array<{ selector: string; caption: string; durationMs: number }>) {
  return page.evaluate(async (items) => {
    const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as {
      clearDispatchQueue: () => void;
      enqueueTagPoints: (points: Array<{ selector: string; caption: string; durationMs: number }>) => number;
    };
    queueMod.clearDispatchQueue();
    return queueMod.enqueueTagPoints(items);
  }, points);
}

async function queueState(page: Page) {
  return page.evaluate(async () => {
    const queueMod = (await import("/src/pointy-host/dispatch-queue.ts" as string)) as {
      dispatchQueueState: () => { depth: number; active: string | null; seen: number };
    };
    return queueMod.dispatchQueueState();
  });
}

test.describe("Pointy guidance control", () => {
  test("multi-step guidance visits targets in order", async ({ page }) => {
    await bootPointy(page);
    const queued = await enqueueGuidance(page, [
      { selector: "attach-file-button", caption: "Bước 1: Đính kèm", durationMs: 700 },
      { selector: "pointy-mode-toggle", caption: "Bước 2: Pointy mode", durationMs: 700 },
      { selector: "chat-send-button", caption: "Bước 3: Gửi tin nhắn", durationMs: 700 },
    ]);
    expect(queued).toBe(3);

    await expect(page.locator("#wiii-pointy-tooltip")).toContainText("Bước 1: Đính kèm");
    await page.waitForTimeout(850);
    await expect(page.locator("#wiii-pointy-tooltip")).toContainText("Bước 2: Pointy mode");
    await page.waitForTimeout(850);
    await expect(page.locator("#wiii-pointy-tooltip")).toContainText("Bước 3: Gửi tin nhắn");
  });

  test("Bỏ qua cancels active and pending guidance", async ({ page }) => {
    await bootPointy(page);
    await enqueueGuidance(page, [
      { selector: "attach-file-button", caption: "Bước 1: Đính kèm", durationMs: 1200 },
      { selector: "pointy-mode-toggle", caption: "Bước 2: Pointy mode", durationMs: 1200 },
      { selector: "chat-send-button", caption: "Bước 3: Gửi tin nhắn", durationMs: 1200 },
    ]);

    await page.getByRole("button", { name: "Bỏ qua hướng dẫn Pointy" }).click();
    await expect(page.locator("#wiii-pointy-tooltip")).toHaveAttribute("aria-hidden", "true");
    await expect.poll(() => queueState(page)).toEqual({ depth: 0, active: null, seen: 0 });
    await page.waitForTimeout(1400);
    await expect(page.locator("#wiii-pointy-tooltip")).toHaveAttribute("aria-hidden", "true");
  });
});
