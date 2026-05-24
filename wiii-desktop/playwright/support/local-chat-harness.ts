import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

type BootstrapOptions = {
  serverUrl?: string;
  userId?: string;
  displayName?: string;
};

type BootstrapResult = {
  serverUrl: string;
  userId: string;
  authenticatedBy: "dev-login-api";
};

function defaultServerUrl(): string {
  return process.env.WIII_PLAYWRIGHT_SERVER_URL || "http://127.0.0.1:8000";
}

function uniqueUserId(base = "playwright-chat"): string {
  return `${base}-${Date.now()}-${randomUUID().slice(0, 8)}`;
}

function settingsPayload(serverUrl: string, userId: string, displayName: string) {
  return {
    server_url: serverUrl,
    api_key: "",
    user_id: userId,
    user_role: "admin",
    display_name: displayName,
    llm_provider: "google",
    theme: "light",
    default_domain: "maritime",
    show_thinking: true,
    show_reasoning_trace: false,
    streaming_version: "v3",
  };
}

function safeEmail(userId: string): string {
  const localPart = userId.toLowerCase().replace(/[^a-z0-9-]+/g, "-").slice(0, 48);
  return `${localPart || "playwright"}@localhost`;
}

async function createDevLoginSession(page: Page, serverUrl: string, userId: string, displayName: string) {
  const response = await page.request.post(`${serverUrl}/api/v1/auth/dev-login`, {
    data: {
      email: safeEmail(userId),
      name: displayName,
      role: "admin",
    },
    timeout: 30_000,
  });
  if (!response.ok()) {
    const body = await response.text().catch(() => "");
    throw new Error(`Local dev-login failed (${response.status()}): ${body}`);
  }
  return await response.json();
}

export function chatComposer(page: Page) {
  return page.locator('[data-wiii-id="chat-textarea"]').first();
}

export async function sendPrompt(page: Page, prompt: string): Promise<void> {
  const input = chatComposer(page);
  await input.waitFor({ state: "visible", timeout: 60_000 });
  await expect(input).toBeEnabled({ timeout: 60_000 });
  await input.fill(prompt);
  await input.press("Enter");
}

async function assertDevLoginEnabled(page: Page, serverUrl: string): Promise<void> {
  const response = await page.request.get(`${serverUrl}/api/v1/auth/dev-login/status`, {
    timeout: 30_000,
  });
  if (!response.ok()) {
    throw new Error(
      `Local dev-login status probe failed (${response.status()}). ` +
        `Start the visual backend with ENABLE_DEV_LOGIN=true and ENVIRONMENT=development.`,
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!data?.enabled) {
    throw new Error(
      "Local dev-login is disabled. The visual E2E harness requires " +
        "ENABLE_DEV_LOGIN=true on the local backend.",
    );
  }
}

export async function bootstrapLocalChat(
  page: Page,
  options: BootstrapOptions = {},
): Promise<BootstrapResult> {
  const serverUrl = options.serverUrl || defaultServerUrl();
  const userId = options.userId || uniqueUserId();
  const displayName = options.displayName || "Wiii Playwright";

  await assertDevLoginEnabled(page, serverUrl);
  const session = await createDevLoginSession(page, serverUrl, userId, displayName);
  const user = {
    id: session.user?.id || userId,
    email: session.user?.email || safeEmail(userId),
    name: session.user?.name || displayName,
    avatar_url: session.user?.avatar_url || "",
    role: session.user?.role || "admin",
    legacy_role: session.user?.legacy_role || session.user?.role || "admin",
    platform_role: session.user?.platform_role || "platform_admin",
    organization_role: session.user?.organization_role || "",
    host_role: session.user?.host_role || "",
    role_source: session.user?.role_source || "platform",
    active_organization_id: session.user?.active_organization_id || session.organization_id || "",
    connector_id: "",
    identity_version: "2",
  };
  const effectiveSettings = {
    ...settingsPayload(serverUrl, user.id, user.name || displayName),
    user_role: user.role,
    organization_id: user.active_organization_id || undefined,
  };
  const authState = {
    data: {
      user,
      authMode: "oauth",
    },
  };
  const tokenState = {
    tokens: {
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      expires_at: Date.now() + Number(session.expires_in || 900) * 1000,
    },
  };

  await page.addInitScript(
    ({ settings, auth, tokens }) => {
      localStorage.clear();
      sessionStorage.clear();
      localStorage.setItem("wiii:app_settings", JSON.stringify(settings));
      localStorage.setItem("wiii:auth_state", JSON.stringify(auth));
      localStorage.setItem("wiii:wiii_auth_tokens", JSON.stringify(tokens));
    },
    { settings: effectiveSettings, auth: authState, tokens: tokenState },
  );

  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });

  const composer = chatComposer(page);
  await composer.waitFor({ state: "visible", timeout: 60_000 });
  await expect(composer).toBeEnabled({ timeout: 60_000 });

  return { serverUrl, userId: user.id, authenticatedBy: "dev-login-api" };
}
