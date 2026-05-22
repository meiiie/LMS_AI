from app.engine.multi_agent.direct_node_thinking_effort import (
    _canonicalize_direct_thinking_effort,
    _resolve_direct_thinking_effort,
)
from app.engine.multi_agent.direct_intent import _looks_identity_selfhood_turn


def test_canonicalize_direct_thinking_effort_maps_legacy_aliases():
    assert _canonicalize_direct_thinking_effort("light") == "low"
    assert _canonicalize_direct_thinking_effort("moderate") == "medium"
    assert _canonicalize_direct_thinking_effort("deep") == "high"


def test_resolve_direct_thinking_effort_uses_low_for_short_house_chatter():
    effort = _resolve_direct_thinking_effort(
        query="hehe",
        state={},
        current_effort=None,
        is_identity_turn=False,
        is_short_house_chatter=True,
    )

    assert effort == "low"


def test_resolve_direct_thinking_effort_overrides_generic_medium_for_short_house_chatter():
    effort = _resolve_direct_thinking_effort(
        query="hehe",
        state={},
        current_effort="moderate",
        is_identity_turn=False,
        is_short_house_chatter=True,
    )

    assert effort == "low"


def test_resolve_direct_thinking_effort_uses_high_for_origin_identity_turn():
    effort = _resolve_direct_thinking_effort(
        query="Wiii duoc sinh ra nhu the nao?",
        state={"routing_metadata": {"intent": "identity"}},
        current_effort=None,
        is_identity_turn=True,
        is_short_house_chatter=False,
    )

    assert effort == "max"


def test_identity_selfhood_detector_recognizes_origin_query():
    assert _looks_identity_selfhood_turn("Wiii duoc sinh ra nhu the nao?") is True


def test_resolve_direct_thinking_effort_uses_medium_for_basic_identity_turn():
    effort = _resolve_direct_thinking_effort(
        query="Wiii la ai?",
        state={"routing_metadata": {"intent": "identity"}},
        current_effort=None,
        is_identity_turn=True,
        is_short_house_chatter=False,
    )

    assert effort == "high"


def test_resolve_direct_thinking_effort_uses_high_for_analytical_math_turn():
    effort = _resolve_direct_thinking_effort(
        query=(
            "Trinh bay cach dung spectral theorem, Stone theorem, va deficiency indices "
            "de phan tich self-adjoint operator tren Hilbert space co compact resolvent"
        ),
        state={"routing_metadata": {"intent": "off_topic"}},
        current_effort=None,
        is_identity_turn=False,
        is_short_house_chatter=False,
    )

    assert effort == "high"


def test_resolve_direct_thinking_effort_upgrades_generic_medium_for_analytical_math_turn():
    effort = _resolve_direct_thinking_effort(
        query=(
            "Hay phan tich spectral theorem, deficiency indices va self-adjoint operator "
            "tren Hilbert space co compact resolvent"
        ),
        state={"routing_metadata": {"intent": "off_topic"}},
        current_effort="moderate",
        is_identity_turn=False,
        is_short_house_chatter=False,
    )

    assert effort == "high"


def test_resolve_direct_thinking_effort_preserves_explicit_canonical_value():
    effort = _resolve_direct_thinking_effort(
        query="Wiii duoc sinh ra nhu the nao?",
        state={"routing_metadata": {"intent": "identity"}},
        current_effort="max",
        is_identity_turn=True,
        is_short_house_chatter=False,
    )

    assert effort == "max"
