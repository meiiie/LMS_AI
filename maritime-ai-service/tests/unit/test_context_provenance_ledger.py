import json
from types import SimpleNamespace

from app.engine.multi_agent.context_provenance_ledger import (
    CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION,
    build_context_provenance_ledger,
)
from app.engine.multi_agent.runtime_flow_ledger import (
    RuntimeFlowLedger,
    build_runtime_flow_trace_from_state,
)


def test_context_provenance_ledger_counts_sources_without_raw_content():
    ledger = build_context_provenance_ledger(
        {
            "conversation_history": "User: private question",
            "history_list": [{"role": "user", "content": "private question"}],
            "conversation_summary": "private summary",
            "semantic_context": "SECRET MEMORY CONTEXT",
            "semantic_memories": [
                {
                    "id": "memory-1",
                    "memory_type": "preference",
                    "content": "SECRET MEMORY ITEM",
                }
            ],
            "user_facts": [{"fact": "SECRET FACT"}],
            "core_memory_block": "SECRET CORE MEMORY",
            "host_context": {
                "surface": "embed_lms",
                "capabilities": ["lms", "host_action"],
            },
            "document_context": {
                "attachments": [
                    {
                        "file_name": "private.docx",
                        "markdown": "SECRET DOCUMENT BODY",
                        "parser": "markitdown",
                        "parser_chain": ["mammoth", "ocr"],
                        "media_kind": "document",
                        "provenance_level": "page",
                        "truncated": True,
                        "source_references": [
                            {"content_type": "heading", "page_start": 1}
                        ],
                    }
                ]
            },
            "source_refs": [{"kind": "rag"}],
        }
    )

    assert ledger["schema_version"] == CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION
    assert ledger["conversation"]["history_present"] is True
    assert ledger["conversation"]["history_item_count"] == 1
    assert ledger["documents"]["usable_attachment_count"] == 1
    assert ledger["documents"]["source_ref_count"] == 2
    assert ledger["documents"]["parser_names"] == ["markitdown"]
    assert ledger["documents"]["parser_chain_names"] == ["mammoth", "ocr"]
    assert ledger["documents"]["source_ref_kinds"] == ["rag", "heading"]
    assert ledger["memory"]["semantic_memory_count"] == 1
    assert ledger["memory"]["semantic_memory_types"] == ["preference"]
    assert ledger["memory"]["user_fact_count"] == 1
    assert ledger["host"]["surface"] == "embed_lms"
    assert ledger["host"]["capability_names"] == ["lms", "host_action"]
    assert ledger["privacy"]["raw_content_included"] is False

    ledger_json = json.dumps(ledger, ensure_ascii=False)
    assert "SECRET" not in ledger_json
    assert "private.docx" not in ledger_json
    assert "private question" not in ledger_json


def test_context_provenance_ledger_warns_on_unprovenanced_context():
    ledger = build_context_provenance_ledger(
        {
            "semantic_context": "Summarized memory without typed items",
            "memory_warnings": ["semantic_memory_read_blocked_missing_org_context"],
            "host_context": {"host_type": "lms"},
            "document_context": {
                "attachments": [{"markdown": "# Uploaded brief"}],
            },
        }
    )

    assert "document_context_without_source_refs" in ledger["warnings"]
    assert "memory_context_without_typed_items" in ledger["warnings"]
    assert "semantic_memory_read_blocked_missing_org_context" in ledger["warnings"]
    assert (
        ledger["memory"]["warning_codes"]
        == ["semantic_memory_read_blocked_missing_org_context"]
    )
    assert "host_context_without_capabilities" in ledger["warnings"]


def test_context_provenance_ledger_counts_typed_memory_retrieval_without_raw_content():
    ledger = build_context_provenance_ledger(
        {
            "semantic_context": "SECRET RETRIEVED MEMORY TEXT",
            "memory_retrieval_summary": {
                "status": "ready",
                "relevant_memory_count": 2,
                "insight_count": 1,
                "user_fact_count": 3,
                "semantic_memory_count": 6,
                "memory_type_names": ["message", "summary"],
                "fact_type_names": ["goal", "preference"],
                "insight_category_names": ["learning_style"],
                "warning_codes": [],
            },
            "user_facts": [
                {"content": "SECRET FACT 1"},
                {"content": "SECRET FACT 2"},
                {"content": "SECRET FACT 3"},
            ],
        }
    )

    memory = ledger["memory"]
    assert memory["retrieval_present"] is True
    assert memory["retrieval_status"] == "ready"
    assert memory["semantic_memory_count"] == 6
    assert memory["relevant_memory_count"] == 2
    assert memory["insight_count"] == 1
    assert memory["user_fact_count"] == 3
    assert memory["semantic_memory_types"] == ["message", "summary"]
    assert memory["fact_type_names"] == ["goal", "preference"]
    assert memory["insight_category_names"] == ["learning_style"]
    assert "memory_context_without_typed_items" not in ledger["warnings"]

    ledger_json = json.dumps(ledger, ensure_ascii=False)
    assert "SECRET RETRIEVED MEMORY TEXT" not in ledger_json
    assert "SECRET FACT" not in ledger_json


def test_context_provenance_ledger_counts_typed_history_without_raw_content():
    ledger = build_context_provenance_ledger(
        {
            "conversation_history": "User: SECRET CURRENT HISTORY",
            "history_list": [{"role": "user", "content": "SECRET TURN"}],
            "history_retrieval_summary": {
                "schema_version": "wiii.chat_history_retrieval.v1",
                "status": "fallback",
                "source": "session_continuity_fallback",
                "persisted_history_item_count": 0,
                "fallback_history_item_count": 2,
                "selected_history_item_count": 2,
                "org_scoped": True,
                "user_name_present": True,
                "raw_content_included": False,
                "warning_codes": ["session_history_fallback_used"],
            },
            "context_budget_summary": {
                "schema_version": "wiii.context_budget.v1",
                "status": "ready",
                "total_budget": 20000,
                "total_used": 12000,
                "utilization": 0.6,
                "needs_compaction": True,
                "messages_included": 4,
                "messages_dropped": 8,
                "has_summary": True,
                "langchain_message_count": 5,
                "raw_content_included": False,
                "warning_codes": ["context_budget_near_limit"],
            },
        }
    )

    conversation = ledger["conversation"]
    assert conversation["history_retrieval_present"] is True
    assert conversation["history_retrieval_status"] == "fallback"
    assert conversation["history_source"] == "session_continuity_fallback"
    assert conversation["persisted_history_item_count"] == 0
    assert conversation["fallback_history_item_count"] == 2
    assert conversation["selected_history_item_count"] == 2
    assert conversation["history_org_scoped"] is True
    assert conversation["history_user_name_present"] is True
    assert conversation["history_raw_content_included"] is False
    assert conversation["context_budget_present"] is True
    assert conversation["context_budget_status"] == "ready"
    assert conversation["context_budget_total"] == 20000
    assert conversation["context_budget_used"] == 12000
    assert conversation["context_budget_utilization"] == 0.6
    assert conversation["context_budget_needs_compaction"] is True
    assert conversation["context_budget_messages_included"] == 4
    assert conversation["context_budget_messages_dropped"] == 8
    assert conversation["context_budget_has_summary"] is True
    assert conversation["context_budget_raw_content_included"] is False
    assert "session_history_fallback_used" in ledger["warnings"]
    assert "context_budget_near_limit" in ledger["warnings"]

    ledger_json = json.dumps(ledger, ensure_ascii=False)
    assert "SECRET CURRENT HISTORY" not in ledger_json
    assert "SECRET TURN" not in ledger_json


def test_context_provenance_ledger_counts_episodic_retrieval_without_raw_content():
    ledger = build_context_provenance_ledger(
        {
            "core_memory_block": "SECRET EPISODIC TEXT",
            "episodic_retrieval_summary": {
                "schema_version": "wiii.episodic_retrieval.v1",
                "status": "ready",
                "match_count": 2,
                "event_types": ["user_message", "assistant_message"],
                "max_score": 0.8,
                "min_score": 0.4,
                "current_session_excluded": True,
                "org_scoped": True,
                "raw_content_included": False,
                "warning_codes": ["episodic_retrieval_failed"],
            },
        }
    )

    memory = ledger["memory"]
    assert memory["episodic_retrieval_present"] is True
    assert memory["episodic_retrieval_status"] == "ready"
    assert memory["episodic_match_count"] == 2
    assert memory["episodic_event_types"] == [
        "user_message",
        "assistant_message",
    ]
    assert memory["episodic_max_score"] == 0.8
    assert memory["episodic_min_score"] == 0.4
    assert memory["episodic_org_scoped"] is True
    assert memory["episodic_current_session_excluded"] is True
    assert memory["episodic_raw_content_included"] is False
    assert "episodic_retrieval_failed" in memory["warning_codes"]
    assert "episodic_retrieval_failed" in ledger["warnings"]

    ledger_json = json.dumps(ledger, ensure_ascii=False)
    assert "SECRET EPISODIC TEXT" not in ledger_json


def test_runtime_flow_ledger_embeds_context_provenance_without_prompt_text():
    flow = RuntimeFlowLedger.from_chat_request(
        chat_request=SimpleNamespace(
            user_id="user-1",
            provider="nvidia",
            model="deepseek",
            user_context={
                "host_context": {
                    "surface": "embed_lms",
                    "capabilities": ["lms", "host_action"],
                },
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "request-private.docx",
                            "markdown": "REQUEST SECRET BODY",
                        }
                    ]
                },
            },
        ),
        request_id="req-1",
    )
    flow.mark_prepared_turn(
        session_id="session-1",
        organization_id="org-1",
        domain_id="maritime",
    )
    flow.mark_execution_input(
        SimpleNamespace(
            provider="nvidia",
            model="deepseek",
            context={
                "conversation_history": "User asked a private question",
                "history_retrieval_summary": {
                    "schema_version": "wiii.chat_history_retrieval.v1",
                    "status": "ready",
                    "source": "persisted_chat_history",
                    "persisted_history_item_count": 1,
                    "fallback_history_item_count": 0,
                    "selected_history_item_count": 1,
                    "org_scoped": True,
                    "user_name_present": False,
                    "raw_content_included": False,
                    "warning_codes": [],
                },
                "context_budget_summary": {
                    "schema_version": "wiii.context_budget.v1",
                    "status": "ready",
                    "total_budget": 20000,
                    "total_used": 10000,
                    "utilization": 0.5,
                    "needs_compaction": False,
                    "messages_included": 1,
                    "messages_dropped": 0,
                    "has_summary": False,
                    "raw_content_included": False,
                    "warning_codes": [],
                },
                "semantic_context": "SECRET MEMORY CONTEXT",
                "semantic_memories": [{"memory_type": "preference"}],
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "execution-private.docx",
                            "markdown": "EXECUTION SECRET BODY",
                            "source_references": [{"content_type": "table"}],
                        }
                    ]
                },
            },
        )
    )

    payload = flow.to_payload()
    provenance = payload["context"]["context_provenance"]
    assert provenance["schema_version"] == CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION
    assert provenance["documents"]["usable_attachment_count"] == 1
    assert provenance["documents"]["source_ref_count"] == 1
    assert provenance["conversation"]["history_retrieval_status"] == "ready"
    assert provenance["conversation"]["selected_history_item_count"] == 1
    assert payload["context"]["uploaded_document_count"] == 1
    assert payload["context"]["source_ref_count"] == 1
    assert payload["context"]["memory_context_count"] == 1
    assert payload["context"]["history_context_count"] == 1
    assert payload["context"]["history_retrieval_status"] == "ready"
    assert payload["context"]["history_source"] == "persisted_chat_history"
    assert payload["context"]["context_budget_utilization"] == 0.5
    assert payload["context"]["context_budget_messages_dropped"] == 0
    assert payload["context"]["context_budget_status"] == "ready"

    payload_json = json.dumps(payload, ensure_ascii=False)
    assert "REQUEST SECRET BODY" not in payload_json
    assert "EXECUTION SECRET BODY" not in payload_json
    assert "SECRET MEMORY CONTEXT" not in payload_json
    assert "private question" not in payload_json
    assert "execution-private.docx" not in payload_json


def test_runtime_flow_trace_counts_provider_call_correlation_without_raw_ids():
    trace = build_runtime_flow_trace_from_state(
        {
            "request_id": "req-private-trace",
            "tool_call_events": [
                {
                    "type": "result",
                    "name": "wiii_connect_execute_action",
                    "result": json.dumps(
                        {
                            "version": "wiii_connect_generic_direct_tool.v1",
                            "status": "action_completed",
                            "success": True,
                            "provider_slug": "gmail",
                            "action_slug": "GMAIL_FETCH_EMAILS",
                            "schema": {
                                "ready": True,
                                "request_id": "req-private-trace",
                            },
                            "execution": {
                                "status": "succeeded",
                                "success": True,
                                "request_id": "req-private-trace",
                            },
                        }
                    ),
                }
            ],
        }
    )

    correlation = trace["external_action_trace"]["provider_call_correlation"]
    assert correlation == {
        "provider_call_seen": True,
        "request_id_present": True,
        "stage_count": 2,
        "stage_request_id_present_count": 2,
        "stage_request_id_missing_count": 0,
        "stage_request_id_match_count": 2,
        "stage_request_id_mismatch_count": 0,
        "stage_request_id_consistent": True,
        "all_stage_request_ids_match_request": True,
    }
    assert (
        trace["external_action_trace"]["events"][0]["provider_call_correlation"]
        == correlation
    )

    serialized = json.dumps(trace, ensure_ascii=False)
    assert "req-private-trace" not in serialized
