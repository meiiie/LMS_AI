import json
from types import SimpleNamespace

from app.engine.multi_agent.context_provenance_ledger import (
    CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION,
    build_context_provenance_ledger,
)
from app.engine.multi_agent.runtime_flow_ledger import RuntimeFlowLedger


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
            "host_context": {"host_type": "lms"},
            "document_context": {
                "attachments": [{"markdown": "# Uploaded brief"}],
            },
        }
    )

    assert "document_context_without_source_refs" in ledger["warnings"]
    assert "memory_context_without_typed_items" in ledger["warnings"]
    assert "host_context_without_capabilities" in ledger["warnings"]


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
    assert payload["context"]["uploaded_document_count"] == 1
    assert payload["context"]["source_ref_count"] == 1
    assert payload["context"]["memory_context_count"] == 1

    payload_json = json.dumps(payload, ensure_ascii=False)
    assert "REQUEST SECRET BODY" not in payload_json
    assert "EXECUTION SECRET BODY" not in payload_json
    assert "SECRET MEMORY CONTEXT" not in payload_json
    assert "private question" not in payload_json
    assert "execution-private.docx" not in payload_json
