import { expect, test } from "@playwright/test";
import { bootstrapLocalChat, sendPrompt } from "./support/local-chat-harness";

const FIRST_PROMPTS = [
  "Explain Kimi linear attention in charts. Use 2 to 3 small inline figures, each proving one claim: the problem, the mechanism, and the result.",
  "Build an article-style explanation in chat for Kimi linear attention. Use 2 or 3 inline figures instead of one big widget, and keep each figure focused on a single claim.",
  "Hay giai thich Kimi linear attention bang 2 den 3 figure nho ngay trong chat. Moi figure chi chung minh mot y: van de, co che, va ket qua.",
];
const FOLLOWUP_PROMPTS = [
  "Patch the most recent visual session only. Do not add a new visual block. Turn it into 3 process steps and highlight where approximation error appears.",
  "Keep the current visual session only. Update the latest visual itself into a 3-step process diagram, explicitly annotate the approximation-error step, and do not create another visual block.",
];
const TECHNICAL_LEAKS = [
  "structured visual",
  "spec_merge",
  "filterable",
  "inline visual",
  "generate visual",
  "template",
  "de tom tat nhanh noi dung",
];

async function visualSnapshot(page) {
  const visual = page.getByTestId("visual-block").last();
  const editorialFlow = page.getByTestId("editorial-visual-flow").first();
  await expect(visual).toBeVisible({ timeout: 120_000 });
  return {
    count: await page.getByTestId("visual-block").count(),
    figureCount: await editorialFlow.count().then(async (count) => (
      count > 0 ? Number(await editorialFlow.getAttribute("data-figure-count")) : 0
    )),
    title: await visual.locator("h3").innerText(),
    text: await visual.innerText(),
  };
}

async function waitForStableVisualSnapshot(page) {
  let stableRounds = 0;
  let previousSignature = "";
  let latest = { count: 0, figureCount: 0, title: "", text: "" };

  await expect
    .poll(async () => {
      latest = await visualSnapshot(page);
      const signature = `${latest.count}::${latest.figureCount}::${latest.title}::${latest.text.slice(0, 320)}`;

      if (signature === previousSignature) {
        stableRounds += 1;
      } else {
        previousSignature = signature;
        stableRounds = 0;
      }

      return stableRounds >= 2;
    }, {
      timeout: 60_000,
      intervals: [1_500, 2_000, 2_500],
    })
    .toBe(true);

  return latest;
}

async function waitForVisualSurfaceChange(page, previousTitle: string, previousText: string) {
  await expect
    .poll(async () => {
      const visual = page.getByTestId("visual-block").last();
      const title = await visual.locator("h3").innerText();
      const text = await visual.innerText();
      const normalized = text.toLowerCase();
      const hasProcessCue = [
        "buoc hien tai",
        "step 1",
        "buoc 1",
        "buoc 2",
        "buoc 3",
        "quy trinh",
        "theo tung buoc",
        "3 buoc",
        "approximation error",
        "diem can chu y",
      ].some((token) => normalized.includes(token));
      return title !== previousTitle || (text !== previousText && hasProcessCue);
    }, {
      timeout: 120_000,
      intervals: [1_000, 1_500, 2_000],
    })
    .toBe(true);
}

async function applyFollowupPatch(page, previousTitle: string, previousText: string) {
  let lastError: unknown = null;

  for (const prompt of FOLLOWUP_PROMPTS) {
    await sendPrompt(page, prompt);

    try {
      await waitForVisualSurfaceChange(page, previousTitle, previousText);
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(1_000);
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Visual patch did not surface after follow-up retries.");
}

async function waitForGenerationToSettle(page) {
  const inputBox = page.locator("textarea[aria-label]").first();
  await expect
    .poll(async () => await page.locator('[aria-label="Dừng tạo phản hồi"]').count(), {
      timeout: 120_000,
      intervals: [1_000, 1_500, 2_000],
    })
    .toBe(0);
  await expect(inputBox).toBeEnabled({ timeout: 120_000 });
}

async function ensureInitialVisualStage(page) {
  let lastError: unknown = null;

  for (const prompt of FIRST_PROMPTS) {
    await sendPrompt(page, prompt);
    await page.waitForTimeout(2_500);

    try {
      const visual = page.getByTestId("visual-block").last();
      await expect(visual).toBeVisible({ timeout: 120_000 });
      return;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(1_000);
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Initial inline visual stage did not appear after prompt retries.");
}

async function evaluateOverflow(page) {
  return page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    hasOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
  }));
}

function hasTechnicalLeak(text: string) {
  const normalized = text.toLowerCase();
  return TECHNICAL_LEAKS.some((token) => normalized.includes(token));
}

async function runVisualScenario(page, testInfo, viewportLabel: string) {
  const uniqueUser = `visual-e2e-${viewportLabel}-${Date.now()}`;
  await bootstrapLocalChat(page, {
    userId: uniqueUser,
    displayName: `Visual ${viewportLabel}`,
  });

  if (viewportLabel === "mobile") {
    await expect(page.getByLabel("Menu")).toBeVisible();
    await expect(page.locator(".sidebar-backdrop")).toHaveClass(/hidden/);
  }

  await ensureInitialVisualStage(page);
  await waitForGenerationToSettle(page);
  await expect(page.getByTestId("reasoning-interval").first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("thinking-block")).toHaveCount(0);

  const before = await waitForStableVisualSnapshot(page);
  const editorialFlow = page.getByTestId("editorial-visual-flow");
  await expect(editorialFlow).toHaveCount(1);
  expect(before.figureCount).toBeGreaterThanOrEqual(2);
  await expect(editorialFlow.locator(".editorial-visual-flow__prose--lead")).toBeVisible();
  const beforeTail = editorialFlow.locator(".editorial-visual-flow__prose--tail");
  if (await beforeTail.count()) {
    await expect(beforeTail).toBeVisible();
  }

  await applyFollowupPatch(page, before.title, before.text);
  await waitForGenerationToSettle(page);
  await page.waitForTimeout(1_500);

  const after = await waitForStableVisualSnapshot(page);
  const overflow = await evaluateOverflow(page);

  expect(after.count).toBeLessThanOrEqual(before.count + 1);
  expect(after.text).not.toBe(before.text);
  expect(hasTechnicalLeak(after.text)).toBe(false);
  expect(overflow.hasOverflow).toBe(false);
  await expect(editorialFlow).toHaveCount(1);
  expect(after.figureCount).toBeGreaterThanOrEqual(2);
  await expect(editorialFlow.locator(".editorial-visual-flow__prose--lead")).toBeVisible();
  const afterTail = editorialFlow.locator(".editorial-visual-flow__prose--tail");
  if (await afterTail.count()) {
    await expect(afterTail).toBeVisible();
  }

  await page.screenshot({
    path: testInfo.outputPath(`visual-runtime-${viewportLabel}.png`),
    fullPage: true,
  });
}

test.describe("visual runtime", () => {
  test("keeps one inline visual and wraps it into the editorial flow on desktop", async ({ page }, testInfo) => {
    await runVisualScenario(page, testInfo, "desktop");
  });

  test("keeps the editorial visual flow responsive on mobile web", async ({ browser }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 1440 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await runVisualScenario(page, testInfo, "mobile");
    await context.close();
  });
});
