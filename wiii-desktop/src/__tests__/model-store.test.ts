import { beforeEach, describe, expect, it, vi } from "vitest";
import { useModelStore } from "@/stores/model-store";
import { useSettingsStore } from "@/stores/settings-store";

const getMock = vi.fn();

vi.mock("@/api/client", () => ({
  getClient: () => ({
    get: getMock,
  }),
}));

const BASE_SETTINGS = {
  server_url: "http://localhost:8000",
  api_key: "local-dev-key",
  llm_provider: "google" as const,
  user_id: "test-user",
  user_role: "student" as const,
  display_name: "Minh",
  default_domain: "maritime",
  theme: "system" as const,
  language: "vi" as const,
  show_thinking: true,
  show_reasoning_trace: false,
  streaming_version: "v3" as const,
  thinking_level: "balanced" as const,
  model_provider: "auto" as const,
};

describe("Model store", () => {
  beforeEach(() => {
    getMock.mockReset();
    useSettingsStore.setState({
      settings: { ...BASE_SETTINGS },
      isLoaded: true,
    });
    useModelStore.setState({
      activeProvider: "auto",
      activeModel: null,
      nextTurnProvider: null,
      providers: [],
      isLoading: false,
      lastFetchedAt: null,
    });
  });

  it("persists active provider selection into settings store", () => {
    useModelStore.getState().setActiveProvider("zhipu");

    expect(useModelStore.getState().activeProvider).toBe("zhipu");
    expect(useSettingsStore.getState().settings.model_provider).toBe("zhipu");
  });

  it("syncs active provider when settings store changes after hydration", async () => {
    await useSettingsStore.getState().updateSettings({
      model_provider: "openai",
    });

    expect(useModelStore.getState().activeProvider).toBe("openai");
  });

  it("resets to auto when fetched provider becomes disabled", async () => {
    useModelStore.setState({ activeProvider: "google" });
    await useSettingsStore.getState().updateSettings({ model_provider: "google" });
    getMock.mockResolvedValueOnce({
      providers: [
        {
          id: "google",
          display_name: "Gemini",
          available: false,
          is_primary: true,
          is_fallback: false,
          state: "disabled",
          reason_code: "busy",
          reason_label: "Provider tam thoi ban hoac da cham gioi han.",
          selected_model: "gemini-3.1-flash-lite-preview",
          strict_pin: true,
          verified_at: "2026-03-23T00:00:00Z",
        },
      ],
    });

    await useModelStore.getState().fetchProviders({ force: true });

    expect(useModelStore.getState().activeProvider).toBe("auto");
    expect(useSettingsStore.getState().settings.model_provider).toBe("auto");
  });

  it("keeps the current selection when provider catalog is temporarily empty", async () => {
    await useSettingsStore.getState().updateSettings({
      model_provider: "nvidia",
      nvidia_model: "nvidia/nemotron-3-ultra",
    });
    getMock.mockResolvedValueOnce({ providers: [] });

    await useModelStore.getState().fetchProviders({ force: true });

    expect(useModelStore.getState().activeProvider).toBe("nvidia");
    expect(useModelStore.getState().activeModel).toBe("nvidia/nemotron-3-ultra");
    expect(useSettingsStore.getState().settings.model_provider).toBe("nvidia");
  });

  it("does not reset a concrete model when live catalog omits its provider", async () => {
    await useSettingsStore.getState().updateSettings({
      model_provider: "nvidia",
      nvidia_model: "nvidia/nemotron-3-ultra",
    });
    getMock.mockResolvedValueOnce({
      providers: [
        {
          id: "zhipu",
          display_name: "Zhipu GLM",
          available: true,
          is_primary: false,
          is_fallback: true,
          state: "selectable",
          reason_code: null,
          reason_label: null,
          selected_model: "glm-5",
          strict_pin: true,
          verified_at: "2026-06-05T00:00:00Z",
        },
      ],
    });

    await useModelStore.getState().fetchProviders({ force: true });

    expect(useModelStore.getState().activeProvider).toBe("nvidia");
    expect(useModelStore.getState().activeModel).toBe("nvidia/nemotron-3-ultra");
    expect(useSettingsStore.getState().settings.model_provider).toBe("nvidia");
  });

  it("preserves discovered model options when a later status refresh omits catalog data", async () => {
    useModelStore.setState({
      providers: [
        {
          id: "nvidia",
          displayName: "NVIDIA NIM",
          available: true,
          isPrimary: true,
          isFallback: false,
          state: "selectable",
          reasonCode: null,
          reasonLabel: null,
          selectedModel: "qwen/qwen3-next-80b-a3b-instruct",
          modelOptions: [
            {
              provider: "nvidia",
              model_name: "nvidia/nemotron-3-ultra-550b-a55b",
              display_name: "Nemotron 3 Ultra",
              status: "available",
              released_on: null,
              is_default: false,
            },
          ],
          strictPin: true,
          verifiedAt: null,
        },
      ],
    });
    getMock.mockResolvedValueOnce({
      providers: [
        {
          id: "nvidia",
          display_name: "NVIDIA NIM",
          available: true,
          is_primary: true,
          is_fallback: false,
          state: "selectable",
          reason_code: null,
          reason_label: null,
          selected_model: "qwen/qwen3-next-80b-a3b-instruct",
          strict_pin: true,
          verified_at: "2026-06-05T00:00:00Z",
        },
      ],
    });

    await useModelStore.getState().fetchProviders({ force: true });

    expect(useModelStore.getState().providers[0]?.modelOptions).toEqual([
      expect.objectContaining({
        model_name: "nvidia/nemotron-3-ultra-550b-a55b",
      }),
    ]);
  });

  it("supports one-shot provider override for the next request", () => {
    useModelStore.getState().setNextTurnProvider("zhipu");

    expect(useModelStore.getState().consumeProviderForRequest()).toBe("zhipu");
    expect(useModelStore.getState().nextTurnProvider).toBeNull();
    expect(useModelStore.getState().consumeProviderForRequest()).toBe("auto");
  });

  it("resolves the selected model for an explicit provider request", () => {
    useSettingsStore.setState((state) => ({
      ...state,
      settings: {
        ...state.settings,
        openrouter_model: "openai/gpt-oss-20b:free",
      },
    }));
    useModelStore.setState({
      activeProvider: "openrouter",
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
          modelOptions: [],
          strictPin: true,
          verifiedAt: null,
        },
      ],
    });

    expect(useModelStore.getState().consumeSelectionForRequest()).toEqual({
      provider: "openrouter",
      model: "qwen/qwen3.6-plus:free",
    });
  });

  it("uses a user-selected model override for an explicit provider request", () => {
    useModelStore.setState({
      activeProvider: "auto",
      activeModel: null,
      providers: [
        {
          id: "nvidia",
          displayName: "NVIDIA NIM",
          available: true,
          isPrimary: false,
          isFallback: true,
          state: "selectable",
          reasonCode: null,
          reasonLabel: null,
          selectedModel: "qwen/qwen3-next-80b-a3b-instruct",
          modelOptions: [
            {
              provider: "nvidia",
              model_name: "nvidia/nemotron-3-ultra",
              display_name: "Nemotron 3 Ultra",
              status: "available",
              released_on: null,
              is_default: false,
            },
          ],
          strictPin: true,
          verifiedAt: null,
        },
      ],
    });

    useModelStore.getState().setActiveModel("nvidia", "nvidia/nemotron-3-ultra");

    expect(useModelStore.getState().consumeSelectionForRequest()).toEqual({
      provider: "nvidia",
      model: "nvidia/nemotron-3-ultra",
    });
    expect(useSettingsStore.getState().settings.model_provider).toBe("nvidia");
    expect(useSettingsStore.getState().settings.nvidia_model).toBe("nvidia/nemotron-3-ultra");
  });

  it("hydrates the persisted concrete model for the active provider", async () => {
    await useSettingsStore.getState().updateSettings({
      model_provider: "nvidia",
      nvidia_model: "nvidia/nemotron-3-ultra",
    });

    expect(useModelStore.getState().activeProvider).toBe("nvidia");
    expect(useModelStore.getState().activeModel).toBe("nvidia/nemotron-3-ultra");
    expect(useModelStore.getState().consumeSelectionForRequest()).toEqual({
      provider: "nvidia",
      model: "nvidia/nemotron-3-ultra",
    });
  });

  it("clears pending one-shot override when user pins a session provider", () => {
    useModelStore.setState({
      activeModel: null,
      providers: [
        {
          id: "zhipu",
          displayName: "Zhipu GLM",
          available: true,
          isPrimary: false,
          isFallback: true,
          state: "selectable",
          reasonCode: null,
          reasonLabel: null,
          selectedModel: "glm-5",
          modelOptions: [],
          strictPin: false,
          verifiedAt: null,
        },
      ],
    });
    useModelStore.getState().setNextTurnProvider("zhipu");

    useModelStore.getState().setActiveProvider("zhipu");

    expect(useModelStore.getState().activeProvider).toBe("zhipu");
    expect(useModelStore.getState().nextTurnProvider).toBeNull();
  });
});
