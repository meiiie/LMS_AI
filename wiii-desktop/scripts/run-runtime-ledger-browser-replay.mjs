import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { writeJsonFile } from "./runtime-evidence-output.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(desktopDir, "..");
const backendDir = path.join(repoRoot, "maritime-ai-service");
const acceptanceScript = path.join(backendDir, "scripts", "wiii_runtime_flow_acceptance.py");
const defaultBrowserReplayScenarios = [
  "uploaded_document_lms_preview_source_replay",
  "facebook_connection_status_control_plane",
  "facebook_action_blocks_without_agent_ready_provider",
  "external_action_missing_provider_blocks_before_tools",
  "visual_inline_figure_stream_replay",
  "code_studio_app_stream_replay",
].join(",");
const POST_TURN_LIFECYCLE_SCHEMA = "wiii.post_turn_lifecycle.v1";
const postTurnLifecycleForbiddenKeys = new Set([
  "domain_id",
  "message",
  "organization_id",
  "prompt",
  "request_id",
  "response",
  "response_text",
  "session_id",
  "text",
  "user_id",
]);
const evidencePath = path.resolve(
  process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON ||
    path.join(
      repoRoot,
      "test-results",
      "runtime-flow-browser-replay",
      "runtime-flow-acceptance-evidence.json",
    ),
);
const summaryPath = path.resolve(
  process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON ||
    path.join(
      repoRoot,
      "test-results",
      "runtime-flow-browser-replay",
      "runtime-flow-browser-replay-summary.json",
    ),
);
const summaryArchiveDir = path.resolve(
  process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_DIR ||
    path.join(repoRoot, "test-results", "runtime-flow-browser-replay", "archive"),
);
const summaryArchiveLimit = parseArchiveLimit(
  process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_LIMIT,
);
const summaryArchivePrefix = "runtime-flow-browser-replay-summary-";
const summaryArchiveIndexName = "runtime-flow-browser-replay-summary-index.json";

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function bool(value) {
  return typeof value === "boolean" ? value : null;
}

function numberOrNull(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringOrEmpty(value) {
  return typeof value === "string" ? value : "";
}

function incrementCount(map, key) {
  if (typeof key !== "string" || key.length === 0) {
    return;
  }
  map[key] = (map[key] || 0) + 1;
}

function hashText(value, length = 16) {
  return createHash("sha256").update(String(value || ""), "utf8").digest("hex").slice(0, length);
}

function hashBuffer(value) {
  return createHash("sha256").update(value).digest("hex");
}

function parseArchiveLimit(value) {
  if (value === undefined || value === "") {
    return 25;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    console.error(
      "WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_LIMIT must be a non-negative integer.",
    );
    process.exit(1);
  }
  return parsed;
}

function archiveTimestamp(value) {
  return String(value || new Date().toISOString())
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z")
    .replace(/[^0-9TZ]/g, "");
}

function buildSummaryArchiveEntry(fileName, summary) {
  const evidence = asRecord(summary.evidence);
  const target = asRecord(summary.target);
  const doctor = asRecord(summary.doctor);
  const checks = asRecord(summary.checks);
  const browserReplay = asRecord(summary.browser_replay);
  const capability = asRecord(summary.wiii_connect_capability);
  return {
    file_name: fileName,
    generated_at: summary.generated_at || "",
    evidence_sha256: evidence.sha256 || "",
    evidence_byte_count: numberOrNull(evidence.byte_count),
    browser_replay_case_count: numberOrNull(evidence.case_count),
    target_env: target.target_env || "",
    commit_sha: target.commit_sha || "",
    doctor_status: doctor.status || "",
    ready_paths: numberOrNull(doctor.ready_paths),
    blocked_paths: numberOrNull(doctor.blocked_paths),
    failed_check_count: numberOrNull(checks.failed),
    sync_parity_passed: numberOrNull(checks.sync_parity_passed),
    route_path_counts: asRecord(browserReplay.route_path_counts),
    route_reason_hash_present_count: numberOrNull(
      browserReplay.route_reason_hash_present_count,
    ),
    visual_lifecycle_case_count: numberOrNull(
      browserReplay.visual_lifecycle_case_count,
    ),
    code_studio_lifecycle_case_count: numberOrNull(
      browserReplay.code_studio_lifecycle_case_count,
    ),
    finalization_saved_case_count: numberOrNull(
      browserReplay.finalization_saved_case_count,
    ),
    finalization_error_case_count: numberOrNull(
      browserReplay.finalization_error_case_count,
    ),
    post_turn_lifecycle_case_count: numberOrNull(
      browserReplay.post_turn_lifecycle_case_count,
    ),
    post_turn_lifecycle_case_hash_count: asArray(
      browserReplay.post_turn_lifecycle_case_id_hashes,
    ).length,
    validated_browser_replay_case_count: asArray(
      browserReplay.validated_case_id_hashes,
    ).length,
    finalized_browser_replay_case_count: asArray(
      browserReplay.finalized_case_id_hashes,
    ).length,
    connected_provider_count: numberOrNull(capability.connected_provider_count),
    connected_scope_count: numberOrNull(capability.connected_scope_count),
    path_readiness_count: numberOrNull(capability.path_readiness_count),
    raw_prompt_answer_or_sse_payload_absent: bool(
      browserReplay.raw_prompt_answer_or_sse_payload_absent,
    ),
    exact_evidence_file_replayed: bool(browserReplay.exact_evidence_file_replayed),
    all_cases_validated_by_playwright: bool(
      browserReplay.all_cases_validated_by_playwright,
    ),
    all_cases_finalized: bool(browserReplay.all_cases_finalized),
    all_cases_have_post_turn_lifecycle_hash: bool(
      browserReplay.all_cases_have_post_turn_lifecycle_hash,
    ),
  };
}

function routeDecisionSummary(replayCase, ledger, trace) {
  const route = asRecord(ledger.route);
  const traceTurnPath = asRecord(trace.turn_path_decision);
  const ledgerTurnPath = asRecord(route.turn_path_decision);
  const policy = asRecord(trace.tool_policy_session);
  const path =
    stringOrEmpty(replayCase.path) ||
    stringOrEmpty(traceTurnPath.path) ||
    stringOrEmpty(ledgerTurnPath.path) ||
    stringOrEmpty(route.lane) ||
    "";
  const reason =
    stringOrEmpty(traceTurnPath.reason) ||
    stringOrEmpty(ledgerTurnPath.reason) ||
    stringOrEmpty(route.reason) ||
    "";
  return {
    path,
    reason,
    bind_tools:
      bool(traceTurnPath.bind_tools) ??
      bool(policy.bind_tools) ??
      bool(ledgerTurnPath.bind_tools),
    force_tools:
      bool(traceTurnPath.force_tools) ??
      bool(policy.force_tools) ??
      bool(ledgerTurnPath.force_tools),
    selected_agent: stringOrEmpty(route.selected_agent),
    final_agent: stringOrEmpty(route.final_agent),
  };
}

function hasForbiddenPostTurnLifecycleScopeKey(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.keys(value).some((key) =>
    postTurnLifecycleForbiddenKeys.has(String(key || "").trim().toLowerCase()),
  );
}

function readArchivedSummary(fileName) {
  try {
    const filePath = path.join(summaryArchiveDir, fileName);
    const payload = asRecord(JSON.parse(readFileSync(filePath, "utf8")));
    if (payload.schema !== "wiii.runtime_flow_browser_replay_summary.v1") {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

function writeSummaryArchive(summary) {
  if (summaryArchiveLimit === 0) {
    console.log("[INFO] Browser replay summary archive disabled by retention limit 0.");
    return;
  }

  mkdirSync(summaryArchiveDir, { recursive: true });
  const archiveFileName = `${summaryArchivePrefix}${archiveTimestamp(summary.generated_at)}-${hashText(
    asRecord(summary.evidence).sha256,
    12,
  )}.json`;
  const archivePath = path.join(summaryArchiveDir, archiveFileName);
  writeJsonFile(archivePath, summary);

  const archiveFileNames = readdirSync(summaryArchiveDir)
    .filter((fileName) => (
      fileName.startsWith(summaryArchivePrefix) &&
      fileName.endsWith(".json") &&
      fileName !== summaryArchiveIndexName
    ))
    .sort()
    .reverse();
  const retained = archiveFileNames.slice(0, summaryArchiveLimit);
  const pruned = archiveFileNames.slice(summaryArchiveLimit);
  for (const fileName of pruned) {
    rmSync(path.join(summaryArchiveDir, fileName), { force: true });
  }

  const entries = retained
    .map((fileName) => {
      const archivedSummary = readArchivedSummary(fileName);
      return archivedSummary ? buildSummaryArchiveEntry(fileName, archivedSummary) : null;
    })
    .filter(Boolean);
  const index = {
    schema: "wiii.runtime_flow_browser_replay_summary_archive.v1",
    generated_at: new Date().toISOString(),
    retention_limit: summaryArchiveLimit,
    retained_count: entries.length,
    pruned_count: pruned.length,
    raw_prompt_answer_or_sse_payload_absent: true,
    entries,
  };
  writeJsonFile(path.join(summaryArchiveDir, summaryArchiveIndexName), index);
  console.log(
    `[INFO] Archived hash/count browser replay summary JSON: ${archivePath}`,
  );
  console.log(
    `[INFO] Updated browser replay summary archive index: ${path.join(
      summaryArchiveDir,
      summaryArchiveIndexName,
    )}`,
  );
}

function writeSummary() {
  const rawEvidence = readFileSync(evidencePath);
  const evidenceText = rawEvidence.toString("utf8").replace(/^\uFEFF/, "");
  const evidence = asRecord(JSON.parse(evidenceText));
  const browserReplay = asRecord(evidence.browser_replay);
  const target = asRecord(evidence.target);
  const doctor = asRecord(evidence.doctor);
  const doctorSummary = asRecord(doctor.summary);
  const capability = asRecord(evidence.wiii_connect_capability);
  const cases = asArray(browserReplay.cases);
  const checks = asArray(evidence.checks);
  const syncParityPassed = checks.filter((check) => {
    const checkRecord = asRecord(check);
    return (
      checkRecord.status === "passed" &&
      stringOrEmpty(checkRecord.detail).includes("sync_parity=ok")
    );
  }).length;
  const caseSummaries = cases.map((rawCase) => {
    const replayCase = asRecord(rawCase);
    const metadata = asRecord(replayCase.assistant_metadata);
    const ledger = asRecord(metadata.runtime_flow_ledger);
    const trace = asRecord(metadata.runtime_flow_trace);
    const context = asRecord(ledger.context);
    const request = asRecord(ledger.request);
    const hostActions = asRecord(ledger.host_actions);
    const tools = asRecord(ledger.tools);
    const stream = asRecord(ledger.stream);
    const eventCounts = asRecord(stream.event_counts);
    const subagents = asRecord(ledger.subagents);
    const subagentReports = asArray(subagents.reports).map(asRecord);
    const finalization = asRecord(ledger.finalization);
    const finalizationStatus = stringOrEmpty(finalization.status);
    const finalizationErrorType = stringOrEmpty(finalization.error_type);
    const postTurnLifecycle = asRecord(finalization.post_turn_lifecycle);
    const postTurnLifecyclePrivacy = asRecord(postTurnLifecycle.privacy);
    const routeDecision = routeDecisionSummary(replayCase, ledger, trace);
    const routeReasonHash =
      typeof routeDecision.reason === "string" && routeDecision.reason.length > 0
        ? hashText(routeDecision.reason)
        : "";
    const subagentStateDroppedKeyCount = subagentReports.reduce(
      (total, report) =>
        total + (numberOrNull(report.state_dropped_key_count) || 0),
      0,
    );
    const subagentThinkingDroppedCount = subagentReports.filter(
      (report) => report.thinking_dropped === true,
    ).length;
    const eventNames = asArray(replayCase.event_names).filter(
      (item) => typeof item === "string",
    );
    const observedTools = asArray(tools.observed).filter(
      (item) => typeof item === "string",
    );
    const visualOpenCount = numberOrNull(eventCounts.visual_open) || 0;
    const visualCommitCount = numberOrNull(eventCounts.visual_commit) || 0;
    const codeOpenCount = numberOrNull(eventCounts.code_open) || 0;
    const codeCompleteCount = numberOrNull(eventCounts.code_complete) || 0;
    return {
      scenario_id: replayCase.scenario_id || "",
      case_id_hash: hashText(replayCase.scenario_id || ""),
      case_id_hash_present: stringOrEmpty(replayCase.scenario_id).length > 0,
      path: routeDecision.path,
      path_hash_present: routeDecision.path.length > 0,
      route_reason_hash_present: routeReasonHash.length > 0,
      route_reason_hash: routeReasonHash,
      route_bind_tools: routeDecision.bind_tools,
      route_force_tools: routeDecision.force_tools,
      route_selected_agent: routeDecision.selected_agent,
      route_final_agent: routeDecision.final_agent,
      prompt_hash_present:
        typeof replayCase.prompt_hash === "string" &&
        replayCase.prompt_hash.length > 0,
      event_name_count: eventNames.length,
      event_names_hash: hashText(eventNames.join("|")),
      event_names_hash_present: eventNames.length > 0,
      raw_prompt_included: false,
      raw_answer_included: false,
      raw_sse_payload_included: false,
      assistant_content_included: false,
      observed_visual_runtime: observedTools.includes("visual_runtime"),
      observed_code_studio: observedTools.includes("code_studio"),
      visual_event_count: visualOpenCount + visualCommitCount,
      code_studio_event_count: codeOpenCount + codeCompleteCount,
      visual_lifecycle_complete: visualOpenCount > 0 && visualCommitCount > 0,
      code_studio_lifecycle_complete:
        codeOpenCount > 0 && codeCompleteCount > 0,
      assistant_metadata_keys: Object.keys(metadata).sort(),
      ledger_schema_version: ledger.schema_version || "",
      trace_version: trace.version || "",
      host_surface: request.host_surface || "",
      host_capability_count: asArray(request.host_capabilities).length,
      uploaded_document_count: numberOrNull(context.uploaded_document_count),
      source_ref_count: numberOrNull(context.source_ref_count),
      memory_context_count: numberOrNull(context.memory_context_count),
      history_context_count: numberOrNull(context.history_context_count),
      history_retrieval_status:
        typeof context.history_retrieval_status === "string"
          ? context.history_retrieval_status
          : "",
      history_source:
        typeof context.history_source === "string" ? context.history_source : "",
      context_budget_utilization: numberOrNull(context.context_budget_utilization),
      context_budget_messages_dropped: numberOrNull(
        context.context_budget_messages_dropped,
      ),
      context_budget_status:
        typeof context.context_budget_status === "string"
          ? context.context_budget_status
          : "",
      subagent_report_count: numberOrNull(subagents.report_count),
      subagent_warning_count: asArray(subagents.warning_codes).length,
      subagent_state_dropped_key_count: subagentStateDroppedKeyCount,
      subagent_thinking_dropped_count: subagentThinkingDroppedCount,
      subagent_raw_content_included: bool(subagents.raw_content_included),
      finalization_status: finalizationStatus,
      finalization_saved: finalizationStatus === "saved",
      finalization_error_type_present: finalizationErrorType.length > 0,
      save_response_immediately: bool(finalization.save_response_immediately),
      post_turn_lifecycle_schema_version: stringOrEmpty(
        postTurnLifecycle.schema_version,
      ),
      post_turn_lifecycle_status: stringOrEmpty(postTurnLifecycle.status),
      post_turn_lifecycle_semantic_memory_policy: stringOrEmpty(
        postTurnLifecycle.semantic_memory_policy,
      ),
      post_turn_lifecycle_background_tasks_scheduled_is_boolean:
        typeof postTurnLifecycle.background_tasks_scheduled === "boolean",
      post_turn_lifecycle_raw_content_included: bool(
        postTurnLifecyclePrivacy.raw_content_included,
      ),
      post_turn_lifecycle_identifier_strategy: stringOrEmpty(
        postTurnLifecyclePrivacy.identifier_strategy,
      ),
      post_turn_lifecycle_raw_scope_keys_present:
        hasForbiddenPostTurnLifecycleScopeKey(postTurnLifecycle),
      preview_required: bool(hostActions.preview_required),
      approval_token_present: bool(hostActions.approval_token_present),
      apply_attempted: bool(hostActions.apply_attempted),
    };
  });
  const routePathCounts = {};
  let routeReasonHashPresentCount = 0;
  let documentContextCaseCount = 0;
  let sourceRefCaseCount = 0;
  let previewRequiredCaseCount = 0;
  let applyAttemptedCount = 0;
  let visualLifecycleCaseCount = 0;
  let codeStudioLifecycleCaseCount = 0;
  const finalizationStatusCounts = {};
  let finalizationSavedCaseCount = 0;
  let finalizationErrorCaseCount = 0;
  const postTurnLifecycleStatusCounts = {};
  let postTurnLifecycleCaseCount = 0;
  for (const caseSummary of caseSummaries) {
    incrementCount(routePathCounts, caseSummary.path);
    incrementCount(
      finalizationStatusCounts,
      caseSummary.finalization_status || "missing",
    );
    incrementCount(
      postTurnLifecycleStatusCounts,
      caseSummary.post_turn_lifecycle_status || "missing",
    );
    if (caseSummary.route_reason_hash_present === true) {
      routeReasonHashPresentCount += 1;
    }
    if (caseSummary.finalization_saved === true) {
      finalizationSavedCaseCount += 1;
    }
    if (
      caseSummary.finalization_error_type_present === true ||
      caseSummary.finalization_status === "failed" ||
      caseSummary.finalization_status === "error"
    ) {
      finalizationErrorCaseCount += 1;
    }
    if (
      caseSummary.post_turn_lifecycle_schema_version ===
      POST_TURN_LIFECYCLE_SCHEMA
    ) {
      postTurnLifecycleCaseCount += 1;
    }
    if ((caseSummary.uploaded_document_count || 0) > 0) documentContextCaseCount += 1;
    if ((caseSummary.source_ref_count || 0) > 0) sourceRefCaseCount += 1;
    if (caseSummary.preview_required === true) previewRequiredCaseCount += 1;
    if (caseSummary.apply_attempted === true) applyAttemptedCount += 1;
    if (caseSummary.visual_lifecycle_complete === true) {
      visualLifecycleCaseCount += 1;
    }
    if (caseSummary.code_studio_lifecycle_complete === true) {
      codeStudioLifecycleCaseCount += 1;
    }
  }
  const selectedReplayCaseId =
    process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_CASE?.trim() || "";
  const validatedCaseSummaries = selectedReplayCaseId
    ? caseSummaries.filter((caseSummary) => caseSummary.scenario_id === selectedReplayCaseId)
    : caseSummaries;
  const finalizedCaseSummaries = caseSummaries.filter(
    (caseSummary) =>
      caseSummary.finalization_saved === true &&
      caseSummary.finalization_error_type_present !== true,
  );
  const postTurnLifecycleCaseSummaries = caseSummaries.filter(
    (caseSummary) =>
      caseSummary.post_turn_lifecycle_schema_version ===
        POST_TURN_LIFECYCLE_SCHEMA &&
      caseSummary.post_turn_lifecycle_raw_content_included === false &&
      caseSummary.post_turn_lifecycle_raw_scope_keys_present === false,
  );
  const capabilityPaths = asArray(capability.paths).map((item) => {
    const pathItem = asRecord(item);
    return {
      path: pathItem.path || "",
      status: pathItem.status || "",
      reason_hash_present:
        typeof pathItem.reason_hash === "string" &&
        pathItem.reason_hash.length > 0,
    };
  });
  const summary = {
    schema: "wiii.runtime_flow_browser_replay_summary.v1",
    generated_at: new Date().toISOString(),
    evidence: {
      file_name: path.basename(evidencePath),
      byte_count: rawEvidence.byteLength,
      sha256: hashBuffer(rawEvidence),
      sha256_present: rawEvidence.byteLength > 0,
      schema: evidence.schema || "",
      browser_replay_schema: browserReplay.schema || "",
      case_count: cases.length,
      case_count_matches_browser_replay: cases.length === caseSummaries.length,
    },
    target: {
      target_env: target.target_env || "",
      commit_sha: target.commit_sha || "",
      backend_url_hash: hashText(
        target.backend_url || process.env.WIII_RUNTIME_FLOW_BACKEND_URL || "",
      ),
      org_id_hash_present:
        typeof target.org_id_hash === "string" && target.org_id_hash.length > 0,
    },
    doctor: {
      status: doctor.status || "",
      ready_paths: numberOrNull(doctorSummary.ready_paths),
      blocked_paths: numberOrNull(doctorSummary.blocked_paths),
      warning_count: asArray(doctor.warnings).length,
      top_blocker_count: asArray(doctor.top_blockers).length,
    },
    checks: {
      total: checks.length,
      failed: checks.filter((check) => asRecord(check).status === "failed").length,
      sync_parity_passed: syncParityPassed,
    },
    browser_replay: {
      validated_by_playwright: true,
      exact_evidence_file_replayed: true,
      raw_prompt_answer_or_sse_payload_absent: true,
      raw_assistant_content_included: false,
      all_cases_validated_by_playwright:
        validatedCaseSummaries.length === caseSummaries.length,
      all_cases_finalized: finalizedCaseSummaries.length === caseSummaries.length,
      all_cases_have_post_turn_lifecycle_hash:
        postTurnLifecycleCaseSummaries.length === caseSummaries.length,
      route_path_counts: routePathCounts,
      route_reason_hash_present_count: routeReasonHashPresentCount,
      validated_case_id_hashes: validatedCaseSummaries.map((caseSummary) =>
        hashText(caseSummary.scenario_id),
      ),
      document_context_case_count: documentContextCaseCount,
      source_ref_case_count: sourceRefCaseCount,
      preview_required_case_count: previewRequiredCaseCount,
      apply_attempted_count: applyAttemptedCount,
      visual_lifecycle_case_count: visualLifecycleCaseCount,
      code_studio_lifecycle_case_count: codeStudioLifecycleCaseCount,
      finalization_status_counts: finalizationStatusCounts,
      finalization_saved_case_count: finalizationSavedCaseCount,
      finalization_error_case_count: finalizationErrorCaseCount,
      finalized_case_id_hashes: caseSummaries
        .filter((caseSummary) => finalizedCaseSummaries.includes(caseSummary))
        .map((caseSummary) => hashText(caseSummary.scenario_id)),
      post_turn_lifecycle_status_counts: postTurnLifecycleStatusCounts,
      post_turn_lifecycle_case_count: postTurnLifecycleCaseCount,
      post_turn_lifecycle_case_id_hashes: caseSummaries
        .filter((caseSummary) => postTurnLifecycleCaseSummaries.includes(caseSummary))
        .map((caseSummary) => hashText(caseSummary.scenario_id)),
      cases: caseSummaries,
    },
    wiii_connect_capability: {
      snapshot_version: capability.snapshot_version || "",
      surface: capability.surface || "",
      connection_count: numberOrNull(capability.connection_count),
      path_capability_count: numberOrNull(capability.path_capability_count),
      path_readiness_count: numberOrNull(capability.path_readiness_count),
      active_connection_count: numberOrNull(capability.active_connection_count),
      agent_ready_connection_count: numberOrNull(
        capability.agent_ready_connection_count,
      ),
      connected_provider_count: numberOrNull(capability.connected_provider_count),
      agent_ready_provider_count: numberOrNull(capability.agent_ready_provider_count),
      connected_scope_count: numberOrNull(capability.connected_scope_count),
      suppressed_tool_group_count: numberOrNull(
        capability.suppressed_tool_group_count,
      ),
      active_connection_slug_hashes: asArray(
        capability.active_connection_slug_hashes,
      ),
      agent_ready_connection_slug_hashes: asArray(
        capability.agent_ready_connection_slug_hashes,
      ),
      connected_provider_slug_hashes: asArray(
        capability.connected_provider_slug_hashes,
      ),
      agent_ready_provider_slug_hashes: asArray(
        capability.agent_ready_provider_slug_hashes,
      ),
      connected_scope_name_hashes: asArray(capability.connected_scope_name_hashes),
      suppressed_tool_group_hashes: asArray(
        capability.suppressed_tool_group_hashes,
      ),
      connection_status_counts: asRecord(capability.connection_status_counts),
      path_status_counts: asRecord(capability.path_status_counts),
      path_count: capabilityPaths.length,
      path_count_matches_readiness_count:
        capabilityPaths.length === numberOrNull(capability.path_readiness_count),
      path_reason_hash_present_count: capabilityPaths.filter(
        (item) => item.reason_hash_present === true,
      ).length,
      paths: capabilityPaths,
      raw_content_included: bool(capability.raw_content_included),
      identifier_strategy: capability.identifier_strategy || "",
    },
    summary_archive: {
      schema: "wiii.runtime_flow_browser_replay_summary_archive.v1",
      enabled: summaryArchiveLimit > 0,
      retention_limit: summaryArchiveLimit,
      raw_prompt_answer_or_sse_payload_absent: true,
      index_file_name: summaryArchiveIndexName,
    },
  };

  writeJsonFile(summaryPath, summary);
  console.log(`[INFO] Wrote hash/count browser replay summary JSON: ${summaryPath}`);
  writeSummaryArchive(summary);
}

function runStep(label, command, args, options) {
  console.log(`\n=== ${label} ===`);
  console.log([command, ...args].join(" "));
  const result = spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });
  if (typeof result.status === "number") {
    if (result.status !== 0) {
      process.exit(result.status);
    }
    return;
  }
  if (result.error) {
    console.error(`${label} failed to start: ${result.error.message}`);
  }
  process.exit(1);
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`Usage: node scripts/run-runtime-ledger-browser-replay.mjs [playwright args...]

Runs the backend runtime acceptance harness with --evidence-json, then replays
that exact sanitized browser_replay JSON file in the desktop Runtime-tab
Playwright acceptance.

Environment:
  WIII_RUNTIME_FLOW_BACKEND_URL        Backend URL, default http://127.0.0.1:8000
  WIII_RUNTIME_FLOW_SCENARIO           Scenario id/list, default ${defaultBrowserReplayScenarios}
  WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON Evidence JSON path under ignored test-results by default
  WIII_RUNTIME_FLOW_BROWSER_REPLAY_CASE Optional browser_replay case id for Playwright
  WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON Hash/count-only summary path
  WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_DIR Hash/count-only summary archive directory
  WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_LIMIT Retained archive summaries, default 25, 0 disables
  WIII_RUNTIME_FLOW_AUTH_MODE          auto, bearer, or dev-login
  WIII_RUNTIME_FLOW_BEARER_TOKEN       Bearer token for non-dev targets
  WIII_RUNTIME_FLOW_SYNC_PARITY        Set to 0 to skip default --sync-parity
`);
  process.exit(0);
}

const pythonCandidates = [
  process.env.WIII_PLAYWRIGHT_PYTHON,
  path.join(backendDir, ".venv", "Scripts", "python.exe"),
  path.join(backendDir, ".venv", "bin", "python"),
  "python",
].filter(Boolean);
const explicitPython = process.env.WIII_PLAYWRIGHT_PYTHON;
const python = explicitPython ||
  pythonCandidates.find((candidate) => candidate === "python" || existsSync(candidate));

if (!python) {
  console.error("Could not find a Python executable for runtime flow acceptance.");
  process.exit(1);
}

const acceptanceArgs = [
  acceptanceScript,
  "--backend-url",
  process.env.WIII_RUNTIME_FLOW_BACKEND_URL || "http://127.0.0.1:8000",
  "--scenario",
  process.env.WIII_RUNTIME_FLOW_SCENARIO || defaultBrowserReplayScenarios,
  "--evidence-json",
  evidencePath,
  "--target-env",
  process.env.WIII_RUNTIME_FLOW_TARGET_ENV || "browser-replay",
];

if (process.env.WIII_RUNTIME_FLOW_AUTH_MODE) {
  acceptanceArgs.push("--auth-mode", process.env.WIII_RUNTIME_FLOW_AUTH_MODE);
}
if (process.env.WIII_RUNTIME_FLOW_BEARER_TOKEN) {
  acceptanceArgs.push("--bearer-token", process.env.WIII_RUNTIME_FLOW_BEARER_TOKEN);
}
if (process.env.WIII_RUNTIME_FLOW_ORG_ID) {
  acceptanceArgs.push("--org-id", process.env.WIII_RUNTIME_FLOW_ORG_ID);
}
if (process.env.WIII_RUNTIME_FLOW_COMMIT_SHA) {
  acceptanceArgs.push("--commit-sha", process.env.WIII_RUNTIME_FLOW_COMMIT_SHA);
}
if (process.env.WIII_RUNTIME_FLOW_SYNC_PARITY !== "0") {
  acceptanceArgs.push("--sync-parity");
}

runStep("backend runtime acceptance evidence", python, acceptanceArgs, {
  cwd: backendDir,
  env: {
    ...process.env,
    PYTHONIOENCODING: "utf-8",
  },
});

const playwrightCli = path.join(desktopDir, "node_modules", "@playwright", "test", "cli.js");
if (!existsSync(playwrightCli)) {
  console.error(`Playwright CLI not found at ${playwrightCli}. Run npm install in wiii-desktop first.`);
  process.exit(1);
}

const playwrightArgs = [
  playwrightCli,
  "test",
  "-c",
  "playwright.runtime-ledger.config.ts",
  "--grep",
  process.env.WIII_RUNTIME_FLOW_BROWSER_REPLAY_GREP ||
    "renders backend browser_replay evidence in Runtime tab",
  ...process.argv.slice(2),
];

runStep("desktop runtime ledger browser replay", process.execPath, playwrightArgs, {
  cwd: desktopDir,
  env: {
    ...process.env,
    WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON: evidencePath,
  },
});

writeSummary();
