def test_sanitize_notification_detail_redacts_url_controls_and_explicit_values():
    from app.services.notifications.privacy import (
        notification_recipient_ref,
        sanitize_notification_detail,
    )

    detail = sanitize_notification_detail(
        "GET https://example.test/send?apikey=raw-api-key"
        "&text=private-message&chat_id=user-secret failed "
        "access_token=raw-access-token",
        "raw-api-key",
        "private-message",
        "user-secret",
    )

    assert notification_recipient_ref("user-secret").startswith("sha256:")
    assert "raw-api-key" not in detail
    assert "private-message" not in detail
    assert "user-secret" not in detail
    assert "raw-access-token" not in detail
    assert "<redacted-secret>" in detail
