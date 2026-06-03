"""
Tests for Sprint 30: Chat API endpoint coverage.

Covers:
- _classify_query_type: Vietnamese + English keyword detection
- _generate_suggested_questions: context-based suggestions
- _get_tool_description: tool usage info formatting
- get_chat_history: limit clamping, offset validation
- delete_chat_history: role-based access control
"""

import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# =============================================================================
# _classify_query_type
# =============================================================================


class TestClassifyQueryType:
    """Test query type classification for LMS analytics."""

    def test_procedural_vietnamese(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Làm thế nào để neo tàu?") == "procedural"

    def test_procedural_english(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("How to anchor a ship?") == "procedural"

    def test_procedural_cach(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Cách tính khoảng cách?") == "procedural"

    def test_procedural_quy_trinh(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Quy trình xử lý sự cố?") == "procedural"

    def test_factual_la_gi(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("COLREGs là gì?") == "factual"

    def test_factual_dieu(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Điều 10 nói gì?") == "factual"

    def test_factual_english(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("What is SOLAS regulation?") == "factual"

    def test_factual_quy_dinh(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Quy định về phòng cháy?") == "factual"

    def test_default_conceptual(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("Giải thích cho tôi về hàng hải") == "conceptual"

    def test_empty_string(self):
        from app.api.v1.chat import _classify_query_type
        assert _classify_query_type("") == "conceptual"

    def test_procedural_takes_priority(self):
        """Procedural checked before factual."""
        from app.api.v1.chat import _classify_query_type
        # "Cách" (procedural) + "quy định" (factual) → procedural wins
        assert _classify_query_type("Cách áp dụng quy định này?") == "procedural"


# =============================================================================
# _generate_suggested_questions
# =============================================================================


class TestGenerateSuggestedQuestions:
    """Test suggested follow-up question generation."""

    def test_returns_three_questions(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions("Hello", "World")
        assert len(result) == 3

    def test_rule_context(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions("test", "Quy tắc 10 nói rằng...")
        assert any("quy tắc" in q.lower() or "ngoại lệ" in q.lower() for q in result)

    def test_safety_context(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions("test", "An toàn hàng hải yêu cầu thiết bị...")
        assert any("yêu cầu" in q.lower() or "tiêu chuẩn" in q.lower() for q in result)

    def test_learning_context(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions("Tôi muốn học COLREGs", "Đây là nội dung bài học")
        assert any("tìm hiểu" in q.lower() or "thực hành" in q.lower() for q in result)

    def test_generic_fallback(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions("random", "random response no keywords")
        assert len(result) == 3
        assert all(isinstance(q, str) for q in result)

    def test_code_generation_followups(self):
        from app.api.v1.chat import _generate_suggested_questions
        result = _generate_suggested_questions(
            "Ve bieu do bang Python",
            "Mình đã tạo xong artifact cho bạn.",
        )
        assert any(
            "artifact" in q.lower() or "html" in q.lower() or "excel" in q.lower()
            for q in result
        )


def test_classify_query_type_code_generation():
    from app.api.v1.chat import _classify_query_type
    assert _classify_query_type("Ve bieu do bang Python va gui file PNG") == "code_generation"


# =============================================================================
# _get_tool_description
# =============================================================================


class TestGetToolDescription:
    """Test tool description formatting."""

    def test_knowledge_search_with_query(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_knowledge_search", "args": {"query": "COLREGs"}})
        assert "COLREGs" in result

    def test_knowledge_search_no_query(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_knowledge_search", "args": {}})
        assert result == "Tra cứu kiến thức"

    def test_maritime_search(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_maritime_search", "args": {"query": "SOLAS"}})
        assert "SOLAS" in result

    def test_save_user_info(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_save_user_info", "args": {"key": "name", "value": "Minh"}})
        assert "name" in result and "Minh" in result

    def test_save_user_info_no_key(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_save_user_info", "args": {}})
        assert result == "Lưu thông tin người dùng"

    def test_get_user_info(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "tool_get_user_info", "args": {"key": "name"}})
        assert "name" in result

    def test_unknown_tool_with_result(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "custom_tool", "result": "some output"})
        assert result == "some output"

    def test_unknown_tool_no_result(self):
        from app.api.v1.chat import _get_tool_description
        result = _get_tool_description({"name": "custom_tool"})
        assert "custom_tool" in result


class TestBuildChatResponse:
    """Test sync API response presenter contract."""

    def test_build_chat_response_maps_sources_tools_and_metadata(self):
        from app.models.schemas import ChatRequest, InternalChatResponse, Source, UserRole
        from app.services.chat_response_presenter import build_chat_response

        request = ChatRequest(
            user_id="user-1",
            message="COLREG Rule 5 là gì?",
            role=UserRole.STUDENT,
        )
        internal_response = InternalChatResponse(
            message="Rule 5 yêu cầu luôn duy trì cảnh giới thích đáng.",
            agent_type="rag",
            sources=[
                Source(
                    node_id="n1",
                    title="COLREG Rule 5",
                    source_type="knowledge_graph",
                    content_snippet="Every vessel shall at all times maintain a proper look-out.",
                    document_id="doc-1",
                    page_number=12,
                )
            ],
            metadata={
                "session_id": "session-1",
                "tools_used": [{"name": "tool_knowledge_search", "args": {"query": "Rule 5"}}],
                "thinking": "Tôi sẽ tra cứu đúng điều khoản liên quan.",
                "routing_metadata": {"intent": "lookup"},
                "runtime_flow_trace": {
                    "version": "wiii.runtime_flow_trace.v1",
                    "turn_path_decision": {
                        "path": "external_app_action",
                        "reason": "facebook_post_request",
                        "approval_token": "raw-approval-token",
                    },
                    "external_action_trace": {
                        "version": "wiii.external_action_trace.v1",
                        "observed_action_result": True,
                        "last_status": "action_completed",
                        "events": [
                            {
                                "type": "result",
                                "tool_name": "tool_wiii_connect_delegate_to_integration",
                                "provider_slug": "facebook",
                                "approval_token": "raw-approval-token",
                            }
                        ],
                    },
                },
                "domain_notice": "ngoài domain nhẹ",
            },
        )

        response = build_chat_response(
            chat_request=request,
            internal_response=internal_response,
            processing_time=1.2345,
            provider_name="zhipu",
            model_name="agentic-rag-v3",
        )

        assert response.status == "success"
        assert response.data.answer == internal_response.message
        assert response.data.domain_notice == "ngoài domain nhẹ"
        assert response.data.sources[0].title == "COLREG Rule 5"
        assert response.metadata.session_id == "session-1"
        assert response.metadata.processing_time == 1.234
        assert response.metadata.provider == "zhipu"
        assert response.metadata.query_type == "factual"
        assert response.metadata.tools_used[0].description == "Tra cứu: Rule 5"
        assert response.metadata.topics_accessed == ["COLREG Rule 5"]
        assert response.metadata.document_ids_used == ["doc-1"]
        assert (
            response.metadata.runtime_flow_trace["turn_path_decision"]["path"]
            == "external_app_action"
        )
        assert "raw-approval-token" not in response.model_dump_json()
        assert response.metadata.thinking == "Tôi sẽ tra cứu đúng điều khoản liên quan."

    def test_build_chat_response_handles_empty_sources_and_tools(self):
        from app.models.schemas import ChatRequest, InternalChatResponse, UserRole
        from app.services.chat_response_presenter import build_chat_response

        request = ChatRequest(
            user_id="user-1",
            message="Giải thích giúp tôi",
            role=UserRole.STUDENT,
        )
        internal_response = InternalChatResponse(
            message="Đây là giải thích tổng quan.",
            agent_type="direct",
            metadata={},
        )

        response = build_chat_response(
            chat_request=request,
            internal_response=internal_response,
            processing_time=0.5,
            provider_name=None,
            model_name="agentic-rag-v3",
        )

        assert response.data.sources == []
        assert response.metadata.tools_used == []
        assert response.metadata.topics_accessed is None
        assert response.metadata.document_ids_used is None
        assert response.metadata.confidence_score is None

    def test_build_chat_response_sanitizes_public_json_boundary(self):
        from app.models.schemas import ChatRequest, InternalChatResponse, Source, UserRole
        from app.services.chat_response_presenter import build_chat_response

        request = ChatRequest(
            user_id="user-1",
            message="show source",
            role=UserRole.STUDENT,
        )
        internal_response = InternalChatResponse(
            message="Done access_token=raw-answer-token",
            agent_type="direct",
            sources=[
                Source(
                    node_id="n1",
                    title="Bearer raw-source-title-token-12345678",
                    source_type="knowledge_graph",
                    content_snippet="token=raw-source-content-token",
                    image_url="https://example.com?token=raw-source-url-token",
                    document_id="doc-token=raw-document-token",
                    page_number=1,
                )
            ],
            metadata={
                "session_id": "session-1",
                "tools_used": [
                    {
                        "name": "tool_knowledge_search",
                        "args": {
                            "query": "Bearer raw-tool-query-token-12345678",
                            "access_token": "raw-tool-token",
                        },
                    }
                ],
                "thinking": "private thinking access_token=raw-thinking-token",
                "thinking_content": "Public thinking.",
                "routing_metadata": {
                    "final_agent": "direct",
                    "connection_ref": "wcn_raw_connection",
                    "safe": "ok",
                },
                "failover": {
                    "last_reason_code": "token=raw-failover-token",
                },
                "runtime_flow_trace": {
                    "version": "wiii.runtime_flow_trace.v1",
                    "turn_path_decision": {
                        "path": "direct",
                        "approval_token": "raw-approval-token",
                    },
                },
                "domain_notice": "Bearer raw-domain-token-12345678",
            },
        )

        response = build_chat_response(
            chat_request=request,
            internal_response=internal_response,
            processing_time=0.25,
            provider_name="google",
            model_name="gemini",
        )

        serialized = response.model_dump_json()

        assert response.metadata.thinking == "Public thinking."
        assert response.metadata.routing_metadata["safe"] == "ok"
        assert "raw-answer-token" not in serialized
        assert "raw-source-title-token" not in serialized
        assert "raw-source-content-token" not in serialized
        assert "raw-source-url-token" not in serialized
        assert "raw-document-token" not in serialized
        assert "raw-tool-query-token" not in serialized
        assert "raw-tool-token" not in serialized
        assert "raw-thinking-token" not in serialized
        assert "wcn_raw_connection" not in serialized
        assert "raw-failover-token" not in serialized
        assert "raw-approval-token" not in serialized
        assert "raw-domain-token" not in serialized


class TestChatEndpointPresenter:
    """Test sync endpoint transport helpers."""

    def test_build_chat_service_error_response_preserves_request_id(self):
        from app.api.v1.chat_endpoint_presenter import (
            build_chat_service_error_response,
        )

        response = build_chat_service_error_response(
            error_code="CHAT_FAILED",
            message="boom",
            http_status=418,
            request_id="req-123",
        )

        assert response.status_code == 418
        payload = json.loads(response.body)
        assert payload["error_code"] == "CHAT_FAILED"
        assert payload["message"] == "boom"
        assert payload["request_id"] == "req-123"

    def test_build_chat_internal_error_response_uses_standard_payload(self):
        from app.api.v1.chat_endpoint_presenter import (
            build_chat_internal_error_response,
        )

        response = build_chat_internal_error_response(request_id="req-500")

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload == {
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "request_id": "req-500",
        }

    def test_build_chat_api_error_response_uses_simple_payload(self):
        from app.api.v1.chat_endpoint_presenter import build_chat_api_error_response

        response = build_chat_api_error_response(
            status_code=403,
            error="permission_denied",
            message="forbidden",
        )

        assert response.status_code == 403
        payload = json.loads(response.body)
        assert payload == {
            "error": "permission_denied",
            "message": "forbidden",
        }

    def test_build_logged_chat_api_error_response_logs_and_builds_payload(self):
        from app.api.v1.chat_endpoint_presenter import (
            build_logged_chat_api_error_response,
        )

        logger = MagicMock()

        response = build_logged_chat_api_error_response(
            logger=logger,
            operation_label="retrieving chat history",
            error=RuntimeError("boom"),
            error_code="internal_error",
            message="Failed to retrieve chat history",
        )

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload == {
            "error": "internal_error",
            "message": "Failed to retrieve chat history",
        }
        logger.exception.assert_called_once()

    def test_build_missing_session_response_uses_standard_payload(self):
        from app.api.v1.chat_endpoint_presenter import build_missing_session_response

        response = build_missing_session_response()

        assert response.status_code == 400
        payload = json.loads(response.body)
        assert payload == {
            "error": "missing_session",
            "message": "X-Session-ID header required",
        }

    def test_log_chat_completion_response_logs_reasoning_and_completion(self):
        from types import SimpleNamespace

        from app.api.v1.chat_endpoint_presenter import log_chat_completion_response

        logger = MagicMock()
        response = SimpleNamespace(
            metadata=SimpleNamespace(
                reasoning_trace=SimpleNamespace(total_steps=4),
                thinking="abc",
            )
        )
        internal_response = SimpleNamespace(
            agent_type=SimpleNamespace(value="rag"),
        )

        log_chat_completion_response(
            logger=logger,
            response=response,
            internal_response=internal_response,
            processing_time=1.5,
        )

        assert logger.info.call_count == 3

    def test_build_chat_completion_success_response_builds_and_logs(self):
        from types import SimpleNamespace

        from app.api.v1.chat_endpoint_presenter import (
            build_chat_completion_success_response,
        )

        logger = MagicMock()
        chat_request = SimpleNamespace(message="Hello", user_id="user-1")
        internal_response = SimpleNamespace(
            message="World",
            agent_type=SimpleNamespace(value="rag"),
            sources=[],
            metadata={
                "reasoning_trace": {
                    "steps": [
                        {
                            "step_name": "direct_response",
                            "result": "Fallback (LLM generation error)",
                            "details": {"response_type": "fallback"},
                        }
                    ]
                }
            },
        )

        with patch(
            "app.api.v1.chat_endpoint_presenter.time.time",
            side_effect=[100.0],
        ), patch(
            "app.api.v1.chat_endpoint_presenter.build_chat_response",
            return_value=SimpleNamespace(
                metadata=SimpleNamespace(reasoning_trace=None, thinking=None),
            ),
        ) as mock_build, patch(
            "app.api.v1.chat_endpoint_presenter.record_llm_runtime_observation",
        ) as mock_record:
            response = build_chat_completion_success_response(
                logger=logger,
                chat_request=chat_request,
                internal_response=internal_response,
                start_time=98.5,
                provider_name="zhipu",
                model_name="gemini-test",
            )

        assert response is not None
        mock_build.assert_called_once_with(
            chat_request=chat_request,
            internal_response=internal_response,
            processing_time=1.5,
            provider_name="zhipu",
            model_name="gemini-test",
            runtime_authoritative=True,
        )
        logger.info.assert_called_once_with(
            "Chat response generated in %.3fs (agent: %s)",
            1.5,
            "rag",
        )
        mock_record.assert_called_once_with(
            provider="zhipu",
            success=True,
            model_name="gemini-test",
            note=None,
            source="chat_sync",
            failover=None,
            degraded_reason="fallback response (LLM generation error)",
        )

    def test_build_chat_completion_error_response_maps_wiii_exception(self):
        from app.api.v1.chat_endpoint_presenter import (
            build_chat_completion_error_response,
        )
        from app.core.exceptions import ChatServiceError

        logger = MagicMock()
        error = ChatServiceError(message="boom")

        response = build_chat_completion_error_response(
            logger=logger,
            error=error,
            request_id="req-1",
        )

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload["error_code"] == "CHAT_SERVICE_ERROR"
        logger.error.assert_called_once()

    def test_build_chat_completion_error_response_maps_generic_exception(self):
        from app.api.v1.chat_endpoint_presenter import (
            build_chat_completion_error_response,
        )

        logger = MagicMock()

        response = build_chat_completion_error_response(
            logger=logger,
            error=RuntimeError("boom"),
            request_id="req-2",
        )

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload["error_code"] == "INTERNAL_ERROR"
        logger.exception.assert_called_once()


class TestChatCompletionEndpointSupport:
    """Test transport support helpers for /chat service invocation."""

    def test_begin_chat_completion_request_logs_and_returns_route_metadata(self):
        from types import SimpleNamespace

        from app.api.v1.chat_completion_endpoint_support import (
            begin_chat_completion_request,
        )

        logger = MagicMock()
        request = SimpleNamespace(headers={"X-Request-ID": "req-1"})
        chat_request = SimpleNamespace(
            user_id="user-1",
            role=SimpleNamespace(value="student"),
            message="Hello world",
        )

        with patch(
            "app.api.v1.chat_completion_endpoint_support.time.time",
            return_value=42.0,
        ):
            start_time, request_id = begin_chat_completion_request(
                logger=logger,
                request=request,
                chat_request=chat_request,
                auth_method="api_key",
            )

        assert start_time == 42.0
        assert request_id == "req-1"
        logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_chat_completion_request_uses_chat_service(self):
        from app.api.v1.chat_completion_endpoint_support import (
            process_chat_completion_request,
        )

        chat_request = MagicMock()
        chat_request.provider = None
        background_save = MagicMock()
        mock_chat_service = MagicMock()
        mock_chat_service.process_message = AsyncMock(return_value="response")

        with patch(
            "app.services.chat_service.get_chat_service",
            return_value=mock_chat_service,
        ):
            result = await process_chat_completion_request(
                chat_request=chat_request,
                background_save=background_save,
            )

        assert result == "response"
        mock_chat_service.process_message.assert_awaited_once_with(
            chat_request,
            background_save=background_save,
        )


class TestChatContextEndpointSupport:
    """Test context endpoint service-wiring helpers."""

    def test_get_context_session_id_reads_standard_header(self):
        from types import SimpleNamespace

        from app.api.v1.chat_context_endpoint_support import get_context_session_id

        request = SimpleNamespace(headers={"X-Session-ID": "session-1"})

        assert get_context_session_id(request=request) == "session-1"

    def test_resolve_context_session_request_returns_missing_response(self):
        from types import SimpleNamespace

        from app.api.v1.chat_context_endpoint_support import (
            resolve_context_session_request,
        )

        request = SimpleNamespace(headers={})

        session_id, response = resolve_context_session_request(request=request)

        assert session_id == ""
        assert response is not None
        assert response.status_code == 400

    def test_resolve_context_session_request_returns_session_id(self):
        from types import SimpleNamespace

        from app.api.v1.chat_context_endpoint_support import (
            resolve_context_session_request,
        )

        request = SimpleNamespace(headers={"X-Session-ID": "session-1"})

        session_id, response = resolve_context_session_request(request=request)

        assert session_id == "session-1"
        assert response is None

    def test_build_missing_context_session_response_reuses_standard_payload(self):
        from app.api.v1.chat_context_endpoint_support import (
            build_missing_context_session_response,
        )

        response = build_missing_context_session_response()

        assert response.status_code == 400
        payload = json.loads(response.body)
        assert payload == {
            "error": "missing_session",
            "message": "X-Session-ID header required",
        }

    @pytest.mark.asyncio
    async def test_compact_context_session_loads_history_and_compacts(self):
        from app.api.v1.chat_context_endpoint_support import compact_context_session

        mock_compactor = MagicMock()
        mock_compactor.force_compact = AsyncMock(return_value="summary")
        mock_chat_history = MagicMock()
        mock_chat_history.is_available.return_value = True
        mock_chat_history.get_recent_messages.return_value = [
            MagicMock(role="user", content="hi"),
            MagicMock(role="assistant", content="hello"),
        ]

        with patch(
            "app.engine.context_manager.get_compactor",
            return_value=mock_compactor,
        ), patch(
            "app.repositories.chat_history_repository.get_chat_history_repository",
            return_value=mock_chat_history,
        ):
            summary, history_list = await compact_context_session(
                session_id="session-1",
                user_id="user-1",
                organization_id="org-1",
            )

        assert summary == "summary"
        assert history_list == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        mock_compactor.force_compact.assert_awaited_once_with(
            "session-1",
            history_list,
            user_id="user-1",
        )
        mock_chat_history.get_recent_messages.assert_called_once_with(
            "session-1",
            user_id="user-1",
            organization_id="org-1",
        )

    def test_load_context_info_inputs_returns_compactor_and_history(self):
        from app.api.v1.chat_context_endpoint_support import load_context_info_inputs

        mock_compactor = MagicMock()
        mock_chat_history = MagicMock()
        mock_chat_history.is_available.return_value = True
        mock_chat_history.get_recent_messages.return_value = [
            MagicMock(role="user", content="hi"),
        ]

        with patch(
            "app.engine.context_manager.get_compactor",
            return_value=mock_compactor,
        ), patch(
            "app.repositories.chat_history_repository.get_chat_history_repository",
            return_value=mock_chat_history,
        ):
            compactor, history_list = load_context_info_inputs(
                session_id="session-1",
                user_id="user-1",
                organization_id="org-1",
            )

        assert compactor is mock_compactor
        assert history_list == [{"role": "user", "content": "hi"}]
        mock_chat_history.get_recent_messages.assert_called_once_with(
            "session-1",
            user_id="user-1",
            organization_id="org-1",
        )

    def test_build_context_operation_error_response_logs_and_builds_payload(self):
        from app.api.v1.chat_context_endpoint_support import (
            build_context_operation_error_response,
        )

        logger = MagicMock()

        response = build_context_operation_error_response(
            logger=logger,
            operation_label="compacting context",
            error=RuntimeError("boom"),
            error_code="compact_failed",
            message="Failed to compact context",
        )

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload == {
            "error": "compact_failed",
            "message": "Failed to compact context",
        }
        logger.exception.assert_called_once()

    def test_clear_context_session_clears_both_compactor_and_summarizer(self):
        from app.api.v1.chat_context_endpoint_support import clear_context_session

        mock_compactor = MagicMock()
        mock_summarizer = MagicMock()

        with patch(
            "app.engine.context_manager.get_compactor",
            return_value=mock_compactor,
        ), patch(
            "app.engine.memory_summarizer.get_memory_summarizer",
            return_value=mock_summarizer,
        ):
            clear_context_session(
                session_id="session-1",
                user_id="user-1",
            )

        mock_compactor.clear_session.assert_called_once_with(
            "session-1",
            user_id="user-1",
        )
        mock_summarizer.clear_session.assert_called_once_with("session-1")


class TestChatHistoryEndpointSupport:
    """Test transport helpers for history-specific auth and repo access."""

    def test_ensure_chat_history_access_allowed_denies_other_user(self):
        from app.api.v1.chat_history_endpoint_support import (
            ensure_chat_history_access_allowed,
        )

        auth = MagicMock(role="student", user_id="user-1")

        response = ensure_chat_history_access_allowed(
            auth=auth,
            user_id="user-2",
        )

        assert response is not None
        assert response.status_code == 403
        payload = json.loads(response.body)
        assert payload["error"] == "permission_denied"

    def test_ensure_delete_chat_history_allowed_allows_own_history_even_with_unknown_role(self):
        from app.api.v1.chat_history_endpoint_support import (
            ensure_delete_chat_history_allowed,
        )

        auth = MagicMock(role="guest", user_id="user-1")

        response = ensure_delete_chat_history_allowed(
            auth=auth,
            user_id="user-1",
        )

        assert response is None

    def test_build_chat_history_operation_error_response_logs_and_builds_payload(self):
        from app.api.v1.chat_history_endpoint_support import (
            build_chat_history_operation_error_response,
        )

        logger = MagicMock()

        response = build_chat_history_operation_error_response(
            logger=logger,
            operation_label="retrieving chat history",
            error=RuntimeError("boom"),
            message="Failed to retrieve chat history",
        )

        assert response.status_code == 500
        payload = json.loads(response.body)
        assert payload == {
            "error": "internal_error",
            "message": "Failed to retrieve chat history",
        }
        logger.exception.assert_called_once()

    def test_load_chat_history_page_uses_repository(self):
        from app.api.v1.chat_history_endpoint_support import load_chat_history_page

        mock_repo = MagicMock()
        mock_repo.get_user_history.return_value = ([], 0)

        with patch(
            "app.repositories.chat_history_repository."
            "get_chat_history_repository",
            return_value=mock_repo,
        ):
            result = load_chat_history_page(
                user_id="user-1",
                limit=20,
                offset=5,
                organization_id="org-1",
            )

        assert result == ([], 0)
        mock_repo.get_user_history.assert_called_once_with(
            "user-1",
            20,
            5,
            organization_id="org-1",
        )

    def test_process_get_chat_history_request_shapes_and_logs_response(self):
        from types import SimpleNamespace

        from app.api.v1.chat_history_endpoint_support import (
            process_get_chat_history_request,
        )

        logger = MagicMock()
        mock_message = SimpleNamespace(role="user", content="hi", created_at="ts")

        with patch(
            "app.api.v1.chat_history_endpoint_support.load_chat_history_page",
            return_value=([mock_message], 1),
        ) as mock_load, patch(
            "app.api.v1.chat_history_endpoint_support._chat_endpoint_presenter"
            ".build_get_chat_history_response",
            return_value=SimpleNamespace(data=[1]),
        ) as mock_build:
            response = process_get_chat_history_request(
                logger=logger,
                user_id="user-1",
                limit=999,
                offset=-1,
                organization_id="org-1",
            )

        assert response.data == [1]
        mock_load.assert_called_once_with(
            user_id="user-1",
            limit=100,
            offset=0,
            organization_id="org-1",
        )
        mock_build.assert_called_once_with(
            messages=[mock_message],
            total=1,
            limit=100,
            offset=0,
        )
        logger.info.assert_called_once_with(
            "Retrieved %d messages for user %s (total: %d)",
            1,
            "user-1",
            1,
        )

    def test_process_delete_chat_history_request_deletes_and_logs_response(self):
        from app.api.v1.chat_history_endpoint_support import (
            process_delete_chat_history_request,
        )

        logger = MagicMock()

        with patch(
            "app.api.v1.chat_history_endpoint_support.delete_chat_history_records",
            return_value=3,
        ) as mock_delete, patch(
            "app.api.v1.chat_history_endpoint_support._chat_endpoint_presenter"
            ".build_delete_chat_history_response",
            return_value="response",
        ) as mock_build:
            response = process_delete_chat_history_request(
                logger=logger,
                user_id="user-1",
                deleted_by="admin-1",
                role="admin",
                organization_id="org-1",
            )

        assert response == "response"
        mock_delete.assert_called_once_with(
            user_id="user-1",
            organization_id="org-1",
        )
        mock_build.assert_called_once_with(
            user_id="user-1",
            deleted_count=3,
            deleted_by="admin-1",
        )
        logger.info.assert_called_once_with(
            "Deleted %d chat messages for user %s by %s (%s)",
            3,
            "user-1",
            "admin-1",
            "admin",
        )


# =============================================================================
# get_chat_history — limit/offset clamping
# =============================================================================


class TestGetChatHistory:
    """Test chat history retrieval."""

    @pytest.mark.asyncio
    async def test_limit_clamped_to_100(self):
        from app.api.v1.chat import get_chat_history

        mock_repo = MagicMock()
        mock_repo.get_user_history.return_value = ([], 0)
        mock_auth = MagicMock()
        mock_auth.user_id = "user-1"  # Match path param for ownership check
        mock_auth.organization_id = "org-1"

        # Lazy import inside function body — patch at source module
        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await get_chat_history("user-1", auth=mock_auth, limit=999, offset=0)

        # Limit should be clamped to 100
        mock_repo.get_user_history.assert_called_once_with(
            "user-1",
            100,
            0,
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_limit_below_1_set_to_20(self):
        from app.api.v1.chat import get_chat_history

        mock_repo = MagicMock()
        mock_repo.get_user_history.return_value = ([], 0)
        mock_auth = MagicMock()
        mock_auth.user_id = "user-1"  # Match path param for ownership check
        mock_auth.organization_id = "org-1"

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await get_chat_history("user-1", auth=mock_auth, limit=-5, offset=0)

        mock_repo.get_user_history.assert_called_once_with(
            "user-1",
            20,
            0,
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_negative_offset_set_to_zero(self):
        from app.api.v1.chat import get_chat_history

        mock_repo = MagicMock()
        mock_repo.get_user_history.return_value = ([], 0)
        mock_auth = MagicMock()
        mock_auth.user_id = "user-1"  # Match path param for ownership check
        mock_auth.organization_id = "org-1"

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await get_chat_history("user-1", auth=mock_auth, limit=10, offset=-1)

        mock_repo.get_user_history.assert_called_once_with(
            "user-1",
            10,
            0,
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_returns_messages(self):
        from app.api.v1.chat import get_chat_history
        from datetime import datetime, timezone

        mock_msg = MagicMock()
        mock_msg.role = "user"
        mock_msg.content = "Hello"
        mock_msg.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        mock_repo = MagicMock()
        mock_repo.get_user_history.return_value = ([mock_msg], 1)
        mock_auth = MagicMock()
        mock_auth.user_id = "user-1"  # Match path param for ownership check
        mock_auth.organization_id = "org-1"

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await get_chat_history("user-1", auth=mock_auth, limit=20, offset=0)

        assert len(result.data) == 1
        assert result.pagination.total == 1

    @pytest.mark.asyncio
    async def test_auth_param_exists(self):
        import inspect
        from app.api.v1.chat import get_chat_history
        sig = inspect.signature(get_chat_history)
        assert "auth" in sig.parameters


# =============================================================================
# delete_chat_history — access control
# =============================================================================


class TestDeleteChatHistory:
    """Test chat history deletion with role-based access."""

    @pytest.mark.asyncio
    async def test_admin_can_delete_any(self):
        from app.api.v1.chat import delete_chat_history

        mock_auth = MagicMock()
        mock_auth.role = "admin"
        mock_auth.user_id = "admin-1"
        mock_auth.organization_id = "org-1"

        mock_request = MagicMock()
        mock_request.requesting_user_id = "admin-1"
        mock_request.role = "admin"

        mock_repo = MagicMock()
        mock_repo.delete_user_history.return_value = 5

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await delete_chat_history("user-2", mock_request, auth=mock_auth)

        assert result.status == "deleted"
        assert result.messages_deleted == 5
        mock_repo.delete_user_history.assert_called_once_with(
            "user-2",
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_student_cannot_delete_others(self):
        from app.api.v1.chat import delete_chat_history

        mock_auth = MagicMock()
        mock_auth.role = "student"
        mock_auth.user_id = "user-1"
        mock_auth.organization_id = "org-1"

        mock_request = MagicMock()
        mock_request.requesting_user_id = "user-1"
        mock_request.role = "student"

        result = await delete_chat_history("user-2", mock_request, auth=mock_auth)

        # Should return 403 JSONResponse
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_student_can_delete_own(self):
        from app.api.v1.chat import delete_chat_history

        mock_auth = MagicMock()
        mock_auth.role = "student"
        mock_auth.user_id = "user-1"
        mock_auth.organization_id = "org-1"

        mock_request = MagicMock()
        mock_request.requesting_user_id = "user-1"
        mock_request.role = "student"

        mock_repo = MagicMock()
        mock_repo.delete_user_history.return_value = 3

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await delete_chat_history("user-1", mock_request, auth=mock_auth)

        assert result.status == "deleted"
        mock_repo.delete_user_history.assert_called_once_with(
            "user-1",
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_unknown_role_can_delete_own_history(self):
        from app.api.v1.chat import delete_chat_history

        mock_auth = MagicMock()
        mock_auth.role = "unknown"
        mock_auth.user_id = "user-1"
        mock_auth.organization_id = "org-1"

        mock_request = MagicMock()
        mock_repo = MagicMock()
        mock_repo.delete_user_history.return_value = 2

        with patch("app.repositories.chat_history_repository.get_chat_history_repository", return_value=mock_repo):
            result = await delete_chat_history("user-1", mock_request, auth=mock_auth)
        assert result.status == "deleted"
        mock_repo.delete_user_history.assert_called_once_with(
            "user-1",
            organization_id="org-1",
        )

    @pytest.mark.asyncio
    async def test_auth_param_exists(self):
        import inspect
        from app.api.v1.chat import delete_chat_history
        sig = inspect.signature(delete_chat_history)
        assert "auth" in sig.parameters
