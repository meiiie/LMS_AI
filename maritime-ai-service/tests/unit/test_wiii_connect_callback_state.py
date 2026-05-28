from __future__ import annotations

from urllib.parse import parse_qs, urlsplit


def test_callback_state_round_trip_is_signed_and_privacy_safe():
    from app.engine.wiii_connect.callback_state import (
        WIII_CONNECT_CALLBACK_STATE_PARAM,
        append_wiii_connect_callback_state,
        build_wiii_connect_callback_state,
        verify_wiii_connect_callback_state,
    )

    state = build_wiii_connect_callback_state(
        provider_slug="facebook",
        organization_id="org_1",
        user_id="user_1",
        secret_key="test-secret-key",
        issued_at=1_000,
        nonce="nonce_1",
    )
    callback_url = append_wiii_connect_callback_state(
        "https://wiii.example.test/callback?existing=1",
        state,
    )
    params = parse_qs(urlsplit(callback_url).query)
    claims = verify_wiii_connect_callback_state(
        params[WIII_CONNECT_CALLBACK_STATE_PARAM][0],
        provider_slug="facebook",
        secret_key="test-secret-key",
        now=1_100,
    )
    metadata = claims.to_audit_metadata()

    assert claims.valid is True
    assert claims.provider_slug == "facebook"
    assert claims.organization_id == "org_1"
    assert claims.user_id == "user_1"
    assert params["existing"] == ["1"]
    assert metadata["organization_id_present"] is True
    assert metadata["user_id_present"] is True


def test_callback_state_rejects_tamper_provider_and_expiry():
    from app.engine.wiii_connect.callback_state import (
        build_wiii_connect_callback_state,
        verify_wiii_connect_callback_state,
    )

    state = build_wiii_connect_callback_state(
        provider_slug="facebook",
        organization_id="org_1",
        user_id="user_1",
        secret_key="test-secret-key",
        issued_at=1_000,
        nonce="nonce_1",
    )
    tampered = f"{state}x"
    tampered_claims = verify_wiii_connect_callback_state(
        tampered,
        provider_slug="facebook",
        secret_key="test-secret-key",
        now=1_100,
    )
    mismatch = verify_wiii_connect_callback_state(
        state,
        provider_slug="gmail",
        secret_key="test-secret-key",
        now=1_100,
    )
    expired = verify_wiii_connect_callback_state(
        state,
        provider_slug="facebook",
        secret_key="test-secret-key",
        now=3_000,
    )

    assert tampered_claims.valid is False
    assert tampered_claims.reason == "invalid_state_signature"
    assert mismatch.valid is False
    assert mismatch.reason == "state_provider_mismatch"
    assert expired.valid is False
    assert expired.reason == "state_expired"
