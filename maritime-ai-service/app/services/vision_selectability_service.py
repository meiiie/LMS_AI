"""Runtime selectability snapshot for vision backends."""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Literal

from app.core.config import settings
from app.engine.openai_compatible_credentials import (
    openrouter_credentials_available,
    resolve_openai_api_key,
)
from app.engine.vision_runtime import (
    VisionCapability,
    _provider_default_model,
    _provider_status,
    _resolve_provider_order,
)

VisionProviderState = Literal["selectable", "disabled"]

SELECTABILITY_CACHE_TTL_SECONDS = 15.0
SUPPORTED_VISION_PROVIDERS: tuple[str, ...] = (
    "google",
    "openai",
    "openrouter",
    "ollama",
    "zhipu",
)
SUPPORTED_VISION_CAPABILITIES: tuple[VisionCapability, ...] = (
    VisionCapability.VISUAL_DESCRIBE,
    VisionCapability.OCR_EXTRACT,
    VisionCapability.GROUNDED_VISUAL_ANSWER,
)
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "google": "Gemini Vision",
    "openai": "OpenAI Vision",
    "openrouter": "OpenRouter Vision",
    "ollama": "Ollama Vision",
    "zhipu": "Zhipu Vision",
}
_CAPABILITY_LABELS: dict[VisionCapability, str] = {
    VisionCapability.VISUAL_DESCRIBE: "Mo ta anh",
    VisionCapability.OCR_EXTRACT: "OCR / trich xuat",
    VisionCapability.GROUNDED_VISUAL_ANSWER: "Grounded visual answer",
}


@dataclass(frozen=True)
class VisionCapabilitySelectability:
    capability: str
    display_name: str
    available: bool
    selected_model: str | None
    lane_fit: str | None
    lane_fit_label: str | None
    reason_code: str | None
    reason_label: str | None
    resolved_base_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VisionProviderSelectability:
    provider: str
    display_name: str
    state: VisionProviderState
    configured: bool
    available: bool
    in_failover_chain: bool
    is_default: bool
    is_active: bool
    selected_model: str | None
    reason_code: str | None
    reason_label: str | None
    capabilities: list[VisionCapabilitySelectability] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["capabilities"] = [item.to_dict() for item in self.capabilities]
        return payload


@dataclass
class _CacheEntry:
    created_at: float
    snapshot: list[VisionProviderSelectability]


_selectability_cache: _CacheEntry | None = None


def invalidate_vision_selectability_cache() -> None:
    global _selectability_cache
    _selectability_cache = None


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider.replace("_", " ").title())


def _provider_is_configured(provider: str) -> bool:
    if provider == "google":
        return bool(getattr(settings, "google_api_key", None))
    if provider == "openai":
        return bool(resolve_openai_api_key(settings))
    if provider == "openrouter":
        return openrouter_credentials_available(settings)
    if provider == "ollama":
        return bool(getattr(settings, "ollama_base_url", None))
    if provider == "zhipu":
        return bool(getattr(settings, "zhipu_api_key", None))
    return False


def _resolve_active_provider(*, allow_local_probe: bool = True) -> str | None:
    for provider in _resolve_provider_order(capability=VisionCapability.VISUAL_DESCRIBE):
        if provider == "ollama" and not allow_local_probe:
            continue
        status = _provider_status(provider, VisionCapability.VISUAL_DESCRIBE)
        if status.available:
            return provider
    return None


def _build_snapshot_uncached(
    *,
    allow_local_probe: bool = True,
) -> list[VisionProviderSelectability]:
    provider_order = _resolve_provider_order(capability=VisionCapability.VISUAL_DESCRIBE)
    in_chain = set(provider_order)
    configured_provider = str(getattr(settings, "vision_provider", "auto") or "auto").strip().lower()
    default_provider = (
        configured_provider
        if configured_provider and configured_provider != "auto"
        else (provider_order[0] if provider_order else None)
    )
    active_provider = _resolve_active_provider(allow_local_probe=allow_local_probe)

    snapshot: list[VisionProviderSelectability] = []
    for provider in SUPPORTED_VISION_PROVIDERS:
        capability_rows: list[VisionCapabilitySelectability] = []
        provider_available = False
        selected_model = None
        primary_reason_code: str | None = None
        primary_reason_label: str | None = None

        for capability in SUPPORTED_VISION_CAPABILITIES:
            if provider == "ollama" and not allow_local_probe:
                status = SimpleNamespace(
                    available=False,
                    model_name=_provider_default_model(provider, capability),
                    lane_fit=None,
                    lane_fit_label=None,
                    reason_code="host_down",
                    reason_label=(
                        "Ollama local chua duoc probe trong luot tai nhanh. "
                        "Chay Probe capability de kiem tra live."
                    ),
                    resolved_base_url=None,
                )
            else:
                status = _provider_status(provider, capability)
            capability_rows.append(
                VisionCapabilitySelectability(
                    capability=capability.value,
                    display_name=_CAPABILITY_LABELS.get(capability, capability.value),
                    available=status.available,
                    selected_model=status.model_name,
                    lane_fit=getattr(status, "lane_fit", None),
                    lane_fit_label=getattr(status, "lane_fit_label", None),
                    reason_code=status.reason_code,
                    reason_label=status.reason_label,
                    resolved_base_url=status.resolved_base_url,
                )
            )
            if capability == VisionCapability.VISUAL_DESCRIBE:
                selected_model = status.model_name or _provider_default_model(provider, capability)
                primary_reason_code = status.reason_code
                primary_reason_label = status.reason_label
            provider_available = provider_available or status.available

        snapshot.append(
            VisionProviderSelectability(
                provider=provider,
                display_name=_provider_display_name(provider),
                state="selectable" if provider_available else "disabled",
                configured=_provider_is_configured(provider),
                available=provider_available,
                in_failover_chain=provider in in_chain,
                is_default=provider == default_provider,
                is_active=provider == active_provider,
                selected_model=selected_model,
                reason_code=None if provider_available else primary_reason_code,
                reason_label=None if provider_available else primary_reason_label,
                capabilities=capability_rows,
            )
        )

    return snapshot


def get_vision_selectability_snapshot(
    *,
    force_refresh: bool = False,
    allow_local_probe: bool = True,
) -> list[VisionProviderSelectability]:
    global _selectability_cache

    now = time.monotonic()
    if (
        not force_refresh
        and _selectability_cache is not None
        and now - _selectability_cache.created_at < SELECTABILITY_CACHE_TTL_SECONDS
    ):
        return copy.deepcopy(_selectability_cache.snapshot)

    snapshot = _build_snapshot_uncached(allow_local_probe=allow_local_probe)
    _selectability_cache = _CacheEntry(
        created_at=now,
        snapshot=copy.deepcopy(snapshot),
    )
    return snapshot


__all__ = [
    "VisionCapabilitySelectability",
    "VisionProviderSelectability",
    "get_vision_selectability_snapshot",
    "invalidate_vision_selectability_cache",
]
