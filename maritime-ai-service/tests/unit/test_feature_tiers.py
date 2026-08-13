"""Tests for feature-flag tier classification."""

from app.core.feature_tiers import (
    FeatureTier,
    flags_for_tier,
    get_duplicate_feature_classifications,
    get_feature_tier,
    get_unclassified_feature_flags,
    summarize_feature_tiers,
)


def test_every_settings_feature_flag_has_exactly_one_tier():
    assert get_unclassified_feature_flags() == ()
    assert get_duplicate_feature_classifications() == {}


def test_foundational_tier_covers_core_runtime_controls():
    assert get_feature_tier("enable_agentic_loop") is FeatureTier.FOUNDATIONAL
    assert (
        get_feature_tier("enable_corrective_rag")
        is FeatureTier.FOUNDATIONAL
    )
    assert get_feature_tier("enable_websocket") is FeatureTier.FOUNDATIONAL


def test_production_supported_tier_covers_real_secondary_surfaces():
    assert (
        get_feature_tier("enable_living_agent")
        is FeatureTier.PRODUCTION_SUPPORTED
    )
    assert (
        get_feature_tier("enable_multi_tenant")
        is FeatureTier.PRODUCTION_SUPPORTED
    )
    assert (
        get_feature_tier("enable_magic_link_auth")
        is FeatureTier.PRODUCTION_SUPPORTED
    )


def test_dormant_tier_captures_legacy_or_low_exercise_surfaces():
    assert get_feature_tier("enable_neo4j") is FeatureTier.DORMANT
    assert get_feature_tier("enable_telegram") is FeatureTier.DORMANT


def test_summary_is_stable_and_sorted():
    summary = summarize_feature_tiers()
    assert set(summary) == {tier.value for tier in FeatureTier}
    expected = tuple(sorted(flags_for_tier(FeatureTier.FOUNDATIONAL)))
    assert summary[FeatureTier.FOUNDATIONAL.value] == expected
