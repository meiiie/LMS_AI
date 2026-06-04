/**
 * TypeScript types mirroring the Wiii backend Pydantic schemas.
 * Source: maritime-ai-service/app/models/schemas.py
 */

// ===== Enums =====
export type UserRole = "student" | "teacher" | "admin";
export type PlatformRole = "user" | "platform_admin";
export type OrganizationRole = "member" | "org_admin" | "owner" | "admin";

// ===== Sprint 179: Multimodal Vision Input =====
export interface ImageInput {
  type: "base64" | "url";
  media_type: string;
  data: string;
  detail?: "auto" | "low" | "high";
}

export interface ChatDocumentAttachment {
  id?: string;
  file_name: string;
  mime_type?: string | null;
  media_kind?: "document" | "video";
  size_bytes: number;
  parser?: string;
  parser_chain?: string[];
  parser_warning?: string | null;
  provenance_level?: "text_only" | "structured_text" | "page_marker" | "page_layout";
  char_count?: number;
  truncated?: boolean;
  extracted_image_count?: number;
  embedded_asset_count?: number;
  figure_count?: number;
  table_count?: number;
}

export interface ChatDocumentContextAttachment extends ChatDocumentAttachment {
  markdown: string;
}

export interface ChatDocumentContext {
  source: "desktop_upload";
  attachments: ChatDocumentContextAttachment[];
}

export interface ChatVisualContext {
  last_visual_session_id?: string;
  last_visual_type?: string;
  last_visual_title?: string;
  visual_state_summary?: string;
  active_inline_visuals?: Array<{
    visual_session_id: string;
    type: string;
    title: string;
    renderer_kind?: string;
    shell_variant?: string;
    patch_strategy?: string;
    state_summary?: string;
    summary?: string;
    status?: string;
  }>;
}

export interface WidgetFeedbackItem {
  widget_id: string;
  widget_kind: string;
  summary?: string;
  status?: string;
  title?: string;
  visual_session_id?: string;
  score?: number;
  correct_count?: number;
  total_count?: number;
  source?: string;
  data?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  session_id?: string;
  message_id?: string;
  version?: string;
  timestamp: string;
}

export interface ChatWidgetFeedbackContext {
  last_widget_kind?: string;
  last_widget_summary?: string;
  recent_widget_feedback?: Array<{
    widget_id: string;
    widget_kind: string;
    summary?: string;
    status?: string;
    title?: string;
    visual_session_id?: string;
    score?: number;
    correct_count?: number;
    total_count?: number;
    source?: string;
    timestamp: string;
  }>;
}

export interface ChatCodeStudioContext {
  active_session?: {
    session_id: string;
    title: string;
    status: "streaming" | "complete" | "error";
    active_version: number;
    version_count: number;
    language: string;
    studio_lane: "app" | "artifact" | "widget";
    artifact_kind?: "html_app" | "code_widget" | "search_widget" | "document" | "chart_widget";
    quality_profile?: "draft" | "standard" | "premium";
    renderer_contract?: "host_shell" | "chart_runtime" | "article_figure";
    has_preview: boolean;
  };
  requested_view?: "code" | "preview";
}

export interface ChatUserContext {
  display_name?: string;
  role?: UserRole;
  page_context?: unknown | null;
  student_state?: unknown | null;
  available_actions?: unknown[] | null;
  host_context?: unknown | null;
  host_capabilities?: unknown | null;
  host_action_feedback?: unknown | null;
  visual_context?: ChatVisualContext | null;
  widget_feedback?: ChatWidgetFeedbackContext | null;
  code_studio_context?: ChatCodeStudioContext | null;
  document_context?: ChatDocumentContext | null;
  [key: string]: unknown;
}

// ===== Chat Request =====
export interface ChatRequest {
  user_id: string;
  message: string;
  role: UserRole;
  session_id?: string;
  thread_id?: string;
  domain_id?: string;
  organization_id?: string;
  images?: ImageInput[];
  user_context?: ChatUserContext;
  provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  model?: string;
  /** Wiii Pointy v2.8: explicit @plugin-name force-bind from chat input. */
  force_skills?: string[];
  /** F18 Phase B (2026-05-07) — Pointy mode flag. */
  pointy_mode?: boolean;
  /** Optional ElevenLabs-backed spoken Pointy captions. Audio is opt-in. */
  pointy_voice_enabled?: boolean;
}

// ===== Chat Response =====
export interface SourceInfo {
  title: string;
  content: string;
  url?: string;
  source_type?: string;
  image_url?: string;
  page_number?: number;
  document_id?: string;
  bounding_boxes?: Array<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  }>;
}

export interface ToolUsageInfo {
  name: string;
  description: string;
}

export interface ReasoningStep {
  step_name: string;
  description: string;
  result: string;
  confidence?: number;
  duration_ms: number;
  details?: Record<string, unknown>;
}

export interface ReasoningTrace {
  total_steps: number;
  total_duration_ms: number;
  was_corrected: boolean;
  correction_reason?: string;
  final_confidence: number;
  steps: ReasoningStep[];
}

export interface ThinkingLifecycleSegment {
  segment_id: string;
  turn_id: string;
  node: string;
  step_id?: string | null;
  sequence_id?: number | null;
  phase: "pre_tool" | "tool_continuation" | "post_tool" | "final_snapshot";
  provenance: "live_native" | "tool_continuation" | "final_snapshot" | "aligned_cleanup";
  status: "live" | "completed";
  display_role?: string | null;
  presentation?: string | null;
  label?: string | null;
  summary?: string | null;
  content: string;
  content_length: number;
  started_at?: number | null;
  ended_at?: number | null;
}

export interface ThinkingLifecycleSnapshot {
  version: number;
  turn_id: string;
  final_text: string;
  final_length: number;
  live_text: string;
  live_length: number;
  segment_count: number;
  has_tool_continuation: boolean;
  phases: Array<ThinkingLifecycleSegment["phase"]>;
  provenance_mix: Array<ThinkingLifecycleSegment["provenance"]>;
  segments: ThinkingLifecycleSegment[];
}

export interface FailoverRouteEvent {
  from_provider?: string | null;
  to_provider?: string | null;
  reason_code?: string | null;
  reason_category?: string | null;
  reason_label?: string | null;
  raw_reason?: string | null;
  error_type?: string | null;
  detail?: string | null;
  timeout_seconds?: number | null;
}

export interface FailoverMetadata {
  switched: boolean;
  switch_count: number;
  initial_provider?: string | null;
  final_provider?: string | null;
  last_reason_code?: string | null;
  last_reason_category?: string | null;
  last_reason_label?: string | null;
  route: FailoverRouteEvent[];
}

export interface ModelSwitchPromptOption {
  provider: "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  label: string;
  selected_model?: string | null;
}

export interface ModelSwitchPrompt {
  trigger: string;
  reason_code?: string | null;
  current_provider?: string | null;
  title: string;
  message: string;
  recommended_provider?: string | null;
  options: ModelSwitchPromptOption[];
  allow_retry_once: boolean;
  allow_session_switch: boolean;
}

export interface RuntimeFlowTrace {
  version?: string;
  turn_path_decision?: Record<string, unknown>;
  tool_policy_session?: Record<string, unknown>;
  external_app_action_plan?: Record<string, unknown>;
  external_app_integration_lane?: Record<string, unknown>;
  external_action_trace?: Record<string, unknown>;
  final_answer?: Record<string, unknown>;
}

export interface RuntimeFlowLedger {
  schema_version?: string;
  request?: Record<string, unknown>;
  context?: Record<string, unknown>;
  route?: Record<string, unknown>;
  runtime?: Record<string, unknown>;
  tools?: Record<string, unknown>;
  scheduled_tasks?: Record<string, unknown>;
  external_app?: Record<string, unknown>;
  stream?: Record<string, unknown>;
  host_actions?: Record<string, unknown>;
  finalization?: Record<string, unknown>;
  final_answer?: Record<string, unknown>;
}

export interface ChatResponseMetadata {
  processing_time: number;
  provider?: string;
  model: string;
  runtime_authoritative?: boolean;
  agent_type: "chat" | "rag" | "tutor" | "direct" | "memory" | "code_studio";
  session_id?: string;
  /** Sprint 225: Composite thread ID for cross-platform sync */
  thread_id?: string;
  tools_used?: ToolUsageInfo[];
  reasoning_trace?: ReasoningTrace;
  thinking_content?: string;
  thinking?: string;
  thinking_lifecycle?: ThinkingLifecycleSnapshot;
  chat_lifecycle?: ChatLifecycleTelemetryEvent[];
  failover?: FailoverMetadata | null;
  model_switch_prompt?: ModelSwitchPrompt | null;
  topics_accessed?: string[];
  confidence_score?: number;
  document_ids_used?: string[];
  query_type?: string;
  suggested_questions?: string[];
  data?: Record<string, unknown>;
  runtime_flow_trace?: RuntimeFlowTrace;
  runtime_flow_ledger?: RuntimeFlowLedger;
  /** Allow runtime-extended fields from server */
  [key: string]: unknown;
}

export interface ChatResponseData {
  answer: string;
  sources: SourceInfo[];
  suggested_questions: string[];
  domain_notice?: string;
  evidence_images?: Array<{
    url: string;
    page_number: number;
    document_id: string;
  }>;
}

// ===== SSE Events (v3 streaming) =====
export interface SSEThinkingEvent {
  content: string;
  step?: string;
  node?: string;
  confidence?: number;
  details?: Record<string, unknown>;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEAnswerEvent {
  content: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSESourcesEvent {
  sources?: SourceInfo[];
  content?: SourceInfo[];
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEMetadataEvent {
  processing_time?: number;
  streaming_version?: string;
  reasoning_trace?: ReasoningTrace;
  thinking?: string;
  thinking_content?: string;
  thinking_lifecycle?: ThinkingLifecycleSnapshot;
  failover?: FailoverMetadata | null;
  model_switch_prompt?: ModelSwitchPrompt | null;
  /** Sprint 120: Mood state from backend emotional state machine */
  mood?: {
    positivity: number;
    energy: number;
    mood: MoodType;
  } | null;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
  [key: string]: unknown;
}

export interface SSEDoneEvent {
  status?: string;
  processing_time?: number;
  runtime_flow_ledger?: RuntimeFlowLedger;
  [key: string]: unknown;
}

export interface SSEErrorEvent {
  message: string;
  provider?: string;
  reason_code?: ProviderDisabledReasonCode | string | null;
  model_switch_prompt?: ModelSwitchPrompt | null;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
  [key: string]: unknown;
}

export interface SSEToolCallEvent {
  content: {
    name: string;
    args: Record<string, unknown>;
    id: string;
  };
  node?: string;
  step?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEToolResultEvent {
  content: {
    name: string;
    result: string;
    id: string;
  };
  node?: string;
  step?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEStatusEvent {
  content: string;
  step?: string;
  node?: string;
  /** Sprint 164: Extra details (e.g. aggregation decision) */
  details?: Record<string, unknown>;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface WiiiConnectRuntimeConnection {
  id?: string | null;
  provider_kind?: string;
  slug: string;
  label: string;
  status: string;
  active?: boolean;
  agent_ready?: boolean;
  scopes?: Record<string, boolean>;
  capabilities?: string[];
  required_for_paths?: string[];
  source?: string;
  last_checked_at?: string | null;
  reason?: string;
  warnings?: string[];
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
  [key: string]: unknown;
}

export interface WiiiConnectRuntimePathCapability {
  path: string;
  allowed_connection_slugs?: string[];
  required_connection_slugs?: string[];
  allowed_tool_groups?: string[];
  forbidden_tool_groups?: string[];
  mutation_policy?: string;
  delegation_policy?: string;
  [key: string]: unknown;
}

export interface WiiiConnectRuntimePathReadiness {
  path: string;
  status: "ready" | "guarded" | "blocked" | string;
  reason: string;
  required_connection_slugs?: string[];
  missing_connection_slugs?: string[];
  agent_ready_connection_slugs?: string[];
  allowed_tool_groups?: string[];
  suppressed_tool_groups?: string[];
  mutation_policy?: string;
  delegation_policy?: string;
  [key: string]: unknown;
}

export interface WiiiConnectCapabilitySummary {
  active_connection_slugs?: string[];
  agent_ready_connection_slugs?: string[];
  connected_provider_slugs?: string[];
  agent_ready_provider_slugs?: string[];
  connected_scope_names?: string[];
  suppressed_tool_groups?: string[];
  path_readiness?: WiiiConnectRuntimePathReadiness[];
}

export interface WiiiConnectRuntimeSnapshot {
  version: string;
  generated_at?: string;
  surface?: string;
  connections?: WiiiConnectRuntimeConnection[];
  path_capabilities?: WiiiConnectRuntimePathCapability[];
  capability_summary?: WiiiConnectCapabilitySummary;
  warnings?: string[];
}

export interface WiiiConnectDoctorPathDiagnostic {
  path: string;
  status: "ready" | "guarded" | "blocked" | string;
  reason: string;
  required_connection_slugs?: string[];
  missing_connection_slugs?: string[];
  blocked_connection_reasons?: string[];
  mutation_policy?: string;
  delegation_policy?: string;
  agent_ready_connection_slugs?: string[];
}

export interface WiiiConnectDoctorProviderStage {
  key: string;
  status: "ready" | "pending" | "blocked" | string;
  reason: string;
  required_next?: string[];
}

export interface WiiiConnectDoctorProviderDiagnostic {
  provider_slug: string;
  label: string;
  provider_kind: string;
  status: "ready" | "guarded" | "blocked" | string;
  reason: string;
  connection_status: string;
  active?: boolean;
  agent_ready?: boolean;
  connection_count?: number;
  active_connection_count?: number;
  action_count?: number;
  scope_count?: number;
  required_next?: string[];
  stages?: WiiiConnectDoctorProviderStage[];
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
}

export interface WiiiConnectDoctorReport {
  version: string;
  generated_at?: string;
  surface?: string;
  status: "ready" | "degraded" | "blocked" | string;
  summary?: Record<string, number>;
  path_diagnostics?: WiiiConnectDoctorPathDiagnostic[];
  provider_diagnostics?: WiiiConnectDoctorProviderDiagnostic[];
  top_blockers?: string[];
  warnings?: string[];
}

export interface RuntimeFlowDoctorAlert {
  code: string;
  severity?: "critical" | "error" | "warning" | string;
  count?: number;
  threshold?: string;
}

export interface RuntimeFlowDoctorTrendBucket {
  bucket_start: string;
  turn_count: number;
  alert_counts?: Record<string, number>;
  status_counts?: Record<string, number>;
}

export interface RuntimeFlowDoctorSubagentSummary {
  turn_count?: number;
  report_count?: number;
  state_projected_key_count?: number;
  state_dropped_key_count?: number;
  source_count?: number;
  tool_count?: number;
  thinking_dropped_count?: number;
  raw_content_flag_count?: number;
  warning_count?: number;
  warnings?: Record<string, number>;
  identifier_strategy?: string;
}

export interface RuntimeLifecycleHookRegistration {
  point?: string;
  owner?: string;
  name?: string;
  registered?: boolean;
}

export interface RuntimeLifecycleRegistrationSummary {
  version?: string;
  registration_count?: number;
  owner_counts?: Record<string, number>;
  point_counts?: Record<string, number>;
  default_runtime_hooks?: {
    owner?: string;
    required_count?: number;
    registered_count?: number;
    installed?: boolean;
    hooks?: RuntimeLifecycleHookRegistration[];
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
}

export interface RuntimePostTurnLifecycleMetricsBlock {
  event_count?: number;
  status_counts?: Record<string, number>;
  reason_counts?: Record<string, number>;
  transport_counts?: Record<string, number>;
  semantic_memory_policy_counts?: Record<string, number>;
  group_counts?: Record<string, number>;
}

export interface RuntimePostTurnLifecycleMetricsReport {
  version?: string;
  post_turn?: RuntimePostTurnLifecycleMetricsBlock;
  background_tasks?: RuntimePostTurnLifecycleMetricsBlock;
  source?: {
    metrics_backend?: string;
    window?: string;
    org_scoped?: boolean;
    counter_names?: Record<string, string>;
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
}

export interface RuntimePostTurnLifecycleLedgerReport {
  version?: string;
  event_count?: number;
  missing_count?: number;
  status_counts?: Record<string, number>;
  reason_counts?: Record<string, number>;
  semantic_memory_policy_counts?: Record<string, number>;
  background_tasks_scheduled_count?: number;
  background_tasks_skipped_count?: number;
  raw_content_flag_count?: number;
  background_schedule?: RuntimePostTurnLifecycleMetricsBlock & {
    task_count?: number;
  };
  source?: {
    ledger_path?: string;
    window?: string;
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
}

export interface RuntimeFlowDoctorReport {
  version: string;
  generated_at?: string;
  status: "ready" | "degraded" | "blocked" | string;
  alerts?: RuntimeFlowDoctorAlert[];
  summary?: Record<string, number>;
  request_correlation?: Record<string, number | string>;
  subagents?: RuntimeFlowDoctorSubagentSummary;
  routes?: Record<string, number>;
  finalization_statuses?: Record<string, number>;
  stream_events?: Record<string, number>;
  suppressed_tools?: Record<string, number>;
  observed_tools?: Record<string, number>;
  context_warnings?: Record<string, number>;
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
  alert_trend?: {
    bucket_strategy?: string;
    identifier_strategy?: string;
    buckets?: RuntimeFlowDoctorTrendBucket[];
  };
  source?: {
    session_event_count?: number;
    runtime_flow_ledger_event_count?: number;
    limit?: number;
    org_scoped?: boolean;
    window?: string;
    since_seq?: number | null;
  };
  runtime_config?: Record<string, string | number | boolean>;
  lifecycle_registrations?: RuntimeLifecycleRegistrationSummary;
  post_turn_lifecycle?: RuntimePostTurnLifecycleMetricsReport;
  post_turn_lifecycle_ledger?: RuntimePostTurnLifecycleLedgerReport;
}

export interface RuntimeFlowDoctorHistoryBucket {
  bucket_start: string;
  status: "ready" | "degraded" | "blocked" | string;
  alerts?: RuntimeFlowDoctorAlert[];
  summary?: Record<string, number>;
  request_correlation?: Record<string, number | string>;
  subagents?: RuntimeFlowDoctorSubagentSummary;
  routes?: Record<string, number>;
  finalization_statuses?: Record<string, number>;
  post_turn_lifecycle_ledger?: RuntimePostTurnLifecycleLedgerReport;
  context_warnings?: Record<string, number>;
  source?: {
    session_event_count?: number;
    runtime_flow_ledger_event_count?: number;
  };
}

export interface RuntimeFlowDoctorHistoryReport {
  version: string;
  generated_at?: string;
  bucket_strategy?: string;
  identifier_strategy?: string;
  buckets?: RuntimeFlowDoctorHistoryBucket[];
  source?: {
    session_event_count?: number;
    runtime_flow_ledger_event_count?: number;
    bucket_count?: number;
    bucket_limit?: number;
    limit?: number;
    org_scoped?: boolean;
    window?: string;
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
  runtime_config?: Record<string, string | number | boolean>;
  lifecycle_registrations?: RuntimeLifecycleRegistrationSummary;
  post_turn_lifecycle?: RuntimePostTurnLifecycleMetricsReport;
  post_turn_lifecycle_ledger?: RuntimePostTurnLifecycleLedgerReport;
}

export interface RuntimeFlowSessionEventPruneReport {
  schema: string;
  status: "dry_run" | "pruned" | string;
  matched_count: number;
  deleted_count: number;
  retention_days: number;
  cutoff: string;
  dry_run: boolean;
  org_scoped: boolean;
  event_type_filter_applied: boolean;
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
  runtime_config?: Record<string, string | number | boolean>;
}

export interface SemanticMemoryWriteDoctorReport {
  version: string;
  generated_at?: string;
  status: "ready" | "degraded" | "blocked" | string;
  summary?: Record<string, number>;
  write_kinds?: Record<string, number>;
  write_statuses?: Record<string, number>;
  organization_contexts?: Record<string, number>;
  warnings?: Record<string, number>;
  source?: {
    session_event_count?: number;
    semantic_memory_write_event_count?: number;
    limit?: number;
    org_scoped?: boolean;
    window?: string;
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
  runtime_config?: Record<string, string | number | boolean>;
}

export interface SemanticMemoryWriteDoctorHistoryBucket {
  bucket_start: string;
  status: "ready" | "degraded" | "blocked" | string;
  summary?: Record<string, number>;
  write_kinds?: Record<string, number>;
  write_statuses?: Record<string, number>;
  organization_contexts?: Record<string, number>;
  warnings?: Record<string, number>;
  source?: {
    session_event_count?: number;
    semantic_memory_write_event_count?: number;
  };
}

export interface SemanticMemoryWriteDoctorHistoryReport {
  version: string;
  generated_at?: string;
  bucket_strategy?: string;
  identifier_strategy?: string;
  buckets?: SemanticMemoryWriteDoctorHistoryBucket[];
  source?: {
    session_event_count?: number;
    semantic_memory_write_event_count?: number;
    bucket_count?: number;
    bucket_limit?: number;
    limit?: number;
    org_scoped?: boolean;
    window?: string;
  };
  privacy?: {
    raw_content_included?: boolean;
    identifier_strategy?: string;
  };
  runtime_config?: Record<string, string | number | boolean>;
}

export interface WiiiConnectProviderRegistryEntry {
  version?: string;
  slug: string;
  label: string;
  provider_kind: string;
  auth_mode?: string;
  enabled?: boolean;
  agent_ready?: boolean;
  category?: string;
  description?: string;
  allowed_paths?: string[];
  action_count?: number;
  requirements?: string[];
  connect_requirements?: string[];
  agent_ready_requirements?: string[];
  required_fields?: Array<Record<string, unknown>>;
  default_scopes?: Record<string, boolean>;
  source?: string;
  warnings?: string[];
}

export interface WiiiConnectProviderRegistryResponse {
  version: string;
  adapter_version?: string;
  providers: WiiiConnectProviderRegistryEntry[];
}

export interface WiiiConnectProviderConnectionStatus {
  version: string;
  provider_slug: string;
  label: string;
  provider_kind: string;
  auth_mode: string;
  enabled: boolean;
  agent_ready: boolean;
  can_start_authorization: boolean;
  reason: string;
  missing_requirements: string[];
  warnings?: string[];
}

export interface WiiiConnectSessionStartBody {
  surface?: string;
  redirect_uri?: string | null;
  probe_database?: boolean;
  requested_scopes?: Record<string, boolean>;
  request_metadata?: Record<string, unknown>;
}

export interface WiiiConnectSessionAuditEvent {
  version: string;
  stage: string;
  reason: string;
  created_at: string;
  request: {
    provider_slug: string;
    surface: string;
    requested_scopes: Record<string, boolean>;
    redirect_uri_present: boolean;
    request_metadata_keys: string[];
  };
}

export interface WiiiConnectSessionStartDecision {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  label: string;
  provider_kind: string;
  auth_mode: string;
  authorization_url?: string;
  required_next?: string[];
  audit_event?: WiiiConnectSessionAuditEvent | null;
}

export interface WiiiConnectProviderAdapterCapability {
  version: string;
  provider_kind: string;
  adapter_name: string;
  bound: boolean;
  configured: boolean;
  can_create_authorization_url: boolean;
  can_exchange_callback: boolean;
  can_execute_actions: boolean;
  authorization_ready: boolean;
  reason: string;
  warnings?: string[];
}

export interface WiiiConnectAuthorizationUrlDecision {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  label: string;
  provider_kind: string;
  auth_mode: string;
  authorization_url?: string;
  adapter?: WiiiConnectProviderAdapterCapability | null;
  required_next?: string[];
  audit_event?: WiiiConnectSessionAuditEvent | null;
}

export interface WiiiConnectConnectionLifecycleDecision {
  version: string;
  provider_slug: string;
  status:
    | "disconnected"
    | "authorizing"
    | "waiting"
    | "connected"
    | "expired"
    | "error"
    | "disconnecting"
    | string;
  reason: string;
  active?: boolean;
  connection_present?: boolean;
  agent_ready?: boolean;
  ready_to_connect?: boolean;
  ready_to_execute_action?: boolean;
  required_next?: string[];
}

export interface WiiiConnectProviderConnectionRecord {
  version: string;
  connection_ref: string;
  connection_ref_present?: boolean;
  connection_id?: string;
  provider_slug: string;
  state: string;
  active?: boolean;
  scopes?: Record<string, boolean>;
  vault_ref_present?: boolean;
  account_label?: string;
  external_account_ref_present?: boolean;
  last_checked_at?: string | null;
  reason?: string;
  warnings?: string[];
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
}

export interface WiiiConnectProviderConnectionListResponse {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  provider_kind: string;
  connection_count: number;
  connections: WiiiConnectProviderConnectionRecord[];
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
  provider?: Record<string, unknown> | null;
  storage?: Record<string, unknown> | null;
}

export interface WiiiConnectEffectiveActionStage {
  key: string;
  status: "ready" | "pending" | "blocked" | string;
  reason: string;
  required_next?: string[];
}

export interface WiiiConnectEffectiveActionRecord {
  version: string;
  slug: string;
  provider_slug: string;
  label: string;
  mutation: string;
  path: string;
  status: "ready" | "guarded" | "blocked" | string;
  reason: string;
  runtime_enabled: boolean;
  visible_to_agent: boolean;
  executable_now: boolean;
  requires_preview?: boolean;
  requires_approval?: boolean;
  required_scopes?: string[];
  argument_policy_version?: string;
  argument_keys?: string[];
  model_argument_keys?: string[];
  hidden_argument_count?: number;
  stages?: WiiiConnectEffectiveActionStage[];
  gateway?: Record<string, unknown> | null;
  warnings?: string[];
}

export interface WiiiConnectEffectiveActionInventoryResponse {
  version: string;
  provider_slug: string;
  provider_kind: string;
  status: "ready" | "guarded" | "blocked" | string;
  reason: string;
  connection_ref_present?: boolean;
  connection_present?: boolean;
  connection_active?: boolean;
  selected_connection_required?: boolean;
  catalog_action_count: number;
  runtime_enabled_action_count: number;
  visible_action_count: number;
  executable_action_count: number;
  actions: WiiiConnectEffectiveActionRecord[];
  storage?: Record<string, unknown> | null;
}

export interface WiiiConnectProviderScopeGrantResponse {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  provider_kind: string;
  connection?: WiiiConnectProviderConnectionRecord | null;
  storage?: Record<string, unknown> | null;
}

export interface WiiiConnectFacebookPageOption {
  page_id: string;
  name: string;
  category?: string;
  link?: string;
}

export interface WiiiConnectFacebookPagesResponse {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  action_slug?: string;
  page_count: number;
  pages: WiiiConnectFacebookPageOption[];
  gateway?: Record<string, unknown> | null;
}

export interface WiiiConnectOperationApprovalLedger {
  version?: string;
  status?: "pending" | "consumed" | "blocked" | "unavailable" | "expired" | string;
  reason?: string;
  provider_slug?: string;
  action_slug?: string;
  preview_evidence_id_present?: boolean;
  request_fingerprint_present?: boolean;
  persistent?: boolean;
  consumed?: boolean;
  blocked?: boolean;
  metadata?: Record<string, unknown>;
}

export interface WiiiConnectFacebookPostPreviewResponse {
  version: string;
  status: "blocked" | "ready" | string;
  reason: string;
  provider_slug: string;
  action_slug?: string;
  preview_evidence_id?: string;
  approval_token?: string;
  preview?: {
    page_id: string;
    message: string;
    image_present: boolean;
    image_media_type?: string;
    image_filename?: string;
    image_url_present?: boolean;
  };
  gateway?: Record<string, unknown> | null;
  approval_ledger?: WiiiConnectOperationApprovalLedger | null;
  storage?: Record<string, unknown> | null;
}

export interface WiiiConnectFacebookPostApplyResponse {
  version: string;
  status: "blocked" | "ready" | "succeeded" | "failed" | string;
  reason: string;
  provider_slug: string;
  action_slug?: string;
  token?: Record<string, unknown> | null;
  gateway?: Record<string, unknown> | null;
  schema?: Record<string, unknown> | null;
  upload?: Record<string, unknown> | null;
  execution?: Record<string, unknown> | null;
  approval_ledger?: WiiiConnectOperationApprovalLedger | null;
  storage?: Record<string, unknown> | null;
  missing_argument_keys?: string[];
}

export interface WiiiConnectActivationGate {
  key: string;
  ready: boolean;
  reason: string;
  required_next?: string[];
  metadata?: Record<string, unknown>;
}

export interface WiiiConnectActivationReadinessConnection {
  present?: boolean;
  provider_slug?: string;
  state?: string;
  active?: boolean;
  scopes?: Record<string, boolean>;
  vault_ref_present?: boolean;
  account_label_present?: boolean;
  external_account_ref_present?: boolean;
  last_checked_at_present?: boolean;
  reason?: string;
  warnings?: string[];
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
}

export interface WiiiConnectActivationReadinessResponse {
  version: string;
  status: "blocked" | "ready" | string;
  provider_slug: string;
  provider_kind: string;
  ready_to_connect: boolean;
  ready_to_execute_action?: boolean;
  ready_to_execute_readonly: boolean;
  gates: WiiiConnectActivationGate[];
  provider?: Record<string, unknown> | null;
  execution_provider?: Record<string, unknown> | null;
  adapter?: WiiiConnectProviderAdapterCapability | null;
  vault?: Record<string, unknown> | null;
  storage?: Record<string, unknown> | null;
  action?: Record<string, unknown> | null;
  connection?: WiiiConnectActivationReadinessConnection | null;
  connection_lifecycle?: WiiiConnectConnectionLifecycleDecision | null;
  execution_gateway?: Record<string, unknown> | null;
}

export interface WiiiConnectProviderDisconnectResponse {
  version: string;
  status: "blocked" | "succeeded" | "failed" | string;
  reason: string;
  provider_slug: string;
  provider_kind: string;
  connection_present: boolean;
  local_disabled: boolean;
  provider?: Record<string, unknown> | null;
  storage?: Record<string, unknown> | null;
}

export interface SSEChatLifecycleEvent {
  schema_version: string;
  event_name: string;
  phase: string;
  status: string;
  message: string;
  request_id?: string;
  session_id?: string;
  lane?: string;
  reason?: string;
  node?: string;
  step?: string;
  capabilities?: {
    host_surface?: string;
    host_capabilities?: string[];
    observed_tools?: string[];
    suppressed_tools?: string[];
    preview_required?: boolean;
    preview_emitted?: boolean;
    approval_token_present?: boolean;
    apply_attempted?: boolean;
    wiii_connect?: WiiiConnectRuntimeSnapshot;
  };
  metadata?: Record<string, unknown>;
  details?: Record<string, unknown>;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface ChatLifecycleTelemetryEvent extends SSEChatLifecycleEvent {
  received_at_ms: number;
}

export interface SSEDomainNoticeEvent {
  content: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/** Sprint 135: Soul emotion event — LLM-driven avatar expression */
export interface SSEEmotionEvent {
  mood: MoodType;
  face: Partial<Record<string, number>>;
  intensity: number;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEThinkingDeltaEvent {
  content: string;
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/** Sprint 147: Bold action text event — narrative between thinking blocks */
export interface SSEActionTextEvent {
  content: string;
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/** Sprint 153: Browser screenshot event — Playwright visual transparency */
export interface SSEBrowserScreenshotEvent {
  content: {
    url: string;
    image: string;   // Base64 JPEG
    label: string;
  };
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEThinkingStartEvent {
  type: "thinking_start";
  content: string;  // label (Vietnamese node name)
  node?: string;
  block_id?: string;
  /** Sprint 145: One-line summary for Claude-like collapsed header */
  summary?: string;
  /** Whether summary is only metadata/header, not visible body fallback */
  summary_mode?: ThinkingSummaryMode;
  /** Runtime reasoning phase from backend contract */
  phase?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEThinkingEndEvent {
  type: "thinking_end";
  node?: string;
  duration_ms?: number;
  block_id?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export type SSEEventType =
  | "thinking"
  | "thinking_delta"
  | "answer"
  | "sources"
  | "metadata"
  | "chat_lifecycle"
  | "done"
  | "error"
  | "tool_call"
  | "tool_result"
  | "status"
  | "thinking_start"
  | "thinking_end"
  | "domain_notice"
  | "emotion"
  | "action_text"
  | "browser_screenshot"
  | "preview"
  | "artifact"
  | "visual"
  | "visual_open"
  | "visual_patch"
  | "visual_commit"
  | "visual_dispose";

export interface ToolCallInfo {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  result?: string;
  node?: string;
}

export type DisplayRole = "thinking" | "tool" | "action" | "answer" | "artifact";
export type StepState = "live" | "completed";
export type PresentationMode = "compact" | "expanded" | "technical";
export type ThinkingSummaryMode = "header_only" | "body_fallback";

export interface DisplayPresentationMeta {
  displayRole?: DisplayRole;
  sequenceId?: number;
  stepId?: string;
  stepState?: StepState;
  presentation?: PresentationMode;
}

// ===== Streaming Progress =====

/** Pipeline progress step (separate from AI thinking content) */
export interface StreamingStep {
  label: string;
  node?: string;
  timestamp: number;
}

// ===== Content Blocks (interleaved thinking/answer) =====

/** A thinking block with optional inline tool calls */
export interface ThinkingBlockData extends DisplayPresentationMeta {
  type: "thinking";
  id: string;
  label?: string;
  /** Sprint 145: One-line summary for Claude-like collapsed header */
  summary?: string;
  summaryMode?: ThinkingSummaryMode;
  /** Backend node that produced this thinking block */
  node?: string;
  /** Runtime reasoning phase from backend contract */
  phase?: string;
  content: string;
  toolCalls: ToolCallInfo[];
  /** epoch ms when block was created (for duration) */
  startTime?: number;
  /** epoch ms when block was closed (next block started) */
  endTime?: number;
  /** Sprint 164: Parent subagent group ID (for grouped rendering) */
  groupId?: string;
  /** Sprint 164: Agent name within the parallel group */
  workerNode?: string;
}

export interface ToolExecutionBlockData extends DisplayPresentationMeta {
  type: "tool_execution";
  id: string;
  tool: ToolCallInfo;
  node?: string;
  status: "pending" | "completed";
}

/** An answer/content block with markdown text */
export interface AnswerBlockData extends DisplayPresentationMeta {
  type: "answer";
  id: string;
  content: string;
}

/** Sprint 147: Bold narrative text between thinking blocks (Claude-style action text) */
export interface ActionTextBlockData extends DisplayPresentationMeta {
  type: "action_text";
  id: string;
  content: string;
  /** Sprint 149: Source agent node for attribution */
  node?: string;
}

/** Sprint 153: Browser screenshot block — Playwright visual transparency */
export interface ScreenshotBlockData extends DisplayPresentationMeta {
  type: "screenshot";
  id: string;
  url: string;
  image: string;           // Base64 JPEG - kept permanently
  label: string;
  node?: string;
}

/** Sprint 164: Subagent worker status within a parallel dispatch group */
export interface SubagentWorker {
  agentName: string;
  label: string;
  status: "active" | "completed" | "error";
  startTime: number;
  endTime?: number;
  /** Status messages for per-worker progress display */
  statusMessages: string[];
}

/** Sprint 164: Aggregation decision summary from the aggregator node */
export interface AggregationSummary {
  strategy: string;
  primaryAgent?: string;
  confidence: number;
  reasoning: string;
}

/** Sprint 164: Subagent group block — visual container for parallel dispatch */
export interface SubagentGroupBlockData extends DisplayPresentationMeta {
  type: "subagent_group";
  id: string;
  label: string;
  workers: SubagentWorker[];
  aggregation?: AggregationSummary;
  startTime: number;
  endTime?: number;
}

// ===== Execution Result (Sprint 167b: deduplicated from artifact-sandbox + pyodide-runtime) =====
export interface ExecutionResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  images: string[];      // base64 PNG from matplotlib
  tables: unknown[][];   // pandas DataFrame as arrays
  executionTime: number;  // ms
}

// ===== Artifact System (Sprint 167) =====
export type ArtifactType = "code" | "html" | "react" | "table" | "chart" | "document" | "excel";

export interface ArtifactData {
  artifact_type: ArtifactType;
  artifact_id: string;
  title: string;
  content: string;
  language?: string;
  metadata?: {
    execution_status?: "pending" | "running" | "success" | "error";
    output?: string;
    error?: string;
    image_url?: string;
    table_data?: unknown[];
    file_url?: string;
    [key: string]: unknown;
  };
}

export interface ArtifactBlockData extends DisplayPresentationMeta {
  type: "artifact";
  id: string;
  artifact: ArtifactData;
  node?: string;
}

/** Sprint 167: SSE artifact event */
export interface SSEArtifactEvent {
  content: ArtifactData;
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

// ===== Structured Visual System (Sprint 230) =====
export type VisualType =
  | "comparison"
  | "process"
  | "matrix"
  | "architecture"
  | "concept"
  | "infographic"
  | "chart"
  | "timeline"
  | "map_lite"
  | "simulation"
  | "quiz"
  | "interactive_table"
  | "react_app";

export type VisualRuntime = "svg" | "sandbox_html" | "sandbox_react";
export type VisualRendererKind = "template" | "inline_html" | "app" | "recharts";
export type VisualShellVariant = "editorial" | "compact" | "immersive";
export type VisualPatchStrategy = "spec_merge" | "replace_html" | "app_state";
export type VisualInteractionMode = "static" | "guided" | "explorable" | "scrubbable" | "filterable";
export type VisualLifecycleEventType = "visual_open" | "visual_patch";
export type VisualSessionStatus = "open" | "committed" | "disposed";
export type VisualPedagogicalRole =
  | "problem"
  | "mechanism"
  | "comparison"
  | "architecture"
  | "result"
  | "benchmark"
  | "conclusion";
export type VisualChromeMode = "editorial" | "app" | "immersive";

export interface VisualRuntimeManifest {
  ui_runtime: string;
  storage?: boolean;
  mcp_access?: boolean;
  file_export?: boolean;
  shareability?: string;
}

export interface VisualControlOption {
  value: string;
  label: string;
}

export interface VisualControl {
  id: string;
  type: "select" | "range" | "chips" | "toggle";
  label: string;
  value?: string | number | boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: VisualControlOption[];
}

export interface VisualAnnotation {
  id: string;
  title: string;
  body: string;
  target_id?: string;
  tone?: "neutral" | "accent" | "warning" | "success";
}

export interface VisualSceneNode {
  id: string;
  label: string;
  kind?: string;
  parent_id?: string;
  metadata?: Record<string, unknown>;
}

export interface VisualScenePanel {
  id: string;
  title: string;
  body?: string;
  node_ids?: string[];
}

export interface VisualScene {
  kind: string;
  nodes?: VisualSceneNode[];
  links?: Array<{
    source: string;
    target: string;
    label?: string;
  }>;
  panels?: VisualScenePanel[];
  scales?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface VisualPayload {
  id: string;
  visual_session_id: string;
  type: VisualType;
  renderer_kind: VisualRendererKind;
  shell_variant: VisualShellVariant;
  patch_strategy: VisualPatchStrategy;
  figure_group_id: string;
  figure_index: number;
  figure_total: number;
  pedagogical_role: VisualPedagogicalRole;
  chrome_mode: VisualChromeMode;
  claim: string;
  presentation_intent?: "text" | "article_figure" | "chart_runtime" | "code_studio_app" | "artifact";
  figure_budget?: number;
  quality_profile?: "draft" | "standard" | "premium";
  renderer_contract?: "host_shell" | "chart_runtime" | "article_figure";
  studio_lane?: "app" | "artifact" | "widget" | null;
  artifact_kind?: "html_app" | "code_widget" | "search_widget" | "document" | "chart_widget" | null;
  narrative_anchor: string;
  runtime: VisualRuntime;
  title: string;
  summary: string;
  spec: Record<string, unknown>;
  scene: VisualScene;
  controls: VisualControl[];
  annotations: VisualAnnotation[];
  interaction_mode: VisualInteractionMode;
  ephemeral: boolean;
  lifecycle_event: VisualLifecycleEventType;
  subtitle?: string;
  fallback_html?: string;
  runtime_manifest?: VisualRuntimeManifest | null;
  artifact_handoff_available?: boolean;
  artifact_handoff_mode?: "none" | "followup_prompt";
  artifact_handoff_label?: string | null;
  artifact_handoff_prompt?: string | null;
  metadata?: Record<string, unknown>;
}

export interface VisualBlockData extends DisplayPresentationMeta {
  type: "visual";
  id: string;
  sessionId?: string;
  visual: VisualPayload;
  node?: string;
  status?: VisualSessionStatus;
}

export interface SSEVisualEvent {
  content: VisualPayload;
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEVisualCommitEvent {
  content: {
    visual_session_id: string;
    status?: VisualSessionStatus;
  };
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface SSEVisualDisposeEvent {
  content: {
    visual_session_id: string;
    reason?: string;
    status?: VisualSessionStatus;
  };
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

export interface VisualSessionState {
  sessionId: string;
  latestVisual: VisualPayload;
  status: VisualSessionStatus;
  revisionCount: number;
  node?: string;
  controlValues: Record<string, string | number | boolean>;
  focusedAnnotationId?: string;
  focusedNodeId?: string;
  interactionCount: number;
  lastUpdatedAt: number;
}

// ===== Preview System (Sprint 166) =====
export type PreviewType = "document" | "product" | "web" | "link" | "code" | "host_action";

export interface PreviewItemData {
  preview_type: PreviewType;
  preview_id: string;
  title: string;
  snippet?: string;
  url?: string;
  image_url?: string;
  citation_index?: number;
  metadata?: Record<string, unknown>;
}

export interface PreviewBlockData extends DisplayPresentationMeta {
  type: "preview";
  id: string;
  items: PreviewItemData[];
  node?: string;
}

/** Sprint 166: SSE preview event */
export interface SSEPreviewEvent {
  content: PreviewItemData;
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/** Sprint 222b: SSE host_action event — AI requests an action from the host app */
export interface SSEHostActionEvent {
  content: {
    id: string;
    action: string;
    params?: Record<string, unknown>;
  };
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/**
 * Wiii Pointy SSE event — agent invokes ``tool_pointy_show`` /
 * ``tool_pointy_clear`` and the runtime emits this to drive the
 * collaborator cursor / spotlight overlay.
 *
 * The action / params shape mirrors the existing ``PointyFastPathAction``
 * so the same in-app handlers (``handleHighlight`` / ``handleCursorMove``
 * from ``pointy-host/bridge.ts``) can run without a translation layer.
 * See ``app/engine/skills/library/wiii-pointy/SKILL.md`` for trigger
 * taxonomy and caption guidance.
 */
export interface SSEPointyActionEvent {
  content: {
    action: "ui.highlight" | "ui.cursor_move" | "ui.clear";
    requestId: string;
    params: {
      selector?: string;
      message?: string;
      duration_ms?: number;
      x?: number;
      y?: number;
      coordinate_space?: "viewport" | "normalized";
      label?: string;
      source: string;
    };
    mode: "highlight" | "cursor" | "clear";
  };
  node?: string;
  display_role?: DisplayRole;
  sequence_id?: number;
  step_id?: string;
  step_state?: StepState;
  presentation?: PresentationMode;
}

/** Code Studio: session opened */
export interface SSECodeOpenEvent {
  content: {
    session_id: string;
    title: string;
    language: string;
    version: number;
    studio_lane?: "app" | "artifact" | "widget";
    artifact_kind?: "html_app" | "code_widget" | "search_widget" | "document" | "chart_widget";
    quality_profile?: "draft" | "standard" | "premium";
    renderer_contract?: "host_shell" | "chart_runtime" | "article_figure";
    requested_view?: "code" | "preview";
  };
  node?: string;
}

/** Code Studio: chunked code content */
export interface SSECodeDeltaEvent {
  content: {
    session_id: string;
    chunk: string;
    chunk_index: number;
    total_bytes: number;
  };
  node?: string;
}

/** Code Studio: full code + trigger preview */
export interface SSECodeCompleteEvent {
  content: {
    session_id: string;
    full_code: string;
    language: string;
    version: number;
    studio_lane?: "app" | "artifact" | "widget";
    artifact_kind?: "html_app" | "code_widget" | "search_widget" | "document" | "chart_widget";
    quality_profile?: "draft" | "standard" | "premium";
    renderer_contract?: "host_shell" | "chart_runtime" | "article_figure";
    requested_view?: "code" | "preview";
    visual_payload?: VisualPayload;
    /** Maps streaming session to the visual_open session for frontend unification */
    visual_session_id?: string;
  };
  node?: string;
}

/** Ordered content block - enables interleaved thinking+answer rendering */
export type ContentBlock =
  | ThinkingBlockData
  | ToolExecutionBlockData
  | AnswerBlockData
  | ActionTextBlockData
  | ScreenshotBlockData
  | SubagentGroupBlockData
  | VisualBlockData
  | PreviewBlockData
  | ArtifactBlockData;

/** Sprint 141: Unified thinking phase for ThinkingFlow component */
export interface ThinkingPhase {
  id: string;
  label: string;              // Vietnamese label from thinking_start
  node?: string;              // Backend node name
  stepId?: string;            // Stable SSE step_id / block_id for interval grouping
  phase?: string;             // Backend reasoning phase label
  summary?: string;           // One-line summary from thinking_start
  summaryMode?: ThinkingSummaryMode;
  status: "active" | "completed";
  startTime: number;
  endTime?: number;
  thinkingContent: string;    // AI reasoning (from thinking/thinking_delta)
  toolCalls: ToolCallInfo[];  // Inline tool cards
  statusMessages: string[];   // Status updates within this phase
}

// ===== Domain =====
export interface DomainSummary {
  id: string;
  name: string;
  name_vi?: string;
  version: string;
  description: string;
  skill_count: number;
  keyword_count: number;
}

// ===== Organization (Sprint 156) =====
export interface OrganizationSummary {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  allowed_domains: string[];
  default_domain?: string;
  is_active: boolean;
}

// ===== Org Settings (Sprint 161) =====
export interface OrgBranding {
  logo_url: string | null;
  primary_color: string;
  accent_color: string;
  welcome_message: string;
  chatbot_name: string;
  chatbot_avatar_url: string | null;
  institution_type: string;
}

export interface OrgFeatureFlags {
  enable_product_search: boolean;
  enable_deep_scanning: boolean;
  enable_thinking_chain: boolean;
  enable_browser_scraping: boolean;
  visible_agents: string[];
  max_search_iterations: number;
}

export interface OrgPermissions {
  student: string[];
  teacher: string[];
  admin: string[];
}

export interface OrgOnboarding {
  quick_start_questions: string[];
  show_domain_suggestions: boolean;
}

export interface OrgSettings {
  schema_version: number;
  branding: OrgBranding;
  features: OrgFeatureFlags;
  ai_config: {
    persona_prompt_overlay: string | null;
    temperature_override: number | null;
    max_response_length: number | null;
    default_domain: string | null;
  };
  permissions: OrgPermissions;
  onboarding: OrgOnboarding;
}

export interface OrgPermissionsResponse {
  permissions: string[];
  role: string;
  permission_role?: string;
  legacy_role?: string;
  platform_role?: PlatformRole | string;
  organization_id: string;
  org_role?: string | null;  // Sprint 215: member | admin | owner
}

// ===== Health =====
export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  components?: Record<string, {
    name: string;
    status: "healthy" | "degraded" | "unavailable";
    latency_ms?: number;
    message?: string;
  }>;
}

// ===== Context Management (Sprint 78/80) =====
export interface ContextLayerInfo {
  budget: number;
  used: number;
}

export interface ContextInfoResponse {
  effective_window: number;
  max_output: number;
  total_budget: number;
  total_used: number;
  utilization: number;
  needs_compaction: boolean;
  layers: {
    system_prompt: ContextLayerInfo;
    core_memory: ContextLayerInfo;
    summary: ContextLayerInfo;
    recent_messages: ContextLayerInfo;
  };
  messages_included: number;
  messages_dropped: number;
  has_summary: boolean;
  session_id: string;
  running_summary_chars: number;
  total_history_messages: number;
}

export interface CompactResponse {
  status: string;
  session_id: string;
  summary_length: number;
  messages_summarized: number;
  message: string;
}

export interface ClearContextResponse {
  status: string;
  session_id: string;
  message: string;
}

// ===== Memory Management (Sprint 80) =====
export interface MemoryItem {
  id: string;
  type: string;
  value: string;
  created_at: string;
}

export interface MemoryHealthSummary {
  total: number;
  type_counts: Record<string, number>;
  latest_created_at: string | null;
  scope_state: string;
  org_scoped: boolean;
  controls: {
    can_delete_one: boolean;
    can_clear_all: boolean;
  };
  provenance: {
    source_kinds: Record<string, number>;
    raw_content_included: boolean;
    identifier_strategy: string;
  };
  privacy: {
    raw_content_included: boolean;
    identifier_strategy: string;
  };
}

export interface MemoryListResponse {
  data: MemoryItem[];
  total: number;
  summary?: MemoryHealthSummary;
}

export interface DeleteMemoryResponse {
  success: boolean;
  message: string;
}

export interface ClearMemoriesResponse {
  success: boolean;
  deleted_count: number;
  message: string;
}

// ===== Character State (Sprint 120) =====
export interface CharacterBlockInfo {
  label: string;
  content: string;
  char_limit: number;
  usage_percent: number;
}

export interface CharacterCardInfo {
  card_id: string;
  card_name: string;
  card_kind: string;
  card_family: string;
  contract_version: string;
  name: string;
  summary: string;
  origin: string;
  greeting: string;
  traits: string[];
  quirks: string[];
  core_truths: string[];
  reasoning_style: string[];
  relationship_style: string[];
  anti_drift: string[];
  runtime_notes: string[];
}

export interface CharacterStateResponse {
  blocks: CharacterBlockInfo[];
  total_blocks: number;
  card?: CharacterCardInfo | null;
}

// ===== Mood / Emotional State (Sprint 120) =====
export type MoodType = "excited" | "warm" | "concerned" | "gentle" | "neutral";

// ===== User Profile (Sprint 158) =====
export interface UserProfile {
  id: string;
  email?: string;
  name?: string;
  avatar_url?: string;
  role: string;
  legacy_role?: string;
  platform_role?: PlatformRole;
  organization_role?: OrganizationRole | string;
  host_role?: string;
  role_source?: string;
  active_organization_id?: string;
  connector_id?: string;
  identity_version?: string;
  connected_workspaces_count?: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ConnectedWorkspace {
  id: string;
  connector_id: string;
  grant_key: string;
  host_type: string;
  host_name?: string;
  host_user_id?: string;
  host_workspace_id?: string;
  host_organization_id?: string;
  organization_id?: string;
  granted_capabilities: Record<string, unknown>;
  auth_metadata: Record<string, unknown>;
  status: string;
  created_at?: string;
  updated_at?: string;
  last_connected_at?: string;
  last_used_at?: string;
}

export interface UserIdentity {
  id: string;
  provider: string;
  provider_sub: string;
  provider_issuer?: string;
  email?: string;
  display_name?: string;
  avatar_url?: string;
  linked_at?: string;
  last_used_at?: string;
}

// ===== Local types (desktop-only) =====
export interface Conversation {
  id: string;
  title: string;
  domain_id?: string;
  organization_id?: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
  session_id?: string;
  thread_id?: string;
  pinned?: boolean;
  message_count?: number;
  summary?: string;
  user_renamed?: boolean;  // Sprint 225: tracks if user explicitly renamed (prevents server title overwrite)
  widget_feedback?: WidgetFeedbackItem[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sources?: SourceInfo[];
  suggested_questions?: string[];
  thinking?: string;
  reasoning_trace?: ReasoningTrace;
  tools_used?: ToolUsageInfo[];
  tool_calls?: ToolCallInfo[];
  /** Ordered content blocks — interleaved thinking + answer. New in Sprint 62. */
  blocks?: ContentBlock[];
  /** Sprint 80b: Gentle notice when content is outside active domain */
  domain_notice?: string;
  /** Sprint 107: User feedback rating */
  feedback?: "up" | "down" | null;
  /** Sprint 166: Rich preview cards */
  previews?: PreviewItemData[];
  /** Sprint 167: Interactive artifacts */
  artifacts?: ArtifactData[];
  /** Sprint 179: User-attached images (multimodal vision) */
  images?: ImageInput[];
  /** Per-turn user-attached documents shown as chips; Markdown lives only in request context. */
  documents?: ChatDocumentAttachment[];
  is_streaming?: boolean;
  metadata?: Record<string, unknown>;
}

/** Sprint 140: Thinking display level — progressive disclosure */
export type ThinkingLevel = "minimal" | "balanced" | "detailed";

export interface AppSettings {
  server_url: string;
  api_key: string;
  llm_provider?: "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  google_model?: string;
  openai_base_url?: string;
  openai_model?: string;
  openai_model_advanced?: string;
  openrouter_base_url?: string;
  openrouter_model?: string;
  openrouter_model_advanced?: string;
  zhipu_base_url?: string;
  zhipu_model?: string;
  zhipu_model_advanced?: string;
  openrouter_model_fallbacks?: string[];
  openrouter_provider_order?: string[];
  openrouter_allowed_providers?: string[];
  openrouter_ignored_providers?: string[];
  openrouter_allow_fallbacks?: boolean | null;
  openrouter_require_parameters?: boolean | null;
  openrouter_data_collection?: "allow" | "deny" | "";
  openrouter_zdr?: boolean | null;
  openrouter_provider_sort?: "price" | "latency" | "throughput" | "";
  ollama_base_url?: string;
  ollama_model?: string;
  ollama_keep_alive?: string;
  llm_failover_enabled?: boolean;
  llm_failover_chain?: string[];
  user_id: string;
  user_role: UserRole;
  display_name: string;
  default_domain: string;
  /** Sprint 156: Active organization ID (null = personal workspace) */
  organization_id?: string | null;
  theme: "light" | "dark" | "system";
  language: "vi" | "en";
  font_size?: "small" | "medium" | "large";
  show_thinking: boolean;
  show_reasoning_trace: boolean;
  /** F18 Phase B (2026-05-07) — Pointy mode: user talks directly to
   * cursor; backend forces tool_pointy_show per turn (deterministic
   * UI navigation, cursor-agent persona). */
  pointy_mode?: boolean;
  /** Optional ElevenLabs-backed spoken Pointy captions. Audio is opt-in. */
  pointy_voice_enabled?: boolean;
  streaming_version: "v1" | "v2" | "v3";
  /** Sprint 140: Thinking level — minimal (status only), balanced (collapsed), detailed (expanded) */
  thinking_level: ThinkingLevel;
  /** Sprint 154: Facebook cookie for logged-in search (optional) */
  facebook_cookie?: string;
  /** Sprint 166: Show rich preview cards */
  show_previews?: boolean;
  /** Sprint 167: Show interactive artifacts */
  show_artifacts?: boolean;
  /** Per-request model provider selection (persisted across reloads) */
  model_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
}

export interface LlmRuntimeConfig {
  provider: "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  use_multi_agent: boolean;
  google_model: string;
  openai_base_url?: string | null;
  openai_model: string;
  openai_model_advanced: string;
  openrouter_base_url?: string | null;
  openrouter_model: string;
  openrouter_model_advanced: string;
  zhipu_base_url?: string | null;
  zhipu_model: string;
  zhipu_model_advanced: string;
  openrouter_model_fallbacks: string[];
  openrouter_provider_order: string[];
  openrouter_allowed_providers: string[];
  openrouter_ignored_providers: string[];
  openrouter_allow_fallbacks?: boolean | null;
  openrouter_require_parameters?: boolean | null;
  openrouter_data_collection?: "allow" | "deny" | null;
  openrouter_zdr?: boolean | null;
  openrouter_provider_sort?: "price" | "latency" | "throughput" | null;
  ollama_base_url?: string | null;
  ollama_model: string;
  ollama_keep_alive?: string | null;
  google_api_key_configured: boolean;
  openai_api_key_configured: boolean;
  openrouter_api_key_configured: boolean;
  zhipu_api_key_configured: boolean;
  ollama_api_key_configured: boolean;
  enable_llm_failover: boolean;
  llm_failover_chain: string[];
  active_provider?: string | null;
  providers_registered: string[];
  request_selectable_providers: string[];
  provider_status: ProviderRuntimeStatus[];
  agent_profiles: Record<string, AgentRuntimeProfileConfig>;
  timeout_profiles: LlmTimeoutProfilesConfig;
  timeout_provider_overrides: Record<string, LlmTimeoutProviderOverride>;
  vision_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_describe_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_describe_model?: string | null;
  vision_ocr_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_ocr_model?: string | null;
  vision_grounded_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_grounded_model?: string | null;
  vision_failover_chain?: string[];
  vision_timeout_seconds: number;
  vision_provider_status?: VisionProviderRuntimeStatus[];
  vision_audit_updated_at?: string | null;
  vision_last_live_probe_at?: string | null;
  vision_audit_persisted?: boolean;
  vision_audit_warnings?: string[];
  embedding_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  embedding_failover_chain?: string[];
  embedding_model: string;
  embedding_dimensions: number;
  embedding_status: string;
  embedding_provider_status?: EmbeddingProviderRuntimeStatus[];
  embedding_space_status?: EmbeddingSpaceStatusSummary | null;
  embedding_migration_previews?: EmbeddingMigrationPreview[];
  runtime_policy_persisted: boolean;
  runtime_policy_updated_at?: string | null;
  warnings: string[];
}

export interface ProviderRuntimeStatus {
  provider: string;
  display_name: string;
  configured: boolean;
  available: boolean;
  registered: boolean;
  request_selectable: boolean;
  in_failover_chain: boolean;
  is_default: boolean;
  is_active: boolean;
  configurable_via_admin: boolean;
  reason_code?: ProviderDisabledReasonCode | string | null;
  reason_label?: string | null;
}

export interface EmbeddingProviderRuntimeStatus {
  provider: string;
  display_name: string;
  configured: boolean;
  available: boolean;
  in_failover_chain: boolean;
  is_default: boolean;
  is_active: boolean;
  selected_model?: string | null;
  selected_dimensions?: number | null;
  supports_dimension_override: boolean;
  reason_code?: string | null;
  reason_label?: string | null;
}

export interface VisionCapabilityRuntimeStatus {
  capability: string;
  display_name: string;
  available: boolean;
  selected_model?: string | null;
  lane_fit?: string | null;
  lane_fit_label?: string | null;
  reason_code?: string | null;
  reason_label?: string | null;
  resolved_base_url?: string | null;
  last_probe_attempt_at?: string | null;
  last_probe_success_at?: string | null;
  last_probe_error?: string | null;
  live_probe_note?: string | null;
  last_runtime_observation_at?: string | null;
  last_runtime_success_at?: string | null;
  last_runtime_error?: string | null;
  last_runtime_note?: string | null;
  last_runtime_source?: string | null;
  recovered?: boolean;
  recovered_label?: string | null;
}

export interface VisionProviderRuntimeStatus {
  provider: string;
  display_name: string;
  configured: boolean;
  available: boolean;
  in_failover_chain: boolean;
  is_default: boolean;
  is_active: boolean;
  selected_model?: string | null;
  reason_code?: string | null;
  reason_label?: string | null;
  last_probe_attempt_at?: string | null;
  last_probe_success_at?: string | null;
  last_probe_error?: string | null;
  last_runtime_observation_at?: string | null;
  last_runtime_success_at?: string | null;
  last_runtime_error?: string | null;
  last_runtime_note?: string | null;
  last_runtime_source?: string | null;
  degraded?: boolean;
  degraded_reasons?: string[];
  recovered?: boolean;
  recovered_reasons?: string[];
  capabilities: VisionCapabilityRuntimeStatus[];
}

export interface EmbeddingSpaceContractSummary {
  provider: string;
  model: string;
  dimensions: number;
  fingerprint: string;
  label: string;
}

export interface EmbeddingSpaceTableSummary {
  table_name: string;
  embedded_row_count: number;
  tracked_row_count: number;
  untracked_row_count: number;
  fingerprints: Record<string, number>;
}

export interface EmbeddingMigrationPreview {
  target_model: string;
  target_provider: string;
  target_dimensions: number;
  target_label: string;
  target_status: string;
  same_space: boolean;
  allowed: boolean;
  requires_reembed: boolean;
  target_backend_constructible: boolean;
  maintenance_required: boolean;
  embedded_row_count: number;
  blocking_tables: string[];
  mixed_tables: string[];
  warnings: string[];
  recommended_steps: string[];
  detail?: string | null;
}

export interface EmbeddingSpaceStatusSummary {
  audit_available: boolean;
  policy_contract?: EmbeddingSpaceContractSummary | null;
  active_contract?: EmbeddingSpaceContractSummary | null;
  active_matches_policy?: boolean | null;
  total_embedded_rows: number;
  total_tracked_rows: number;
  total_untracked_rows: number;
  tables: EmbeddingSpaceTableSummary[];
  warnings: string[];
  error?: string | null;
}

export interface EmbeddingSpaceMigrationTablePlanSummary {
  table_name: string;
  candidate_rows: number;
  embedded_rows: number;
  tracked_rows: number;
  untracked_rows: number;
}

export interface EmbeddingSpaceMigrationPlanRequest {
  target_model: string;
  target_dimensions?: number;
  tables?: string[];
}

export interface EmbeddingSpaceMigrationPlanResponse {
  current_contract_fingerprint?: string | null;
  target_contract_fingerprint?: string | null;
  current_contract_label?: string | null;
  target_contract_label?: string | null;
  same_space: boolean;
  transition_allowed: boolean;
  target_backend_constructible: boolean;
  maintenance_required: boolean;
  total_candidate_rows: number;
  total_embedded_rows: number;
  tables: EmbeddingSpaceMigrationTablePlanSummary[];
  warnings: string[];
  recommended_steps: string[];
  detail?: string | null;
}

export interface EmbeddingSpaceMigrationTableResultSummary {
  table_name: string;
  candidate_rows: number;
  updated_rows: number;
  skipped_rows: number;
  failed_rows: number;
}

export interface EmbeddingSpaceMigrationRunRequest {
  target_model: string;
  target_dimensions?: number;
  dry_run?: boolean;
  batch_size?: number;
  limit_per_table?: number;
  tables?: string[];
  acknowledge_maintenance_window?: boolean;
}

export interface EmbeddingSpaceMigrationRunResponse {
  dry_run: boolean;
  maintenance_acknowledged: boolean;
  current_contract_fingerprint?: string | null;
  target_contract_fingerprint?: string | null;
  target_backend_constructible: boolean;
  tables: EmbeddingSpaceMigrationTableResultSummary[];
  warnings: string[];
  detail?: string | null;
  recommended_next_steps: string[];
}

export interface EmbeddingSpaceMigrationPromoteRequest {
  target_model: string;
  target_dimensions?: number;
  tables?: string[];
  acknowledge_maintenance_window?: boolean;
}

export interface AgentRuntimeProfileConfig {
  default_provider: "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  tier: "deep" | "moderate" | "light";
  provider_models: Record<string, string>;
}

export interface LlmTimeoutProfilesConfig {
  light_seconds: number;
  moderate_seconds: number;
  deep_seconds: number;
  structured_seconds: number;
  background_seconds: number;
  stream_keepalive_interval_seconds: number;
  stream_idle_timeout_seconds: number;
}

export interface LlmTimeoutProviderOverride {
  light_seconds?: number | null;
  moderate_seconds?: number | null;
  deep_seconds?: number | null;
  structured_seconds?: number | null;
  background_seconds?: number | null;
}

export interface ModelCatalogEntry {
  provider: string;
  model_name: string;
  display_name: string;
  status: string;
  released_on?: string | null;
  is_default: boolean;
}

export interface ProviderCatalogCapability {
  provider: string;
  display_name: string;
  configured: boolean;
  available: boolean;
  request_selectable: boolean;
  configurable_via_admin: boolean;
  supports_runtime_discovery: boolean;
  runtime_discovery_enabled: boolean;
  runtime_discovery_succeeded: boolean;
  catalog_source: "static" | "runtime" | "mixed";
  model_count: number;
  discovered_model_count: number;
  selected_model?: string | null;
  selected_model_in_catalog: boolean;
  selected_model_advanced?: string | null;
  selected_model_advanced_in_catalog: boolean;
  last_discovery_attempt_at?: string | null;
  last_discovery_success_at?: string | null;
  last_live_probe_attempt_at?: string | null;
  last_live_probe_success_at?: string | null;
  last_live_probe_error?: string | null;
  live_probe_note?: string | null;
  last_runtime_observation_at?: string | null;
  last_runtime_success_at?: string | null;
  last_runtime_error?: string | null;
  last_runtime_note?: string | null;
  last_runtime_source?: string | null;
  degraded: boolean;
  degraded_reasons: string[];
  recovered: boolean;
  recovered_reasons: string[];
  tool_calling_supported?: boolean | null;
  tool_calling_source?: string | null;
  structured_output_supported?: boolean | null;
  structured_output_source?: string | null;
  streaming_supported?: boolean | null;
  streaming_source?: string | null;
  context_window_tokens?: number | null;
  context_window_source?: string | null;
  max_output_tokens?: number | null;
  max_output_source?: string | null;
}

export interface ModelCatalogResponse {
  providers: Record<string, ModelCatalogEntry[]>;
  embedding_models: ModelCatalogEntry[];
  provider_capabilities: Record<string, ProviderCatalogCapability>;
  ollama_discovered: boolean;
  audit_updated_at?: string | null;
  last_live_probe_at?: string | null;
  degraded_providers: string[];
  audit_persisted: boolean;
  audit_warnings: string[];
  timestamp: string;
}

export interface LlmRuntimeUpdateBody {
  provider?: "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  use_multi_agent?: boolean;
  google_api_key?: string;
  clear_google_api_key?: boolean;
  google_model?: string;
  openai_api_key?: string;
  clear_openai_api_key?: boolean;
  openrouter_api_key?: string;
  clear_openrouter_api_key?: boolean;
  zhipu_api_key?: string;
  clear_zhipu_api_key?: boolean;
  ollama_api_key?: string;
  clear_ollama_api_key?: boolean;
  openai_base_url?: string;
  openai_model?: string;
  openai_model_advanced?: string;
  openrouter_base_url?: string;
  openrouter_model?: string;
  openrouter_model_advanced?: string;
  zhipu_base_url?: string;
  zhipu_model?: string;
  zhipu_model_advanced?: string;
  openrouter_model_fallbacks?: string[];
  openrouter_provider_order?: string[];
  openrouter_allowed_providers?: string[];
  openrouter_ignored_providers?: string[];
  openrouter_allow_fallbacks?: boolean | null;
  openrouter_require_parameters?: boolean | null;
  openrouter_data_collection?: "allow" | "deny" | "";
  openrouter_zdr?: boolean | null;
  openrouter_provider_sort?: "price" | "latency" | "throughput" | "";
  ollama_base_url?: string;
  ollama_model?: string;
  ollama_keep_alive?: string;
  enable_llm_failover?: boolean;
  llm_failover_chain?: string[];
  agent_profiles?: Record<string, AgentRuntimeProfileConfig>;
  timeout_profiles?: LlmTimeoutProfilesConfig;
  timeout_provider_overrides?: Record<string, LlmTimeoutProviderOverride>;
  vision_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_describe_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_describe_model?: string;
  vision_ocr_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_ocr_model?: string;
  vision_grounded_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  vision_grounded_model?: string;
  vision_failover_chain?: string[];
  vision_timeout_seconds?: number;
  embedding_provider?: "auto" | "google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama";
  embedding_failover_chain?: string[];
  embedding_model?: string;
}

export type ProviderSelectabilityState = "selectable" | "disabled" | "hidden";
export type ProviderDisabledReasonCode =
  | "busy"
  | "rate_limit"
  | "auth_error"
  | "host_down"
  | "model_missing"
  | "capability_missing"
  | "provider_unavailable"
  | "server_error"
  | "timeout"
  | "verifying";

export interface LlmStatusProvider {
  id: string;
  display_name: string;
  available: boolean;
  is_primary: boolean;
  is_fallback: boolean;
  state: ProviderSelectabilityState;
  reason_code?: ProviderDisabledReasonCode | null;
  reason_label?: string | null;
  selected_model?: string | null;
  strict_pin: boolean;
  verified_at?: string | null;
}

export interface LlmStatusResponse {
  providers: LlmStatusProvider[];
}

export interface LlmRuntimeAuditRefreshBody {
  providers?: Array<"google" | "zhipu" | "openai" | "openrouter" | "nvidia" | "ollama">;
}

// ===== Sprint 170: Living Agent Types =====

/** Wiii's mood types */
export type WiiiMoodType =
  | "curious"
  | "happy"
  | "excited"
  | "focused"
  | "calm"
  | "tired"
  | "concerned"
  | "reflective"
  | "proud"
  | "neutral";

/** Skill development status */
export type SkillStatus =
  | "discovered"
  | "learning"
  | "practicing"
  | "evaluating"
  | "mastered"
  | "archived";

/** Emotional state response */
export interface LivingAgentEmotionalState {
  primary_mood: WiiiMoodType;
  energy_level: number;
  social_battery: number;
  engagement: number;
  mood_label: string;
  behavior_modifiers: Record<string, string>;
  last_updated: string | null;
}

/** Heartbeat info */
export interface LivingAgentHeartbeat {
  is_running: boolean;
  heartbeat_count: number;
  interval_seconds: number;
  active_hours: string;
}

/** Overall living agent status */
export interface LivingAgentStatus {
  enabled: boolean;
  emotional_state: LivingAgentEmotionalState | null;
  heartbeat: LivingAgentHeartbeat | null;
  skills_count: number;
  journal_entries_count: number;
  soul_loaded: boolean;
  soul_name: string;
}

/** Journal entry */
export interface LivingAgentJournalEntry {
  id: string;
  entry_date: string;
  content: string;
  mood_summary: string;
  energy_avg: number;
  notable_events: string[];
  learnings: string[];
  goals_next: string[];
}

/** Tracked skill */
export interface LivingAgentSkill {
  id: string;
  skill_name: string;
  domain: string;
  status: SkillStatus;
  confidence: number;
  usage_count: number;
  success_rate: number;
  discovered_at: string | null;
  last_practiced: string | null;
  mastered_at: string | null;
}

/** Heartbeat trigger result */
export interface HeartbeatTriggerResult {
  success: boolean;
  actions_taken: number;
  duration_ms: number;
  error: string | null;
}

// ===== Sprint 210: Goals & Reflections Types =====

/** Goal status */
export type GoalStatus = "proposed" | "active" | "completed" | "abandoned";

/** A dynamic goal */
export interface LivingAgentGoal {
  id: string;
  title: string;
  description: string;
  status: GoalStatus;
  priority: string;
  progress: number;
  source: string;
  milestones: string[];
  completed_milestones: string[];
  created_at: string | null;
  target_date: string | null;
  completed_at: string | null;
}

/** A reflection entry */
export interface LivingAgentReflection {
  id: string;
  content: string;
  insights: string[];
  goals_next_week: string[];
  patterns_noticed: string[];
  emotion_trend: string;
  reflection_date: string | null;
}

// ===== Sprint 179: Admin Panel Types =====

/** Sprint 179b: Organization summary in dashboard */
export interface AdminOrgSummary {
  id: string;
  name: string;
  display_name: string | null;
  member_count: number;
  document_count?: number;  // Sprint 190: Org knowledge docs
  is_active: boolean;
}

/** Sprint 179b: Organization detail (from /organizations/{id}) */
export interface AdminOrgDetail {
  id: string;
  name: string;
  display_name: string | null;
  description: string | null;
  allowed_domains: string[];
  default_domain: string | null;
  settings: OrgSettings | null;
  document_count?: number;  // Sprint 190: Org knowledge docs
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/** Sprint 179b: Organization member */
export interface AdminOrgMember {
  user_id: string;
  organization_id: string;
  role: string;
  joined_at: string | null;
}

// ===== Sprint 181: Admin Context (Two-Tier Admin) =====

/** GET /users/me/admin-context */
export interface AdminContext {
  is_system_admin: boolean;
  is_org_admin: boolean;
  admin_org_ids: string[];
  enable_org_admin: boolean;
  platform_role?: PlatformRole;
  organization_role?: OrganizationRole | string;
  host_role?: string;
  role_source?: string;
  active_organization_id?: string;
  connector_id?: string;
  identity_version?: string;
  legacy_role?: string;
}

/** GET /admin/dashboard */
export interface AdminDashboard {
  total_users: number;
  active_users: number;
  total_organizations: number;
  total_chat_sessions_24h: number;
  total_llm_tokens_24h: number;
  estimated_cost_24h_usd: number;
  feature_flags_active: number;
  /** Sprint 179b: Organization list in dashboard */
  organizations?: AdminOrgSummary[];
}

/** User row in admin search */
export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: string;
  legacy_role?: string;
  platform_role?: PlatformRole;
  is_active: boolean;
  created_at: string | null;
  organization_count: number;
}

/** GET /admin/users params */
export interface AdminUserSearchParams {
  q?: string;
  email?: string;
  role?: string;
  platform_role?: PlatformRole | string;
  org_id?: string;
  status?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

/** GET /admin/users response */
export interface AdminUserSearchResponse {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

/** Feature flag entry */
export interface AdminFeatureFlag {
  key: string;
  value: boolean;
  source: "config" | "db_override";
  flag_type: string;
  description: string | null;
  owner: string | null;
  expires_at: string | null;
}

/** PATCH /admin/feature-flags/{key} body */
export interface AdminFlagUpdateBody {
  value: boolean;
  flag_type?: string | null;
  description?: string | null;
  organization_id?: string | null;
  expires_at?: string | null;
}

/** Analytics overview response */
export interface AnalyticsOverview {
  period_start: string;
  period_end: string;
  daily_active_users: AnalyticsDataPoint[];
  chat_volume: ChatVolumePoint[];
  error_rate: ErrorRatePoint[];
}

export interface AnalyticsDataPoint {
  date: string;
  count: number;
}

export interface ChatVolumePoint {
  date: string;
  messages: number;
  sessions: number;
}

export interface ErrorRatePoint {
  date: string;
  total: number;
  errors: number;
  rate: number;
}

/** LLM usage analytics */
export interface LlmUsageAnalytics {
  total_tokens: number;
  total_cost_usd: number;
  total_requests: number;
  breakdown: LlmUsageBreakdown[];
  top_models: { model: string; tokens: number; requests: number }[];
  top_users: { user_id: string; tokens: number; requests: number }[];
}

export interface LlmUsageBreakdown {
  group: string;
  tokens: number;
  cost: number;
  requests: number;
}

/** User analytics */
export interface UserAnalytics {
  total_users: number;
  new_users_period: number;
  active_users_period: number;
  user_growth: UserGrowthPoint[];
  role_distribution: Record<string, number>;
  legacy_role_distribution?: Record<string, number>;
  platform_role_distribution?: Record<string, number>;
  organization_role_distribution?: Record<string, number>;
  top_active_users: { user_id: string; sessions: number }[];
}

export interface UserGrowthPoint {
  date: string;
  new_users: number;
}

/** Admin audit log entry */
export interface AdminAuditEntry {
  id: string;
  actor_id: string;
  actor_role: string;
  actor_name: string;
  action: string;
  http_method: string;
  http_path: string;
  http_status: number;
  target_type: string;
  target_id: string;
  target_name: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string;
  request_id: string;
  organization_id: string | null;
  occurred_at: string | null;
}

/** GET /admin/audit-logs response */
export interface AdminAuditLogsResponse {
  entries: AdminAuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

/** Auth event entry */
export interface AdminAuthEvent {
  id: string;
  event_type: string;
  user_id: string;
  provider: string;
  result: string;
  reason: string | null;
  ip_address: string;
  organization_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

/** GET /admin/auth-events response */
export interface AdminAuthEventsResponse {
  entries: AdminAuthEvent[];
  total: number;
  limit: number;
  offset: number;
}

/** GDPR export response */
export interface GdprExportResponse {
  user_id: string;
  exported_at: string;
  data: {
    profile: Record<string, unknown>;
    identities: Record<string, unknown>[];
    memories: Record<string, unknown>[];
    auth_events: Record<string, unknown>[];
    audit_entries: Record<string, unknown>[];
  };
}

// ===== Sprint 190: Org Knowledge Management =====

export type OrgDocumentStatus = "uploading" | "processing" | "ready" | "failed" | "deleted";

export interface OrgDocument {
  document_id: string;
  organization_id: string;
  filename: string;
  file_size_bytes: number | null;
  status: OrgDocumentStatus;
  page_count: number | null;
  chunk_count: number | null;
  error_message: string | null;
  uploaded_by: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface OrgDocumentListResponse {
  documents: OrgDocument[];
  total: number;
}

// ===== Sprint 191: Knowledge Visualization =====

export interface ScatterPoint {
  x: number;
  y: number;
  z?: number | null;
  document_id: string;
  document_name: string;
  content_preview: string;
  content_type?: string | null;
  page_number?: number | null;
}

export interface ScatterDocument {
  id: string;
  name: string;
  color: string;
}

export interface ScatterResponse {
  points: ScatterPoint[];
  documents: ScatterDocument[];
  method: string;
  dimensions: number;
  computation_ms: number;
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  node_type: "document" | "chunk";
  document_id?: string | null;
  page_number?: number | null;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  edge_type: "contains" | "similar_to";
  weight?: number | null;
}

export interface KnowledgeGraphResponse {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  mermaid_code: string;
  computation_ms: number;
}

export interface RagFlowStep {
  name: string;
  duration_ms: number;
  detail?: string | null;
}

export interface RagFlowChunk {
  chunk_id: string;
  document_id: string;
  document_name: string;
  content_preview: string;
  page_number?: number | null;
  similarity: number;
  grade: "relevant" | "partial" | "irrelevant";
  content_type?: string | null;
}

export interface RagFlowResponse {
  query: string;
  steps: RagFlowStep[];
  chunks: RagFlowChunk[];
  computation_ms: number;
}

/** GDPR forget response */
export interface GdprForgetResponse {
  user_id: string;
  status: string;
  profile_anonymized: boolean;
  identities_deleted: number;
  tokens_revoked: number;
  memories_deleted: number;
  audit_logs_preserved: boolean;
}
