import { useEffect, useMemo } from "react";
import { ArrowRightLeft, RotateCcw } from "lucide-react";
import type { Message } from "@/api/types";
import { useToastStore } from "@/stores/toast-store";
import { useModelStore, type RequestModelProvider } from "@/stores/model-store";
import { resolveModelSwitchPrompt } from "@/lib/model-switch-prompt";

interface ModelSwitchPromptCardProps {
  metadata?: Message["metadata"];
  onRetryOnce?: () => void;
}

function buttonClass(kind: "retry" | "session", disabled = false): string {
  const base =
    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors";
  if (disabled) {
    return `${base} cursor-not-allowed border-border text-text-tertiary opacity-60`;
  }
  if (kind === "retry") {
    return `${base} border-[var(--accent)]/30 bg-[var(--accent-light)] text-[var(--accent)] hover:border-[var(--accent)]/40 hover:bg-[var(--accent-light)]/80`;
  }
  return `${base} border-border text-text-secondary hover:bg-surface-secondary hover:text-text`;
}

export function ModelSwitchPromptCard({
  metadata,
  onRetryOnce,
}: ModelSwitchPromptCardProps) {
  const {
    providers,
    activeProvider,
    setActiveProvider,
    setNextTurnProvider,
    refreshIfStale,
  } = useModelStore();
  const { addToast } = useToastStore();
  const prompt = useMemo(
    () =>
      resolveModelSwitchPrompt(
        metadata as Record<string, unknown> | undefined,
        providers,
      ),
    [metadata, providers],
  );

  useEffect(() => {
    if (prompt) {
      void refreshIfStale(0);
    }
  }, [prompt, refreshIfStale]);

  if (!prompt || prompt.options.length === 0) {
    return null;
  }

  const handleRetryOnce = (provider: RequestModelProvider, label: string) => {
    setNextTurnProvider(provider);
    addToast("info", `Wiii sẽ thử lại lượt này bằng ${label}.`, 3500);
    onRetryOnce?.();
  };

  const handleSessionSwitch = (
    provider: RequestModelProvider,
    label: string,
  ) => {
    setActiveProvider(provider);
    addToast("success", `Wiii sẽ ưu tiên ${label} cho các lượt sau.`, 3500);
  };

  return (
    <div className="mt-3 rounded-2xl border border-border bg-surface-secondary/65 px-3.5 py-3">
      <div className="text-sm font-medium text-text">{prompt.title}</div>
      <p className="mt-1 text-xs leading-6 text-text-secondary">
        {prompt.message}
      </p>

      {prompt.allow_retry_once && onRetryOnce ? (
        <div className="mt-3">
          <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-text-tertiary">
            Thử cho lượt này
          </div>
          <div className="flex flex-wrap gap-2">
            {prompt.options.map((option) => (
              <button
                key={`retry-${option.provider}`}
                type="button"
                onClick={() => handleRetryOnce(option.provider, option.label)}
                className={buttonClass("retry")}
                aria-label={`Thử lượt này bằng ${option.label}`}
              >
                <RotateCcw size={13} />
                <span>{option.label}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {prompt.allow_session_switch ? (
        <div className="mt-3">
          <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-text-tertiary">
            Giữ cho cả phiên
          </div>
          <div className="flex flex-wrap gap-2">
            {prompt.options.map((option) => {
              const isActive = activeProvider === option.provider;
              return (
                <button
                  key={`session-${option.provider}`}
                  type="button"
                  disabled={isActive}
                  onClick={() =>
                    handleSessionSwitch(option.provider, option.label)
                  }
                  className={buttonClass("session", isActive)}
                  aria-label={
                    isActive
                      ? `${option.label} đang được dùng`
                      : `Dùng ${option.label} cho cả phiên`
                  }
                >
                  <ArrowRightLeft size={13} />
                  <span>
                    {isActive ? `${option.label} đang được dùng` : option.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
