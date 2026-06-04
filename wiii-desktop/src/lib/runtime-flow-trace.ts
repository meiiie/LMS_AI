import type {
  ChatResponseMetadata,
  Message,
  RuntimeFlowLedger,
  RuntimeFlowTrace,
} from "@/api/types";

export interface RuntimeFlowTraceRow {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "pending" | "off";
}

export interface RuntimeFlowTraceViewModel {
  present: boolean;
  version: string;
  summary: string;
  tone: "ok" | "warn" | "pending" | "off";
  rows: RuntimeFlowTraceRow[];
  warnings: string[];
}

export interface RuntimeFlowLedgerViewModel {
  present: boolean;
  version: string;
  summary: string;
  tone: "ok" | "warn" | "pending" | "off";
  rows: RuntimeFlowTraceRow[];
  warnings: string[];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function looksSensitiveTraceText(value: string): boolean {
  const textValue = value.trim();
  const lower = textValue.toLowerCase();
  if (!textValue) return false;
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
  if (/^(sk-|ak_|tp-|wcn_|ca_)/i.test(textValue)) return true;
  if (/^eyJ[\w-]*\.[\w-]*\.[\w-]*$/.test(textValue)) return true;
  return false;
}

function text(value: unknown, fallback = "Chưa có"): string {
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : fallback;
  const raw = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!raw) return fallback;
  if (looksSensitiveTraceText(raw)) return "[redacted]";
  return raw.length > 96 ? `${raw.slice(0, 95)}...` : raw;
}

function boolText(value: unknown): string {
  return typeof value === "boolean" ? (value ? "Có" : "Không") : "Chưa rõ";
}

function listText(value: unknown): string {
  if (!Array.isArray(value)) return "Không";
  const items = value
    .map((item) => text(item, ""))
    .filter(Boolean)
    .slice(0, 5);
  if (items.length === 0) return "Không";
  const suffix = value.length > items.length ? ` +${value.length - items.length}` : "";
  return `${items.join(", ")}${suffix}`;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function countFromMap(map: Record<string, unknown>, key: string): number {
  const value = map[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function boolFlag(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "unknown";
}

function finiteNumberText(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : null;
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function contextProvenanceRows(
  context: Record<string, unknown>,
): RuntimeFlowTraceRow[] {
  const provenance = asRecord(context.context_provenance);
  if (Object.keys(provenance).length === 0) return [];

  const documents = asRecord(provenance.documents);
  const memory = asRecord(provenance.memory);
  const privacy = asRecord(provenance.privacy);
  const provenanceWarnings = [
    ...stringList(provenance.warnings),
    ...stringList(memory.warning_codes),
  ].filter((item, index, items) => items.indexOf(item) === index);
  const sourceKinds = stringList(documents.source_ref_kinds);
  const memoryTypes = stringList(memory.semantic_memory_types);
  const factTypes = stringList(memory.fact_type_names);
  const insightCategories = stringList(memory.insight_category_names);
  const episodicEventTypes = stringList(memory.episodic_event_types);
  const memorySignals = [...memoryTypes, ...factTypes, ...insightCategories]
    .filter((item, index, items) => items.indexOf(item) === index)
    .slice(0, 6);
  const episodicPresent =
    memory.episodic_retrieval_present === true ||
    typeof memory.episodic_match_count === "number" ||
    episodicEventTypes.length > 0;
  const episodicMinScore = finiteNumberText(memory.episodic_min_score);
  const episodicMaxScore = finiteNumberText(memory.episodic_max_score);
  const episodicScore =
    episodicMinScore && episodicMaxScore
      ? `${episodicMinScore}-${episodicMaxScore}`
      : episodicMaxScore || episodicMinScore || "unknown";
  const rawContentIncluded = privacy.raw_content_included;
  const privacyLabel =
    rawContentIncluded === false
      ? text(privacy.identifier_strategy, "hash/count")
      : rawContentIncluded === true
        ? "raw_content_flagged"
        : "privacy_unknown";
  const rows: RuntimeFlowTraceRow[] = [
    {
      label: "Provenance",
      value: `docs ${sourceKinds.length > 0 ? listText(sourceKinds) : "Không"}; memory ${memorySignals.length > 0 ? listText(memorySignals) : "Không"}; ${privacyLabel}`,
      tone: rawContentIncluded === true ? "warn" : rawContentIncluded === false ? "ok" : "pending",
    },
  ];

  if (episodicPresent) {
    const episodicParts = [
      text(memory.episodic_retrieval_status, "unknown"),
      `matches ${text(memory.episodic_match_count, "0")}`,
      `events ${episodicEventTypes.length > 0 ? listText(episodicEventTypes) : "Không"}`,
      `score ${episodicScore}`,
      `org_scoped ${boolFlag(memory.episodic_org_scoped)}`,
      `current_session_excluded ${boolFlag(memory.episodic_current_session_excluded)}`,
      `episodic_raw_content ${boolFlag(memory.episodic_raw_content_included)}`,
    ];
    rows.push({
      label: "Episodic recall",
      value: episodicParts.join("; "),
      tone: memory.episodic_raw_content_included === true ? "warn" : "ok",
    });
  }

  rows.push({
    label: "Context warnings",
    value: provenanceWarnings.length > 0 ? listText(provenanceWarnings) : "Không",
    tone: provenanceWarnings.length > 0 ? "warn" : "off",
  });

  return rows;
}

function subagentBoundaryRows(
  subagents: Record<string, unknown>,
): RuntimeFlowTraceRow[] {
  const reports = Array.isArray(subagents.reports)
    ? subagents.reports.map(asRecord)
    : [];
  const reportCount = finiteNumber(subagents.report_count) || reports.length;
  if (reportCount === 0 && reports.length === 0) return [];

  const agents = reports
    .map((report) => text(report.agent_name, "unknown"))
    .filter(Boolean)
    .slice(0, 5);
  const projectedKeys = reports.reduce(
    (total, report) => total + finiteNumber(report.state_projected_key_count),
    0,
  );
  const droppedKeys = reports.reduce(
    (total, report) => total + finiteNumber(report.state_dropped_key_count),
    0,
  );
  const sources = reports.reduce(
    (total, report) => total + finiteNumber(report.source_count),
    0,
  );
  const tools = reports.reduce(
    (total, report) => total + finiteNumber(report.tool_count),
    0,
  );
  const thinkingDropped = reports.filter(
    (report) => report.thinking_dropped === true,
  ).length;
  const warnings = stringList(subagents.warning_codes);
  const rawContentIncluded = subagents.raw_content_included === true;

  return [
    {
      label: "Subagent boundary",
      value: `reports ${reportCount}; agents ${agents.length > 0 ? agents.join(", ") : "KhÃ´ng"}; projected ${projectedKeys}; dropped ${droppedKeys}; sources ${sources}; tools ${tools}; thinking dropped ${thinkingDropped}`,
      tone: rawContentIncluded ? "warn" : "ok",
    },
    {
      label: "Subagent warnings",
      value: warnings.length > 0 ? listText(warnings) : "KhÃ´ng",
      tone: warnings.length > 0 || rawContentIncluded ? "warn" : "off",
    },
  ];
}

function hasRuntimeFlowTrace(value: unknown): value is RuntimeFlowTrace {
  const record = asRecord(value);
  return record.version === "wiii.runtime_flow_trace.v1" || Boolean(record.turn_path_decision);
}

function hasRuntimeFlowLedger(value: unknown): value is RuntimeFlowLedger {
  const record = asRecord(value);
  return record.schema_version === "wiii.runtime_flow_ledger.v1" || Boolean(record.stream);
}

function runtimeFlowTraceFromMetadata(
  metadata: ChatResponseMetadata | Record<string, unknown> | null | undefined,
): RuntimeFlowTrace | null {
  if (!metadata) return null;
  const trace = (metadata as Record<string, unknown>).runtime_flow_trace;
  return hasRuntimeFlowTrace(trace) ? trace : null;
}

function runtimeFlowLedgerFromMetadata(
  metadata: ChatResponseMetadata | Record<string, unknown> | null | undefined,
): RuntimeFlowLedger | null {
  if (!metadata) return null;
  const ledger = (metadata as Record<string, unknown>).runtime_flow_ledger;
  return hasRuntimeFlowLedger(ledger) ? ledger : null;
}

export function latestRuntimeFlowTrace(
  messages: Message[] | undefined,
  pendingMetadata?: ChatResponseMetadata | null,
): RuntimeFlowTrace | null {
  const pendingTrace = runtimeFlowTraceFromMetadata(pendingMetadata);
  if (pendingTrace) return pendingTrace;

  const items = messages ?? [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index];
    if (message.role !== "assistant") continue;
    const trace = runtimeFlowTraceFromMetadata(message.metadata);
    if (trace) return trace;
  }
  return null;
}

export function latestRuntimeFlowLedger(
  messages: Message[] | undefined,
  pendingMetadata?: ChatResponseMetadata | null,
): RuntimeFlowLedger | null {
  const pendingLedger = runtimeFlowLedgerFromMetadata(pendingMetadata);
  if (pendingLedger) return pendingLedger;

  const items = messages ?? [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index];
    if (message.role !== "assistant") continue;
    const ledger = runtimeFlowLedgerFromMetadata(message.metadata);
    if (ledger) return ledger;
  }
  return null;
}

function finalAnswerWarning(
  externalAction: Record<string, unknown>,
  finalAnswer: Record<string, unknown>,
): string | null {
  if (externalAction.observed_action_result !== true) return null;
  const source = text(finalAnswer.source, "");
  if (!source || source === "missing_explicit_final_answer_source") {
    return "Có action result nhưng chưa có nguồn final answer rõ ràng.";
  }
  return null;
}

export function buildRuntimeFlowTraceViewModel(
  trace: RuntimeFlowTrace | null,
): RuntimeFlowTraceViewModel {
  if (!trace) {
    return {
      present: false,
      version: "",
      summary: "Chưa có runtime_flow_trace",
      tone: "pending",
      rows: [
        {
          label: "Nguồn",
          value: "Chờ metadata từ lượt chat mới",
          tone: "pending",
        },
      ],
      warnings: [],
    };
  }

  const turnPath = asRecord(trace.turn_path_decision);
  const policy = asRecord(trace.tool_policy_session);
  const plan = asRecord(trace.external_app_action_plan);
  const lane = asRecord(trace.external_app_integration_lane);
  const externalAction = asRecord(trace.external_action_trace);
  const gateway = asRecord(externalAction.gateway);
  const worker = asRecord(externalAction.integration_worker);
  const workerClassification = asRecord(worker.result_classification);
  const finalAnswer = asRecord(trace.final_answer);

  const path = text(turnPath.path, "Chưa phân loại");
  const executor = text(lane.executor, "Không");
  const provider = text(lane.provider_slug || plan.provider_slug || externalAction.provider_slug, "Không");
  const action = text(lane.action_slug || plan.action_slug || externalAction.action_slug, "Không");
  const actionStatus = text(externalAction.last_status, "Chưa chạy");
  const actionSuccess = externalAction.last_success;
  const workerOutcome = text(
    externalAction.worker_outcome || workerClassification.outcome,
    "Chưa chạy",
  );
  const workerFailedStage = text(
    externalAction.worker_failed_stage || workerClassification.failed_stage,
    "Không",
  );
  const workerReason = text(
    externalAction.worker_reason || workerClassification.reason,
    "không rõ",
  );
  const finalSource = text(finalAnswer.source, "Chưa có");
  const warnings = [
    finalAnswerWarning(externalAction, finalAnswer),
    gateway.status === "blocked" ? `Gateway blocked: ${text(gateway.reason, "không rõ")}` : null,
  ].filter((item): item is string => Boolean(item));

  const tone: RuntimeFlowTraceViewModel["tone"] =
    warnings.length > 0
      ? "warn"
      : actionStatus === "action_failed"
        ? "warn"
        : trace.final_answer
          ? "ok"
          : "pending";

  return {
    present: true,
    version: text(trace.version, "runtime_flow_trace"),
    summary: `${path} · ${executor}`,
    tone,
    warnings,
    rows: [
      { label: "Path", value: path, tone: "ok" },
      { label: "Lý do path", value: text(turnPath.reason), tone: "off" },
      {
        label: "Bind tool",
        value: `${boolText(policy.bind_tools)} · force ${boolText(policy.force_tools)}`,
        tone: policy.bind_tools ? "ok" : "off",
      },
      {
        label: "Tool hiển thị",
        value: listText(policy.visible_tool_names),
        tone: Array.isArray(policy.visible_tool_names) && policy.visible_tool_names.length > 0 ? "ok" : "off",
      },
      {
        label: "Provider/action",
        value: `${provider} · ${action}`,
        tone: provider !== "Không" ? "ok" : "off",
      },
      {
        label: "Executor",
        value: `${executor} · ${text(lane.status, "not_applicable")}`,
        tone: lane.status === "ready" ? "ok" : lane.status === "blocked" ? "warn" : "off",
      },
      {
        label: "Gateway",
        value: `${text(gateway.status, "Chưa có")} · ${text(gateway.reason, "không rõ")}`,
        tone: gateway.status === "allowed" ? "ok" : gateway.status === "blocked" ? "warn" : "off",
      },
      {
        label: "Worker",
        value: `${workerOutcome} · ${workerFailedStage} · ${workerReason}`,
        tone:
          workerOutcome === "completed"
            ? "ok"
            : workerOutcome === "Chưa chạy"
              ? "off"
              : workerOutcome.endsWith("_required")
                ? "pending"
                : "warn",
      },
      {
        label: "Action result",
        value: `${actionStatus} · success ${boolText(actionSuccess)}`,
        tone: actionSuccess === true ? "ok" : actionSuccess === false ? "warn" : "pending",
      },
      {
        label: "Final answer",
        value: `${finalSource} · ${text(finalAnswer.status, "Chưa rõ")}`,
        tone: finalSource === "missing_explicit_final_answer_source" ? "warn" : finalAnswer.source ? "ok" : "pending",
      },
    ],
  };
}

function ledgerContractWarnings(ledger: RuntimeFlowLedger): string[] {
  const route = asRecord(ledger.route);
  const turnPath = asRecord(route.turn_path_decision);
  const lane = text(route.lane || turnPath.path, "");
  const tools = asRecord(ledger.tools);
  const stream = asRecord(ledger.stream);
  const eventCounts = asRecord(stream.event_counts);
  const observedTools = stringList(tools.observed);
  const warnings: string[] = [];

  if (stream.done_seen !== true) {
    warnings.push("Runtime ledger chưa ghi nhận done_seen.");
  }
  if (
    observedTools.includes("visual_runtime") &&
    (countFromMap(eventCounts, "visual_open") < 1 ||
      countFromMap(eventCounts, "visual_commit") < 1)
  ) {
    warnings.push("Visual runtime thiếu visual_open hoặc visual_commit trong ledger.");
  }
  if (
    observedTools.includes("code_studio") &&
    (countFromMap(eventCounts, "code_open") < 1 ||
      countFromMap(eventCounts, "code_complete") < 1)
  ) {
    warnings.push("Code Studio thiếu code_open hoặc code_complete trong ledger.");
  }
  if (lane === "casual_chat" || lane === "direct_prose") {
    const forbiddenEvents = [
      "host_action",
      "host_action_result",
      "pointy_action",
      "visual_open",
      "visual_commit",
      "code_open",
      "code_complete",
    ];
    const leakedEvents = forbiddenEvents.filter(
      (eventName) => countFromMap(eventCounts, eventName) > 0,
    );
    if (leakedEvents.length > 0) {
      warnings.push(`No-action turn có event không được phép: ${leakedEvents.join(", ")}.`);
    }
  }

  return warnings;
}

export function buildRuntimeFlowLedgerViewModel(
  ledger: RuntimeFlowLedger | null,
): RuntimeFlowLedgerViewModel {
  if (!ledger) {
    return {
      present: false,
      version: "",
      summary: "Chưa có runtime_flow_ledger",
      tone: "pending",
      rows: [
        {
          label: "Nguồn",
          value: "Chờ done metadata từ lượt chat mới",
          tone: "pending",
        },
      ],
      warnings: [],
    };
  }

  const request = asRecord(ledger.request);
  const context = asRecord(ledger.context);
  const route = asRecord(ledger.route);
  const tools = asRecord(ledger.tools);
  const subagents = asRecord((ledger as Record<string, unknown>).subagents);
  const stream = asRecord(ledger.stream);
  const hostActions = asRecord(ledger.host_actions);
  const runtime = asRecord(ledger.runtime);
  const scheduledTasks = asRecord(ledger.scheduled_tasks);
  const scheduledTaskDelivery = asRecord(scheduledTasks.delivery);
  const finalization = asRecord(ledger.finalization);
  const policySession = asRecord(tools.policy_session);
  const eventCounts = asRecord(stream.event_counts);
  const turnPath = asRecord(route.turn_path_decision);
  const lane = text(route.lane || turnPath.path, "Chưa phân loại");
  const routeReason = text(turnPath.reason || route.reason, "khong ro");
  const routeAgent = text(route.final_agent || route.selected_agent, "Khong");
  const observed = stringList(tools.observed);
  const suppressed = stringList(tools.suppressed);
  const visibleTools = stringList(policySession.visible_tool_names);
  const policyDenials = Array.isArray(tools.policy_denials) ? tools.policy_denials : [];
  const warnings = ledgerContractWarnings(ledger);
  const doneSeen = stream.done_seen === true;
  const visualEvents = countFromMap(eventCounts, "visual_open") + countFromMap(eventCounts, "visual_commit");
  const codeEvents = countFromMap(eventCounts, "code_open") + countFromMap(eventCounts, "code_complete");
  const actionEvents = countFromMap(eventCounts, "host_action") + countFromMap(eventCounts, "pointy_action");
  const toolCallEvents = countFromMap(eventCounts, "tool_call");
  const toolResultEvents = countFromMap(eventCounts, "tool_result");
  const toolErrorEvents = countFromMap(eventCounts, "tool_error") + countFromMap(eventCounts, "error");
  const provenanceRows = contextProvenanceRows(context);
  const subagentRows = subagentBoundaryRows(subagents);
  const hasScheduledTaskEvidence = Object.keys(scheduledTasks).length > 0;
  const droppedContextMessages =
    typeof context.context_budget_messages_dropped === "number" &&
    Number.isFinite(context.context_budget_messages_dropped)
      ? context.context_budget_messages_dropped
      : 0;
  const contextBudgetUtilization =
    typeof context.context_budget_utilization === "number" &&
    Number.isFinite(context.context_budget_utilization)
      ? context.context_budget_utilization
      : null;

  return {
    present: true,
    version: text(ledger.schema_version, "runtime_flow_ledger"),
    summary: `${lane} · ${doneSeen ? "done" : "chưa done"}`,
    tone: warnings.length > 0 ? "warn" : doneSeen ? "ok" : "pending",
    warnings,
    rows: [
      { label: "Lane", value: lane, tone: doneSeen ? "ok" : "pending" },
      {
        label: "Route decision",
        value: `${routeReason}; bind ${boolText(turnPath.bind_tools)}; force ${boolText(turnPath.force_tools)}; agent ${routeAgent}`,
        tone: doneSeen ? "ok" : "pending",
      },
      {
        label: "Host",
        value: `${text(request.host_surface, "unknown")} · ${listText(request.host_capabilities)}`,
        tone: "off",
      },
      {
        label: "Provider/model",
        value: `${text(runtime.provider || runtime.requested_provider, "Khong")} · ${text(runtime.model || runtime.requested_model, "Khong")} · authoritative ${boolText(runtime.runtime_authoritative)}`,
        tone: runtime.provider || runtime.model ? "ok" : "off",
      },
      {
        label: "Tool loop",
        value: `visible ${visibleTools.length > 0 ? listText(visibleTools) : "Khong"}; calls ${toolCallEvents}; results ${toolResultEvents}; denials ${policyDenials.length}; host result ${hostActions.result_received === true ? boolText(hostActions.result_success) : "Khong"}; errors ${toolErrorEvents || text(finalization.error_type, "0")}`,
        tone: toolErrorEvents > 0 || finalization.error_type ? "warn" : toolCallEvents > 0 || toolResultEvents > 0 ? "ok" : "off",
      },
      ...(hasScheduledTaskEvidence
        ? [
            {
              label: "Scheduled task",
              value: `created ${boolText(scheduledTasks.created)}; tool ${text(scheduledTasks.creation_tool || scheduledTasks.tool, "Khong")}; due ${boolText(scheduledTasks.due_seen)}; delivery ${text(scheduledTaskDelivery.channel, "Khong")}/${text(scheduledTaskDelivery.status, "Khong")}`,
              tone:
                scheduledTaskDelivery.status === "failed"
                  ? "warn"
                  : scheduledTasks.created === true
                    ? "ok"
                    : "pending",
            } satisfies RuntimeFlowTraceRow,
          ]
        : []),
      {
        label: "Observed",
        value: observed.length > 0 ? listText(observed) : "Không",
        tone: observed.length > 0 ? "ok" : "off",
      },
      {
        label: "Suppressed",
        value: suppressed.length > 0 ? listText(suppressed) : "Không",
        tone: suppressed.length > 0 ? "ok" : "off",
      },
      {
        label: "Stream",
        value: `answer ${text(eventCounts.answer, "0")} · visual ${visualEvents} · code ${codeEvents} · action ${actionEvents}`,
        tone: warnings.length > 0 ? "warn" : "ok",
      },
      {
        label: "Context",
        value: `docs ${text(context.uploaded_document_count, "0")} · sources ${text(context.source_ref_count, "0")} · memory ${text(context.memory_context_count, "0")}`,
        tone: "off",
      },
      {
        label: "History context",
        value: `items ${text(context.history_context_count, "0")}; ${text(context.history_retrieval_status, "unknown")}/${text(context.history_source, "unknown")}`,
        tone:
          context.history_retrieval_status === "fallback"
            ? "warn"
            : context.history_retrieval_status
              ? "ok"
              : "off",
      },
      {
        label: "Context budget",
        value: `utilization ${text(context.context_budget_utilization, "0")}; dropped ${text(context.context_budget_messages_dropped, "0")}; ${text(context.context_budget_status, "unknown")}`,
        tone:
          droppedContextMessages > 0 ||
          (typeof contextBudgetUtilization === "number" &&
            contextBudgetUtilization >= 0.75)
            ? "warn"
            : context.context_budget_status === "ready"
              ? "ok"
              : "off",
      },
      ...subagentRows,
      ...provenanceRows,
      {
        label: "Preview/apply",
        value: `preview ${boolText(hostActions.preview_required)}; approval ${boolText(hostActions.approval_token_present)}; apply ${boolText(hostActions.apply_attempted)}`,
        tone: hostActions.apply_attempted === true ? "warn" : "off",
      },
      {
        label: "Done",
        value: boolText(stream.done_seen),
        tone: doneSeen ? "ok" : "pending",
      },
    ],
  };
}
