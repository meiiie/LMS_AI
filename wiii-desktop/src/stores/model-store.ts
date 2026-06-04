/**
 * Provider/runtime selector store for per-request chat routing.
 */
import { create } from "zustand";
import type {
  AppSettings,
  LlmStatusProvider,
  LlmStatusResponse,
  ModelCatalogEntry,
  ProviderDisabledReasonCode,
  ProviderSelectabilityState,
} from "@/api/types";
import { getClient } from "@/api/client";
import { useSettingsStore } from "@/stores/settings-store";

export type RequestModelProvider = NonNullable<AppSettings["model_provider"]>;
export interface RequestModelSelection {
  provider: RequestModelProvider;
  model: string | null;
}

export interface ProviderInfo {
  id: string;
  displayName: string;
  available: boolean;
  isPrimary: boolean;
  isFallback: boolean;
  state: ProviderSelectabilityState;
  reasonCode?: ProviderDisabledReasonCode | null;
  reasonLabel?: string | null;
  selectedModel?: string | null;
  modelOptions: ModelCatalogEntry[];
  strictPin: boolean;
  verifiedAt?: string | null;
}

interface ModelState {
  activeProvider: RequestModelProvider;
  activeModel: string | null;
  nextTurnProvider: RequestModelProvider | null;
  providers: ProviderInfo[];
  isLoading: boolean;
  lastFetchedAt: number | null;

  setActiveProvider: (id: RequestModelProvider) => void;
  setActiveModel: (provider: RequestModelProvider, model: string) => void;
  applyConversationSelection: (selection: RequestModelSelection | null) => void;
  setNextTurnProvider: (id: RequestModelProvider | null) => void;
  consumeProviderForRequest: () => RequestModelProvider;
  consumeSelectionForRequest: () => RequestModelSelection;
  fetchProviders: (options?: { force?: boolean; includeModels?: boolean }) => Promise<void>;
  refreshIfStale: (
    maxAgeMs?: number,
    options?: { includeModels?: boolean },
  ) => Promise<void>;
}

function normalizeModelProvider(
  value?: AppSettings["model_provider"] | null,
): RequestModelProvider {
  return value || "auto";
}

function mapProvider(
  provider: LlmStatusProvider,
  previous?: ProviderInfo,
): ProviderInfo {
  return {
    id: provider.id,
    displayName: provider.display_name,
    available: provider.available,
    isPrimary: provider.is_primary,
    isFallback: provider.is_fallback,
    state: provider.state,
    reasonCode: provider.reason_code ?? null,
    reasonLabel: provider.reason_label ?? null,
    selectedModel: provider.selected_model ?? null,
    modelOptions: provider.model_options ?? previous?.modelOptions ?? [],
    strictPin: provider.strict_pin,
    verifiedAt: provider.verified_at ?? null,
  };
}

function resolveConfiguredModelForProvider(
  provider: RequestModelProvider,
  settings: AppSettings,
): string | null {
  switch (provider) {
    case "google":
      return settings.google_model?.trim() || null;
    case "zhipu":
      return settings.zhipu_model?.trim() || null;
    case "openai":
      return settings.openai_model?.trim() || null;
    case "openrouter":
      return settings.openrouter_model?.trim() || null;
    case "nvidia":
      return settings.nvidia_model?.trim() || null;
    case "ollama":
      return settings.ollama_model?.trim() || null;
    default:
      return null;
  }
}

function modelSettingPatchForProvider(
  provider: RequestModelProvider,
  model: string,
): Partial<AppSettings> {
  switch (provider) {
    case "google":
      return { google_model: model };
    case "zhipu":
      return { zhipu_model: model };
    case "openai":
      return { openai_model: model };
    case "openrouter":
      return { openrouter_model: model };
    case "nvidia":
      return { nvidia_model: model };
    case "ollama":
      return { ollama_model: model };
    default:
      return {};
  }
}

export function resolveSelectedModelForProvider(
  provider: RequestModelProvider,
  providers: ProviderInfo[],
  settings: AppSettings,
): string | null {
  if (provider === "auto") {
    return null;
  }
  const providerInfo = providers.find((item) => item.id === provider);
  const runtimeSelectedModel = providerInfo?.selectedModel?.trim();
  if (runtimeSelectedModel) {
    return runtimeSelectedModel;
  }
  return resolveConfiguredModelForProvider(provider, settings);
}

export const useModelStore = create<ModelState>((set, get) => ({
  activeProvider: normalizeModelProvider(
    useSettingsStore.getState().settings.model_provider,
  ),
  activeModel: resolveConfiguredModelForProvider(
    normalizeModelProvider(useSettingsStore.getState().settings.model_provider),
    useSettingsStore.getState().settings,
  ),
  nextTurnProvider: null,
  providers: [],
  isLoading: false,
  lastFetchedAt: null,

  setActiveProvider: (id) => {
    const provider = get().providers.find((item) => item.id === id);
    if (id !== "auto" && provider && provider.state !== "selectable") {
      return;
    }
    set({ activeProvider: id, activeModel: null, nextTurnProvider: null });
    void useSettingsStore.getState().updateSettings({ model_provider: id });
  },

  setActiveModel: (id, model) => {
    const normalizedModel = model.trim();
    const provider = get().providers.find((item) => item.id === id);
    if (id === "auto" || !normalizedModel) {
      get().setActiveProvider(id);
      return;
    }
    if (provider && provider.state !== "selectable") {
      return;
    }
    set({
      activeProvider: id,
      activeModel: normalizedModel,
      nextTurnProvider: null,
    });
    void useSettingsStore.getState().updateSettings({
      model_provider: id,
      ...modelSettingPatchForProvider(id, normalizedModel),
    });
  },

  applyConversationSelection: (selection) => {
    if (selection?.provider) {
      set({
        activeProvider: selection.provider,
        activeModel:
          selection.provider === "auto"
            ? null
            : selection.model?.trim() || null,
        nextTurnProvider: null,
      });
      return;
    }

    const settings = useSettingsStore.getState().settings;
    const provider = normalizeModelProvider(settings.model_provider);
    set({
      activeProvider: provider,
      activeModel: resolveConfiguredModelForProvider(provider, settings),
      nextTurnProvider: null,
    });
  },

  setNextTurnProvider: (id) => {
    set({ nextTurnProvider: id });
  },

  consumeProviderForRequest: () => {
    const nextTurnProvider = get().nextTurnProvider;
    if (nextTurnProvider) {
      set({ nextTurnProvider: null });
      return nextTurnProvider;
    }
    return get().activeProvider;
  },

  consumeSelectionForRequest: () => {
    const nextTurnProvider = get().nextTurnProvider;
    const provider = nextTurnProvider || get().activeProvider;
    if (nextTurnProvider) {
      set({ nextTurnProvider: null });
    }
    return {
      provider,
      model:
        provider === get().activeProvider && get().activeModel
          ? get().activeModel
          : resolveSelectedModelForProvider(
              provider,
              get().providers,
              useSettingsStore.getState().settings,
            ),
    };
  },

  fetchProviders: async ({ force = false, includeModels = false } = {}) => {
    if (!force && get().isLoading) return;
    set({ isLoading: true });
    try {
      const client = getClient();
      const data = await client.get<LlmStatusResponse>(
        `/api/v1/llm/status${includeModels ? "?include_models=true" : ""}`,
      );
      const previousProvidersById = new Map(
        get().providers.map((provider) => [provider.id, provider]),
      );
      const providers = (data.providers || []).map((provider) =>
        mapProvider(provider, previousProvidersById.get(provider.id)),
      );
      const activeProvider = get().activeProvider;
      const activeModel = get().activeModel;
      const nextTurnProvider = get().nextTurnProvider;
      const activeSelection = providers.find((item) => item.id === activeProvider);
      const nextTurnSelection = nextTurnProvider
        ? providers.find((item) => item.id === nextTurnProvider)
        : undefined;
      const hasProviderCatalog = providers.length > 0;
      const shouldResetToAuto =
        hasProviderCatalog
        &&
        activeProvider !== "auto"
        && !activeModel
        && (!activeSelection || activeSelection.state !== "selectable");
      const shouldClearNextTurn =
        hasProviderCatalog
        &&
        Boolean(nextTurnProvider)
        && nextTurnProvider !== "auto"
        && (!nextTurnSelection || nextTurnSelection.state !== "selectable");

      set({
        providers,
        isLoading: false,
        lastFetchedAt: Date.now(),
        activeProvider: shouldResetToAuto ? "auto" : activeProvider,
        activeModel: shouldResetToAuto ? null : activeModel,
        nextTurnProvider: shouldClearNextTurn ? null : nextTurnProvider,
      });

      if (shouldResetToAuto) {
        void useSettingsStore.getState().updateSettings({ model_provider: "auto" });
      }
    } catch (err) {
      console.warn("[Model] Failed to fetch providers:", err);
      set({ isLoading: false });
    }
  },

  refreshIfStale: async (maxAgeMs = 30_000, options = {}) => {
    const lastFetchedAt = get().lastFetchedAt;
    if (!lastFetchedAt || Date.now() - lastFetchedAt > maxAgeMs) {
      await get().fetchProviders({
        force: true,
        includeModels: options.includeModels ?? false,
      });
    }
  },
}));

useSettingsStore.subscribe((state) => {
  const nextProvider = normalizeModelProvider(state.settings.model_provider);
  if (useModelStore.getState().activeProvider !== nextProvider) {
    useModelStore.setState({
      activeProvider: nextProvider,
      activeModel: resolveConfiguredModelForProvider(nextProvider, state.settings),
    });
  }
});
