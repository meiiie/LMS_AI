from __future__ import annotations

import json


def test_action_catalog_exposes_disabled_read_only_candidate_without_secrets():
    from app.engine.wiii_connect.action_catalog import (
        action_catalog_public_metadata,
        action_catalog_summary_for_provider,
        enabled_action_slugs_for_provider,
    )

    metadata = action_catalog_public_metadata(provider_slug="gmail")
    summary = action_catalog_summary_for_provider("gmail")
    serialized = json.dumps(metadata, sort_keys=True)

    assert metadata["version"] == "wiii_connect_action_catalog.v1"
    assert metadata["action_count"] == 1
    assert metadata["enabled_action_count"] == 0
    assert metadata["actions"][0]["slug"] == "GMAIL_FETCH_EMAILS"
    assert metadata["actions"][0]["mutation"] == "read"
    assert metadata["actions"][0]["enabled"] is False
    assert summary["catalog_action_count"] == 1
    assert summary["enabled_action_count"] == 0
    assert summary["read_only_action_count"] == 1
    assert enabled_action_slugs_for_provider("gmail") == ()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "client_secret" not in serialized
    assert "provider_payload" not in serialized


def test_action_catalog_projects_only_model_visible_argument_keys():
    from app.engine.wiii_connect.action_catalog import WiiiConnectCuratedAction

    action = WiiiConnectCuratedAction(
        slug="TEST_READ",
        provider_slug="internal",
        provider_kind="composio",
        label="Test read",
        argument_keys=("page_id", "access_token", "client_secret"),
    )
    metadata = action.to_public_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert "page_id" not in metadata["argument_keys"]
    assert "redacted_sensitive_field" in metadata["argument_keys"]
    assert metadata["model_argument_keys"] == metadata["argument_keys"]
    assert metadata["hidden_argument_count"] == 3
    assert "access_token" not in serialized
    assert "client_secret" not in serialized


def test_action_catalog_hides_backend_owned_facebook_post_arguments():
    from app.engine.wiii_connect.action_catalog import action_catalog_public_metadata

    metadata = action_catalog_public_metadata(
        provider_slug="facebook",
        enabled_slugs=("FACEBOOK_CREATE_POST",),
    )
    post = {
        action["slug"]: action for action in metadata["actions"]
    }["FACEBOOK_CREATE_POST"]
    serialized = json.dumps(post, sort_keys=True)

    assert post["argument_keys"] == ["message", "link"]
    assert post["model_argument_keys"] == ["message", "link"]
    assert post["hidden_argument_count"] == 3
    assert "page_id" not in serialized
    assert "published" not in serialized
    assert "scheduled_publish_time" not in serialized


def test_action_catalog_can_project_runtime_enabled_curated_action():
    from app.engine.wiii_connect.action_catalog import (
        action_catalog_public_metadata,
        configured_action_slugs_for_provider,
    )

    enabled = configured_action_slugs_for_provider(
        "gmail",
        enabled_slugs=("GMAIL_FETCH_EMAILS",),
    )
    metadata = action_catalog_public_metadata(
        provider_slug="gmail",
        enabled_slugs=enabled,
    )

    assert enabled == ("GMAIL_FETCH_EMAILS",)
    assert metadata["enabled_action_count"] == 1
    assert metadata["actions"][0]["enabled"] is True
    assert "runtime_enabled_requires_live_schema_verification" in metadata["actions"][0][
        "warnings"
    ]
