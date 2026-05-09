import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Server,
  Sparkles,
} from "lucide-react";
import {
  getLlmRuntimeConfig,
  getModelCatalog,
  planEmbeddingSpaceMigration,
  promoteEmbeddingSpaceMigration,
  refreshLlmRuntimeAudit,
  refreshVisionRuntimeAudit,
  runEmbeddingSpaceMigration,
  updateLlmRuntimeConfig,
} from "@/api/admin";
import type {
  AgentRuntimeProfileConfig,
  EmbeddingSpaceMigrationPlanResponse,
  EmbeddingSpaceMigrationRunResponse,
  LlmRuntimeConfig,
  LlmTimeoutProfilesConfig,
  LlmTimeoutProviderOverride,
  ModelCatalogEntry,
  ModelCatalogResponse,
} from "@/api/types";
import {
  applyLlmProviderPreset,
  GOOGLE_DEFAULT_MODEL,
  OPENAI_DEFAULT_MODEL,
  OPENAI_DEFAULT_MODEL_ADVANCED,
  OLLAMA_DEFAULT_BASE_URL,
  OLLAMA_DEFAULT_KEEP_ALIVE,
  OLLAMA_DEFAULT_MODEL,
  OPENROUTER_BASE_URL,
  OPENROUTER_DEFAULT_MODEL,
  OPENROUTER_DEFAULT_MODEL_ADVANCED,
  type LlmProvider,
  ZHIPU_DEFAULT_BASE_URL,
  ZHIPU_DEFAULT_MODEL,
  ZHIPU_DEFAULT_MODEL_ADVANCED,
} from "@/lib/llm-presets";
import {
  clearOpenAiApiKey,
  clearGeminiApiKey,
  clearOllamaApiKey,
  clearOpenRouterApiKey,
  clearZhipuApiKey,
  loadOpenAiApiKey,
  loadGeminiApiKey,
  loadOllamaApiKey,
  loadOpenRouterApiKey,
  loadZhipuApiKey,
  storeOpenAiApiKey,
  storeGeminiApiKey,
  storeOllamaApiKey,
  storeOpenRouterApiKey,
  storeZhipuApiKey,
} from "@/lib/secure-token-storage";
import { useSettingsStore } from "@/stores/settings-store";

export type RuntimeEditorVariant = "admin" | "settings";
type ToastTone = "success" | "error";
type BoolChoice = "inherit" | "true" | "false";
type RuntimeProvider = NonNullable<LlmRuntimeConfig["provider"]>;
type VisionProvider = NonNullable<LlmRuntimeConfig["vision_provider"]>;
type EmbeddingProvider = NonNullable<LlmRuntimeConfig["embedding_provider"]>;
type EmbeddingMigrationPreviewItem = NonNullable<
  LlmRuntimeConfig["embedding_migration_previews"]
>[number];
type TimeoutProfileField = keyof Pick<
  LlmTimeoutProfilesConfig,
  | "light_seconds"
  | "moderate_seconds"
  | "deep_seconds"
  | "structured_seconds"
  | "background_seconds"
>;
type TimeoutProviderOverrideDraft = Partial<
  Record<TimeoutProfileField, string>
>;

type RuntimeDraft = {
  provider: RuntimeProvider;
  use_multi_agent: boolean;
  google_api_key: string;
  clear_google_api_key: boolean;
  google_model: string;
  openai_api_key: string;
  clear_openai_api_key: boolean;
  openai_base_url: string;
  openai_model: string;
  openai_model_advanced: string;
  openrouter_api_key: string;
  clear_openrouter_api_key: boolean;
  openrouter_base_url: string;
  openrouter_model: string;
  openrouter_model_advanced: string;
  zhipu_api_key: string;
  clear_zhipu_api_key: boolean;
  zhipu_base_url: string;
  zhipu_model: string;
  zhipu_model_advanced: string;
  openrouter_model_fallbacks: string;
  openrouter_provider_order: string;
  openrouter_allowed_providers: string;
  openrouter_ignored_providers: string;
  openrouter_allow_fallbacks: BoolChoice;
  openrouter_require_parameters: BoolChoice;
  openrouter_data_collection: "" | "allow" | "deny";
  openrouter_zdr: BoolChoice;
  openrouter_provider_sort: "" | "price" | "latency" | "throughput";
  ollama_api_key: string;
  clear_ollama_api_key: boolean;
  ollama_base_url: string;
  ollama_model: string;
  ollama_keep_alive: string;
  enable_llm_failover: boolean;
  llm_failover_chain: string;
  vision_provider: VisionProvider;
  vision_describe_provider: VisionProvider;
  vision_describe_model: string;
  vision_ocr_provider: VisionProvider;
  vision_ocr_model: string;
  vision_grounded_provider: VisionProvider;
  vision_grounded_model: string;
  vision_failover_chain: string;
  vision_timeout_seconds: string;
  embedding_provider: EmbeddingProvider;
  embedding_failover_chain: string;
  embedding_model: string;
  agent_profiles: Record<string, AgentRuntimeProfileConfig>;
  timeout_profiles: LlmTimeoutProfilesConfig;
  timeout_provider_overrides: Record<
    RuntimeProvider,
    TimeoutProviderOverrideDraft
  >;
};

interface Props {
  variant: RuntimeEditorVariant;
  onToast?: (message: string, tone: ToastTone) => void;
}

const PROVIDERS: RuntimeProvider[] = [
  "google",
  "zhipu",
  "openai",
  "openrouter",
  "ollama",
];
const VISION_PROVIDERS: VisionProvider[] = [
  "auto",
  "google",
  "openai",
  "openrouter",
  "ollama",
  "zhipu",
];
const EMBEDDING_PROVIDERS: EmbeddingProvider[] = [
  "auto",
  "google",
  "openai",
  "openrouter",
  "ollama",
  "zhipu",
];
const AGENT_PROFILE_GROUPS = [
  "routing",
  "safety",
  "knowledge",
  "utility",
  "evaluation",
  "creative",
] as const;
const AGENT_PROFILE_LABELS: Record<
  (typeof AGENT_PROFILE_GROUPS)[number],
  string
> = {
  routing: "Routing",
  safety: "Safety",
  knowledge: "Knowledge",
  utility: "Utility",
  evaluation: "Evaluation",
  creative: "Creative",
};
const AGENT_PROFILE_DESCRIPTIONS: Record<
  (typeof AGENT_PROFILE_GROUPS)[number],
  string
> = {
  routing: "Supervisor và luồng điều phối hướng xử lý.",
  safety: "Guardian và các luồng an toàn nội dung.",
  knowledge: "RAG, tutor, synthesizer và phần ứng dụng tri thức.",
  utility: "Direct response, memory và các luồng nhẹ.",
  evaluation: "Grader, planner, curation, aggregation, KG, sentiment.",
  creative: "Code Studio, course generation và các tác vụ sáng tạo/cơ cấu.",
};
const AGENT_PROFILE_PROVIDER_OPTIONS: RuntimeProvider[] = [
  "google",
  "zhipu",
  "openai",
  "openrouter",
  "ollama",
];
const TIMEOUT_OVERRIDE_PROVIDERS: RuntimeProvider[] = [
  "google",
  "zhipu",
  "openai",
  "openrouter",
  "ollama",
];
const TIMEOUT_PROFILE_FIELDS: Array<{
  key: TimeoutProfileField;
  label: string;
  hint: string;
}> = [
  {
    key: "light_seconds",
    label: "Light",
    hint: "Chat nhanh, first-response timeout.",
  },
  {
    key: "moderate_seconds",
    label: "Moderate",
    hint: "Chat thông thường và task cân bằng.",
  },
  {
    key: "deep_seconds",
    label: "Deep",
    hint: "Reasoning/code interactive nặng hơn.",
  },
  {
    key: "structured_seconds",
    label: "Structured",
    hint: "Structured output và planner/coordinator.",
  },
  {
    key: "background_seconds",
    label: "Background",
    hint: "Workflow dài hơi; 0 = không cắt sớm.",
  },
];

function defaultAgentProfiles(): Record<string, AgentRuntimeProfileConfig> {
  return {
    routing: { default_provider: "google", tier: "light", provider_models: {} },
    safety: { default_provider: "google", tier: "light", provider_models: {} },
    knowledge: {
      default_provider: "google",
      tier: "moderate",
      provider_models: {},
    },
    utility: { default_provider: "google", tier: "light", provider_models: {} },
    evaluation: {
      default_provider: "google",
      tier: "moderate",
      provider_models: {},
    },
    creative: {
      default_provider: "google",
      tier: "deep",
      provider_models: { google: "gemini-3.1-pro-preview" },
    },
  };
}

function defaultTimeoutProfiles(): LlmTimeoutProfilesConfig {
  return {
    light_seconds: 12,
    moderate_seconds: 25,
    deep_seconds: 45,
    structured_seconds: 60,
    background_seconds: 0,
    stream_keepalive_interval_seconds: 15,
    stream_idle_timeout_seconds: 0,
  };
}

function defaultTimeoutProviderOverrides(): Record<
  RuntimeProvider,
  TimeoutProviderOverrideDraft
> {
  return {
    google: {},
    zhipu: {},
    openai: {},
    openrouter: {},
    nvidia: {},
    ollama: {},
  };
}

const LEGACY_PAID_OPENAI_MODELS = new Set([
  "gpt-4o-mini",
  "gpt-4o",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
]);
const EMPTY_DRAFT: RuntimeDraft = {
  provider: "google",
  use_multi_agent: true,
  google_api_key: "",
  clear_google_api_key: false,
  google_model: GOOGLE_DEFAULT_MODEL,
  openai_api_key: "",
  clear_openai_api_key: false,
  openai_base_url: "",
  openai_model: OPENAI_DEFAULT_MODEL,
  openai_model_advanced: OPENAI_DEFAULT_MODEL_ADVANCED,
  openrouter_api_key: "",
  clear_openrouter_api_key: false,
  openrouter_base_url: OPENROUTER_BASE_URL,
  openrouter_model: OPENROUTER_DEFAULT_MODEL,
  openrouter_model_advanced: OPENROUTER_DEFAULT_MODEL_ADVANCED,
  zhipu_api_key: "",
  clear_zhipu_api_key: false,
  zhipu_base_url: ZHIPU_DEFAULT_BASE_URL,
  zhipu_model: ZHIPU_DEFAULT_MODEL,
  zhipu_model_advanced: ZHIPU_DEFAULT_MODEL_ADVANCED,
  openrouter_model_fallbacks: "",
  openrouter_provider_order: "",
  openrouter_allowed_providers: "",
  openrouter_ignored_providers: "",
  openrouter_allow_fallbacks: "inherit",
  openrouter_require_parameters: "inherit",
  openrouter_data_collection: "",
  openrouter_zdr: "inherit",
  openrouter_provider_sort: "",
  ollama_api_key: "",
  clear_ollama_api_key: false,
  ollama_base_url: OLLAMA_DEFAULT_BASE_URL,
  ollama_model: OLLAMA_DEFAULT_MODEL,
  ollama_keep_alive: OLLAMA_DEFAULT_KEEP_ALIVE,
  enable_llm_failover: true,
  llm_failover_chain: "google, zhipu, ollama, openrouter",
  vision_provider: "auto",
  vision_describe_provider: "auto",
  vision_describe_model: "",
  vision_ocr_provider: "auto",
  vision_ocr_model: "glm-ocr",
  vision_grounded_provider: "auto",
  vision_grounded_model: "",
  vision_failover_chain: "google, openai, openrouter, ollama",
  vision_timeout_seconds: "30",
  embedding_provider: "auto",
  embedding_failover_chain: "google, openai, ollama, openrouter",
  embedding_model: "models/gemini-embedding-001",
  agent_profiles: defaultAgentProfiles(),
  timeout_profiles: defaultTimeoutProfiles(),
  timeout_provider_overrides: defaultTimeoutProviderOverrides(),
};

function listToCsv(values: string[] | undefined): string {
  return (values ?? []).join(", ");
}

function csvToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index);
}

function boolToChoice(value: boolean | null | undefined): BoolChoice {
  if (value === true) return "true";
  if (value === false) return "false";
  return "inherit";
}

function choiceToBool(value: BoolChoice): boolean | null {
  if (value === "inherit") return null;
  return value === "true";
}

function timeoutNumberToInput(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return String(value);
}

function parseTimeoutInput(value: string): number {
  const normalized = value.trim();
  if (!normalized) return 0;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

function timeoutOverrideToDraft(
  value: LlmTimeoutProviderOverride | null | undefined,
): TimeoutProviderOverrideDraft {
  if (!value) return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter(
        ([, timeoutValue]) =>
          timeoutValue !== null && timeoutValue !== undefined,
      )
      .map(([key, timeoutValue]) => [
        key,
        timeoutNumberToInput(timeoutValue as number),
      ]),
  ) as TimeoutProviderOverrideDraft;
}

function draftToTimeoutOverrides(
  value: Record<RuntimeProvider, TimeoutProviderOverrideDraft>,
): Record<RuntimeProvider, LlmTimeoutProviderOverride> {
  return Object.fromEntries(
    Object.entries(value)
      .map(([provider, overrides]) => {
        const normalized = Object.fromEntries(
          Object.entries(overrides)
            .filter(([, rawValue]) => (rawValue ?? "").trim().length > 0)
            .map(([key, rawValue]) => [key, parseTimeoutInput(rawValue ?? "")]),
        );
        return [provider, normalized];
      })
      .filter(
        ([, overrides]) =>
          Object.keys(overrides as Record<string, number>).length > 0,
      ),
  ) as Record<RuntimeProvider, LlmTimeoutProviderOverride>;
}

function badgeClass(tone: "neutral" | "good" | "warn" | "accent"): string {
  if (tone === "good")
    return "border-green-200 bg-green-50 text-green-700 dark:border-green-900/60 dark:bg-green-950/40 dark:text-green-300";
  if (tone === "warn")
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300";
  if (tone === "accent")
    return "border-[var(--accent)]/20 bg-[var(--accent)]/10 text-[var(--accent)]";
  return "border-border bg-surface-tertiary text-text-secondary";
}

function formatCapabilityLabel(value: boolean | null | undefined): string {
  if (value === true) return "supported";
  if (value === false) return "unsupported";
  return "unknown";
}

function capabilityTone(
  value: boolean | null | undefined,
): "good" | "warn" | "neutral" {
  if (value === true) return "good";
  if (value === false) return "warn";
  return "neutral";
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "chưa có";
  return new Date(value).toLocaleString("vi-VN");
}

function visionLaneFitTone(
  value: string | null | undefined,
): "good" | "warn" | "accent" | "neutral" {
  if (value === "specialist") return "accent";
  if (value === "fallback") return "warn";
  if (value === "general") return "neutral";
  return "neutral";
}

function embeddingPreviewTone(
  preview: EmbeddingMigrationPreviewItem,
): "good" | "warn" | "accent" | "neutral" {
  if (preview.same_space) return "accent";
  if (!preview.allowed || preview.requires_reembed) return "warn";
  if (preview.embedded_row_count > 0) return "neutral";
  return "good";
}

function embeddingPreviewLabel(preview: EmbeddingMigrationPreviewItem): string {
  if (preview.same_space) return "same space";
  if (preview.requires_reembed) return "re-embed required";
  if (preview.allowed && preview.embedded_row_count <= 0) return "safe switch";
  return "review";
}

function modelNames(entries: ModelCatalogEntry[] | undefined): string[] {
  return (entries ?? []).map((entry) => entry.model_name);
}

function uniqueStrings(values: string[]): string[] {
  return values.filter((value, index, all) => all.indexOf(value) === index);
}

function FieldGroup({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-text">{label}</span>
        {hint && (
          <span className="text-[11px] text-text-tertiary text-right">
            {hint}
          </span>
        )}
      </div>
      {children}
    </label>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-start justify-between gap-3 rounded-xl border border-border bg-surface-secondary px-4 py-3 text-left hover:bg-surface-tertiary transition-colors"
    >
      <div className="min-w-0">
        <div className="text-sm font-medium text-text">{label}</div>
        <div className="mt-1 text-xs text-text-tertiary">{description}</div>
      </div>
      <span
        className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${checked ? "bg-[var(--accent)]" : "bg-gray-300 dark:bg-gray-700"}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? "translate-x-6" : "translate-x-1"}`}
        />
      </span>
    </button>
  );
}

function SecretField({
  label,
  placeholder,
  value,
  configured,
  clearRequested,
  onChange,
  onToggleClear,
}: {
  label: string;
  placeholder: string;
  value: string;
  configured: boolean;
  clearRequested: boolean;
  onChange: (value: string) => void;
  onToggleClear: () => void;
}) {
  const help = clearRequested
    ? "Sẽ xóa khỏi runtime khi lưu."
    : configured
      ? "Backend đã có key. Để trống để giữ nguyên."
      : "Chưa có key runtime.";
  return (
    <FieldGroup label={label}>
      <>
        <input
          type="password"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
        <div className="flex items-center justify-between gap-3 text-[11px] text-text-tertiary">
          <span>{help}</span>
          <button
            type="button"
            onClick={onToggleClear}
            className={`shrink-0 rounded-full border px-2 py-1 transition-colors ${clearRequested ? "border-red-200 bg-red-50 text-red-600 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300" : "border-border bg-surface text-text-secondary hover:bg-surface-tertiary"}`}
          >
            {clearRequested ? "Giữ lại key" : "Xóa key"}
          </button>
        </div>
      </>
    </FieldGroup>
  );
}

function toDraft(runtime: LlmRuntimeConfig): RuntimeDraft {
  return {
    ...EMPTY_DRAFT,
    provider: runtime.provider,
    use_multi_agent: runtime.use_multi_agent,
    google_model: runtime.google_model,
    openai_base_url: runtime.openai_base_url ?? "",
    openai_model: runtime.openai_model,
    openai_model_advanced: runtime.openai_model_advanced,
    openrouter_base_url: runtime.openrouter_base_url ?? OPENROUTER_BASE_URL,
    openrouter_model: runtime.openrouter_model,
    openrouter_model_advanced: runtime.openrouter_model_advanced,
    zhipu_base_url: runtime.zhipu_base_url ?? ZHIPU_DEFAULT_BASE_URL,
    zhipu_model: runtime.zhipu_model,
    zhipu_model_advanced: runtime.zhipu_model_advanced,
    openrouter_model_fallbacks: listToCsv(runtime.openrouter_model_fallbacks),
    openrouter_provider_order: listToCsv(runtime.openrouter_provider_order),
    openrouter_allowed_providers: listToCsv(
      runtime.openrouter_allowed_providers,
    ),
    openrouter_ignored_providers: listToCsv(
      runtime.openrouter_ignored_providers,
    ),
    openrouter_allow_fallbacks: boolToChoice(
      runtime.openrouter_allow_fallbacks,
    ),
    openrouter_require_parameters: boolToChoice(
      runtime.openrouter_require_parameters,
    ),
    openrouter_data_collection: runtime.openrouter_data_collection ?? "",
    openrouter_zdr: boolToChoice(runtime.openrouter_zdr),
    openrouter_provider_sort: runtime.openrouter_provider_sort ?? "",
    ollama_base_url: runtime.ollama_base_url ?? OLLAMA_DEFAULT_BASE_URL,
    ollama_model: runtime.ollama_model,
    ollama_keep_alive: runtime.ollama_keep_alive ?? OLLAMA_DEFAULT_KEEP_ALIVE,
    enable_llm_failover: runtime.enable_llm_failover,
    llm_failover_chain: runtime.llm_failover_chain.join(", "),
    vision_provider: runtime.vision_provider ?? "auto",
    vision_describe_provider: runtime.vision_describe_provider ?? "auto",
    vision_describe_model: runtime.vision_describe_model ?? "",
    vision_ocr_provider: runtime.vision_ocr_provider ?? "auto",
    vision_ocr_model: runtime.vision_ocr_model ?? "glm-ocr",
    vision_grounded_provider: runtime.vision_grounded_provider ?? "auto",
    vision_grounded_model: runtime.vision_grounded_model ?? "",
    vision_failover_chain: listToCsv(runtime.vision_failover_chain),
    vision_timeout_seconds: timeoutNumberToInput(
      runtime.vision_timeout_seconds,
    ),
    embedding_provider: runtime.embedding_provider ?? "auto",
    embedding_failover_chain: listToCsv(runtime.embedding_failover_chain),
    embedding_model: runtime.embedding_model,
    agent_profiles: runtime.agent_profiles ?? defaultAgentProfiles(),
    timeout_profiles: runtime.timeout_profiles ?? defaultTimeoutProfiles(),
    timeout_provider_overrides: {
      ...defaultTimeoutProviderOverrides(),
      ...Object.fromEntries(
        Object.entries(runtime.timeout_provider_overrides ?? {}).map(
          ([provider, override]) => [
            provider,
            timeoutOverrideToDraft(override),
          ],
        ),
      ),
    } as Record<RuntimeProvider, TimeoutProviderOverrideDraft>,
  };
}

function mergeRuntimeIntoDraft(
  runtime: LlmRuntimeConfig,
  current: RuntimeDraft,
): RuntimeDraft {
  return {
    ...toDraft(runtime),
    google_api_key: current.google_api_key,
    openai_api_key: current.openai_api_key,
    openrouter_api_key: current.openrouter_api_key,
    zhipu_api_key: current.zhipu_api_key,
    ollama_api_key: current.ollama_api_key,
  };
}

function applyProviderDefaults(
  current: RuntimeDraft,
  provider: RuntimeProvider,
): RuntimeDraft {
  const preset = applyLlmProviderPreset(
    {
      llm_provider: current.provider,
      google_model: current.google_model,
      openai_base_url: current.openai_base_url,
      openai_model: current.openai_model,
      openai_model_advanced: current.openai_model_advanced,
      openrouter_base_url: current.openrouter_base_url,
      openrouter_model: current.openrouter_model,
      openrouter_model_advanced: current.openrouter_model_advanced,
      zhipu_base_url: current.zhipu_base_url,
      zhipu_model: current.zhipu_model,
      zhipu_model_advanced: current.zhipu_model_advanced,
      ollama_base_url: current.ollama_base_url,
      ollama_model: current.ollama_model,
      ollama_keep_alive: current.ollama_keep_alive,
      llm_failover_chain: csvToList(current.llm_failover_chain),
    },
    provider as LlmProvider,
  );
  const next = {
    ...current,
    provider,
    google_model: preset.google_model ?? current.google_model,
    openai_base_url: preset.openai_base_url ?? current.openai_base_url,
    openai_model: preset.openai_model ?? current.openai_model,
    openai_model_advanced:
      preset.openai_model_advanced ?? current.openai_model_advanced,
    openrouter_base_url:
      preset.openrouter_base_url ?? current.openrouter_base_url,
    openrouter_model: preset.openrouter_model ?? current.openrouter_model,
    openrouter_model_advanced:
      preset.openrouter_model_advanced ?? current.openrouter_model_advanced,
    zhipu_base_url: preset.zhipu_base_url ?? current.zhipu_base_url,
    zhipu_model: preset.zhipu_model ?? current.zhipu_model,
    zhipu_model_advanced:
      preset.zhipu_model_advanced ?? current.zhipu_model_advanced,
    ollama_base_url: preset.ollama_base_url ?? current.ollama_base_url,
    ollama_model: preset.ollama_model ?? current.ollama_model,
    ollama_keep_alive: preset.ollama_keep_alive ?? current.ollama_keep_alive,
    llm_failover_chain: listToCsv(
      (preset.llm_failover_chain as string[]) ??
        csvToList(current.llm_failover_chain),
    ),
  };
  if (provider === "openrouter") {
    if (
      !next.openrouter_model ||
      LEGACY_PAID_OPENAI_MODELS.has(next.openrouter_model)
    )
      next.openrouter_model = OPENROUTER_DEFAULT_MODEL;
    if (
      !next.openrouter_model_advanced ||
      LEGACY_PAID_OPENAI_MODELS.has(next.openrouter_model_advanced)
    )
      next.openrouter_model_advanced = OPENROUTER_DEFAULT_MODEL_ADVANCED;
  }
  return next;
}

export function LlmRuntimePolicyEditor({ variant, onToast }: Props) {
  const updateSettings = useSettingsStore((state) => state.updateSettings);
  const [runtime, setRuntime] = useState<LlmRuntimeConfig | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalogResponse | null>(null);
  const [draft, setDraft] = useState<RuntimeDraft>(EMPTY_DRAFT);
  const [state, setState] = useState<"idle" | "loading" | "saving" | "error">(
    "loading",
  );
  const [message, setMessage] = useState("");
  const [isProbing, setIsProbing] = useState(false);
  const [isPlanningEmbeddingMigration, setIsPlanningEmbeddingMigration] =
    useState(false);
  const [embeddingMigrationPlan, setEmbeddingMigrationPlan] =
    useState<EmbeddingSpaceMigrationPlanResponse | null>(null);
  const [embeddingMigrationRun, setEmbeddingMigrationRun] =
    useState<EmbeddingSpaceMigrationRunResponse | null>(null);
  const isAdmin = variant === "admin";

  const notify = (msg: string, tone: ToastTone) => onToast?.(msg, tone);
  const googleModels = useMemo(
    () => modelNames(catalog?.providers.google),
    [catalog],
  );
  const openaiModels = useMemo(
    () => modelNames(catalog?.providers.openai),
    [catalog],
  );
  const openrouterModels = useMemo(
    () => modelNames(catalog?.providers.openrouter),
    [catalog],
  );
  const zhipuModels = useMemo(
    () => modelNames(catalog?.providers.zhipu),
    [catalog],
  );
  const ollamaModels = useMemo(
    () => modelNames(catalog?.providers.ollama),
    [catalog],
  );
  const providerCapabilities = useMemo(
    () => catalog?.provider_capabilities ?? {},
    [catalog],
  );

  const providerOptions = useMemo(() => {
    const statusMap = new Map(
      (runtime?.provider_status ?? []).map((item) => [item.provider, item]),
    );
    return PROVIDERS.filter((provider) => {
      const status = statusMap.get(provider);
      return status ? status.configurable_via_admin : true;
    }).map((provider) => ({
      provider,
      label: statusMap.get(provider)?.display_name ?? provider,
    }));
  }, [runtime]);
  const embeddingProviderOptions = useMemo(() => {
    const statusMap = new Map(
      (runtime?.embedding_provider_status ?? []).map((item) => [
        item.provider,
        item,
      ]),
    );
    const options = EMBEDDING_PROVIDERS.map((provider) => {
      if (provider === "auto") {
        return { provider, label: "Auto (theo chain)" };
      }
      return {
        provider,
        label: statusMap.get(provider)?.display_name ?? provider,
      };
    });
    return options;
  }, [runtime]);
  const visionProviderOptions = useMemo(() => {
    const statusMap = new Map(
      (runtime?.vision_provider_status ?? []).map((item) => [
        item.provider,
        item,
      ]),
    );
    return VISION_PROVIDERS.map((provider) => {
      if (provider === "auto") {
        return { provider, label: "Auto (theo chain)" };
      }
      return {
        provider,
        label: statusMap.get(provider)?.display_name ?? provider,
      };
    });
  }, [runtime]);
  const embeddingModelOptions = useMemo(() => {
    const fromCatalog = (catalog?.embedding_models ?? []).map((entry) => ({
      provider: entry.provider,
      model_name: entry.model_name,
    }));
    const fromRuntime = (runtime?.embedding_provider_status ?? [])
      .filter((item) => item.selected_model)
      .map((item) => ({
        provider: item.provider,
        model_name: item.selected_model as string,
      }));
    return uniqueStrings(
      [...fromCatalog, ...fromRuntime]
        .filter((entry) =>
          draft.embedding_provider === "auto"
            ? true
            : entry.provider === draft.embedding_provider,
        )
        .map((entry) => entry.model_name),
    );
  }, [catalog, draft.embedding_provider, runtime]);

  const requestSelectable = runtime?.request_selectable_providers ?? [];
  const openaiCapability = providerCapabilities.openai;
  const openrouterCapability = providerCapabilities.openrouter;
  const runtimePersistenceLabel = runtime?.runtime_policy_persisted
    ? runtime.runtime_policy_updated_at
      ? `Đã lưu vào system DB lúc ${new Date(runtime.runtime_policy_updated_at).toLocaleString("vi-VN")}.`
      : "Đã lưu vào system DB."
    : "Đang dùng env defaults hoặc runtime tạm thời chưa persist.";
  const degradedProviders = catalog?.degraded_providers ?? [];
  const auditWarnings = catalog?.audit_warnings ?? [];
  const embeddingSpaceStatus = runtime?.embedding_space_status ?? null;
  const embeddingMigrationPreviews =
    runtime?.embedding_migration_previews ?? [];
  const selectedEmbeddingPreview =
    embeddingMigrationPreviews.find(
      (item) => item.target_model === draft.embedding_model,
    ) ?? null;
  const auditSummaryLabel = catalog?.audit_updated_at
    ? `Audit cập nhật lúc ${formatDateTime(catalog.audit_updated_at)}`
    : "Chưa có audit snapshot";
  const liveProbeSummaryLabel = catalog?.last_live_probe_at
    ? `Live probe gần nhất lúc ${formatDateTime(catalog.last_live_probe_at)}`
    : "Chưa chạy live probe";
  const auditPersistenceLabel = catalog
    ? catalog.audit_persisted
      ? "Đã persist vào admin_runtime_settings."
      : "Đang hiển thị kết quả tạm thời trong request hiện tại."
    : "Đang tải audit state.";
  const setAgentProfileField = <K extends keyof AgentRuntimeProfileConfig>(
    group: string,
    field: K,
    value: AgentRuntimeProfileConfig[K],
  ) => {
    setDraft((current) => ({
      ...current,
      agent_profiles: {
        ...current.agent_profiles,
        [group]: {
          ...(current.agent_profiles[group] ?? defaultAgentProfiles()[group]),
          [field]: value,
        },
      },
    }));
  };
  const setAgentProfileProviderModel = (
    group: string,
    provider: RuntimeProvider,
    value: string,
  ) => {
    setDraft((current) => {
      const currentProfile =
        current.agent_profiles[group] ?? defaultAgentProfiles()[group];
      const nextProviderModels = { ...(currentProfile?.provider_models ?? {}) };
      if (value.trim()) nextProviderModels[provider] = value.trim();
      else delete nextProviderModels[provider];
      return {
        ...current,
        agent_profiles: {
          ...current.agent_profiles,
          [group]: {
            ...currentProfile,
            provider_models: nextProviderModels,
          },
        },
      };
    });
  };
  const setTimeoutProfileField = (
    field: keyof LlmTimeoutProfilesConfig,
    value: string,
  ) => {
    setDraft((current) => ({
      ...current,
      timeout_profiles: {
        ...current.timeout_profiles,
        [field]: parseTimeoutInput(value),
      },
    }));
  };
  const setTimeoutProviderOverride = (
    provider: RuntimeProvider,
    field: TimeoutProfileField,
    value: string,
  ) => {
    setDraft((current) => ({
      ...current,
      timeout_provider_overrides: {
        ...current.timeout_provider_overrides,
        [provider]: {
          ...(current.timeout_provider_overrides[provider] ?? {}),
          [field]: value,
        },
      },
    }));
  };
  const setEmbeddingProvider = (provider: EmbeddingProvider) => {
    setDraft((current) => {
      const suggestedModel =
        runtime?.embedding_provider_status?.find(
          (item) => item.provider === provider,
        )?.selected_model ?? current.embedding_model;
      return {
        ...current,
        embedding_provider: provider,
        embedding_model:
          provider === "auto" || !suggestedModel
            ? current.embedding_model
            : suggestedModel,
      };
    });
  };

  const loadRuntime = async () => {
    setState("loading");
    setMessage("");
    setEmbeddingMigrationPlan(null);
    setEmbeddingMigrationRun(null);
    try {
      const [runtimeConfig, modelCatalog] = await Promise.all([
        getLlmRuntimeConfig(),
        getModelCatalog(),
      ]);
      setRuntime(runtimeConfig);
      setCatalog(modelCatalog);
      setDraft((current) => mergeRuntimeIntoDraft(runtimeConfig, current));
      setState("idle");
    } catch (error) {
      setState("error");
      setMessage(
        "Không đọc được runtime policy hoặc model catalog từ backend.",
      );
      notify(String(error), "error");
    }
  };

  useEffect(() => {
    void loadRuntime();
  }, []);

  useEffect(() => {
    setEmbeddingMigrationPlan(null);
    setEmbeddingMigrationRun(null);
  }, [draft.embedding_model]);

  useEffect(() => {
    if (variant !== "settings") return;
    let cancelled = false;
    Promise.all([
      loadGeminiApiKey(),
      loadOpenAiApiKey(),
      loadOpenRouterApiKey(),
      loadZhipuApiKey(),
      loadOllamaApiKey(),
    ])
      .then(
        ([
          geminiApiKey,
          openAiApiKey,
          openRouterApiKey,
          zhipuApiKey,
          ollamaApiKey,
        ]) => {
          if (cancelled) return;
          setDraft((current) => ({
            ...current,
            google_api_key: geminiApiKey ?? current.google_api_key,
            openai_api_key: openAiApiKey ?? current.openai_api_key,
            openrouter_api_key: openRouterApiKey ?? current.openrouter_api_key,
            zhipu_api_key: zhipuApiKey ?? current.zhipu_api_key,
            ollama_api_key: ollamaApiKey ?? current.ollama_api_key,
          }));
        },
      )
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [variant]);

  const saveRuntime = async () => {
    setState("saving");
    setMessage("");
    try {
      const updated = await updateLlmRuntimeConfig({
        provider: draft.provider,
        use_multi_agent: draft.use_multi_agent,
        google_api_key: draft.google_api_key.trim() || undefined,
        clear_google_api_key: draft.clear_google_api_key,
        google_model: draft.google_model,
        openai_api_key: draft.openai_api_key.trim() || undefined,
        clear_openai_api_key: draft.clear_openai_api_key,
        openai_base_url: draft.openai_base_url,
        openai_model: draft.openai_model,
        openai_model_advanced: draft.openai_model_advanced,
        openrouter_api_key: draft.openrouter_api_key.trim() || undefined,
        clear_openrouter_api_key: draft.clear_openrouter_api_key,
        openrouter_base_url: draft.openrouter_base_url,
        openrouter_model: draft.openrouter_model,
        openrouter_model_advanced: draft.openrouter_model_advanced,
        zhipu_api_key: draft.zhipu_api_key.trim() || undefined,
        clear_zhipu_api_key: draft.clear_zhipu_api_key,
        zhipu_base_url: draft.zhipu_base_url,
        zhipu_model: draft.zhipu_model,
        zhipu_model_advanced: draft.zhipu_model_advanced,
        openrouter_model_fallbacks: csvToList(draft.openrouter_model_fallbacks),
        openrouter_provider_order: csvToList(draft.openrouter_provider_order),
        openrouter_allowed_providers: csvToList(
          draft.openrouter_allowed_providers,
        ),
        openrouter_ignored_providers: csvToList(
          draft.openrouter_ignored_providers,
        ),
        openrouter_allow_fallbacks: choiceToBool(
          draft.openrouter_allow_fallbacks,
        ),
        openrouter_require_parameters: choiceToBool(
          draft.openrouter_require_parameters,
        ),
        openrouter_data_collection: draft.openrouter_data_collection,
        openrouter_zdr: choiceToBool(draft.openrouter_zdr),
        openrouter_provider_sort: draft.openrouter_provider_sort,
        ollama_api_key: draft.ollama_api_key.trim() || undefined,
        clear_ollama_api_key: draft.clear_ollama_api_key,
        ollama_base_url: draft.ollama_base_url,
        ollama_model: draft.ollama_model,
        ollama_keep_alive: draft.ollama_keep_alive,
        enable_llm_failover: draft.enable_llm_failover,
        llm_failover_chain: csvToList(draft.llm_failover_chain.toLowerCase()),
        vision_provider: draft.vision_provider,
        vision_describe_provider: draft.vision_describe_provider,
        vision_describe_model: draft.vision_describe_model.trim() || undefined,
        vision_ocr_provider: draft.vision_ocr_provider,
        vision_ocr_model: draft.vision_ocr_model.trim() || undefined,
        vision_grounded_provider: draft.vision_grounded_provider,
        vision_grounded_model: draft.vision_grounded_model.trim() || undefined,
        vision_failover_chain: csvToList(
          draft.vision_failover_chain.toLowerCase(),
        ),
        vision_timeout_seconds:
          parseTimeoutInput(draft.vision_timeout_seconds) ||
          runtime?.vision_timeout_seconds ||
          30,
        embedding_provider: draft.embedding_provider,
        embedding_failover_chain: csvToList(
          draft.embedding_failover_chain.toLowerCase(),
        ),
        embedding_model: draft.embedding_model.trim() || undefined,
        agent_profiles: draft.agent_profiles,
        timeout_profiles: draft.timeout_profiles,
        timeout_provider_overrides: draftToTimeoutOverrides(
          draft.timeout_provider_overrides,
        ),
      });
      let refreshedCatalog: ModelCatalogResponse | null = null;
      try {
        refreshedCatalog = await getModelCatalog();
      } catch {
        refreshedCatalog = null;
      }

      if (variant === "settings") {
        await Promise.all([
          draft.google_api_key.trim()
            ? storeGeminiApiKey(draft.google_api_key.trim())
            : draft.clear_google_api_key
              ? clearGeminiApiKey()
              : Promise.resolve(),
          draft.openai_api_key.trim()
            ? storeOpenAiApiKey(draft.openai_api_key.trim())
            : draft.clear_openai_api_key
              ? clearOpenAiApiKey()
              : Promise.resolve(),
          draft.openrouter_api_key.trim()
            ? storeOpenRouterApiKey(draft.openrouter_api_key.trim())
            : draft.clear_openrouter_api_key
              ? clearOpenRouterApiKey()
              : Promise.resolve(),
          draft.zhipu_api_key.trim()
            ? storeZhipuApiKey(draft.zhipu_api_key.trim())
            : draft.clear_zhipu_api_key
              ? clearZhipuApiKey()
              : Promise.resolve(),
          draft.ollama_api_key.trim()
            ? storeOllamaApiKey(draft.ollama_api_key.trim())
            : draft.clear_ollama_api_key
              ? clearOllamaApiKey()
              : Promise.resolve(),
        ]);

        await updateSettings({
          llm_provider: updated.provider,
          google_model: updated.google_model,
          openai_base_url: updated.openai_base_url ?? "",
          openai_model: updated.openai_model,
          openai_model_advanced: updated.openai_model_advanced,
          openrouter_base_url:
            updated.openrouter_base_url ?? OPENROUTER_BASE_URL,
          openrouter_model: updated.openrouter_model,
          openrouter_model_advanced: updated.openrouter_model_advanced,
          zhipu_base_url: updated.zhipu_base_url ?? ZHIPU_DEFAULT_BASE_URL,
          zhipu_model: updated.zhipu_model,
          zhipu_model_advanced: updated.zhipu_model_advanced,
          ollama_base_url: updated.ollama_base_url ?? OLLAMA_DEFAULT_BASE_URL,
          ollama_model: updated.ollama_model,
          ollama_keep_alive:
            updated.ollama_keep_alive ?? OLLAMA_DEFAULT_KEEP_ALIVE,
          llm_failover_enabled: updated.enable_llm_failover,
          llm_failover_chain: updated.llm_failover_chain,
        });
      }

      setRuntime(updated);
      if (refreshedCatalog) setCatalog(refreshedCatalog);
      setDraft(toDraft(updated));
      setState("idle");
      setMessage(
        isAdmin ? "Đã cập nhật runtime policy." : "Đã đồng bộ LLM gateway.",
      );
      notify(
        isAdmin ? "Đã cập nhật runtime policy" : "Đã cập nhật LLM gateway",
        "success",
      );
    } catch (error) {
      setState("error");
      setMessage("Không thể cập nhật runtime policy.");
      notify(String(error), "error");
    }
  };

  const planSelectedEmbeddingMigration = async () => {
    if (!draft.embedding_model.trim()) return;
    setIsPlanningEmbeddingMigration(true);
    setMessage("");
    try {
      const plan = await planEmbeddingSpaceMigration({
        target_model: draft.embedding_model.trim(),
        target_dimensions: selectedEmbeddingPreview?.target_dimensions,
      });
      setEmbeddingMigrationPlan(plan);
      setEmbeddingMigrationRun(null);
      notify("Đã tạo migration plan cho embedding model đang chọn.", "success");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setMessage(
        "Không tạo được migration plan cho embedding model đang chọn.",
      );
      notify(detail, "error");
    } finally {
      setIsPlanningEmbeddingMigration(false);
    }
  };

  const dryRunSelectedEmbeddingMigration = async () => {
    if (!draft.embedding_model.trim()) return;
    setIsPlanningEmbeddingMigration(true);
    setMessage("");
    try {
      const result = await runEmbeddingSpaceMigration({
        target_model: draft.embedding_model.trim(),
        target_dimensions: selectedEmbeddingPreview?.target_dimensions,
        dry_run: true,
        acknowledge_maintenance_window: true,
      });
      setEmbeddingMigrationRun(result);
      if (!embeddingMigrationPlan) {
        const plan = await planEmbeddingSpaceMigration({
          target_model: draft.embedding_model.trim(),
          target_dimensions: selectedEmbeddingPreview?.target_dimensions,
        });
        setEmbeddingMigrationPlan(plan);
      }
      notify(
        "Đã chạy dry-run migration cho embedding model đang chọn.",
        "success",
      );
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setMessage(
        "Không chạy được dry-run migration cho embedding model đang chọn.",
      );
      notify(detail, "error");
    } finally {
      setIsPlanningEmbeddingMigration(false);
    }
  };

  const applySelectedEmbeddingMigration = async () => {
    if (!draft.embedding_model.trim()) return;
    setIsPlanningEmbeddingMigration(true);
    setMessage("");
    try {
      const result = await runEmbeddingSpaceMigration({
        target_model: draft.embedding_model.trim(),
        target_dimensions: selectedEmbeddingPreview?.target_dimensions,
        dry_run: false,
        acknowledge_maintenance_window: true,
      });
      setEmbeddingMigrationRun(result);
      notify(
        "Đã prepare/backfill shadow migration cho embedding model đang chọn.",
        "success",
      );
      await loadRuntime();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setMessage(
        "Không apply được shadow migration cho embedding model đang chọn.",
      );
      notify(detail, "error");
    } finally {
      setIsPlanningEmbeddingMigration(false);
    }
  };

  const promoteSelectedEmbeddingMigration = async () => {
    if (!draft.embedding_model.trim()) return;
    setIsPlanningEmbeddingMigration(true);
    setMessage("");
    try {
      const result = await promoteEmbeddingSpaceMigration({
        target_model: draft.embedding_model.trim(),
        target_dimensions: selectedEmbeddingPreview?.target_dimensions,
        acknowledge_maintenance_window: true,
      });
      setEmbeddingMigrationRun(result);
      notify("Đã promote target embedding space thành active.", "success");
      await loadRuntime();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setMessage("Không promote được target embedding space.");
      notify(detail, "error");
    } finally {
      setIsPlanningEmbeddingMigration(false);
    }
  };

  const runCapabilityProbe = async () => {
    setIsProbing(true);
    setMessage("");
    try {
      const [refreshedCatalog, refreshedRuntime] = await Promise.all([
        refreshLlmRuntimeAudit({}),
        refreshVisionRuntimeAudit({}),
      ]);
      setCatalog(refreshedCatalog);
      setRuntime(refreshedRuntime);
      setDraft((current) => mergeRuntimeIntoDraft(refreshedRuntime, current));
      const llmPersisted = refreshedCatalog.audit_persisted;
      const visionPersisted = refreshedRuntime.vision_audit_persisted;
      const probeMessage =
        llmPersisted && visionPersisted
          ? "Đã refresh LLM + vision capability audit và live probe."
          : "Đã refresh capability audit, nhưng một phần audit DB chưa sẵn sàng nên kết quả đang là tạm thời.";
      setMessage(probeMessage);
      notify(
        llmPersisted && visionPersisted
          ? "Đã refresh capability audit"
          : "Đã refresh capability audit (tạm thời)",
        "success",
      );
    } catch (error) {
      setMessage("Không thể chạy live capability probe.");
      notify(String(error), "error");
    } finally {
      setIsProbing(false);
    }
  };

  return (
    <div className="space-y-5" data-testid="llm-runtime-policy-editor">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-text">
            <Server size={16} className="text-[var(--accent)]" />
            {isAdmin ? "Runtime và Model Policy" : "LLM Gateway"}
          </div>
          <div className="mt-1 max-w-3xl text-xs text-text-tertiary">
            {isAdmin
              ? "Quản lý provider mặc định, model, failover chain và runtime truth của hệ thống."
              : "Đồng bộ provider, model, failover và secret runtime để desktop và backend khớp nhau hơn."}
          </div>
        </div>
        <div className="flex gap-2">
          {isAdmin && (
            <button
              type="button"
              onClick={() => void runCapabilityProbe()}
              disabled={state === "loading" || state === "saving" || isProbing}
              className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-secondary hover:bg-surface-tertiary disabled:opacity-50"
            >
              <Sparkles size={14} className={isProbing ? "animate-spin" : ""} />
              {isProbing ? "Đang probe..." : "Probe capability"}
            </button>
          )}
          <button
            type="button"
            onClick={() => void loadRuntime()}
            disabled={state === "loading" || state === "saving" || isProbing}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-secondary hover:bg-surface-tertiary disabled:opacity-50"
          >
            <RefreshCw
              size={14}
              className={state === "loading" ? "animate-spin" : ""}
            />
            Làm mới
          </button>
          <button
            type="button"
            onClick={() => void saveRuntime()}
            disabled={state === "loading" || state === "saving" || isProbing}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {state === "saving" ? "Đang lưu..." : "Lưu policy"}
          </button>
        </div>
      </div>

      {(message || (runtime?.warnings?.length ?? 0) > 0) && (
        <div
          className="rounded-xl border border-border bg-surface-secondary p-4 text-sm text-text-secondary"
          role="status"
          aria-live="polite"
        >
          {message && <div>{message}</div>}
          {runtime?.warnings.map((warning) => (
            <div key={warning} className="mt-2 flex items-start gap-2">
              <AlertTriangle
                size={14}
                className="mt-0.5 shrink-0 text-amber-500"
              />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      {runtime && (
        <div className="rounded-xl border border-border bg-surface-secondary px-4 py-3 text-xs text-text-tertiary">
          <span className="font-medium text-text">Persistence:</span>{" "}
          {runtimePersistenceLabel}
        </div>
      )}

      {isAdmin && catalog && (
        <div className="rounded-xl border border-border bg-surface-secondary px-4 py-3 text-xs text-text-tertiary">
          <div>
            <span className="font-medium text-text">Audit:</span>{" "}
            {auditSummaryLabel}
          </div>
          <div className="mt-1">
            <span className="font-medium text-text">Live probe:</span>{" "}
            {liveProbeSummaryLabel}
          </div>
          <div className="mt-1">
            <span className="font-medium text-text">Audit storage:</span>{" "}
            {auditPersistenceLabel}
          </div>
          <div className="mt-1">
            <span className="font-medium text-text">Degraded providers:</span>{" "}
            {degradedProviders.length
              ? degradedProviders.join(", ")
              : "không có"}
          </div>
          {auditWarnings.map((warning) => (
            <div
              key={warning}
              className="mt-2 flex items-start gap-2 text-amber-600 dark:text-amber-300"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      {isAdmin ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-border bg-surface-secondary p-4">
            <div className="text-xs text-text-tertiary">Provider mặc định</div>
            <div className="mt-1 text-lg font-semibold text-text">
              {runtime?.provider ?? "..."}
            </div>
          </div>
          <div className="rounded-xl border border-border bg-surface-secondary p-4">
            <div className="text-xs text-text-tertiary">
              Provider đang active
            </div>
            <div className="mt-1 text-lg font-semibold text-text">
              {runtime?.active_provider ?? "chưa khởi tạo"}
            </div>
          </div>
          <div className="rounded-xl border border-border bg-surface-secondary p-4">
            <div className="text-xs text-text-tertiary">
              Request-level switcher
            </div>
            <div className="mt-1 text-sm font-medium text-text">
              {requestSelectable.length
                ? requestSelectable.join(", ")
                : "Không có provider nào khả dụng"}
            </div>
          </div>
          <div className="rounded-xl border border-border bg-surface-secondary p-4">
            <div className="text-xs text-text-tertiary">Embedding hiện tại</div>
            <div className="mt-1 text-sm font-medium text-text">
              {runtime?.embedding_model ?? "..."}
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              {runtime
                ? `${runtime.embedding_dimensions} dims - ${runtime.embedding_status}`
                : "Đang tải"}
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-surface-secondary p-4 text-sm text-text-secondary">
          <div className="font-medium text-text">Runtime summary</div>
          <div className="mt-2 space-y-1 text-xs">
            <div>
              Provider mặc định:{" "}
              <span className="font-medium text-text">
                {runtime?.provider ?? draft.provider}
              </span>
            </div>
            <div>
              Active provider:{" "}
              <span className="font-medium text-text">
                {runtime?.active_provider ?? "chưa khởi tạo"}
              </span>
            </div>
            <div>
              Request switcher:{" "}
              <span className="font-medium text-text">
                {requestSelectable.join(", ") || "không có"}
              </span>
            </div>
          </div>
        </div>
      )}

      {isAdmin && (
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-[var(--accent)]" />
            <div>
              <div className="text-sm font-medium text-text">
                Trạng thái provider
              </div>
              <div className="text-xs text-text-tertiary">
                Provider nào đã cấu hình, cho phép request switch và nằm trong
                failover chain.
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(runtime?.provider_status ?? []).map((provider) => (
              <div
                key={provider.provider}
                className="rounded-xl border border-border bg-surface-secondary p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-text">
                      {provider.display_name}
                    </div>
                    <div className="text-[11px] font-mono text-text-tertiary">
                      {provider.provider}
                    </div>
                  </div>
                  {provider.available ? (
                    <CheckCircle2
                      size={16}
                      className="shrink-0 text-green-500"
                    />
                  ) : (
                    <AlertTriangle
                      size={16}
                      className="shrink-0 text-amber-500"
                    />
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span
                    className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.configured ? "good" : "warn")}`}
                  >
                    {provider.configured ? "configured" : "missing config"}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.request_selectable ? "accent" : "neutral")}`}
                  >
                    {provider.request_selectable
                      ? "request switch"
                      : "hidden from switcher"}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.in_failover_chain ? "good" : "neutral")}`}
                  >
                    {provider.in_failover_chain
                      ? "in failover chain"
                      : "outside chain"}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(providerCapabilities[provider.provider]?.degraded ? "warn" : "good")}`}
                  >
                    {providerCapabilities[provider.provider]?.degraded
                      ? "degraded"
                      : "healthy"}
                  </span>
                  {providerCapabilities[provider.provider]?.recovered ? (
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                    >
                      recovered
                    </span>
                  ) : null}
                  {provider.is_default && (
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                    >
                      default
                    </span>
                  )}
                  {provider.is_active && (
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                    >
                      active
                    </span>
                  )}
                </div>
                <div className="mt-3 space-y-1 text-[11px] text-text-tertiary">
                  <div>
                    Discovery success:{" "}
                    {formatDateTime(
                      providerCapabilities[provider.provider]
                        ?.last_discovery_success_at,
                    )}
                  </div>
                  <div>
                    Live probe success:{" "}
                    {formatDateTime(
                      providerCapabilities[provider.provider]
                        ?.last_live_probe_success_at,
                    )}
                  </div>
                  {providerCapabilities[provider.provider]
                    ?.last_runtime_success_at ? (
                    <div>
                      Runtime success:{" "}
                      {formatDateTime(
                        providerCapabilities[provider.provider]
                          ?.last_runtime_success_at,
                      )}
                    </div>
                  ) : null}
                  {providerCapabilities[provider.provider]?.live_probe_note ? (
                    <div>
                      {providerCapabilities[provider.provider]?.live_probe_note}
                    </div>
                  ) : null}
                  {providerCapabilities[provider.provider]
                    ?.last_runtime_note ? (
                    <div>
                      {
                        providerCapabilities[provider.provider]
                          ?.last_runtime_note
                      }
                    </div>
                  ) : null}
                  {providerCapabilities[provider.provider]
                    ?.last_runtime_error ? (
                    <div className="text-amber-700 dark:text-amber-300">
                      Runtime error:{" "}
                      {
                        providerCapabilities[provider.provider]
                          ?.last_runtime_error
                      }
                    </div>
                  ) : null}
                  {(providerCapabilities[provider.provider]?.recovered_reasons
                    ?.length ?? 0) > 0 ? (
                    <div className="text-green-700 dark:text-green-300">
                      Runtime recovered:{" "}
                      {providerCapabilities[
                        provider.provider
                      ]?.recovered_reasons.join(", ")}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div
        className={`grid gap-5 ${isAdmin ? "xl:grid-cols-[1.35fr_0.9fr]" : ""}`}
      >
        <div className="space-y-5 rounded-2xl border border-border bg-surface p-5">
          <div>
            <div className="text-sm font-medium text-text">Policy editor</div>
            <div className="mt-1 text-xs text-text-tertiary">
              Chỉnh default provider, model, API key, routing policy và failover
              chain mà không cần sửa code backend.
            </div>
          </div>

          <FieldGroup label="Provider mặc định">
            <select
              value={draft.provider}
              onChange={(event) =>
                setDraft((current) =>
                  applyProviderDefaults(
                    current,
                    event.target.value as RuntimeProvider,
                  ),
                )
              }
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            >
              {providerOptions.map((provider) => (
                <option key={provider.provider} value={provider.provider}>
                  {provider.label}
                </option>
              ))}
            </select>
          </FieldGroup>

          <div className="grid gap-4 md:grid-cols-2">
            <SecretField
              label="Gemini API Key"
              placeholder="AIza..."
              value={draft.google_api_key}
              configured={runtime?.google_api_key_configured ?? false}
              clearRequested={draft.clear_google_api_key}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  google_api_key: value,
                  clear_google_api_key: false,
                }))
              }
              onToggleClear={() =>
                setDraft((current) => ({
                  ...current,
                  google_api_key: "",
                  clear_google_api_key: !current.clear_google_api_key,
                }))
              }
            />
            <SecretField
              label="OpenAI API Key"
              placeholder="sk-proj-..."
              value={draft.openai_api_key}
              configured={runtime?.openai_api_key_configured ?? false}
              clearRequested={draft.clear_openai_api_key}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  openai_api_key: value,
                  clear_openai_api_key: false,
                }))
              }
              onToggleClear={() =>
                setDraft((current) => ({
                  ...current,
                  openai_api_key: "",
                  clear_openai_api_key: !current.clear_openai_api_key,
                }))
              }
            />
            <SecretField
              label="OpenRouter API Key"
              placeholder="sk-or-v1-..."
              value={draft.openrouter_api_key}
              configured={runtime?.openrouter_api_key_configured ?? false}
              clearRequested={draft.clear_openrouter_api_key}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  openrouter_api_key: value,
                  clear_openrouter_api_key: false,
                }))
              }
              onToggleClear={() =>
                setDraft((current) => ({
                  ...current,
                  openrouter_api_key: "",
                  clear_openrouter_api_key: !current.clear_openrouter_api_key,
                }))
              }
            />
            <SecretField
              label="Zhipu API Key"
              placeholder="zhipu-key"
              value={draft.zhipu_api_key}
              configured={runtime?.zhipu_api_key_configured ?? false}
              clearRequested={draft.clear_zhipu_api_key}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  zhipu_api_key: value,
                  clear_zhipu_api_key: false,
                }))
              }
              onToggleClear={() =>
                setDraft((current) => ({
                  ...current,
                  zhipu_api_key: "",
                  clear_zhipu_api_key: !current.clear_zhipu_api_key,
                }))
              }
            />
            <SecretField
              label="Ollama API Key"
              placeholder="ollama_api_key"
              value={draft.ollama_api_key}
              configured={runtime?.ollama_api_key_configured ?? false}
              clearRequested={draft.clear_ollama_api_key}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  ollama_api_key: value,
                  clear_ollama_api_key: false,
                }))
              }
              onToggleClear={() =>
                setDraft((current) => ({
                  ...current,
                  ollama_api_key: "",
                  clear_ollama_api_key: !current.clear_ollama_api_key,
                }))
              }
            />
          </div>

          <FieldGroup
            label="Gemini model"
            hint="Default cloud path cho Wiii hiện tại."
          >
            <>
              <input
                list="runtime-google-models"
                value={draft.google_model}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    google_model: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
              <datalist id="runtime-google-models">
                {googleModels.map((model) => (
                  <option key={model} value={model} />
                ))}
              </datalist>
            </>
          </FieldGroup>

          <div className="rounded-2xl border border-border bg-surface-secondary p-4 text-xs text-text-tertiary">
            OpenAI và OpenRouter giờ là hai plug riêng. Mỗi bên có key, base URL
            và model riêng, nhưng runtime vẫn đọc được legacy shared slot cũ để
            tránh vỡ cấu hình đang sống.
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup label="OpenAI base URL">
              <input
                value={draft.openai_base_url}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    openai_base_url: event.target.value,
                  }))
                }
                placeholder="https://api.openai.com/v1"
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
            <FieldGroup
              label="OpenAI model"
              hint={
                openaiCapability
                  ? `${openaiCapability.model_count} gợi ý`
                  : "openai"
              }
            >
              <>
                <input
                  list="runtime-openai-models"
                  value={draft.openai_model}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openai_model: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
                <datalist id="runtime-openai-models">
                  {openaiModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </>
            </FieldGroup>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup
              label="OpenAI advanced model"
              hint={
                openaiCapability?.selected_model_advanced_in_catalog === false
                  ? "đang dùng custom id"
                  : undefined
              }
            >
              <input
                value={draft.openai_model_advanced}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    openai_model_advanced: event.target.value,
                  }))
                }
                list="runtime-openai-models"
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
            <FieldGroup label="OpenRouter base URL">
              <input
                value={draft.openrouter_base_url}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    openrouter_base_url: event.target.value,
                  }))
                }
                placeholder={OPENROUTER_BASE_URL}
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup
              label="OpenRouter model"
              hint={
                openrouterCapability
                  ? `${openrouterCapability.model_count} gợi ý`
                  : "openrouter"
              }
            >
              <>
                <input
                  list="runtime-openrouter-models"
                  value={draft.openrouter_model}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_model: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
                <datalist id="runtime-openrouter-models">
                  {openrouterModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </>
            </FieldGroup>
            <FieldGroup
              label="OpenRouter advanced model"
              hint={
                openrouterCapability?.selected_model_advanced_in_catalog ===
                false
                  ? "đang dùng custom id"
                  : undefined
              }
            >
              <input
                value={draft.openrouter_model_advanced}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    openrouter_model_advanced: event.target.value,
                  }))
                }
                list="runtime-openrouter-models"
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup label="Zhipu base URL">
              <input
                value={draft.zhipu_base_url}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    zhipu_base_url: event.target.value,
                  }))
                }
                placeholder={ZHIPU_DEFAULT_BASE_URL}
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FieldGroup label="Zhipu model">
              <>
                <input
                  list="runtime-zhipu-models"
                  value={draft.zhipu_model}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      zhipu_model: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
                <datalist id="runtime-zhipu-models">
                  {zhipuModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </>
            </FieldGroup>
            <FieldGroup label="Zhipu advanced model">
              <input
                value={draft.zhipu_model_advanced}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    zhipu_model_advanced: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <FieldGroup label="Ollama base URL">
              <input
                value={draft.ollama_base_url}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    ollama_base_url: event.target.value,
                  }))
                }
                placeholder={OLLAMA_DEFAULT_BASE_URL}
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
            <FieldGroup label="Ollama model">
              <>
                <input
                  list="runtime-ollama-models"
                  value={draft.ollama_model}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      ollama_model: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
                <datalist id="runtime-ollama-models">
                  {ollamaModels.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </>
            </FieldGroup>
            <FieldGroup label="Ollama keep-alive">
              <input
                value={draft.ollama_keep_alive}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    ollama_keep_alive: event.target.value,
                  }))
                }
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              />
            </FieldGroup>
          </div>

          <div className="rounded-2xl border border-border bg-surface-secondary p-4">
            <div className="text-sm font-medium text-text">
              OpenRouter routing policy
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              Các trường này chỉ có tác dụng khi request đi qua OpenRouter.
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <FieldGroup label="Model fallbacks">
                <input
                  value={draft.openrouter_model_fallbacks}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_model_fallbacks: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
              <FieldGroup label="Provider order">
                <input
                  value={draft.openrouter_provider_order}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_provider_order: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
              <FieldGroup label="Allowed providers">
                <input
                  value={draft.openrouter_allowed_providers}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_allowed_providers: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
              <FieldGroup label="Ignored providers">
                <input
                  value={draft.openrouter_ignored_providers}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_ignored_providers: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
              <FieldGroup label="Allow fallbacks">
                <select
                  value={draft.openrouter_allow_fallbacks}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_allow_fallbacks: event.target
                        .value as BoolChoice,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                >
                  <option value="inherit">Inherit</option>
                  <option value="true">On</option>
                  <option value="false">Off</option>
                </select>
              </FieldGroup>
              <FieldGroup label="Require parameters">
                <select
                  value={draft.openrouter_require_parameters}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_require_parameters: event.target
                        .value as BoolChoice,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                >
                  <option value="inherit">Inherit</option>
                  <option value="true">On</option>
                  <option value="false">Off</option>
                </select>
              </FieldGroup>
              <FieldGroup label="Data collection">
                <select
                  value={draft.openrouter_data_collection}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_data_collection: event.target.value as
                        | ""
                        | "allow"
                        | "deny",
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                >
                  <option value="">Inherit</option>
                  <option value="allow">Allow</option>
                  <option value="deny">Deny</option>
                </select>
              </FieldGroup>
              <FieldGroup label="Zero data retention">
                <select
                  value={draft.openrouter_zdr}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_zdr: event.target.value as BoolChoice,
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                >
                  <option value="inherit">Inherit</option>
                  <option value="true">On</option>
                  <option value="false">Off</option>
                </select>
              </FieldGroup>
              <FieldGroup label="Provider sort">
                <select
                  value={draft.openrouter_provider_sort}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      openrouter_provider_sort: event.target.value as
                        | ""
                        | "price"
                        | "latency"
                        | "throughput",
                    }))
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                >
                  <option value="">Inherit</option>
                  <option value="price">Price</option>
                  <option value="latency">Latency</option>
                  <option value="throughput">Throughput</option>
                </select>
              </FieldGroup>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface-secondary p-4">
            <div className="text-sm font-medium text-text">
              Grouped agent profiles
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              Admin quan ly provider/tier/model theo nhom workload. End-user chi
              chon provider, không chọn raw model ID.
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {AGENT_PROFILE_GROUPS.map((group) => {
                const profile =
                  draft.agent_profiles[group] ?? defaultAgentProfiles()[group];
                return (
                  <div
                    key={group}
                    className="rounded-xl border border-border bg-surface p-4"
                  >
                    <div className="text-sm font-medium text-text">
                      {AGENT_PROFILE_LABELS[group]}
                    </div>
                    <div className="mt-1 text-xs text-text-tertiary">
                      {AGENT_PROFILE_DESCRIPTIONS[group]}
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <FieldGroup label="Default provider">
                        <select
                          value={profile.default_provider}
                          onChange={(event) =>
                            setAgentProfileField(
                              group,
                              "default_provider",
                              event.target.value as RuntimeProvider,
                            )
                          }
                          className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                        >
                          {AGENT_PROFILE_PROVIDER_OPTIONS.map((provider) => (
                            <option key={provider} value={provider}>
                              {provider}
                            </option>
                          ))}
                        </select>
                      </FieldGroup>
                      <FieldGroup label="Tier">
                        <select
                          value={profile.tier}
                          onChange={(event) =>
                            setAgentProfileField(
                              group,
                              "tier",
                              event.target
                                .value as AgentRuntimeProfileConfig["tier"],
                            )
                          }
                          className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                        >
                          <option value="light">light</option>
                          <option value="moderate">moderate</option>
                          <option value="deep">deep</option>
                        </select>
                      </FieldGroup>
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      {AGENT_PROFILE_PROVIDER_OPTIONS.map((provider) => (
                        <FieldGroup
                          key={`${group}-${provider}`}
                          label={`${provider} model`}
                          hint="Để trống để dùng model mặc định của provider"
                        >
                          <input
                            value={profile.provider_models?.[provider] ?? ""}
                            onChange={(event) =>
                              setAgentProfileProviderModel(
                                group,
                                provider,
                                event.target.value,
                              )
                            }
                            className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                          />
                        </FieldGroup>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface-secondary p-4">
            <div className="text-sm font-medium text-text">
              Timeout profiles
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              Timeout ở đây là first-response timeout và stream stall policy.
              Tác vụ dài hơi như course generation hoặc code workflow nên đi qua
              background/session workflow, không nên ép một request sync chạy vô
              hạn.
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {TIMEOUT_PROFILE_FIELDS.map((field) => (
                <FieldGroup
                  key={field.key}
                  label={`${field.label} (giây)`}
                  hint={field.hint}
                >
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={timeoutNumberToInput(
                      draft.timeout_profiles[field.key],
                    )}
                    onChange={(event) =>
                      setTimeoutProfileField(field.key, event.target.value)
                    }
                    className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  />
                </FieldGroup>
              ))}
              <FieldGroup
                label="Stream keepalive (giây)"
                hint="Heartbeat giữ SSE sống."
              >
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={timeoutNumberToInput(
                    draft.timeout_profiles.stream_keepalive_interval_seconds,
                  )}
                  onChange={(event) =>
                    setTimeoutProfileField(
                      "stream_keepalive_interval_seconds",
                      event.target.value,
                    )
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
              <FieldGroup
                label="Stream idle timeout (giây)"
                hint="0 = không cắt stream đang im lặng."
              >
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={timeoutNumberToInput(
                    draft.timeout_profiles.stream_idle_timeout_seconds,
                  )}
                  onChange={(event) =>
                    setTimeoutProfileField(
                      "stream_idle_timeout_seconds",
                      event.target.value,
                    )
                  }
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                />
              </FieldGroup>
            </div>
            <div className="mt-4 rounded-xl border border-border bg-surface p-3 text-[11px] text-text-tertiary">
              Gợi ý vận hành: `light/moderate/deep` dành cho interactive chat,
              `structured` dành cho planner/router/schema-heavy calls, còn
              `background` dành cho workflow dài có checkpoint.
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface-secondary p-4">
            <div className="text-sm font-medium text-text">
              Provider-specific timeout overrides
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              Nếu để trống, provider sẽ inherit timeout global bên trên. Dùng
              khi một provider có latency/throttle khác biệt nhưng bạn chưa muốn
              đổi policy chung của hệ thống.
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {TIMEOUT_OVERRIDE_PROVIDERS.map((provider) => {
                const overrides =
                  draft.timeout_provider_overrides[provider] ?? {};
                return (
                  <div
                    key={`timeout-${provider}`}
                    className="rounded-xl border border-border bg-surface p-4"
                  >
                    <div className="text-sm font-medium text-text">
                      {provider}
                    </div>
                    <div className="mt-1 text-xs text-text-tertiary">
                      Override theo provider cho first-response timeout. Bỏ
                      trống = inherit.
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      {TIMEOUT_PROFILE_FIELDS.map((field) => (
                        <FieldGroup
                          key={`${provider}-${field.key}`}
                          label={`${field.label} (giây)`}
                          hint="Để trống để inherit"
                        >
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={overrides[field.key] ?? ""}
                            onChange={(event) =>
                              setTimeoutProviderOverride(
                                provider,
                                field.key,
                                event.target.value,
                              )
                            }
                            className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                          />
                        </FieldGroup>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <FieldGroup
            label="Failover chain"
            hint="Ví dụ: google, zhipu, ollama"
          >
            <input
              value={draft.llm_failover_chain}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  llm_failover_chain: event.target.value,
                }))
              }
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            />
          </FieldGroup>

          <div className="space-y-3">
            <ToggleRow
              label="Bật failover runtime"
              description="Cho phép chuyển sang provider tiếp theo trong chain khi provider hiện tại lỗi."
              checked={draft.enable_llm_failover}
              onChange={(value) =>
                setDraft((current) => ({
                  ...current,
                  enable_llm_failover: value,
                }))
              }
            />
            <ToggleRow
              label="Bật Multi-Agent Graph"
              description="Tắt khi cần direct path gọn hơn; bật khi muốn dùng orchestration đầy đủ."
              checked={draft.use_multi_agent}
              onChange={(value) =>
                setDraft((current) => ({ ...current, use_multi_agent: value }))
              }
            />
          </div>
        </div>

        {isAdmin && (
          <div className="space-y-5">
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="text-sm font-medium text-text">
                Vision runtime
              </div>
              <div className="mt-1 text-xs text-text-tertiary">
                Authority chung cho mô tả ảnh, OCR và grounded visual answer.
                Bạn có thể đổi provider mode, chain và timeout mà không phải sửa
                từng lane riêng.
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <FieldGroup
                  label="Provider mode"
                  hint="`auto` = theo failover chain"
                >
                  <select
                    aria-label="Vision provider mode"
                    data-testid="runtime-vision-provider"
                    value={draft.vision_provider}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        vision_provider: event.target.value as VisionProvider,
                      }))
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  >
                    {visionProviderOptions.map((option) => (
                      <option
                        key={`vision-provider-${option.provider}`}
                        value={option.provider}
                      >
                        {option.label}
                      </option>
                    ))}
                  </select>
                </FieldGroup>
                <FieldGroup
                  label="Vision failover chain"
                  hint="Vi du: google, openai, ollama"
                >
                  <input
                    aria-label="Vision failover chain"
                    data-testid="runtime-vision-failover-chain"
                    value={draft.vision_failover_chain}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        vision_failover_chain: event.target.value,
                      }))
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  />
                </FieldGroup>
                <FieldGroup
                  label="Vision timeout (giây)"
                  hint="Cho một request vision đã gồm failover"
                >
                  <input
                    aria-label="Vision timeout"
                    data-testid="runtime-vision-timeout"
                    type="number"
                    min="5"
                    max="120"
                    step="1"
                    value={draft.vision_timeout_seconds}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        vision_timeout_seconds: event.target.value,
                      }))
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  />
                </FieldGroup>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <FieldGroup
                  label="Visual describe lane"
                  hint="Captioning / memory / Visual RAG"
                >
                  <div className="space-y-2">
                    <select
                      aria-label="Vision describe provider"
                      data-testid="runtime-vision-describe-provider"
                      value={draft.vision_describe_provider}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_describe_provider: event.target
                            .value as VisionProvider,
                        }))
                      }
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    >
                      {visionProviderOptions.map((option) => (
                        <option
                          key={`vision-describe-provider-${option.provider}`}
                          value={option.provider}
                        >
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="Vision describe model"
                      data-testid="runtime-vision-describe-model"
                      value={draft.vision_describe_model}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_describe_model: event.target.value,
                        }))
                      }
                      placeholder="Vi du: qwen/qwen2.5-vl-7b-instruct"
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    />
                  </div>
                </FieldGroup>
                <FieldGroup
                  label="OCR lane"
                  hint="Document parsing / formulas / tables"
                >
                  <div className="space-y-2">
                    <select
                      aria-label="Vision OCR provider"
                      data-testid="runtime-vision-ocr-provider"
                      value={draft.vision_ocr_provider}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_ocr_provider: event.target
                            .value as VisionProvider,
                        }))
                      }
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    >
                      {visionProviderOptions.map((option) => (
                        <option
                          key={`vision-ocr-provider-${option.provider}`}
                          value={option.provider}
                        >
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="Vision OCR model"
                      data-testid="runtime-vision-ocr-model"
                      value={draft.vision_ocr_model}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_ocr_model: event.target.value,
                        }))
                      }
                      placeholder="Vi du: glm-ocr"
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    />
                  </div>
                </FieldGroup>
                <FieldGroup
                  label="Grounded answer lane"
                  hint="Visual QA / chart reasoning"
                >
                  <div className="space-y-2">
                    <select
                      aria-label="Vision grounded provider"
                      data-testid="runtime-vision-grounded-provider"
                      value={draft.vision_grounded_provider}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_grounded_provider: event.target
                            .value as VisionProvider,
                        }))
                      }
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    >
                      {visionProviderOptions.map((option) => (
                        <option
                          key={`vision-grounded-provider-${option.provider}`}
                          value={option.provider}
                        >
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="Vision grounded model"
                      data-testid="runtime-vision-grounded-model"
                      value={draft.vision_grounded_model}
                      onChange={(event) =>
                        setDraft((current) => ({
                          ...current,
                          vision_grounded_model: event.target.value,
                        }))
                      }
                      placeholder="Vi du: qwen/qwen2.5-vl-32b-instruct"
                      className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                    />
                  </div>
                </FieldGroup>
              </div>
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                Provider mode:{" "}
                <span className="font-medium text-text">
                  {runtime?.vision_provider ?? "auto"}
                </span>
                {(runtime?.vision_failover_chain?.length ?? 0) > 0
                  ? ` • chain ${runtime?.vision_failover_chain?.join(", ")}`
                  : ""}
                {runtime?.vision_timeout_seconds
                  ? ` • timeout ${runtime.vision_timeout_seconds}s`
                  : ""}
              </div>
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                <div>
                  Describe lane:{" "}
                  <span className="font-medium text-text">
                    {runtime?.vision_describe_provider ?? "auto"}
                  </span>
                  {runtime?.vision_describe_model
                    ? ` / ${runtime.vision_describe_model}`
                    : ""}
                </div>
                <div className="mt-1">
                  OCR lane:{" "}
                  <span className="font-medium text-text">
                    {runtime?.vision_ocr_provider ?? "auto"}
                  </span>
                  {runtime?.vision_ocr_model
                    ? ` / ${runtime.vision_ocr_model}`
                    : ""}
                </div>
                <div className="mt-1">
                  Grounded lane:{" "}
                  <span className="font-medium text-text">
                    {runtime?.vision_grounded_provider ?? "auto"}
                  </span>
                  {runtime?.vision_grounded_model
                    ? ` / ${runtime.vision_grounded_model}`
                    : ""}
                </div>
              </div>
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                <div>
                  Audit DB:{" "}
                  <span className="font-medium text-text">
                    {runtime?.vision_audit_persisted
                      ? "Đã lưu vào system DB"
                      : "Đang hiển thị kết quả tạm thời"}
                  </span>
                </div>
                <div className="mt-1">
                  Live probe gần nhất:{" "}
                  <span className="font-medium text-text">
                    {formatDateTime(runtime?.vision_last_live_probe_at)}
                  </span>
                </div>
                <div className="mt-1">
                  Audit update:{" "}
                  <span className="font-medium text-text">
                    {formatDateTime(runtime?.vision_audit_updated_at)}
                  </span>
                </div>
                {(runtime?.vision_audit_warnings?.length ?? 0) > 0 ? (
                  <div className="mt-2 space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
                    {runtime?.vision_audit_warnings?.map((warning) => (
                      <div key={warning}>{warning}</div>
                    ))}
                  </div>
                ) : null}
              </div>
              {(runtime?.vision_provider_status?.length ?? 0) > 0 ? (
                <div className="mt-4 space-y-3">
                  {runtime?.vision_provider_status?.map((provider) => (
                    <div
                      key={`vision-${provider.provider}`}
                      className="rounded-xl border border-border bg-surface-secondary p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-text">
                            {provider.display_name}
                          </div>
                          <div className="text-[11px] font-mono text-text-tertiary">
                            {provider.provider}
                          </div>
                        </div>
                        {provider.available ? (
                          <CheckCircle2
                            size={16}
                            className="shrink-0 text-green-500"
                          />
                        ) : (
                          <AlertTriangle
                            size={16}
                            className="shrink-0 text-amber-500"
                          />
                        )}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.configured ? "good" : "warn")}`}
                        >
                          {provider.configured
                            ? "configured"
                            : "missing config"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.in_failover_chain ? "good" : "neutral")}`}
                        >
                          {provider.in_failover_chain
                            ? "in chain"
                            : "outside chain"}
                        </span>
                        {provider.is_default ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                          >
                            default
                          </span>
                        ) : null}
                        {provider.is_active ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                          >
                            active
                          </span>
                        ) : null}
                        {provider.degraded ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("warn")}`}
                          >
                            degraded
                          </span>
                        ) : null}
                        {provider.recovered ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                          >
                            recovered
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-3 space-y-1 text-[11px] text-text-tertiary">
                        <div>
                          model:{" "}
                          <span className="font-mono text-text">
                            {provider.selected_model ?? "n/a"}
                          </span>
                        </div>
                        <div>
                          probe success:{" "}
                          <span className="font-medium text-text">
                            {formatDateTime(provider.last_probe_success_at)}
                          </span>
                        </div>
                        {provider.last_runtime_success_at ? (
                          <div>
                            runtime success:{" "}
                            <span className="font-medium text-text">
                              {formatDateTime(provider.last_runtime_success_at)}
                            </span>
                          </div>
                        ) : null}
                        {provider.reason_label ? (
                          <div>{provider.reason_label}</div>
                        ) : null}
                        {provider.last_probe_error ? (
                          <div>
                            live probe error: {provider.last_probe_error}
                          </div>
                        ) : null}
                        {provider.last_runtime_error ? (
                          <div>
                            runtime error: {provider.last_runtime_error}
                          </div>
                        ) : null}
                        {provider.last_runtime_note ? (
                          <div>runtime note: {provider.last_runtime_note}</div>
                        ) : null}
                        {(provider.recovered_reasons?.length ?? 0) > 0 ? (
                          <div>
                            runtime recovered on:{" "}
                            {provider.recovered_reasons?.join(", ")}
                          </div>
                        ) : null}
                        {(provider.degraded_reasons?.length ?? 0) > 0 ? (
                          <div>{provider.degraded_reasons?.join(" ")}</div>
                        ) : null}
                      </div>
                      {(provider.capabilities?.length ?? 0) > 0 ? (
                        <div className="mt-3 grid gap-2 md:grid-cols-3">
                          {provider.capabilities.map((capability) => (
                            <div
                              key={`${provider.provider}-${capability.capability}`}
                              className="rounded-lg border border-border bg-surface px-3 py-2 text-[11px] text-text-tertiary"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="font-medium text-text">
                                  {capability.display_name}
                                </div>
                                {capability.lane_fit_label ? (
                                  <span
                                    className={`rounded-full border px-2 py-0.5 text-[10px] ${badgeClass(visionLaneFitTone(capability.lane_fit))}`}
                                  >
                                    {capability.lane_fit_label}
                                  </span>
                                ) : null}
                                {capability.recovered ? (
                                  <span
                                    className={`rounded-full border px-2 py-0.5 text-[10px] ${badgeClass("good")}`}
                                  >
                                    recovered
                                  </span>
                                ) : null}
                              </div>
                              <div className="mt-1">
                                {capability.available
                                  ? "usable"
                                  : (capability.reason_label ??
                                    "not available")}
                              </div>
                              {capability.selected_model ? (
                                <div className="mt-1 break-all font-mono">
                                  {capability.selected_model}
                                </div>
                              ) : null}
                              {capability.last_probe_success_at ? (
                                <div className="mt-1">
                                  probe ok:{" "}
                                  {formatDateTime(
                                    capability.last_probe_success_at,
                                  )}
                                </div>
                              ) : null}
                              {capability.last_runtime_success_at ? (
                                <div className="mt-1">
                                  runtime ok:{" "}
                                  {formatDateTime(
                                    capability.last_runtime_success_at,
                                  )}
                                </div>
                              ) : null}
                              {capability.live_probe_note ? (
                                <div className="mt-1">
                                  {capability.live_probe_note}
                                </div>
                              ) : null}
                              {capability.last_runtime_note ? (
                                <div className="mt-1 text-text-secondary">
                                  {capability.last_runtime_note}
                                </div>
                              ) : null}
                              {capability.recovered_label ? (
                                <div className="mt-1 text-green-700 dark:text-green-300">
                                  {capability.recovered_label}
                                </div>
                              ) : null}
                              {capability.last_probe_error ? (
                                <div className="mt-1 text-amber-700 dark:text-amber-300">
                                  {capability.last_probe_error}
                                </div>
                              ) : null}
                              {capability.last_runtime_error ? (
                                <div className="mt-1 text-amber-700 dark:text-amber-300">
                                  runtime: {capability.last_runtime_error}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                Vision audit giúp thấy provider nào đang dùng được cho mô tả
                ảnh, OCR và grounded answer, thay vì để từng lane gọi vision
                riêng rồi chết ngầm.
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="text-sm font-medium text-text">
                Embedding policy
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <FieldGroup
                  label="Provider mode"
                  hint="`auto` = theo failover chain"
                >
                  <select
                    aria-label="Embedding provider mode"
                    data-testid="runtime-embedding-provider"
                    value={draft.embedding_provider}
                    onChange={(event) =>
                      setEmbeddingProvider(
                        event.target.value as EmbeddingProvider,
                      )
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  >
                    {embeddingProviderOptions.map((option) => (
                      <option
                        key={`embedding-provider-${option.provider}`}
                        value={option.provider}
                      >
                        {option.label}
                      </option>
                    ))}
                  </select>
                </FieldGroup>
                <FieldGroup
                  label="Embedding model"
                  hint="Chỉ mở các model có contract đã biết"
                >
                  <input
                    aria-label="Embedding model"
                    data-testid="runtime-embedding-model"
                    list="embedding-model-options"
                    value={draft.embedding_model}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        embedding_model: event.target.value,
                      }))
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  />
                  <datalist id="embedding-model-options">
                    {embeddingModelOptions.map((modelName) => (
                      <option
                        key={`embedding-model-${modelName}`}
                        value={modelName}
                      />
                    ))}
                  </datalist>
                </FieldGroup>
                <FieldGroup
                  label="Embedding failover chain"
                  hint="Ví dụ: ollama, google, openai"
                >
                  <input
                    aria-label="Embedding failover chain"
                    data-testid="runtime-embedding-failover-chain"
                    value={draft.embedding_failover_chain}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        embedding_failover_chain: event.target.value,
                      }))
                    }
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
                  />
                </FieldGroup>
              </div>
              <div className="mt-2 text-sm text-text">
                <div className="font-medium">
                  {runtime?.embedding_model ?? "..."}
                </div>
                <div className="mt-1 text-xs text-text-tertiary">
                  {runtime
                    ? `${runtime.embedding_dimensions} dimensions`
                    : "Đang tải"}
                </div>
                <div className="mt-1 text-xs text-text-tertiary">
                  Status: {runtime?.embedding_status ?? "unknown"}
                </div>
                <div className="mt-1 text-xs text-text-tertiary">
                  Provider mode:{" "}
                  <span className="font-medium text-text">
                    {runtime?.embedding_provider ?? "auto"}
                  </span>
                  {(runtime?.embedding_failover_chain?.length ?? 0) > 0
                    ? ` • chain ${runtime?.embedding_failover_chain?.join(", ")}`
                    : ""}
                </div>
              </div>
              {embeddingSpaceStatus ? (
                <div className="mt-4 rounded-xl border border-border bg-surface-secondary p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-text">
                        Embedding space health
                      </div>
                      <div className="mt-1 text-xs text-text-tertiary">
                        Đây là tình trạng thật của vector-space đang sống trong
                        DB và backend active.
                      </div>
                    </div>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(embeddingSpaceStatus.audit_available ? "good" : "warn")}`}
                    >
                      {embeddingSpaceStatus.audit_available
                        ? "audit ok"
                        : "audit unavailable"}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-border bg-surface p-3">
                      <div className="text-[11px] uppercase tracking-wide text-text-tertiary">
                        Policy contract
                      </div>
                      <div className="mt-1 text-sm font-medium text-text">
                        {embeddingSpaceStatus.policy_contract?.label ??
                          "chưa có"}
                      </div>
                      <div className="mt-1 break-all text-[11px] font-mono text-text-tertiary">
                        {embeddingSpaceStatus.policy_contract?.fingerprint ??
                          "n/a"}
                      </div>
                    </div>
                    <div className="rounded-xl border border-border bg-surface p-3">
                      <div className="text-[11px] uppercase tracking-wide text-text-tertiary">
                        Active contract
                      </div>
                      <div className="mt-1 text-sm font-medium text-text">
                        {embeddingSpaceStatus.active_contract?.label ??
                          "chưa có"}
                      </div>
                      <div className="mt-1 break-all text-[11px] font-mono text-text-tertiary">
                        {embeddingSpaceStatus.active_contract?.fingerprint ??
                          "n/a"}
                      </div>
                      <div className="mt-2">
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(
                            embeddingSpaceStatus.active_matches_policy === false
                              ? "warn"
                              : embeddingSpaceStatus.active_matches_policy ===
                                  true
                                ? "good"
                                : "neutral",
                          )}`}
                        >
                          {embeddingSpaceStatus.active_matches_policy === false
                            ? "active != policy"
                            : embeddingSpaceStatus.active_matches_policy ===
                                true
                              ? "active = policy"
                              : "chưa xác định"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                    >
                      {embeddingSpaceStatus.total_embedded_rows} embedded rows
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(
                        embeddingSpaceStatus.total_untracked_rows > 0
                          ? "warn"
                          : "good",
                      )}`}
                    >
                      {embeddingSpaceStatus.total_tracked_rows} tracked
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(
                        embeddingSpaceStatus.total_untracked_rows > 0
                          ? "warn"
                          : "neutral",
                      )}`}
                    >
                      {embeddingSpaceStatus.total_untracked_rows} untracked
                    </span>
                  </div>
                  {(embeddingSpaceStatus.tables?.length ?? 0) > 0 ? (
                    <div className="mt-3 space-y-2">
                      {embeddingSpaceStatus.tables.map((table) => (
                        <div
                          key={`embedding-space-${table.table_name}`}
                          className="rounded-xl border border-border bg-surface p-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-sm font-medium text-text">
                              {table.table_name}
                            </div>
                            <div className="text-[11px] text-text-tertiary">
                              {table.embedded_row_count} embedded •{" "}
                              {table.tracked_row_count} tracked •{" "}
                              {table.untracked_row_count} untracked
                            </div>
                          </div>
                          {Object.keys(table.fingerprints ?? {}).length > 0 ? (
                            <div className="mt-2 space-y-1 text-[11px] text-text-tertiary">
                              {Object.entries(table.fingerprints).map(
                                ([fingerprint, count]) => (
                                  <div
                                    key={`${table.table_name}-${fingerprint}`}
                                    className="break-all font-mono"
                                  >
                                    {fingerprint} • {count}
                                  </div>
                                ),
                              )}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {(embeddingSpaceStatus.warnings?.length ?? 0) > 0 ? (
                    <div className="mt-3 space-y-2">
                      {embeddingSpaceStatus.warnings.map((warning) => (
                        <div
                          key={warning}
                          className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300"
                        >
                          {warning}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {embeddingSpaceStatus.error ? (
                    <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
                      Audit error: {embeddingSpaceStatus.error}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {selectedEmbeddingPreview ? (
                <div className="mt-4 rounded-xl border border-border bg-surface-secondary p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-text">
                        Preview cho model đang chọn
                      </div>
                      <div className="mt-1 text-xs text-text-tertiary">
                        {selectedEmbeddingPreview.target_label} •{" "}
                        {selectedEmbeddingPreview.target_provider} •{" "}
                        {selectedEmbeddingPreview.target_dimensions}d
                      </div>
                    </div>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(embeddingPreviewTone(selectedEmbeddingPreview))}`}
                    >
                      {embeddingPreviewLabel(selectedEmbeddingPreview)}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(selectedEmbeddingPreview.same_space ? "accent" : "neutral")}`}
                    >
                      {selectedEmbeddingPreview.same_space
                        ? "same vector-space"
                        : "space change"}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(selectedEmbeddingPreview.allowed ? "good" : "warn")}`}
                    >
                      {selectedEmbeddingPreview.allowed
                        ? "transition allowed"
                        : "transition blocked"}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(selectedEmbeddingPreview.requires_reembed ? "warn" : "neutral")}`}
                    >
                      {selectedEmbeddingPreview.requires_reembed
                        ? "re-embed trước"
                        : "không cần re-embed"}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(selectedEmbeddingPreview.target_backend_constructible ? "good" : "warn")}`}
                    >
                      {selectedEmbeddingPreview.target_backend_constructible
                        ? "target backend ok"
                        : "target backend chưa sẵn sàng"}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(selectedEmbeddingPreview.maintenance_required ? "warn" : "neutral")}`}
                    >
                      {selectedEmbeddingPreview.maintenance_required
                        ? "maintenance only"
                        : "không cần drain traffic"}
                    </span>
                  </div>
                  <div className="mt-3 space-y-1 text-[11px] text-text-tertiary">
                    <div>
                      Target model:{" "}
                      <span className="font-mono text-text">
                        {selectedEmbeddingPreview.target_model}
                      </span>
                    </div>
                    <div>
                      Status:{" "}
                      <span className="font-medium text-text">
                        {selectedEmbeddingPreview.target_status}
                      </span>
                    </div>
                    <div>
                      Embedded rows hiện tại:{" "}
                      <span className="font-medium text-text">
                        {selectedEmbeddingPreview.embedded_row_count}
                      </span>
                    </div>
                    {selectedEmbeddingPreview.detail ? (
                      <div>{selectedEmbeddingPreview.detail}</div>
                    ) : null}
                    {(selectedEmbeddingPreview.recommended_steps?.length ?? 0) >
                    0 ? (
                      <div className="space-y-1 pt-1">
                        {selectedEmbeddingPreview.recommended_steps
                          .slice(0, 3)
                          .map((step) => (
                            <div key={step}>• {step}</div>
                          ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void planSelectedEmbeddingMigration()}
                      disabled={isPlanningEmbeddingMigration}
                      className="rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-text hover:bg-surface-tertiary disabled:opacity-50"
                    >
                      {isPlanningEmbeddingMigration
                        ? "Đang xử lý..."
                        : "Plan migration"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void dryRunSelectedEmbeddingMigration()}
                      disabled={isPlanningEmbeddingMigration}
                      className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-3 py-2 text-xs font-medium text-[var(--accent)] hover:bg-[var(--accent)]/15 disabled:opacity-50"
                    >
                      {isPlanningEmbeddingMigration
                        ? "Đang xử lý..."
                        : "Dry-run migration"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void applySelectedEmbeddingMigration()}
                      disabled={isPlanningEmbeddingMigration}
                      className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-600 hover:bg-emerald-500/15 disabled:opacity-50"
                    >
                      {isPlanningEmbeddingMigration
                        ? "Đang xử lý..."
                        : "Apply shadow"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void promoteSelectedEmbeddingMigration()}
                      disabled={isPlanningEmbeddingMigration}
                      className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-500/15 disabled:opacity-50"
                    >
                      {isPlanningEmbeddingMigration
                        ? "Đang xử lý..."
                        : "Promote target"}
                    </button>
                  </div>
                  {embeddingMigrationPlan ? (
                    <div className="mt-4 rounded-xl border border-border bg-surface p-3 text-[11px] text-text-tertiary">
                      <div className="text-sm font-medium text-text">
                        Migration plan snapshot
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <span
                          className={`rounded-full border px-2 py-1 ${badgeClass(embeddingMigrationPlan.same_space ? "accent" : "neutral")}`}
                        >
                          {embeddingMigrationPlan.same_space
                            ? "same space"
                            : "new space"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 ${badgeClass(embeddingMigrationPlan.transition_allowed ? "good" : "warn")}`}
                        >
                          {embeddingMigrationPlan.transition_allowed
                            ? "transition allowed"
                            : "transition blocked"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 ${badgeClass(embeddingMigrationPlan.target_backend_constructible ? "good" : "warn")}`}
                        >
                          {embeddingMigrationPlan.target_backend_constructible
                            ? "backend ok"
                            : "backend missing"}
                        </span>
                        {embeddingMigrationPlan.maintenance_required ? (
                          <span
                            className={`rounded-full border px-2 py-1 ${badgeClass("warn")}`}
                          >
                            maintenance only
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-2">
                        Candidate rows:{" "}
                        <span className="font-medium text-text">
                          {embeddingMigrationPlan.total_candidate_rows}
                        </span>
                        {" • "}
                        Embedded rows:{" "}
                        <span className="font-medium text-text">
                          {embeddingMigrationPlan.total_embedded_rows}
                        </span>
                      </div>
                      {embeddingMigrationPlan.detail ? (
                        <div className="mt-2">
                          {embeddingMigrationPlan.detail}
                        </div>
                      ) : null}
                      {(embeddingMigrationPlan.recommended_steps?.length ?? 0) >
                      0 ? (
                        <div className="mt-2 space-y-1">
                          {embeddingMigrationPlan.recommended_steps
                            .slice(0, 3)
                            .map((step) => (
                              <div key={step}>• {step}</div>
                            ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {embeddingMigrationRun ? (
                    <div className="mt-3 rounded-xl border border-border bg-surface p-3 text-[11px] text-text-tertiary">
                      <div className="text-sm font-medium text-text">
                        {embeddingMigrationRun.dry_run
                          ? "Dry-run result"
                          : "Migration action result"}
                      </div>
                      <div className="mt-2">
                        Target contract:{" "}
                        <span className="font-mono text-text">
                          {embeddingMigrationRun.target_contract_fingerprint ??
                            "n/a"}
                        </span>
                      </div>
                      {(embeddingMigrationRun.tables?.length ?? 0) > 0 ? (
                        <div className="mt-2 space-y-1">
                          {embeddingMigrationRun.tables.map((table) => (
                            <div key={table.table_name}>
                              {table.table_name}: candidate{" "}
                              {table.candidate_rows}, skipped{" "}
                              {table.skipped_rows}, failed {table.failed_rows}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {embeddingMigrationRun.detail ? (
                        <div className="mt-2">
                          {embeddingMigrationRun.detail}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {(runtime?.embedding_provider_status?.length ?? 0) > 0 ? (
                <div className="mt-4 space-y-3">
                  {runtime?.embedding_provider_status?.map((provider) => (
                    <div
                      key={`embedding-${provider.provider}`}
                      className="rounded-xl border border-border bg-surface-secondary p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-text">
                            {provider.display_name}
                          </div>
                          <div className="text-[11px] font-mono text-text-tertiary">
                            {provider.provider}
                          </div>
                        </div>
                        {provider.available ? (
                          <CheckCircle2
                            size={16}
                            className="shrink-0 text-green-500"
                          />
                        ) : (
                          <AlertTriangle
                            size={16}
                            className="shrink-0 text-amber-500"
                          />
                        )}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.configured ? "good" : "warn")}`}
                        >
                          {provider.configured
                            ? "configured"
                            : "missing config"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.in_failover_chain ? "good" : "neutral")}`}
                        >
                          {provider.in_failover_chain
                            ? "in chain"
                            : "outside chain"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(provider.supports_dimension_override ? "accent" : "neutral")}`}
                        >
                          {provider.supports_dimension_override
                            ? "dims override"
                            : "fixed dims"}
                        </span>
                        {provider.is_default ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                          >
                            default
                          </span>
                        ) : null}
                        {provider.is_active ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                          >
                            active
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-3 space-y-1 text-[11px] text-text-tertiary">
                        <div>
                          model:{" "}
                          <span className="font-mono text-text">
                            {provider.selected_model ?? "n/a"}
                          </span>
                          {provider.selected_dimensions
                            ? ` • ${provider.selected_dimensions}d`
                            : ""}
                        </div>
                        {provider.reason_label ? (
                          <div>{provider.reason_label}</div>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {(embeddingMigrationPreviews.length ?? 0) > 0 ? (
                <div className="mt-4">
                  <div className="text-sm font-medium text-text">
                    Migration matrix
                  </div>
                  <div className="mt-1 text-xs text-text-tertiary">
                    Cho biết nếu đổi sang model khác thì có thể save in-place
                    hay phải re-embed trước.
                  </div>
                  <div className="mt-3 space-y-2">
                    {embeddingMigrationPreviews.map((preview) => (
                      <div
                        key={`embedding-preview-${preview.target_model}`}
                        className={`rounded-xl border p-3 ${preview.target_model === draft.embedding_model ? "border-[var(--accent)]/40 bg-[var(--accent)]/5" : "border-border bg-surface-secondary"}`}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium text-text">
                              {preview.target_label}
                            </div>
                            <div className="text-[11px] font-mono text-text-tertiary">
                              {preview.target_model}
                            </div>
                          </div>
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(embeddingPreviewTone(preview))}`}
                          >
                            {embeddingPreviewLabel(preview)}
                          </span>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("neutral")}`}
                          >
                            {preview.target_provider}
                          </span>
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("neutral")}`}
                          >
                            {preview.target_dimensions}d
                          </span>
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(preview.same_space ? "accent" : "neutral")}`}
                          >
                            {preview.same_space ? "same space" : "new space"}
                          </span>
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(preview.target_backend_constructible ? "good" : "warn")}`}
                          >
                            {preview.target_backend_constructible
                              ? "backend ok"
                              : "backend missing"}
                          </span>
                          {preview.maintenance_required ? (
                            <span
                              className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("warn")}`}
                            >
                              maintenance
                            </span>
                          ) : null}
                        </div>
                        {preview.detail ? (
                          <div className="mt-2 text-[11px] text-text-tertiary">
                            {preview.detail}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                Embedding runtime audit này giúp nhìn rõ backend nào khả dụng,
                backend nào đang bị chặn, và lý do có liên quan đến key, local
                model hay không gian vector.
              </div>
              <div className="mt-3 rounded-xl border border-border bg-surface-secondary p-3 text-xs text-text-tertiary">
                Lưu ý: dimensions hiện chưa mở cho edit trong UI để tránh làm
                lệch schema pgvector và không gian vector đang sống.
              </div>
            </div>
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="text-sm font-medium text-text">Model catalog</div>
              <div className="mt-1 text-xs text-text-tertiary">
                Catalog backend cho biết model nào current, legacy, preset hoặc
                được discover runtime.
              </div>
              <div className="mt-4 space-y-4">
                {Object.entries(catalog?.providers ?? {}).map(
                  ([provider, entries]) => (
                    <div key={provider}>
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">
                          {provider}
                        </div>
                        {providerCapabilities[provider]?.configured ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("good")}`}
                          >
                            configured
                          </span>
                        ) : (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("warn")}`}
                          >
                            missing config
                          </span>
                        )}
                        {providerCapabilities[provider]?.request_selectable ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                          >
                            request switch
                          </span>
                        ) : null}
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("neutral")}`}
                        >
                          catalog{" "}
                          {providerCapabilities[provider]?.catalog_source ??
                            "static"}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("neutral")}`}
                        >
                          {providerCapabilities[provider]?.model_count ??
                            entries.length}{" "}
                          models
                        </span>
                        {providerCapabilities[provider]
                          ?.runtime_discovery_enabled ? (
                          <span
                            className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(providerCapabilities[provider]?.runtime_discovery_succeeded ? "good" : "warn")}`}
                          >
                            {providerCapabilities[provider]
                              ?.runtime_discovery_succeeded
                              ? "runtime discovery ok"
                              : "runtime discovery fail"}
                          </span>
                        ) : null}
                      </div>
                      <div className="mb-2 text-[11px] text-text-tertiary">
                        selected:{" "}
                        <span className="font-mono text-text">
                          {providerCapabilities[provider]?.selected_model ??
                            "n/a"}
                        </span>
                        {providerCapabilities[provider]
                          ?.selected_model_in_catalog === false
                          ? " (custom/off-catalog)"
                          : ""}
                        {providerCapabilities[provider]
                          ?.selected_model_advanced ? (
                          <>
                            {" • "}advanced:{" "}
                            <span className="font-mono text-text">
                              {
                                providerCapabilities[provider]
                                  ?.selected_model_advanced
                              }
                            </span>
                            {providerCapabilities[provider]
                              ?.selected_model_advanced_in_catalog === false
                              ? " (custom/off-catalog)"
                              : ""}
                          </>
                        ) : null}
                      </div>
                      <div className="mb-3 flex flex-wrap gap-2">
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(capabilityTone(providerCapabilities[provider]?.tool_calling_supported))}`}
                        >
                          tools{" "}
                          {formatCapabilityLabel(
                            providerCapabilities[provider]
                              ?.tool_calling_supported,
                          )}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(capabilityTone(providerCapabilities[provider]?.structured_output_supported))}`}
                        >
                          structured{" "}
                          {formatCapabilityLabel(
                            providerCapabilities[provider]
                              ?.structured_output_supported,
                          )}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(capabilityTone(providerCapabilities[provider]?.streaming_supported))}`}
                        >
                          streaming{" "}
                          {formatCapabilityLabel(
                            providerCapabilities[provider]?.streaming_supported,
                          )}
                        </span>
                      </div>
                      <div className="mb-3 space-y-1 text-[11px] text-text-tertiary">
                        <div>
                          context window:{" "}
                          <span className="font-medium text-text">
                            {providerCapabilities[provider]
                              ?.context_window_tokens
                              ? `${providerCapabilities[provider]?.context_window_tokens?.toLocaleString("vi-VN")} tokens`
                              : "unknown"}
                          </span>
                          {providerCapabilities[provider]?.context_window_source
                            ? ` • ${providerCapabilities[provider]?.context_window_source}`
                            : ""}
                        </div>
                        <div>
                          max output:{" "}
                          <span className="font-medium text-text">
                            {providerCapabilities[provider]?.max_output_tokens
                              ? `${providerCapabilities[provider]?.max_output_tokens?.toLocaleString("vi-VN")} tokens`
                              : "unknown"}
                          </span>
                          {providerCapabilities[provider]?.max_output_source
                            ? ` • ${providerCapabilities[provider]?.max_output_source}`
                            : ""}
                        </div>
                        <div>
                          discovery success:{" "}
                          {formatDateTime(
                            providerCapabilities[provider]
                              ?.last_discovery_success_at,
                          )}
                        </div>
                        <div>
                          live probe success:{" "}
                          {formatDateTime(
                            providerCapabilities[provider]
                              ?.last_live_probe_success_at,
                          )}
                        </div>
                      </div>
                      {providerCapabilities[provider]?.last_live_probe_error ? (
                        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
                          Live probe error:{" "}
                          {
                            providerCapabilities[provider]
                              ?.last_live_probe_error
                          }
                        </div>
                      ) : null}
                      {providerCapabilities[provider]?.degraded_reasons
                        ?.length ? (
                        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
                          {providerCapabilities[
                            provider
                          ]?.degraded_reasons.join(" ")}
                        </div>
                      ) : null}
                      <div className="space-y-2">
                        {entries.length === 0 ? (
                          <div className="rounded-xl border border-dashed border-border bg-surface-secondary px-3 py-3 text-xs text-text-tertiary">
                            Chưa có gợi ý model từ catalog này. Bạn vẫn có thể
                            nhập custom model id, hoặc bổ sung key/base URL để
                            backend thử discovery runtime.
                          </div>
                        ) : null}
                        {entries.slice(0, 4).map((entry) => (
                          <div
                            key={`${provider}:${entry.model_name}`}
                            className="rounded-xl border border-border bg-surface-secondary px-3 py-2"
                          >
                            <div className="text-sm font-medium text-text">
                              {entry.display_name}
                            </div>
                            <div className="mt-1 text-[11px] font-mono text-text-tertiary">
                              {entry.model_name}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <span
                                className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass(entry.status === "current" || entry.status === "available" ? "good" : entry.status === "legacy" ? "warn" : "neutral")}`}
                              >
                                {entry.status}
                              </span>
                              {entry.is_default && (
                                <span
                                  className={`rounded-full border px-2 py-1 text-[11px] ${badgeClass("accent")}`}
                                >
                                  selected
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ),
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
