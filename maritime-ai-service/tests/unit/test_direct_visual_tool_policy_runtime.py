from types import SimpleNamespace


def test_direct_visual_tool_policy_requires_commit_for_article_figure():
    from app.engine.multi_agent.direct_visual_tool_policy_runtime import (
        build_direct_visual_tool_policy,
    )

    policy = build_direct_visual_tool_policy(
        query="ve infographic",
        settings_obj=SimpleNamespace(enable_structured_visuals=True),
        timeout_profile_structured="structured",
        timeout_profile_background="background",
        resolve_visual_intent_fn=lambda _query: SimpleNamespace(
            force_tool=True,
            presentation_intent="article_figure",
        ),
    )

    assert policy.requires_visual_commit is True
    assert policy.initial_timeout_profile == "structured"
    assert policy.followup_timeout_profile == "background"
    assert policy.structured_visuals_enabled is True


def test_direct_visual_tool_policy_keeps_structured_followup_for_app_visuals():
    from app.engine.multi_agent.direct_visual_tool_policy_runtime import (
        build_direct_visual_tool_policy,
    )

    policy = build_direct_visual_tool_policy(
        query="tao app mo phong",
        settings_obj=SimpleNamespace(enable_structured_visuals=False),
        timeout_profile_structured="structured",
        timeout_profile_background="background",
        resolve_visual_intent_fn=lambda _query: SimpleNamespace(
            force_tool=True,
            presentation_intent="code_studio_app",
        ),
    )

    assert policy.requires_visual_commit is False
    assert policy.initial_timeout_profile == "structured"
    assert policy.followup_timeout_profile == "structured"
    assert policy.structured_visuals_enabled is False


def test_direct_visual_tool_policy_uses_no_initial_profile_for_text_turns():
    from app.engine.multi_agent.direct_visual_tool_policy_runtime import (
        build_direct_visual_tool_policy,
    )

    policy = build_direct_visual_tool_policy(
        query="xin chao",
        settings_obj=SimpleNamespace(),
        timeout_profile_structured="structured",
        timeout_profile_background="background",
        resolve_visual_intent_fn=lambda _query: SimpleNamespace(
            force_tool=False,
            presentation_intent="text",
        ),
    )

    assert policy.requires_visual_commit is False
    assert policy.initial_timeout_profile is None
    assert policy.followup_timeout_profile == "structured"
    assert policy.structured_visuals_enabled is False
