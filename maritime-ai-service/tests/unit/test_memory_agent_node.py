"""
Tests for MemoryAgentNode — Sprint 72: Retrieve-Extract-Respond.

Tests memory retrieval, fact extraction, response generation,
template fallbacks, and state management.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_semantic_memory():
    mem = MagicMock()
    mem.get_user_facts = AsyncMock(return_value={
        "name": "Minh",
        "role": "student",
        "preferences": ["visual learning"],
        "interests": ["COLREGs", "SOLAS"],
    })
    mem._fact_extractor = MagicMock()
    mem._fact_extractor.extract_and_store_facts = AsyncMock(return_value=[])
    return mem


@pytest.fixture
def base_state():
    return {
        "user_id": "user-123",
        "query": "test query",
        "agent_outputs": {},
    }


def _make_node(semantic_memory=None):
    """Create MemoryAgentNode with mocked dependencies (avoids singleton)."""
    from app.engine.multi_agent.agents.memory_agent import MemoryAgentNode
    return MemoryAgentNode(semantic_memory=semantic_memory)


# ---------------------------------------------------------------------------
# process() tests
# ---------------------------------------------------------------------------

class TestMemoryAgentProcess:
    @pytest.mark.asyncio
    async def test_process_happy_path(self, mock_semantic_memory, base_state):
        node = _make_node(mock_semantic_memory)
        result = await node.process(base_state)

        assert result["current_agent"] == "memory_agent"
        assert result["memory_output"]  # non-empty string
        assert result["agent_outputs"]["memory"] == result["memory_output"]

    @pytest.mark.asyncio
    async def test_process_semantic_memory_only(self, mock_semantic_memory, base_state):
        node = _make_node(semantic_memory=mock_semantic_memory)
        result = await node.process(base_state)

        assert result["current_agent"] == "memory_agent"
        assert result["memory_output"]

    @pytest.mark.asyncio
    async def test_process_no_services(self, base_state):
        """Without semantic memory, returns friendly fallback."""
        node = _make_node()
        result = await node.process(base_state)

        assert result["current_agent"] == "memory_agent"
        assert result["memory_output"]
        # Should NOT contain old hardcoded error
        assert "Không có thông tin về user" not in result["memory_output"]

    @pytest.mark.asyncio
    async def test_process_semantic_memory_exception(self, base_state):
        bad_mem = MagicMock()
        bad_mem.get_user_facts = AsyncMock(side_effect=Exception("DB down"))
        bad_mem._fact_extractor = MagicMock()
        bad_mem._fact_extractor.extract_and_store_facts = AsyncMock(
            side_effect=Exception("LLM down"),
        )
        node = _make_node(semantic_memory=bad_mem)
        result = await node.process(base_state)

        # Should still have a response (graceful fallback)
        assert result["current_agent"] == "memory_agent"
        assert result["memory_output"]

    @pytest.mark.asyncio
    async def test_process_with_llm(self, mock_semantic_memory, base_state):
        """process() accepts and uses llm parameter."""
        node = _make_node(mock_semantic_memory)
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
            content="Chào Minh!"
        ))

        from unittest.mock import patch
        with patch("app.services.thinking_post_processor.ThinkingPostProcessor.process",
                    return_value=("Chào Minh!", None)):
            result = await node.process(base_state, llm=mock_llm)

        assert result["memory_output"] == "Chào Minh!"


    @pytest.mark.asyncio
    async def test_process_skips_long_term_facts_for_service_identity(self, mock_semantic_memory):
        node = _make_node(mock_semantic_memory)
        state = {
            "user_id": "api-client",
            "query": "Wii không nhớ mình hả?",
            "agent_outputs": {},
            "context": {
                "history_list": [
                    {"role": "user", "content": "chào"},
                    {"role": "user", "content": "đói quá huhu"},
                    {"role": "user", "content": "nằm im á"},
                ]
            },
        }

        result = await node.process(state)

        assert "đói quá huhu" in result["memory_output"]
        assert "COLREGs" not in result["memory_output"]
        mock_semantic_memory.get_user_facts.assert_not_awaited()
        mock_semantic_memory._fact_extractor.extract_and_store_facts.assert_not_awaited()


# ---------------------------------------------------------------------------
# _retrieve_facts() tests
# ---------------------------------------------------------------------------

class TestRetrieveFacts:
    @pytest.mark.asyncio
    async def test_returns_facts_list(self, mock_semantic_memory):
        node = _make_node(mock_semantic_memory)
        facts = await node._retrieve_facts("user-123")
        # Should contain name and role at minimum
        types_found = {f["type"] for f in facts}
        assert "name" in types_found
        assert "role" in types_found

    @pytest.mark.asyncio
    async def test_skips_internal_updated_at_fact_keys(self):
        semantic_memory = MagicMock()
        semantic_memory.get_user_facts = AsyncMock(
            return_value={
                "preference": "ma semantic test cuoi cua minh la trang xanh 618",
                "preference__updated_at": "2026-05-07T14:00:00Z",
            }
        )
        node = _make_node(semantic_memory)

        facts = await node._retrieve_facts("user-123")

        assert facts == [
            {
                "type": "preference",
                "content": "ma semantic test cuoi cua minh la trang xanh 618",
            }
        ]

    @pytest.mark.asyncio
    async def test_no_service_returns_empty(self):
        node = _make_node()
        facts = await node._retrieve_facts("user-1")
        assert facts == []


class TestExtractAndStoreFacts:
    @pytest.mark.asyncio
    async def test_classifies_changes_when_extractor_returns_facts_only(self):
        from app.engine.semantic_memory.memory_updater import MemoryAction
        from app.models.semantic_memory import FactType, UserFact

        semantic_memory = MagicMock()
        semantic_memory._fact_extractor = MagicMock()
        semantic_memory._fact_extractor.extract_and_store_facts = AsyncMock(
            return_value=[
                UserFact(
                    fact_type=FactType.ROLE,
                    value="captain",
                    confidence=0.95,
                )
            ]
        )
        node = _make_node(semantic_memory)

        facts, decisions = await node._extract_and_store_facts(
            "user-123",
            "Mình là thuyền trưởng",
            {"role": "student"},
        )

        assert facts == ["role: captain"]
        assert len(decisions) == 1
        assert decisions[0].action == MemoryAction.UPDATE
        assert decisions[0].old_value == "student"


class TestGenerateResponseContext:
    @pytest.mark.asyncio
    async def test_generate_response_includes_recent_conversation_context(self):
        node = _make_node()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Nho chu."))
        state = {
            "context": {
                "core_memory_block": "Name: Minh\nPreference: visual learning",
                "history_list": [
                    {"role": "user", "content": "doi qua huhu"},
                    {
                        "role": "assistant",
                        "content": "Trong nha con gi an duoc khong?",
                    },
                ]
            }
        }

        with patch(
            "app.services.thinking_post_processor.ThinkingPostProcessor.process",
            return_value=("Nho chu.", None),
        ):
            text = await node._generate_response(
                mock_llm,
                "Wii khong nho minh ha?",
                [],
                [],
                "",
                state,
            )

        assert text == "Nho chu."
        prompt = mock_llm.ainvoke.await_args.args[0][-1]["content"]
        assert "Doan hoi thoai gan day" in prompt
        assert "doi qua huhu" in prompt
        assert "Core memory block" in prompt
        assert "visual learning" in prompt

    @pytest.mark.asyncio
    async def test_generate_response_handles_none_context(self):
        node = _make_node()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Minh nè."))
        state = {"context": None}

        with patch(
            "app.services.thinking_post_processor.ThinkingPostProcessor.process",
            return_value=("Minh nè.", None),
        ):
            text = await node._generate_response(
                mock_llm,
                "Wiii khong nho minh ha?",
                [],
                [],
                "",
                state,
            )

        assert text == "Minh nè."
        mock_llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_response_short_circuits_explicit_memory_ack(self):
        node = _make_node()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("explicit memory ack should not call LLM"))

        text = await node._generate_response(
            mock_llm,
            (
                "Hãy ghi nhớ lâu dài rằng mã semantic test của mình là "
                "hải đăng bạc 884. Trả lời ngắn gọn rằng đã lưu."
            ),
            [],
            ["preference: mã semantic test của mình là hải đăng bạc 884"],
            "",
            {"context": None},
        )

        assert text == "\u0110\u00e3 l\u01b0u."
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_response_keeps_verbose_memory_ack_without_short_directive(self):
        node = _make_node()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("explicit memory template should not call LLM"))

        text = await node._generate_response(
            mock_llm,
            "Hay ghi nho lau dai rang ma semantic test cua minh la trang xanh 618.",
            [],
            ["preference: ma semantic test cua minh la trang xanh 618"],
            "",
            {"context": None},
        )

        assert "trang xanh 618" in text
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_response_short_circuits_named_memory_recall(self):
        node = _make_node()
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=AssertionError("named memory recall should not call LLM"))

        text = await node._generate_response(
            mock_llm,
            "Mã semantic test cuối mình vừa nhờ bạn ghi nhớ là gì? Trả lời đúng 1 câu.",
            [
                {
                    "type": "preference",
                    "content": "preference: mã semantic test cuối của mình là la bàn đỏ 317",
                }
            ],
            [],
            "",
            {"context": None},
        )

        assert text == "la bàn đỏ 317"
        mock_llm.ainvoke.assert_not_awaited()


# ---------------------------------------------------------------------------
# _template_response() tests
# ---------------------------------------------------------------------------

class TestTemplateResponse:
    def test_with_new_facts(self):
        node = _make_node()
        text = node._template_response("test", [], ["Tên: Minh"], "")
        assert "ghi nhớ" in text
        assert "Minh" in text

    def test_with_existing_facts(self):
        node = _make_node()
        text = node._template_response(
            "bạn nhớ gì?",
            [{"type": "name", "content": "Minh"}],
            [],
            "",
        )
        assert "Minh" in text

    def test_empty_returns_friendly(self):
        node = _make_node()
        text = node._template_response("test", [], [], "")
        assert "chưa có thông tin" in text.lower() or "chia sẻ" in text.lower()
        # Never returns old hardcoded error
        assert text != "Không có thông tin về user"

    def test_empty_with_recent_context_does_not_claim_no_memory(self):
        node = _make_node()
        text = node._template_response(
            "Wii không nhớ mình hả?",
            [],
            [],
            "",
            recent_conversation=(
                "User: chào\n"
                "AI: Chào bạn\n"
                "User: đói quá huhu\n"
                "User: nằm im á"
            ),
        )

        assert "đoạn vừa rồi" in text
        assert "đói quá huhu" in text
        assert "chưa có thông tin gì" not in text.lower()


# ---------------------------------------------------------------------------
# is_available() tests
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_available_with_semantic_memory(self, mock_semantic_memory):
        node = _make_node(semantic_memory=mock_semantic_memory)
        assert node.is_available() is True

    def test_not_available_without_services(self):
        node = _make_node()
        assert node.is_available() is False


# ---------------------------------------------------------------------------
# Singleton test
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_memory_agent_node_returns_instance(self):
        import app.engine.multi_agent.agents.memory_agent as mod
        mod._memory_node = None  # reset singleton
        try:
            node = mod.get_memory_agent_node()
            assert isinstance(node, mod.MemoryAgentNode)
            # Second call returns same instance
            node2 = mod.get_memory_agent_node()
            assert node is node2
        finally:
            mod._memory_node = None


class TestMemoryPublicThinking:
    @pytest.mark.asyncio
    async def test_process_with_llm_stores_thinking_in_state(self, mock_semantic_memory, base_state):
        node = _make_node(mock_semantic_memory)
        base_state["query"] = "Minh ten Nam, nho giup minh nhe"
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Chao Nam!"))
        mock_semantic_memory._fact_extractor.extract_and_store_facts = AsyncMock(
            return_value=[MagicMock(to_content=MagicMock(return_value="name: Nam"))]
        )

        with patch(
            "app.services.thinking_post_processor.ThinkingPostProcessor.process",
            return_value=("Chao Nam!", "Minh nhan ra ten Nam tu ngu canh."),
        ):
            result = await node.process(base_state, llm=mock_llm)

        assert result["memory_output"] == "Chao Nam!"
        assert result.get("thinking") == "Minh nhan ra ten Nam tu ngu canh."

    @pytest.mark.asyncio
    async def test_process_with_llm_adds_public_memory_thinking_when_none(self, mock_semantic_memory, base_state):
        node = _make_node(mock_semantic_memory)
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Minh nho roi nhe!"))

        mock_semantic_memory._fact_extractor.extract_and_store_facts = AsyncMock(
            return_value=[MagicMock(to_content=MagicMock(return_value="name: Nam"))]
        )

        with patch(
            "app.services.thinking_post_processor.ThinkingPostProcessor.process",
            return_value=("Minh nho roi nhe!", None),
        ):
            result = await node.process(base_state, llm=mock_llm)

        assert result["memory_output"] == "Minh nho roi nhe!"
        assert "mảnh nhớ" in result["thinking"]
        assert result["thinking_provenance"] == "authored_public_summary"
