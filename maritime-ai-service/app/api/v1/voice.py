"""Voice endpoints for Wiii UI affordances.

The desktop client never talks to ElevenLabs directly. This router keeps the
provider API key server-side and exposes a small, authenticated audio proxy for
Pointy captions.
"""

from __future__ import annotations

import logging
import re
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import RequireAuth
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security_roles import is_platform_admin
from app.repositories.admin_runtime_settings_repository import (
    get_admin_runtime_settings_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

ELEVENLABS_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
MAX_POINTY_SPEECH_CHARS = 320
VOICE_RUNTIME_CONFIG_KEY = "pointy_voice_runtime_config"
VOICE_RUNTIME_CONFIG_DESCRIPTION = "Persisted Pointy voice runtime configuration"
_FERNET_ENCODING = "fernet:v1"


class PointySpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_POINTY_SPEECH_CHARS)


class VoiceStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    provider: str = "elevenlabs"
    voice_id: str
    model_id: str
    output_format: str
    reason: str | None = None


class VoiceConfigResponse(VoiceStatusResponse):
    persisted: bool = False
    updated_at: str | None = None
    key_hint: str | None = None


class VoiceConfigUpdate(BaseModel):
    enabled: bool | None = None
    api_key: str | None = Field(default=None, min_length=8, max_length=1000, repr=False)
    clear_api_key: bool = False
    voice_id: str | None = Field(default=None, min_length=1, max_length=200)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    output_format: str | None = Field(default=None, min_length=1, max_length=80)


@dataclass(frozen=True)
class _PointyVoiceConfig:
    enabled: bool
    api_key: str
    voice_id: str
    model_id: str
    output_format: str
    persisted: bool = False
    updated_at: str | None = None


def _fernet_key_material() -> bytes:
    configured = str(getattr(settings, "oauth_encryption_key", "") or "").strip()
    if configured:
        candidate = configured.encode("utf-8")
        try:
            from cryptography.fernet import Fernet

            Fernet(candidate)
            return candidate
        except (ValueError, TypeError):
            logger.warning(
                "oauth_encryption_key is not a valid Fernet key; deriving "
                "Pointy voice encryption material from it instead"
            )
            return urlsafe_b64encode(
                sha256(f"wiii-pointy-voice::{configured}".encode("utf-8")).digest()
            )
    seed = str(getattr(settings, "jwt_secret_key", "") or "wiii-local-dev-secret")
    digest = sha256(f"wiii-pointy-voice::{seed}".encode("utf-8")).digest()
    return urlsafe_b64encode(digest)


def _encrypt_runtime_secret(value: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_fernet_key_material()).encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_runtime_secret(value: str) -> str:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(_fernet_key_material()).decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Pointy voice secret could not be decrypted with current runtime key")
        return ""


def _mask_secret(value: str) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) <= 10:
        return f"{cleaned[:2]}...{cleaned[-2:]}"
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _voice_config_storage_key(auth: Any | None = None) -> str:
    if str(getattr(auth, "auth_method", "") or "").strip().lower() == "api_key":
        return VOICE_RUNTIME_CONFIG_KEY
    if auth is not None and is_platform_admin(auth):
        return VOICE_RUNTIME_CONFIG_KEY
    user_id = str(getattr(auth, "user_id", "") or "").strip()
    if not user_id:
        return VOICE_RUNTIME_CONFIG_KEY
    digest = sha256(user_id.encode("utf-8")).hexdigest()[:24]
    return f"{VOICE_RUNTIME_CONFIG_KEY}:user:{digest}"


def _load_persisted_voice_payload(
    storage_key: str = VOICE_RUNTIME_CONFIG_KEY,
) -> tuple[dict[str, Any], str | None]:
    repo = get_admin_runtime_settings_repository()
    record = repo.get_settings(storage_key)
    if record is None:
        return {}, None
    return dict(record.settings or {}), record.updated_at.isoformat() if record.updated_at else None


def _api_key_from_payload(payload: dict[str, Any]) -> str:
    encrypted = str(payload.get("elevenlabs_api_key_encrypted") or "").strip()
    if encrypted:
        return _decrypt_runtime_secret(encrypted)
    # Backward-compatible read for early local experiments. New writes always
    # use encrypted storage.
    return str(payload.get("elevenlabs_api_key") or "").strip()


def _resolve_pointy_voice_config(auth: Any | None = None) -> _PointyVoiceConfig:
    storage_keys = [_voice_config_storage_key(auth)]
    if storage_keys[0] != VOICE_RUNTIME_CONFIG_KEY:
        storage_keys.append(VOICE_RUNTIME_CONFIG_KEY)

    payload: dict[str, Any] = {}
    updated_at: str | None = None
    for storage_key in storage_keys:
        payload, updated_at = _load_persisted_voice_payload(storage_key)
        if payload:
            break

    persisted = bool(payload)
    api_key = _api_key_from_payload(payload) or str(
        getattr(settings, "elevenlabs_api_key", "") or ""
    ).strip()
    return _PointyVoiceConfig(
        enabled=bool(payload.get("enabled", getattr(settings, "enable_pointy_voice", False))),
        api_key=api_key,
        voice_id=str(
            payload.get("voice_id")
            or getattr(settings, "elevenlabs_voice_id", "")
            or ""
        ).strip(),
        model_id=str(
            payload.get("model_id")
            or getattr(settings, "elevenlabs_model_id", "")
            or ""
        ).strip(),
        output_format=str(
            payload.get("output_format")
            or getattr(settings, "elevenlabs_output_format", "")
            or ""
        ).strip(),
        persisted=persisted,
        updated_at=updated_at,
    )

def _voice_config_response(config: _PointyVoiceConfig) -> VoiceConfigResponse:
    configured = bool(config.enabled and config.api_key and config.voice_id)
    reason: str | None = None
    if not config.enabled:
        reason = "pointy_voice_disabled"
    elif not configured:
        reason = "elevenlabs_api_key_or_voice_id_missing"
    return VoiceConfigResponse(
        enabled=config.enabled,
        configured=configured,
        voice_id=config.voice_id,
        model_id=config.model_id,
        output_format=config.output_format,
        reason=reason,
        persisted=config.persisted,
        updated_at=config.updated_at,
        key_hint=_mask_secret(config.api_key),
    )


def _pointy_voice_configured() -> bool:
    config = _resolve_pointy_voice_config()
    return bool(
        config.enabled
        and config.api_key
        and config.voice_id
    )


def _clean_pointy_speech_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"\[POINT:[^\]]+\]", "", cleaned)
    cleaned = cleaned.replace("[/POINT]", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > MAX_POINTY_SPEECH_CHARS:
        cleaned = cleaned[: MAX_POINTY_SPEECH_CHARS - 1].rstrip() + "..."
    return cleaned


def _build_elevenlabs_payload(text: str, *, model_id: str | None = None) -> dict[str, Any]:
    return {
        "text": text,
        "model_id": model_id or getattr(settings, "elevenlabs_model_id", "eleven_flash_v2_5"),
        "voice_settings": {
            "stability": 0.42,
            "similarity_boost": 0.82,
            "use_speaker_boost": True,
            "speed": 1.02,
        },
    }


@router.get("/status", response_model=VoiceStatusResponse)
async def voice_status(auth: RequireAuth) -> VoiceStatusResponse:
    return _voice_config_response(_resolve_pointy_voice_config(auth))


@router.get("/config", response_model=VoiceConfigResponse)
async def get_voice_config(auth: RequireAuth) -> VoiceConfigResponse:
    return _voice_config_response(_resolve_pointy_voice_config(auth))


@router.put("/config", response_model=VoiceConfigResponse)
async def update_voice_config(
    body: VoiceConfigUpdate,
    auth: RequireAuth,
) -> VoiceConfigResponse:
    storage_key = _voice_config_storage_key(auth)
    existing_payload, _updated_at = _load_persisted_voice_payload(storage_key)
    payload: dict[str, Any] = {
        "provider": "elevenlabs",
        "enabled": bool(
            body.enabled
            if body.enabled is not None
            else existing_payload.get("enabled", getattr(settings, "enable_pointy_voice", False))
        ),
        "voice_id": str(
            body.voice_id
            or existing_payload.get("voice_id")
            or getattr(settings, "elevenlabs_voice_id", "")
            or ""
        ).strip(),
        "model_id": str(
            body.model_id
            or existing_payload.get("model_id")
            or getattr(settings, "elevenlabs_model_id", "")
            or ""
        ).strip(),
        "output_format": str(
            body.output_format
            or existing_payload.get("output_format")
            or getattr(settings, "elevenlabs_output_format", "")
            or ""
        ).strip(),
    }

    if body.clear_api_key:
        pass
    elif body.api_key is not None:
        api_key = body.api_key.strip()
        payload["elevenlabs_api_key_encrypted"] = _encrypt_runtime_secret(api_key)
        payload["secret_encoding"] = _FERNET_ENCODING
    elif existing_payload.get("elevenlabs_api_key_encrypted"):
        payload["elevenlabs_api_key_encrypted"] = existing_payload["elevenlabs_api_key_encrypted"]
        payload["secret_encoding"] = existing_payload.get("secret_encoding", _FERNET_ENCODING)
    elif existing_payload.get("elevenlabs_api_key"):
        payload["elevenlabs_api_key_encrypted"] = _encrypt_runtime_secret(
            str(existing_payload.get("elevenlabs_api_key") or "").strip()
        )
        payload["secret_encoding"] = _FERNET_ENCODING

    record = get_admin_runtime_settings_repository().upsert_settings(
        storage_key,
        payload,
        description=VOICE_RUNTIME_CONFIG_DESCRIPTION,
    )
    if record is None:
        raise HTTPException(
            status_code=503,
            detail="Voice runtime settings storage is unavailable",
        )

    config = _resolve_pointy_voice_config(auth)
    return _voice_config_response(config)


@router.post("/pointy/tts")
@limiter.limit("60/minute")
async def synthesize_pointy_speech(
    request: Request,
    body: PointySpeechRequest,
    auth: RequireAuth,
) -> Response:
    text = _clean_pointy_speech_text(body.text)
    if not text:
        raise HTTPException(status_code=400, detail="Speech text is empty")

    config = _resolve_pointy_voice_config(auth)
    if not config.enabled:
        raise HTTPException(status_code=503, detail="Pointy voice is disabled")

    api_key = config.api_key
    voice_id = config.voice_id
    if not api_key or not voice_id:
        raise HTTPException(
            status_code=503,
            detail="ElevenLabs is not configured on the backend",
        )

    url = ELEVENLABS_STREAM_URL.format(voice_id=voice_id)
    output_format = str(
        config.output_format or "mp3_22050_32"
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            upstream = await client.post(
                url,
                params={"output_format": output_format},
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=_build_elevenlabs_payload(text, model_id=config.model_id),
            )
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs Pointy TTS request failed: %s", exc)
        raise HTTPException(status_code=502, detail="ElevenLabs request failed") from exc

    if upstream.status_code >= 400:
        logger.warning(
            "ElevenLabs Pointy TTS returned %s: %s",
            upstream.status_code,
            upstream.text[:300],
        )
        raise HTTPException(status_code=502, detail="ElevenLabs synthesis failed")

    media_type = upstream.headers.get("content-type") or "audio/mpeg"
    return Response(
        content=upstream.content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Wiii-Voice-Provider": "elevenlabs",
        },
    )
