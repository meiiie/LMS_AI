import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class FakeVoiceSettingsRepo:
    def __init__(self, payload=None):
        self.records = {}
        if payload is not None:
            self.records["pointy_voice_runtime_config"] = payload
        self.updated_at = datetime(2026, 5, 8, tzinfo=timezone.utc)

    def get_settings(self, key):
        payload = self.records.get(key)
        if payload is None:
            return None
        return SimpleNamespace(settings=payload, updated_at=self.updated_at)

    def upsert_settings(self, key, settings_payload, *, description=None):
        self.records[key] = settings_payload
        return SimpleNamespace(settings=settings_payload, updated_at=self.updated_at)


def _install_voice_repo(monkeypatch, module, payload=None):
    repo = FakeVoiceSettingsRepo(payload)
    monkeypatch.setattr(
        module,
        "get_admin_runtime_settings_repository",
        lambda: repo,
    )
    return repo


def test_clean_pointy_speech_text_removes_internal_markup():
    from app.api.v1.voice import _clean_pointy_speech_text

    assert _clean_pointy_speech_text("  [POINT:send]  Đây là nút gửi. \n ") == "Đây là nút gửi."


def test_voice_status_reports_missing_backend_key(monkeypatch):
    from app.api.v1 import voice as module

    _install_voice_repo(monkeypatch, module)
    monkeypatch.setattr(module.settings, "enable_pointy_voice", True, raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_voice_id", "voice-id", raising=False)

    response = asyncio.run(module.voice_status(SimpleNamespace(user_id="u")))
    assert response.enabled is True
    assert response.configured is False
    assert response.reason == "elevenlabs_api_key_or_voice_id_missing"


def test_update_voice_config_encrypts_key_and_applies_runtime(monkeypatch):
    from app.api.v1 import voice as module

    raw_key = "unit-test-elevenlabs-key"
    repo = _install_voice_repo(monkeypatch, module)
    monkeypatch.setattr(module.settings, "oauth_encryption_key", None, raising=False)
    monkeypatch.setattr(module.settings, "jwt_secret_key", "unit-test-secret", raising=False)
    monkeypatch.setattr(module.settings, "enable_pointy_voice", False, raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_voice_id", "voice-id", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_model_id", "eleven_flash_v2_5", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_output_format", "mp3_22050_32", raising=False)

    response = asyncio.run(
        module.update_voice_config(
            module.VoiceConfigUpdate(enabled=True, api_key=raw_key),
            SimpleNamespace(user_id="admin", platform_role="platform_admin"),
        )
    )

    assert response.enabled is True
    assert response.configured is True
    assert response.persisted is True
    assert response.key_hint == "unit...-key"
    payload = repo.records[module.VOICE_RUNTIME_CONFIG_KEY]
    assert payload["secret_encoding"] == module._FERNET_ENCODING
    assert payload["elevenlabs_api_key_encrypted"] != raw_key
    assert raw_key not in str(payload)
    assert module.settings.elevenlabs_api_key in ("", None)

    status = asyncio.run(module.voice_status(SimpleNamespace(user_id="admin")))
    assert status.configured is True

    other_user_status = asyncio.run(module.voice_status(SimpleNamespace(user_id="u")))
    assert other_user_status.configured is True


def test_non_admin_voice_config_remains_user_scoped(monkeypatch):
    from app.api.v1 import voice as module

    repo = _install_voice_repo(monkeypatch, module)
    monkeypatch.setattr(module.settings, "oauth_encryption_key", None, raising=False)
    monkeypatch.setattr(module.settings, "jwt_secret_key", "unit-test-secret", raising=False)
    monkeypatch.setattr(module.settings, "enable_pointy_voice", False, raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_voice_id", "voice-id", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_model_id", "eleven_flash_v2_5", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_output_format", "mp3_22050_32", raising=False)

    asyncio.run(
        module.update_voice_config(
            module.VoiceConfigUpdate(enabled=True, api_key="sk-test-user-7890"),
            SimpleNamespace(user_id="student-1", role="student", platform_role="member"),
        )
    )

    assert any(key.startswith(f"{module.VOICE_RUNTIME_CONFIG_KEY}:user:") for key in repo.records)
    assert module.VOICE_RUNTIME_CONFIG_KEY not in repo.records


def test_synthesize_pointy_speech_requires_backend_key(monkeypatch):
    from app.api.v1 import voice as module

    _install_voice_repo(monkeypatch, module)
    monkeypatch.setattr(module.settings, "enable_pointy_voice", True, raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_api_key", "", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_voice_id", "voice-id", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            module.synthesize_pointy_speech(
                SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
                module.PointySpeechRequest(text="Xin chào"),
                SimpleNamespace(user_id="u"),
            )
        )
    assert exc.value.status_code == 503


def test_synthesize_pointy_speech_proxies_to_elevenlabs(monkeypatch):
    from app.api.v1 import voice as module

    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"mp3-bytes"
        text = ""
        headers = {"content-type": "audio/mpeg"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    _install_voice_repo(monkeypatch, module)
    monkeypatch.setattr(module.settings, "enable_pointy_voice", True, raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_api_key", "test-key", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_voice_id", "voice-id", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_model_id", "eleven_flash_v2_5", raising=False)
    monkeypatch.setattr(module.settings, "elevenlabs_output_format", "mp3_22050_32", raising=False)
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    response = asyncio.run(
        module.synthesize_pointy_speech(
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            module.PointySpeechRequest(text="Đây là nút gửi."),
            SimpleNamespace(user_id="u"),
        )
    )

    assert response.body == b"mp3-bytes"
    assert captured["url"].endswith("/voice-id/stream")
    assert captured["params"] == {"output_format": "mp3_22050_32"}
    assert captured["headers"]["xi-api-key"] == "test-key"
    assert captured["json"]["model_id"] == "eleven_flash_v2_5"


def test_synthesize_pointy_speech_uses_persisted_model_config(monkeypatch):
    from app.api.v1 import voice as module

    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"mp3-bytes"
        text = ""
        headers = {"content-type": "audio/mpeg"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    _install_voice_repo(
        monkeypatch,
        module,
        {
            "enabled": True,
            "elevenlabs_api_key": "test-key",
            "voice_id": "voice-id",
            "model_id": "eleven_multilingual_v2",
            "output_format": "mp3_44100_128",
        },
    )
    monkeypatch.setattr(module.settings, "elevenlabs_model_id", "eleven_flash_v2_5", raising=False)
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    response = asyncio.run(
        module.synthesize_pointy_speech(
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            module.PointySpeechRequest(text="Xin chao"),
            SimpleNamespace(user_id="u"),
        )
    )

    assert response.body == b"mp3-bytes"
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    assert captured["json"]["model_id"] == "eleven_multilingual_v2"
