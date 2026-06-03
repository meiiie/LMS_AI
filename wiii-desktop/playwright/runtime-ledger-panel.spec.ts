import { readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Frame, type Page } from "@playwright/test";

type BrowserTarget = Frame | Page;
type BrowserReplayCase = {
  schema?: string;
  scenario_id?: string;
  prompt_hash?: string;
  path: string;
  event_names?: string[];
  assistant_content: string;
  assistant_metadata: Record<string, unknown>;
  timing?: Record<string, unknown>;
};
type RuntimeAcceptanceBrowserReplayEvidence = {
  schema: string;
  generated_at?: string;
  browser_replay: {
    schema: string;
    cases: BrowserReplayCase[];
  };
};

const USER_ID = "runtime-ledger-browser-user";
const RAW_TOKEN = "runtime-ledger-secret-token";
const EMBED_USER_ID = "embed-lms-runtime-user";
const EMBED_ORG_ID = "maritime-lms";
const EMBED_DOMAIN_ID = "maritime";
const EMBED_SESSION_ID = "embed-lms-runtime-session";
const PLAYWRIGHT_FRONTEND_ORIGIN =
  process.env.WIII_PLAYWRIGHT_BASE_URL ||
  `http://127.0.0.1:${process.env.WIII_PLAYWRIGHT_FRONTEND_PORT || "1420"}`;
const EMBED_COURSE_MARKDOWN =
  "# Bridge Resource Management\n\nCOLREG watchkeeping lesson with STCW scenario evidence.";

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function looksSensitiveBrowserReplayText(value: string): boolean {
  const text = value.trim();
  const lower = text.toLowerCase();
  if (!text) return false;
  if (lower.startsWith("bearer ")) return true;
  if (
    lower.includes("access_token=") ||
    lower.includes("refresh_token=") ||
    lower.includes("approval_token=") ||
    lower.includes("provider_payload=") ||
    lower.includes("raw_payload=")
  ) {
    return true;
  }
  if (/^(sk-|ak_|tp-|wcn_|ca_)/i.test(text)) return true;
  if (/^eyJ[\w-]*\.[\w-]*\.[\w-]*$/.test(text)) return true;
  return false;
}

const forbiddenBrowserReplayRawKeys = new Set([
  "prompt",
  "user_prompt",
  "prompt_text",
  "raw_prompt",
  "answer",
  "answer_text",
  "raw_answer",
  "answer_preview",
  "sse_events",
  "event_payloads",
  "raw_sse_events",
  "raw_events",
  "raw_event_payloads",
  "event_data",
  "sse_data",
  "message",
  "messages",
  "content",
  "raw_data",
  "raw_payload",
  "provider_payload",
  "request_payload",
  "response_payload",
  "params",
  "arguments",
]);

function isRawReplayValue(value: unknown): boolean {
  return typeof value === "string" ||
    Array.isArray(value) ||
    Boolean(value && typeof value === "object");
}

function assertBrowserReplayEvidenceIsSanitized(value: unknown, path = "evidence"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertBrowserReplayEvidenceIsSanitized(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
      const normalized = key.trim().toLowerCase();
      const childPath = `${path}.${key}`;
      if (forbiddenBrowserReplayRawKeys.has(normalized) && isRawReplayValue(item)) {
        throw new Error(`${childPath} exposes a raw replay field`);
      }
      assertBrowserReplayEvidenceIsSanitized(item, childPath);
    });
    return;
  }
  if (typeof value === "string" && looksSensitiveBrowserReplayText(value)) {
    throw new Error(`${path} exposes a sensitive replay value`);
  }
}

function nowIso(): string {
  return new Date("2026-05-31T12:00:00.000Z").toISOString();
}

function base64Url(value: string): string {
  return Buffer.from(value, "utf8")
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function unsignedJwt(payload: Record<string, unknown>): string {
  return [
    base64Url(JSON.stringify({ alg: "none", typ: "JWT" })),
    base64Url(JSON.stringify(payload)),
    "signature",
  ].join(".");
}

function embedLmsHashParams(): URLSearchParams {
  const token = unsignedJwt({
    sub: EMBED_USER_ID,
    email: "embed-lms-runtime@example.test",
    name: "Embed LMS Teacher",
    role: "teacher",
    legacy_role: "teacher",
    platform_role: "user",
    organization_role: "member",
    active_organization_id: EMBED_ORG_ID,
    connector_id: "playwright-lms",
    identity_version: "v2",
  });
  return new URLSearchParams({
    token,
    refresh_token: "embed-refresh-token",
    org: EMBED_ORG_ID,
    domain: EMBED_DOMAIN_ID,
    server: PLAYWRIGHT_FRONTEND_ORIGIN,
    role: "teacher",
    hide_welcome: "true",
    mode: "widget",
    session_id: EMBED_SESSION_ID,
  });
}

function runtimeLedger() {
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "browser-runtime-ledger",
      session_id: "browser-runtime-ledger-session",
      user_id_hash: "browser-runtime-ledger-user-hash",
      organization_id_hash: "browser-runtime-ledger-org-hash",
      host_surface: "desktop_chat",
      host_capabilities: [
        "wiii_connect",
        `Bearer ${RAW_TOKEN}`,
        "visual_runtime",
        "code_studio",
      ],
    },
    context: {
      document_context_present: false,
      uploaded_document_count: 0,
      source_ref_count: 2,
      memory_context_count: 1,
      context_provenance: {
        uploaded_documents: 0,
        source_references: 2,
        memory_items: 1,
      },
    },
    route: {
      lane: "external_app_action",
      reason: "browser_runtime_ledger_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: "external_app_action",
        reason: "Wiii Connect delegated to integration.",
        bind_tools: true,
        force_tools: false,
      },
    },
    runtime: {
      provider: "browser-harness",
      model: "runtime-ledger-panel-mock",
      runtime_authoritative: true,
      fallback_used: false,
      failover_used: false,
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
          path: "external_app_action",
          reason: "not_visible_in_bound_tool_set",
        },
      ],
    },
    stream: {
      transport: "sse_v3",
      event_counts: {
        answer: 2,
        tool_call: 1,
        tool_result: 1,
        metadata: 1,
        done: 1,
      },
      event_sequence_tail: ["answer", "answer", "metadata", "done"],
      metadata_seen: true,
      done_seen: true,
    },
    host_actions: {
      preview_required: false,
      preview_emitted: false,
      approval_token_present: false,
      apply_attempted: false,
      result_received: true,
      result_success: true,
      result_statuses: ["action_completed"],
    },
    finalization: {
      status: "saved",
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function embedLmsRuntimeLedger() {
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "embed-lms-browser-ledger",
      session_id: EMBED_SESSION_ID,
      user_id_hash: "embed-lms-user-hash",
      organization_id_hash: "embed-lms-org-hash",
      host_surface: "embed_lms",
      host_capabilities: ["lms", "host_action", "document_preview"],
    },
    context: {
      document_context_present: true,
      uploaded_document_count: 1,
      source_ref_count: 2,
      memory_context_count: 0,
      context_provenance: {
        schema_version: "wiii.context_provenance_ledger.v1",
        conversation: {
          history_present: false,
          history_item_count: 0,
          summary_present: false,
        },
        documents: {
          present: true,
          attachment_count: 1,
          usable_attachment_count: 1,
          total_markdown_chars: EMBED_COURSE_MARKDOWN.length,
          truncated_count: 0,
          parser_names: ["markdown_parser"],
          parser_chain_names: ["frontmatter", "markdown"],
          media_kinds: ["document"],
          provenance_levels: ["page_marker"],
          attachment_id_hashes: ["sha256:embedlessonhash"],
          source_ref_count: 2,
          source_ref_kinds: ["lesson_section", "course_citation"],
        },
        memory: {
          semantic_context_present: false,
          semantic_memory_count: 0,
          semantic_memory_types: [],
          retrieval_present: false,
          retrieval_status: "unknown",
          fact_type_names: [],
          insight_category_names: [],
          core_memory_present: false,
          episodic_retrieval_present: false,
          episodic_retrieval_status: "unknown",
          episodic_event_types: [],
          episodic_org_scoped: false,
          episodic_current_session_excluded: false,
          episodic_raw_content_included: false,
          warning_codes: [],
        },
        host: {
          host_context_present: true,
          surface: "embed_lms",
          capability_names: ["lms", "host_action", "document_preview"],
          available_action_count: 1,
          host_capabilities_present: true,
        },
        warnings: [],
        privacy: {
          raw_content_included: false,
          identifier_strategy: "hash_or_count_only",
        },
      },
    },
    route: {
      lane: "lms_document_preview",
      reason: "embed_lms_document_upload_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: "lms_document_preview",
        reason: "Embed LMS course content with document preview capability.",
        bind_tools: true,
        force_tools: false,
      },
    },
    runtime: {
      provider: "browser-harness",
      model: "embed-lms-ledger-mock",
      runtime_authoritative: true,
      fallback_used: false,
      failover_used: false,
    },
    tools: {
      observed: ["tool_lms_document_preview"],
      suppressed: ["pointy_action", "visual_runtime", "code_studio"],
    },
    stream: {
      transport: "sse_v3",
      event_counts: {
        answer: 1,
        preview: 1,
        metadata: 1,
        done: 1,
      },
      event_sequence_tail: ["answer", "preview", "metadata", "done"],
      metadata_seen: true,
      done_seen: true,
    },
    host_actions: {
      preview_required: true,
      preview_emitted: true,
      approval_token_present: true,
      apply_attempted: false,
    },
    finalization: {
      status: "saved",
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function embedLmsRuntimeTrace() {
  return {
    version: "wiii.runtime_flow_trace.v1",
    turn_path_decision: {
      path: "lms_document_preview",
      reason: "Embed LMS course content with document preview capability.",
    },
    tool_policy_session: {
      bind_tools: true,
      force_tools: false,
      visible_tool_names: ["tool_lms_document_preview"],
    },
    final_answer: {
      source: "lms_document_preview",
      status: "ready",
    },
  };
}

function embedLmsHostActionPreview() {
  return {
    preview_type: "host_action",
    preview_id: "embed-lms-lesson-preview",
    title: "Preview cập nhật bài học LMS",
    snippet: "Bản nháp lesson patch từ tài liệu khóa học đã tải lên.",
    url: "https://lms.example.test/courses/bridge-101/lessons/watchkeeping",
    metadata: {
      preview_kind: "lesson_patch",
      action: "authoring.preview_lesson_patch",
      apply_action: "authoring.apply_lesson_patch",
      preview_token: "preview-token-browser-lms",
      approval_token: "approval-lesson-browser-lms",
      target_label: "Bridge Resource Management",
      course_id: "bridge-101",
      lesson_id: "watchkeeping",
      workflow_stage: "lesson_drafting",
      requires_confirmation: true,
      changed_fields: ["objectives", "content"],
      changed_count: 2,
      next_step: "Giáo viên xác nhận trong host bridge trước khi LMS nhận apply.",
      source_references: [
        {
          kind: "lesson_section",
          chapter_index: 0,
          lesson_index: 0,
          source_pages: [1],
          excerpt: "COLREG watchkeeping lesson",
        },
        {
          kind: "course_citation",
          source_pages: [1],
          excerpt: "STCW scenario evidence",
        },
      ],
      lesson_before: {
        title: "Bridge Resource Management",
        objectives: ["Review existing watchkeeping notes."],
      },
      lesson_after: {
        title: "Bridge Resource Management",
        objectives: [
          "Explain COLREG watchkeeping responsibilities.",
          "Apply STCW scenario evidence in bridge decisions.",
        ],
      },
    },
  };
}

function runtimeTrace() {
  return {
    version: "wiii.runtime_flow_trace.v1",
    turn_path_decision: {
      path: "external_app_action",
      reason: "Wiii Connect delegated to integration.",
    },
    tool_policy_session: {
      bind_tools: true,
      force_tools: false,
      visible_tool_names: ["tool_wiii_connect_delegate_to_integration"],
    },
    external_app_integration_lane: {
      executor: "integration_worker",
      provider_slug: "wiii_connect",
      action_slug: "delegate_to_integration",
      status: "ready",
    },
    external_action_trace: {
      provider_slug: "wiii_connect",
      action_slug: "delegate_to_integration",
      last_status: "action_completed",
      last_success: true,
      worker_outcome: "completed",
    },
    final_answer: {
      source: "explicit_action_result",
      status: "ready",
    },
  };
}

function streamRuntimeLedger() {
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "browser-runtime-ledger-stream",
      session_id: "browser-runtime-ledger-stream-session",
      user_id_hash: "browser-runtime-ledger-user-hash",
      organization_id_hash: "browser-runtime-ledger-org-hash",
      host_surface: "desktop_chat",
      host_capabilities: ["visual_runtime", "code_studio"],
    },
    context: {
      document_context_present: false,
      uploaded_document_count: 0,
      source_ref_count: 0,
      memory_context_count: 0,
    },
    route: {
      lane: "visual_generation",
      reason: "browser_stream_lifecycle_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: "visual_generation",
        reason: "Visual and Code Studio stream lifecycle.",
        bind_tools: true,
        force_tools: false,
      },
    },
    runtime: {
      provider: "browser-harness",
      model: "runtime-ledger-stream-mock",
      runtime_authoritative: true,
      fallback_used: false,
      failover_used: false,
    },
    tools: {
      observed: ["visual_runtime", "code_studio"],
      suppressed: ["host_action", "pointy_action"],
    },
    stream: {
      transport: "sse_v3",
      event_counts: {
        answer: 1,
        visual_open: 1,
        visual_commit: 1,
        code_open: 1,
        code_complete: 1,
        metadata: 1,
        done: 1,
      },
      event_sequence_tail: [
        "answer",
        "visual_open",
        "visual_commit",
        "code_open",
        "code_complete",
        "metadata",
        "done",
      ],
      metadata_seen: true,
      done_seen: true,
    },
    host_actions: {
      preview_required: false,
      preview_emitted: false,
      approval_token_present: false,
      apply_attempted: false,
    },
    finalization: {
      status: "saved",
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function streamRuntimeTrace() {
  return {
    version: "wiii.runtime_flow_trace.v1",
    turn_path_decision: {
      path: "visual_generation",
      reason: "Visual and Code Studio stream lifecycle.",
    },
    tool_policy_session: {
      bind_tools: true,
      force_tools: false,
      visible_tool_names: ["tool_generate_visual", "tool_create_visual_code"],
    },
    final_answer: {
      source: "stream_done_runtime_ledger",
      status: "ready",
    },
  };
}

function scheduledTaskRuntimeLedger() {
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "browser-scheduled-task-ledger",
      session_id: "browser-scheduled-task-session",
      user_id_hash: "browser-scheduled-task-user-hash",
      organization_id_hash: "browser-scheduled-task-org-hash",
      host_surface: "desktop_chat",
      host_capabilities: ["scheduled_tasks", "websocket_notifications"],
    },
    context: {
      document_context_present: false,
      uploaded_document_count: 0,
      source_ref_count: 0,
      memory_context_count: 0,
    },
    route: {
      lane: "scheduled_task_create",
      reason: "browser_scheduled_autonomy_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: "scheduled_task_create",
        reason: "Schedule reminder request with due delivery channel.",
        bind_tools: true,
        force_tools: false,
      },
    },
    runtime: {
      provider: "browser-harness",
      model: "scheduled-task-ledger-mock",
      runtime_authoritative: true,
      fallback_used: false,
      failover_used: false,
    },
    tools: {
      observed: ["tool_schedule_reminder"],
      suppressed: ["host_action", "pointy_action", "visual_runtime", "code_studio"],
      policy_session: {
        visible_tool_names: ["tool_schedule_reminder"],
      },
    },
    scheduled_tasks: {
      created: true,
      creation_tool: "tool_schedule_reminder",
      task_id_hash: "sha256:browser-scheduled-reminder",
      due_seen: true,
      delivery: {
        channel: "websocket",
        status: "queued",
      },
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
      event_sequence_tail: ["tool_call", "tool_result", "answer", "metadata", "done"],
      metadata_seen: true,
      done_seen: true,
    },
    host_actions: {
      preview_required: false,
      preview_emitted: false,
      approval_token_present: false,
      apply_attempted: false,
      result_received: false,
    },
    finalization: {
      status: "saved",
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function scheduledTaskRuntimeTrace() {
  return {
    version: "wiii.runtime_flow_trace.v1",
    turn_path_decision: {
      path: "scheduled_task_create",
      reason: "Schedule reminder request with due delivery channel.",
    },
    tool_policy_session: {
      bind_tools: true,
      force_tools: false,
      visible_tool_names: ["tool_schedule_reminder"],
    },
    final_answer: {
      source: "scheduled_task_created",
      status: "ready",
    },
  };
}

function sourceMemoryRuntimeLedger() {
  return {
    schema_version: "wiii.runtime_flow_ledger.v1",
    request: {
      request_id: "browser-source-memory-ledger",
      session_id: "browser-source-memory-session",
      user_id_hash: "browser-runtime-ledger-user-hash",
      organization_id_hash: "browser-runtime-ledger-org-hash",
      host_surface: "desktop_chat",
      host_capabilities: ["document_context", "semantic_memory"],
    },
    context: {
      document_context_present: true,
      uploaded_document_count: 1,
      source_ref_count: 2,
      memory_context_count: 3,
      context_provenance: {
        schema_version: "wiii.context_provenance_ledger.v1",
        conversation: {
          history_present: true,
          history_item_count: 2,
          summary_present: true,
        },
        documents: {
          present: true,
          attachment_count: 1,
          usable_attachment_count: 1,
          source_ref_count: 2,
          source_ref_kinds: ["document_source_ref", "citation"],
          parser_names: ["docx_parser"],
          media_kinds: ["document"],
          provenance_levels: ["page_marker"],
          attachment_id_hashes: ["sha256:documenthash"],
        },
        memory: {
          semantic_context_present: true,
          semantic_memory_count: 3,
          semantic_memory_types: ["preference", "goal"],
          retrieval_present: true,
          retrieval_status: "ready",
          relevant_memory_count: 2,
          fact_type_names: ["learning_profile"],
          insight_category_names: ["habit"],
          user_fact_count: 2,
          core_memory_present: true,
          episodic_retrieval_present: true,
          episodic_retrieval_status: "ready",
          episodic_match_count: 1,
          episodic_event_types: ["lesson_completed"],
          episodic_min_score: 0.4,
          episodic_max_score: 0.92,
          episodic_org_scoped: true,
          episodic_current_session_excluded: true,
          episodic_raw_content_included: false,
          warning_codes: ["memory_context_without_typed_items"],
        },
        host: {
          host_context_present: true,
          surface: "desktop_chat",
          capability_names: ["document_context", "semantic_memory"],
          available_action_count: 0,
          host_capabilities_present: true,
        },
        warnings: ["document_context_truncated", "memory_context_without_typed_items"],
        privacy: {
          raw_content_included: false,
          identifier_strategy: "hash_or_count_only",
        },
      },
    },
    route: {
      lane: "document_grounded_answer",
      reason: "browser_source_memory_context_acceptance",
      selected_agent: "direct",
      final_agent: "direct",
      turn_path_decision: {
        path: "document_grounded_answer",
        reason: "Source-backed document and memory context were available.",
        bind_tools: false,
        force_tools: false,
      },
    },
    runtime: {
      provider: "browser-harness",
      model: "source-memory-ledger-mock",
      runtime_authoritative: true,
      fallback_used: false,
      failover_used: false,
    },
    tools: {
      observed: [],
      suppressed: ["host_action", "pointy_action", "visual_runtime", "code_studio"],
    },
    stream: {
      transport: "sse_v3",
      event_counts: {
        answer: 1,
        metadata: 1,
        done: 1,
      },
      event_sequence_tail: ["answer", "metadata", "done"],
      metadata_seen: true,
      done_seen: true,
    },
    host_actions: {
      preview_required: true,
      preview_emitted: true,
      approval_token_present: true,
      apply_attempted: false,
    },
    finalization: {
      status: "saved",
      error_type: null,
      save_response_immediately: false,
    },
  };
}

function sourceMemoryRuntimeTrace() {
  return {
    version: "wiii.runtime_flow_trace.v1",
    turn_path_decision: {
      path: "document_grounded_answer",
      reason: "Source-backed document and memory context were available.",
    },
    tool_policy_session: {
      bind_tools: false,
      force_tools: false,
      visible_tool_names: [],
    },
    final_answer: {
      source: "source_memory_context",
      status: "ready",
    },
  };
}

function wiiiConnectCapabilitySnapshot() {
  return {
    version: "wiii_connect_snapshot.v0",
    generated_at: nowIso(),
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
        allowed_tool_groups: [],
        forbidden_tool_groups: [],
        mutation_policy: "none",
        delegation_policy: "direct_only",
      },
      {
        path: "external_app_action",
        required_connection_slugs: [],
        allowed_tool_groups: ["external_app"],
        forbidden_tool_groups: ["pointy"],
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
  };
}

function wiiiConnectDoctorReport() {
  return {
    version: "wiii_connect_doctor.v0",
    generated_at: nowIso(),
    surface: "desktop",
    status: "ready",
    summary: {
      total_paths: 2,
      ready_paths: 1,
      guarded_paths: 1,
      blocked_paths: 0,
      total_connections: 2,
      agent_ready_connections: 2,
      external_provider_connections: 1,
      external_agent_ready_connections: 1,
      warning_count: 0,
    },
    path_diagnostics: [
      {
        path: "external_app_action",
        status: "guarded",
        reason: "provider_worker_gateway_required",
        required_connection_slugs: [],
        missing_connection_slugs: [],
        blocked_connection_reasons: [],
        mutation_policy: "approval_token_required",
        delegation_policy: "delegate_to_integrations_agent",
        agent_ready_connection_slugs: ["facebook"],
      },
    ],
    provider_diagnostics: [],
    top_blockers: [],
    warnings: [],
  };
}

function runtimeFlowDoctorReport() {
  return {
    version: "wiii.runtime_flow_doctor.v1",
    generated_at: nowIso(),
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
      done_seen_count: 3,
      missing_done_count: 0,
      metadata_seen_count: 3,
      uploaded_document_turns: 1,
      memory_context_turns: 1,
      source_ref_total: 2,
      context_provenance_turns: 3,
      context_warning_count: 1,
      failed_finalization_count: 0,
      raw_content_flag_count: 0,
    },
    request_correlation: {
      request_id_present_count: 2,
      missing_request_id_count: 1,
      provider_call_turn_count: 1,
      provider_call_correlated_turn_count: 1,
      provider_call_uncorrelated_turn_count: 0,
      provider_call_stage_count: 2,
      provider_call_stage_request_id_present_count: 2,
      provider_call_stage_request_id_missing_count: 0,
      provider_call_stage_request_id_match_count: 2,
      provider_call_stage_request_id_mismatch_count: 0,
      identifier_strategy: "presence_counts_only",
    },
    routes: {
      external_app_action: 2,
      lms_document_preview: 1,
    },
    finalization_statuses: { saved: 3 },
    stream_events: { done: 3, metadata: 3, tool_call: 1, tool_result: 1 },
    suppressed_tools: { pointy_action: 2 },
    observed_tools: { tool_wiii_connect_delegate_to_integration: 1 },
    context_warnings: { document_context_truncated: 1 },
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
          turn_count: 3,
          alert_counts: { missing_request_id: 1 },
          status_counts: { degraded: 1, ready: 2 },
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
          ephemeral_direct_turn: 1,
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
          profile_stats: 1,
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
  };
}

function runtimeFlowDoctorHistoryReport() {
  return {
    version: "wiii.runtime_flow_doctor_history.v1",
    generated_at: nowIso(),
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
          done_seen_count: 3,
          missing_done_count: 0,
          raw_content_flag_count: 0,
        },
        request_correlation: {
          missing_request_id_count: 1,
        },
        routes: {
          external_app_action: 2,
          lms_document_preview: 1,
        },
        finalization_statuses: { saved: 3 },
        context_warnings: { document_context_truncated: 1 },
        source: {
          session_event_count: 3,
          runtime_flow_ledger_event_count: 3,
        },
      },
      {
        bucket_start: "2026-05-31T10:00:00+00:00",
        status: "ready",
        alerts: [],
        summary: {
          turn_count: 1,
          done_seen_count: 1,
          missing_done_count: 0,
          raw_content_flag_count: 0,
        },
        request_correlation: {
          missing_request_id_count: 0,
        },
        routes: { casual_chat: 1 },
        finalization_statuses: { saved: 1 },
        context_warnings: {},
        source: {
          session_event_count: 1,
          runtime_flow_ledger_event_count: 1,
        },
      },
    ],
    source: {
      session_event_count: 4,
      runtime_flow_ledger_event_count: 4,
      bucket_count: 2,
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
  };
}

function semanticMemoryDoctorReport() {
  return {
    version: "wiii.semantic_memory_write_doctor.v1",
    generated_at: nowIso(),
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
    },
    write_statuses: {
      saved: 1,
      degraded: 1,
    },
    organization_contexts: {
      request_scoped: 2,
    },
    warnings: {
      insight_store_degraded: 1,
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
  };
}

function semanticMemoryDoctorHistoryReport() {
  return {
    version: "wiii.semantic_memory_write_doctor_history.v1",
    generated_at: nowIso(),
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
          insight_store: 1,
        },
        write_statuses: {
          saved: 1,
          degraded: 1,
        },
        organization_contexts: {
          request_scoped: 2,
        },
        warnings: {
          insight_store_degraded: 1,
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
  };
}

function runtimeFlowPruneReport(dryRun: boolean, orgScoped: boolean) {
  return {
    schema: "wiii.session_event_log_prune.v1",
    status: dryRun ? "dry_run" : "pruned",
    matched_count: 2,
    deleted_count: dryRun ? 0 : 2,
    retention_days: 30,
    cutoff: "2026-05-01T00:00:00+00:00",
    dry_run: dryRun,
    org_scoped: orgScoped,
    event_type_filter_applied: true,
    privacy: {
      raw_content_included: false,
      identifier_strategy: "aggregate_counts_only",
    },
    runtime_config: {
      session_event_log_backend: "postgres",
    },
  };
}

function memoryHealthResponse(cleared = false) {
  const memories = cleared
    ? []
    : [
        {
          id: "memory-name",
          type: "name",
          value: "Minh Anh",
          created_at: "2026-05-30T08:15:00Z",
        },
        {
          id: "memory-goal",
          type: "goal",
          value: "Simulation goal",
          created_at: "2026-05-31T09:20:00Z",
        },
      ];
  return {
    data: memories,
    total: memories.length,
    summary: {
      total: memories.length,
      type_counts: cleared ? {} : { goal: 1, name: 1 },
      latest_created_at: cleared ? null : "2026-05-31T09:20:00Z",
      scope_state: "request_scoped",
      org_scoped: true,
      controls: {
        can_delete_one: true,
        can_clear_all: true,
      },
      provenance: {
        source_kinds: cleared ? {} : { semantic_fact: memories.length },
        raw_content_included: false,
        identifier_strategy: "count_only",
      },
      privacy: {
        raw_content_included: false,
        identifier_strategy: "hash_or_count_only",
      },
    },
  };
}

function visualPayload() {
  return {
    id: "browser-visual-1",
    visual_session_id: "browser-visual-session",
    type: "process",
    renderer_kind: "template",
    shell_variant: "editorial",
    patch_strategy: "spec_merge",
    figure_group_id: "browser-visual-group",
    figure_index: 1,
    figure_total: 1,
    pedagogical_role: "mechanism",
    chrome_mode: "editorial",
    claim: "Browser acceptance renders a lifecycle-backed visual.",
    narrative_anchor: "after-lead",
    runtime: "svg",
    title: "Lifecycle visual",
    summary: "Visual lifecycle browser acceptance.",
    spec: {
      steps: [{ title: "Open" }, { title: "Commit" }],
    },
    scene: { kind: "process", nodes: [], panels: [] },
    controls: [],
    annotations: [],
    interaction_mode: "static",
    ephemeral: true,
    lifecycle_event: "visual_open",
  };
}

function formatSseEvent(
  id: number,
  type: string,
  data: Record<string, unknown>,
): string {
  return `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

async function installMemorySummaryApiMocks(
  page: Page,
  clearRequests: { count: number },
): Promise<void> {
  let cleared = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = request.url();
    let body: unknown = {};

    if (url.includes(`/api/v1/memories/${USER_ID}`)) {
      if (request.method() === "DELETE") {
        cleared = true;
        clearRequests.count += 1;
        body = {
          success: true,
          deleted_count: 2,
          message: "Cleared memory facts for browser acceptance.",
        };
      } else {
        body = memoryHealthResponse(cleared);
      }
    } else if (url.includes("/api/v1/health")) {
      body = { status: "healthy" };
    } else if (url.includes("/api/v1/admin/domains")) {
      body = [];
    } else if (url.includes("/api/v1/organizations")) {
      body = [];
    } else if (url.includes("/api/v1/users/me/connected-workspaces")) {
      body = [];
    } else if (url.includes("/api/v1/users/me/identities")) {
      body = [];
    } else if (url.includes("/api/v1/users/me/admin-context")) {
      body = {
        is_system_admin: false,
        is_org_admin: false,
        organizations: [],
      };
    } else if (url.includes("/api/v1/users/me")) {
      body = {
        id: USER_ID,
        email: "runtime-ledger-browser@example.test",
        name: "Runtime Ledger Browser",
        role: "teacher",
        connected_workspaces_count: 0,
      };
    } else if (url.includes("/api/v1/threads")) {
      body = [];
    } else if (url.includes("/api/v1/llm/status")) {
      body = { status: "ready" };
    }

    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

async function installWiiiConnectControlPlaneMocks(
  page: Page,
  pruneRequests: URL[] = [],
): Promise<void> {
  await page.route("**/api/v1/admin/runtime-flow/doctor/recent**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(runtimeFlowDoctorReport()),
    });
  });

  await page.route("**/api/v1/admin/runtime-flow/doctor/history**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(runtimeFlowDoctorHistoryReport()),
    });
  });

  await page.route("**/api/v1/admin/semantic-memory/doctor/recent**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(semanticMemoryDoctorReport()),
    });
  });

  await page.route("**/api/v1/admin/semantic-memory/doctor/history**", async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(semanticMemoryDoctorHistoryReport()),
    });
  });

  await page.route("**/api/v1/admin/runtime-flow/session-events/prune**", async (route) => {
    const url = new URL(route.request().url());
    pruneRequests.push(url);
    const dryRun = url.searchParams.get("dry_run") !== "false";
    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(runtimeFlowPruneReport(dryRun, url.searchParams.has("org_id"))),
    });
  });

  await page.route("**/api/v1/wiii-connect/**", async (route) => {
    const url = route.request().url();
    let body: unknown = {};
    if (url.includes("/api/v1/wiii-connect/snapshot")) {
      body = wiiiConnectCapabilitySnapshot();
    } else if (url.includes("/api/v1/wiii-connect/doctor")) {
      body = wiiiConnectDoctorReport();
    } else if (url.includes("/api/v1/wiii-connect/providers")) {
      body = {
        version: "wiii_connect_provider_registry.v1",
        providers: [],
      };
    }

    await route.fulfill({
      status: 200,
      headers: {
        "access-control-allow-origin": "*",
      },
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

async function installVisualCodeStreamMock(page: Page): Promise<void> {
  await page.route("**/api/v1/chat/stream/v3", async (route) => {
    const html = [
      "<!doctype html>",
      "<html><body>",
      "<main>Runtime ledger Code Studio acceptance</main>",
      "</body></html>",
    ].join("");
    const events: Array<{ type: string; data: Record<string, unknown> }> = [
      {
        type: "answer",
        data: { content: "Visual and Code Studio lifecycle completed." },
      },
      {
        type: "visual_open",
        data: { content: visualPayload(), node: "browser_harness" },
      },
      {
        type: "visual_commit",
        data: {
          content: {
            visual_session_id: "browser-visual-session",
            status: "committed",
          },
          node: "browser_harness",
        },
      },
      {
        type: "code_open",
        data: {
          content: {
            session_id: "browser-code-session",
            title: "Runtime ledger app",
            language: "html",
            version: 1,
            studio_lane: "app",
            artifact_kind: "html_app",
            quality_profile: "standard",
            renderer_contract: "host_shell",
            requested_view: "preview",
          },
          node: "browser_harness",
        },
      },
      {
        type: "code_complete",
        data: {
          content: {
            session_id: "browser-code-session",
            full_code: html,
            language: "html",
            version: 1,
            studio_lane: "app",
            artifact_kind: "html_app",
            quality_profile: "standard",
            renderer_contract: "host_shell",
            requested_view: "preview",
          },
          node: "browser_harness",
        },
      },
      {
        type: "metadata",
        data: {
          session_id: "browser-runtime-ledger-stream-session",
          thread_id: "browser-runtime-ledger-stream-thread",
          model: "runtime-ledger-stream-mock",
          runtime_flow_trace: streamRuntimeTrace(),
        },
      },
      {
        type: "done",
        data: {
          status: "complete",
          processing_time: 0.2,
          runtime_flow_ledger: streamRuntimeLedger(),
        },
      },
    ];

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: events
        .map((event, index) => formatSseEvent(index + 1, event.type, event.data))
        .join(""),
    });
  });
}

async function installSourceMemoryStreamMock(page: Page): Promise<void> {
  await page.route("**/api/v1/chat/stream/v3", async (route) => {
    const events: Array<{ type: string; data: Record<string, unknown> }> = [
      {
        type: "answer",
        data: { content: "Source-backed memory context was used safely." },
      },
      {
        type: "metadata",
        data: {
          session_id: "browser-source-memory-session",
          thread_id: "browser-source-memory-thread",
          model: "source-memory-ledger-mock",
          runtime_flow_trace: sourceMemoryRuntimeTrace(),
        },
      },
      {
        type: "done",
        data: {
          status: "complete",
          processing_time: 0.18,
          runtime_flow_ledger: sourceMemoryRuntimeLedger(),
        },
      },
    ];

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: events
        .map((event, index) => formatSseEvent(index + 1, event.type, event.data))
        .join(""),
    });
  });
}

async function installScheduledTaskStreamMock(page: Page): Promise<void> {
  await page.route("**/api/v1/chat/stream/v3", async (route) => {
    const events: Array<{ type: string; data: Record<string, unknown> }> = [
      {
        type: "tool_call",
        data: {
          content: {
            id: "browser-schedule-call",
            name: "tool_schedule_reminder",
            args: {
              description: "Review COLREG Rule 13",
              when: "2026-05-31T12:01:00.000Z",
            },
          },
          node: "browser_harness",
        },
      },
      {
        type: "tool_result",
        data: {
          content: {
            id: "browser-schedule-call",
            name: "tool_schedule_reminder",
            result: "Created scheduled reminder sha256:browser-scheduled-reminder.",
          },
          node: "browser_harness",
        },
      },
      {
        type: "answer",
        data: { content: "Đã lên lịch nhắc ôn COLREG Rule 13." },
      },
      {
        type: "metadata",
        data: {
          session_id: "browser-scheduled-task-session",
          thread_id: "browser-scheduled-task-thread",
          model: "scheduled-task-ledger-mock",
          runtime_flow_trace: scheduledTaskRuntimeTrace(),
        },
      },
      {
        type: "done",
        data: {
          status: "complete",
          processing_time: 0.16,
          runtime_flow_ledger: scheduledTaskRuntimeLedger(),
        },
      },
    ];

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: events
        .map((event, index) => formatSseEvent(index + 1, event.type, event.data))
        .join(""),
    });
  });
}

async function installScheduledTaskWebSocketMock(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type MockSocket = {
      url: string;
      readyState: number;
      onopen: ((event: Event) => void) | null;
      onmessage: ((event: MessageEvent) => void) | null;
      onclose: ((event: Event) => void) | null;
      onerror: ((event: Event) => void) | null;
      send: (data: string) => void;
      close: () => void;
    };
    type Harness = {
      urls: string[];
      sent: string[];
      clients: MockSocket[];
      emit: (payload: Record<string, unknown>) => void;
    };
    const originalWebSocket = window.WebSocket;
    const harness: Harness = {
      urls: [],
      sent: [],
      clients: [],
      emit(payload) {
        for (const client of this.clients) {
          if (client.readyState !== 1) continue;
          client.onmessage?.(
            new MessageEvent("message", { data: JSON.stringify(payload) }),
          );
        }
      },
    };
    const MockWebSocket = function (
      this: MockSocket,
      url: string | URL,
      protocols?: string | string[],
    ) {
      const stringUrl = String(url);
      if (!stringUrl.includes("/api/v1/ws/")) {
        return protocols
          ? new originalWebSocket(url, protocols)
          : new originalWebSocket(url);
      }
      this.url = stringUrl;
      this.readyState = 0;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      harness.urls.push(stringUrl);
      harness.clients.push(this);
      setTimeout(() => {
        this.readyState = 1;
        this.onopen?.(new Event("open"));
      }, 0);
    } as unknown as typeof WebSocket;

    MockWebSocket.CONNECTING = 0;
    MockWebSocket.OPEN = 1;
    MockWebSocket.CLOSING = 2;
    MockWebSocket.CLOSED = 3;
    MockWebSocket.prototype.send = function (this: MockSocket, data: string) {
      harness.sent.push(String(data));
      const payload = JSON.parse(String(data)) as { type?: string };
      if (payload.type === "auth") {
        this.onmessage?.(
          new MessageEvent("message", {
            data: JSON.stringify({ type: "auth_ok" }),
          }),
        );
      }
    };
    MockWebSocket.prototype.close = function (this: MockSocket) {
      if (this.readyState === 3) return;
      this.readyState = 3;
      this.onclose?.(new Event("close"));
    };
    Object.defineProperty(window, "WebSocket", {
      configurable: true,
      value: MockWebSocket,
    });
    (window as unknown as { __wiiiScheduledNotificationWs: Harness })
      .__wiiiScheduledNotificationWs = harness;
  });
}

async function installEmbedLmsApiMocks(
  page: Page,
  seenChatRequests: Array<Record<string, unknown>>,
  seenHostActionAudits: Array<Record<string, unknown>> = [],
): Promise<void> {
  await page.route("**/api/v1/admin/domains", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: EMBED_DOMAIN_ID,
          name: "Maritime",
          display_name: "Maritime",
          description: "Runtime ledger LMS acceptance domain",
          is_active: true,
        },
      ]),
    });
  });

  await page.route("**/api/v1/organizations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: EMBED_ORG_ID,
          name: "Maritime LMS",
          display_name: "Maritime LMS",
          allowed_domains: [EMBED_DOMAIN_ID],
          is_active: true,
        },
      ]),
    });
  });

  await page.route(`**/api/v1/organizations/${EMBED_ORG_ID}/settings`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ branding: null }),
    });
  });

  await page.route(`**/api/v1/organizations/${EMBED_ORG_ID}/permissions`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ permissions: ["read:lms", "preview:lesson"], org_role: "teacher" }),
    });
  });

  await page.route("**/api/v1/users/me/admin-context", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        is_system_admin: false,
        enable_org_admin: false,
        admin_org_ids: [],
      }),
    });
  });

  await page.route("**/api/v1/llm/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        providers: [],
        primary_provider: "auto",
        fallback_provider: null,
      }),
    });
  });

  await page.route("**/api/v1/document-context/parse", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        file_name: "bridge-resource-management.md",
        mime_type: "text/markdown",
        media_kind: "document",
        size_bytes: Buffer.byteLength(EMBED_COURSE_MARKDOWN),
        parser: "markdown_parser",
        parser_chain: ["frontmatter", "markdown"],
        provenance_level: "page_marker",
        title: "Bridge Resource Management",
        page_count: 1,
        section_titles: ["Bridge Resource Management"],
        section_snippets: [
          {
            title: "Bridge Resource Management",
            markdown: EMBED_COURSE_MARKDOWN,
            char_start: 0,
            char_end: EMBED_COURSE_MARKDOWN.length,
            source_pages: [1],
            page_start: 1,
            page_end: 1,
          },
        ],
        markdown: EMBED_COURSE_MARKDOWN,
        char_count: EMBED_COURSE_MARKDOWN.length,
        truncated: false,
        extracted_images: [],
        extracted_image_count: 0,
        embedded_assets: [],
        embedded_asset_count: 0,
        figure_count: 0,
        table_count: 0,
      }),
    });
  });

  await page.route("**/api/v1/host-actions/audit", async (route) => {
    seenHostActionAudits.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, event_id: "browser-host-action-audit" }),
    });
  });

  await page.route("**/api/v1/chat/stream/v3", async (route) => {
    seenChatRequests.push(route.request().postDataJSON() as Record<string, unknown>);
    const events: Array<{ type: string; data: Record<string, unknown> }> = [
      {
        type: "answer",
        data: { content: "Đã tạo bản nháp preview LMS từ tài liệu khóa học." },
      },
      {
        type: "preview",
        data: {
          content: embedLmsHostActionPreview(),
          node: "browser_harness",
        },
      },
      {
        type: "metadata",
        data: {
          session_id: EMBED_SESSION_ID,
          thread_id: "embed-lms-runtime-thread",
          model: "embed-lms-ledger-mock",
          runtime_flow_trace: embedLmsRuntimeTrace(),
        },
      },
      {
        type: "done",
        data: {
          status: "complete",
          processing_time: 0.22,
          runtime_flow_ledger: embedLmsRuntimeLedger(),
        },
      },
    ];

    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      },
      body: events
        .map((event, index) => formatSseEvent(index + 1, event.type, event.data))
        .join(""),
    });
  });
}

async function seedRuntimeLedgerConversation(
  page: Page,
  overrides: {
    user?: Record<string, unknown>;
    settings?: Record<string, unknown>;
    assistantContent?: string;
    assistantMetadata?: Record<string, unknown>;
    userPrompt?: string;
  } = {},
): Promise<void> {
  const timestamp = nowIso();
  const user = {
    id: USER_ID,
    email: "runtime-ledger-browser@example.test",
    name: "Runtime Ledger Browser",
    role: "teacher",
    platform_role: "user",
    organization_role: "member",
    ...overrides.user,
  };
  const settings = {
    server_url: "http://127.0.0.1:9",
    api_key: "",
    user_id: USER_ID,
    user_role: "teacher",
    display_name: "Runtime Ledger Browser",
    theme: "light",
    language: "vi",
    show_thinking: true,
    show_reasoning_trace: false,
    streaming_version: "v3",
    thinking_level: "balanced",
    pointy_voice_enabled: false,
    show_previews: true,
    show_artifacts: true,
    ...overrides.settings,
  };
  const conversation = {
    id: "runtime-ledger-browser-conversation",
    title: "Runtime ledger browser acceptance",
    created_at: timestamp,
    updated_at: timestamp,
    messages: [
      {
        id: "runtime-ledger-browser-user-message",
        role: "user",
        content: overrides.userPrompt || "Check runtime ledger browser acceptance.",
        timestamp,
      },
      {
        id: "runtime-ledger-browser-assistant-message",
        role: "assistant",
        content: overrides.assistantContent || "Runtime ledger browser acceptance is ready.",
        timestamp,
        metadata: overrides.assistantMetadata || {
          runtime_flow_ledger: runtimeLedger(),
          runtime_flow_trace: runtimeTrace(),
        },
      },
    ],
  };

  await page.addInitScript(
    ({ authUser, appSettings, conversations, token }) => {
      localStorage.clear();
      sessionStorage.clear();
      localStorage.setItem("wiii:app_settings", JSON.stringify(appSettings));
      localStorage.setItem(
        "wiii:auth_state",
        JSON.stringify({ data: { user: authUser, authMode: "oauth" } }),
      );
      localStorage.setItem(
        "wiii:wiii_auth_tokens",
        JSON.stringify({
          tokens: {
            access_token: token,
            refresh_token: "runtime-ledger-refresh-token",
            expires_at: Date.now() + 60 * 60 * 1000,
          },
        }),
      );
      localStorage.setItem(
        `wiii:conversations_${authUser.id}.json`,
        JSON.stringify({ [`conversations_${authUser.id}`]: conversations }),
      );
    },
    {
      authUser: user,
      appSettings: settings,
      conversations: [conversation],
      token: RAW_TOKEN,
    },
  );
}

function runtimeAcceptanceBrowserReplayEvidence(): RuntimeAcceptanceBrowserReplayEvidence {
  return {
    schema: "wiii.runtime_flow_acceptance.v1",
    generated_at: nowIso(),
    browser_replay: {
      schema: "wiii.runtime_flow_browser_replay.v1",
      cases: [
        {
          schema: "wiii.runtime_flow_browser_replay.v1",
          scenario_id: "source_memory_browser_replay",
          prompt_hash: "sha256:backendprompt",
          path: "document_grounded_answer",
          event_names: ["answer", "metadata", "done"],
          assistant_content: "Runtime flow acceptance evidence replay.",
          assistant_metadata: {
            runtime_flow_ledger: sourceMemoryRuntimeLedger(),
            runtime_flow_trace: sourceMemoryRuntimeTrace(),
          },
          timing: {
            first_event_seconds: 0.1,
            first_answer_seconds: 0.2,
            total_seconds: 0.3,
          },
        },
      ],
    },
  };
}

function loadRuntimeAcceptanceBrowserReplayEvidence(
  evidencePath: string,
): RuntimeAcceptanceBrowserReplayEvidence {
  const evidence = asRecord(
    JSON.parse(readFileSync(evidencePath, "utf8").replace(/^\uFEFF/, "")) as unknown,
    "runtime acceptance evidence",
  );
  assertBrowserReplayEvidenceIsSanitized(evidence);
  const browserReplay = asRecord(
    evidence.browser_replay,
    "runtime acceptance browser_replay",
  );
  const rawCases = browserReplay.cases;
  if (!Array.isArray(rawCases) || rawCases.length === 0) {
    throw new Error("runtime acceptance browser_replay.cases must be a non-empty array");
  }
  const cases = rawCases.map((rawCase, index): BrowserReplayCase => {
    const replayCase = asRecord(rawCase, `runtime acceptance browser_replay.cases[${index}]`);
    const assistantMetadata = asRecord(
      replayCase.assistant_metadata,
      `runtime acceptance browser_replay.cases[${index}].assistant_metadata`,
    );
    const eventNames = Array.isArray(replayCase.event_names)
      ? replayCase.event_names.filter((eventName): eventName is string => typeof eventName === "string")
      : undefined;
    const timing = replayCase.timing === undefined
      ? undefined
      : asRecord(replayCase.timing, `runtime acceptance browser_replay.cases[${index}].timing`);
    return {
      schema: typeof replayCase.schema === "string" ? replayCase.schema : undefined,
      scenario_id: typeof replayCase.scenario_id === "string" ? replayCase.scenario_id : undefined,
      prompt_hash: typeof replayCase.prompt_hash === "string" ? replayCase.prompt_hash : undefined,
      path: requiredString(replayCase.path, `runtime acceptance browser_replay.cases[${index}].path`),
      event_names: eventNames,
      assistant_content: requiredString(
        replayCase.assistant_content,
        `runtime acceptance browser_replay.cases[${index}].assistant_content`,
      ),
      assistant_metadata: assistantMetadata,
      timing,
    };
  });
  return {
    schema: requiredString(evidence.schema, "runtime acceptance evidence.schema"),
    generated_at: typeof evidence.generated_at === "string" ? evidence.generated_at : undefined,
    browser_replay: {
      schema: requiredString(browserReplay.schema, "runtime acceptance browser_replay.schema"),
      cases,
    },
  };
}

function runtimeAcceptanceBrowserReplayEvidenceForTest(): RuntimeAcceptanceBrowserReplayEvidence {
  const evidencePath = process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON?.trim();
  const evidence = evidencePath
    ? loadRuntimeAcceptanceBrowserReplayEvidence(evidencePath)
    : runtimeAcceptanceBrowserReplayEvidence();
  assertBrowserReplayEvidenceIsSanitized(evidence);
  return evidence;
}

function selectRuntimeAcceptanceBrowserReplayCases(
  evidence: RuntimeAcceptanceBrowserReplayEvidence,
): BrowserReplayCase[] {
  const preferredCaseId = process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_CASE?.trim();
  if (!preferredCaseId) {
    return evidence.browser_replay.cases;
  }
  const selected = evidence.browser_replay.cases.find(
    (candidate) => candidate.scenario_id === preferredCaseId,
  );
  if (!selected) {
    throw new Error(`Configured browser_replay case not found: ${preferredCaseId}`);
  }
  return [selected];
}

async function postEmbedLmsHostContext(target: BrowserTarget): Promise<void> {
  await target.evaluate(() => {
    const capabilities = {
      host_type: "lms",
      host_name: "Maritime LMS",
      connector_id: "playwright-lms",
      host_workspace_id: "course-bridge-101",
      host_organization_id: "maritime-lms",
      version: "playwright",
      resources: ["course", "lesson"],
      surfaces: ["embed_lms"],
      tools: [
        {
          name: "lms_document_preview",
          label: "Preview lesson draft",
          description: "Create a lesson preview before applying changes.",
          permission: "preview:lesson",
          requires_confirmation: true,
          mutates_state: false,
          surface: "embed_lms",
        },
        {
          name: "authoring.apply_lesson_patch",
          label: "Apply lesson patch",
          description: "Apply an already approved lesson patch.",
          permission: "apply:lesson",
          requires_confirmation: true,
          mutates_state: true,
          surface: "embed_lms",
          input_schema: {
            type: "object",
            required: ["preview_token", "approval_token"],
            properties: {
              preview_token: { type: "string" },
              approval_token: { type: "string" },
            },
          },
        },
      ],
    };
    const context = {
      host_type: "lms",
      host_name: "Maritime LMS",
      connector_id: "playwright-lms",
      host_user_id: "teacher-bridge",
      host_workspace_id: "course-bridge-101",
      host_organization_id: "maritime-lms",
      resource_uri: "lms://course/bridge-101/lesson/watchkeeping",
      page: {
        type: "lesson_editor",
        title: "Bridge Resource Management",
        url: "https://lms.example.test/courses/bridge-101/lessons/watchkeeping",
        metadata: {
          surface: "embed_lms",
          course_id: "bridge-101",
          lesson_id: "watchkeeping",
          action: "document_preview",
        },
      },
      user_role: "teacher",
      workflow_stage: "lesson_drafting",
      content: {
        snippet: "Teacher is preparing a COLREG/STCW lesson preview.",
      },
      available_actions: [
        {
          action: "lms_document_preview",
          name: "lms_document_preview",
          label: "Preview lesson draft",
          permission: "preview:lesson",
          requires_confirmation: true,
          mutates_state: false,
          surface: "embed_lms",
        },
        {
          action: "authoring.apply_lesson_patch",
          name: "authoring.apply_lesson_patch",
          label: "Apply lesson patch",
          permission: "apply:lesson",
          requires_confirmation: true,
          mutates_state: true,
          surface: "embed_lms",
          input_schema: {
            type: "object",
            required: ["preview_token", "approval_token"],
            properties: {
              preview_token: { type: "string" },
              approval_token: { type: "string" },
            },
          },
        },
      ],
    };
    window.dispatchEvent(new MessageEvent("message", {
      origin: window.location.origin,
      data: { type: "wiii:capabilities", payload: capabilities },
    }));
    window.dispatchEvent(new MessageEvent("message", {
      origin: window.location.origin,
      data: { type: "wiii:context", payload: context },
    }));
  });
}

async function sendPrompt(target: BrowserTarget, prompt: string): Promise<void> {
  const input = target.locator('[data-wiii-id="chat-textarea"]').first();
  await expect(input).toBeVisible({ timeout: 60_000 });
  await expect(input).toBeEnabled({ timeout: 60_000 });
  await input.fill(prompt);
  await input.press("Enter");
}

async function latestAssistantMetadataFromStorage(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(() => {
    const assistantMessages: Array<{ metadata?: Record<string, unknown> }> = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key || !key.includes("conversations_")) continue;
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      try {
        const parsed = JSON.parse(raw);
        for (const value of Object.values(parsed)) {
          if (!Array.isArray(value)) continue;
          for (const conversation of value) {
            const messages = (conversation as { messages?: unknown[] })?.messages;
            if (!Array.isArray(messages)) continue;
            for (const message of messages) {
              if (
                message &&
                typeof message === "object" &&
                (message as { role?: unknown }).role === "assistant"
              ) {
                assistantMessages.push(message as { metadata?: Record<string, unknown> });
              }
            }
          }
        }
      } catch {
        // Ignore unrelated localStorage entries.
      }
    }
    return assistantMessages[assistantMessages.length - 1]?.metadata || {};
  });
}

async function openRuntimeTab(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Wiii Connect" }).click();
  await expect(page.getByTestId("wiii-connect-page")).toBeVisible();
  await page
    .locator('nav[aria-label="Wiii Connect"] button')
    .filter({ hasText: "Runtime" })
    .click();
}

async function latestAssistantMetadata(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate((userId) => {
    const raw = localStorage.getItem(`wiii:conversations_${userId}.json`);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    const conversations = parsed?.[`conversations_${userId}`];
    if (!Array.isArray(conversations)) return {};
    const messages = conversations.flatMap((conversation: { messages?: unknown[] }) =>
      Array.isArray(conversation.messages) ? conversation.messages : [],
    );
    const assistants = messages.filter((message: unknown) => (
      Boolean(message)
      && typeof message === "object"
      && (message as { role?: unknown }).role === "assistant"
    ));
    const latest = assistants[assistants.length - 1] as
      | { metadata?: Record<string, unknown> }
      | undefined;
    return latest?.metadata || {};
  }, USER_ID);
}

test.describe("runtime ledger browser acceptance", () => {
  test("renders MemoryTab health summary and updates it after clear", async ({ page }, testInfo) => {
    const clearRequests = { count: 0 };
    await installMemorySummaryApiMocks(page, clearRequests);
    await seedRuntimeLedgerConversation(page);

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await page.keyboard.press("Control+,");
    await expect(page.getByTestId("full-page-content")).toBeVisible();
    await page.getByRole("button", { name: "Trí nhớ" }).click();

    const content = page.getByTestId("full-page-content");
    await expect(content).toContainText("Wiii nhớ gì về bạn");
    await expect(content).toContainText(/Tổng\s*2/);
    await expect(content).toContainText(/Loại\s*2/);
    await expect(content).toContainText("31/5/2026");
    await expect(content).toContainText("Theo tổ chức");
    await expect(content).toContainText("Minh Anh");
    await expect(content).toContainText("Simulation goal");
    await expect(content).not.toContainText("semantic_fact");
    await expect(content).not.toContainText("hash_or_count_only");
    await expect(content).not.toContainText("raw_content_included");

    await page.screenshot({
      path: testInfo.outputPath("memory-summary-settings.png"),
      fullPage: true,
    });

    await page.getByRole("button", { name: "Xóa tất cả" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Xóa tất cả bộ nhớ?");
    await dialog.getByRole("button", { name: "Xóa tất cả" }).click();

    await expect(content).toContainText(/Tổng\s*0/);
    await expect(content).toContainText(/Loại\s*0/);
    await expect(content).toContainText("Chưa có");
    await expect(content).toContainText("Theo tổ chức");
    await expect(content).toContainText("Mình chưa nhớ gì về bạn");
    await expect(content).not.toContainText("Minh Anh");
    await expect(content).not.toContainText("Simulation goal");
    expect(clearRequests.count).toBe(1);

    await page.screenshot({
      path: testInfo.outputPath("memory-summary-cleared.png"),
      fullPage: true,
    });
  });

  test("renders sanitized runtime_flow_ledger facts in Wiii Connect Runtime", async ({ page }, testInfo) => {
    const pruneRequests: URL[] = [];
    await installWiiiConnectControlPlaneMocks(page, pruneRequests);
    await seedRuntimeLedgerConversation(page, {
      user: {
        platform_role: "platform_admin",
        active_organization_id: "org-runtime-doctor-browser",
      },
    });

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await openRuntimeTab(page);

    const ledgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
    await expect(ledgerPanel).toBeVisible();
    await expect(ledgerPanel).toContainText("wiii.runtime_flow_ledger.v1");
    await expect(ledgerPanel).toContainText("external_app_action");
    await expect(ledgerPanel).toContainText("Route decision");
    await expect(ledgerPanel).toContainText("Wiii Connect delegated to integration.");
    await expect(ledgerPanel).toContainText("Provider/model");
    await expect(ledgerPanel).toContainText("browser-harness");
    await expect(ledgerPanel).toContainText("runtime-ledger-panel-mock");
    await expect(ledgerPanel).toContainText("Tool loop");
    await expect(ledgerPanel).toContainText("calls 1");
    await expect(ledgerPanel).toContainText("results 1");
    await expect(ledgerPanel).toContainText("denials 1");
    await expect(ledgerPanel).toContainText("desktop_chat");
    await expect(ledgerPanel).toContainText("tool_wiii_connect_delegate_to_integration");
    await expect(ledgerPanel).toContainText("pointy_action");
    await expect(ledgerPanel).toContainText("[redacted]");
    await expect(ledgerPanel).not.toContainText(RAW_TOKEN);

    const tracePanel = page.getByTestId("wiii-connect-runtime-flow-trace");
    await expect(tracePanel).toContainText("wiii.runtime_flow_trace.v1");
    await expect(tracePanel).toContainText("integration_worker");
    await expect(tracePanel).not.toContainText(RAW_TOKEN);

    const aggregateDoctorPanel = page.getByTestId("wiii-connect-runtime-flow-doctor-panel");
    await expect(aggregateDoctorPanel).toBeVisible();
    await expect(aggregateDoctorPanel).toContainText("Aggregate runtime doctor");
    await expect(aggregateDoctorPanel).toContainText("missing_request_id");
    await expect(aggregateDoctorPanel).toContainText("external_app_action");
    await expect(aggregateDoctorPanel).toContainText("document_context_truncated");
    await expect(aggregateDoctorPanel).toContainText("aggregate_counts_only");
    await expect(aggregateDoctorPanel).toContainText("postgres");
    const postTurnLifecyclePanel = page.getByTestId("wiii-connect-runtime-post-turn-lifecycle");
    await expect(postTurnLifecyclePanel).toContainText("Post-turn lifecycle");
    await expect(postTurnLifecyclePanel).toContainText("wiii.post_turn_lifecycle_metrics.v1");
    await expect(postTurnLifecyclePanel).toContainText("wiii.post_turn_lifecycle_ledger.v1");
    await expect(postTurnLifecyclePanel).toContainText("Durable events");
    await expect(postTurnLifecyclePanel).toContainText("Durable task count");
    await expect(postTurnLifecyclePanel).toContainText("post_turn_background_tasks_scheduled");
    await expect(postTurnLifecyclePanel).toContainText("semantic_memory_interaction");
    await expect(postTurnLifecyclePanel).toContainText("semantic_memory_maintenance");
    await expect(postTurnLifecyclePanel).toContainText("process_lifetime_in_memory");
    await expect(postTurnLifecyclePanel).toContainText("ledger_events");
    await expect(postTurnLifecyclePanel).toContainText("process-wide");
    await postTurnLifecyclePanel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath("runtime-post-turn-lifecycle.png"),
      fullPage: false,
    });
    const lifecyclePanel = page.getByTestId("wiii-connect-runtime-lifecycle-hooks");
    await expect(lifecyclePanel).toContainText("Lifecycle hooks");
    await expect(lifecyclePanel).toContainText("2 hooks / 1 owners");
    await expect(lifecyclePanel).toContainText("installed");
    await expect(lifecyclePanel).toContainText("end 1 / error 1");
    await expect(lifecyclePanel).toContainText("code_metadata_only");
    await lifecyclePanel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath("runtime-lifecycle-hooks.png"),
      fullPage: false,
    });
    await expect(aggregateDoctorPanel).not.toContainText(RAW_TOKEN);
    await expect(aggregateDoctorPanel).not.toContainText("PRIVATE LIFECYCLE OWNER SHOULD NOT APPEAR");

    const historyPanel = page.getByTestId("wiii-connect-runtime-flow-doctor-history");
    await expect(historyPanel).toBeVisible();
    await expect(aggregateDoctorPanel).toContainText("Doctor history");
    await expect(historyPanel).toContainText("missing_request_id");
    await expect(historyPanel).toContainText("external_app_action");
    await expect(historyPanel).toContainText("casual_chat");
    await expect(historyPanel).not.toContainText(RAW_TOKEN);

    const semanticMemoryPanel = page.getByTestId("wiii-connect-semantic-memory-doctor-panel");
    await expect(semanticMemoryPanel).toBeVisible();
    await expect(semanticMemoryPanel).toContainText("Semantic memory doctor");
    await expect(semanticMemoryPanel).toContainText("Memory write history");
    await expect(semanticMemoryPanel).toContainText("degraded");
    await expect(semanticMemoryPanel).toContainText("interaction");
    await expect(semanticMemoryPanel).toContainText("insight_store");
    await expect(semanticMemoryPanel).toContainText("request_scoped");
    await expect(semanticMemoryPanel).toContainText("insight_store_degraded");
    await expect(semanticMemoryPanel).toContainText("aggregate_counts_only");
    await expect(semanticMemoryPanel).toContainText("postgres");
    await expect(semanticMemoryPanel).not.toContainText("org-runtime-doctor-browser");
    await expect(semanticMemoryPanel).not.toContainText(RAW_TOKEN);
    await expect(semanticMemoryPanel).not.toContainText("access_token");

    const semanticMemoryHistory = page.getByTestId("wiii-connect-semantic-memory-doctor-history");
    await expect(semanticMemoryHistory).toBeVisible();
    await expect(semanticMemoryHistory).toContainText("interaction 1");
    await expect(semanticMemoryHistory).toContainText("insight_store_degraded 1");

    const pruneReport = page.getByTestId("wiii-connect-runtime-prune-report");
    const dryRunButton = page.getByTestId("wiii-connect-runtime-prune-dry-run");
    const applyButton = page.getByTestId("wiii-connect-runtime-prune-apply");
    await expect(dryRunButton).toBeEnabled();
    await expect(applyButton).toBeDisabled();
    await dryRunButton.click();
    await expect(pruneReport).toContainText("Matched");
    await expect(pruneReport).toContainText("2");
    await expect(applyButton).toBeEnabled();
    await applyButton.click();
    await expect(pruneReport).toContainText("Deleted");
    await expect(pruneReport).toContainText("2");
    expect(
      pruneRequests.some(
        (url) =>
          url.searchParams.get("dry_run") === "true" &&
          url.searchParams.get("event_type") === "runtime_flow_ledger",
      ),
    ).toBe(true);
    expect(
      pruneRequests.some(
        (url) =>
          url.searchParams.get("dry_run") === "false" &&
          url.searchParams.get("retention_days") === "30" &&
          url.searchParams.get("event_type") === "runtime_flow_ledger",
      ),
    ).toBe(true);
    await expect(aggregateDoctorPanel).not.toContainText("org-runtime-doctor-browser");
    await expect(aggregateDoctorPanel).not.toContainText("runtime_flow_ledger");
    await expect(aggregateDoctorPanel).not.toContainText("access_token");

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-panel.png"),
      fullPage: true,
    });
  });

  test("renders Wiii Connect capability_summary in Path policy", async ({ page }, testInfo) => {
    await installWiiiConnectControlPlaneMocks(page);
    await seedRuntimeLedgerConversation(page);

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await page.getByRole("button", { name: "Wiii Connect" }).click();
    await expect(page.getByTestId("wiii-connect-page")).toBeVisible();
    await page
      .locator('nav[aria-label="Wiii Connect"] button')
      .filter({ hasText: "Path policy" })
      .click();

    const summary = page.getByTestId("wiii-connect-capability-summary");
    await expect(summary).toBeVisible();
    await expect(summary).toContainText("facebook");
    await expect(summary).toContainText("read, preview, apply");
    await expect(summary).toContainText("1/2 ready");
    await expect(summary).toContainText("external_app_action");
    await expect(summary).toContainText("provider_worker_gateway_required");
    await expect(summary).toContainText("pointy");
    await expect(summary).not.toContainText(RAW_TOKEN);

    await page.screenshot({
      path: testInfo.outputPath("wiii-connect-capability-summary.png"),
      fullPage: true,
    });
  });

  test("uses terminal done runtime_flow_ledger after visual and Code Studio stream events", async ({ page }, testInfo) => {
    await installVisualCodeStreamMock(page);
    await seedRuntimeLedgerConversation(page);

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await sendPrompt(page, "Create a lifecycle-backed visual and Code Studio app.");
    await expect(page.locator('[data-message-role="assistant"]').last()).toContainText(
      "Visual and Code Studio lifecycle completed.",
      { timeout: 30_000 },
    );

    await expect
      .poll(async () => {
        const metadata = await latestAssistantMetadata(page);
        const ledger = metadata.runtime_flow_ledger as
          | { stream?: { done_seen?: boolean } }
          | undefined;
        return ledger?.stream?.done_seen === true;
      }, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    await openRuntimeTab(page);

    const ledgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
    await expect(ledgerPanel).toContainText("visual_generation");
    await expect(ledgerPanel).toContainText("visual_runtime");
    await expect(ledgerPanel).toContainText("code_studio");
    await expect(ledgerPanel).toContainText("visual 2");
    await expect(ledgerPanel).toContainText("code 2");
    await expect(ledgerPanel).toContainText("Done");
    await expect(ledgerPanel).not.toContainText("Cần kiểm tra ledger");

    const tracePanel = page.getByTestId("wiii-connect-runtime-flow-trace");
    await expect(tracePanel).toContainText("visual_generation");
    await expect(tracePanel).toContainText("tool_generate_visual");

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-stream-panel.png"),
      fullPage: true,
    });
  });

  test("surfaces scheduled reminder creation and WebSocket delivery", async ({ page }, testInfo) => {
    await installScheduledTaskWebSocketMock(page);
    await installScheduledTaskStreamMock(page);
    await seedRuntimeLedgerConversation(page, {
      user: {
        active_organization_id: "org-scheduled-browser",
      },
      settings: {
        api_key: "scheduled-browser-api-key-123456",
        organization_id: "org-scheduled-browser",
      },
    });

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await expect
      .poll(async () => page.evaluate(() => {
        const harness = (window as unknown as {
          __wiiiScheduledNotificationWs?: { sent: string[] };
        }).__wiiiScheduledNotificationWs;
        return harness?.sent.some((raw) => {
          const parsed = JSON.parse(raw) as Record<string, unknown>;
          return parsed.type === "auth" &&
            parsed.user_id === "runtime-ledger-browser-user" &&
            parsed.organization_id === "org-scheduled-browser";
        }) === true;
      }), {
        timeout: 15_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    await sendPrompt(page, "Nhắc tôi ôn COLREG Rule 13 sau 1 phút.");
    await expect(page.locator('[data-message-role="assistant"]').last()).toContainText(
      "Đã lên lịch nhắc ôn COLREG Rule 13.",
      { timeout: 30_000 },
    );

    await expect
      .poll(async () => {
        const metadata = await latestAssistantMetadata(page);
        const ledger = metadata.runtime_flow_ledger as
          | { scheduled_tasks?: { created?: boolean } }
          | undefined;
        return ledger?.scheduled_tasks?.created === true;
      }, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    await page.evaluate(() => {
      const harness = (window as unknown as {
        __wiiiScheduledNotificationWs?: {
          emit: (payload: Record<string, unknown>) => void;
        };
      }).__wiiiScheduledNotificationWs;
      harness?.emit({
        type: "scheduled_task",
        task_id: "tool-created-reminder-browser",
        mode: "notification",
        content: "Review COLREG Rule 13",
        executed_at: "2026-05-31T12:01:00.000Z",
      });
    });

    await expect(
      page.getByRole("status").filter({
        hasText: "Nhắc việc: Review COLREG Rule 13",
      }),
    ).toBeVisible();

    await openRuntimeTab(page);
    const ledgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
    await expect(ledgerPanel).toContainText("scheduled_task_create");
    await expect(ledgerPanel).toContainText("Scheduled task");
    await expect(ledgerPanel).toContainText("tool_schedule_reminder");
    await expect(ledgerPanel).toContainText("websocket/queued");
    await expect(ledgerPanel).not.toContainText("scheduled-browser-api-key");

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-scheduled-task-delivery.png"),
      fullPage: true,
    });
  });

  test("surfaces proactive WebSocket outreach toast", async ({ page }, testInfo) => {
    await installScheduledTaskWebSocketMock(page);
    await seedRuntimeLedgerConversation(page, {
      user: {
        active_organization_id: "org-proactive-browser",
      },
      settings: {
        api_key: "proactive-browser-api-key-123456",
        organization_id: "org-proactive-browser",
      },
    });

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await expect
      .poll(async () => page.evaluate(() => {
        const harness = (window as unknown as {
          __wiiiScheduledNotificationWs?: { urls: string[]; sent: string[] };
        }).__wiiiScheduledNotificationWs;
        const sentAuth = harness?.sent.some((raw) => {
          const parsed = JSON.parse(raw) as Record<string, unknown>;
          return parsed.type === "auth" &&
            parsed.user_id === "runtime-ledger-browser-user" &&
            parsed.organization_id === "org-proactive-browser";
        }) === true;
        const cleanUrls = harness?.urls.every(
          (url) => !url.includes("api_key") && !url.includes("access_token"),
        ) === true;
        return sentAuth && cleanUrls;
      }), {
        timeout: 15_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    await page.evaluate(() => {
      const harness = (window as unknown as {
        __wiiiScheduledNotificationWs?: {
          emit: (payload: Record<string, unknown>) => void;
        };
      }).__wiiiScheduledNotificationWs;
      harness?.emit({
        type: "proactive_message",
        trigger: "inactive_reengage",
        content: "Wiii found a revision window for COLREG Rule 13.",
        timestamp: "2026-05-31T12:05:00.000Z",
      });
    });

    await expect(
      page.getByRole("status").filter({
        hasText: "Wiii chủ động: Wiii found a revision window for COLREG Rule 13.",
      }),
    ).toBeVisible();

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-proactive-websocket-toast.png"),
      fullPage: true,
    });
  });

  test("renders source and memory context provenance from terminal done ledger", async ({ page }, testInfo) => {
    await installSourceMemoryStreamMock(page);
    await seedRuntimeLedgerConversation(page);

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await sendPrompt(page, "Use source-backed document and memory context.");
    await expect(page.locator('[data-message-role="assistant"]').last()).toContainText(
      "Source-backed memory context was used safely.",
      { timeout: 30_000 },
    );

    await expect
      .poll(async () => {
        const metadata = await latestAssistantMetadata(page);
        const ledger = metadata.runtime_flow_ledger as
          | { context?: { context_provenance?: unknown } }
          | undefined;
        return Boolean(ledger?.context?.context_provenance);
      }, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    await openRuntimeTab(page);

    const ledgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
    await expect(ledgerPanel).toContainText("document_grounded_answer");
    await expect(ledgerPanel).toContainText("docs 1");
    await expect(ledgerPanel).toContainText("sources 2");
    await expect(ledgerPanel).toContainText("memory 3");
    await expect(ledgerPanel).toContainText("document_source_ref");
    await expect(ledgerPanel).toContainText("preference");
    await expect(ledgerPanel).toContainText("learning_profile");
    await expect(ledgerPanel).toContainText("Episodic recall");
    await expect(ledgerPanel).toContainText("matches 1");
    await expect(ledgerPanel).toContainText("lesson_completed");
    await expect(ledgerPanel).toContainText("score 0.4-0.92");
    await expect(ledgerPanel).toContainText("org_scoped true");
    await expect(ledgerPanel).toContainText("current_session_excluded true");
    await expect(ledgerPanel).toContainText("episodic_raw_content false");
    await expect(ledgerPanel).toContainText("document_context_truncated");
    await expect(ledgerPanel).toContainText("memory_context_without_typed_items");
    await expect(ledgerPanel).toContainText("hash_or_count_only");
    await expect(ledgerPanel).toContainText("preview Có; approval Có; apply Không");

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-source-memory-panel.png"),
      fullPage: true,
    });
  });

  test("rejects raw browser_replay evidence payloads before Runtime tab seeding", async ({}, testInfo) => {
    const evidencePath = testInfo.outputPath("raw-browser-replay-evidence.json");
    writeFileSync(
      evidencePath,
      JSON.stringify({
        schema: "wiii.runtime_flow_acceptance.v1",
        browser_replay: {
          schema: "wiii.runtime_flow_browser_replay.v1",
          cases: [
            {
              schema: "wiii.runtime_flow_browser_replay.v1",
              scenario_id: "raw_payload_rejected",
              prompt_hash: "sha256:private",
              path: "document_grounded_answer",
              event_names: ["answer", "done"],
              prompt: "raw private prompt must not be replayed",
              assistant_content: "Runtime flow acceptance evidence replay.",
              assistant_metadata: {
                runtime_flow_ledger: sourceMemoryRuntimeLedger(),
                runtime_flow_trace: sourceMemoryRuntimeTrace(),
              },
            },
          ],
        },
      }),
      "utf8",
    );

    expect(() => loadRuntimeAcceptanceBrowserReplayEvidence(evidencePath)).toThrow(
      /raw replay field/,
    );
  });

  test("renders backend browser_replay evidence in Runtime tab", async ({ page }, testInfo) => {
    const evidence = runtimeAcceptanceBrowserReplayEvidenceForTest();
    const replayCases = selectRuntimeAcceptanceBrowserReplayCases(evidence);
    const evidenceText = JSON.stringify(evidence);
    const usesExternalEvidence = Boolean(process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON?.trim());

    expect(evidence.schema).toBe("wiii.runtime_flow_acceptance.v1");
    expect(evidence.browser_replay.schema).toBe("wiii.runtime_flow_browser_replay.v1");
    expect(replayCases.length).toBeGreaterThan(0);
    expect(evidenceText).not.toContain("private prompt");
    expect(evidenceText).not.toContain("private answer");
    expect(evidenceText).not.toContain("answer_preview");

    const replayCase = replayCases[0];
    await seedRuntimeLedgerConversation(page, {
      assistantContent: replayCase.assistant_content,
      assistantMetadata: replayCase.assistant_metadata,
      userPrompt: "Seeded from backend browser replay evidence.",
    });

    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    await openRuntimeTab(page);

    const ledgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
    await expect(ledgerPanel).toContainText(replayCase.path);
    await expect(ledgerPanel).toContainText("wiii.runtime_flow_ledger.v1");
    if (!usesExternalEvidence) {
      await expect(ledgerPanel).toContainText("docs 1");
      await expect(ledgerPanel).toContainText("sources 2");
      await expect(ledgerPanel).toContainText("memory 3");
      await expect(ledgerPanel).toContainText("Episodic recall");
      await expect(ledgerPanel).toContainText("hash_or_count_only");
      await expect(ledgerPanel).toContainText("preview Có; approval Có; apply Không");
    }
    await expect(ledgerPanel).not.toContainText("private prompt");
    await expect(ledgerPanel).not.toContainText("private answer");
    await expect(ledgerPanel).not.toContainText("answer_preview");

    const tracePanel = page.getByTestId("wiii-connect-runtime-flow-trace");
    await expect(tracePanel).toContainText("wiii.runtime_flow_trace.v1");
    await expect(tracePanel).toContainText(replayCase.path);

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-browser-replay-evidence.png"),
      fullPage: true,
    });

    for (const [index, nextReplayCase] of replayCases.slice(1).entries()) {
      await seedRuntimeLedgerConversation(page, {
        assistantContent: nextReplayCase.assistant_content,
        assistantMetadata: nextReplayCase.assistant_metadata,
        userPrompt: `Seeded from backend browser replay evidence ${index + 2}.`,
      });

      await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
      await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
        timeout: 60_000,
      });
      await openRuntimeTab(page);

      const nextLedgerPanel = page.getByTestId("wiii-connect-runtime-flow-ledger");
      await expect(nextLedgerPanel).toContainText(nextReplayCase.path);
      await expect(nextLedgerPanel).toContainText("wiii.runtime_flow_ledger.v1");
      await expect(nextLedgerPanel).not.toContainText("private prompt");
      await expect(nextLedgerPanel).not.toContainText("private answer");
      await expect(nextLedgerPanel).not.toContainText("answer_preview");

      const nextTracePanel = page.getByTestId("wiii-connect-runtime-flow-trace");
      await expect(nextTracePanel).toContainText("wiii.runtime_flow_trace.v1");
      await expect(nextTracePanel).toContainText(nextReplayCase.path);

      await page.screenshot({
        path: testInfo.outputPath(
          `runtime-ledger-browser-replay-evidence-${index + 2}.png`,
        ),
        fullPage: true,
      });
    }
  });

  test("carries authenticated embed LMS document context into terminal runtime ledger", async ({ page }, testInfo) => {
    const seenChatRequests: Array<Record<string, unknown>> = [];
    await installEmbedLmsApiMocks(page, seenChatRequests);

    const params = embedLmsHashParams();

    await page.goto(`/embed.html#${params.toString()}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });
    await postEmbedLmsHostContext(page);

    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.locator('[data-wiii-id="attach-file-button"]').first().click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: "bridge-resource-management.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(EMBED_COURSE_MARKDOWN, "utf8"),
    });
    await expect(page.getByText("markdown_parser")).toBeVisible({ timeout: 30_000 });

    await sendPrompt(page, "Tạo preview bài học LMS từ tài liệu khóa học vừa tải lên.");
    await expect(page.locator('[data-message-role="assistant"]').last()).toContainText(
      "Đã tạo bản nháp preview LMS từ tài liệu khóa học.",
      { timeout: 30_000 },
    );

    expect(seenChatRequests).toHaveLength(1);
    const request = seenChatRequests[0];
    const userContext = request.user_context as {
      host_context?: { host_type?: string; page?: { metadata?: Record<string, unknown> } };
      host_capabilities?: { host_type?: string; tools?: unknown[] };
      document_context?: { attachments?: Array<Record<string, unknown>> };
      available_actions?: unknown[];
    };
    expect(request.user_id).toBe(EMBED_USER_ID);
    expect(request.organization_id).toBe(EMBED_ORG_ID);
    expect(request.domain_id).toBe(EMBED_DOMAIN_ID);
    expect(request.session_id).toBe(EMBED_SESSION_ID);
    expect(userContext.host_context?.host_type).toBe("lms");
    expect(userContext.host_context?.page?.metadata?.surface).toBe("embed_lms");
    expect(userContext.host_capabilities?.host_type).toBe("lms");
    expect(userContext.host_capabilities?.tools?.length).toBe(2);
    expect(userContext.available_actions?.length).toBe(2);
    expect(userContext.document_context?.attachments?.[0]?.markdown).toContain(
      "COLREG watchkeeping lesson",
    );

    await expect
      .poll(async () => {
        const metadata = await latestAssistantMetadataFromStorage(page);
        const ledger = metadata.runtime_flow_ledger as
          | {
              route?: { lane?: string };
              context?: { context_provenance?: unknown };
              host_actions?: {
                preview_required?: boolean;
                approval_token_present?: boolean;
                apply_attempted?: boolean;
              };
            }
          | undefined;
        return ledger?.route?.lane === "lms_document_preview" &&
          Boolean(ledger?.context?.context_provenance) &&
          ledger?.host_actions?.preview_required === true &&
          ledger?.host_actions?.approval_token_present === true &&
          ledger?.host_actions?.apply_attempted === false;
      }, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(true);

    const metadata = await latestAssistantMetadataFromStorage(page);
    const ledgerText = JSON.stringify(metadata.runtime_flow_ledger);
    expect(ledgerText).toContain("lms_document_preview");
    expect(ledgerText).toContain("embed_lms");
    expect(ledgerText).toContain("lesson_section");
    expect(ledgerText).toContain("hash_or_count_only");
    expect(ledgerText).toContain("\"preview_required\":true");
    expect(ledgerText).toContain("\"approval_token_present\":true");
    expect(ledgerText).toContain("\"apply_attempted\":false");
    expect(ledgerText).not.toContain("COLREG watchkeeping lesson");
    expect(ledgerText).not.toContain("bridge-resource-management.md");
    expect(ledgerText).not.toContain("approval-lesson");

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-embed-lms-document.png"),
      fullPage: true,
    });
  });

  test("applies embed LMS preview through parent host bridge", async ({ page }, testInfo) => {
    const seenChatRequests: Array<Record<string, unknown>> = [];
    const seenHostActionAudits: Array<Record<string, unknown>> = [];
    await installEmbedLmsApiMocks(page, seenChatRequests, seenHostActionAudits);

    const embedSrc = `${PLAYWRIGHT_FRONTEND_ORIGIN}/embed.html#${embedLmsHashParams().toString()}`;
    await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.setContent(`
      <!doctype html>
      <html>
        <body style="margin:0">
          <iframe
            id="wiii-frame"
            title="Wiii embed LMS host bridge harness"
            style="width:1440px;height:1100px;border:0;display:block"
          ></iframe>
          <script>
            (() => {
              const frame = document.getElementById("wiii-frame");
              window.__wiiiHostActions = [];
              window.addEventListener("message", (event) => {
                const data = event.data || {};
                if (data.type !== "wiii:action-request") return;
                window.__wiiiHostActions.push(data);
                event.source.postMessage({
                  type: "wiii:action-response",
                  id: data.id,
                  result: {
                    success: true,
                    data: {
                      summary: "Đã áp dụng cập nhật bài học vào LMS.",
                      applied: true,
                      lesson_id: "watchkeeping",
                      preview_token_received: Boolean(data.params && data.params.preview_token),
                      approval_token_received: Boolean(data.params && data.params.approval_token)
                    }
                  }
                }, event.origin || "*");
              });
              frame.src = ${JSON.stringify(embedSrc)};
            })();
          </script>
        </body>
      </html>
    `);

    const frameLocator = page.frameLocator("#wiii-frame");
    await expect(frameLocator.locator('[data-wiii-id="chat-textarea"]').first()).toBeVisible({
      timeout: 60_000,
    });

    const app = page.frames().find((frame) => frame.url().includes("/embed.html"));
    expect(app, "embed iframe should be loaded").toBeTruthy();
    const embedFrame = app as Frame;
    await postEmbedLmsHostContext(embedFrame);

    const fileChooserPromise = page.waitForEvent("filechooser");
    await embedFrame.locator('[data-wiii-id="attach-file-button"]').first().click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: "bridge-resource-management.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(EMBED_COURSE_MARKDOWN, "utf8"),
    });
    await expect(embedFrame.getByText("markdown_parser")).toBeVisible({ timeout: 30_000 });

    await sendPrompt(embedFrame, "Tạo preview bài học LMS từ tài liệu khóa học vừa tải lên.");
    await expect(embedFrame.locator('[data-message-role="assistant"]').last()).toContainText(
      "Đã tạo bản nháp preview LMS từ tài liệu khóa học.",
      { timeout: 30_000 },
    );

    await embedFrame
      .getByRole("button", { name: /Preview thao tác host: Preview cập nhật bài học LMS/ })
      .click();

    const previewPanel = embedFrame.locator(".preview-panel-shell");
    await expect(previewPanel).toContainText("Preview token:");
    await expect(previewPanel).toContainText("Bridge Resource Management");

    const applyButton = previewPanel
      .getByRole("button")
      .filter({ hasText: "Xác nhận áp dụng" })
      .first();
    await expect(applyButton).toBeEnabled();
    await applyButton.click();

    await expect(previewPanel).toContainText("Đã áp dụng cập nhật bài học vào LMS.", {
      timeout: 30_000,
    });

    await expect
      .poll(async () => {
        return page.evaluate(() => {
          const hostWindow = window as Window & {
            __wiiiHostActions?: Array<Record<string, unknown>>;
          };
          return hostWindow.__wiiiHostActions?.length ?? 0;
        });
      }, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(1);

    const hostActions = await page.evaluate(() => {
      const hostWindow = window as Window & {
        __wiiiHostActions?: Array<Record<string, unknown>>;
      };
      return hostWindow.__wiiiHostActions ?? [];
    });
    const hostAction = hostActions[0] as {
      type?: string;
      action?: string;
      params?: Record<string, unknown>;
    };
    expect(hostAction.type).toBe("wiii:action-request");
    expect(hostAction.action).toBe("authoring.apply_lesson_patch");
    expect(hostAction.params?.preview_token).toBe("preview-token-browser-lms");
    expect(hostAction.params?.approval_token).toBe("approval-lesson-browser-lms");

    await expect
      .poll(() => seenHostActionAudits.length, {
        timeout: 30_000,
        intervals: [250, 500, 1_000],
      })
      .toBe(1);

    const audit = seenHostActionAudits[0];
    expect(audit.event_type).toBe("apply_confirmed");
    expect(audit.action).toBe("authoring.apply_lesson_patch");
    expect(audit.preview_token).toBe("preview-token-browser-lms");
    expect(audit.target_id).toBe("watchkeeping");
    expect(JSON.stringify(audit)).not.toContain("approval-lesson-browser-lms");

    expect(seenChatRequests).toHaveLength(1);

    await page.screenshot({
      path: testInfo.outputPath("runtime-ledger-embed-lms-apply.png"),
      fullPage: true,
    });
  });
});
