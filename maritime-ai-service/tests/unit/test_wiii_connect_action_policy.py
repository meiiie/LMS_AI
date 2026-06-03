from __future__ import annotations


def test_wiii_connect_action_policy_blocks_implicit_apply_action():
    from app.engine.wiii_connect.action_policy import select_wiii_connect_action

    decision = select_wiii_connect_action(
        provider_slug="facebook",
        mutation="apply",
        action_allowlist=("FACEBOOK_CREATE_POST",),
        prompt="dang mot bai len facebook",
    )

    assert decision.status == "blocked"
    assert decision.reason == "explicit_action_required_for_mutation"
    assert decision.action_slug == ""
    assert decision.candidates
    assert decision.candidates[0].slug == "FACEBOOK_CREATE_POST"
    assert "verb_match" in decision.candidates[0].rank_reasons


def test_wiii_connect_action_policy_selects_single_read_action():
    from app.engine.wiii_connect.action_policy import select_wiii_connect_action

    decision = select_wiii_connect_action(
        provider_slug="gmail",
        mutation="read",
        action_allowlist=("GMAIL_FETCH_EMAILS",),
        prompt="kiem tra email moi",
    )

    assert decision.selected is True
    assert decision.reason == "selected_single_read_action"
    assert decision.action_slug == "GMAIL_FETCH_EMAILS"
    assert decision.selected_action is not None
    assert decision.selected_action.provider_slug == "gmail"


def test_wiii_connect_action_policy_rejects_unallowlisted_explicit_action():
    from app.engine.wiii_connect.action_policy import select_wiii_connect_action

    decision = select_wiii_connect_action(
        provider_slug="facebook",
        action_slug="FACEBOOK_CREATE_POST",
        mutation="apply",
        action_allowlist=("FACEBOOK_LIST_MANAGED_PAGES",),
        prompt="dang bai",
    )

    assert decision.status == "blocked"
    assert decision.reason == "action_not_allowlisted"
    assert decision.action_slug == "FACEBOOK_CREATE_POST"


def test_wiii_connect_action_authorization_ignores_unverified_mutation_claims():
    from app.engine.wiii_connect.action_authorization import (
        resolve_wiii_connect_action_authorization,
    )

    decision = resolve_wiii_connect_action_authorization(
        mutation="apply",
        preview_evidence_id="preview_injected",
        approval_token_present=True,
    )

    metadata = decision.to_public_metadata()
    assert decision.status == "required"
    assert decision.reason == "backend_verified_authorization_required"
    assert decision.trusted_preview_evidence_id is None
    assert decision.trusted_approval_token_present is False
    assert metadata["caller_claim_ignored"] is True
    assert metadata["trusted_preview_evidence_present"] is False


def test_wiii_connect_action_authorization_accepts_verified_backend_token():
    from app.engine.wiii_connect.action_authorization import (
        resolve_wiii_connect_action_authorization,
    )

    decision = resolve_wiii_connect_action_authorization(
        mutation="apply",
        preview_evidence_id="wcp_verified_preview",
        approval_token_present=True,
        authorization_verified=True,
    )

    assert decision.status == "verified"
    assert decision.reason == "verified_backend_authorization"
    assert decision.trusted_preview_evidence_id == "wcp_verified_preview"
    assert decision.trusted_approval_token_present is True


def test_wiii_connect_model_visible_arguments_filter_backend_owned_keys():
    from app.engine.wiii_connect.argument_key_policy import model_visible_arguments

    arguments = model_visible_arguments(
        provider_slug="facebook",
        action_slug="FACEBOOK_CREATE_POST",
        arguments={
            "message": "visible copy",
            "page_id": "private_page",
            "published": True,
            "access_token": "secret",
        },
    )

    assert arguments == {"message": "visible copy"}
