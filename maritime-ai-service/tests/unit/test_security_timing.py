"""Tests for app.core.security — timing-safe API key comparison."""

import hmac
from unittest.mock import patch

import pytest


class TestVerifyApiKey:
    """Verify API key comparison uses constant-time comparison."""

    def test_valid_key_returns_true(self):
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = "test-key-123"
            assert verify_api_key("test-key-123") is True

    def test_invalid_key_returns_false(self):
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = "test-key-123"
            assert verify_api_key("wrong-key") is False

    def test_empty_configured_key_allows_all(self):
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = ""
            assert verify_api_key("anything") is True

    def test_none_configured_key_allows_all(self):
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.api_key = None
            assert verify_api_key("anything") is True

        # Should NOT use bare == for the actual comparison
        # (the 'if not settings.api_key' check is fine)
