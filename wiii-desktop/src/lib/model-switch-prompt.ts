import type {
  FailoverMetadata,
  ModelSwitchPrompt,
  ModelSwitchPromptOption,
} from "@/api/types";
import type { ProviderInfo, RequestModelProvider } from "@/stores/model-store";

const PROVIDER_LABELS: Record<string, string> = {
  google: "Gemini",
  zhipu: "Zhipu GLM",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  nvidia: "NVIDIA NIM",
  ollama: "Ollama",
};

const REASON_LABELS: Record<string, string> = {
  busy: "dang cham gioi han",
  rate_limit: "dang cham gioi han",
  auth_error: "dang gap loi xac thuc",
  provider_unavailable: "tam thoi khong kha dung",
  host_down: "tam thoi chua san sang",
  server_error: "dang gap loi may chu",
  timeout: "phan hoi qua lau",
  verifying: "dang duoc xac minh",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function isProvider(value: unknown): value is RequestModelProvider {
  return (
    value === "auto"
    || value === "google"
    || value === "zhipu"
    || value === "openai"
    || value === "openrouter"
    || value === "ollama"
  );
}

function providerLabel(
  provider: string | null | undefined,
  providers: ProviderInfo[],
): string {
  if (!provider) return "Model hien tai";
  const providerInfo = providers.find((item) => item.id === provider);
  return providerInfo?.displayName || PROVIDER_LABELS[provider] || provider;
}

function normalizeOption(
  raw: unknown,
  providers: ProviderInfo[],
): ModelSwitchPromptOption | null {
  const record = asRecord(raw);
  const provider = record?.provider;
  if (!isProvider(provider) || provider === "auto") {
    return null;
  }
  const providerInfo = providers.find((item) => item.id === provider);
  const label =
    typeof record?.label === "string" && record.label.trim()
      ? record.label.trim()
      : providerInfo?.displayName || PROVIDER_LABELS[provider] || provider;
  const selectedModel =
    typeof record?.selected_model === "string" && record.selected_model.trim()
      ? record.selected_model.trim()
      : providerInfo?.selectedModel || null;
  return {
    provider,
    label,
    selected_model: selectedModel,
  };
}

function dedupeOptions(
  options: ModelSwitchPromptOption[],
): ModelSwitchPromptOption[] {
  const seen = new Set<string>();
  const unique: ModelSwitchPromptOption[] = [];
  for (const option of options) {
    if (seen.has(option.provider)) continue;
    seen.add(option.provider);
    unique.push(option);
  }
  return unique;
}

export function resolveModelSwitchPrompt(
  metadata: Record<string, unknown> | undefined,
  providers: ProviderInfo[],
): ModelSwitchPrompt | null {
  const prompt = normalizeModelSwitchPrompt(metadata?.model_switch_prompt, providers);
  if (prompt) return prompt;
  return deriveModelSwitchPromptFromFailover(metadata?.failover, providers);
}

export function normalizeModelSwitchPrompt(
  raw: unknown,
  providers: ProviderInfo[],
): ModelSwitchPrompt | null {
  const record = asRecord(raw);
  if (!record) return null;

  const title =
    typeof record.title === "string" && record.title.trim()
      ? record.title.trim()
      : "";
  const message =
    typeof record.message === "string" && record.message.trim()
      ? record.message.trim()
      : "";
  if (!title || !message) return null;

  const explicitOptions = Array.isArray(record.options)
    ? dedupeOptions(
      record.options
        .map((option) => normalizeOption(option, providers))
        .filter((option): option is ModelSwitchPromptOption => Boolean(option)),
    )
    : [];

  const recommendedProvider = isProvider(record.recommended_provider) && record.recommended_provider !== "auto"
    ? record.recommended_provider
    : explicitOptions[0]?.provider;

  const options = explicitOptions.length > 0
    ? explicitOptions
    : recommendedProvider
      ? [
        {
          provider: recommendedProvider,
          label: providerLabel(recommendedProvider, providers),
          selected_model:
            providers.find((item) => item.id === recommendedProvider)?.selectedModel || null,
        },
      ]
      : [];

  if (options.length === 0) return null;

  return {
    trigger: typeof record.trigger === "string" ? record.trigger : "provider_unavailable",
    reason_code: typeof record.reason_code === "string" ? record.reason_code : null,
    current_provider:
      typeof record.current_provider === "string" ? record.current_provider : null,
    title,
    message,
    recommended_provider: recommendedProvider || null,
    options,
    allow_retry_once: Boolean(record.allow_retry_once),
    allow_session_switch: record.allow_session_switch !== false,
  };
}

export function deriveModelSwitchPromptFromFailover(
  rawFailover: unknown,
  providers: ProviderInfo[],
): ModelSwitchPrompt | null {
  const failover = rawFailover as FailoverMetadata | null | undefined;
  if (!failover?.switched) return null;
  const initialProvider = failover.initial_provider?.trim() || null;
  const finalProvider = failover.final_provider?.trim() || null;
  if (
    !initialProvider
    || !finalProvider
    || !isProvider(finalProvider)
    || finalProvider === "auto"
    || initialProvider === finalProvider
  ) {
    return null;
  }

  const finalOption: ModelSwitchPromptOption = {
    provider: finalProvider,
    label: providerLabel(finalProvider, providers),
    selected_model:
      providers.find((item) => item.id === finalProvider)?.selectedModel || null,
  };
  const extraOptions = providers
    .filter(
      (item) =>
        item.state === "selectable"
        && item.id !== initialProvider
        && item.id !== finalProvider
        && item.id !== "auto",
    )
    .slice(0, 2)
    .map<ModelSwitchPromptOption>((item) => ({
      provider: item.id as ModelSwitchPromptOption["provider"],
      label: item.displayName,
      selected_model: item.selectedModel || null,
    }));

  const reasonCode = failover.last_reason_category || failover.last_reason_code || null;
  const reasonLabel = reasonCode ? REASON_LABELS[reasonCode] || "dang gap van de" : "dang gap van de";
  const initialLabel = providerLabel(initialProvider, providers);
  const finalLabel = providerLabel(finalProvider, providers);

  return {
    trigger: "hard_failover",
    reason_code: reasonCode,
    current_provider: initialProvider,
    title: "Giu model moi cho cac luot sau?",
    message: `Wiii da chuyen tu ${initialLabel} sang ${finalLabel} vi ${initialLabel} ${reasonLabel}. Neu ban muon, minh co the giu ${finalLabel} cho cac luot sau.`,
    recommended_provider: finalProvider,
    options: dedupeOptions([finalOption, ...extraOptions]),
    allow_retry_once: false,
    allow_session_switch: true,
  };
}
