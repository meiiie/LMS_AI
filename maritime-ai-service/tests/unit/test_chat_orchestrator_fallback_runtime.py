from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_orchestrator_fallback_runtime import (
    build_fast_chatter_result_impl,
    persist_chat_message_impl,
    process_with_direct_llm_impl,
    process_without_multi_agent_impl,
    should_use_local_direct_llm_fallback_impl,
    upsert_thread_view_impl,
)


@dataclass
class FakeProcessingResult:
    message: str
    agent_type: str
    metadata: dict | None = None
    sources: list | None = None
    thinking: str | None = None


class TestPersistChatMessageImpl:
    def test_skips_empty_content(self):
        chat_history = MagicMock()

        persist_chat_message_impl(
            chat_history=chat_history,
            session_id="s1",
            role="user",
            content="",
        )

        chat_history.save_message.assert_not_called()

    def test_skips_when_history_unavailable(self):
        chat_history = MagicMock()
        chat_history.is_available.return_value = False

        persist_chat_message_impl(
            chat_history=chat_history,
            session_id="s1",
            role="assistant",
            content="hello",
        )

        chat_history.save_message.assert_not_called()

    def test_saves_immediately_when_requested(self):
        chat_history = MagicMock()
        chat_history.is_available.return_value = True
        background_save = MagicMock()

        persist_chat_message_impl(
            chat_history=chat_history,
            session_id="s1",
            role="assistant",
            content="hello",
            user_id="u1",
            background_save=background_save,
            immediate=True,
        )

        chat_history.save_message.assert_called_once_with(
            "s1",
            "assistant",
            "hello",
            "u1",
            organization_id=None,
        )
        background_save.assert_not_called()

    def test_uses_background_save_when_available(self):
        chat_history = MagicMock()
        chat_history.is_available.return_value = True
        background_save = MagicMock()

        persist_chat_message_impl(
            chat_history=chat_history,
            session_id="s1",
            role="assistant",
            content="hello",
            user_id="u1",
            background_save=background_save,
        )

        chat_history.save_message.assert_not_called()
        background_save.assert_called_once_with(
            chat_history.save_message,
            "s1",
            "assistant",
            "hello",
            "u1",
            organization_id=None,
        )


class TestUpsertThreadViewImpl:
    def test_skips_empty_title(self):
        logger_obj = MagicMock()

        upsert_thread_view_impl(
            logger_obj=logger_obj,
            user_id="u1",
            session_id="s1",
            domain_id="maritime",
            title="",
            organization_id=None,
        )

        logger_obj.warning.assert_not_called()

    def test_upserts_thread_view_when_repository_available(self):
        logger_obj = MagicMock()
        thread_repo = MagicMock()
        thread_repo.is_available.return_value = True

        with patch(
            "app.services.chat_orchestrator_fallback_runtime.get_thread_repository",
            return_value=thread_repo,
            create=True,
        ), patch(
            "app.services.chat_orchestrator_fallback_runtime.build_thread_id",
            return_value="thread-1",
            create=True,
        ):
            # Patch the import targets used inside the function body.
            with patch(
                "app.repositories.thread_repository.get_thread_repository",
                return_value=thread_repo,
            ), patch(
                "app.core.thread_utils.build_thread_id",
                return_value="thread-1",
            ):
                upsert_thread_view_impl(
                    logger_obj=logger_obj,
                    user_id="u1",
                    session_id="s1",
                    domain_id="maritime",
                    title="A" * 80,
                    organization_id="org-1",
                )

        thread_repo.upsert_thread.assert_called_once_with(
            thread_id="thread-1",
            user_id="u1",
            domain_id="maritime",
            title="A" * 50,
            message_count_increment=2,
            organization_id="org-1",
        )

    def test_logs_warning_on_upsert_error(self):
        logger_obj = MagicMock()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            side_effect=RuntimeError("boom"),
        ):
            upsert_thread_view_impl(
                logger_obj=logger_obj,
                user_id="u1",
                session_id="s1",
                domain_id="maritime",
                title="hello",
                organization_id=None,
            )

        logger_obj.warning.assert_called_once()


class TestShouldUseLocalDirectLlmFallbackImpl:
    def test_returns_true_for_local_ollama_without_google_key(self):
        settings_obj = SimpleNamespace(llm_provider="ollama", google_api_key=None)
        assert should_use_local_direct_llm_fallback_impl(settings_obj=settings_obj) is True

    def test_returns_false_for_google_provider(self):
        settings_obj = SimpleNamespace(llm_provider="google", google_api_key="key")
        assert should_use_local_direct_llm_fallback_impl(settings_obj=settings_obj) is False


class TestProcessWithDirectLlmImpl:
    @pytest.mark.asyncio
    async def test_builds_processing_result_from_direct_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="assistant text"))
        get_llm_light_fn = MagicMock(return_value=llm)
        extract_thinking = MagicMock(return_value=("Hello there", "Thinking here"))
        resolve_runtime = MagicMock(
            return_value={"provider": "google", "model": "gemini-test"}
        )
        context = SimpleNamespace(message="Hi")

        result = await process_with_direct_llm_impl(
            context=context,
            get_llm_light_fn=get_llm_light_fn,
            extract_thinking_from_response_fn=extract_thinking,
            resolve_runtime_llm_metadata_fn=resolve_runtime,
            processing_result_cls=FakeProcessingResult,
            agent_type_direct="direct",
        )

        assert result == FakeProcessingResult(
            message="Hello there",
            agent_type="direct",
            metadata={
                "mode": "local_direct_llm",
                "provider": "google",
                "model": "gemini-test",
                "_execution_provider": "google",
                "_execution_model": "gemini-test",
                "runtime_authoritative": True,
            },
            thinking="Thinking here",
        )
        llm.ainvoke.assert_awaited_once_with([{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_builds_processing_result_prefers_llm_authoritative_override(self):
        llm = MagicMock()
        llm._wiii_provider_name = "openai"
        llm.model = "gpt-4o"
        llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="assistant text"))
        get_llm_light_fn = MagicMock(return_value=llm)
        extract_thinking = MagicMock(return_value=("Hello there", None))
        resolve_runtime = MagicMock(
            return_value={
                "provider": "google",
                "model": "gemini-test",
                "_execution_provider": "zhipu",
                "_execution_model": "glm-4.5-air",
            }
        )
        context = SimpleNamespace(message="Hi")

        result = await process_with_direct_llm_impl(
            context=context,
            get_llm_light_fn=get_llm_light_fn,
            extract_thinking_from_response_fn=extract_thinking,
            resolve_runtime_llm_metadata_fn=resolve_runtime,
            processing_result_cls=FakeProcessingResult,
            agent_type_direct="direct",
        )

        assert result.metadata == {
            "mode": "local_direct_llm",
            "provider": "openai",
            "model": "gpt-4o",
            "_execution_provider": "openai",
            "_execution_model": "gpt-4o",
            "runtime_authoritative": True,
        }
        llm.ainvoke.assert_awaited_once_with([{"role": "user", "content": "Hi"}])

    @pytest.mark.asyncio
    async def test_builds_processing_result_from_execution_metadata_only(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="assistant text"))
        get_llm_light_fn = MagicMock(return_value=llm)
        extract_thinking = MagicMock(return_value=("Hello there", None))
        resolve_runtime = MagicMock(
            return_value={
                "_execution_provider": "zhipu",
                "_execution_model": "glm-4.5-air",
            }
        )
        context = SimpleNamespace(message="Hi")

        result = await process_with_direct_llm_impl(
            context=context,
            get_llm_light_fn=get_llm_light_fn,
            extract_thinking_from_response_fn=extract_thinking,
            resolve_runtime_llm_metadata_fn=resolve_runtime,
            processing_result_cls=FakeProcessingResult,
            agent_type_direct="direct",
        )

        assert result.metadata == {
            "mode": "local_direct_llm",
            "provider": "zhipu",
            "model": "glm-4.5-air",
            "_execution_provider": "zhipu",
            "_execution_model": "glm-4.5-air",
            "runtime_authoritative": True,
        }
        llm.ainvoke.assert_awaited_once_with([{"role": "user", "content": "Hi"}])


class TestProcessWithoutMultiAgentImpl:
    def test_fast_chatter_result_handles_plain_greeting_without_rag(self):
        context = SimpleNamespace(message="Xin chào Wiii")

        result = build_fast_chatter_result_impl(
            context=context,
            processing_result_cls=FakeProcessingResult,
            agent_type_direct="direct",
        )

        assert result is not None
        assert result.agent_type == "direct"
        assert "Chào" in result.message
        assert result.metadata["provider"] == "deterministic"
        assert result.metadata["routing_metadata"]["method"] == "fast_chatter"

    def test_fast_chatter_result_does_not_bypass_document_context(self):
        context = SimpleNamespace(
            message="Xin chào Wiii",
            document_context={"document_ids": ["doc-1"]},
        )

        result = build_fast_chatter_result_impl(
            context=context,
            processing_result_cls=FakeProcessingResult,
            agent_type_direct="direct",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_uses_fast_chatter_for_greeting_before_rag(self):
        logger_obj = MagicMock()
        rag_agent = MagicMock()
        rag_agent.query = AsyncMock()

        result = await process_without_multi_agent_impl(
            context=SimpleNamespace(message="Xin chào Wiii"),
            rag_agent=rag_agent,
            output_processor=MagicMock(),
            logger_obj=logger_obj,
            should_use_local_direct_llm_fallback=False,
            process_with_direct_llm_fn=AsyncMock(),
            resolve_runtime_llm_metadata_fn=MagicMock(return_value={}),
            processing_result_cls=FakeProcessingResult,
            agent_type_rag="rag",
            agent_type_direct="direct",
        )

        assert result.agent_type == "direct"
        assert result.metadata["provider"] == "deterministic"
        assert "searched for information" not in result.message.lower()
        rag_agent.query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_direct_llm_path_when_flag_enabled(self):
        logger_obj = MagicMock()
        context = SimpleNamespace(
            message="Explain COLREG Rule 5",
            user_role=SimpleNamespace(value="student"),
        )
        process_with_direct_llm_fn = AsyncMock(return_value=FakeProcessingResult("hello", "direct"))

        result = await process_without_multi_agent_impl(
            context=context,
            rag_agent=None,
            output_processor=MagicMock(),
            logger_obj=logger_obj,
            should_use_local_direct_llm_fallback=True,
            process_with_direct_llm_fn=process_with_direct_llm_fn,
            resolve_runtime_llm_metadata_fn=MagicMock(return_value={}),
            processing_result_cls=FakeProcessingResult,
            agent_type_rag="rag",
        )

        assert result.message == "hello"
        process_with_direct_llm_fn.assert_awaited_once_with(context)

    @pytest.mark.asyncio
    async def test_uses_rag_path_when_available(self):
        logger_obj = MagicMock()
        output_processor = MagicMock()
        output_processor.format_sources.return_value = [{"title": "Doc"}]
        rag_agent = MagicMock()
        rag_agent.query = AsyncMock(
            return_value=SimpleNamespace(
                content="rag answer",
                citations=["citation"],
                native_thinking="rag thinking",
            )
        )

        result = await process_without_multi_agent_impl(
            context=SimpleNamespace(
                message="Explain COLREG Rule 5",
                user_role=SimpleNamespace(value="student"),
            ),
            rag_agent=rag_agent,
            output_processor=output_processor,
            logger_obj=logger_obj,
            should_use_local_direct_llm_fallback=False,
            process_with_direct_llm_fn=AsyncMock(),
            resolve_runtime_llm_metadata_fn=MagicMock(
                return_value={"provider": "google", "model": "gemini-test"}
            ),
            processing_result_cls=FakeProcessingResult,
            agent_type_rag="rag",
        )

        assert result == FakeProcessingResult(
            message="rag answer",
            agent_type="rag",
            sources=[{"title": "Doc"}],
            metadata={
                "mode": "fallback_rag",
                "provider": "google",
                "model": "gemini-test",
                "_execution_provider": "google",
                "_execution_model": "gemini-test",
                "runtime_authoritative": True,
            },
            thinking="rag thinking",
        )

    @pytest.mark.asyncio
    async def test_raises_when_no_agent_available(self):
        with pytest.raises(RuntimeError, match="No processing agent available"):
            await process_without_multi_agent_impl(
                context=SimpleNamespace(
                    message="Explain COLREG Rule 5",
                    user_role=SimpleNamespace(value="student"),
                ),
                rag_agent=None,
                output_processor=MagicMock(),
                logger_obj=MagicMock(),
                should_use_local_direct_llm_fallback=False,
                process_with_direct_llm_fn=AsyncMock(),
                resolve_runtime_llm_metadata_fn=MagicMock(return_value={}),
                processing_result_cls=FakeProcessingResult,
                agent_type_rag="rag",
            )
