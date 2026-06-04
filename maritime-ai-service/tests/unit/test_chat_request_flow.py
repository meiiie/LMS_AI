"""Tests for the shared sync/stream request preparation helpers."""

import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import UserRole
from app.engine.multi_agent.runtime_contracts import WiiiTurnRequest, WiiiTurnResult
from app.services.background_tasks import BackgroundTaskScheduleSummary
from app.services.chat_orchestrator import ChatOrchestrator, RequestScope
from app.services.input_processor import ChatContext


def _make_orchestrator() -> ChatOrchestrator:
    chat_history = MagicMock()
    chat_history.is_available.return_value = True
    background_runner = MagicMock()
    background_runner._semantic_memory.is_available.return_value = True
    background_runner.schedule_non_semantic_tasks.return_value = (
        BackgroundTaskScheduleSummary(task_count=0, groups=())
    )
    return ChatOrchestrator(
        session_manager=MagicMock(),
        input_processor=MagicMock(),
        output_processor=MagicMock(),
        background_runner=background_runner,
        chat_history=chat_history,
    )


def _make_request(**overrides):
    base = {
        "user_id": "user-1",
        "message": "Explain COLREG Rule 5",
        "role": UserRole.STUDENT,
        "thread_id": None,
        "session_id": None,
        "organization_id": None,
        "domain_id": None,
        "model": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_session(total_responses: int = 0):
    return SimpleNamespace(
        user_name=None,
        state=SimpleNamespace(
            is_first_message=False,
            pronoun_style=None,
            update_pronoun_style=MagicMock(),
            update_response_language=MagicMock(),
            total_responses=total_responses,
            name_usage_count=2,
            recent_phrases=["xin chao"],
        )
    )


def _make_chat_context() -> ChatContext:
    context = ChatContext(
        user_id="user-1",
        session_id=uuid4(),
        message="Explain COLREG Rule 5",
        user_role=UserRole.STUDENT,
        user_name="Minh",
        lms_course_name="COLREGs",
        lms_module_id="module-1",
        conversation_history="User asked about lookout.",
        semantic_context="Rule 5 requires proper lookout.",
        conversation_summary="Earlier discussion about lookout duties.",
        core_memory_block="Learner prefers examples.",
        mood_hint="curious",
        organization_id="org-1",
    )
    context.history_list = [{"role": "user", "content": "Hi"}]
    context.history_retrieval_summary = {
        "schema_version": "wiii.chat_history_retrieval.v1",
        "status": "ready",
        "source": "persisted_chat_history",
        "selected_history_item_count": 1,
        "raw_content_included": False,
    }
    context.context_budget_summary = {
        "schema_version": "wiii.context_budget.v1",
        "status": "ready",
        "utilization": 0.25,
        "messages_dropped": 0,
        "raw_content_included": False,
    }
    context.page_context = {"page_type": "lesson"}
    context.student_state = {"scroll_percent": 42}
    context.available_actions = [{"action": "navigate", "label": "Next"}]
    context.host_context = {"host_type": "lms"}
    context.visual_context = {
        "last_visual_session_id": "vs-comparison-keep",
        "last_visual_type": "comparison",
        "last_visual_title": "Softmax vs Linear",
        "active_inline_visuals": [
            {
                "visual_session_id": "vs-comparison-keep",
                "type": "comparison",
                "title": "Softmax vs Linear",
            }
        ],
    }
    context.widget_feedback = {
        "latest_results": [
            {
                "widget_id": "quiz-1",
                "widget_kind": "quiz",
                "status": "complete",
                "summary": "Sai 2 cau ve COLREG Rule 15",
            }
        ]
    }
    context.code_studio_context = {
        "requested_view": "code",
        "active_session": {
            "session_id": "vs-pendulum-1",
            "title": "Mo phong Con lac",
            "status": "complete",
            "active_version": 2,
            "version_count": 2,
            "language": "html",
            "studio_lane": "app",
            "artifact_kind": "html_app",
            "quality_profile": "premium",
            "renderer_contract": "host_shell",
            "has_preview": True,
        }
    }
    context.images = [SimpleNamespace(model_dump=lambda: {"kind": "image"})]
    return context


def test_normalize_thread_id_prefers_thread_id():
    request = _make_request(thread_id="thread-1", session_id="session-1")

    assert ChatOrchestrator.normalize_thread_id(request) == "thread-1"


def test_normalize_thread_id_falls_back_to_session_id():
    request = _make_request(thread_id=None, session_id="session-1")

    assert ChatOrchestrator.normalize_thread_id(request) == "session-1"


def test_normalize_thread_id_treats_new_as_none():
    request = _make_request(thread_id="new", session_id="session-1")

    assert ChatOrchestrator.normalize_thread_id(request) == "session-1"


def test_sync_fast_chatter_handles_unicode_hunger_without_llm():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    context.message = "\u0111\u00f3i ph\u1ebft"
    context.images = None

    result = orchestrator._build_sync_fast_chatter_result(context)

    assert result is not None
    assert result.agent_type.value == "direct"
    assert "\u0110\u00f3i ph\u1ebft" in result.message
    assert result.metadata["provider"] == "deterministic"
    assert result.metadata["routing_metadata"] == {
        "method": "sync_fast_chatter",
        "intent": "social",
        "shape": "hunger_chatter",
        "reason": "obvious_short_social_turn_without_tool_context",
    }


def test_sync_fast_chatter_handles_plain_greeting_without_llm():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    context.message = "chao"
    context.images = None

    result = orchestrator._build_sync_fast_chatter_result(context)

    assert result is not None
    assert "Ch\u00e0o c\u1eadu" in result.message
    assert result.metadata["routing_metadata"]["shape"] == "social"


def test_sync_fast_chatter_does_not_bypass_document_context():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    context.message = "chao"
    context.images = None
    context.document_context = {"file_name": "manual.docx"}

    assert orchestrator._build_sync_fast_chatter_result(context) is None


@pytest.mark.asyncio
async def test_process_uses_sync_fast_chatter_before_multi_agent():
    orchestrator = _make_orchestrator()
    request = _make_request(message="\u0111\u00f3i ph\u1ebft")
    context = _make_chat_context()
    context.message = request.message
    context.images = None
    session = _make_session()
    session.session_id = context.session_id
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope(organization_id="org-1", domain_id="maritime"),
        session=session,
        session_id=context.session_id,
        validation=SimpleNamespace(blocked=False, blocked_response=None),
        chat_context=context,
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator._process_with_multi_agent = AsyncMock(
        side_effect=AssertionError("multi-agent should not run for fast chatter")
    )
    orchestrator._output_processor.validate_and_format = AsyncMock(
        side_effect=lambda *, result, session_id, user_name, user_role: SimpleNamespace(
            message=result.message,
            metadata=result.metadata,
            agent_type=result.agent_type,
            sources=result.sources,
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value={
            "schema_version": "wiii.post_turn_lifecycle.v1",
            "status": "scheduled",
            "reason": "post_turn_background_tasks_scheduled",
            "semantic_memory_policy": "extract_facts",
            "background_tasks_scheduled": True,
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        }
    )

    response = await orchestrator.process(request)

    assert "\u0110\u00f3i ph\u1ebft" in response.message
    assert response.metadata["routing_metadata"]["method"] == "sync_fast_chatter"
    assert response.metadata["post_turn_lifecycle"]["schema_version"] == (
        "wiii.post_turn_lifecycle.v1"
    )
    orchestrator._process_with_multi_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_request_scope_uses_request_and_router():
    orchestrator = _make_orchestrator()
    request = _make_request(organization_id="org-explicit", domain_id="maritime")
    domain_router = MagicMock()
    domain_router.resolve = AsyncMock(return_value="traffic_law")

    with patch(
        "app.core.org_context.get_current_org_id",
        return_value="org-context",
    ), patch(
        "app.core.org_context.get_current_org_allowed_domains",
        return_value=["maritime", "traffic_law"],
    ), patch(
        "app.domains.router.get_domain_router",
        return_value=domain_router,
    ):
        scope = await orchestrator.resolve_request_scope(request)

    assert scope == RequestScope(
        organization_id="org-explicit",
        domain_id="traffic_law",
    )
    domain_router.resolve.assert_awaited_once_with(
        query="Explain COLREG Rule 5",
        explicit_domain_id="maritime",
        allowed_domains=["maritime", "traffic_law"],
    )


@pytest.mark.asyncio
async def test_resolve_request_scope_blocks_default_org_in_production_multi_tenant(monkeypatch):
    from app.core.config import settings

    orchestrator = _make_orchestrator()
    request = _make_request(organization_id=None, domain_id="maritime")
    domain_router = MagicMock()

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")

    with patch(
        "app.core.org_context.get_current_org_id",
        return_value=None,
    ), patch(
        "app.core.org_context.get_current_org_allowed_domains",
        return_value=["maritime"],
    ), patch(
        "app.domains.router.get_domain_router",
        return_value=domain_router,
    ):
        with pytest.raises(Exception) as exc_info:
            await orchestrator.resolve_request_scope(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Organization context required for chat request scope"
    domain_router.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_request_scope_allows_default_org_outside_prod_multi_tenant(monkeypatch):
    from app.core.config import settings

    orchestrator = _make_orchestrator()
    request = _make_request(organization_id=None, domain_id="maritime")
    domain_router = MagicMock()
    domain_router.resolve = AsyncMock(return_value="maritime")

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "default_organization_id", "default")

    with patch(
        "app.core.org_context.get_current_org_id",
        return_value=None,
    ), patch(
        "app.core.org_context.get_current_org_allowed_domains",
        return_value=["maritime"],
    ), patch(
        "app.domains.router.get_domain_router",
        return_value=domain_router,
    ):
        scope = await orchestrator.resolve_request_scope(request)

    assert scope == RequestScope(
        organization_id="default",
        domain_id="maritime",
    )


@pytest.mark.asyncio
async def test_build_multi_agent_context_uses_shared_contract_fields():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session(total_responses=7)

    with patch.object(
        orchestrator,
        "resolve_lms_identity",
        new=AsyncMock(return_value=("lms-user-1", "maritime-lms")),
    ):
        multi_agent_context = await orchestrator.build_multi_agent_context(
            context,
            session,
        )

    assert multi_agent_context["user_name"] == "Minh"
    assert multi_agent_context["user_role"] == UserRole.STUDENT.value
    assert multi_agent_context["organization_id"] == "org-1"
    assert multi_agent_context["conversation_phase"] == "deep"
    assert multi_agent_context["total_responses"] == 7
    assert multi_agent_context["core_memory_block"] == "Learner prefers examples."
    assert multi_agent_context["history_list"] == [{"role": "user", "content": "Hi"}]
    assert multi_agent_context["history_retrieval_summary"]["status"] == "ready"
    assert multi_agent_context["context_budget_summary"]["utilization"] == 0.25
    assert multi_agent_context["user_facts"] == []
    assert multi_agent_context["lms_external_id"] == "lms-user-1"
    assert multi_agent_context["lms_connector_id"] == "maritime-lms"
    assert multi_agent_context["page_context"] == {"page_type": "lesson"}
    assert multi_agent_context["student_state"] == {"scroll_percent": 42}
    assert multi_agent_context["available_actions"] == [
        {"action": "navigate", "label": "Next"}
    ]
    assert multi_agent_context["host_context"] == {"host_type": "lms"}
    assert multi_agent_context["visual_context"] == {
        "last_visual_session_id": "vs-comparison-keep",
        "last_visual_type": "comparison",
        "last_visual_title": "Softmax vs Linear",
        "active_inline_visuals": [
            {
                "visual_session_id": "vs-comparison-keep",
                "type": "comparison",
                "title": "Softmax vs Linear",
            }
        ],
    }
    assert multi_agent_context["widget_feedback"] == {
        "latest_results": [
            {
                "widget_id": "quiz-1",
                "widget_kind": "quiz",
                "status": "complete",
                "summary": "Sai 2 cau ve COLREG Rule 15",
            }
        ]
    }
    assert multi_agent_context["code_studio_context"] == {
        "requested_view": "code",
        "active_session": {
            "session_id": "vs-pendulum-1",
            "title": "Mo phong Con lac",
            "status": "complete",
            "active_version": 2,
            "version_count": 2,
            "language": "html",
            "studio_lane": "app",
            "artifact_kind": "html_app",
            "quality_profile": "premium",
            "renderer_contract": "host_shell",
            "has_preview": True,
        }
    }
    assert multi_agent_context["images"] == [{"kind": "image"}]
    assert multi_agent_context["is_follow_up"] is True


@pytest.mark.asyncio
async def test_build_multi_agent_context_does_not_mark_first_turn_as_follow_up():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session(total_responses=0)

    with patch.object(
        orchestrator,
        "resolve_lms_identity",
        new=AsyncMock(return_value=("lms-user-1", "maritime-lms")),
    ):
        multi_agent_context = await orchestrator.build_multi_agent_context(
            context,
            session,
        )

    assert context.history_list  # current request may already be in history
    assert multi_agent_context["is_follow_up"] is False
    assert multi_agent_context["conversation_phase"] == "opening"


@pytest.mark.asyncio
async def test_build_multi_agent_context_normalizes_missing_user_facts():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    context.user_facts = None
    session = _make_session(total_responses=1)

    with patch.object(
        orchestrator,
        "resolve_lms_identity",
        new=AsyncMock(return_value=("lms-user-1", "maritime-lms")),
    ):
        multi_agent_context = await orchestrator.build_multi_agent_context(
            context,
            session,
        )

    assert multi_agent_context["user_facts"] == []


@pytest.mark.asyncio
async def test_build_multi_agent_execution_input_for_streaming_adds_transport_fields():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session(total_responses=2)
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session=session,
        session_id="session-1",
        chat_context=context,
    )
    request = _make_request(
        show_previews=True,
        preview_types=["tool", "product"],
        preview_max_count=3,
        model="qwen/qwen3.6-plus:free",
    )

    with patch.object(
        orchestrator,
        "resolve_lms_identity",
        new=AsyncMock(return_value=("lms-user-1", "maritime-lms")),
    ):
        execution_input = await orchestrator.build_multi_agent_execution_input(
            request=request,
            prepared_turn=prepared_turn,
            include_streaming_fields=True,
            thinking_effort="high",
            request_id="req-stream-123",
        )

    assert execution_input.query == "Explain COLREG Rule 5"
    assert execution_input.user_id == "user-1"
    assert execution_input.session_id == "session-1"
    assert execution_input.domain_id == "maritime"
    assert execution_input.thinking_effort == "high"
    assert execution_input.model == "qwen/qwen3.6-plus:free"
    assert execution_input.context["user_facts"] == []
    assert execution_input.context["history_list"] == [{"role": "user", "content": "Hi"}]
    assert execution_input.context["show_previews"] is True
    assert execution_input.context["preview_types"] == ["tool", "product"]
    assert execution_input.context["preview_max_count"] == 3
    assert execution_input.context["request_id"] == "req-stream-123"


@pytest.mark.asyncio
async def test_build_multi_agent_execution_input_keeps_memory_contract_for_sync():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session(total_responses=2)
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session=session,
        session_id="session-1",
        chat_context=context,
    )
    request = _make_request()

    with patch.object(
        orchestrator,
        "resolve_lms_identity",
        new=AsyncMock(return_value=("lms-user-1", "maritime-lms")),
    ):
        execution_input = await orchestrator.build_multi_agent_execution_input(
            request=request,
            prepared_turn=prepared_turn,
            include_streaming_fields=False,
        )

    assert execution_input.context["core_memory_block"] == "Learner prefers examples."
    assert execution_input.context["history_list"] == [{"role": "user", "content": "Hi"}]
    assert execution_input.context["user_facts"] == []


def test_build_minimal_multi_agent_execution_input_uses_degraded_contract():
    orchestrator = _make_orchestrator()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
    )
    request = _make_request(
        organization_id="org-1",
        domain_id="maritime",
        model="qwen/qwen3.6-plus:free",
    )

    execution_input = orchestrator.build_minimal_multi_agent_execution_input(
        request=request,
        prepared_turn=prepared_turn,
        thinking_effort="low",
        request_id="req-minimal-123",
    )

    assert execution_input.query == "Explain COLREG Rule 5"
    assert execution_input.user_id == "user-1"
    assert execution_input.session_id == "session-1"
    assert execution_input.domain_id == "maritime"
    assert execution_input.thinking_effort == "low"
    assert execution_input.model == "qwen/qwen3.6-plus:free"
    assert execution_input.context == {
        "user_id": "user-1",
        "user_role": UserRole.STUDENT.value,
        "user_name": None,
        "conversation_history": "",
        "organization_id": "org-1",
        "response_language": "vi",
        "request_id": "req-minimal-123",
    }


def test_persist_chat_message_passes_user_id_immediately():
    orchestrator = _make_orchestrator()

    orchestrator.persist_chat_message(
        session_id="session-1",
        role="user",
        content="hello",
        user_id="user-1",
        organization_id="org-1",
        immediate=True,
    )

    orchestrator._chat_history.save_message.assert_called_once_with(
        "session-1",
        "user",
        "hello",
        "user-1",
        organization_id="org-1",
    )


def test_persist_chat_message_passes_user_id_to_background_save():
    orchestrator = _make_orchestrator()
    background_save = MagicMock()

    orchestrator.persist_chat_message(
        session_id="session-1",
        role="assistant",
        content="hi",
        user_id="user-1",
        organization_id="org-1",
        background_save=background_save,
    )

    background_save.assert_any_call(
        orchestrator._chat_history.save_message,
        "session-1",
        "assistant",
        "hi",
        "user-1",
        organization_id="org-1",
    )


@pytest.mark.asyncio
async def test_prepare_turn_builds_shared_session_and_context_contract():
    orchestrator = _make_orchestrator()
    request = _make_request()
    session = _make_session()
    session.state.is_first_message = True
    session.session_id = "session-1"
    chat_context = _make_chat_context()
    recent_history_fallback = [
        {"role": "user", "content": "Giải thích Quy tắc 15 COLREGs"},
        {"role": "assistant", "content": "Để mình giải thích rõ nhé."},
    ]

    orchestrator._session_manager.get_or_create_session.return_value = session
    orchestrator._session_manager.get_recent_messages.return_value = recent_history_fallback
    orchestrator._input_processor.build_context = AsyncMock(return_value=chat_context)
    orchestrator._input_processor.extract_user_name.return_value = "Minh"
    orchestrator._input_processor.validate_pronoun_request = AsyncMock(return_value=None)

    with patch.object(
        orchestrator,
        "resolve_request_scope",
        new=AsyncMock(return_value=RequestScope("org-1", "maritime")),
    ), patch.object(
        orchestrator,
        "validate_request",
        new=AsyncMock(return_value=SimpleNamespace(blocked=False)),
    ), patch.object(
        orchestrator,
        "_maybe_summarize_previous_session",
    ) as mock_summarize, patch.object(
        orchestrator,
        "_load_pronoun_style_from_facts",
    ) as mock_load_pronoun, patch.object(
        orchestrator,
        "persist_chat_message",
    ) as mock_persist_message, patch(
        "app.prompts.prompt_loader.detect_pronoun_style",
        return_value={"user": "mình", "assistant": "bạn"},
    ):
        prepared_turn = await orchestrator.prepare_turn(
            request=request,
            background_save=MagicMock(),
            persist_user_message_immediately=True,
        )

    assert prepared_turn.request_scope == RequestScope("org-1", "maritime")
    assert prepared_turn.session is session
    assert prepared_turn.session_id == "session-1"
    assert prepared_turn.chat_context is chat_context
    assert chat_context.organization_id == "org-1"
    orchestrator._session_manager.get_or_create_session.assert_called_once_with(
        "user-1",
        None,
        organization_id="org-1",
    )
    mock_summarize.assert_called_once()
    assert mock_summarize.call_args.args[1:] == ("user-1", "org-1")
    mock_load_pronoun.assert_called_once_with(session, "user-1")
    mock_persist_message.assert_called_once_with(
        session_id="session-1",
        role="user",
        content="Explain COLREG Rule 5",
        user_id="user-1",
        organization_id="org-1",
        background_save=mock_persist_message.call_args.kwargs["background_save"],
        immediate=True,
    )
    orchestrator._session_manager.append_message.assert_called_once_with(
        session_id="session-1",
        role="user",
        content="Explain COLREG Rule 5",
        organization_id="org-1",
    )
    orchestrator._input_processor.build_context.assert_awaited_once_with(
        request=request,
        session_id="session-1",
        user_name=session.user_name,
        recent_history_fallback=recent_history_fallback,
    )
    orchestrator._session_manager.get_recent_messages.assert_called_once_with(
        "session-1",
        organization_id="org-1",
    )
    orchestrator._session_manager.update_user_name.assert_called_once_with(
        "session-1",
        "Minh",
        organization_id="org-1",
    )
    session.state.update_pronoun_style.assert_called_once_with(
        {"user": "mình", "assistant": "bạn"}
    )


@pytest.mark.asyncio
async def test_prepare_turn_returns_early_when_validation_blocks():
    orchestrator = _make_orchestrator()
    request = _make_request()
    session = _make_session()
    session.session_id = "session-1"
    validation = SimpleNamespace(blocked=True, blocked_response=MagicMock())

    orchestrator._session_manager.get_or_create_session.return_value = session

    with patch.object(
        orchestrator,
        "resolve_request_scope",
        new=AsyncMock(return_value=RequestScope("org-1", "maritime")),
    ), patch.object(
        orchestrator,
        "validate_request",
        new=AsyncMock(return_value=validation),
    ), patch.object(
        orchestrator,
        "persist_chat_message",
    ) as mock_persist_message:
        prepared_turn = await orchestrator.prepare_turn(request=request)

    assert prepared_turn.validation is validation
    assert prepared_turn.chat_context is None
    mock_persist_message.assert_not_called()


@pytest.mark.asyncio
async def test_validate_request_delegates_to_input_processor_with_blocked_factory():
    orchestrator = _make_orchestrator()
    request = _make_request()
    validation_result = SimpleNamespace(blocked=False)
    orchestrator._input_processor.validate = AsyncMock(return_value=validation_result)
    blocked_factory = MagicMock()
    orchestrator._output_processor.create_blocked_response = blocked_factory

    result = await orchestrator.validate_request(request, "session-1")

    assert result is validation_result
    orchestrator._input_processor.validate.assert_awaited_once_with(
        request=request,
        session_id="session-1",
        create_blocked_response=blocked_factory,
    )


def test_finalize_response_turn_runs_authoritative_post_response_contract():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    background_save = MagicMock()

    with patch.object(
        orchestrator,
        "upsert_thread_view",
    ) as mock_upsert, patch(
        "app.services.chat_orchestrator.schedule_post_response_continuity",
        return_value=("routine_tracking", "lms_insights"),
    ) as mock_schedule_continuity, patch(
        "app.services.chat_orchestrator.logger",
    ) as mock_logger:
        lifecycle_summary = orchestrator.finalize_response_turn(
            session_id="session-1",
            user_id="user-1",
            user_role=UserRole.STUDENT,
            message="Explain COLREG Rule 5",
            response_text="Minh, Rule 5 requires proper lookout.",
            context=context,
            domain_id="maritime",
            organization_id="org-1",
            current_agent="memory_agent",
            background_save=background_save,
            request_id="req-finalize-1",
        )

    orchestrator._session_manager.update_state.assert_called_once_with(
        session_id="session-1",
        phrase="Minh, Rule 5 requires proper lookout.",
        used_name=True,
        organization_id="org-1",
    )
    orchestrator._session_manager.append_message.assert_called_once_with(
        session_id="session-1",
        role="assistant",
        content="Minh, Rule 5 requires proper lookout.",
        organization_id="org-1",
    )
    background_save.assert_any_call(
        orchestrator._chat_history.save_message,
        "session-1",
        "assistant",
        "Minh, Rule 5 requires proper lookout.",
        "user-1",
        organization_id="org-1",
    )
    assert background_save.call_args_list[1].args == (
        orchestrator._background_runner._store_semantic_interaction,
        "user-1",
        "Explain COLREG Rule 5",
        "Minh, Rule 5 requires proper lookout.",
        "session-1",
        True,
        "org-1",
    )
    assert background_save.call_args_list[2].args == (
        orchestrator._background_runner._enqueue_or_run_semantic_memory_maintenance,
        "user-1",
        "session-1",
        "org-1",
    )
    mock_upsert.assert_called_once_with(
        user_id="user-1",
        session_id="session-1",
        domain_id="maritime",
        title="Explain COLREG Rule 5",
        organization_id="org-1",
    )
    orchestrator._background_runner.schedule_non_semantic_tasks.assert_called_once_with(
        background_save=background_save,
        user_id="user-1",
        session_id="session-1",
        message="Explain COLREG Rule 5",
        response="Minh, Rule 5 requires proper lookout.",
        org_id="org-1",
    )
    continuity_context = mock_schedule_continuity.call_args.args[0]
    assert continuity_context.user_id == "user-1"
    assert continuity_context.request_id == "req-finalize-1"
    assert continuity_context.response_text == "Minh, Rule 5 requires proper lookout."
    assert mock_schedule_continuity.call_args.kwargs == {"include_lms_insights": True}
    mock_logger.info.assert_called_once()
    log_payload = json.loads(mock_logger.info.call_args.args[1])
    assert lifecycle_summary == {
        "background_tasks_scheduled": True,
        "background_schedule": {
            "groups": [
                {
                    "group": "semantic_memory_interaction",
                    "reason": "skip_fact_extraction",
                    "status": "scheduled",
                },
                {
                    "group": "semantic_memory_maintenance",
                    "reason": "after_interaction_write",
                    "status": "scheduled",
                },
            ],
            "privacy": {
                "identifier_strategy": "status_only",
                "raw_content_included": False,
            },
            "schema_version": "wiii.background_task_schedule.v1",
            "task_count": 2,
        },
        "privacy": {
            "identifier_strategy": "status_only",
            "raw_content_included": False,
        },
        "reason": "post_turn_background_tasks_scheduled",
        "schema_version": "wiii.post_turn_lifecycle.v1",
        "semantic_memory_policy": "skip_fact_extraction",
        "status": "scheduled",
    }
    assert log_payload == {
        "background_tasks_scheduled": True,
        "continuity_channel": "web",
        "domain_id": "maritime",
        "include_lms_insights": True,
        "organization_id": "org-1",
        "post_turn_lifecycle": {
            "background_tasks_scheduled": True,
            "background_schedule": {
                "groups": [
                    {
                        "group": "semantic_memory_interaction",
                        "reason": "skip_fact_extraction",
                        "status": "scheduled",
                    },
                    {
                        "group": "semantic_memory_maintenance",
                        "reason": "after_interaction_write",
                        "status": "scheduled",
                    },
                ],
                "privacy": {
                    "identifier_strategy": "status_only",
                    "raw_content_included": False,
                },
                "schema_version": "wiii.background_task_schedule.v1",
                "task_count": 2,
            },
            "privacy": {
                "identifier_strategy": "status_only",
                "raw_content_included": False,
            },
            "reason": "post_turn_background_tasks_scheduled",
            "schema_version": "wiii.post_turn_lifecycle.v1",
            "semantic_memory_policy": "skip_fact_extraction",
            "status": "scheduled",
        },
        "request_id": "req-finalize-1",
        "response_persistence": "background",
        "scheduled_hooks": ["routine_tracking", "lms_insights"],
        "session_id": "session-1",
        "transport_type": "sync",
        "user_id": "user-1",
    }


def test_finalize_response_turn_can_persist_immediately_for_streaming():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()

    with patch.object(
        orchestrator,
        "upsert_thread_view",
    ), patch(
        "app.services.chat_orchestrator.schedule_post_response_continuity",
        return_value=("living_continuity",),
    ) as mock_schedule_continuity, patch(
        "app.services.chat_orchestrator.logger",
    ) as mock_logger:
        orchestrator.finalize_response_turn(
            session_id="session-1",
            user_id="user-1",
            user_role=UserRole.STUDENT,
            message="Hello",
            response_text="Streaming answer",
            context=context,
            domain_id="maritime",
            organization_id="org-1",
            background_save=MagicMock(),
            save_response_immediately=True,
            include_lms_insights=False,
            transport_type="stream",
        )

    orchestrator._chat_history.save_message.assert_called_once_with(
        "session-1",
        "assistant",
        "Streaming answer",
        "user-1",
        organization_id="org-1",
    )
    orchestrator._session_manager.append_message.assert_called_once_with(
        session_id="session-1",
        role="assistant",
        content="Streaming answer",
        organization_id="org-1",
    )
    assert mock_schedule_continuity.call_args.kwargs == {
        "include_lms_insights": False,
    }
    log_payload = json.loads(mock_logger.info.call_args.args[1])
    assert log_payload["transport_type"] == "stream"
    assert log_payload["response_persistence"] == "immediate"
    assert log_payload["scheduled_hooks"] == ["living_continuity"]


def test_finalize_response_turn_defers_completed_stream_persistence():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    background_save = MagicMock()

    with patch.object(
        orchestrator,
        "upsert_thread_view",
    ) as mock_upsert, patch(
        "app.services.chat_orchestrator.schedule_post_response_continuity",
        return_value=(),
    ), patch("app.services.chat_orchestrator.logger") as mock_logger:
        orchestrator.finalize_response_turn(
            session_id="session-1",
            user_id="user-1",
            user_role=UserRole.STUDENT,
            message="Hello",
            response_text="Streaming answer",
            context=context,
            domain_id="maritime",
            organization_id="org-1",
            background_save=background_save,
            save_response_immediately=False,
            include_lms_insights=False,
            transport_type="stream",
        )

    orchestrator._chat_history.save_message.assert_not_called()
    mock_upsert.assert_not_called()
    assert background_save.call_args_list[0].args == (
        orchestrator._chat_history.save_message,
        "session-1",
        "assistant",
        "Streaming answer",
        "user-1",
    )
    assert background_save.call_args_list[0].kwargs == {"organization_id": "org-1"}
    assert background_save.call_args_list[1].args == (mock_upsert,)
    assert background_save.call_args_list[1].kwargs == {
        "user_id": "user-1",
        "session_id": "session-1",
        "domain_id": "maritime",
        "title": "Hello",
        "organization_id": "org-1",
    }
    log_payload = json.loads(mock_logger.info.call_args.args[1])
    assert log_payload["response_persistence"] == "background"


def test_finalize_response_turn_skips_fact_extraction_for_direct_ephemeral_turns():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    background_save = MagicMock()

    with patch.object(
        orchestrator,
        "upsert_thread_view",
    ), patch(
        "app.services.chat_orchestrator.schedule_post_response_continuity",
        return_value=(),
    ) as mock_schedule_continuity, patch("app.services.chat_orchestrator.logger"):
        orchestrator.finalize_response_turn(
            session_id="session-1",
            user_id="user-1",
            user_role=UserRole.STUDENT,
            message="đói phết nữa",
            response_text="Kiếm gì dễ ăn trong 5-10 phút trước nha.",
            context=context,
            domain_id="maritime",
            organization_id="org-1",
            current_agent="direct",
            background_save=background_save,
            save_response_immediately=True,
            transport_type="stream",
        )

    orchestrator._background_runner.schedule_non_semantic_tasks.assert_not_called()
    assert mock_schedule_continuity.call_args.kwargs == {
        "include_lms_insights": False,
    }


def test_finalize_response_turn_keeps_fact_extraction_for_direct_durable_user_fact():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    background_save = MagicMock()

    with patch.object(
        orchestrator,
        "upsert_thread_view",
    ), patch(
        "app.services.chat_orchestrator.schedule_post_response_continuity",
        return_value=(),
    ), patch("app.services.chat_orchestrator.logger"):
        orchestrator.finalize_response_turn(
            session_id="session-1",
            user_id="user-1",
            user_role=UserRole.STUDENT,
            message="Mình tên là Minh.",
            response_text="Mình nhớ rồi, Minh.",
            context=context,
            domain_id="maritime",
            organization_id="org-1",
            current_agent="direct",
            background_save=background_save,
            save_response_immediately=True,
            transport_type="stream",
        )

    semantic_write_call = next(
        call
        for call in background_save.call_args_list
        if call.args[0] is orchestrator._background_runner._store_semantic_interaction
    )
    assert semantic_write_call.args[0] is (
        orchestrator._background_runner._store_semantic_interaction
    )
    assert semantic_write_call.args[1] == "user-1"
    assert semantic_write_call.args[4:] == ("session-1", False, "org-1")
    orchestrator._background_runner.schedule_non_semantic_tasks.assert_called_once()


@pytest.mark.asyncio
async def test_process_with_multi_agent_preserves_runtime_provider_metadata():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session()
    execution_input = SimpleNamespace(
        query=context.message,
        user_id=context.user_id,
        session_id=str(context.session_id),
        context={"history": []},
        domain_id="maritime",
        thinking_effort=None,
        provider="zhipu",
    )

    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=execution_input
    )

    with patch(
        "app.engine.multi_agent.graph.process_with_multi_agent",
        new=AsyncMock(
            return_value={
                "response": "He thong dang hoat dong binh thuong.",
                "sources": [],
                "tools_used": [],
                "grader_score": 0.0,
                "agent_outputs": {},
                "current_agent": "direct",
                "next_agent": "direct",
                "provider": "zhipu",
            }
        ),
    ):
        result = await orchestrator._process_with_multi_agent(
            context=context,
            session=session,
            domain_id="maritime",
            thinking_effort=None,
            provider="zhipu",
        )

    assert result.metadata["provider"] == "zhipu"
    assert str(result.metadata["model"]).startswith("glm-")


@pytest.mark.asyncio
async def test_process_with_multi_agent_uses_native_wiii_turn_request():
    orchestrator = _make_orchestrator()
    context = _make_chat_context()
    session = _make_session()
    execution_input = SimpleNamespace(
        query=context.message,
        user_id=context.user_id,
        session_id=str(context.session_id),
        context={"history": [], "organization_id": "org-1"},
        domain_id="maritime",
        thinking_effort="medium",
        provider="nvidia",
        model="deepseek-ai/deepseek-v3.1",
    )

    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=execution_input
    )

    with patch(
        "app.engine.multi_agent.runtime.run_wiii_turn",
        new=AsyncMock(
            return_value=WiiiTurnResult.from_payload(
                {
                    "response": "Native turn ok.",
                    "sources": [],
                    "tools_used": [],
                    "grader_score": 0.0,
                    "agent_outputs": {},
                    "current_agent": "direct",
                    "next_agent": "direct",
                    "provider": "nvidia",
                    "model": "deepseek-ai/deepseek-v3.1",
                    "runtime_flow_trace": {
                        "version": "wiii.runtime_flow_trace.v1",
                        "turn_path_decision": {
                            "path": "external_app_action",
                            "reason": "facebook_post_request",
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
                                    "data": {"access_token": "raw-provider-token"},
                                }
                            ],
                        },
                    },
                }
            )
        ),
    ) as run_turn:
        result = await orchestrator._process_with_multi_agent(
            context=context,
            session=session,
            domain_id="maritime",
            thinking_effort="medium",
            provider="nvidia",
            model="deepseek-ai/deepseek-v3.1",
        )

    turn_request = run_turn.await_args.args[0]
    assert isinstance(turn_request, WiiiTurnRequest)
    assert turn_request.query == "Explain COLREG Rule 5"
    assert turn_request.run_context.user_id == "user-1"
    assert turn_request.run_context.session_id == str(context.session_id)
    assert turn_request.run_context.domain_id == "maritime"
    assert turn_request.run_context.organization_id == "org-1"
    assert turn_request.run_context.thinking_effort == "medium"
    assert turn_request.run_context.provider == "nvidia"
    assert turn_request.run_context.model == "deepseek-ai/deepseek-v3.1"
    assert result.message == "Native turn ok."
    assert result.metadata["provider"] == "nvidia"
    assert (
        result.metadata["runtime_flow_trace"]["turn_path_decision"]["path"]
        == "external_app_action"
    )
    serialized_metadata = json.dumps(result.metadata, ensure_ascii=False)
    assert "raw-approval-token" not in serialized_metadata
    assert "raw-provider-token" not in serialized_metadata


@pytest.mark.asyncio
async def test_record_eval_turn_sanitizes_identity_metadata_and_tool_calls():
    from app.models.schemas import AgentType, ChatRequest, InternalChatResponse
    from app.services.output_processor import ProcessingResult

    orchestrator = _make_orchestrator()
    request = ChatRequest(
        user_id="raw-user-id",
        message="Dang bai len Facebook",
        role=UserRole.TEACHER,
    )
    response = InternalChatResponse(
        message="Da tao preview.",
        agent_type=AgentType.DIRECT,
        sources=[],
        metadata={},
    )
    result = ProcessingResult(
        message="Da tao preview.",
        agent_type=AgentType.DIRECT,
        metadata={
            "current_agent": "direct",
            "tool_calls": [
                {
                    "name": "host_action",
                    "args": {
                        "message": "hello",
                        "access_token": "raw-access-token",
                    },
                    "result": json.dumps(
                        {
                            "status": "action_completed",
                            "approval_token": "raw-approval-token",
                            "data": {
                                "provider_payload": {"id": "raw-provider"},
                                "safe_id": "post-1",
                            },
                        }
                    ),
                }
            ],
            "runtime_flow_trace": {
                "turn_path_decision": {
                    "path": "external_app_action",
                    "approval_token": "raw-approval-token",
                }
            },
        },
    )

    captured = {}

    async def fake_write(_self, record):
        captured["record"] = record

    with patch("app.engine.runtime.eval_recorder.EvalRecorder.write", new=fake_write):
        await orchestrator._record_eval_turn(
            request=request,
            response=response,
            result=result,
            session_id="session-1",
            org_id="org-1",
        )

    record = captured["record"]
    serialized = record.model_dump_json()

    assert record.response == "Da tao preview."
    assert record.request["user_id_hash"].startswith("sha256:")
    assert record.request["message"] == "Dang bai len Facebook"
    assert record.tool_calls[0]["args"]["message"] == "hello"
    assert record.tool_calls[0]["result"]["data"]["safe_id"] == "post-1"
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-approval-token" not in serialized
    assert "raw-provider" not in serialized
    assert "access_token" not in serialized
    assert "approval_token" not in serialized
    assert "provider_payload" not in serialized
