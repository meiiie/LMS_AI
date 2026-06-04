/**
 * Provider selector for per-request chat routing.
 */
import { Fragment, useState, useRef, useEffect, useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertCircle, ChevronUp, Cpu, Sparkles, Check, RefreshCw, Search } from "lucide-react";
import {
  useModelStore,
  type ProviderInfo,
  type RequestModelProvider,
} from "@/stores/model-store";
import { useChatStore } from "@/stores/chat-store";
import type { ModelCatalogEntry } from "@/api/types";

const PROVIDER_ICONS: Record<string, typeof Cpu> = {
  auto: Sparkles,
  google: Cpu,
  zhipu: Cpu,
  openai: Cpu,
  openrouter: Cpu,
  nvidia: Cpu,
  ollama: Cpu,
};

const PROVIDER_LABELS: Record<string, string> = {
  auto: "Tự động",
  google: "Gemini",
  zhipu: "Zhipu GLM",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  nvidia: "NVIDIA NIM",
  ollama: "Ollama",
};

interface ModelSelectorProps {
  compact?: boolean;
}

export function ModelSelector({ compact: _compact }: ModelSelectorProps = {}) {
  const {
    activeProvider,
    activeModel,
    setActiveProvider,
    setActiveModel,
    applyConversationSelection,
    providers,
    fetchProviders,
    refreshIfStale,
  } = useModelStore();
  const activeConversation = useChatStore((state) => state.activeConversation());
  const setConversationModel = useChatStore((state) => state.setConversationModel);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!fetchedRef.current) {
      fetchedRef.current = true;
      void fetchProviders({ force: true, includeModels: true });
    }
  }, [fetchProviders]);

  useEffect(() => {
    if (activeConversation?.model_provider) {
      applyConversationSelection({
        provider: activeConversation.model_provider,
        model: activeConversation.model ?? null,
      });
      return;
    }
    applyConversationSelection(null);
  }, [
    activeConversation?.id,
    activeConversation?.model_provider,
    activeConversation?.model,
    applyConversationSelection,
  ]);

  useEffect(() => {
    if (open) {
      void fetchProviders({ force: true, includeModels: true });
    }
  }, [open, fetchProviders]);

  useEffect(() => {
    const refreshVisibleProviders = () => {
      if (document.visibilityState === "visible") {
        void refreshIfStale(10_000, { includeModels: true });
      }
    };
    window.addEventListener("focus", refreshVisibleProviders);
    document.addEventListener("visibilitychange", refreshVisibleProviders);
    return () => {
      window.removeEventListener("focus", refreshVisibleProviders);
      document.removeEventListener("visibilitychange", refreshVisibleProviders);
    };
  }, [refreshIfStale]);

  const handleClickOutside = useCallback(
    (e: MouseEvent) => {
      if (
        open
        && containerRef.current
        && !containerRef.current.contains(e.target as Node)
      ) {
        setSearchQuery("");
        setOpen(false);
      }
    },
    [open],
  );

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [handleClickOutside]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  const visibleProviders = useMemo(() => {
    const visible = providers.filter((provider) => provider.state !== "hidden");
    if (
      activeProvider === "auto"
      || visible.some((provider) => provider.id === activeProvider)
    ) {
      return visible;
    }

    const fallbackProvider: ProviderInfo = {
      id: activeProvider,
      displayName: PROVIDER_LABELS[activeProvider] || activeProvider,
      available: true,
      isPrimary: false,
      isFallback: false,
      state: "selectable",
      reasonCode: null,
      reasonLabel: "Đang dùng từ phiên chat. Bấm làm mới để tải danh sách model.",
      selectedModel: activeModel,
      modelOptions: activeModel
        ? [
            {
              provider: activeProvider,
              model_name: activeModel,
              display_name: activeModel,
              status: "selected",
              released_on: null,
              is_default: false,
            },
          ]
        : [],
      strictPin: false,
      verifiedAt: null,
    };
    return [fallbackProvider, ...visible];
  }, [activeModel, activeProvider, providers]);
  const catalogUnavailable = providers.length === 0;

  const activeProviderInfo = visibleProviders.find((provider) => provider.id === activeProvider);
  const ActiveIcon = PROVIDER_ICONS[activeProvider] || Sparkles;
  const activeLabel =
    activeProviderInfo?.displayName || PROVIDER_LABELS[activeProvider] || activeProvider;
  const activeModelLabel = activeModel || activeProviderInfo?.selectedModel || null;

  const options: Array<{
    kind: "auto" | "provider" | "model";
    id: RequestModelProvider;
    label: string;
    Icon: typeof Cpu;
    disabled?: boolean;
    groupOnly?: boolean;
    reasonLabel?: string | null;
    selectedModel?: string | null;
    isProviderDefaultModel?: boolean;
    model?: ModelCatalogEntry;
  }> = [
    { kind: "auto", id: "auto", label: PROVIDER_LABELS.auto, Icon: PROVIDER_ICONS.auto },
    ...visibleProviders.flatMap((provider) => {
      const providerId = provider.id as RequestModelProvider;
      const disabled = provider.state !== "selectable";
      const providerLabel = provider.displayName || PROVIDER_LABELS[provider.id] || provider.id;
      const modelOptions = provider.modelOptions || [];
      const hasModelOptions = modelOptions.length > 0;
      return [
        {
          kind: "provider" as const,
          id: providerId,
          label: providerLabel,
          Icon: PROVIDER_ICONS[provider.id] || Cpu,
          disabled,
          groupOnly: hasModelOptions,
          reasonLabel: provider.reasonLabel,
          selectedModel: provider.selectedModel,
        },
        ...modelOptions.map((model) => ({
          kind: "model" as const,
          id: providerId,
          label: model.display_name || model.model_name,
          Icon: PROVIDER_ICONS[provider.id] || Cpu,
          disabled,
          reasonLabel: provider.reasonLabel,
          selectedModel: model.model_name,
          isProviderDefaultModel: provider.selectedModel === model.model_name,
          model,
        })),
      ];
    }),
  ];
  const normalizedSearch = searchQuery.trim().toLowerCase();
  const filteredOptions = normalizedSearch
    ? options.filter(({ id, label, selectedModel, model }) =>
        [
          id,
          label,
          selectedModel,
          model?.model_name,
          model?.display_name,
          model?.provider,
          model?.status,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalizedSearch)),
      )
    : options;
  const firstProviderIndex = filteredOptions.findIndex((option) => option.kind === "provider");
  const firstModelIndex = filteredOptions.findIndex((option) => option.kind === "model");

  const handleSelect = (
    id: RequestModelProvider,
    disabled?: boolean,
    model?: ModelCatalogEntry,
    groupOnly?: boolean,
  ) => {
    if (disabled || groupOnly) return;
    if (model) {
      setActiveModel(id, model.model_name);
      if (activeConversation?.id) {
        setConversationModel(activeConversation.id, id, model.model_name);
      }
    } else {
      setActiveProvider(id);
      if (activeConversation?.id) {
        setConversationModel(activeConversation.id, id, null);
      }
    }
    setSearchQuery("");
    setOpen(false);
  };

  const handleRefreshModels = () => {
    void fetchProviders({ force: true, includeModels: true });
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => {
          setSearchQuery("");
          setOpen((value) => !value);
        }}
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-text-secondary transition-colors hover:bg-surface-tertiary hover:text-text"
        aria-label="Chọn model AI"
        aria-expanded={open}
        data-testid="model-selector-trigger"
        data-wiii-id="model-selector"
        data-wiii-synonyms="chọn model,đổi model,chọn model ai,model ai,ai model,đổi llm,provider ai"
      >
        <ActiveIcon size={13} />
        <span className="max-w-[180px] truncate">{activeModelLabel || activeLabel}</span>
        <motion.span
          animate={{ rotate: open ? 0 : 180 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          className="inline-flex"
        >
          <ChevronUp size={12} />
        </motion.span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 4 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute bottom-full left-0 mb-1 max-h-[420px] min-w-[300px] overflow-y-auto rounded-xl border border-border bg-surface shadow-lg"
            style={{ zIndex: 50 }}
            role="listbox"
            aria-label="Danh sach provider"
            data-testid="model-selector-dropdown"
          >
            <div className="sticky top-0 z-10 border-b border-border bg-surface p-2">
              <div className="flex items-center gap-2">
                <div className="relative min-w-0 flex-1">
                  <Search
                    size={14}
                    className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary"
                  />
                  <input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder="Tìm model..."
                    className="h-8 w-full rounded-lg border border-border bg-surface-secondary pl-8 pr-2 text-xs text-text outline-none transition-colors placeholder:text-text-tertiary focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleRefreshModels}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border text-text-tertiary transition-colors hover:bg-surface-secondary hover:text-text"
                  title="Làm mới danh sách model"
                  aria-label="Làm mới danh sách model"
                >
                  <RefreshCw size={14} />
                </button>
              </div>
              {activeModelLabel ? (
                <div className="mt-2 truncate text-[11px] text-text-tertiary">
                  Đang dùng <span className="text-text-secondary">{activeModelLabel}</span>
                </div>
              ) : null}
            </div>
            {catalogUnavailable ? (
              <div className="border-b border-border px-3 py-2 text-[11px] text-text-tertiary">
                Chưa tải được danh sách model. Nút chọn vẫn giữ model hiện tại của phiên chat.
              </div>
            ) : null}
            <div className="py-1">
              {filteredOptions.length === 0 ? (
                <div className="px-3 py-5 text-center text-xs text-text-tertiary">
                  Không tìm thấy model phù hợp.
                </div>
              ) : null}
              {filteredOptions.map(({ kind, id, label, Icon, disabled, groupOnly, reasonLabel, selectedModel, isProviderDefaultModel, model }, index) => {
                const isModel = kind === "model";
                const isActive =
                  kind === "auto"
                    ? activeProvider === "auto"
                    : isModel
                      ? id === activeProvider
                        && (
                          activeModel === model?.model_name
                          || (!activeModel && Boolean(isProviderDefaultModel))
                        )
                      : id === activeProvider && !activeModel && !groupOnly;
                const optionKey = isModel ? `${id}:${model?.model_name}` : id;
                const showSelectedModel =
                  Boolean(selectedModel)
                  && id !== "auto"
                  && (!isModel || selectedModel !== label);
                const detailText = isModel
                  ? `${PROVIDER_LABELS[id] || id}${model?.status ? ` · ${model.status}` : ""}`
                  : showSelectedModel
                    ? `Mặc định: ${selectedModel}`
                    : null;
                const sectionLabel =
                  index === firstProviderIndex
                    ? "Nguồn chạy"
                    : index === firstModelIndex
                      ? "Models"
                      : null;
                return (
                  <Fragment key={optionKey}>
                    {sectionLabel ? (
                      <div className="px-3 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wide text-text-tertiary">
                        {sectionLabel}
                      </div>
                    ) : null}
                    <button
                      onClick={() => handleSelect(id, disabled, model, groupOnly)}
                      disabled={disabled || groupOnly}
                      role="option"
                      aria-selected={isActive}
                      aria-disabled={disabled || groupOnly}
                      title={
                        disabled
                          ? reasonLabel ?? undefined
                          : groupOnly
                            ? "Chọn một model cụ thể bên dưới"
                            : undefined
                      }
                      className={`flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors ${
                        isActive
                          ? "bg-[var(--accent-light)] text-[var(--accent)]"
                          : disabled
                            ? "cursor-not-allowed text-text-tertiary opacity-70"
                            : groupOnly
                              ? "cursor-default text-text-secondary"
                              : "text-text hover:bg-surface-secondary"
                      } ${isModel ? "pl-8 text-xs" : "text-sm"}`}
                    >
                      <Icon size={15} className="mt-0.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate">{label}</span>
                          {disabled && !groupOnly && id !== "auto" ? (
                            <AlertCircle size={13} className="text-amber-500" />
                          ) : null}
                        </div>
                        {detailText ? (
                          <div className="truncate text-[11px] text-text-tertiary">
                            {detailText}
                          </div>
                        ) : null}
                        {disabled && reasonLabel ? (
                          <div className="mt-0.5 text-[11px] text-text-tertiary">
                            {reasonLabel}
                          </div>
                        ) : null}
                      </div>
                      {id !== "auto" && !isModel && !isActive ? (
                        <span
                          className={`mt-1 h-2 w-2 rounded-full ${
                            disabled ? "bg-gray-400" : "bg-green-500"
                          }`}
                          title={disabled ? "Disabled" : "Ready"}
                        />
                      ) : isActive ? (
                        <Check size={14} className="ml-auto text-[var(--accent)]" aria-label="Selected" />
                      ) : null}
                    </button>
                  </Fragment>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
