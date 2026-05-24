import { expect, test } from "@playwright/test";
import { bootstrapLocalChat, chatComposer } from "./support/local-chat-harness";

test.describe("local chat harness", () => {
  test("uses dev-login to reach the chat composer on localhost", async ({ page }) => {
    const result = await bootstrapLocalChat(page, {
      userId: `harness-smoke-${Date.now()}`,
      displayName: "Harness Smoke",
    });

    expect(result.authenticatedBy).toBe("dev-login-api");
    await expect(chatComposer(page)).toBeVisible();
    await expect(page.getByText("Chào mừng đến Wiii")).toHaveCount(0);
  });
});
