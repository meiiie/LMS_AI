import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyWiiiConnectFacebookPost,
  buildWiiiConnectProviderCallbackUrl,
  createWiiiConnectProviderAuthorizationUrl,
  disconnectWiiiConnectProviderConnection,
  fetchWiiiConnectFacebookPages,
  fetchRecentRuntimeFlowDoctor,
  fetchRecentSemanticMemoryDoctor,
  fetchRuntimeFlowDoctorHistory,
  fetchSemanticMemoryDoctorHistory,
  fetchWiiiConnectDoctor,
  fetchWiiiConnectProviderActivationReadiness,
  fetchWiiiConnectProviderConnections,
  fetchWiiiConnectProviderEffectiveActions,
  fetchWiiiConnectProviders,
  fetchWiiiConnectSnapshot,
  grantWiiiConnectProviderConnectionScopes,
  previewWiiiConnectFacebookPost,
  pruneRuntimeFlowSessionEvents,
  startWiiiConnectProviderSession,
} from "@/api/wiii-connect";
import { WiiiConnectPage } from "@/components/connect/WiiiConnectPage";
import { useAuthStore } from "@/stores/auth-store";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useUIStore } from "@/stores/ui-store";

vi.mock("@/api/wiii-connect", () => ({
  applyWiiiConnectFacebookPost: vi.fn(),
  buildWiiiConnectProviderCallbackUrl: vi.fn(),
  createWiiiConnectProviderAuthorizationUrl: vi.fn(),
  disconnectWiiiConnectProviderConnection: vi.fn(),
  fetchRecentRuntimeFlowDoctor: vi.fn(),
  fetchRecentSemanticMemoryDoctor: vi.fn(),
  fetchRuntimeFlowDoctorHistory: vi.fn(),
  fetchSemanticMemoryDoctorHistory: vi.fn(),
  fetchWiiiConnectFacebookPages: vi.fn(),
  fetchWiiiConnectDoctor: vi.fn(),
  fetchWiiiConnectProviderActivationReadiness: vi.fn(),
  fetchWiiiConnectProviderConnections: vi.fn(),
  fetchWiiiConnectProviderEffectiveActions: vi.fn(),
  fetchWiiiConnectProviders: vi.fn(),
  fetchWiiiConnectSnapshot: vi.fn(),
  grantWiiiConnectProviderConnectionScopes: vi.fn(),
  pruneRuntimeFlowSessionEvents: vi.fn(),
  previewWiiiConnectFacebookPost: vi.fn(),
  startWiiiConnectProviderSession: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-shell", () => ({
  open: vi.fn().mockRejectedValue(new Error("no tauri runtime")),
}));

const mockBuildWiiiConnectProviderCallbackUrl = vi.mocked(buildWiiiConnectProviderCallbackUrl);
const mockApplyWiiiConnectFacebookPost = vi.mocked(applyWiiiConnectFacebookPost);
const mockCreateWiiiConnectProviderAuthorizationUrl = vi.mocked(createWiiiConnectProviderAuthorizationUrl);
const mockDisconnectWiiiConnectProviderConnection = vi.mocked(disconnectWiiiConnectProviderConnection);
const mockFetchWiiiConnectFacebookPages = vi.mocked(fetchWiiiConnectFacebookPages);
const mockFetchRecentRuntimeFlowDoctor = vi.mocked(fetchRecentRuntimeFlowDoctor);
const mockFetchRecentSemanticMemoryDoctor = vi.mocked(fetchRecentSemanticMemoryDoctor);
const mockFetchRuntimeFlowDoctorHistory = vi.mocked(fetchRuntimeFlowDoctorHistory);
const mockFetchSemanticMemoryDoctorHistory = vi.mocked(fetchSemanticMemoryDoctorHistory);
const mockFetchWiiiConnectDoctor = vi.mocked(fetchWiiiConnectDoctor);
const mockFetchWiiiConnectProviderActivationReadiness = vi.mocked(
  fetchWiiiConnectProviderActivationReadiness,
);
const mockFetchWiiiConnectProviderConnections = vi.mocked(fetchWiiiConnectProviderConnections);
const mockFetchWiiiConnectProviderEffectiveActions = vi.mocked(fetchWiiiConnectProviderEffectiveActions);
const mockFetchWiiiConnectProviders = vi.mocked(fetchWiiiConnectProviders);
const mockFetchWiiiConnectSnapshot = vi.mocked(fetchWiiiConnectSnapshot);
const mockGrantWiiiConnectProviderConnectionScopes = vi.mocked(
  grantWiiiConnectProviderConnectionScopes,
);
const mockPreviewWiiiConnectFacebookPost = vi.mocked(previewWiiiConnectFacebookPost);
const mockPruneRuntimeFlowSessionEvents = vi.mocked(pruneRuntimeFlowSessionEvents);
const mockStartWiiiConnectProviderSession = vi.mocked(startWiiiConnectProviderSession);

describe("WiiiConnectPage", () => {
  beforeEach(() => {
    mockFetchWiiiConnectProviders.mockReset();
    mockFetchWiiiConnectProviders.mockRejectedValue(new Error("offline"));
    mockFetchWiiiConnectSnapshot.mockReset();
    mockFetchWiiiConnectSnapshot.mockRejectedValue(new Error("offline"));
    mockBuildWiiiConnectProviderCallbackUrl.mockReset();
    mockBuildWiiiConnectProviderCallbackUrl.mockReturnValue("http://localhost:8080/api/v1/wiii-connect/providers/facebook/callback");
    mockApplyWiiiConnectFacebookPost.mockReset();
    mockApplyWiiiConnectFacebookPost.mockRejectedValue(new Error("offline"));
    mockCreateWiiiConnectProviderAuthorizationUrl.mockReset();
    mockCreateWiiiConnectProviderAuthorizationUrl.mockRejectedValue(new Error("offline"));
    mockDisconnectWiiiConnectProviderConnection.mockReset();
    mockDisconnectWiiiConnectProviderConnection.mockRejectedValue(new Error("offline"));
    mockFetchWiiiConnectFacebookPages.mockReset();
    mockFetchWiiiConnectFacebookPages.mockRejectedValue(new Error("offline"));
    mockFetchRecentRuntimeFlowDoctor.mockReset();
    mockFetchRecentRuntimeFlowDoctor.mockResolvedValue({
      version: "wiii.runtime_flow_doctor.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      status: "ready",
      alerts: [],
      summary: {
        turn_count: 2,
        done_seen_count: 2,
        missing_done_count: 0,
        metadata_seen_count: 2,
        uploaded_document_turns: 0,
        memory_context_turns: 0,
        source_ref_total: 0,
        context_provenance_turns: 2,
        context_warning_count: 0,
        failed_finalization_count: 0,
        raw_content_flag_count: 0,
      },
      request_correlation: {
        request_id_present_count: 2,
        missing_request_id_count: 0,
        provider_call_turn_count: 0,
        provider_call_correlated_turn_count: 0,
        provider_call_uncorrelated_turn_count: 0,
        provider_call_stage_count: 0,
        provider_call_stage_request_id_present_count: 0,
        provider_call_stage_request_id_missing_count: 0,
        provider_call_stage_request_id_match_count: 0,
        provider_call_stage_request_id_mismatch_count: 0,
        identifier_strategy: "presence_counts_only",
      },
      routes: { casual_chat: 2 },
      finalization_statuses: { saved: 2 },
      stream_events: { done: 2 },
      suppressed_tools: {},
      observed_tools: {},
      context_warnings: {},
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      alert_trend: {
        bucket_strategy: "event_created_at_hour",
        identifier_strategy: "aggregate_counts_only",
        buckets: [],
      },
      source: {
        session_event_count: 2,
        runtime_flow_ledger_event_count: 2,
        limit: 50,
        org_scoped: false,
        window: "recent_runtime_flow_ledger_events",
      },
      runtime_config: {
        native_stream_dispatch_enabled: false,
        session_event_log_backend: "in_memory",
        lifecycle_hook_total: 2,
        lifecycle_hook_owner_count: 1,
        lifecycle_on_run_end_hook_count: 1,
        lifecycle_on_run_error_hook_count: 1,
      },
      lifecycle_registrations: {
        version: "wiii.runtime_lifecycle_registrations.v1",
        registration_count: 2,
        owner_counts: { "engine.runtime": 2 },
        point_counts: { on_run_end: 1, on_run_error: 1 },
        default_runtime_hooks: {
          owner: "engine.runtime",
          required_count: 2,
          registered_count: 2,
          installed: true,
          hooks: [
            {
              point: "on_run_end",
              owner: "engine.runtime",
              name: "runtime_flow_session_event_finalization",
              registered: true,
            },
            {
              point: "on_run_error",
              owner: "engine.runtime",
              name: "runtime_flow_session_event_finalization",
              registered: true,
            },
          ],
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "code_metadata_only",
        },
      },
      post_turn_lifecycle: {
        version: "wiii.post_turn_lifecycle_metrics.v1",
        post_turn: {
          event_count: 3,
          status_counts: { scheduled: 2, skipped: 1 },
          reason_counts: {
            post_turn_background_tasks_scheduled: 2,
            "PRIVATE POST TURN SHOULD NOT APPEAR": 1,
          },
          transport_counts: { sync: 2, other: 1 },
          semantic_memory_policy_counts: {
            extract_facts: 2,
            not_applicable: 1,
          },
        },
        background_tasks: {
          event_count: 4,
          group_counts: {
            semantic_memory_interaction: 2,
            memory_summarizer: 1,
            "authorization=Bearer raw-post-turn-token": 1,
          },
          status_counts: { scheduled: 3, skipped: 1 },
          reason_counts: {
            extract_facts: 2,
            missing_dependency: 1,
          },
        },
        source: {
          metrics_backend: "runtime_metrics.snapshot",
          window: "process_lifetime_in_memory",
          org_scoped: false,
          counter_names: {
            post_turn: "runtime.post_turn.lifecycle.scheduling",
            background_tasks: "runtime.background_tasks.scheduling",
          },
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
      },
      post_turn_lifecycle_ledger: {
        version: "wiii.post_turn_lifecycle_ledger.v1",
        event_count: 2,
        missing_count: 0,
        status_counts: { scheduled: 2 },
        reason_counts: { post_turn_background_tasks_scheduled: 2 },
        semantic_memory_policy_counts: { extract_facts: 2 },
        background_tasks_scheduled_count: 2,
        background_tasks_skipped_count: 0,
        raw_content_flag_count: 0,
        background_schedule: {
          event_count: 2,
          task_count: 4,
          group_counts: {
            semantic_memory_interaction: 2,
            semantic_memory_maintenance: 2,
          },
          status_counts: { scheduled: 4 },
          reason_counts: {
            extract_facts: 2,
            after_interaction_write: 2,
          },
        },
        source: {
          ledger_path: "finalization.post_turn_lifecycle",
          window: "runtime_flow_ledger_events",
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
      },
    });
    mockFetchRuntimeFlowDoctorHistory.mockReset();
    mockFetchRuntimeFlowDoctorHistory.mockResolvedValue({
      version: "wiii.runtime_flow_doctor_history.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      bucket_strategy: "event_created_at_hour",
      identifier_strategy: "aggregate_counts_only",
      buckets: [
        {
          bucket_start: "2026-05-31T10:00:00+00:00",
          status: "ready",
          alerts: [],
          summary: {
            turn_count: 2,
            done_seen_count: 2,
            missing_done_count: 0,
            raw_content_flag_count: 0,
          },
          request_correlation: {
            missing_request_id_count: 0,
          },
          routes: { casual_chat: 2 },
          finalization_statuses: { saved: 2 },
          post_turn_lifecycle_ledger: {
            version: "wiii.post_turn_lifecycle_ledger.v1",
            event_count: 2,
            missing_count: 0,
            background_tasks_scheduled_count: 2,
            background_tasks_skipped_count: 0,
            raw_content_flag_count: 0,
            status_counts: { scheduled: 2 },
            reason_counts: { post_turn_background_tasks_scheduled: 2 },
            semantic_memory_policy_counts: { extract_facts: 2 },
            background_schedule: {
              event_count: 2,
              task_count: 4,
              group_counts: {
                semantic_memory_interaction: 2,
                semantic_memory_maintenance: 2,
              },
              status_counts: { scheduled: 4 },
              reason_counts: { extract_facts: 2, after_interaction_write: 2 },
            },
            source: {
              ledger_path: "finalization.post_turn_lifecycle",
              window: "runtime_flow_ledger_events",
            },
            privacy: {
              raw_content_included: false,
              identifier_strategy: "aggregate_counts_only",
            },
          },
          context_warnings: {},
          source: {
            session_event_count: 2,
            runtime_flow_ledger_event_count: 2,
          },
        },
      ],
      source: {
        session_event_count: 2,
        runtime_flow_ledger_event_count: 2,
        bucket_count: 1,
        bucket_limit: 24,
        limit: 500,
        org_scoped: false,
        window: "recent_runtime_flow_ledger_history",
      },
      post_turn_lifecycle_ledger: {
        version: "wiii.post_turn_lifecycle_ledger.v1",
        event_count: 2,
        missing_count: 0,
        background_tasks_scheduled_count: 2,
        background_tasks_skipped_count: 0,
        raw_content_flag_count: 0,
        status_counts: { scheduled: 2 },
        reason_counts: { post_turn_background_tasks_scheduled: 2 },
        semantic_memory_policy_counts: { extract_facts: 2 },
        background_schedule: {
          event_count: 2,
          task_count: 4,
          group_counts: {
            semantic_memory_interaction: 2,
            semantic_memory_maintenance: 2,
          },
          status_counts: { scheduled: 4 },
          reason_counts: { extract_facts: 2, after_interaction_write: 2 },
        },
        source: {
          ledger_path: "finalization.post_turn_lifecycle",
          window: "runtime_flow_ledger_events",
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "in_memory",
      },
    });
    mockFetchRecentSemanticMemoryDoctor.mockReset();
    mockFetchRecentSemanticMemoryDoctor.mockResolvedValue({
      version: "wiii.semantic_memory_write_doctor.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      status: "ready",
      summary: {
        write_count: 2,
        message_saved_count: 1,
        response_saved_count: 1,
        fact_extraction_requested_count: 1,
        stored_fact_total: 2,
        stored_insight_total: 1,
        blocked_count: 0,
        failed_count: 0,
        degraded_count: 0,
        warning_count: 0,
        raw_content_flag_count: 0,
      },
      write_kinds: { interaction: 1, insight_store: 1 },
      write_statuses: { saved: 2 },
      organization_contexts: { request_scoped: 2 },
      warnings: {},
      source: {
        session_event_count: 2,
        semantic_memory_write_event_count: 2,
        limit: 50,
        org_scoped: false,
        window: "recent_semantic_memory_write_events",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "in_memory",
      },
    });
    mockFetchSemanticMemoryDoctorHistory.mockReset();
    mockFetchSemanticMemoryDoctorHistory.mockResolvedValue({
      version: "wiii.semantic_memory_write_doctor_history.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      bucket_strategy: "event_created_at_hour",
      identifier_strategy: "aggregate_counts_only",
      buckets: [
        {
          bucket_start: "2026-05-31T10:00:00+00:00",
          status: "ready",
          summary: {
            write_count: 2,
            stored_fact_total: 2,
            stored_insight_total: 1,
            blocked_count: 0,
            warning_count: 0,
          },
          write_kinds: { interaction: 1, insight_store: 1 },
          write_statuses: { saved: 2 },
          organization_contexts: { request_scoped: 2 },
          warnings: {},
          source: {
            session_event_count: 2,
            semantic_memory_write_event_count: 2,
          },
        },
      ],
      source: {
        session_event_count: 2,
        semantic_memory_write_event_count: 2,
        bucket_count: 1,
        bucket_limit: 24,
        limit: 500,
        org_scoped: false,
        window: "recent_semantic_memory_write_history",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "in_memory",
      },
    });
    mockPruneRuntimeFlowSessionEvents.mockReset();
    mockPruneRuntimeFlowSessionEvents.mockResolvedValue({
      schema: "wiii.session_event_log_prune.v1",
      status: "dry_run",
      matched_count: 0,
      deleted_count: 0,
      retention_days: 30,
      cutoff: "2026-05-01T00:00:00+00:00",
      dry_run: true,
      org_scoped: false,
      event_type_filter_applied: true,
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "in_memory",
      },
    });
    mockFetchWiiiConnectDoctor.mockReset();
    mockFetchWiiiConnectDoctor.mockResolvedValue({
      version: "wiii_connect_doctor.v0",
      generated_at: "2026-05-29T00:00:00.000Z",
      surface: "desktop",
      status: "degraded",
      summary: {
        total_paths: 2,
        ready_paths: 1,
        guarded_paths: 0,
        blocked_paths: 1,
        total_connections: 2,
        agent_ready_connections: 1,
        external_provider_connections: 1,
        external_agent_ready_connections: 0,
        warning_count: 2,
      },
      path_diagnostics: [
        {
          path: "casual_chat",
          status: "ready",
          reason: "ready",
        },
        {
          path: "external_app_action",
          status: "blocked",
          reason: "no_agent_ready_external_provider",
          missing_connection_slugs: [],
          blocked_connection_reasons: [],
          mutation_policy: "none",
          delegation_policy: "delegate_to_integrations_agent",
        },
      ],
      provider_diagnostics: [
        {
          provider_slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          status: "blocked",
          reason: "connection_storage_unavailable",
          connection_status: "not_connected",
          active: false,
          agent_ready: false,
          connection_count: 0,
          active_connection_count: 0,
          action_count: 0,
          scope_count: 0,
          required_next: ["configure_wiii_connect_storage"],
          stages: [
            {
              key: "registry",
              status: "ready",
              reason: "registered",
              required_next: [],
            },
            {
              key: "adapter",
              status: "blocked",
              reason: "provider_adapter_not_bound",
              required_next: ["bind_provider_adapter"],
            },
            {
              key: "account",
              status: "blocked",
              reason: "connection_storage_unavailable",
              required_next: ["configure_wiii_connect_storage"],
            },
            {
              key: "agent_policy",
              status: "pending",
              reason: "account_required",
              required_next: ["complete_provider_oauth"],
            },
            {
              key: "gateway",
              status: "blocked",
              reason: "agent_policy_not_ready",
              required_next: ["enable_provider_agent_policy"],
            },
          ],
        },
      ],
      top_blockers: ["path:external_app_action:no_agent_ready_external_provider"],
      warnings: ["adapter_disabled"],
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockReset();
    mockFetchWiiiConnectProviderActivationReadiness.mockRejectedValue(new Error("offline"));
    mockFetchWiiiConnectProviderConnections.mockReset();
    mockFetchWiiiConnectProviderConnections.mockRejectedValue(new Error("offline"));
    mockFetchWiiiConnectProviderEffectiveActions.mockReset();
    mockFetchWiiiConnectProviderEffectiveActions.mockRejectedValue(new Error("offline"));
    mockGrantWiiiConnectProviderConnectionScopes.mockReset();
    mockGrantWiiiConnectProviderConnectionScopes.mockRejectedValue(new Error("offline"));
    mockPreviewWiiiConnectFacebookPost.mockReset();
    mockPreviewWiiiConnectFacebookPost.mockRejectedValue(new Error("offline"));
    mockStartWiiiConnectProviderSession.mockReset();
    mockStartWiiiConnectProviderSession.mockRejectedValue(new Error("offline"));
    useHostContextStore.getState().clear();
    useConnectionStore.setState({
      status: "connected",
      serverVersion: "test-version",
      lastCheckedAt: "2026-05-28T12:00:00.000Z",
      errorMessage: null,
      pollIntervalId: null,
    });
    useChatStore.setState({
      streamingLifecycleEvents: [],
      lastCompletedLifecycleEvents: [],
    });
    useAuthStore.setState({
      isAuthenticated: false,
      isLoaded: true,
      user: null,
      tokens: null,
      authMode: "legacy",
    });
    useUIStore.setState({
      activeView: "wiii-connect",
      commandPaletteOpen: false,
      sidebarOpen: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders sanitized Wiii Connect snapshot without raw tool or token payloads", async () => {
    useChatStore.setState({
      lastCompletedLifecycleEvents: [
        {
          schema_version: "1",
          event_name: "path.selected",
          phase: "routing",
          status: "selected",
          message: "Selected document path",
          lane: "document_grounded_answer",
          capabilities: {
            host_surface: "desktop_chat",
            observed_tools: ["authoring.apply_lesson_patch", "document.read"],
            suppressed_tools: ["host_action.execute"],
            approval_token_present: true,
            wiii_connect: {
              version: "wiii_connect_snapshot.v0",
              generated_at: "2026-05-28T12:00:00.000Z",
              surface: "desktop_chat",
              connections: [
                {
                  slug: "document_corpus",
                  label: "Document corpus",
                  provider_kind: "wiii_native",
                  status: "connected",
                  active: true,
                  agent_ready: true,
                  capabilities: ["document.read", "document.cite"],
                  required_for_paths: ["document_grounded_answer"],
                  scopes: { read: true },
                  attachment_count: 1,
                  source_ref_count: 2,
                  last_checked_at: "2026-05-28T12:00:00.000Z",
                  reason: "active",
                },
                {
                  slug: "lms_authoring",
                  label: "LMS authoring",
                  provider_kind: "wiii_native",
                  status: "not_connected",
                  active: false,
                  agent_ready: false,
                  capabilities: ["authoring.apply_lesson_patch"],
                  required_for_paths: ["lms_document_preview", "lms_document_apply"],
                  scopes: { read: false, preview: false, apply: false },
                  reason: "missing_lms_host",
                },
              ],
              path_capabilities: [
                {
                  path: "document_grounded_answer",
                  required_connection_slugs: ["document_corpus"],
                  allowed_tool_groups: ["knowledge_search"],
                  mutation_policy: "none",
                  delegation_policy: "direct_only",
                },
                {
                  path: "lms_document_apply",
                  required_connection_slugs: ["lms_authoring"],
                  allowed_tool_groups: ["lms_authoring"],
                  mutation_policy: "approval_token_required",
                  delegation_policy: "direct_only",
                },
              ],
            },
          },
          received_at_ms: 1779969600000,
        },
      ],
    });

    render(<WiiiConnectPage />);

    expect(screen.getByTestId("wiii-connect-page")).toBeTruthy();
    expect(screen.getByText("Document corpus")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Document corpus/i }));
    expect(screen.getByText("2 capability")).toBeTruthy();
    expect(screen.getByText(/1 file/)).toBeTruthy();
    expect(screen.queryByText("document.read")).toBeNull();
    expect(screen.queryByText("authoring.apply_lesson_patch")).toBeNull();
    expect(screen.queryByText("host_action.execute")).toBeNull();
    expect(screen.queryByText("approval-token")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Path policy/i }));

    expect(screen.getByText("document_grounded_answer")).toBeTruthy();
    expect(await screen.findByText("lms_document_apply")).toBeTruthy();
    expect(screen.getByText("Cần approval_token")).toBeTruthy();
  });

  it("shows a fail-closed connection catalog before a backend snapshot exists", () => {
    useHostContextStore.getState().setCapabilities({
      host_type: "desktop",
      host_name: "Wiii Desktop",
      tools: [{ name: "ui.highlight", description: "Highlight" }],
    });

    render(<WiiiConnectPage />);

    expect(screen.getAllByText("Chưa có snapshot").length).toBeGreaterThan(0);
    expect(screen.getByText("Danh bạ kết nối")).toBeTruthy();
    expect(screen.getByText("Đang dùng fallback local")).toBeTruthy();
    expect(screen.getAllByText("Máy chủ Wiii").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    expect(screen.getByRole("button", { name: /Facebook/i })).toBeTruthy();
    expect(screen.getAllByText("Chưa nối").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    expect(screen.getByText("Token vault")).toBeTruthy();
    const disabledConnectButton = screen.getByRole("button", {
      name: "Chưa thể kết nối",
    }) as HTMLButtonElement;
    expect(disabledConnectButton.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("Tìm kết nối..."), {
      target: { value: "facebook" },
    });
    expect(screen.getByRole("button", { name: /Facebook/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Gmail/i })).toBeNull();
    expect(screen.queryByText("ui.highlight")).toBeNull();
  });

  it("uses backend runtime snapshot when no chat lifecycle snapshot exists", async () => {
    mockFetchWiiiConnectSnapshot.mockResolvedValue({
      version: "wiii_connect_snapshot.v0",
      generated_at: "2026-05-29T00:00:00.000Z",
      surface: "desktop",
      connections: [
        {
          slug: "server",
          label: "Wiii backend",
          provider_kind: "wiii_native",
          status: "connected",
          active: true,
          agent_ready: true,
          scopes: { read: true },
          capabilities: ["server.health"],
          required_for_paths: [],
          reason: "backend_runtime",
        },
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          status: "connected",
          active: true,
          agent_ready: true,
          scopes: { read: true, preview: true, apply: true },
          capabilities: ["wiii_connect.facebook.agent_ready"],
          required_for_paths: ["external_app_action"],
          reason: "connected",
        },
      ],
      path_capabilities: [
        {
          path: "casual_chat",
          required_connection_slugs: [],
          mutation_policy: "none",
          delegation_policy: "direct_only",
        },
        {
          path: "external_app_action",
          required_connection_slugs: [],
          allowed_tool_groups: ["external_app"],
          mutation_policy: "approval_token_required",
          delegation_policy: "delegate_to_integrations_agent",
        },
      ],
      capability_summary: {
        active_connection_slugs: ["server", "facebook"],
        agent_ready_connection_slugs: ["server", "facebook"],
        connected_provider_slugs: ["facebook"],
        agent_ready_provider_slugs: ["facebook"],
        connected_scope_names: ["read", "preview", "apply"],
        suppressed_tool_groups: ["pointy"],
        path_readiness: [
          {
            path: "casual_chat",
            status: "ready",
            reason: "ready",
            required_connection_slugs: [],
            missing_connection_slugs: [],
            agent_ready_connection_slugs: [],
            allowed_tool_groups: [],
            suppressed_tool_groups: [],
            mutation_policy: "none",
            delegation_policy: "direct_only",
          },
          {
            path: "external_app_action",
            status: "guarded",
            reason: "provider_worker_gateway_required",
            required_connection_slugs: [],
            missing_connection_slugs: [],
            agent_ready_connection_slugs: ["facebook"],
            allowed_tool_groups: ["external_app"],
            suppressed_tool_groups: ["pointy"],
            mutation_policy: "approval_token_required",
            delegation_policy: "delegate_to_integrations_agent",
          },
        ],
      },
      warnings: [],
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("2/2 agent-ready")).toBeTruthy();
    expect(mockFetchWiiiConnectSnapshot).toHaveBeenCalledWith({ surface: "desktop" });
    fireEvent.click(screen.getByRole("button", { name: /Snapshot/i }));

    expect(screen.getAllByText("Wiii backend").length).toBeGreaterThan(0);
    expect(screen.queryByText(/fallback local/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Path policy/i }));
    const capabilitySummary = await screen.findByTestId("wiii-connect-capability-summary");
    expect(capabilitySummary.textContent).toContain("facebook");
    expect(capabilitySummary.textContent).toContain("read, preview, apply");
    expect(capabilitySummary.textContent).toContain("1/2 ready");
    expect(capabilitySummary.textContent).toContain("external_app_action");
    expect(capabilitySummary.textContent).toContain("provider_worker_gateway_required");
    expect(capabilitySummary.textContent).toContain("pointy");
  });

  it("does not count a merely connected provider as agent-ready", async () => {
    mockFetchWiiiConnectSnapshot.mockResolvedValue({
      version: "wiii_connect_snapshot.v0",
      generated_at: "2026-05-29T00:00:00.000Z",
      surface: "desktop",
      connections: [
        {
          slug: "server",
          label: "Wiii backend",
          provider_kind: "wiii_native",
          status: "connected",
          active: true,
          agent_ready: true,
          scopes: { read: true },
          capabilities: ["server.health"],
          required_for_paths: [],
          reason: "backend_runtime",
        },
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          status: "connected",
          active: true,
          agent_ready: false,
          scopes: { read: true },
          capabilities: ["wiii_connect.facebook.connected"],
          required_for_paths: ["external_app_action"],
          reason: "connected_provider_not_agent_ready",
        },
      ],
      path_capabilities: [],
      warnings: [],
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("1/2 agent-ready")).toBeTruthy();
    expect(screen.queryByText("2/2 agent-ready")).toBeNull();
  });

  it("polls the runtime snapshot and doctor as a live control-plane", async () => {
    vi.useFakeTimers();
    mockFetchWiiiConnectSnapshot
      .mockResolvedValueOnce({
        version: "wiii_connect_snapshot.v0",
        generated_at: "2026-05-29T00:00:00.000Z",
        surface: "desktop",
        connections: [
          {
            slug: "server",
            label: "Wiii backend",
            provider_kind: "wiii_native",
            status: "connected",
            active: true,
            agent_ready: true,
            scopes: { read: true },
            capabilities: ["server.health"],
            required_for_paths: [],
            reason: "backend_runtime",
          },
        ],
        path_capabilities: [],
        warnings: [],
      })
      .mockResolvedValueOnce({
        version: "wiii_connect_snapshot.v0",
        generated_at: "2026-05-29T00:00:05.000Z",
        surface: "desktop",
        connections: [
          {
            slug: "server",
            label: "Wiii backend",
            provider_kind: "wiii_native",
            status: "connected",
            active: true,
            agent_ready: true,
            scopes: { read: true },
            capabilities: ["server.health"],
            required_for_paths: [],
            reason: "backend_runtime",
          },
          {
            slug: "facebook",
            label: "Facebook",
            provider_kind: "composio",
            status: "connected",
            active: true,
            agent_ready: true,
            scopes: { read: true, preview: true, apply: true },
            capabilities: ["wiii_connect.facebook.agent_ready"],
            required_for_paths: ["external_app_action"],
            reason: "connected",
          },
        ],
        path_capabilities: [],
        warnings: [],
      });
    mockFetchWiiiConnectDoctor.mockResolvedValue({
      version: "wiii_connect_doctor.v0",
      generated_at: "2026-05-29T00:00:00.000Z",
      surface: "desktop",
      status: "ready",
      summary: {
        total_paths: 0,
        ready_paths: 0,
        guarded_paths: 0,
        blocked_paths: 0,
        total_connections: 1,
        agent_ready_connections: 1,
        external_provider_connections: 0,
        external_agent_ready_connections: 0,
        warning_count: 0,
      },
      path_diagnostics: [],
      top_blockers: [],
      warnings: [],
    });

    render(<WiiiConnectPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("1/1 agent-ready")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockFetchWiiiConnectSnapshot).toHaveBeenCalledTimes(2);
    expect(mockFetchWiiiConnectDoctor).toHaveBeenCalledTimes(2);
    expect(screen.getByText("2/2 agent-ready")).toBeTruthy();
  });

  it("uses backend provider registry when available", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: false,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["execution_gateway", "audit_ledger"],
          action_count: 0,
        },
      ],
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    expect(screen.getAllByText("Facebook provider from backend registry.").length).toBeGreaterThan(0);
    expect(screen.getByText("execution_gateway")).toBeTruthy();
    expect(screen.getByText("audit_ledger")).toBeTruthy();
    expect(screen.getByText("Backend registry")).toBeTruthy();
  });

  it("renders activation readiness gates without exposing provider secrets", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "gmail",
          label: "Gmail",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "productivity",
          description: "Gmail provider from backend registry.",
          requirements: ["scope_policy", "execution_gateway"],
          action_count: 1,
        },
      ],
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "blocked",
      provider_slug: "gmail",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: false,
      gates: [
        {
          key: "provider_adapter",
          ready: true,
          reason: "ready",
          required_next: [],
          metadata: { configured: true },
        },
        {
          key: "local_connection",
          ready: false,
          reason: "connection_missing",
          required_next: ["complete_provider_oauth"],
        },
        {
          key: "execution_gateway",
          ready: false,
          reason: "connection_missing",
          required_next: ["connect_provider_account"],
        },
      ],
      connection: {
        present: false,
        state: "missing",
        active: false,
        vault_ref_present: false,
        reason: "connection_missing",
      },
      execution_gateway: {
        status: "blocked",
        reason: "connection_missing",
      },
      provider: { api_key: "secret-api-key" },
      storage: { persistent: true },
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Gmail/i }));

    expect(await screen.findByTestId("wiii-connect-readiness-panel")).toBeTruthy();
    expect(screen.getByTestId("wiii-connect-lifecycle-panel")).toBeTruthy();
    expect(screen.getByTestId("wiii-connect-next-action").textContent).toContain(
      "Mở OAuth/Connect Link với provider",
    );
    expect(screen.getByText("Hoàn tất OAuth/Connect Link")).toBeTruthy();
    expect(screen.getByText("Activation readiness")).toBeTruthy();
    expect(screen.getByText("Connect-ready")).toBeTruthy();
    expect(screen.getByText("Agent read-only")).toBeTruthy();
    expect(screen.getByText("Adapter")).toBeTruthy();
    expect(screen.getAllByText("Connection").length).toBeGreaterThan(0);
    expect(screen.getByText("complete_provider_oauth")).toBeTruthy();
    expect(mockFetchWiiiConnectProviderActivationReadiness).toHaveBeenCalledWith("gmail", {
      actionSlug: "GMAIL_FETCH_EMAILS",
      connectionRef: "",
      probeDatabase: true,
    });
    expect(screen.queryByText("secret-api-key")).toBeNull();
    expect(screen.queryByText("api_key")).toBeNull();
    expect(screen.queryByText("access_token")).toBeNull();
  });

  it("renders effective action stage blockers without exposing provider secrets", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: true,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          action_count: 1,
        },
      ],
    });
    mockFetchWiiiConnectProviderEffectiveActions.mockResolvedValue({
      version: "wiii_connect_action_inventory.v1",
      provider_slug: "facebook",
      provider_kind: "composio",
      status: "blocked",
      reason: "missing_scope",
      connection_ref_present: true,
      connection_present: true,
      connection_active: true,
      selected_connection_required: false,
      catalog_action_count: 1,
      runtime_enabled_action_count: 1,
      visible_action_count: 0,
      executable_action_count: 0,
      actions: [
        {
          version: "wiii_connect_action_inventory.v1",
          slug: "FACEBOOK_CREATE_POST",
          provider_slug: "facebook",
          label: "Create Facebook post",
          mutation: "write",
          path: "external_app_action",
          status: "blocked",
          reason: "missing_scope",
          runtime_enabled: true,
          visible_to_agent: false,
          executable_now: false,
          requires_preview: true,
          requires_approval: true,
          required_scopes: ["apply"],
          argument_policy_version: "wiii_connect_argument_key_policy.v1",
          argument_keys: ["message", "link"],
          model_argument_keys: ["message", "link"],
          hidden_argument_count: 3,
          stages: [
            {
              key: "account",
              status: "ready",
              reason: "connected",
              required_next: [],
            },
            {
              key: "agent_policy",
              status: "blocked",
              reason: "missing_scope",
              required_next: ["grant_required_scope"],
            },
            {
              key: "gateway",
              status: "blocked",
              reason: "access_token=raw-provider-token",
              required_next: ["ak_secret"],
            },
          ],
          gateway: { status: "blocked", reason: "missing_scope" },
          warnings: [],
        },
      ],
      storage: { persistent: true },
    });

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));

    const panel = await screen.findByTestId("wiii-connect-action-inventory-panel");
    expect(panel.textContent).toContain("Create Facebook post");
    expect(panel.textContent).toContain("Model args");
    expect(panel.textContent).toContain("message, link");
    expect(panel.textContent).toContain("3 backend-owned");
    expect(panel.textContent).toContain("Agent policy");
    expect(panel.textContent).toContain("missing_scope");
    expect(panel.textContent).toContain("grant_required_scope");
    expect(panel.textContent).toContain("[đã ẩn]");
    expect(container.textContent).not.toContain("page_id");
    expect(container.textContent).not.toContain("published");
    expect(container.textContent).not.toContain("raw-provider-token");
    expect(container.textContent).not.toContain("access_token");
    expect(container.textContent).not.toContain("ak_secret");
  });

  it("auto-syncs backend provider connections when a provider is selected", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_public_1",
          provider_slug: "facebook",
          state: "connected",
          active: true,
          scopes: { read: true, write: false },
          vault_ref_present: true,
          account_label: "Wiii Facebook Page",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready", access_token: "secret-token" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "blocked",
      provider_slug: "facebook",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: false,
      gates: [
        {
          key: "local_connection",
          ready: true,
          reason: "ready",
          required_next: [],
        },
        {
          key: "execution_gateway",
          ready: false,
          reason: "provider_not_agent_ready",
          required_next: ["enable_provider_agent_policy"],
        },
      ],
      connection: {
        present: true,
        provider_slug: "facebook",
        state: "connected",
        active: true,
        scopes: { read: true },
        vault_ref_present: true,
        reason: "ready",
      },
      execution_gateway: {
        status: "blocked",
        reason: "provider_not_agent_ready",
      },
      provider: { access_token: "secret-token" },
      storage: { persistent: true },
    });

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));

    expect(await screen.findByText("Connection thật")).toBeTruthy();
    expect(screen.getAllByText("Wiii Facebook Page").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Đã kết nối").length).toBeGreaterThan(0);
    expect(screen.getByTestId("wiii-connect-next-action").textContent).toContain(
      "Hoàn tất policy/gateway trước khi agent dùng",
    );
    expect(screen.getByText("Bật policy agent cho provider")).toBeTruthy();
    await waitFor(() => {
      expect(mockFetchWiiiConnectProviderConnections).toHaveBeenCalledWith("facebook", {
        probeDatabase: true,
      });
    });
    await waitFor(() => {
      expect(mockFetchWiiiConnectProviderActivationReadiness).toHaveBeenCalledWith("facebook", {
        actionSlug: "FACEBOOK_LIST_MANAGED_PAGES",
        connectionRef: "wcn_public_1",
        probeDatabase: true,
      });
    });
    expect(container.textContent).not.toContain("wcn_public_1");
    expect(container.textContent).not.toContain("secret-token");
    expect(screen.queryByText("access_token")).toBeNull();
  });

  it("shows Facebook preview approval ledger without exposing approval secrets", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: true,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 2,
        },
      ],
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_public_ledger",
          provider_slug: "facebook",
          state: "connected",
          active: true,
          scopes: { read: true, preview: true, apply: true },
          vault_ref_present: true,
          account_label: "Wiii Facebook Page",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "ready",
      provider_slug: "facebook",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: true,
      gates: [
        {
          key: "local_connection",
          ready: true,
          reason: "ready",
          required_next: [],
        },
        {
          key: "execution_gateway",
          ready: true,
          reason: "allowed",
          required_next: [],
        },
      ],
      connection: {
        present: true,
        provider_slug: "facebook",
        state: "connected",
        active: true,
        scopes: { read: true, preview: true, apply: true },
        vault_ref_present: true,
        reason: "ready",
      },
      execution_gateway: {
        status: "allowed",
        reason: "ready",
      },
      storage: {
        persistent: true,
        operation_approval_table_ready: true,
      },
    });
    mockFetchWiiiConnectFacebookPages.mockResolvedValue({
      version: "wiii_connect_facebook_pages.v1",
      status: "ready",
      reason: "ready",
      provider_slug: "facebook",
      page_count: 1,
      pages: [
        {
          page_id: "123456",
          name: "Wiii Page",
        },
      ],
      gateway: { status: "allowed" },
    });
    mockPreviewWiiiConnectFacebookPost.mockResolvedValue({
      version: "wiii_connect_facebook_post_preview.v1",
      status: "ready",
      reason: "preview_ready",
      provider_slug: "facebook",
      action_slug: "FACEBOOK_CREATE_POST",
      preview_evidence_id: "wcp_preview",
      approval_token: "approval-token-secret",
      preview: {
        page_id: "123456",
        message: "safe preview copy",
        image_present: false,
      },
      gateway: { status: "allowed" },
      approval_ledger: {
        version: "wiii_connect_operation_approval.v1",
        status: "pending",
        reason: "preview_recorded",
        persistent: true,
        preview_evidence_id_present: true,
        request_fingerprint_present: true,
      },
      storage: {
        persistent: true,
        operation_approval_table_ready: true,
      },
    });

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    const loadPagesButton = await screen.findByRole("button", { name: /Page/i });
    await waitFor(() => {
      expect((loadPagesButton as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(loadPagesButton);
    await waitFor(() => {
      expect(mockFetchWiiiConnectFacebookPages).toHaveBeenCalledWith(
        "facebook",
        "wcn_public_ledger",
      );
    });
    const previewButton = await screen.findByRole("button", { name: /preview/i });
    await waitFor(() => {
      expect((previewButton as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(previewButton);

    const ledger = await screen.findByTestId("wiii-connect-facebook-approval-ledger");
    expect(ledger.textContent).toContain("Approval ledger");
    expect(ledger.textContent).toContain("pending");
    expect(ledger.textContent).toContain("preview_recorded");
    expect(ledger.textContent).toContain("Persistent");
    expect(container.textContent).not.toContain("approval-token-secret");
    expect(ledger.textContent).not.toContain("wcn_public_ledger");
    expect(ledger.textContent).not.toContain("123456");
  });

  it("reflects backend read-only execution readiness on provider cards", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "gmail",
          label: "Gmail",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "productivity",
          description: "Gmail provider from backend registry.",
          requirements: ["scope_policy", "execution_gateway"],
          connect_requirements: ["provider_managed_vault_ref"],
          agent_ready_requirements: ["curated_readonly_action", "execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "gmail",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_live_gmail_1",
          provider_slug: "gmail",
          state: "connected",
          active: true,
          scopes: { read: true, write: false },
          vault_ref_present: true,
          account_label: "Wiii Gmail Account",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready", refresh_token: "secret-refresh-token" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "ready",
      provider_slug: "gmail",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: true,
      gates: [
        {
          key: "local_connection",
          ready: true,
          reason: "ready",
          required_next: [],
        },
        {
          key: "curated_readonly_action",
          ready: true,
          reason: "ready",
          required_next: [],
        },
        {
          key: "execution_gateway",
          ready: true,
          reason: "allowed",
          required_next: [],
        },
      ],
      action: {
        action_slug: "GMAIL_FETCH_EMAILS",
        api_key: "secret-action-key",
      },
      connection: {
        present: true,
        provider_slug: "gmail",
        state: "connected",
        active: true,
        scopes: { read: true },
        vault_ref_present: true,
        reason: "ready",
      },
      execution_gateway: {
        status: "allowed",
        reason: "readonly_action_allowed",
      },
      provider: { refresh_token: "secret-refresh-token" },
      storage: { persistent: true },
    });

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Gmail/i }));

    expect(await screen.findByText("Read-only sẵn sàng")).toBeTruthy();
    expect(screen.getByTestId("wiii-connect-next-action").textContent).toContain(
      "Sẵn sàng cho agent read-only",
    );
    expect(screen.getByText("Không tự mở write/admin scope")).toBeTruthy();
    expect(
      screen.getByText(
        "Read-only action đã qua scope policy và execution gateway; mutation/write vẫn bị chặn ngoài allowlist.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByText("allowed").length).toBeGreaterThan(0);
    expect(container.textContent?.replace(/\s+/g, "")).toContain("Agent-readyCó");
    expect(container.textContent).not.toContain("wcn_live_gmail_1");
    expect(container.textContent).not.toContain("secret-refresh-token");
    expect(container.textContent).not.toContain("secret-action-key");
    expect(screen.queryByText("refresh_token")).toBeNull();
    expect(screen.queryByText("api_key")).toBeNull();
  });

  it("requests backend session decision for backend registry providers", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: false,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["execution_gateway", "audit_ledger"],
          action_count: 0,
        },
      ],
    });
    mockStartWiiiConnectProviderSession.mockResolvedValue({
      version: "wiii_connect_session.v1",
      status: "blocked",
      reason: "provider_disabled",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "",
      required_next: ["encrypted_vault_ref", "execution_gateway"],
      audit_event: {
        version: "wiii_connect_session.v1",
        stage: "start_requested",
        reason: "provider_disabled",
        created_at: "2026-05-28T00:00:00Z",
        request: {
          provider_slug: "facebook",
          surface: "desktop",
          requested_scopes: { read: true },
          redirect_uri_present: false,
          request_metadata_keys: ["source", "provider"],
        },
      },
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra policy" }));

    expect(mockStartWiiiConnectProviderSession).toHaveBeenCalledWith("facebook", {
      surface: "desktop",
      requested_scopes: { read: true },
      request_metadata: {
        source: "wiii_connect_page",
        provider: "composio",
      },
    });
    expect(await screen.findByText("Quyết định backend")).toBeTruthy();
    expect(screen.getByText("provider_disabled")).toBeTruthy();
    expect(screen.getByText("encrypted_vault_ref")).toBeTruthy();
    expect(screen.getByText("Không phát hành")).toBeTruthy();
    expect(screen.queryByText("access_token")).toBeNull();
    expect(screen.queryByText("secret-value")).toBeNull();
  });

  it("starts backend-owned authorization and renders sanitized provider connections", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockCreateWiiiConnectProviderAuthorizationUrl.mockResolvedValue({
      version: "wiii_connect_provider_adapter.v1",
      status: "ready",
      reason: "authorization_url_issued",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "https://composio.example/connect/safe",
      adapter: {
        version: "wiii_connect_provider_adapter.v1",
        provider_kind: "composio",
        adapter_name: "composio",
        bound: true,
        configured: true,
        can_create_authorization_url: true,
        can_exchange_callback: true,
        can_execute_actions: false,
        authorization_ready: true,
        reason: "configured",
        warnings: [],
      },
      required_next: [],
      audit_event: null,
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_public_1",
          provider_slug: "facebook",
          state: "connected",
          active: true,
          scopes: { read: true, write: false },
          vault_ref_present: true,
          account_label: "Wiii Facebook Page",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: "Kết nối qua Wiii" }));

    expect(await screen.findByText("Connect Link backend")).toBeTruthy();
    expect(mockCreateWiiiConnectProviderAuthorizationUrl).toHaveBeenCalledWith("facebook", {
      surface: "desktop",
      redirect_uri: "http://localhost:8080/api/v1/wiii-connect/providers/facebook/callback",
      probe_database: true,
      requested_scopes: { read: true },
      request_metadata: {
        source: "wiii_connect_page",
        provider: "composio",
      },
    });
    expect(openSpy).toHaveBeenCalledWith(
      "https://composio.example/connect/safe",
      "_blank",
      "noopener,noreferrer",
    );
    expect(await screen.findByText("Connection thật")).toBeTruthy();
    expect(screen.getAllByText("Wiii Facebook Page").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Đã kết nối").length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("wcn_public_1");
    expect(container.textContent).not.toContain("fb_page_public");
    expect(container.textContent).not.toContain("https://composio.example/connect/safe");
    expect(screen.queryByText("access_token")).toBeNull();
    expect(screen.queryByText("secret-value")).toBeNull();

    openSpy.mockRestore();
  });

  it("shows waiting connection flow after Connect Link is issued before account appears", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockCreateWiiiConnectProviderAuthorizationUrl.mockResolvedValue({
      version: "wiii_connect_provider_adapter.v1",
      status: "ready",
      reason: "authorization_url_issued",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "https://composio.example/connect/safe",
      adapter: {
        version: "wiii_connect_provider_adapter.v1",
        provider_kind: "composio",
        adapter_name: "composio",
        bound: true,
        configured: true,
        can_create_authorization_url: true,
        can_exchange_callback: true,
        can_execute_actions: false,
        authorization_ready: true,
        reason: "configured",
        warnings: [],
      },
      required_next: [],
      audit_event: null,
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "waiting_for_oauth",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 0,
      connections: [],
      connection_lifecycle: {
        version: "wiii_connect_connection_lifecycle.v1",
        provider_slug: "facebook",
        status: "disconnected",
        reason: "waiting_for_oauth",
        active: false,
        connection_present: false,
        agent_ready: false,
        ready_to_connect: true,
        ready_to_execute_action: false,
        required_next: ["complete_provider_oauth"],
      },
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "blocked",
      provider_slug: "facebook",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: false,
      gates: [
        {
          key: "local_connection",
          ready: false,
          reason: "connection_missing",
          required_next: ["complete_provider_oauth"],
        },
        {
          key: "execution_gateway",
          ready: false,
          reason: "connection_missing",
          required_next: ["connect_provider_account"],
        },
      ],
      connection: {
        present: false,
        state: "missing",
        active: false,
        vault_ref_present: false,
        reason: "connection_missing",
      },
      execution_gateway: {
        status: "blocked",
        reason: "connection_missing",
      },
      connection_lifecycle: {
        version: "wiii_connect_connection_lifecycle.v1",
        provider_slug: "facebook",
        status: "disconnected",
        reason: "connection_missing",
        active: false,
        connection_present: false,
        agent_ready: false,
        ready_to_connect: true,
        ready_to_execute_action: false,
        required_next: ["complete_provider_oauth"],
      },
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderEffectiveActions.mockResolvedValue({
      version: "wiii_connect_effective_action_inventory.v1",
      provider_slug: "facebook",
      provider_kind: "composio",
      status: "blocked",
      reason: "connection_missing",
      connection_ref_present: false,
      connection_present: false,
      connection_active: false,
      selected_connection_required: false,
      catalog_action_count: 0,
      runtime_enabled_action_count: 0,
      visible_action_count: 0,
      executable_action_count: 0,
      actions: [],
      storage: { persistent: true },
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: "Kết nối qua Wiii" }));

    await waitFor(() => {
      expect(screen.getByTestId("wiii-connect-connection-flow-state").getAttribute("data-state")).toBe("waiting");
    });
    expect(screen.getByTestId("wiii-connect-next-action").textContent).toContain(
      "Đang chờ OAuth hoàn tất",
    );
    expect(container.textContent).not.toContain("https://composio.example/connect/safe");
    expect(container.textContent).not.toContain("connection_ref");
    expect(container.textContent).not.toContain("access_token");

    openSpy.mockRestore();
  });

  it("shows expired connection flow and keeps expired connection refs hidden", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_expired_1",
          provider_slug: "facebook",
          state: "waiting",
          active: false,
          scopes: { read: true },
          vault_ref_present: true,
          account_label: "Expired Facebook Page",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "legacy_waiting_state",
          warnings: [],
          connection_lifecycle: {
            version: "wiii_connect_connection_lifecycle.v1",
            provider_slug: "facebook",
            status: "expired",
            reason: "oauth_token_expired",
            active: false,
            connection_present: true,
            agent_ready: false,
            ready_to_connect: true,
            ready_to_execute_action: false,
            required_next: ["reconnect_provider_account"],
          },
        },
      ],
      connection_lifecycle: {
        version: "wiii_connect_connection_lifecycle.v1",
        provider_slug: "facebook",
        status: "expired",
        reason: "oauth_token_expired",
        active: false,
        connection_present: true,
        agent_ready: false,
        ready_to_connect: true,
        ready_to_execute_action: false,
        required_next: ["reconnect_provider_account"],
      },
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderActivationReadiness.mockResolvedValue({
      version: "wiii_connect_activation_readiness.v1",
      status: "blocked",
      provider_slug: "facebook",
      provider_kind: "composio",
      ready_to_connect: true,
      ready_to_execute_readonly: false,
      gates: [
        {
          key: "local_connection",
          ready: false,
          reason: "connection_expired",
          required_next: ["reconnect_provider_account"],
        },
        {
          key: "execution_gateway",
          ready: false,
          reason: "connection_expired",
          required_next: ["connect_provider_account"],
        },
      ],
      connection: {
        present: true,
        provider_slug: "facebook",
        state: "waiting",
        active: false,
        scopes: { read: true },
        vault_ref_present: true,
        reason: "legacy_waiting_state",
      },
      execution_gateway: {
        status: "blocked",
        reason: "connection_expired",
      },
      connection_lifecycle: {
        version: "wiii_connect_connection_lifecycle.v1",
        provider_slug: "facebook",
        status: "expired",
        reason: "oauth_token_expired",
        active: false,
        connection_present: true,
        agent_ready: false,
        ready_to_connect: true,
        ready_to_execute_action: false,
        required_next: ["reconnect_provider_account"],
      },
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    mockFetchWiiiConnectProviderEffectiveActions.mockResolvedValue({
      version: "wiii_connect_effective_action_inventory.v1",
      provider_slug: "facebook",
      provider_kind: "composio",
      status: "blocked",
      reason: "connection_expired",
      connection_ref_present: true,
      connection_present: true,
      connection_active: false,
      selected_connection_required: true,
      catalog_action_count: 1,
      runtime_enabled_action_count: 0,
      visible_action_count: 0,
      executable_action_count: 0,
      actions: [],
      storage: { persistent: true },
    });

    const { container } = render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));

    await waitFor(() => {
      expect(screen.getByTestId("wiii-connect-connection-flow-state").getAttribute("data-state")).toBe("expired");
    });
    expect(screen.getByTestId("wiii-connect-next-action").textContent).toContain("reconnect");
    expect(container.textContent).not.toContain("wcn_expired_1");
    expect(container.textContent).not.toContain("connection_ref");
    expect(container.textContent).not.toContain("access_token");
  });

  it("disconnects a provider connection through Wiii backend and keeps payloads sanitized", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockCreateWiiiConnectProviderAuthorizationUrl.mockResolvedValue({
      version: "wiii_connect_provider_adapter.v1",
      status: "ready",
      reason: "authorization_url_issued",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "https://composio.example/connect/safe",
      adapter: {
        version: "wiii_connect_provider_adapter.v1",
        provider_kind: "composio",
        adapter_name: "composio",
        bound: true,
        configured: true,
        can_create_authorization_url: true,
        can_exchange_callback: true,
        can_execute_actions: false,
        authorization_ready: true,
        reason: "configured",
        warnings: [],
      },
      required_next: [],
      audit_event: null,
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_ref: "wcn_public_1",
          provider_slug: "facebook",
          state: "connected",
          active: true,
          scopes: { read: true, write: false },
          vault_ref_present: true,
          account_label: "Wiii Facebook Page",
          external_account_ref_present: true,
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready", access_token: "secret-token" },
      storage: { persistent: true },
    });
    mockDisconnectWiiiConnectProviderConnection.mockResolvedValue({
      version: "wiii_connect_disconnect.v1",
      status: "succeeded",
      reason: "ready",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_present: true,
      local_disabled: true,
      provider: { status: "succeeded", connection_ref_present: true },
      storage: { persistent: true },
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: /qua Wiii$/ }));
    expect((await screen.findAllByText("Wiii Facebook Page")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("wiii-connect-disconnect-button"));

    expect(mockDisconnectWiiiConnectProviderConnection).toHaveBeenCalledWith(
      "facebook",
      "wcn_public_1",
    );
    expect((await screen.findByTestId("wiii-connect-disconnect-status")).textContent).toContain("local");
    expect(screen.getByTestId("wiii-connect-disconnect-button").textContent?.toLowerCase()).toContain("ng");
    expect(screen.getAllByText("user_disconnect_requested").length).toBeGreaterThan(0);
    expect(screen.queryByText("wcn_public_1")).toBeNull();
    expect(screen.queryByText("secret-token")).toBeNull();
    expect(screen.queryByText("access_token")).toBeNull();

    openSpy.mockRestore();
  });

  it("shows sanitized runtime_flow_trace for the latest chat turn", async () => {
    const now = "2026-05-29T00:00:00.000Z";
    useChatStore.setState({
      activeConversationId: "conv-runtime-trace",
      conversations: [
        {
          id: "conv-runtime-trace",
          title: "Runtime trace",
          created_at: now,
          updated_at: now,
          messages: [
            {
              id: "user-runtime-trace",
              role: "user",
              content: "Wiii đăng một bài lên Facebook đi",
              timestamp: now,
            },
            {
              id: "assistant-runtime-trace",
              role: "assistant",
              content: "Đã tạo preview bài đăng Facebook.",
              timestamp: now,
              metadata: {
                processing_time: 1.2,
                provider: "nvidia",
                model: "qwen/qwen3-next-80b-a3b-instruct",
                agent_type: "direct",
                runtime_flow_trace: {
                  version: "wiii.runtime_flow_trace.v1",
                  turn_path_decision: {
                    path: "external_app_action",
                    reason: "external_app_action_request",
                  },
                  tool_policy_session: {
                    bind_tools: true,
                    force_tools: true,
                    visible_tool_names: ["tool_wiii_connect_delegate_to_integration"],
                  },
                  external_app_action_plan: {
                    status: "ready",
                    provider_slug: "facebook",
                    action_slug: "FACEBOOK_CREATE_POST",
                  },
                  external_app_integration_lane: {
                    status: "ready",
                    executor: "provider_worker",
                    provider_slug: "facebook",
                    action_slug: "FACEBOOK_CREATE_POST",
                  },
                  external_action_trace: {
                    observed_action_result: true,
                    result_count: 1,
                    last_status: "action_completed",
                    last_success: true,
                    worker_outcome: "completed",
                    worker_failed_stage: "",
                    worker_reason: "access_token=secret-access-token",
                    provider_slug: "facebook",
                    action_slug: "FACEBOOK_CREATE_POST",
                    integration_worker: {
                      executor: "provider_worker",
                      result_classification: {
                        outcome: "completed",
                        failed_stage: "",
                        reason: "provider_payload=unsafe-provider-body",
                      },
                    },
                    gateway: {
                      status: "allowed",
                      reason: "approved",
                    },
                    access_token: "secret-access-token",
                    raw_payload: "unsafe-provider-body",
                  },
                  final_answer: {
                    source: "wiii_connect_action_result",
                    status: "resolved",
                  },
                },
                runtime_flow_ledger: {
                  schema_version: "wiii.runtime_flow_ledger.v1",
                  request: {
                    host_surface: "desktop_chat",
                    host_capabilities: ["wiii_connect"],
                    request_id: "req-runtime-ledger",
                    user_id_hash: "sha256:1234567890abcdef",
                  },
                  context: {
                    uploaded_document_count: 0,
                    source_ref_count: 0,
                    memory_context_count: 0,
                  },
                  route: {
                    lane: "external_app_action",
                    turn_path_decision: {
                      path: "external_app_action",
                      reason: "external_app_action_request",
                    },
                  },
                  runtime: {
                    provider: "nvidia",
                    model: "qwen3-next",
                    runtime_authoritative: true,
                  },
                  tools: {
                    observed: ["tool_wiii_connect_delegate_to_integration"],
                    suppressed: ["pointy_action", "visual_runtime", "code_studio"],
                    policy_session: {
                      visible_tool_names: ["tool_wiii_connect_delegate_to_integration"],
                    },
                    policy_denials: [
                      {
                        tool_name: "pointy_action",
                        reason: "not_visible_in_bound_tool_set",
                      },
                    ],
                  },
                  stream: {
                    transport: "sse_v3",
                    event_counts: {
                      answer: 1,
                      tool_call: 1,
                      tool_result: 1,
                      metadata: 1,
                      done: 1,
                    },
                    event_sequence_tail: ["answer", "metadata", "done"],
                    metadata_seen: true,
                    done_seen: true,
                  },
                  host_actions: {
                    preview_required: false,
                    apply_attempted: false,
                    result_received: true,
                    result_success: true,
                  },
                  finalization: {
                    status: "saved",
                  },
                },
              },
            },
          ],
        },
      ],
      pendingStreamMetadata: null,
    });

    const { container } = render(<WiiiConnectPage />);

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Wiii Connect" })).getByRole(
        "button",
        { name: /Runtime/i },
      ),
    );

    const tracePanel = await screen.findByTestId("wiii-connect-runtime-flow-trace");
    const ledgerPanel = await screen.findByTestId("wiii-connect-runtime-flow-ledger");
    const doctorPanel = await screen.findByTestId("wiii-connect-doctor-panel");
    expect(ledgerPanel.textContent).toContain("wiii.runtime_flow_ledger.v1");
    expect(ledgerPanel.textContent).toContain("external_app_action");
    expect(ledgerPanel.textContent).toContain("Route decision");
    expect(ledgerPanel.textContent).toContain("external_app_action_request");
    expect(ledgerPanel.textContent).toContain("Provider/model");
    expect(ledgerPanel.textContent).toContain("nvidia");
    expect(ledgerPanel.textContent).toContain("qwen3-next");
    expect(ledgerPanel.textContent).toContain("Tool loop");
    expect(ledgerPanel.textContent).toContain("calls 1");
    expect(ledgerPanel.textContent).toContain("results 1");
    expect(ledgerPanel.textContent).toContain("denials 1");
    expect(ledgerPanel.textContent).toContain("desktop_chat");
    expect(ledgerPanel.textContent).toContain("tool_wiii_connect_delegate_to_integration");
    expect(ledgerPanel.textContent).toContain("pointy_action");
    expect(ledgerPanel.textContent).toContain("Có");
    expect(tracePanel.textContent).toContain("external_app_action");
    expect(tracePanel.textContent).toContain("provider_worker");
    expect(tracePanel.textContent).toContain("FACEBOOK_CREATE_POST");
    expect(tracePanel.textContent).toContain("Worker");
    expect(tracePanel.textContent).toContain("completed");
    expect(tracePanel.textContent).toContain("[redacted]");
    expect(tracePanel.textContent).toContain("action_completed");
    expect(tracePanel.textContent).toContain("wiii_connect_action_result");
    expect(doctorPanel.textContent).toContain("Runtime doctor");
    expect(doctorPanel.textContent).toContain("no_agent_ready_external_provider");
    expect(doctorPanel.textContent).toContain("Facebook");
    expect(doctorPanel.textContent).toContain("connection_storage_unavailable");
    expect(doctorPanel.textContent).toContain("Registry");
    expect(doctorPanel.textContent).toContain("Adapter");
    expect(doctorPanel.textContent).toContain("Account");
    expect(doctorPanel.textContent).toContain("Agent policy");
    expect(doctorPanel.textContent).toContain("Gateway");
    expect(doctorPanel.textContent).toContain("configure_wiii_connect_storage");
    expect(container.textContent).not.toContain("secret-access-token");
    expect(container.textContent).not.toContain("unsafe-provider-body");
    expect(container.textContent).not.toContain("access_token");
    expect(container.textContent).not.toContain("raw_payload");
  });

  it("shows aggregate runtime-flow doctor counts without raw ids", async () => {
    mockFetchRecentRuntimeFlowDoctor.mockResolvedValue({
      version: "wiii.runtime_flow_doctor.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      status: "degraded",
      alerts: [
        {
          code: "missing_request_id",
          severity: "warning",
          count: 1,
          threshold: "count>0",
        },
        {
          code: "authorization=Bearer raw-doctor-token",
          severity: "critical",
          count: 1,
          threshold: "count>0",
        },
      ],
      summary: {
        turn_count: 3,
        done_seen_count: 2,
        missing_done_count: 1,
        metadata_seen_count: 2,
        uploaded_document_turns: 1,
        memory_context_turns: 1,
        source_ref_total: 4,
        context_provenance_turns: 3,
        context_warning_count: 2,
        failed_finalization_count: 1,
        raw_content_flag_count: 0,
      },
      request_correlation: {
        request_id_present_count: 2,
        missing_request_id_count: 1,
        provider_call_turn_count: 1,
        provider_call_correlated_turn_count: 0,
        provider_call_uncorrelated_turn_count: 1,
        provider_call_stage_count: 2,
        provider_call_stage_request_id_present_count: 1,
        provider_call_stage_request_id_missing_count: 1,
        provider_call_stage_request_id_match_count: 1,
        provider_call_stage_request_id_mismatch_count: 0,
        identifier_strategy: "presence_counts_only",
      },
      subagents: {
        turn_count: 1,
        report_count: 2,
        state_projected_key_count: 6,
        state_dropped_key_count: 5,
        source_count: 3,
        tool_count: 2,
        thinking_dropped_count: 1,
        raw_content_flag_count: 0,
        warning_count: 1,
        warnings: {
          state_top_level_keys_dropped: 1,
          "PRIVATE SUBAGENT WARNING SHOULD NOT APPEAR": 1,
        },
        identifier_strategy: "aggregate_counts_only",
      },
      routes: {
        external_app_action: 2,
        "PRIVATE ROUTE SHOULD NOT APPEAR": 1,
        wcn_secret_route: 1,
      },
      finalization_statuses: { saved: 2, failed: 1 },
      stream_events: { done: 2, metadata: 2 },
      suppressed_tools: { pointy_action: 2 },
      observed_tools: { tool_wiii_connect_delegate_to_integration: 1 },
      context_warnings: {
        document_context_truncated: 1,
        "PRIVATE WARNING SHOULD NOT APPEAR": 1,
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      alert_trend: {
        bucket_strategy: "event_created_at_hour",
        identifier_strategy: "aggregate_counts_only",
        buckets: [
          {
            bucket_start: "2026-05-31T10:00:00+00:00",
            turn_count: 2,
            alert_counts: {
              missing_request_id: 1,
              "PRIVATE ALERT SHOULD NOT APPEAR": 1,
            },
            status_counts: { degraded: 2 },
          },
        ],
      },
      source: {
        session_event_count: 4,
        runtime_flow_ledger_event_count: 3,
        limit: 50,
        org_scoped: true,
        window: "recent_runtime_flow_ledger_events",
      },
      runtime_config: {
        native_stream_dispatch_enabled: true,
        session_event_log_backend: "postgres",
        lifecycle_hook_total: 2,
        lifecycle_hook_owner_count: 1,
        lifecycle_on_run_end_hook_count: 1,
        lifecycle_on_run_error_hook_count: 1,
      },
      lifecycle_registrations: {
        version: "wiii.runtime_lifecycle_registrations.v1",
        registration_count: 2,
        owner_counts: {
          "engine.runtime": 2,
          "PRIVATE LIFECYCLE OWNER SHOULD NOT APPEAR": 1,
        },
        point_counts: { on_run_end: 1, on_run_error: 1 },
        default_runtime_hooks: {
          owner: "engine.runtime",
          required_count: 2,
          registered_count: 2,
          installed: true,
          hooks: [
            {
              point: "on_run_end",
              owner: "engine.runtime",
              name: "runtime_flow_session_event_finalization",
              registered: true,
            },
            {
              point: "on_run_error",
              owner: "engine.runtime",
              name: "authorization=Bearer raw-doctor-token",
              registered: true,
            },
          ],
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "code_metadata_only",
        },
      },
      post_turn_lifecycle: {
        version: "wiii.post_turn_lifecycle_metrics.v1",
        post_turn: {
          event_count: 3,
          status_counts: { scheduled: 2, skipped: 1 },
          reason_counts: {
            post_turn_background_tasks_scheduled: 2,
            "PRIVATE POST TURN SHOULD NOT APPEAR": 1,
          },
          transport_counts: { sync: 2, other: 1 },
          semantic_memory_policy_counts: {
            extract_facts: 2,
            not_applicable: 1,
          },
        },
        background_tasks: {
          event_count: 4,
          group_counts: {
            semantic_memory_interaction: 2,
            memory_summarizer: 1,
            "authorization=Bearer raw-post-turn-token": 1,
          },
          status_counts: { scheduled: 3, skipped: 1 },
          reason_counts: {
            extract_facts: 2,
            missing_dependency: 1,
          },
        },
        source: {
          metrics_backend: "runtime_metrics.snapshot",
          window: "process_lifetime_in_memory",
          org_scoped: false,
          counter_names: {
            post_turn: "runtime.post_turn.lifecycle.scheduling",
            background_tasks: "runtime.background_tasks.scheduling",
          },
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
      },
      post_turn_lifecycle_ledger: {
        version: "wiii.post_turn_lifecycle_ledger.v1",
        event_count: 2,
        missing_count: 1,
        status_counts: { scheduled: 2 },
        reason_counts: { post_turn_background_tasks_scheduled: 2 },
        semantic_memory_policy_counts: { extract_facts: 2 },
        background_tasks_scheduled_count: 2,
        background_tasks_skipped_count: 0,
        raw_content_flag_count: 0,
        background_schedule: {
          event_count: 2,
          task_count: 4,
          group_counts: {
            semantic_memory_interaction: 2,
            semantic_memory_maintenance: 2,
            "PRIVATE LEDGER GROUP SHOULD NOT APPEAR": 1,
          },
          status_counts: { scheduled: 4 },
          reason_counts: {
            extract_facts: 2,
            after_interaction_write: 2,
          },
        },
        source: {
          ledger_path: "finalization.post_turn_lifecycle",
          window: "runtime_flow_ledger_events",
        },
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
      },
    });
    mockFetchRuntimeFlowDoctorHistory.mockResolvedValue({
      version: "wiii.runtime_flow_doctor_history.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      bucket_strategy: "event_created_at_hour",
      identifier_strategy: "aggregate_counts_only",
      buckets: [
        {
          bucket_start: "2026-05-31T11:00:00+00:00",
          status: "degraded",
          alerts: [
            {
              code: "missing_request_id",
              severity: "warning",
              count: 1,
              threshold: "count>0",
            },
          ],
          summary: {
            turn_count: 3,
            done_seen_count: 2,
            missing_done_count: 1,
          },
          request_correlation: {
            missing_request_id_count: 1,
          },
          subagents: {
            turn_count: 1,
            report_count: 2,
            state_projected_key_count: 6,
            state_dropped_key_count: 5,
            source_count: 3,
            tool_count: 2,
            thinking_dropped_count: 1,
            raw_content_flag_count: 0,
            warning_count: 1,
            warnings: {
              state_top_level_keys_dropped: 1,
            },
            identifier_strategy: "aggregate_counts_only",
          },
          routes: {
            external_app_action: 2,
            "PRIVATE HISTORY ROUTE SHOULD NOT APPEAR": 1,
          },
          finalization_statuses: { saved: 2, failed: 1 },
          context_warnings: {
            "PRIVATE HISTORY WARNING SHOULD NOT APPEAR": 1,
          },
          source: {
            session_event_count: 3,
            runtime_flow_ledger_event_count: 3,
          },
        },
      ],
      source: {
        session_event_count: 3,
        runtime_flow_ledger_event_count: 3,
        bucket_count: 1,
        bucket_limit: 24,
        limit: 500,
        org_scoped: true,
        window: "recent_runtime_flow_ledger_history",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "postgres",
      },
    });
    mockFetchRecentSemanticMemoryDoctor.mockResolvedValue({
      version: "wiii.semantic_memory_write_doctor.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      status: "degraded",
      summary: {
        write_count: 2,
        message_saved_count: 1,
        response_saved_count: 1,
        fact_extraction_requested_count: 1,
        stored_fact_total: 2,
        stored_insight_total: 1,
        blocked_count: 0,
        failed_count: 0,
        degraded_count: 1,
        warning_count: 1,
        raw_content_flag_count: 0,
      },
      write_kinds: {
        interaction: 1,
        insight_store: 1,
        "PRIVATE MEMORY KIND SHOULD NOT APPEAR": 1,
      },
      write_statuses: { saved: 1, degraded: 1 },
      organization_contexts: { request_scoped: 2 },
      warnings: {
        insight_store_degraded: 1,
        "authorization=Bearer raw-memory-token": 1,
      },
      source: {
        session_event_count: 3,
        semantic_memory_write_event_count: 2,
        limit: 50,
        org_scoped: true,
        window: "recent_semantic_memory_write_events",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "postgres",
      },
    });
    mockFetchSemanticMemoryDoctorHistory.mockResolvedValue({
      version: "wiii.semantic_memory_write_doctor_history.v1",
      generated_at: "2026-05-31T00:00:00.000Z",
      bucket_strategy: "event_created_at_hour",
      identifier_strategy: "aggregate_counts_only",
      buckets: [
        {
          bucket_start: "2026-05-31T11:00:00+00:00",
          status: "degraded",
          summary: {
            write_count: 2,
            stored_fact_total: 2,
            stored_insight_total: 1,
            blocked_count: 0,
            warning_count: 1,
          },
          write_kinds: {
            interaction: 1,
            "PRIVATE HISTORY KIND SHOULD NOT APPEAR": 1,
          },
          write_statuses: { saved: 1, degraded: 1 },
          organization_contexts: { request_scoped: 2 },
          warnings: {
            insight_store_degraded: 1,
            "PRIVATE HISTORY WARNING SHOULD NOT APPEAR": 1,
          },
          source: {
            session_event_count: 2,
            semantic_memory_write_event_count: 2,
          },
        },
      ],
      source: {
        session_event_count: 3,
        semantic_memory_write_event_count: 2,
        bucket_count: 1,
        bucket_limit: 24,
        limit: 500,
        org_scoped: true,
        window: "recent_semantic_memory_write_history",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "aggregate_counts_only",
      },
      runtime_config: {
        session_event_log_backend: "postgres",
      },
    });

    const { container } = render(<WiiiConnectPage />);

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Wiii Connect" })).getByRole(
        "button",
        { name: /Runtime/i },
      ),
    );

    const panel = await screen.findByTestId("wiii-connect-runtime-flow-doctor-panel");
    expect(panel.textContent).toContain("Aggregate runtime doctor");
    expect(panel.textContent).toContain("degraded");
    expect(panel.textContent).toContain("missing_request_id");
    expect(panel.textContent).toContain("external_app_action");
    expect(panel.textContent).toContain("document_context_truncated");
    expect(panel.textContent).toContain("Subagent reports");
    expect(panel.textContent).toContain("Dropped keys");
    expect(panel.textContent).toContain("state_top_level_keys_dropped");
    expect(panel.textContent).toContain("postgres");
    expect(panel.textContent).toContain("aggregate_counts_only");
    expect(panel.textContent).toContain("Events: 3/4");
    const lifecyclePanel = await screen.findByTestId("wiii-connect-runtime-lifecycle-hooks");
    expect(lifecyclePanel.textContent).toContain("Lifecycle hooks");
    expect(lifecyclePanel.textContent).toContain("2 hooks / 1 owners");
    expect(lifecyclePanel.textContent).toContain("installed");
    expect(lifecyclePanel.textContent).toContain("end 1 / error 1");
    expect(lifecyclePanel.textContent).toContain("code_metadata_only");
    const postTurnPanel = await screen.findByTestId("wiii-connect-runtime-post-turn-lifecycle");
    expect(postTurnPanel.textContent).toContain("Post-turn lifecycle");
    expect(postTurnPanel.textContent).toContain("wiii.post_turn_lifecycle_metrics.v1");
    expect(postTurnPanel.textContent).toContain("wiii.post_turn_lifecycle_ledger.v1");
    expect(postTurnPanel.textContent).toContain("Post-turn events");
    expect(postTurnPanel.textContent).toContain("3");
    expect(postTurnPanel.textContent).toContain("Background events");
    expect(postTurnPanel.textContent).toContain("4");
    expect(postTurnPanel.textContent).toContain("Durable events");
    expect(postTurnPanel.textContent).toContain("Missing ledger");
    expect(postTurnPanel.textContent).toContain("Durable task count");
    expect(postTurnPanel.textContent).toContain("post_turn_background_tasks_scheduled");
    expect(postTurnPanel.textContent).toContain("semantic_memory_interaction");
    expect(postTurnPanel.textContent).toContain("semantic_memory_maintenance");
    expect(postTurnPanel.textContent).toContain("memory_summarizer");
    expect(postTurnPanel.textContent).toContain("process_lifetime_in_memory");
    expect(postTurnPanel.textContent).toContain("ledger_events");
    expect(postTurnPanel.textContent).toContain("process-wide");
    expect(postTurnPanel.textContent).toContain("aggregate_counts_only");
    const historyPanel = await screen.findByTestId("wiii-connect-runtime-flow-doctor-history");
    expect(panel.textContent).toContain("Doctor history");
    expect(historyPanel.textContent).toContain("missing_request_id");
    expect(historyPanel.textContent).toContain("external_app_action");
    expect(historyPanel.textContent).toContain("2 reports / 1 warnings");
    expect(historyPanel.textContent).toContain("3");
    const memoryPanel = await screen.findByTestId("wiii-connect-semantic-memory-doctor-panel");
    expect(memoryPanel.textContent).toContain("Semantic memory doctor");
    expect(memoryPanel.textContent).toContain("Memory write history");
    expect(memoryPanel.textContent).toContain("degraded");
    expect(memoryPanel.textContent).toContain("interaction");
    expect(memoryPanel.textContent).toContain("request_scoped");
    expect(memoryPanel.textContent).toContain("insight_store_degraded");
    expect(memoryPanel.textContent).toContain("Events: 2/3");
    expect(memoryPanel.textContent).toContain("postgres");
    expect(memoryPanel.textContent).toContain("aggregate_counts_only");
    const memoryHistory = await screen.findByTestId("wiii-connect-semantic-memory-doctor-history");
    expect(memoryHistory.textContent).toContain("interaction 1");
    expect(memoryHistory.textContent).toContain("2");
    expect(container.textContent).not.toContain("raw-doctor-token");
    expect(container.textContent).not.toContain("raw-memory-token");
    expect(container.textContent).not.toContain("PRIVATE ROUTE SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE WARNING SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE ALERT SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE SUBAGENT WARNING SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE LIFECYCLE OWNER SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE POST TURN SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE LEDGER GROUP SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("raw-post-turn-token");
    expect(container.textContent).not.toContain("PRIVATE HISTORY ROUTE SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE HISTORY WARNING SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE MEMORY KIND SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("PRIVATE HISTORY KIND SHOULD NOT APPEAR");
    expect(container.textContent).not.toContain("wcn_secret_route");
    expect(container.textContent).not.toContain("authorization=Bearer");
  });

  it("runs runtime-flow session event retention dry-run before prune apply", async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      isLoaded: true,
      authMode: "oauth",
      tokens: null,
      user: {
        id: "platform-admin",
        email: "admin@example.test",
        name: "Platform Admin",
        role: "admin",
        platform_role: "platform_admin",
        active_organization_id: "org-secret-retention",
      },
    });
    mockPruneRuntimeFlowSessionEvents
      .mockResolvedValueOnce({
        schema: "wiii.session_event_log_prune.v1",
        status: "dry_run",
        matched_count: 2,
        deleted_count: 0,
        retention_days: 30,
        cutoff: "2026-05-01T00:00:00+00:00",
        dry_run: true,
        org_scoped: true,
        event_type_filter_applied: true,
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
        runtime_config: {
          session_event_log_backend: "postgres",
        },
      })
      .mockResolvedValueOnce({
        schema: "wiii.session_event_log_prune.v1",
        status: "pruned",
        matched_count: 2,
        deleted_count: 2,
        retention_days: 30,
        cutoff: "2026-05-01T00:00:00+00:00",
        dry_run: false,
        org_scoped: true,
        event_type_filter_applied: true,
        privacy: {
          raw_content_included: false,
          identifier_strategy: "aggregate_counts_only",
        },
        runtime_config: {
          session_event_log_backend: "postgres",
        },
      });

    const { container } = render(<WiiiConnectPage />);

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Wiii Connect" })).getByRole(
        "button",
        { name: /Runtime/i },
      ),
    );

    await screen.findByTestId("wiii-connect-runtime-flow-doctor-panel");
    const dryRunButton = await screen.findByTestId("wiii-connect-runtime-prune-dry-run");
    const applyButton = await screen.findByTestId("wiii-connect-runtime-prune-apply");
    expect((applyButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(dryRunButton);

    await waitFor(() => {
      expect(mockPruneRuntimeFlowSessionEvents).toHaveBeenCalledWith(
        expect.objectContaining({
          dryRun: true,
          eventType: "runtime_flow_ledger",
          orgId: "org-secret-retention",
        }),
      );
    });
    const report = screen.getByTestId("wiii-connect-runtime-prune-report");
    await waitFor(() => {
      expect(report.textContent).toContain("Matched");
      expect(report.textContent).toContain("2");
      expect((applyButton as HTMLButtonElement).disabled).toBe(false);
    });

    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(mockPruneRuntimeFlowSessionEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({
          dryRun: false,
          eventType: "runtime_flow_ledger",
          orgId: "org-secret-retention",
          retentionDays: 30,
        }),
      );
    });
    await waitFor(() => {
      expect(report.textContent).toContain("Deleted");
      expect(report.textContent).toContain("2");
    });
    const aggregatePanel = screen.getByTestId("wiii-connect-runtime-flow-doctor-panel");
    expect(container.textContent).toContain("aggregate_counts_only");
    expect(container.textContent).not.toContain("org-secret-retention");
    expect(aggregatePanel.textContent).not.toContain("runtime_flow_ledger");
    expect(container.textContent).not.toContain("raw_payload");
    expect(container.textContent).not.toContain("access_token");
  });

  it("redacts sensitive doctor lifecycle fields before rendering", async () => {
    mockFetchWiiiConnectDoctor.mockResolvedValue({
      version: "wiii_connect_doctor.v0",
      generated_at: "2026-05-29T00:00:00.000Z",
      surface: "desktop",
      status: "degraded",
      summary: {
        total_paths: 2,
        ready_paths: 1,
        guarded_paths: 1,
        blocked_paths: 0,
        total_connections: 2,
        agent_ready_connections: 1,
        external_provider_connections: 1,
        external_agent_ready_connections: 1,
        warning_count: 0,
      },
      path_diagnostics: [
        {
          path: "casual_chat",
          status: "ready",
          reason: "ready",
        },
        {
          path: "external_app_action",
          status: "guarded",
          reason: "approval_token=secret-token",
          missing_connection_slugs: ["wcn_secret_path"],
          blocked_connection_reasons: ["Bearer secret"],
          mutation_policy: "approval_token_required",
          delegation_policy: "delegate_to_integrations_agent",
        },
      ],
      provider_diagnostics: [
        {
          provider_slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          status: "guarded",
          reason: "access_token=secret-token",
          connection_status: "connected",
          active: true,
          agent_ready: true,
          connection_count: 1,
          active_connection_count: 1,
          action_count: 1,
          scope_count: 3,
          required_next: ["connection_ref=wcn_secret_ref"],
          stages: [
            {
              key: "registry",
              status: "ready",
              reason: "registered",
              required_next: [],
            },
            {
              key: "adapter",
              status: "ready",
              reason: "authorization=Bearer secret",
              required_next: [],
            },
            {
              key: "account",
              status: "ready",
              reason: "ca_secret_account",
              required_next: [],
            },
            {
              key: "agent_policy",
              status: "ready",
              reason: "scope_policy",
              required_next: [],
            },
            {
              key: "gateway",
              status: "pending",
              reason: "provider_payload=raw",
              required_next: ["ak_secret"],
            },
          ],
        },
      ],
      top_blockers: ["refresh_token=secret-refresh"],
      warnings: [],
    });

    const { container } = render(<WiiiConnectPage />);

    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Wiii Connect" })).getByRole(
        "button",
        { name: /Runtime/i },
      ),
    );

    const doctorPanel = await screen.findByTestId("wiii-connect-doctor-panel");
    expect(doctorPanel.textContent).toContain("Facebook");
    expect(doctorPanel.textContent).toContain("Registry");
    expect(doctorPanel.textContent).toContain("Gateway");
    expect(doctorPanel.textContent).toContain("[đã ẩn]");
    expect(container.textContent).not.toContain("secret-token");
    expect(container.textContent).not.toContain("wcn_secret");
    expect(container.textContent).not.toContain("Bearer secret");
    expect(container.textContent).not.toContain("ca_secret_account");
    expect(container.textContent).not.toContain("provider_payload");
    expect(container.textContent).not.toContain("secret-refresh");
    expect(container.textContent).not.toContain("ak_secret");
  });
});
