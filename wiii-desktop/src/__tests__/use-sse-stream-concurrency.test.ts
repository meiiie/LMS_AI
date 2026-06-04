import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSSEStream } from "@/hooks/useSSEStream";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { useContextStore } from "@/stores/context-store";
import { useCharacterStore } from "@/stores/character-store";
import { usePageContextStore } from "@/stores/page-context-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useModelStore } from "@/stores/model-store";
import type { VisualPayload } from "@/api/types";
import { sendMessageStream } from "@/api/chat";
import {
  fetchWiiiConnectFacebookPages,
  fetchWiiiConnectProviderConnections,
} from "@/api/wiii-connect";

vi.mock("@/api/chat", () => ({
  sendMessageStream: vi.fn(),
}));

vi.mock("@/api/wiii-connect", () => ({
  fetchWiiiConnectProviderConnections: vi.fn(),
  fetchWiiiConnectFacebookPages: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  initClient: vi.fn(),
  getClient: () => ({
    get: vi.fn().mockResolvedValue({ providers: [] }),
  }),
}));

vi.mock("@/lib/visual-telemetry", () => ({
  trackVisualTelemetry: vi.fn(),
}));

function makeVisual(overrides?: Partial<VisualPayload>): VisualPayload {
  return {
    id: "visual-patch-1",
    visual_session_id: "vs-1",
    type: "process",
    renderer_kind: "template",
    shell_variant: "editorial",
    patch_strategy: "spec_merge",
    figure_group_id: "fg-vs-1",
    figure_index: 1,
    figure_total: 1,
    pedagogical_role: "mechanism",
    chrome_mode: "editorial",
    claim: "Figure nay mo ta quy trinh duoc patch trong cung session.",
    narrative_anchor: "after-lead",
    runtime: "svg",
    title: "Patched process",
    summary: "Updated process visual",
    spec: {
      steps: [
        { title: "Step 1", description: "Transform inputs" },
        { title: "Step 2", description: "Aggregate efficiently" },
        { title: "Step 3", description: "Approximation error appears here" },
      ],
    },
    scene: { kind: "process", nodes: [], panels: [] },
    controls: [],
    annotations: [],
    interaction_mode: "guided",
    ephemeral: true,
    lifecycle_event: "visual_patch",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();

  useSettingsStore.setState((state) => ({
    ...state,
    settings: {
      ...state.settings,
      server_url: "http://127.0.0.1:8001",
      api_key: "local-dev-key",
      user_id: "sse-race-user",
      user_role: "admin",
      display_name: "SSE Race",
    },
    isLoaded: true,
  }));

  useDomainStore.setState({
    activeDomainId: "maritime",
    domains: [],
    isLoading: false,
    orgAllowedDomains: [],
  });

  useOrgStore.setState({
    activeOrgId: null,
    organizations: [],
    isLoading: false,
    multiTenantEnabled: false,
    subdomainOrgId: null,
    orgSettings: null,
    permissions: [],
    orgRole: null,
    adminContext: null,
  });

  useContextStore.setState({
    info: null,
    status: "unknown",
    isLoading: false,
    isPanelOpen: false,
    error: null,
    pollIntervalId: null,
  });

  useCharacterStore.getState().reset();
  usePageContextStore.getState().clear();
  useHostContextStore.getState().clear();
  vi.mocked(fetchWiiiConnectProviderConnections).mockReset();
  vi.mocked(fetchWiiiConnectFacebookPages).mockReset();
  useModelStore.setState({
    activeProvider: "auto",
    nextTurnProvider: null,
    providers: [],
    isLoading: false,
    lastFetchedAt: null,
  });

  useChatStore.setState({
    conversations: [],
    activeConversationId: null,
    isLoaded: true,
    isStreaming: false,
    streamingContent: "",
    streamingThinking: "",
    streamingSources: [],
    streamingStep: "",
    streamingToolCalls: [],
    streamingBlocks: [],
    streamingStartTime: null,
    streamingSteps: [],
    streamingLifecycleEvents: [],
    lastCompletedLifecycleEvents: [],
    streamingDomainNotice: "",
    streamingPhases: [],
    streamingPreviews: [],
    streamingArtifacts: [],
    pendingStreamMetadata: null,
    visualSessions: {},
    _activeSubagentGroupId: null,
    streamError: "",
    streamCompletedAt: null,
  });
});

describe("useSSEStream concurrency", () => {
  it("does not let an aborted previous stream retry against the new controller", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);

    sendMessageStreamMock.mockImplementationOnce(
      async (_request, _handlers, abortSignal) =>
        new Promise((_resolve, reject) => {
          if (abortSignal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          abortSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );

    sendMessageStreamMock.mockImplementationOnce(async (_request, handlers) => {
      handlers.onVisualPatch?.({
        content: makeVisual(),
        node: "direct",
        display_role: "artifact",
        presentation: "compact",
      });
      handlers.onVisualCommit?.({
        content: {
          visual_session_id: "vs-1",
          status: "committed",
        },
        node: "direct",
        display_role: "artifact",
        presentation: "compact",
      });
      return {
        lastEventId: null,
        sawDone: true,
        eventOrder: ["visual_patch", "visual_commit", "done"],
      };
    });

    const { result } = renderHook(() => useSSEStream());

    let firstSend: Promise<void>;
    let secondSend: Promise<void>;

    await act(async () => {
      firstSend = result.current.sendMessage("First prompt");
      await Promise.resolve();
      secondSend = result.current.sendMessage("Follow-up patch");
      await Promise.allSettled([firstSend!, secondSend!]);
    });

    expect(sendMessageStreamMock).toHaveBeenCalledTimes(2);

    const conversation = useChatStore.getState().activeConversation();
    expect(conversation).toBeTruthy();

    const assistantMessages = conversation?.messages.filter((message) => message.role === "assistant") || [];
    expect(assistantMessages).toHaveLength(1);

    const visualBlocks = (assistantMessages[0]?.blocks || []).filter((block) => block.type === "visual");
    expect(visualBlocks).toHaveLength(1);
    expect((visualBlocks[0] as { visual: VisualPayload }).visual.title).toBe("Patched process");
    expect((visualBlocks[0] as { visual: VisualPayload }).visual.type).toBe("process");
    expect(useChatStore.getState().streamError).toBe("");
  });

  it("sends the selected provider model with the stream request", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);
    useModelStore.setState({
      activeProvider: "openrouter",
      nextTurnProvider: null,
      providers: [
        {
          id: "openrouter",
          displayName: "OpenRouter",
          available: true,
          isPrimary: false,
          isFallback: true,
          state: "selectable",
          reasonCode: null,
          reasonLabel: null,
          selectedModel: "qwen/qwen3.6-plus:free",
          strictPin: true,
          verifiedAt: "2026-04-04T00:00:00Z",
        },
      ],
    });
    sendMessageStreamMock.mockResolvedValueOnce({
      lastEventId: null,
      sawDone: true,
      eventOrder: ["done"],
    });

    const { result } = renderHook(() => useSSEStream());

    await act(async () => {
      await result.current.sendMessage("Thu model OpenRouter");
    });

    expect(sendMessageStreamMock).toHaveBeenCalledTimes(1);
    expect(sendMessageStreamMock.mock.calls[0]?.[0]).toMatchObject({
      provider: "openrouter",
      model: "qwen/qwen3.6-plus:free",
    });
  });

  it("captures chat lifecycle telemetry without displaying raw lifecycle payloads", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);
    sendMessageStreamMock.mockImplementationOnce(async (_request, handlers) => {
      handlers.onChatLifecycle?.({
        schema_version: "wiii.chat_runtime_lifecycle.v1",
        event_name: "path.selected",
        phase: "routing",
        status: "selected",
        message: "Path selected",
        lane: "native_turn",
        capabilities: {
          host_surface: "desktop_chat",
          observed_tools: ["tool_web_search"],
          suppressed_tools: ["host_action"],
          preview_required: false,
          wiii_connect: {
            version: "wiii_connect_snapshot.v0",
            surface: "desktop_chat",
            connections: [
              {
                slug: "document_corpus",
                label: "Document corpus",
                status: "connected",
                active: true,
                agent_ready: true,
                attachment_count: 1,
                filename: "private.docx",
                approval_token: "must-not-persist",
              },
            ],
            path_capabilities: [
              {
                path: "document_grounded_answer",
                raw_prompt: "must-not-persist",
              },
            ],
          },
        },
        metadata: {
          model: "qwen/qwen3-next-80b-a3b-instruct",
          raw_payload: { should_not: "persist" },
        },
        details: {
          reason_code: "native_runtime",
          raw_payload: { should_not: "persist" },
        },
      });
      handlers.onAnswer({ content: "Lifecycle observed." });
      handlers.onMetadata({
        processing_time: 0.2,
        model: "qwen/qwen3-next-80b-a3b-instruct",
        agent_type: "direct",
      });
      handlers.onDone();
      return {
        lastEventId: null,
        sawDone: true,
        eventOrder: ["chat_lifecycle", "answer", "metadata", "done"],
      };
    });

    const { result } = renderHook(() => useSSEStream());

    await act(async () => {
      await result.current.sendMessage("hello");
      await Promise.resolve();
    });

    const state = useChatStore.getState();
    expect(state.streamingLifecycleEvents).toHaveLength(0);
    expect(state.lastCompletedLifecycleEvents).toHaveLength(1);
    expect(state.lastCompletedLifecycleEvents[0]).toMatchObject({
      event_name: "path.selected",
      lane: "native_turn",
      status: "selected",
      capabilities: {
        observed_tools: ["tool_web_search"],
        suppressed_tools: ["host_action"],
        wiii_connect: {
          version: "wiii_connect_snapshot.v0",
          connections: [
            {
              slug: "document_corpus",
              label: "Document corpus",
              attachment_count: 1,
            },
          ],
        },
      },
      metadata: {
        model: "qwen/qwen3-next-80b-a3b-instruct",
      },
      details: {
        reason_code: "native_runtime",
      },
      received_at_ms: expect.any(Number),
    });
    expect(state.lastCompletedLifecycleEvents[0]?.metadata).not.toHaveProperty(
      "raw_payload",
    );
    expect(state.lastCompletedLifecycleEvents[0]?.details).not.toHaveProperty(
      "raw_payload",
    );
    const sanitizedLifecycle = JSON.stringify(
      state.lastCompletedLifecycleEvents[0]?.capabilities,
    );
    expect(sanitizedLifecycle).not.toContain("private.docx");
    expect(sanitizedLifecycle).not.toContain("approval_token");
    expect(sanitizedLifecycle).not.toContain("raw_prompt");

    const conversation = state.activeConversation();
    const assistantMessages =
      conversation?.messages.filter((message) => message.role === "assistant") ||
      [];
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessages[0]?.content).toContain("Lifecycle observed.");
    expect(assistantMessages[0]?.content).not.toContain("Path selected");

    const lifecycleMetadata = assistantMessages[0]?.metadata?.chat_lifecycle as
      | unknown[]
      | undefined;
    expect(Array.isArray(lifecycleMetadata)).toBe(true);
    expect(lifecycleMetadata).toHaveLength(1);
    expect(lifecycleMetadata?.[0]).toMatchObject({
      event_name: "path.selected",
      phase: "routing",
      received_at_ms: expect.any(Number),
    });

    useChatStore.getState().startStreaming();
    expect(useChatStore.getState().streamingLifecycleEvents).toHaveLength(0);
    expect(useChatStore.getState().lastCompletedLifecycleEvents).toHaveLength(0);
    useChatStore.getState().clearStreaming();
  });

  it("sends Wiii Connect Facebook snapshot even when host context is missing", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);
    vi.mocked(fetchWiiiConnectProviderConnections).mockResolvedValueOnce({
      version: "wiii_connect_connection_list.v1",
      provider_slug: "facebook",
      status: "ready",
      connections: [
        {
          provider_slug: "facebook",
          connection_ref: "conn-1",
          connection_id: "conn-1",
          state: "connected",
          active: true,
        },
      ],
      connection_count: 1,
    } as any);
    vi.mocked(fetchWiiiConnectFacebookPages).mockResolvedValueOnce({
      version: "wiii_connect_facebook_pages.v1",
      provider_slug: "facebook",
      status: "ready",
      connection_ref: "conn-1",
      pages: [{ page_id: "page-1", name: "Wiii" }],
      page_count: 1,
    } as any);
    sendMessageStreamMock.mockResolvedValueOnce({
      lastEventId: null,
      sawDone: true,
      eventOrder: ["done"],
    });

    const { result } = renderHook(() => useSSEStream());

    await act(async () => {
      await result.current.sendMessage("Wiii có kết nối được Facebook không?");
    });

    const request = sendMessageStreamMock.mock.calls[0]?.[0] as any;
    const hostContext = request.user_context?.host_context;
    expect(hostContext?.host_type).toBe("wiii-desktop");
    expect(hostContext?.page?.metadata?.wiii_connect).toMatchObject({
      provider_slug: "facebook",
      provider_label: "Facebook",
      status: "connected",
      active_connection_count: 1,
      page_count: 1,
      page_names: ["Wiii"],
      available_actions: [
        "wiii_connect.facebook_post.direct_apply",
        "wiii_connect.facebook_post.preview",
        "wiii_connect.facebook_post.apply",
      ],
    });
  });

  it("sends pending Facebook connection state without probing pages", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);
    vi.mocked(fetchWiiiConnectProviderConnections).mockResolvedValueOnce({
      version: "wiii_connect_connection_list.v1",
      provider_slug: "facebook",
      status: "ready",
      connections: [
        {
          provider_slug: "facebook",
          connection_ref: "conn-waiting",
          connection_id: "conn-waiting",
          state: "waiting",
          active: false,
          reason: "provider_connection_list",
        },
      ],
      connection_count: 1,
    } as any);
    sendMessageStreamMock.mockResolvedValueOnce({
      lastEventId: null,
      sawDone: true,
      eventOrder: ["done"],
    });

    const { result } = renderHook(() => useSSEStream());

    await act(async () => {
      await result.current.sendMessage("Wiii connected Facebook?");
    });

    expect(fetchWiiiConnectFacebookPages).not.toHaveBeenCalled();
    const request = sendMessageStreamMock.mock.calls[0]?.[0] as any;
    expect(request.user_context?.host_context?.page?.metadata?.wiii_connect).toMatchObject({
      provider_slug: "facebook",
      status: "not_connected",
      connection_count: 1,
      active_connection_count: 0,
      connection_state: "waiting",
      connection_active: false,
      blocked_reason: "provider_connection_list",
    });
  });

  it("sanitizes host context and action feedback before sending chat request", async () => {
    const sendMessageStreamMock = vi.mocked(sendMessageStream);
    useHostContextStore.getState().updateContext({
      host_type: "lms",
      page: {
        type: "lesson",
        title: "COLREGs",
        metadata: {
          safe: "visible metadata",
          connection_ref: "conn-secret",
          connection_id: "conn-secret-id",
          page_id: "page-secret",
          access_token: "access-secret",
          wiii_connect: {
            provider_slug: "facebook",
            status: "connected",
            connection_ref: "conn-secret",
            page_id: "page-secret",
          },
        },
      },
      selection: {
        text: "visible selection",
        approval_token: "approval-secret",
      },
      available_actions: [
        {
          action: "safe.action",
          label: "Safe action",
          input_schema: {
            properties: {
              message: { type: "string" },
              connection_ref: { type: "string" },
              image_base64: { type: "string" },
            },
          },
        },
      ],
    });
    useHostContextStore.setState({
      lastActionResult: {
        request_id: "req-secret",
        action: "wiii_connect.facebook_post.preview",
        params: {
          message: "visible message",
          connection_ref: "conn-secret",
          page_id: "page-secret",
        },
        success: true,
        summary: "Visible summary.",
        data: {
          preview_kind: "facebook_post",
          message: "visible message",
          approval_token: "approval-secret",
          facebook_post_body: {
            connection_ref: "conn-secret",
            page_id: "page-secret",
            message: "visible message",
          },
        },
        timestamp: "2026-05-29T00:00:00.000Z",
      },
      recentActionResults: [],
    });
    sendMessageStreamMock.mockResolvedValueOnce({
      lastEventId: null,
      sawDone: true,
      eventOrder: ["done"],
    });

    const { result } = renderHook(() => useSSEStream());

    await act(async () => {
      await result.current.sendMessage("Summarize the current page");
    });

    const request = sendMessageStreamMock.mock.calls[0]?.[0] as any;
    const userContext = request.user_context;
    const serialized = JSON.stringify(userContext);
    expect(userContext?.host_context?.page?.metadata?.safe).toBe("visible metadata");
    expect(userContext?.page_context?.safe).toBe("visible metadata");
    expect(serialized).toContain("visible selection");
    expect(serialized).toContain("Visible summary.");
    expect(serialized).toContain("visible message");
    expect(serialized).not.toContain("conn-secret");
    expect(serialized).not.toContain("conn-secret-id");
    expect(serialized).not.toContain("page-secret");
    expect(serialized).not.toContain("access-secret");
    expect(serialized).not.toContain("approval-secret");
    expect(serialized).not.toContain("connection_ref");
    expect(serialized).not.toContain("connection_id");
    expect(serialized).not.toContain("page_id");
    expect(serialized).not.toContain("access_token");
    expect(serialized).not.toContain("approval_token");
    expect(serialized).not.toContain("image_base64");
  });
});
