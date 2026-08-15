import type { AppSettings } from "@/api/types";

export type LlmProvider = "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";

export const GOOGLE_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview";
export const OPENAI_DEFAULT_MODEL = "gpt-5.4-mini";
export const OPENAI_DEFAULT_MODEL_ADVANCED = "gpt-5.4";
export const CURRENT_GOOGLE_CHAT_MODELS = [GOOGLE_DEFAULT_MODEL] as const;
export const GOOGLE_LEGACY_MODELS = [
  "gemini-2.5-flash",
  "gemini-2.5-pro",
  "gemini-2.0-flash",
  "gemini-2.0-flash-exp",
] as const;
export const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";
export const OPENROUTER_DEFAULT_MODEL = "openai/gpt-oss-20b:free";
export const OPENROUTER_DEFAULT_MODEL_ADVANCED = "openai/gpt-oss-120b:free";
export const NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1";
export const NVIDIA_DEFAULT_MODEL = "qwen/qwen3-next-80b-a3b-instruct";
export const NVIDIA_DEFAULT_MODEL_ADVANCED = "qwen/qwen3-next-80b-a3b-thinking";
export const ZHIPU_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4";
export const ZHIPU_DEFAULT_MODEL = "glm-4.5-air";
export const ZHIPU_DEFAULT_MODEL_ADVANCED = "glm-5";
// Current verified local-dev default: backend Docker container -> native host Ollama.
// If backend runs outside Docker, switch this to http://localhost:11434 in runtime config.
export const OLLAMA_DEFAULT_BASE_URL = "http://host.docker.internal:11434";
export const OLLAMA_DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M";
export const OLLAMA_DEFAULT_KEEP_ALIVE = "30m";

type LlmProviderPreset = {
  provider: LlmProvider;
  llm_failover_chain: string[];
  google_model?: string;
  openai_base_url?: string;
  openai_model?: string;
  openai_model_advanced?: string;
  openrouter_base_url?: string;
  openrouter_model?: string;
  openrouter_model_advanced?: string;
  nvidia_base_url?: string;
  nvidia_model?: string;
  nvidia_model_advanced?: string;
  zhipu_base_url?: string;
  zhipu_model?: string;
  zhipu_model_advanced?: string;
  ollama_base_url?: string;
  ollama_model?: string;
  ollama_keep_alive?: string;
};

const PRESETS: Record<LlmProvider, LlmProviderPreset> = {
  google: {
    provider: "google",
    llm_failover_chain: ["google", "zhipu", "ollama", "openrouter"],
    google_model: GOOGLE_DEFAULT_MODEL,
  },
  zhipu: {
    provider: "zhipu",
    llm_failover_chain: ["zhipu", "google", "openrouter", "ollama"],
    zhipu_base_url: ZHIPU_DEFAULT_BASE_URL,
    zhipu_model: ZHIPU_DEFAULT_MODEL,
    zhipu_model_advanced: ZHIPU_DEFAULT_MODEL_ADVANCED,
  },
  openai: {
    provider: "openai",
    llm_failover_chain: ["openai", "google", "zhipu", "ollama"],
    openai_model: OPENAI_DEFAULT_MODEL,
    openai_model_advanced: OPENAI_DEFAULT_MODEL_ADVANCED,
  },
  openrouter: {
    provider: "openrouter",
    llm_failover_chain: ["openrouter", "google", "zhipu", "ollama"],
    openrouter_base_url: OPENROUTER_BASE_URL,
    openrouter_model: OPENROUTER_DEFAULT_MODEL,
    openrouter_model_advanced: OPENROUTER_DEFAULT_MODEL_ADVANCED,
  },
  nvidia: {
    provider: "nvidia",
    llm_failover_chain: ["nvidia", "google", "zhipu", "openrouter", "ollama"],
    nvidia_base_url: NVIDIA_BASE_URL,
    nvidia_model: NVIDIA_DEFAULT_MODEL,
    nvidia_model_advanced: NVIDIA_DEFAULT_MODEL_ADVANCED,
  },
  ollama: {
    provider: "ollama",
    llm_failover_chain: ["ollama", "google", "zhipu", "openrouter"],
    ollama_base_url: OLLAMA_DEFAULT_BASE_URL,
    ollama_model: OLLAMA_DEFAULT_MODEL,
    ollama_keep_alive: OLLAMA_DEFAULT_KEEP_ALIVE,
  },
};

export function getLlmPreset(provider: LlmProvider): LlmProviderPreset {
  return PRESETS[provider];
}

export function applyLlmProviderPreset(
  current: Partial<AppSettings>,
  provider: LlmProvider
): Partial<AppSettings> {
  const preset = getLlmPreset(provider);
  return {
    ...current,
    llm_provider: provider,
    google_model: preset.google_model ?? current.google_model ?? GOOGLE_DEFAULT_MODEL,
    openai_base_url: preset.openai_base_url ?? current.openai_base_url ?? "",
    openai_model:
      preset.openai_model ?? current.openai_model ?? OPENAI_DEFAULT_MODEL,
    openai_model_advanced:
      preset.openai_model_advanced
      ?? current.openai_model_advanced
      ?? OPENAI_DEFAULT_MODEL_ADVANCED,
    openrouter_base_url:
      preset.openrouter_base_url ?? current.openrouter_base_url ?? OPENROUTER_BASE_URL,
    openrouter_model:
      preset.openrouter_model ?? current.openrouter_model ?? OPENROUTER_DEFAULT_MODEL,
    openrouter_model_advanced:
      preset.openrouter_model_advanced
      ?? current.openrouter_model_advanced
      ?? OPENROUTER_DEFAULT_MODEL_ADVANCED,
    nvidia_base_url:
      preset.nvidia_base_url ?? current.nvidia_base_url ?? NVIDIA_BASE_URL,
    nvidia_model:
      preset.nvidia_model ?? current.nvidia_model ?? NVIDIA_DEFAULT_MODEL,
    nvidia_model_advanced:
      preset.nvidia_model_advanced
      ?? current.nvidia_model_advanced
      ?? NVIDIA_DEFAULT_MODEL_ADVANCED,
    zhipu_base_url:
      preset.zhipu_base_url ?? current.zhipu_base_url ?? ZHIPU_DEFAULT_BASE_URL,
    zhipu_model:
      preset.zhipu_model ?? current.zhipu_model ?? ZHIPU_DEFAULT_MODEL,
    zhipu_model_advanced:
      preset.zhipu_model_advanced
      ?? current.zhipu_model_advanced
      ?? ZHIPU_DEFAULT_MODEL_ADVANCED,
    ollama_base_url:
      preset.ollama_base_url ?? current.ollama_base_url ?? OLLAMA_DEFAULT_BASE_URL,
    ollama_model:
      preset.ollama_model ?? current.ollama_model ?? OLLAMA_DEFAULT_MODEL,
    ollama_keep_alive:
      preset.ollama_keep_alive
      ?? current.ollama_keep_alive
      ?? OLLAMA_DEFAULT_KEEP_ALIVE,
    llm_failover_chain: preset.llm_failover_chain,
  };
}
