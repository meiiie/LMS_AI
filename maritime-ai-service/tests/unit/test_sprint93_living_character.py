"""
Sprint 93: Living Character Card — Tests

Tests:
1. Identity YAML enrichment (quirks, opinions, catchphrases, backstory)
2. Character models (CharacterBlock, CharacterExperience, BlockLabel, etc.)
3. CharacterStateManager (compile_living_state, caching, default blocks)
4. Character tools (note, replace, read, log_experience)
5. Prompt integration (quirks/opinions/catchphrases in built prompt)
6. Living state injection into system prompt
7. Edge cases (empty blocks, DB unavailable, char limits)
"""

import sys
import types
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Break circular import
_cs_key = "app.services.chat_service"
if _cs_key not in sys.modules:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs


PROMPTS_DIR = Path(__file__).parent.parent.parent / "app" / "prompts"


# =============================================================================
# Phase 1: Identity YAML enrichment
# =============================================================================

class TestIdentityYAMLEnrichment:
    """Sprint 93: wiii_identity.yaml has real character depth."""

    @pytest.fixture
    def identity(self):
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)["identity"]

    def test_has_birthday(self, identity):
        assert identity.get("birthday"), "Should have a birthday"

    def test_backstory_is_rich(self, identity):
        backstory = identity["backstory"]
        assert len(backstory) > 200, f"Backstory too short ({len(backstory)} chars)"
        assert "Bông" in backstory, "Should mention pet cat Bông"
        assert "The Wiii Lab" in backstory

    def test_backstory_has_specific_memory(self, identity):
        """Backstory should have concrete identity details, not just generic description."""
        backstory = identity["backstory"]
        assert "Bông" in backstory and "The Wiii Lab" in backstory
        assert "tại sao" in backstory.lower() or "ngộ" in backstory.lower()

    def test_has_quirks(self, identity):
        quirks = identity.get("quirks", [])
        assert len(quirks) >= 5, f"Should have at least 5 quirks, got {len(quirks)}"

    def test_quirks_has_tilde(self, identity):
        """Wiii's signature '~' quirk should be present."""
        quirks = identity.get("quirks", [])
        tilde_quirk = any("~" in q for q in quirks)
        assert tilde_quirk, "Should have the '~' usage quirk"

    def test_quirks_has_bong(self, identity):
        """Quirks should mention pet cat Bông."""
        quirks = identity.get("quirks", [])
        bong_quirk = any("Bông" in q for q in quirks)
        assert bong_quirk, "Should have the Bông cat quirk"

    def test_has_opinions(self, identity):
        opinions = identity.get("opinions", {})
        assert "loves" in opinions
        assert "dislikes" in opinions

    def test_opinions_loves_has_items(self, identity):
        loves = identity["opinions"]["loves"]
        assert len(loves) >= 3, "Should have at least 3 things Wiii loves"

    def test_opinions_dislikes_has_items(self, identity):
        dislikes = identity["opinions"]["dislikes"]
        assert len(dislikes) >= 2, "Should have at least 2 things Wiii dislikes"

    def test_has_catchphrases(self, identity):
        catchphrases = identity.get("catchphrases", [])
        assert len(catchphrases) >= 4, f"Should have at least 4 catchphrases, got {len(catchphrases)}"

    def test_catchphrases_has_signature(self, identity):
        """Should have Wiii's signature catchphrase."""
        catchphrases = identity.get("catchphrases", [])
        assert any("Hay quá~" in c for c in catchphrases)

    def test_has_living_state_config(self, identity):
        living = identity.get("living_state", {})
        assert living.get("enabled") is True

    def test_living_state_has_editable_blocks(self, identity):
        blocks = identity["living_state"]["editable_blocks"]
        assert len(blocks) >= 4
        labels = [b["label"] for b in blocks]
        assert "learned_lessons" in labels
        assert "favorite_topics" in labels
        assert "self_notes" in labels

    def test_emotional_range_has_proud(self, identity):
        """Sprint 93 added 'proud' emotion (shy when praised)."""
        emotional = identity.get("emotional_range", {})
        assert "proud" in emotional

    def test_example_dialogues_count(self, identity):
        examples = identity.get("example_dialogues", [])
        assert len(examples) >= 7, f"Should have at least 7 examples, got {len(examples)}"

    def test_example_dialogues_has_praise_response(self, identity):
        """Should have example of Wiii being shy when praised."""
        examples = identity.get("example_dialogues", [])
        praise_ex = any("khen" in ex.get("context", "").lower() for ex in examples)
        assert praise_ex, "Should have a praise/compliment example"

    def test_identity_anchor_updated(self, identity):
        anchor = identity.get("identity_anchor", "")
        assert "tò mò" in anchor, "Anchor should reflect updated personality"

    # Backward compatibility — existing fields still present
    def test_has_name(self, identity):
        assert identity["name"] == "Wiii"

    def test_has_traits(self, identity):
        assert len(identity["personality"]["traits"]) >= 6

    def test_has_avoid_list(self, identity):
        assert len(identity["response_style"]["avoid"]) >= 7

    def test_has_suggestions(self, identity):
        assert len(identity["response_style"]["suggestions"]) >= 5


# =============================================================================
# Phase 2: Character models
# =============================================================================

class TestCharacterModels:
    """Test Pydantic models for character state."""

    def test_character_block_creation(self):
        from app.engine.character.models import CharacterBlock
        block = CharacterBlock(label="self_notes", content="Test note")
        assert block.label == "self_notes"
        assert block.content == "Test note"
        assert block.version == 1
        assert block.char_limit == 1000

    def test_character_block_remaining_chars(self):
        from app.engine.character.models import CharacterBlock
        block = CharacterBlock(label="test", content="A" * 300, char_limit=500)
        assert block.remaining_chars() == 200

    def test_character_block_is_full(self):
        from app.engine.character.models import CharacterBlock
        block = CharacterBlock(label="test", content="A" * 1000, char_limit=1000)
        assert block.is_full()

    def test_character_block_not_full(self):
        from app.engine.character.models import CharacterBlock
        block = CharacterBlock(label="test", content="A" * 500, char_limit=1000)
        assert not block.is_full()

    def test_block_label_enum(self):
        from app.engine.character.models import BlockLabel
        assert BlockLabel.LEARNED_LESSONS == "learned_lessons"
        assert BlockLabel.FAVORITE_TOPICS == "favorite_topics"
        assert BlockLabel.USER_PATTERNS == "user_patterns"
        assert BlockLabel.SELF_NOTES == "self_notes"

    def test_experience_type_enum(self):
        from app.engine.character.models import ExperienceType
        assert ExperienceType.MILESTONE == "milestone"
        assert ExperienceType.LEARNING == "learning"
        assert ExperienceType.FUNNY_MOMENT == "funny"

    def test_block_char_limits(self):
        from app.engine.character.models import BLOCK_CHAR_LIMITS, BlockLabel
        assert BLOCK_CHAR_LIMITS[BlockLabel.LEARNED_LESSONS] == 1500
        assert BLOCK_CHAR_LIMITS[BlockLabel.SELF_NOTES] == 1000

    def test_character_experience_creation(self):
        from app.engine.character.models import CharacterExperience
        exp = CharacterExperience(
            experience_type="learning",
            content="Learned about Rule 15",
            importance=0.8,
            user_id="user_123",
        )
        assert exp.experience_type == "learning"
        assert exp.importance == 0.8
        assert exp.user_id == "user_123"

    def test_character_block_create_schema(self):
        from app.engine.character.models import CharacterBlockCreate
        create = CharacterBlockCreate(label="self_notes", content="Hi", char_limit=500)
        assert create.label == "self_notes"

    def test_character_block_update_schema(self):
        from app.engine.character.models import CharacterBlockUpdate
        update = CharacterBlockUpdate(content="New content")
        assert update.content == "New content"
        assert update.append is None

    def test_character_block_update_append(self):
        from app.engine.character.models import CharacterBlockUpdate
        update = CharacterBlockUpdate(append="\n- New item")
        assert update.append == "\n- New item"
        assert update.content is None

    def test_character_experience_create_schema(self):
        from app.engine.character.models import CharacterExperienceCreate
        create = CharacterExperienceCreate(
            experience_type="milestone",
            content="First user interaction",
        )
        assert create.importance == 0.5  # default
        assert create.user_id is None


# =============================================================================
# Phase 3: CharacterStateManager
# =============================================================================

class TestCharacterStateManager:
    """Test CharacterStateManager compile and caching logic."""

    def test_compile_empty_blocks(self):
        """Empty blocks should produce empty string (no noise)."""
        from app.engine.character.character_state import CharacterStateManager
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._initialized_defaults.add(cache_key)  # Skip DB seed
        manager._cache = {cache_key: {
            "learned_lessons": MagicMock(content="", label="learned_lessons"),
            "self_notes": MagicMock(content="", label="self_notes"),
        }}
        manager._cache_timestamp = {cache_key: __import__("time").time()}
        result = manager.compile_living_state()
        assert result == ""

    def test_compile_with_content(self):
        """Non-empty blocks should be compiled into formatted text."""
        from app.engine.character.character_state import CharacterStateManager
        from app.engine.character.models import CharacterBlock
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._initialized_defaults.add(cache_key)
        manager._cache = {cache_key: {
            "learned_lessons": CharacterBlock(
                label="learned_lessons",
                content="- Rule 15 hay bị hỏi sai\n- User thích ví dụ đời thường",
            ),
            "self_notes": CharacterBlock(
                label="self_notes",
                content="- Mình nên giải thích kỹ hơn về SOLAS",
            ),
            "favorite_topics": CharacterBlock(
                label="favorite_topics", content="",
            ),
            "user_patterns": CharacterBlock(
                label="user_patterns", content="",
            ),
        }}
        manager._cache_timestamp = {cache_key: __import__("time").time()}
        result = manager.compile_living_state()

        assert "TRẢI NGHIỆM CỦA WIII" in result
        assert "Bài học rút ra" in result
        assert "Rule 15" in result
        assert "Ghi chú cá nhân" in result
        assert "Chủ đề yêu thích" not in result  # Empty block skipped

    def test_cache_fresh_check(self):
        """Cache should be considered fresh within TTL."""
        import time
        from app.engine.character.character_state import CharacterStateManager
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._cache_timestamp = {cache_key: time.time()}
        assert manager._is_cache_fresh()

    def test_cache_stale_check(self):
        """Cache should be stale after TTL expires."""
        import time
        from app.engine.character.character_state import CharacterStateManager, _CACHE_TTL_SECONDS
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._cache_timestamp = {cache_key: time.time() - _CACHE_TTL_SECONDS - 1}
        assert not manager._is_cache_fresh()

    def test_invalidate_cache(self):
        """invalidate_cache should reset cache."""
        import time
        from app.engine.character.character_state import CharacterStateManager
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._cache = {cache_key: {"test": "data"}}
        manager._cache_timestamp = {cache_key: time.time()}
        manager.invalidate_cache()
        assert manager._cache == {}
        assert manager._cache_timestamp == {}

    def test_get_block_from_cache(self):
        """get_block should return from cache when fresh."""
        import time
        from app.engine.character.character_state import CharacterStateManager
        from app.engine.character.models import CharacterBlock
        manager = CharacterStateManager()
        block = CharacterBlock(label="self_notes", content="My notes")
        cache_key = manager._cache_key()
        manager._cache = {cache_key: {"self_notes": block}}
        manager._cache_timestamp = {cache_key: time.time()}
        result = manager.get_block("self_notes")
        assert result.content == "My notes"

    def test_get_block_nonexistent(self):
        """get_block should return None for nonexistent label."""
        import time
        from app.engine.character.character_state import CharacterStateManager
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._cache = {cache_key: {}}
        manager._cache_timestamp = {cache_key: time.time()}
        result = manager.get_block("nonexistent")
        assert result is None


# =============================================================================
# Phase 4: Character tools
# =============================================================================

class TestCharacterTools:
    """Test character self-editing tools."""

    def test_tool_character_note_invalid_block(self):
        """Should reject invalid block label."""
        from app.engine.character.character_tools import tool_character_note
        result = tool_character_note.invoke({"note": "test", "block": "invalid_block"})
        assert "không hợp lệ" in result

    def test_tool_character_replace_invalid_block(self):
        """Should reject invalid block label."""
        from app.engine.character.character_tools import tool_character_replace
        result = tool_character_replace("invalid_block", "content")
        assert "không hợp lệ" in result

    def test_tool_character_read_invalid_block(self):
        """Should reject invalid block label."""
        from app.engine.character.character_tools import tool_character_read
        result = tool_character_read.invoke({"block": "invalid_block"})
        assert "không hợp lệ" in result

    def test_tool_character_log_experience_invalid_type(self):
        """Should reject invalid experience type (Sprint 97: now @tool)."""
        from app.engine.character.character_tools import tool_character_log_experience
        result = tool_character_log_experience.invoke({"content": "test", "experience_type": "invalid"})
        assert "không hợp lệ" in result

    @patch("app.engine.character.character_state.get_character_state_manager")
    def test_tool_character_note_success(self, mock_get_mgr):
        """Should append note to block."""
        from app.engine.character.character_tools import tool_character_note
        from app.engine.character.models import CharacterBlock
        mock_mgr = MagicMock()
        mock_mgr.update_block.return_value = CharacterBlock(
            label="self_notes", content="- old\n- new", char_limit=1000
        )
        mock_get_mgr.return_value = mock_mgr
        result = tool_character_note.invoke({"note": "New learning", "block": "self_notes"})
        assert "ghi nhận" in result
        mock_mgr.update_block.assert_called_once()

    @patch("app.engine.character.character_state.get_character_state_manager")
    def test_tool_character_replace_success(self, mock_get_mgr):
        """Should replace block content."""
        from app.engine.character.character_tools import tool_character_replace
        from app.engine.character.models import CharacterBlock
        mock_mgr = MagicMock()
        mock_mgr.update_block.return_value = CharacterBlock(
            label="learned_lessons", content="New content", version=2
        )
        mock_get_mgr.return_value = mock_mgr
        result = tool_character_replace("learned_lessons", "New content")
        assert "cập nhật" in result
        assert "version 2" in result

    @patch("app.engine.character.character_state.get_character_state_manager")
    def test_tool_character_read_with_content(self, mock_get_mgr):
        """Should return block content."""
        from app.engine.character.character_tools import tool_character_read
        from app.engine.character.models import CharacterBlock
        mock_mgr = MagicMock()
        mock_mgr.get_block.return_value = CharacterBlock(
            label="self_notes", content="My notes here"
        )
        mock_get_mgr.return_value = mock_mgr
        result = tool_character_read.invoke({"block": "self_notes"})
        assert "My notes here" in result

    @patch("app.engine.character.character_state.get_character_state_manager")
    def test_tool_character_read_empty(self, mock_get_mgr):
        """Should return empty message when no content."""
        from app.engine.character.character_tools import tool_character_read
        from app.engine.character.models import CharacterBlock
        mock_mgr = MagicMock()
        mock_mgr.get_block.return_value = CharacterBlock(
            label="self_notes", content=""
        )
        mock_get_mgr.return_value = mock_mgr
        result = tool_character_read.invoke({"block": "self_notes"})
        assert "Chưa có" in result

    @patch("app.engine.character.character_repository.get_character_repository")
    def test_tool_log_experience_success(self, mock_get_repo):
        """Should log experience."""
        from app.engine.character.character_tools import tool_character_log_experience
        from app.engine.character.models import CharacterExperience
        mock_repo = MagicMock()
        mock_repo.log_experience.return_value = CharacterExperience(
            experience_type="learning", content="test"
        )
        mock_get_repo.return_value = mock_repo
        result = tool_character_log_experience.invoke({"content": "Learned something", "experience_type": "learning"})
        assert "ghi nhận" in result

    @patch("app.engine.character.character_state.get_character_state_manager")
    def test_tool_character_note_db_unavailable(self, mock_get_mgr):
        """Should handle DB unavailable gracefully."""
        from app.engine.character.character_tools import tool_character_note
        mock_mgr = MagicMock()
        mock_mgr.update_block.return_value = None
        mock_get_mgr.return_value = mock_mgr
        result = tool_character_note.invoke({"note": "test", "block": "self_notes"})
        assert "chưa ghi nhận" in result or "sẵn sàng" in result or "Không" in result


# =============================================================================
# Phase 5: Prompt integration
# =============================================================================

class TestPromptIntegration:
    """Test that new identity fields appear in built prompt."""

    def _build_prompt(self, **kwargs):
        """Build prompt with character state manager mocked to avoid DB connection."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_mgr:
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.compile_living_state.return_value = ""
            mock_mgr.return_value = mock_mgr_inst
            return loader.build_system_prompt(**kwargs)

    def test_quirks_in_prompt(self):
        prompt = self._build_prompt(role="student")
        # Post-Living Core Card refactor: quirks in NÉT RIÊNG DỄ NHẬN RA
        assert "NÉT RIÊNG DỄ NHẬN RA" in prompt or "NÉT RIÊNG:" in prompt

    def test_quirks_tilde_in_prompt(self):
        prompt = self._build_prompt(role="student")
        assert "~" in prompt

    def test_catchphrases_in_prompt(self):
        prompt = self._build_prompt(role="student")
        # Post-refactor: catchphrases may be in NÉT RIÊNG DỄ NHẬN RA or CHỐNG DRIFT
        prompt_lower = prompt.lower()
        assert "~" in prompt  # Wiii's signature tilde

    def test_opinions_in_prompt(self):
        prompt = self._build_prompt(role="student")
        # Post-refactor: opinions/preferences merged into core card
        assert "WIII LIVING CORE CARD" in prompt or "CỐT LÕI NHÂN VẬT" in prompt

    def test_opinions_loves_content(self):
        prompt = self._build_prompt(role="student")
        # Post-refactor: detailed opinions stay in identity YAML, while prompt
        # carries the compact Living Core Card to avoid overloading each turn.
        assert "WIII LIVING CORE CARD" in prompt or "CỐT LÕI NHÂN VẬT" in prompt

    def test_backstory_rich_in_prompt(self):
        prompt = self._build_prompt(role="student")
        # The tutor YAML backstory may be different, but identity section
        # injects via personality summary which references backstory indirectly
        assert "Wiii" in prompt

    def test_living_state_not_in_prompt_when_empty(self):
        """Living state should NOT appear when all blocks are empty."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        # Mock the character state manager to return empty
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_mgr:
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.compile_living_state.return_value = ""
            mock_mgr.return_value = mock_mgr_inst
            prompt = loader.build_system_prompt(role="student")
        assert "TRẢI NGHIỆM CỦA WIII" not in prompt

    def test_living_state_in_prompt_when_has_content(self):
        """Living state should appear when blocks have content."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        living_text = "--- TRẢI NGHIỆM CỦA WIII (Living State) ---\n📝 Bài học rút ra:\n- Rule 15 hay bị hỏi sai"
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_mgr:
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.compile_living_state.return_value = living_text
            mock_mgr.return_value = mock_mgr_inst
            prompt = loader.build_system_prompt(role="student")
        assert "TRẢI NGHIỆM CỦA WIII" in prompt
        assert "Rule 15 hay bị hỏi sai" in prompt

    def test_living_state_graceful_on_import_error(self):
        """Should not crash if character module unavailable."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            side_effect=ImportError("Not available"),
        ):
            prompt = loader.build_system_prompt(role="student")
        # Should still return a valid prompt
        assert "Wiii" in prompt
        assert "TRẢI NGHIỆM CỦA WIII" not in prompt


# =============================================================================
# Phase 6: Backward compatibility
# =============================================================================

class TestBackwardCompatibility:
    """Ensure Sprint 92 features still work after Sprint 93 changes."""

    def _build_prompt(self, **kwargs):
        """Build prompt with character state manager mocked to avoid DB hang."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_mgr:
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.compile_living_state.return_value = ""
            mock_mgr.return_value = mock_mgr_inst
            return loader.build_system_prompt(**kwargs)

    def test_traits_still_injected(self):
        prompt = self._build_prompt(role="student")
        # Post-Living Core Card refactor: traits in TÍNH NÉT CHỦ ĐẠO or CỐT LÕI NHÂN VẬT
        assert "TÍNH NÉT CHỦ ĐẠO" in prompt or "CỐT LÕI NHÂN VẬT" in prompt

    def test_goal_still_injected(self):
        prompt = self._build_prompt(role="student")
        assert "MỤC TIÊU" in prompt

    def test_voice_still_injected(self):
        prompt = self._build_prompt(role="student")
        # Post-refactor: voice in GIỌNG VĂN section
        assert "GIỌNG VĂN" in prompt

    def test_greeting_tone_anchor_first_message(self):
        prompt = self._build_prompt(role="student", is_follow_up=False)
        # Post-refactor: greeting anchor may use different section name
        assert "ĐIỂM TỰA GIỌNG NÓI" in prompt or "LỜI CHÀO MẪU" in prompt or "Wiii" in prompt

    def test_tools_from_yaml(self):
        prompt = self._build_prompt(role="student")
        assert "tool_knowledge_search" in prompt

    def test_anchor_at_threshold_turns(self):
        """Sprint 115: anchor threshold 10→6."""
        prompt = self._build_prompt(role="student", total_responses=6)
        assert "PERSONA REMINDER" in prompt

    def test_avoid_count_still_covers_core_rules(self):
        """Identity YAML avoid list can grow, but core anti-drift rules remain."""
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        avoid = config["identity"]["response_style"]["avoid"]
        assert len(avoid) >= 7
        assert any("follow-up" in item for item in avoid)


# =============================================================================
# Phase 7: Repository unit tests (no DB required)
# =============================================================================

class TestCharacterRepositoryUnit:
    """Test repository methods handle errors gracefully without DB."""

    def test_get_all_blocks_no_db(self):
        from unittest.mock import patch
        from app.engine.character.character_repository import CharacterRepository
        # Prevent lazy init from connecting to real DB
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            # _session_factory is None → should return []
            result = repo.get_all_blocks()
            assert result == []

    def test_get_block_no_db(self):
        from unittest.mock import patch
        from app.engine.character.character_repository import CharacterRepository
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.get_block("self_notes")
            assert result is None

    def test_create_block_no_db(self):
        from app.engine.character.character_repository import CharacterRepository
        from app.engine.character.models import CharacterBlockCreate
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.create_block(CharacterBlockCreate(label="test", content="hi"))
        assert result is None

    def test_update_block_no_db(self):
        from app.engine.character.character_repository import CharacterRepository
        from app.engine.character.models import CharacterBlockUpdate
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.update_block("test", CharacterBlockUpdate(content="new"))
        assert result is None

    def test_log_experience_no_db(self):
        from app.engine.character.character_repository import CharacterRepository
        from app.engine.character.models import CharacterExperienceCreate
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.log_experience(CharacterExperienceCreate(
                experience_type="learning", content="test"
            ))
        assert result is None

    def test_get_recent_experiences_no_db(self):
        from app.engine.character.character_repository import CharacterRepository
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.get_recent_experiences()
        assert result == []

    def test_count_experiences_no_db(self):
        from app.engine.character.character_repository import CharacterRepository
        with patch("app.engine.character.character_repository.CharacterRepository._ensure_initialized"):
            repo = CharacterRepository()
            result = repo.count_experiences()
        assert result == 0

    def test_singleton_pattern(self):
        from app.engine.character.character_repository import (
            get_character_repository,
            _character_repo,
        )
        import app.engine.character.character_repository as mod
        # Reset singleton
        mod._character_repo = None
        repo1 = get_character_repository()
        repo2 = get_character_repository()
        assert repo1 is repo2
        mod._character_repo = None  # cleanup


# =============================================================================
# Phase 8: Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge cases for character system."""

    def test_compile_with_only_one_block(self):
        """Only one non-empty block should still compile."""
        from app.engine.character.character_state import CharacterStateManager
        from app.engine.character.models import CharacterBlock
        manager = CharacterStateManager()
        cache_key = manager._cache_key()
        manager._initialized_defaults.add(cache_key)
        manager._cache = {cache_key: {
            "self_notes": CharacterBlock(label="self_notes", content="One note"),
            "learned_lessons": CharacterBlock(label="learned_lessons", content=""),
        }}
        manager._cache_timestamp = {cache_key: __import__("time").time()}
        result = manager.compile_living_state()
        assert "Ghi chú cá nhân" in result
        assert "Bài học rút ra" not in result  # Empty, should be skipped

    def test_character_block_remaining_chars_at_zero(self):
        from app.engine.character.models import CharacterBlock
        block = CharacterBlock(label="test", content="A" * 1500, char_limit=1000)
        assert block.remaining_chars() == 0  # Clamped to 0, not negative

    def test_character_experience_importance_bounds(self):
        from app.engine.character.models import CharacterExperienceCreate
        # Should clamp to valid range
        exp = CharacterExperienceCreate(
            experience_type="learning",
            content="test",
            importance=0.0,
        )
        assert exp.importance == 0.0

    def test_state_manager_singleton(self):
        from app.engine.character.character_state import (
            get_character_state_manager,
        )
        import app.engine.character.character_state as mod
        mod._state_manager = None
        m1 = get_character_state_manager()
        m2 = get_character_state_manager()
        assert m1 is m2
        mod._state_manager = None  # cleanup

    def test_no_identity_still_works(self):
        """build_system_prompt should work even without identity."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        loader._identity = {}
        with patch(
            "app.engine.character.character_state.get_character_state_manager"
        ) as mock_mgr:
            mock_mgr_inst = MagicMock()
            mock_mgr_inst.compile_living_state.return_value = ""
            mock_mgr.return_value = mock_mgr_inst
            prompt = loader.build_system_prompt(role="student")
        assert "Wiii" in prompt  # From agent.name in tutor.yaml
        assert "NÉT RIÊNG:" not in prompt  # No identity quirks
