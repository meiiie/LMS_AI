/**
 * Provider selector for per-request chat routing.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertCircle, ChevronUp, Cpu, Sparkles, Check } from "lucide-react";
import { useModelStore, type RequestModelProvider } from "@/stores/model-store";

const PROVIDER_ICONS: Record<string, typeof Cpu> = {
  auto: Sparkles,
  google: Cpu,
  zhipu: Cpu,
  openai: Cpu,
  openrouter: Cpu,
  ollama: Cpu,
};

const PROVIDER_LABELS: Record<string, string> = {
  auto: "Tự động",
  google: "Gemini",
  zhipu: "Zhipu GLM",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

interface ModelSelectorProps {
  compact?: boolean;
}

export function ModelSelector({ compact: _compact }: ModelSelectorProps = {}) {
  const {
    activeProvider,
    setActiveProvider,
    providers,
    fetchProviders,
    refreshIfStale,
  } = useModelStore();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!fetchedRef.current) {
      fetchedRef.current = true;
      void fetchProviders();
    }
  }, [fetchProviders]);

  useEffect(() => {
    if (open) {
      void fetchProviders({ force: true });
    }
  }, [open, fetchProviders]);

  useEffect(() => {
    const refreshVisibleProviders = () => {
      if (document.visibilityState === "visible") {
        void refreshIfStale(10_000);
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

  const visibleProviders = useMemo(
    () => providers.filter((provider) => provider.state !== "hidden"),
    [providers],
  );

  if (visibleProviders.length === 0) return null;

  const activeProviderInfo = visibleProviders.find((provider) => provider.id === activeProvider);
  const ActiveIcon = PROVIDER_ICONS[activeProvider] || Sparkles;
  const activeLabel =
    activeProviderInfo?.displayName || PROVIDER_LABELS[activeProvider] || activeProvider;

  const options: Array<{
    id: RequestModelProvider;
    label: string;
    Icon: typeof Cpu;
    disabled?: boolean;
    reasonLabel?: string | null;
    selectedModel?: string | null;
  }> = [
    { id: "auto", label: PROVIDER_LABELS.auto, Icon: PROVIDER_ICONS.auto },
    ...visibleProviders.map((provider) => ({
      id: provider.id as RequestModelProvider,
      label: provider.displayName || PROVIDER_LABELS[provider.id] || provider.id,
      Icon: PROVIDER_ICONS[provider.id] || Cpu,
      disabled: provider.state !== "selectable",
      reasonLabel: provider.reasonLabel,
      selectedModel: provider.selectedModel,
    })),
  ];

  const handleSelect = (id: RequestModelProvider, disabled?: boolean) => {
    if (disabled) return;
    setActiveProvider(id);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-text-secondary transition-colors hover:bg-surface-tertiary hover:text-text"
        aria-label="Chọn model AI"
        aria-expanded={open}
        data-testid="model-selector-trigger"
        data-wiii-id="model-selector"
        data-wiii-synonyms="chọn model,đổi model,chọn model ai,model ai,ai model,đổi llm,provider ai"
      >
        <ActiveIcon size={13} />
        <span>{activeLabel}</span>
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
            className="absolute bottom-full left-0 mb-1 min-w-[240px] rounded-xl border border-border bg-surface shadow-lg"
            style={{ zIndex: 50 }}
            role="listbox"
            aria-label="Danh sach provider"
            data-testid="model-selector-dropdown"
          >
            <div className="py-1">
              {options.map(({ id, label, Icon, disabled, reasonLabel, selectedModel }) => {
                const isActive = id === activeProvider;
                return (
                  <button
                    key={id}
                    onClick={() => handleSelect(id, disabled)}
                    disabled={disabled}
                    role="option"
                    aria-selected={isActive}
                    aria-disabled={disabled}
                    title={disabled ? reasonLabel ?? undefined : undefined}
                    className={`flex w-full items-start gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
                      isActive
                        ? "bg-[var(--accent-light)] text-[var(--accent)]"
                        : disabled
                          ? "cursor-not-allowed text-text-tertiary opacity-70"
                          : "text-text hover:bg-surface-secondary"
                    }`}
                  >
                    <Icon size={15} className="mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span>{label}</span>
                        {disabled && id !== "auto" ? (
                          <AlertCircle size={13} className="text-amber-500" />
                        ) : null}
                      </div>
                      {selectedModel && id !== "auto" ? (
                        <div className="truncate text-[11px] text-text-tertiary">
                          {selectedModel}
                        </div>
                      ) : null}
                      {disabled && reasonLabel ? (
                        <div className="mt-0.5 text-[11px] text-text-tertiary">
                          {reasonLabel}
                        </div>
                      ) : null}
                    </div>
                    {id !== "auto" ? (
                      <span
                        className={`mt-1 h-2 w-2 rounded-full ${
                          disabled ? "bg-gray-400" : "bg-green-500"
                        }`}
                        title={disabled ? "Tạm khoá" : "Sẵn sàng"}
                      />
                    ) : isActive ? (
                      <Check size={14} className="ml-auto text-[var(--accent)]" aria-label="Đã chọn" />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
