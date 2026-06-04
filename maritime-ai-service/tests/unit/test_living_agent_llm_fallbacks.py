from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.engine.living_agent.journal import JournalWriter
from app.engine.living_agent.models import EmotionalState, MoodType
from app.engine.living_agent.reflector import Reflector


@pytest.mark.asyncio
async def test_journal_writer_persists_deterministic_fallback_when_local_llm_empty():
    writer = JournalWriter()
    saved: list[object] = []
    llm = type("EmptyLLM", (), {"generate": AsyncMock(return_value="")})()

    with (
        patch("app.engine.living_agent.local_llm.get_local_llm", return_value=llm),
        patch.object(writer, "_get_entry_by_date", return_value=None),
        patch.object(writer, "_save_entry", side_effect=lambda entry, *, scope: saved.append(entry)),
    ):
        entry = await writer.write_daily_entry(
            EmotionalState(
                primary_mood=MoodType.CURIOUS,
                energy_level=0.6,
                social_battery=0.7,
            ),
            organization_id="org-fallback",
        )

    assert entry is not None
    assert saved == [entry]
    assert "deterministic journal fallback" in entry.content
    assert entry.organization_id == "org-fallback"
    assert entry.notable_events
    assert entry.learnings
    assert entry.goals_next


@pytest.mark.asyncio
async def test_reflector_persists_deterministic_fallback_when_local_llm_empty():
    reflector = Reflector()
    saved: list[object] = []
    llm = type("EmptyLLM", (), {"generate": AsyncMock(return_value="")})()

    def save_reflection(entry):
        saved.append(entry)
        return True

    with (
        patch("app.engine.living_agent.local_llm.get_local_llm", return_value=llm),
        patch.object(reflector, "_has_reflected_today", new=AsyncMock(return_value=False)),
        patch.object(reflector, "_get_journal_summary", new=AsyncMock(return_value="")),
        patch.object(reflector, "_get_emotion_summary", new=AsyncMock(return_value="")),
        patch.object(reflector, "_get_browsing_summary", new=AsyncMock(return_value="")),
        patch.object(reflector, "_get_skills_summary", new=AsyncMock(return_value="")),
        patch.object(reflector, "_save_reflection", new=AsyncMock(side_effect=save_reflection)),
    ):
        entry = await reflector.reflect(organization_id="org-fallback")

    assert entry is not None
    assert saved == [entry]
    assert "deterministic daily reflection fallback" in entry.content
    assert entry.organization_id == "org-fallback"
    assert entry.insights
    assert entry.goals_next_week
    assert entry.patterns_noticed
