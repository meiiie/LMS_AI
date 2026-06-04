import {
  applyLlmProviderPreset,
  CURRENT_GOOGLE_CHAT_MODELS,
  GOOGLE_DEFAULT_MODEL,
  NVIDIA_BASE_URL,
  NVIDIA_DEFAULT_MODEL,
  NVIDIA_DEFAULT_MODEL_ADVANCED,
  OPENAI_DEFAULT_MODEL,
  OPENAI_DEFAULT_MODEL_ADVANCED,
  ZHIPU_DEFAULT_BASE_URL,
  ZHIPU_DEFAULT_MODEL,
} from "@/lib/llm-presets";

describe("llm presets", () => {
  it("keeps the Google default aligned with the current model catalog", () => {
    expect(GOOGLE_DEFAULT_MODEL).toBe("gemini-3.1-flash-lite-preview");
    expect(CURRENT_GOOGLE_CHAT_MODELS).toContain(GOOGLE_DEFAULT_MODEL);
  });

  it("applies the Google preset when no runtime override exists", () => {
    const updated = applyLlmProviderPreset({}, "google");

    expect(updated.llm_provider).toBe("google");
    expect(updated.google_model).toBe(GOOGLE_DEFAULT_MODEL);
  });

  it("applies the Zhipu preset with current runtime defaults", () => {
    const updated = applyLlmProviderPreset({}, "zhipu");

    expect(updated.llm_provider).toBe("zhipu");
    expect(updated.zhipu_base_url).toBe(ZHIPU_DEFAULT_BASE_URL);
    expect(updated.zhipu_model).toBe(ZHIPU_DEFAULT_MODEL);
    expect(updated.zhipu_model_advanced).toBe("glm-5");
    expect(updated.llm_failover_chain).toContain("google");
  });

  it("applies dedicated OpenAI defaults instead of OpenRouter presets", () => {
    const updated = applyLlmProviderPreset({}, "openai");

    expect(updated.llm_provider).toBe("openai");
    expect(updated.openai_model).toBe(OPENAI_DEFAULT_MODEL);
    expect(updated.openai_model_advanced).toBe(OPENAI_DEFAULT_MODEL_ADVANCED);
  });

  it("applies NVIDIA as a first-class OpenAI-compatible provider", () => {
    const updated = applyLlmProviderPreset({}, "nvidia");

    expect(updated.llm_provider).toBe("nvidia");
    expect(updated.nvidia_base_url).toBe(NVIDIA_BASE_URL);
    expect(updated.nvidia_model).toBe(NVIDIA_DEFAULT_MODEL);
    expect(updated.nvidia_model_advanced).toBe(NVIDIA_DEFAULT_MODEL_ADVANCED);
    expect(updated.llm_failover_chain).toContain("nvidia");
  });
});
