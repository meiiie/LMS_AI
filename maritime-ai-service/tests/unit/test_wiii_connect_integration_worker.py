from __future__ import annotations


def _composio_config():
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="test-key",
        api_key_present=True,
        auth_config_by_provider={
            "facebook": "authcfg_fb",
            "gmail": "authcfg_gmail",
        },
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "gmail": ("GMAIL_FETCH_EMAILS",),
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
        apply_execute_enabled=True,
        apply_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_CREATE_POST",),
        },
    )


def test_integration_worker_selects_provider_scoped_read_action():
    from app.engine.wiii_connect.integration_worker import (
        WIII_CONNECT_INTEGRATION_WORKER_VERSION,
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="gmail",
        prompt="doc email moi nhat tu giao vien",
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
        composio_config=_composio_config(),
    )

    metadata = plan.to_public_metadata()
    assert plan.ready is True
    assert plan.version == WIII_CONNECT_INTEGRATION_WORKER_VERSION
    assert plan.provider_slug == "gmail"
    assert plan.action_slug == "GMAIL_FETCH_EMAILS"
    assert plan.selected_mutation == "read"
    assert plan.stage_sequence == ("provider_gate", "action_policy", "ready")
    assert metadata["executor"] == "provider_worker"
    assert metadata["prompt_present"] is True
    assert "doc email moi nhat" not in str(metadata)


def test_integration_worker_derives_safe_read_arguments_from_prompt():
    from app.engine.wiii_connect.integration_worker import (
        build_wiii_connect_worker_arguments,
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="gmail",
        prompt="doc 2 email moi nhat tu giao vien",
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
        composio_config=_composio_config(),
    )

    argument_plan = build_wiii_connect_worker_arguments(
        plan=plan,
        prompt="doc 2 email moi nhat tu giao vien",
    )
    metadata = argument_plan.to_public_metadata()

    assert argument_plan.source == "backend_prompt_mapper"
    assert argument_plan.arguments == {"query": "from:teacher", "max_results": 2}
    assert metadata["argument_keys"] == ["max_results", "query"]
    assert "doc 2 email" not in str(metadata)
    assert "from:teacher" not in str(metadata)


def test_integration_worker_filters_caller_provided_backend_owned_arguments():
    from app.engine.wiii_connect.integration_worker import (
        build_wiii_connect_worker_arguments,
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="facebook",
        prompt="dang bai",
        action_slug="FACEBOOK_CREATE_POST",
        mutation="apply",
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={"facebook": ("FACEBOOK_CREATE_POST",)},
        composio_config=_composio_config(),
    )

    argument_plan = build_wiii_connect_worker_arguments(
        plan=plan,
        prompt="dang bai",
        provided_arguments={
            "message": "safe text",
            "page_id": "private_page",
            "published": True,
            "access_token": "secret",
        },
    )
    metadata = argument_plan.to_public_metadata()

    assert argument_plan.source == "caller_provided"
    assert argument_plan.arguments == {"message": "safe text"}
    assert metadata["argument_keys"] == ["message"]
    assert "page_id" not in str(metadata)
    assert "published" not in str(metadata)
    assert "access_token" not in str(metadata)


def test_integration_worker_blocks_provider_outside_scope():
    from app.engine.wiii_connect.integration_worker import (
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="facebook",
        prompt="dang bai",
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
        composio_config=_composio_config(),
    )

    assert plan.ready is False
    assert plan.status == "blocked"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.provider_slug == "facebook"
    assert plan.stage_sequence == ("provider_gate", "blocked")


def test_integration_worker_requires_explicit_mutating_action():
    from app.engine.wiii_connect.integration_worker import (
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="facebook",
        prompt="dang mot bai len facebook",
        mutation="apply",
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={"facebook": ("FACEBOOK_CREATE_POST",)},
        composio_config=_composio_config(),
    )

    assert plan.ready is False
    assert plan.status == "blocked"
    assert plan.reason == "explicit_action_required_for_mutation"
    assert plan.provider_slug == "facebook"
    assert plan.action_policy is not None
    assert plan.to_public_metadata()["action_policy"]["reason"] == (
        "explicit_action_required_for_mutation"
    )


def test_integration_worker_classifies_blocked_policy_stage():
    from app.engine.wiii_connect.integration_worker import (
        classify_wiii_connect_integration_worker_result,
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="facebook",
        prompt="dang mot bai len facebook",
        mutation="apply",
        allowed_provider_slugs=("facebook",),
        allowed_action_slugs_by_provider={"facebook": ("FACEBOOK_CREATE_POST",)},
        composio_config=_composio_config(),
    )

    classification = classify_wiii_connect_integration_worker_result(
        {
            "status": "action_failed",
            "success": False,
            "error": "explicit_action_required_for_mutation",
        },
        plan=plan,
    )

    assert classification["outcome"] == "blocked"
    assert classification["failed_stage"] == "action_policy"
    assert classification["provider_slug"] == "facebook"


def test_integration_worker_classifies_gateway_failure():
    from app.engine.wiii_connect.integration_worker import (
        classify_wiii_connect_integration_worker_result,
        plan_wiii_connect_integration_worker,
    )

    plan = plan_wiii_connect_integration_worker(
        provider_slug="gmail",
        prompt="doc email moi nhat tu giao vien",
        allowed_provider_slugs=("gmail",),
        allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
        composio_config=_composio_config(),
    )

    classification = classify_wiii_connect_integration_worker_result(
        {
            "status": "action_failed",
            "success": False,
            "error": "missing_scope",
            "gateway": {"status": "blocked", "reason": "missing_scope"},
        },
        plan=plan,
    )

    assert classification["outcome"] == "failed"
    assert classification["failed_stage"] == "gateway"
    assert classification["action_slug"] == "GMAIL_FETCH_EMAILS"
