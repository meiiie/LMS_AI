import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LlmRuntimeTab } from "@/components/admin/LlmRuntimeTab";
import { useAdminStore } from "@/stores/admin-store";
import type { LlmRuntimeConfig, ModelCatalogResponse } from "@/api/types";

vi.mock("@/api/admin", () => ({
  getLlmRuntimeConfig: vi.fn(),
  getModelCatalog: vi.fn(),
  planEmbeddingSpaceMigration: vi.fn(),
  promoteEmbeddingSpaceMigration: vi.fn(),
  refreshLlmRuntimeAudit: vi.fn(),
  refreshVisionRuntimeAudit: vi.fn(),
  runEmbeddingSpaceMigration: vi.fn(),
  updateLlmRuntimeConfig: vi.fn(),
}));

const runtimeFixture: LlmRuntimeConfig = {
  provider: "google",
  use_multi_agent: true,
  google_model: "gemini-3.1-flash-lite-preview",
  openai_base_url: "https://api.openai.com/v1",
  openai_model: "gpt-5.4-mini",
  openai_model_advanced: "gpt-5.4",
  openrouter_base_url: "https://openrouter.ai/api/v1",
  openrouter_model: "openai/gpt-oss-20b:free",
  openrouter_model_advanced: "openai/gpt-oss-120b:free",
  zhipu_base_url: "https://open.bigmodel.cn/api/paas/v4",
  zhipu_model: "glm-5",
  zhipu_model_advanced: "glm-5",
  openrouter_model_fallbacks: [],
  openrouter_provider_order: [],
  openrouter_allowed_providers: [],
  openrouter_ignored_providers: [],
  openrouter_allow_fallbacks: true,
  openrouter_require_parameters: null,
  openrouter_data_collection: "deny",
  openrouter_zdr: true,
  openrouter_provider_sort: "latency",
  ollama_base_url: "http://localhost:11434",
  ollama_model: "qwen3:8b",
  ollama_keep_alive: "30m",
  google_api_key_configured: true,
  openai_api_key_configured: false,
  openrouter_api_key_configured: false,
  zhipu_api_key_configured: true,
  ollama_api_key_configured: false,
  enable_llm_failover: true,
  llm_failover_chain: ["google", "zhipu", "ollama"],
  active_provider: "google",
  providers_registered: ["google", "zhipu", "ollama"],
  request_selectable_providers: ["google", "zhipu", "ollama"],
  provider_status: [
    {
      provider: "google",
      display_name: "Google Gemini",
      configured: true,
      available: true,
      registered: true,
      request_selectable: true,
      in_failover_chain: true,
      is_default: true,
      is_active: true,
      configurable_via_admin: true,
    },
    {
      provider: "zhipu",
      display_name: "Zhipu GLM",
      configured: true,
      available: true,
      registered: true,
      request_selectable: true,
      in_failover_chain: true,
      is_default: false,
      is_active: false,
      configurable_via_admin: true,
    },
  ],
  agent_profiles: {
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
  },
  timeout_profiles: {
    light_seconds: 12,
    moderate_seconds: 25,
    deep_seconds: 45,
    structured_seconds: 60,
    background_seconds: 0,
    stream_keepalive_interval_seconds: 15,
    stream_idle_timeout_seconds: 0,
  },
  timeout_provider_overrides: {
    google: { deep_seconds: 55 },
  },
  vision_provider: "auto",
  vision_describe_provider: "auto",
  vision_describe_model: "qwen/qwen2.5-vl-7b-instruct",
  vision_ocr_provider: "auto",
  vision_ocr_model: "glm-ocr",
  vision_grounded_provider: "auto",
  vision_grounded_model: "qwen/qwen2.5-vl-32b-instruct",
  vision_failover_chain: ["google", "openai", "ollama"],
  vision_timeout_seconds: 40,
  vision_audit_updated_at: "2026-03-23T08:06:00Z",
  vision_last_live_probe_at: "2026-03-23T08:05:00Z",
  vision_audit_persisted: true,
  vision_audit_warnings: [],
  vision_provider_status: [
    {
      provider: "google",
      display_name: "Gemini Vision",
      configured: true,
      available: true,
      in_failover_chain: true,
      is_default: true,
      is_active: true,
      selected_model: "gemini-3.1-flash-lite-preview",
      reason_code: null,
      reason_label: null,
      last_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_probe_success_at: "2026-03-23T08:05:00Z",
      last_probe_error: null,
      last_runtime_observation_at: "2026-03-23T08:06:00Z",
      last_runtime_success_at: "2026-03-23T08:06:00Z",
      last_runtime_error: null,
      last_runtime_note: "General vision runtime da chay that.",
      last_runtime_source: "runtime_call",
      degraded: false,
      degraded_reasons: [],
      capabilities: [
        {
          capability: "visual_describe",
          display_name: "Mo ta anh",
          available: true,
          selected_model: "gemini-3.1-flash-lite-preview",
          lane_fit: "general",
          lane_fit_label: "General vision",
          reason_code: null,
          reason_label: null,
          resolved_base_url: null,
          last_probe_attempt_at: "2026-03-23T08:05:00Z",
          last_probe_success_at: "2026-03-23T08:05:00Z",
          last_probe_error: null,
          live_probe_note: "Mo ta hop le.",
          last_runtime_observation_at: "2026-03-23T08:06:00Z",
          last_runtime_success_at: "2026-03-23T08:06:00Z",
          last_runtime_error: null,
          last_runtime_note: "Runtime describe call thanh cong.",
          last_runtime_source: "runtime_call",
        },
      ],
    },
    {
      provider: "ollama",
      display_name: "Ollama Vision",
      configured: true,
      available: false,
      in_failover_chain: true,
      is_default: false,
      is_active: false,
      selected_model: "llava:latest",
      reason_code: "model_missing",
      reason_label: "Model vision local chua duoc cai tren Ollama.",
      last_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_probe_success_at: null,
      last_probe_error:
        "ocr_extract: Model vision local chua duoc cai tren Ollama.",
      last_runtime_observation_at: null,
      last_runtime_success_at: null,
      last_runtime_error: null,
      last_runtime_note: null,
      last_runtime_source: null,
      degraded: true,
      degraded_reasons: [
        "ocr_extract: Model vision local chua duoc cai tren Ollama.",
      ],
      recovered: false,
      recovered_reasons: [],
      capabilities: [
        {
          capability: "ocr_extract",
          display_name: "OCR / trich xuat",
          available: false,
          selected_model: "llava:latest",
          lane_fit: "fallback",
          lane_fit_label: "OCR fallback",
          reason_code: "model_missing",
          reason_label: "Model vision local chua duoc cai tren Ollama.",
          resolved_base_url: null,
          last_probe_attempt_at: "2026-03-23T08:05:00Z",
          last_probe_success_at: null,
          last_probe_error: "Model vision local chua duoc cai tren Ollama.",
          live_probe_note: null,
          last_runtime_observation_at: null,
          last_runtime_success_at: null,
          last_runtime_error: null,
          last_runtime_note: null,
          last_runtime_source: null,
          recovered: false,
          recovered_label: null,
        },
      ],
    },
    {
      provider: "zhipu",
      display_name: "Zhipu Vision",
      configured: true,
      available: true,
      in_failover_chain: true,
      is_default: false,
      is_active: false,
      selected_model: "glm-ocr",
      reason_code: null,
      reason_label: null,
      last_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_probe_success_at: null,
      last_probe_error: "ocr_extract: Provider tam thoi khong kha dung.",
      last_runtime_observation_at: "2026-03-23T08:06:00Z",
      last_runtime_success_at: "2026-03-23T08:06:00Z",
      last_runtime_error: null,
      last_runtime_note: "OCR runtime da hoi phuc.",
      last_runtime_source: "runtime_call",
      degraded: true,
      degraded_reasons: ["ocr_extract: Provider tam thoi khong kha dung."],
      recovered: true,
      recovered_reasons: ["OCR / trich xuat"],
      capabilities: [
        {
          capability: "ocr_extract",
          display_name: "OCR / trich xuat",
          available: true,
          selected_model: "glm-ocr",
          lane_fit: "specialist",
          lane_fit_label: "OCR specialist",
          reason_code: null,
          reason_label: null,
          resolved_base_url: "https://open.bigmodel.cn/api/paas/v4",
          last_probe_attempt_at: "2026-03-23T08:05:00Z",
          last_probe_success_at: null,
          last_probe_error: "Provider tam thoi khong kha dung.",
          live_probe_note: null,
          last_runtime_observation_at: "2026-03-23T08:06:00Z",
          last_runtime_success_at: "2026-03-23T08:06:00Z",
          last_runtime_error: null,
          last_runtime_note: "OCR runtime da hoi phuc.",
          last_runtime_source: "runtime_call",
          recovered: true,
          recovered_label: "Runtime da hoi phuc sau probe",
        },
      ],
    },
  ],
  embedding_provider: "auto",
  embedding_failover_chain: ["google", "openai", "ollama"],
  embedding_model: "models/gemini-embedding-001",
  embedding_dimensions: 768,
  embedding_status: "stable",
  embedding_provider_status: [
    {
      provider: "google",
      display_name: "Gemini Embeddings",
      configured: true,
      available: true,
      in_failover_chain: true,
      is_default: true,
      is_active: true,
      selected_model: "models/gemini-embedding-001",
      selected_dimensions: 768,
      supports_dimension_override: true,
      reason_code: null,
      reason_label: null,
    },
    {
      provider: "ollama",
      display_name: "Ollama Embeddings",
      configured: true,
      available: false,
      in_failover_chain: true,
      is_default: false,
      is_active: false,
      selected_model: "embeddinggemma",
      selected_dimensions: 768,
      supports_dimension_override: false,
      reason_code: "model_missing",
      reason_label: "Model embedding local chua duoc cai tren Ollama.",
    },
  ],
  embedding_space_status: {
    audit_available: true,
    policy_contract: {
      provider: "google",
      model: "models/gemini-embedding-001",
      dimensions: 768,
      fingerprint: "google:models/gemini-embedding-001:768",
      label: "Gemini Embedding 001 [google, 768d]",
    },
    active_contract: {
      provider: "google",
      model: "models/gemini-embedding-001",
      dimensions: 768,
      fingerprint: "google:models/gemini-embedding-001:768",
      label: "Gemini Embedding 001 [google, 768d]",
    },
    active_matches_policy: true,
    total_embedded_rows: 5,
    total_tracked_rows: 5,
    total_untracked_rows: 0,
    tables: [
      {
        table_name: "semantic_memories",
        embedded_row_count: 3,
        tracked_row_count: 3,
        untracked_row_count: 0,
        fingerprints: {
          "google:models/gemini-embedding-001:768": 3,
        },
      },
      {
        table_name: "knowledge_embeddings",
        embedded_row_count: 2,
        tracked_row_count: 2,
        untracked_row_count: 0,
        fingerprints: {
          "google:models/gemini-embedding-001:768": 2,
        },
      },
    ],
    warnings: [],
    error: null,
  },
  embedding_migration_previews: [
    {
      target_model: "models/gemini-embedding-001",
      target_provider: "google",
      target_dimensions: 768,
      target_label: "Gemini Embedding 001",
      target_status: "stable",
      same_space: true,
      allowed: true,
      requires_reembed: false,
      target_backend_constructible: true,
      maintenance_required: false,
      embedded_row_count: 5,
      blocking_tables: [],
      mixed_tables: [],
      warnings: [],
      recommended_steps: ["noop"],
      detail: null,
    },
    {
      target_model: "text-embedding-3-small",
      target_provider: "openai",
      target_dimensions: 1536,
      target_label: "OpenAI Text Embedding 3 Small",
      target_status: "current",
      same_space: false,
      allowed: false,
      requires_reembed: true,
      target_backend_constructible: false,
      maintenance_required: true,
      embedded_row_count: 5,
      blocking_tables: ["semantic_memories=3", "knowledge_embeddings=2"],
      mixed_tables: [],
      warnings: [],
      recommended_steps: ["maintenance"],
      detail:
        "Khong the doi embedding model in-place khi vector index van co du lieu song.",
    },
  ],
  runtime_policy_persisted: true,
  runtime_policy_updated_at: "2026-03-22T08:30:00Z",
  warnings: [],
};

const catalogFixture: ModelCatalogResponse = {
  providers: {
    google: [
      {
        provider: "google",
        model_name: "gemini-3.1-flash-lite-preview",
        display_name: "Gemini 3.1 Flash-Lite Preview",
        status: "current",
        released_on: "2026-03-03",
        is_default: true,
      },
    ],
    openai: [
      {
        provider: "openai",
        model_name: "gpt-5.4-mini",
        display_name: "GPT-5.4 Mini",
        status: "current",
        released_on: null,
        is_default: false,
      },
    ],
    openrouter: [
      {
        provider: "openrouter",
        model_name: "openai/gpt-oss-20b:free",
        display_name: "GPT-OSS 20B",
        status: "preset",
        released_on: null,
        is_default: true,
      },
    ],
    zhipu: [
      {
        provider: "zhipu",
        model_name: "glm-5",
        display_name: "GLM-5",
        status: "current",
        released_on: "2026-03",
        is_default: false,
      },
    ],
    ollama: [
      {
        provider: "ollama",
        model_name: "qwen3:8b",
        display_name: "Qwen3 8B",
        status: "available",
        released_on: null,
        is_default: true,
      },
    ],
  },
  embedding_models: [
    {
      provider: "google",
      model_name: "models/gemini-embedding-001",
      display_name: "Gemini Embedding 001",
      status: "stable",
      released_on: null,
      is_default: true,
    },
  ],
  provider_capabilities: {
    google: {
      provider: "google",
      display_name: "Google Gemini",
      configured: true,
      available: true,
      request_selectable: true,
      configurable_via_admin: true,
      supports_runtime_discovery: true,
      runtime_discovery_enabled: true,
      runtime_discovery_succeeded: true,
      catalog_source: "mixed",
      model_count: 4,
      discovered_model_count: 2,
      selected_model: "gemini-3.1-flash-lite-preview",
      selected_model_in_catalog: true,
      selected_model_advanced: null,
      selected_model_advanced_in_catalog: false,
      last_discovery_attempt_at: "2026-03-23T08:00:00Z",
      last_discovery_success_at: "2026-03-23T08:00:00Z",
      last_live_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_live_probe_success_at: "2026-03-23T08:05:00Z",
      last_live_probe_error: "provider probe: quota_or_rate_limited (429)",
      live_probe_note: "Live probe passed.",
      last_runtime_observation_at: "2026-03-23T08:06:00Z",
      last_runtime_success_at: "2026-03-23T08:06:00Z",
      last_runtime_error: null,
      last_runtime_note:
        "chat_sync: completed via google/gemini-3.1-flash-lite-preview.",
      last_runtime_source: "chat_sync",
      degraded: false,
      degraded_reasons: [],
      recovered: true,
      recovered_reasons: ["Runtime da hoi phuc sau live probe"],
      tool_calling_supported: true,
      tool_calling_source: "live_probe",
      structured_output_supported: true,
      structured_output_source: "live_probe",
      streaming_supported: true,
      streaming_source: "live_probe",
      context_window_tokens: 1048576,
      context_window_source: "runtime",
      max_output_tokens: 65536,
      max_output_source: "runtime",
    },
    openai: {
      provider: "openai",
      display_name: "OpenAI-Compatible",
      configured: false,
      available: false,
      request_selectable: false,
      configurable_via_admin: true,
      supports_runtime_discovery: true,
      runtime_discovery_enabled: false,
      runtime_discovery_succeeded: false,
      catalog_source: "static",
      model_count: 1,
      discovered_model_count: 0,
      selected_model: "openai/gpt-oss-20b:free",
      selected_model_in_catalog: false,
      selected_model_advanced: "openai/gpt-oss-120b:free",
      selected_model_advanced_in_catalog: false,
      last_discovery_attempt_at: null,
      last_discovery_success_at: null,
      last_live_probe_attempt_at: null,
      last_live_probe_success_at: null,
      last_live_probe_error: null,
      live_probe_note:
        "Shared OpenAI-compatible slot is currently targeting openrouter, not openai.",
      degraded: false,
      degraded_reasons: [],
      last_runtime_observation_at: null,
      last_runtime_success_at: null,
      last_runtime_error: null,
      last_runtime_note: null,
      last_runtime_source: null,
      recovered: false,
      recovered_reasons: [],
      tool_calling_supported: null,
      tool_calling_source: null,
      structured_output_supported: null,
      structured_output_source: null,
      streaming_supported: null,
      streaming_source: null,
      context_window_tokens: null,
      context_window_source: null,
      max_output_tokens: null,
      max_output_source: null,
    },
    zhipu: {
      provider: "zhipu",
      display_name: "Zhipu GLM",
      configured: true,
      available: true,
      request_selectable: true,
      configurable_via_admin: true,
      supports_runtime_discovery: true,
      runtime_discovery_enabled: true,
      runtime_discovery_succeeded: true,
      catalog_source: "mixed",
      model_count: 2,
      discovered_model_count: 1,
      selected_model: "glm-5",
      selected_model_in_catalog: true,
      selected_model_advanced: "glm-5",
      selected_model_advanced_in_catalog: true,
      last_discovery_attempt_at: "2026-03-23T08:00:00Z",
      last_discovery_success_at: "2026-03-23T08:00:00Z",
      last_live_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_live_probe_success_at: "2026-03-23T08:05:00Z",
      last_live_probe_error: null,
      live_probe_note: "Live probe passed.",
      degraded: false,
      degraded_reasons: [],
      last_runtime_observation_at: "2026-03-23T08:06:30Z",
      last_runtime_success_at: "2026-03-23T08:06:30Z",
      last_runtime_error: null,
      last_runtime_note: "chat_stream: completed via zhipu/glm-5.",
      last_runtime_source: "chat_stream",
      recovered: false,
      recovered_reasons: [],
      tool_calling_supported: true,
      tool_calling_source: "live_probe",
      structured_output_supported: true,
      structured_output_source: "live_probe",
      streaming_supported: true,
      streaming_source: "live_probe",
      context_window_tokens: 200000,
      context_window_source: "static",
      max_output_tokens: 128000,
      max_output_source: "static",
    },
    openrouter: {
      provider: "openrouter",
      display_name: "OpenRouter",
      configured: false,
      available: false,
      request_selectable: false,
      configurable_via_admin: true,
      supports_runtime_discovery: true,
      runtime_discovery_enabled: false,
      runtime_discovery_succeeded: false,
      catalog_source: "static",
      model_count: 1,
      discovered_model_count: 0,
      selected_model: "openai/gpt-oss-20b:free",
      selected_model_in_catalog: true,
      selected_model_advanced: "openai/gpt-oss-120b:free",
      selected_model_advanced_in_catalog: true,
      last_discovery_attempt_at: "2026-03-23T08:00:00Z",
      last_discovery_success_at: "2026-03-23T08:00:00Z",
      last_live_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_live_probe_success_at: "2026-03-23T08:05:00Z",
      last_live_probe_error: null,
      live_probe_note: "Live probe passed.",
      degraded: false,
      degraded_reasons: [],
      last_runtime_observation_at: null,
      last_runtime_success_at: null,
      last_runtime_error: null,
      last_runtime_note: null,
      last_runtime_source: null,
      recovered: false,
      recovered_reasons: [],
      tool_calling_supported: true,
      tool_calling_source: "live_probe",
      structured_output_supported: false,
      structured_output_source: "live_probe",
      streaming_supported: true,
      streaming_source: "live_probe",
      context_window_tokens: null,
      context_window_source: null,
      max_output_tokens: null,
      max_output_source: null,
    },
    ollama: {
      provider: "ollama",
      display_name: "Ollama",
      configured: false,
      available: false,
      request_selectable: true,
      configurable_via_admin: true,
      supports_runtime_discovery: true,
      runtime_discovery_enabled: true,
      runtime_discovery_succeeded: false,
      catalog_source: "mixed",
      model_count: 2,
      discovered_model_count: 1,
      selected_model: "qwen3:8b",
      selected_model_in_catalog: true,
      selected_model_advanced: null,
      selected_model_advanced_in_catalog: false,
      last_discovery_attempt_at: "2026-03-23T08:00:00Z",
      last_discovery_success_at: null,
      last_live_probe_attempt_at: "2026-03-23T08:05:00Z",
      last_live_probe_success_at: null,
      last_live_probe_error: "connect timeout",
      live_probe_note: "Live probe failed.",
      degraded: true,
      degraded_reasons: [
        "Runtime discovery that current provider slot failed.",
        "Live capability probe failed.",
      ],
      last_runtime_observation_at: null,
      last_runtime_success_at: null,
      last_runtime_error: null,
      last_runtime_note: null,
      last_runtime_source: null,
      recovered: false,
      recovered_reasons: [],
      tool_calling_supported: null,
      tool_calling_source: null,
      structured_output_supported: null,
      structured_output_source: null,
      streaming_supported: true,
      streaming_source: "static",
      context_window_tokens: 32768,
      context_window_source: "runtime",
      max_output_tokens: null,
      max_output_source: null,
    },
  },
  ollama_discovered: true,
  audit_updated_at: "2026-03-23T08:05:00Z",
  last_live_probe_at: "2026-03-23T08:05:00Z",
  degraded_providers: ["ollama"],
  audit_persisted: true,
  audit_warnings: [],
  timestamp: "2026-03-22T08:00:00Z",
};

describe("LlmRuntimeTab", () => {
  beforeEach(async () => {
    useAdminStore.getState().reset();
    vi.clearAllMocks();

    const adminApi = await import("@/api/admin");
    vi.mocked(adminApi.getLlmRuntimeConfig).mockResolvedValue(runtimeFixture);
    vi.mocked(adminApi.getModelCatalog).mockResolvedValue(catalogFixture);
    vi.mocked(adminApi.refreshLlmRuntimeAudit).mockResolvedValue(
      catalogFixture,
    );
    vi.mocked(adminApi.refreshVisionRuntimeAudit).mockResolvedValue(
      runtimeFixture,
    );
    vi.mocked(adminApi.updateLlmRuntimeConfig).mockResolvedValue(
      runtimeFixture,
    );
  });

  it("loads runtime truth and provider status cards", async () => {
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getAllByText("Google Gemini").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("Runtime và Model Policy")).toBeTruthy();
    expect(screen.getByText("Vision runtime")).toBeTruthy();
    expect(screen.getByText("Embedding hiện tại")).toBeTruthy();
    expect(screen.getAllByText("Zhipu GLM").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Gemini Vision").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Model vision local chua duoc cai tren Ollama.")
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("General vision")).toBeTruthy();
    expect(screen.getByText("OCR fallback")).toBeTruthy();
    expect(screen.getAllByText("recovered").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "chat_sync: completed via google/gemini-3.1-flash-lite-preview.",
      ),
    ).toBeTruthy();
    expect(screen.getByText(/Runtime recovered:/i)).toBeTruthy();
    expect(screen.getByText(/runtime recovered on:/i)).toBeTruthy();
    expect(screen.getByText("Runtime da hoi phuc sau probe")).toBeTruthy();
    expect(screen.getAllByText(/runtime success:/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Runtime describe call thanh cong.")).toBeTruthy();
    expect(
      screen.getAllByText("models/gemini-embedding-001").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Ollama Embeddings").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Model embedding local chua duoc cai tren Ollama."),
    ).toBeTruthy();
    expect(screen.getByText("Embedding space health")).toBeTruthy();
    expect(screen.getByText("Migration matrix")).toBeTruthy();
    expect(screen.getAllByText("same space").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Đã lưu vào system DB/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText(/Live probe gần nhất/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText(/Mo ta hop le./i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/degraded/i).length).toBeGreaterThan(0);
  });

  it("normalizes failover chain before saving", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("google, zhipu, ollama")).toBeTruthy();
    });

    const failoverInput = screen.getByDisplayValue("google, zhipu, ollama");
    fireEvent.change(failoverInput, {
      target: { value: "google, zhipu, ollama,  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu policy" }));

    await waitFor(() => {
      expect(adminApi.updateLlmRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          llm_failover_chain: ["google", "zhipu", "ollama"],
        }),
      );
    });
  });

  it("saves timeout profiles and provider overrides", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("12")).toBeTruthy();
    });

    fireEvent.change(screen.getByDisplayValue("45"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByDisplayValue("55"), {
      target: { value: "70" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu policy" }));

    await waitFor(() => {
      expect(adminApi.updateLlmRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          timeout_profiles: expect.objectContaining({
            deep_seconds: 50,
          }),
          timeout_provider_overrides: expect.objectContaining({
            google: expect.objectContaining({
              deep_seconds: 70,
            }),
          }),
        }),
      );
    });
  });

  it("saves embedding provider policy", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByTestId("runtime-embedding-provider")).toBeTruthy();
    });

    fireEvent.change(screen.getByTestId("runtime-embedding-provider"), {
      target: { value: "ollama" },
    });
    fireEvent.change(screen.getByTestId("runtime-embedding-failover-chain"), {
      target: { value: "ollama, google" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu policy" }));

    await waitFor(() => {
      expect(adminApi.updateLlmRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          embedding_provider: "ollama",
          embedding_failover_chain: ["ollama", "google"],
          embedding_model: "embeddinggemma",
        }),
      );
    });
  });

  it("saves vision provider policy", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByTestId("runtime-vision-provider")).toBeTruthy();
    });

    fireEvent.change(screen.getByTestId("runtime-vision-provider"), {
      target: { value: "openai" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-failover-chain"), {
      target: { value: "openai, google" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-timeout"), {
      target: { value: "55" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu policy" }));

    await waitFor(() => {
      expect(adminApi.updateLlmRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          vision_provider: "openai",
          vision_failover_chain: ["openai", "google"],
          vision_timeout_seconds: 55,
        }),
      );
    });
  });

  it("saves capability-specific vision lanes", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByTestId("runtime-vision-ocr-provider")).toBeTruthy();
    });

    fireEvent.change(screen.getByTestId("runtime-vision-describe-provider"), {
      target: { value: "openrouter" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-describe-model"), {
      target: { value: "qwen/qwen2.5-vl-7b-instruct" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-ocr-provider"), {
      target: { value: "zhipu" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-ocr-model"), {
      target: { value: "glm-ocr" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-grounded-provider"), {
      target: { value: "openrouter" },
    });
    fireEvent.change(screen.getByTestId("runtime-vision-grounded-model"), {
      target: { value: "qwen/qwen2.5-vl-32b-instruct" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu policy" }));

    await waitFor(() => {
      expect(adminApi.updateLlmRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          vision_describe_provider: "openrouter",
          vision_describe_model: "qwen/qwen2.5-vl-7b-instruct",
          vision_ocr_provider: "zhipu",
          vision_ocr_model: "glm-ocr",
          vision_grounded_provider: "openrouter",
          vision_grounded_model: "qwen/qwen2.5-vl-32b-instruct",
        }),
      );
    });
  });

  it("runs live probe from admin button", async () => {
    const adminApi = await import("@/api/admin");
    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Probe capability" }),
      ).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Probe capability" }));

    await waitFor(() => {
      expect(adminApi.refreshLlmRuntimeAudit).toHaveBeenCalledWith({});
      expect(adminApi.refreshVisionRuntimeAudit).toHaveBeenCalledWith({});
    });
  });

  it("shows audit storage warnings when live probe is not persisted", async () => {
    const adminApi = await import("@/api/admin");
    vi.mocked(adminApi.getModelCatalog).mockResolvedValue({
      ...catalogFixture,
      audit_persisted: false,
      audit_warnings: [
        "Could not persist LLM runtime audit to admin_runtime_settings.",
      ],
    });

    render(<LlmRuntimeTab />);

    await waitFor(() => {
      expect(screen.getByText(/Đang hiển thị kết quả tạm thời/i)).toBeTruthy();
    });

    expect(
      screen.getByText(/Could not persist LLM runtime audit/i),
    ).toBeTruthy();
  });
});
