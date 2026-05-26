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

export type ChatBaselineScenario = {
  id: string;
  prompt: string;
  answerChunks: string[];
  expectedText: string;
  expectedTurnPath: string;
  expectCodeBlock?: boolean;
};

export type ChatBaselineTurnCapture = {
  scenarioId: string;
  request: Record<string, unknown>;
};

export type ObservedChatBaselineEvent = {
  id: string | null;
  type: string;
  data: Record<string, unknown> | null;
  rawData: string;
};

export type ObservedChatBaselineStream = {
  url: string;
  status: number;
  events: ObservedChatBaselineEvent[];
  done: boolean;
  error?: string;
};

type PersistedAssistantMessage = {
  role?: string;
  content?: string;
  metadata?: Record<string, unknown>;
};

const CHAT_BASELINE_SUPPRESSED_TOOLS = [
  "host_action",
  "pointy_action",
  "visual_runtime",
  "code_studio",
];

const RAW_CHAT_BASELINE_MARKERS = [
  '"tool_calls"',
  '"function_call"',
  '"host_action"',
  '"pointy_action"',
  '"visual_open"',
  '"code_open"',
  "<wiii-widget",
  "[POINT:",
  "runtime_flow_ledger",
  "turn_path_decision",
];

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

export function assistantMessages(page: Page) {
  return page.locator('[data-message-role="assistant"]');
}

export function lastAssistantMessage(page: Page) {
  return assistantMessages(page).last();
}

export async function sendPrompt(page: Page, prompt: string): Promise<void> {
  const input = chatComposer(page);
  await input.waitFor({ state: "visible", timeout: 60_000 });
  await expect(input).toBeEnabled({ timeout: 60_000 });
  await input.fill(prompt);
  await input.press("Enter");
}

export async function waitForGenerationToSettle(page: Page): Promise<void> {
  await expect
    .poll(
      async () => page.locator('[aria-label="Dừng tạo phản hồi"]').count(),
      { timeout: 120_000, intervals: [500, 1_000, 1_500] },
    )
    .toBe(0);
  await expect(chatComposer(page)).toBeEnabled({ timeout: 60_000 });
}

export async function expectNoBaselineToolSurfaces(page: Page): Promise<void> {
  await expect(page.getByTestId("visual-block")).toHaveCount(0);
  await expect(page.locator(".code-studio-card")).toHaveCount(0);
  await expect(page.locator(".code-studio-panel")).toHaveCount(0);
  await expect(page.locator('[aria-label^="Preview thao tác host"]')).toHaveCount(0);
  await expect(page.locator(
    '[data-wiii-pointy="overlay"], [data-wiii-pointy="target-ring"], [data-wiii-pointy="tooltip"]',
  )).toHaveCount(0);
}

export function expectNoRawChatBaselinePayload(text: string): void {
  for (const marker of RAW_CHAT_BASELINE_MARKERS) {
    expect(text).not.toContain(marker);
  }
}

function formatSseEvent(
  id: number,
  type: string,
  data: Record<string, unknown>,
): string {
  return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

function createChatBaselineLedger(
  request: Record<string, unknown>,
  scenario: ChatBaselineScenario,
  eventTypes: string[],
  finalizationStatus: "pending" | "saved",
) {
  const eventCounts = eventTypes.reduce<Record<string, number>>((counts, type) => {
    counts[type] = (counts[type] || 0) + 1;
    return counts;
  }, {});
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "browser-chat-baseline",
      session_id: typeof request.session_id === "string" ? request.session_id : null,
      user_id_hash: "browser-harness-user",
      organization_id_hash: null,
      domain_id: typeof request.domain_id === "string" ? request.domain_id : null,
      host_surface: "desktop_chat",
      host_capabilities: [],
    },
    context: {
      document_context_present: false,
      uploaded_document_count: 0,
      source_ref_count: 0,
      memory_context_count: 0,
      context_provenance: {
        uploaded_documents: 0,
        source_references: 0,
        memory_items: 0,
      },
    },
    route: {
      lane: "native_turn",
      reason: "browser_chat_baseline_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: scenario.expectedTurnPath,
        reason: "browser_chat_baseline_mock",
        bind_tools: false,
        force_tools: false,
      },
    },
    runtime: {
      requested_provider: typeof request.provider === "string" ? request.provider : null,
      requested_model: typeof request.model === "string" ? request.model : null,
      provider: "browser-harness",
      model: "browser-chat-baseline-mock",
      runtime_authoritative: true,
      fallback_used: false,
      fallback_reason: null,
      failover_used: false,
    },
    tools: {
      observed: [],
      suppressed: CHAT_BASELINE_SUPPRESSED_TOOLS,
    },
    stream: {
      transport: "sse_v3",
      event_counts: eventCounts,
      event_sequence_tail: eventTypes.slice(-12),
      metadata_seen: eventTypes.includes("metadata"),
      done_seen: eventTypes.includes("done"),
    },
    host_actions: {
      preview_required: false,
      preview_emitted: false,
      approval_token_present: false,
      approval_token_hash: null,
      apply_attempted: false,
      mutation_blocked_reason: null,
    },
    finalization: {
      status: finalizationStatus,
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function createChatLifecycleEvent(
  eventName: string,
  phase: string,
  status: string,
  message: string,
  request: Record<string, unknown>,
  scenario: ChatBaselineScenario,
): Record<string, unknown> {
  return {
    schema_version: "wiii.chat_runtime_lifecycle.v1",
    event_name: eventName,
    phase,
    status,
    message,
    request_id: "browser-chat-baseline",
    session_id: typeof request.session_id === "string" ? request.session_id : "browser-session",
    lane: "native_turn",
    reason: "browser_chat_baseline_acceptance",
    node: "browser_harness",
    capabilities: {
      host_surface: "desktop_chat",
      host_capabilities: [],
      observed_tools: [],
      suppressed_tools: CHAT_BASELINE_SUPPRESSED_TOOLS,
      preview_required: false,
      preview_emitted: false,
      approval_token_present: false,
      apply_attempted: false,
    },
    metadata: {
      provider: "browser-harness",
      model: "browser-chat-baseline-mock",
      bound_tools: [],
      turn_path: scenario.expectedTurnPath,
      runtime_authoritative: true,
    },
  };
}

function createChatBaselineLifecycleEvents(
  request: Record<string, unknown>,
  scenario: ChatBaselineScenario,
): Array<Record<string, unknown>> {
  return [
    createChatLifecycleEvent(
      "path.selected",
      "routing",
      "selected",
      "Browser baseline selected ordinary chat lane.",
      request,
      scenario,
    ),
    createChatLifecycleEvent(
      "capability.checked",
      "capability",
      "allowed",
      "Browser baseline suppressed tool-capable surfaces.",
      request,
      scenario,
    ),
    createChatLifecycleEvent(
      "finalization.completed",
      "finalization",
      "completed",
      "Browser baseline assistant message finalized.",
      request,
      scenario,
    ),
    createChatLifecycleEvent(
      "chat.done",
      "terminal",
      "completed",
      "Browser baseline stream completed.",
      request,
      scenario,
    ),
  ];
}

function parseChatRequestBody(raw: string | null): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return { parse_error: "invalid_json" };
  }
}

export async function installChatBaselineStreamMock(
  page: Page,
  scenarios: ChatBaselineScenario[],
) {
  const captures: ChatBaselineTurnCapture[] = [];
  const byPrompt = new Map(scenarios.map((scenario) => [scenario.prompt, scenario]));

  await page.addInitScript(() => {
    type BrowserObservedEvent = {
      id: string | null;
      type: string;
      data: Record<string, unknown> | null;
      rawData: string;
    };
    type BrowserObservedStream = {
      url: string;
      status: number;
      events: BrowserObservedEvent[];
      done: boolean;
      error?: string;
    };
    type BrowserWindow = typeof window & {
      __wiiiChatBaselineFetchWrapped?: boolean;
      __wiiiChatBaselineObservedStreams?: BrowserObservedStream[];
    };

    const browserWindow = window as BrowserWindow;
    if (browserWindow.__wiiiChatBaselineFetchWrapped) return;

    browserWindow.__wiiiChatBaselineFetchWrapped = true;
    const originalFetch = window.fetch.bind(window);
    const observedStreams: BrowserObservedStream[] = [];
    browserWindow.__wiiiChatBaselineObservedStreams = observedStreams;

    const parseSseText = (text: string): BrowserObservedEvent[] => text
      .split(/\r?\n\r?\n/)
      .map((block) => block.trim())
      .filter(Boolean)
      .map((block) => {
        let id: string | null = null;
        let type = "message";
        const dataLines: string[] = [];

        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("id:")) {
            id = line.slice(3).trim();
          } else if (line.startsWith("event:")) {
            type = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trimStart());
          }
        }

        const rawData = dataLines.join("\n");
        let data: Record<string, unknown> | null = null;
        if (rawData) {
          try {
            const parsed = JSON.parse(rawData);
            data = parsed && typeof parsed === "object"
              ? parsed as Record<string, unknown>
              : { value: parsed };
          } catch {
            data = { parse_error: "invalid_json", raw: rawData };
          }
        }

        return { id, type, data, rawData };
      });

    const requestUrl = (input: Parameters<typeof fetch>[0]): string => {
      if (typeof input === "string") return input;
      if (input instanceof URL) return input.toString();
      return input.url;
    };

    window.fetch = async (
      input: Parameters<typeof fetch>[0],
      init?: Parameters<typeof fetch>[1],
    ): Promise<Response> => {
      const response = await originalFetch(input, init);
      const url = requestUrl(input);

      if (url.includes("/api/v1/chat/stream/v3")) {
        const record: BrowserObservedStream = {
          url,
          status: response.status,
          events: [],
          done: false,
        };
        observedStreams.push(record);
        response.clone().text()
          .then((text) => {
            record.events = parseSseText(text);
            record.done = record.events.some((event) => event.type === "done");
          })
          .catch((error: unknown) => {
            record.error = error instanceof Error ? error.message : String(error);
          });
      }

      return response;
    };
  });

  await page.route("**/api/v1/chat/stream/v3", async (route) => {
    const request = parseChatRequestBody(route.request().postData());
    const prompt = typeof request.message === "string" ? request.message : "";
    const scenario = byPrompt.get(prompt);

    if (!scenario) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: `Unexpected chat-baseline prompt: ${prompt}` }),
      });
      return;
    }

    const lifecycleEvents = createChatBaselineLifecycleEvents(request, scenario);
    const eventTypes = [
      ...lifecycleEvents.map(() => "chat_lifecycle"),
      "status",
      ...scenario.answerChunks.map(() => "answer"),
      "metadata",
      "done",
    ];
    const metadataLedger = createChatBaselineLedger(
      request,
      scenario,
      eventTypes.filter((type) => type !== "done"),
      "pending",
    );
    const terminalLedger = createChatBaselineLedger(request, scenario, eventTypes, "saved");
    const sseEvents: Array<{ type: string; data: Record<string, unknown> }> = [
      ...lifecycleEvents.map((data) => ({
        type: "chat_lifecycle",
        data,
      })),
      {
        type: "status",
        data: {
          content: "Đang kiểm tra baseline chat...",
          step: "browser_chat_baseline",
          node: "browser_harness",
          details: {
            subtype: "status_only",
            visibility: "status_only",
          },
        },
      },
      ...scenario.answerChunks.map((content) => ({
        type: "answer",
        data: { content },
      })),
      {
        type: "metadata",
        data: {
          session_id: typeof request.session_id === "string" ? request.session_id : "browser-session",
          thread_id: `browser-thread-${scenario.id}`,
          processing_time: 0.12,
          confidence: 1,
          model: "browser-chat-baseline-mock",
          runtime_authoritative: true,
          routing_metadata: {
            method: "browser_chat_baseline_acceptance",
            intent: "ordinary_chat",
          },
          turn_path_decision: {
            path: scenario.expectedTurnPath,
            reason: "browser_chat_baseline_mock",
            bind_tools: false,
            force_tools: false,
          },
          runtime_flow_ledger: metadataLedger,
        },
      },
      {
        type: "done",
        data: {
          status: "complete",
          processing_time: 0.12,
          runtime_flow_ledger: terminalLedger,
        },
      },
    ];

    captures.push({ scenarioId: scenario.id, request });

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: sseEvents.map((event, index) => formatSseEvent(index + 1, event.type, event.data)).join(""),
    });
  });

  return { captures };
}

export async function readObservedChatBaselineStreams(
  page: Page,
): Promise<ObservedChatBaselineStream[]> {
  return page.evaluate(() => {
    type BrowserWindow = typeof window & {
      __wiiiChatBaselineObservedStreams?: ObservedChatBaselineStream[];
    };
    return (window as BrowserWindow).__wiiiChatBaselineObservedStreams || [];
  });
}

export async function waitForObservedChatBaselineStream(
  page: Page,
  index: number,
): Promise<ObservedChatBaselineStream> {
  await expect
    .poll(
      async () => {
        const stream = (await readObservedChatBaselineStreams(page))[index];
        if (!stream) return `missing:${index}`;
        if (stream.error) return `error:${stream.error}`;
        return stream.done ? "done" : `pending:${stream.events.length}`;
      },
      { timeout: 30_000, intervals: [250, 500, 1_000] },
    )
    .toBe("done");

  const stream = (await readObservedChatBaselineStreams(page))[index];
  if (!stream) {
    throw new Error(`Browser did not observe chat-baseline stream ${index}.`);
  }
  if (stream.error) {
    throw new Error(`Browser failed to observe chat-baseline stream ${index}: ${stream.error}`);
  }
  return stream;
}

export async function readPersistedAssistantMessages(
  page: Page,
  userId: string,
): Promise<PersistedAssistantMessage[]> {
  return page.evaluate((uid) => {
    const raw = localStorage.getItem(`wiii:conversations_${uid}.json`);
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      const conversations = parsed?.[`conversations_${uid}`];
      if (!Array.isArray(conversations)) return [];
      return conversations.flatMap((conversation: { messages?: unknown[] }) => {
        const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
        return messages.filter((message: unknown) => (
          Boolean(message)
          && typeof message === "object"
          && (message as { role?: unknown }).role === "assistant"
        ));
      });
    } catch {
      return [];
    }
  }, userId);
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
        "ENABLE_DEV_LOGIN=true and ENVIRONMENT=development on the local backend.",
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
