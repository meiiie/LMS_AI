import { describe, expect, it } from "vitest";
import {
  buildRuntimeFlowLedgerViewModel,
  latestRuntimeFlowLedger,
} from "@/lib/runtime-flow-trace";

function viewText(value: ReturnType<typeof buildRuntimeFlowLedgerViewModel>): string {
  return [
    value.summary,
    ...value.rows.map((row) => `${row.label}: ${row.value}`),
    ...value.warnings,
  ].join("\n");
}

describe("runtime flow ledger view model", () => {
  it("prefers pending stream ledger over older assistant metadata", () => {
    const pending = {
      processing_time: 0.1,
      model: "test",
      agent_type: "direct" as const,
      runtime_flow_ledger: {
        schema_version: "wiii.runtime_flow_ledger.v1",
        route: { lane: "visual_generation" },
        stream: { done_seen: true, event_counts: { done: 1 } },
      },
    };
    const older = {
      id: "assistant-old",
      role: "assistant" as const,
      content: "old",
      timestamp: "2026-06-01T00:00:00.000Z",
      metadata: {
        processing_time: 0.1,
        model: "test",
        agent_type: "direct" as const,
        runtime_flow_ledger: {
          schema_version: "wiii.runtime_flow_ledger.v1",
          route: { lane: "casual_chat" },
          stream: { done_seen: true, event_counts: { done: 1 } },
        },
      },
    };

    const ledger = latestRuntimeFlowLedger([older], pending);

    expect(ledger?.route?.lane).toBe("visual_generation");
  });

  it("warns when visual runtime lacks visual lifecycle events and redacts text", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "access_token=secret-token",
        host_capabilities: ["visual"],
      },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: { lane: "visual_generation" },
      tools: { observed: ["visual_runtime"], suppressed: [] },
      stream: {
        done_seen: true,
        event_counts: { answer: 1, visual_open: 1, done: 1 },
      },
      host_actions: { preview_required: false, apply_attempted: false },
    });
    const rendered = viewText(vm);

    expect(vm.tone).toBe("warn");
    expect(rendered).toContain("Visual runtime thiếu visual_open hoặc visual_commit");
    expect(rendered).toContain("[redacted]");
    expect(rendered).not.toContain("secret-token");
  });

  it("accepts complete Code Studio lifecycle evidence", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "desktop_chat",
        host_capabilities: ["code_studio"],
      },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: { lane: "visual_generation" },
      tools: { observed: ["code_studio"], suppressed: ["pointy_action"] },
      stream: {
        done_seen: true,
        event_counts: { answer: 1, code_open: 1, code_complete: 1, done: 1 },
      },
      host_actions: { preview_required: false, apply_attempted: false },
    });

    expect(vm.tone).toBe("ok");
    expect(vm.warnings).toEqual([]);
    expect(viewText(vm)).toContain("code_studio");
  });

  it("surfaces compact route decision evidence", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "desktop_chat",
        host_capabilities: [],
      },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: {
        lane: "native_turn",
        reason: "browser_route_reason",
        selected_agent: "direct",
        final_agent: "direct",
        turn_path_decision: {
          path: "casual_chat",
          reason: "ordinary_chat_no_tools",
          bind_tools: false,
          force_tools: false,
        },
      },
      tools: { observed: [], suppressed: ["host_action"] },
      stream: {
        done_seen: true,
        event_counts: { answer: 1, metadata: 1, done: 1 },
      },
      host_actions: { preview_required: false, apply_attempted: false },
    });
    const rendered = viewText(vm);

    expect(rendered).toContain("Route decision");
    expect(rendered).toContain("ordinary_chat_no_tools");
    expect(rendered).toContain("bind");
    expect(rendered).toContain("force");
    expect(rendered).toContain("agent direct");
  });

  it("surfaces provider model and tool-loop evidence", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "desktop_chat",
        host_capabilities: ["wiii_connect"],
      },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: { lane: "external_app_action" },
      runtime: {
        provider: "nvidia",
        model: "qwen3-next",
        runtime_authoritative: true,
      },
      tools: {
        observed: ["tool_wiii_connect_delegate_to_integration"],
        suppressed: ["pointy_action"],
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
        done_seen: true,
        event_counts: {
          answer: 1,
          tool_call: 1,
          tool_result: 1,
          metadata: 1,
          done: 1,
        },
      },
      host_actions: {
        preview_required: false,
        apply_attempted: false,
        result_received: true,
        result_success: true,
      },
    });
    const rendered = viewText(vm);

    expect(rendered).toContain("Provider/model");
    expect(rendered).toContain("nvidia");
    expect(rendered).toContain("qwen3-next");
    expect(rendered).toContain("authoritative C");
    expect(rendered).toContain("Tool loop");
    expect(rendered).toContain("tool_wiii_connect_delegate_to_integration");
    expect(rendered).toContain("calls 1");
    expect(rendered).toContain("results 1");
    expect(rendered).toContain("denials 1");
    expect(rendered).toContain("host result C");
  });

  it("surfaces scheduled task creation and delivery evidence", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "desktop_chat",
        host_capabilities: ["scheduled_tasks"],
      },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: { lane: "scheduled_task_create" },
      runtime: {
        provider: "browser-harness",
        model: "scheduled-task-mock",
        runtime_authoritative: true,
      },
      tools: {
        observed: ["tool_schedule_reminder"],
        suppressed: ["host_action"],
        policy_session: {
          visible_tool_names: ["tool_schedule_reminder"],
        },
      },
      scheduled_tasks: {
        created: true,
        creation_tool: "tool_schedule_reminder",
        due_seen: true,
        delivery: {
          channel: "websocket",
          status: "delivered",
        },
      },
      stream: {
        done_seen: true,
        event_counts: {
          answer: 1,
          tool_call: 1,
          tool_result: 1,
          metadata: 1,
          done: 1,
        },
      },
      host_actions: {
        preview_required: false,
        apply_attempted: false,
      },
    });
    const rendered = viewText(vm);

    expect(vm.tone).toBe("ok");
    expect(rendered).toContain("scheduled_task_create");
    expect(rendered).toContain("Scheduled task");
    expect(rendered).toContain("created C");
    expect(rendered).toContain("tool_schedule_reminder");
    expect(rendered).toContain("due C");
    expect(rendered).toContain("websocket/delivered");
  });

  it("surfaces privacy-safe context provenance and warning codes", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: {
        host_surface: "desktop_chat",
        host_capabilities: ["document_context", "semantic_memory"],
      },
      context: {
        uploaded_document_count: 1,
        source_ref_count: 2,
        memory_context_count: 3,
        history_context_count: 2,
        history_retrieval_status: "ready",
        history_source: "persisted_chat_history",
        context_budget_utilization: 0.5,
        context_budget_messages_dropped: 2,
        context_budget_status: "ready",
        context_provenance: {
          schema_version: "wiii.context_provenance_ledger.v1",
          documents: {
            attachment_count: 1,
            source_ref_count: 2,
            source_ref_kinds: ["document_source_ref", "citation"],
          },
          memory: {
            semantic_memory_count: 3,
            semantic_memory_types: ["preference", "goal"],
            fact_type_names: ["learning_profile"],
            insight_category_names: ["habit"],
            episodic_retrieval_present: true,
            episodic_retrieval_status: "ready",
            episodic_match_count: 1,
            episodic_event_types: ["lesson_completed"],
            episodic_min_score: 0.42,
            episodic_max_score: 0.91,
            episodic_org_scoped: true,
            episodic_current_session_excluded: true,
            episodic_raw_content_included: false,
          },
          warnings: ["document_context_truncated"],
          privacy: {
            raw_content_included: false,
            identifier_strategy: "hash_or_count_only",
          },
        },
      },
      route: { lane: "document_grounded_answer" },
      tools: { observed: [], suppressed: ["host_action"] },
      subagents: {
        schema_version: "wiii.subagent_boundary_trace.v1",
        report_count: 1,
        raw_content_included: false,
        warning_codes: ["state_top_level_keys_dropped"],
        reports: [
          {
            agent_name: "rag",
            agent_type: "retrieval",
            status: "success",
            state_projected_key_count: 4,
            state_dropped_key_count: 6,
            output_char_count: 128,
            source_count: 2,
            tool_count: 1,
            thinking_dropped: true,
          },
        ],
      },
      stream: {
        done_seen: true,
        event_counts: { answer: 1, metadata: 1, done: 1 },
      },
      host_actions: {
        preview_required: true,
        approval_token_present: true,
        apply_attempted: false,
      },
    });
    const rendered = viewText(vm);

    expect(vm.tone).toBe("ok");
    expect(rendered).toContain("docs 1");
    expect(rendered).toContain("sources 2");
    expect(rendered).toContain("memory 3");
    expect(rendered).toContain("History context");
    expect(rendered).toContain("items 2");
    expect(rendered).toContain("ready/persisted_chat_history");
    expect(rendered).toContain("Context budget");
    expect(rendered).toContain("utilization 0.5");
    expect(rendered).toContain("dropped 2");
    expect(rendered).toContain("Subagent boundary");
    expect(rendered).toContain("reports 1");
    expect(rendered).toContain("projected 4");
    expect(rendered).toContain("dropped 6");
    expect(rendered).toContain("sources 2");
    expect(rendered).toContain("tools 1");
    expect(rendered).toContain("thinking dropped 1");
    expect(rendered).toContain("state_top_level_keys_dropped");
    expect(rendered).toContain("document_source_ref");
    expect(rendered).toContain("preference");
    expect(rendered).toContain("learning_profile");
    expect(rendered).toContain("Episodic recall");
    expect(rendered).toContain("matches 1");
    expect(rendered).toContain("lesson_completed");
    expect(rendered).toContain("score 0.42-0.91");
    expect(rendered).toContain("org_scoped true");
    expect(rendered).toContain("current_session_excluded true");
    expect(rendered).toContain("episodic_raw_content false");
    expect(rendered).toContain("document_context_truncated");
    expect(rendered).toContain("hash_or_count_only");
    expect(rendered).toContain("preview Có; approval Có; apply Không");
  });

  it("warns when normal chat receives host, Pointy, visual, or code events", () => {
    const vm = buildRuntimeFlowLedgerViewModel({
      schema_version: "wiii.runtime_flow_ledger.v1",
      request: { host_surface: "desktop_chat", host_capabilities: [] },
      context: {
        uploaded_document_count: 0,
        source_ref_count: 0,
        memory_context_count: 0,
      },
      route: { lane: "casual_chat" },
      tools: {
        observed: [],
        suppressed: ["host_action", "pointy_action", "visual_runtime", "code_studio"],
      },
      stream: {
        done_seen: true,
        event_counts: { answer: 1, pointy_action: 1, code_open: 1, done: 1 },
      },
      host_actions: { preview_required: false, apply_attempted: false },
    });
    const rendered = viewText(vm);

    expect(vm.tone).toBe("warn");
    expect(rendered).toContain("No-action turn có event không được phép");
    expect(rendered).toContain("pointy_action");
    expect(rendered).toContain("code_open");
  });
});
