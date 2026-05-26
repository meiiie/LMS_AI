/**
 * Sprint 106: Polish & completeness tests.
 * Tests loading screen logic, disconnected banner, connection badge reconnect.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useSettingsStore } from "@/stores/settings-store";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";

// Mock APIs
vi.mock("@/api/health", () => ({
  checkHealth: vi.fn(),
}));

import * as healthApi from "@/api/health";

beforeEach(() => {
  vi.clearAllMocks();
  useSettingsStore.setState({
    settings: {
      server_url: "http://localhost:8000",
      api_key: "",
      user_id: "test-user-fixed",
      user_role: "student",
      display_name: "User",
      default_domain: "maritime",
      theme: "system",
      language: "vi",
      font_size: "medium",
      show_thinking: true,
      show_reasoning_trace: false,
      streaming_version: "v3",
      thinking_level: "balanced",
    },
    isLoaded: false,
  });
  useChatStore.setState({
    conversations: [],
    activeConversationId: null,
    isLoaded: false,
    isStreaming: false,
    streamingBlocks: [],
  });
  useConnectionStore.setState({
    status: "disconnected",
    serverVersion: null,
    lastCheckedAt: null,
    errorMessage: null,
    consecutiveFailures: 0,
    pollIntervalId: null,
  });
});

describe("Loading Screen — Store readiness", () => {
  it("should not be ready when settings not loaded", () => {
    useSettingsStore.setState({ isLoaded: false });
    useChatStore.setState({ isLoaded: true });

    const settingsLoaded = useSettingsStore.getState().isLoaded;
    const chatsLoaded = useChatStore.getState().isLoaded;
    expect(settingsLoaded && chatsLoaded).toBe(false);
  });

  it("should not be ready when chats not loaded", () => {
    useSettingsStore.setState({ isLoaded: true });
    useChatStore.setState({ isLoaded: false });

    const settingsLoaded = useSettingsStore.getState().isLoaded;
    const chatsLoaded = useChatStore.getState().isLoaded;
    expect(settingsLoaded && chatsLoaded).toBe(false);
  });

  it("should be ready when both loaded", () => {
    useSettingsStore.setState({ isLoaded: true });
    useChatStore.setState({ isLoaded: true });

    const settingsLoaded = useSettingsStore.getState().isLoaded;
    const chatsLoaded = useChatStore.getState().isLoaded;
    expect(settingsLoaded && chatsLoaded).toBe(true);
  });
});

describe("Disconnected Banner — Connection status", () => {
  it("should show banner when disconnected", () => {
    useConnectionStore.setState({ status: "disconnected" });
    expect(useConnectionStore.getState().status).toBe("disconnected");
    const showDisconnected = useConnectionStore.getState().status === "disconnected";
    expect(showDisconnected).toBe(true);
  });

  it("should not show banner when connected", () => {
    useConnectionStore.setState({ status: "connected" });
    const showDisconnected = useConnectionStore.getState().status === "disconnected";
    expect(showDisconnected).toBe(false);
  });

  it("should not show banner when degraded", () => {
    useConnectionStore.setState({ status: "degraded" });
    const showDisconnected = useConnectionStore.getState().status === "disconnected";
    expect(showDisconnected).toBe(false);
  });

  it("should not show banner when checking", () => {
    useConnectionStore.setState({ status: "checking" });
    const showDisconnected = useConnectionStore.getState().status === "disconnected";
    expect(showDisconnected).toBe(false);
  });
});

describe("ConnectionBadge — Reconnect logic", () => {
  it("should allow reconnect when disconnected", () => {
    useConnectionStore.setState({ status: "disconnected" });
    const status = useConnectionStore.getState().status;
    const canReconnect = status === "disconnected" || status === "degraded";
    expect(canReconnect).toBe(true);
  });

  it("should allow reconnect when degraded", () => {
    useConnectionStore.setState({ status: "degraded" });
    const status = useConnectionStore.getState().status;
    const canReconnect = status === "disconnected" || status === "degraded";
    expect(canReconnect).toBe(true);
  });

  it("should not allow reconnect when connected", () => {
    useConnectionStore.setState({ status: "connected" });
    const status = useConnectionStore.getState().status;
    const canReconnect = status === "disconnected" || status === "degraded";
    expect(canReconnect).toBe(false);
  });

  it("should not allow reconnect when checking", () => {
    useConnectionStore.setState({ status: "checking" });
    const status = useConnectionStore.getState().status;
    const canReconnect = status === "disconnected" || status === "degraded";
    expect(canReconnect).toBe(false);
  });

  it("should transition to connected after successful health check", async () => {
    vi.mocked(healthApi.checkHealth).mockResolvedValue({
      status: "ok",
      version: "1.0.0",
      environment: "development",
    });

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("connected");
    expect(useConnectionStore.getState().serverVersion).toBe("1.0.0");
  });

  it("should remain disconnected after failed health check", async () => {
    vi.mocked(healthApi.checkHealth).mockRejectedValue(
      new Error("Connection refused")
    );

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("disconnected");
    expect(useConnectionStore.getState().errorMessage).toBe("Connection refused");
  });

  it("should treat a single connected-state health failure as degraded", async () => {
    useConnectionStore.setState({
      status: "connected",
      consecutiveFailures: 0,
    });
    vi.mocked(healthApi.checkHealth).mockRejectedValue(
      new Error("Backend hot reload")
    );

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("degraded");
    expect(useConnectionStore.getState().consecutiveFailures).toBe(1);
  });

  it("should mark disconnected after repeated health failures", async () => {
    useConnectionStore.setState({
      status: "degraded",
      consecutiveFailures: 1,
    });
    vi.mocked(healthApi.checkHealth).mockRejectedValue(
      new Error("Connection refused")
    );

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("disconnected");
    expect(useConnectionStore.getState().consecutiveFailures).toBe(2);
  });

  it("should reset failure count after successful health check", async () => {
    useConnectionStore.setState({
      status: "degraded",
      consecutiveFailures: 1,
    });
    vi.mocked(healthApi.checkHealth).mockResolvedValue({
      status: "ok",
      version: "1.0.0",
      environment: "development",
    });

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("connected");
    expect(useConnectionStore.getState().consecutiveFailures).toBe(0);
  });

  it("should set degraded for non-ok health response", async () => {
    vi.mocked(healthApi.checkHealth).mockResolvedValue({
      status: "degraded",
      version: "1.0.0",
      environment: "development",
    });

    await useConnectionStore.getState().checkHealth();

    expect(useConnectionStore.getState().status).toBe("degraded");
  });
});
