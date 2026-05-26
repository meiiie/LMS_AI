"""Runtime selectability policy for chat provider selection."""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.openai_compatible_credentials import (
    resolve_nvidia_model,
    resolve_openai_model,
    resolve_openrouter_model,
)
from app.engine.llm_runtime_state import (
    get_llm_runtime_provider_info,
    get_llm_runtime_stats,
)
from app.engine.model_catalog import (
    GOOGLE_DEFAULT_MODEL,
    ZHIPU_DEFAULT_MODEL,
)
from app.engine.llm_provider_registry import get_supported_provider_names
from app.services.llm_selectability_cache_token import (
    bump_llm_selectability_cache_generation,
    get_llm_selectability_cache_generation,
)

logger = logging.getLogger(__name__)

ProviderSelectabilityState = Literal["selectable", "disabled", "hidden"]
ProviderDisabledReasonCode = Literal[
    "busy",
    "host_down",
    "model_missing",
    "capability_missing",
    "verifying",
]

SELECTABILITY_CACHE_TTL_SECONDS = 15.0
BUSY_REASON_STALE_SECONDS = 600.0

_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "google": "Gemini",
    "zhipu": "Zhipu GLM",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA NIM",
    "ollama": "Ollama",
}
_BUSY_MARKERS = (
    "quota_or_rate_limited",
    "429",
    "resource_exhausted",
    "too many requests",
    "rate limit",
    "quota",
)
_HOST_DOWN_MARKERS = (
    "unreachable",
    "connection refused",
    "connecterror",
    "timed out",
    "timeout",
    "dependency_missing",
    "host unreachable",
)
_MODEL_MISSING_MARKERS = (
    "model missing",
    "model not found",
    "unknown model",
)
_DEGRADED_BUT_ROUTABLE_REASON_CODES: tuple[ProviderDisabledReasonCode, ...] = (
    "capability_missing",
    "verifying",
)
_CAPABILITY_FIELDS: dict[str, tuple[str, str]] = {
    "streaming": ("streaming_supported", "streaming_source"),
    "structured_output": ("structured_output_supported", "structured_output_source"),
    "tool_calling": ("tool_calling_supported", "tool_calling_source"),
}
_PROVIDER_REQUIRED_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "google": ("streaming", "structured_output", "tool_calling"),
    "openai": ("streaming", "structured_output", "tool_calling"),
    "zhipu": ("streaming", "structured_output", "tool_calling"),
    "openrouter": ("streaming",),
    "nvidia": ("streaming",),
    "ollama": ("streaming",),
}


class LLMPool:
    """Compatibility proxy for legacy tests/patch paths."""

    @staticmethod
    def get_stats() -> dict[str, Any]:
        return get_llm_runtime_stats()

    @staticmethod
    def get_provider_info(name: str):
        return get_llm_runtime_provider_info(name)


def _load_runtime_audit_payload() -> tuple[Any, dict[str, Any]]:
    try:
        audit_record = get_persisted_llm_runtime_audit()
        audit_payload = sanitize_llm_runtime_audit_payload(
            audit_record.payload if audit_record else None
        )
    except ModuleNotFoundError as exc:
        if exc.name != "openai":
            raise
        logger.debug(
            "LLM runtime audit unavailable because optional provider SDK is missing: %s",
            exc,
        )
        return None, {}

    return audit_record, audit_payload


def get_persisted_llm_runtime_audit() -> Any:
    from app.services.llm_runtime_audit_service import get_persisted_llm_runtime_audit

    return get_persisted_llm_runtime_audit()


def sanitize_llm_runtime_audit_payload(payload: Any) -> dict[str, Any]:
    from app.services.llm_runtime_audit_service import (
        sanitize_llm_runtime_audit_payload,
    )

    return sanitize_llm_runtime_audit_payload(payload)


@dataclass(frozen=True)
class ProviderSelectability:
    provider: str
    display_name: str
    state: ProviderSelectabilityState
    reason_code: ProviderDisabledReasonCode | None
    reason_label: str | None
    selected_model: str | None
    strict_pin: bool
    verified_at: str | None
    available: bool
    configured: bool
    request_selectable: bool
    is_primary: bool
    is_fallback: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _CacheEntry:
    created_at: float
    generation: int
    snapshot: list[ProviderSelectability]


_selectability_cache: _CacheEntry | None = None


def invalidate_llm_selectability_cache() -> None:
    """Clear the short-lived runtime selectability cache."""
    global _selectability_cache
    _selectability_cache = None
    bump_llm_selectability_cache_generation()


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider.replace("_", " ").title())


def _selected_model_for_provider(provider: str) -> str | None:
    if provider == "google":
        return settings.google_model or GOOGLE_DEFAULT_MODEL
    if provider == "zhipu":
        return getattr(settings, "zhipu_model", ZHIPU_DEFAULT_MODEL)
    if provider == "ollama":
        return settings.ollama_model
    if provider == "openai":
        return resolve_openai_model(settings)
    if provider == "openrouter":
        return resolve_openrouter_model(settings)
    if provider == "nvidia":
        return resolve_nvidia_model(settings)
    return None


def _friendly_reason_label(reason_code: ProviderDisabledReasonCode) -> str:
    if reason_code == "busy":
        return "Provider tam thoi ban hoac da cham gioi han."
    if reason_code == "host_down":
        return "Máy chủ local hiện chưa sẵn sàng."
    if reason_code == "model_missing":
        return "Model hiện tại chưa khả dụng trên provider này."
    if reason_code == "capability_missing":
        return "Provider này chưa đủ khả năng cho chế độ chat hiện tại."
    return "Hệ thống đang xác minh trạng thái runtime."


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_runtime_observation_succeeded(state: dict[str, Any]) -> bool:
    observed_at = _parse_iso_datetime(state.get("last_runtime_observation_at"))
    success_at = _parse_iso_datetime(state.get("last_runtime_success_at"))
    if observed_at is None:
        return success_at is not None
    if _is_preflight_provider_unavailable_observation(state):
        return True
    if success_at is None:
        return False
    return success_at >= observed_at


def _probe_success_supersedes_observation(state: Mapping[str, Any]) -> bool:
    """A successful live probe at-or-after the failed observation supersedes it.

    The provider has been verifiably reached since the recorded failure, so
    stale chat_stream:error records (often from pre-flight selectability
    rejections) shouldn't keep it disabled. Mirrors the ``>=`` semantics of
    ``_latest_runtime_observation_succeeded`` for consistency: when the two
    timestamps are equal the probe wins, since a probe is the more reliable
    signal of reachability.
    """
    probe_success_at = _parse_iso_datetime(state.get("last_live_probe_success_at"))
    observed_at = _parse_iso_datetime(state.get("last_runtime_observation_at"))
    if probe_success_at is None or observed_at is None:
        return False
    return probe_success_at >= observed_at


def _latest_runtime_observation_failed(state: Mapping[str, Any]) -> bool:
    observed_at = _parse_iso_datetime(state.get("last_runtime_observation_at"))
    if observed_at is None:
        return False
    if (
        _is_preflight_provider_unavailable_observation(state)
        and _live_streaming_probe_supersedes_host_down_signal(state)
    ):
        return False
    if _probe_success_supersedes_observation(state):
        return False
    success_at = _parse_iso_datetime(state.get("last_runtime_success_at"))
    if success_at is None:
        return True
    return success_at < observed_at


def _is_stale_runtime_failure(state: Mapping[str, Any]) -> bool:
    observed_at = _parse_iso_datetime(state.get("last_runtime_observation_at"))
    if observed_at is None or _latest_runtime_observation_succeeded(state):
        return False
    age_seconds = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds >= BUSY_REASON_STALE_SECONDS


def _is_stale_busy_signal(state: Mapping[str, Any]) -> bool:
    runtime_note = " | ".join(
        str(state.get(key) or "").strip()
        for key in ("last_runtime_error", "last_runtime_note")
        if str(state.get(key) or "").strip()
    ).lower()
    if any(marker in runtime_note for marker in _BUSY_MARKERS):
        if _is_stale_runtime_failure(state):
            return True
        if _probe_success_supersedes_observation(state):
            return True
        # When an explicit busy marker is present we ONLY trust a fresh probe
        # success (above) or age-based staleness. The probe-attempt-age
        # heuristic in the lower branch intentionally does NOT apply here —
        # otherwise an old probe attempt would silently mask a fresh 429
        # signal. Future readers: don't unify the two branches.
        return False

    probe_dt = _parse_iso_datetime(
        state.get("last_live_probe_attempt_at")
        or state.get("last_live_probe_success_at")
        or state.get("last_discovery_attempt_at")
    )
    if probe_dt is None:
        return False
    if _latest_runtime_observation_succeeded(state):
        runtime_success_at = _parse_iso_datetime(state.get("last_runtime_success_at"))
        if runtime_success_at is not None and runtime_success_at >= probe_dt:
            return True
    age_seconds = (datetime.now(timezone.utc) - probe_dt.astimezone(timezone.utc)).total_seconds()
    return age_seconds >= BUSY_REASON_STALE_SECONDS


def _collect_signal_texts(state: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "last_live_probe_error",
        "live_probe_note",
        "last_discovery_error",
        "last_runtime_error",
        "last_runtime_note",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for reason in state.get("degraded_reasons", []) or []:
        text = str(reason).strip()
        if text:
            parts.append(text)
    return " | ".join(parts).lower()


def _is_preflight_provider_unavailable_observation(state: Mapping[str, Any]) -> bool:
    source = str(state.get("last_runtime_source") or "").strip().lower()
    note = str(state.get("last_runtime_note") or "").strip().lower()
    if source not in {"chat_stream:error", "chat_sync:error"}:
        return False
    return "requested provider" in note and "unavailable" in note


def _live_streaming_probe_supersedes_host_down_signal(state: Mapping[str, Any]) -> bool:
    """Treat a fresh successful streaming probe as authoritative for reachability."""
    if state.get("streaming_supported") is not True:
        return False
    if str(state.get("streaming_source") or "").strip().lower() != "live_probe":
        return False

    probe_success_at = _parse_iso_datetime(state.get("last_live_probe_success_at"))
    if probe_success_at is None:
        return False

    observed_at = _parse_iso_datetime(state.get("last_runtime_observation_at"))
    if (
        observed_at is not None
        and probe_success_at < observed_at
        and not _is_preflight_provider_unavailable_observation(state)
    ):
        return False

    return True


def _has_provider_audit_truth(state: dict[str, Any]) -> bool:
    if not isinstance(state, dict) or not state:
        return False
    if state.get("selected_model_in_catalog") is True:
        return True
    if state.get("selected_model_advanced_in_catalog") is True:
        return True
    if state.get("model_count"):
        return True
    if state.get("discovered_model_count"):
        return True
    for key in (
        "last_discovery_attempt_at",
        "last_discovery_success_at",
        "last_live_probe_attempt_at",
        "last_live_probe_success_at",
        "last_runtime_observation_at",
        "last_runtime_success_at",
        "last_runtime_error_at",
        "last_runtime_error",
        "last_runtime_note",
        "live_probe_note",
        "last_live_probe_error",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return True
    degraded_reasons = state.get("degraded_reasons")
    if isinstance(degraded_reasons, list) and degraded_reasons:
        return True
    return False


def _clear_stale_provider_state_for_model_change(
    state: dict[str, Any],
    *,
    selected_model: str | None,
) -> None:
    state["selected_model"] = selected_model
    state["selected_model_in_catalog"] = None
    state["selected_model_advanced_in_catalog"] = None
    state["probe_model"] = None
    state["last_discovery_attempt_at"] = None
    state["last_discovery_success_at"] = None
    state["last_discovery_error"] = None
    state["last_live_probe_attempt_at"] = None
    state["last_live_probe_success_at"] = None
    state["last_live_probe_error"] = None
    state["live_probe_note"] = None
    state["last_runtime_observation_at"] = None
    state["last_runtime_success_at"] = None
    state["last_runtime_error"] = None
    state["last_runtime_note"] = None
    state["last_runtime_source"] = None
    state["degraded"] = False
    state["degraded_reasons"] = []
    state["tool_calling_supported"] = None
    state["tool_calling_source"] = None
    state["structured_output_supported"] = None
    state["structured_output_source"] = None
    state["streaming_supported"] = None
    state["streaming_source"] = None
    state["context_window_tokens"] = None
    state["context_window_source"] = None
    state["max_output_tokens"] = None
    state["max_output_source"] = None


def _provider_flag(provider_obj: Any, *, method_name: str, key: str) -> bool:
    """Read provider booleans from live provider objects or serialized snapshots."""
    if not provider_obj:
        return False

    method = getattr(provider_obj, method_name, None)
    if callable(method):
        try:
            return bool(method())
        except Exception as exc:
            logger.debug(
                "[LLM_SELECTABILITY] provider.%s() failed: %s",
                method_name,
                exc,
            )
            return False

    if isinstance(provider_obj, Mapping):
        return bool(provider_obj.get(key))

    return bool(getattr(provider_obj, key, False))


def _resolve_required_capability_reason(
    state: dict[str, Any],
    *,
    provider: str | None = None,
) -> ProviderDisabledReasonCode | None:
    provider_key = str(provider or "").strip().lower()
    required_capabilities = (
        _PROVIDER_REQUIRED_CAPABILITIES.get(provider_key)
        if getattr(settings, "use_multi_agent", True)
        else ("streaming",)
    )
    if not required_capabilities:
        required_capabilities = ("streaming", "structured_output", "tool_calling")

    capability_checks = [
        _CAPABILITY_FIELDS[capability]
        for capability in required_capabilities
        if capability in _CAPABILITY_FIELDS
    ]

    has_unknown_capability = False
    for flag_field, source_field in capability_checks:
        flag = state.get(flag_field)
        source = str(state.get(source_field) or "").strip().lower()
        # A partial live-probe timeout should not hide a provider that still
        # has catalog-backed capabilities and succeeds in real traffic.
        if source == "probe_failed":
            continue
        if flag is False:
            return "capability_missing"
        if flag is None:
            has_unknown_capability = True

    if has_unknown_capability:
        return "verifying"
    return None


def _resolve_disabled_reason(
    provider: str,
    *,
    runtime_available: bool,
    audit_available: bool,
    state: dict[str, Any],
) -> ProviderDisabledReasonCode | None:
    if not audit_available:
        if runtime_available:
            return None
        if provider == "ollama":
            return "host_down"
        return "verifying"

    signal_text = _collect_signal_texts(state)
    has_catalog_truth = bool(
        state.get("selected_model")
        and (
            state.get("model_count", 0)
            or state.get("last_discovery_attempt_at")
            or state.get("last_discovery_success_at")
        )
    )
    if (has_catalog_truth and state.get("selected_model_in_catalog") is False) or any(
        marker in signal_text for marker in _MODEL_MISSING_MARKERS
    ):
        return "model_missing"

    if runtime_available and _latest_runtime_observation_failed(state):
        if not _is_stale_runtime_failure(state):
            return "busy"

    if any(marker in signal_text for marker in _BUSY_MARKERS):
        if runtime_available and _is_stale_busy_signal(state):
            logger.info(
                "[LLM_SELECTABILITY] Ignoring stale busy signal for provider=%s (last_probe=%s)",
                provider,
                state.get("last_live_probe_attempt_at") or state.get("last_discovery_attempt_at"),
            )
        else:
            return "busy"

    capability_reason = _resolve_required_capability_reason(state, provider=provider)
    if capability_reason is not None:
        if (
            capability_reason == "verifying"
            and runtime_available
            and _latest_runtime_observation_succeeded(state)
        ):
            return None
        return capability_reason

    if _latest_runtime_observation_succeeded(state):
        return None

    if provider == "ollama" and any(marker in signal_text for marker in _HOST_DOWN_MARKERS):
        if _live_streaming_probe_supersedes_host_down_signal(state):
            logger.info(
                "[LLM_SELECTABILITY] Ignoring Ollama host-down marker after "
                "successful live streaming probe",
            )
        else:
            return "host_down"

    if not runtime_available:
        if provider == "ollama":
            return "host_down"
        return "busy"

    if not state.get("last_live_probe_attempt_at") and not state.get("last_live_probe_success_at"):
        return "verifying"

    return None


def get_llm_selectability_snapshot(
    *,
    force_refresh: bool = False,
) -> list[ProviderSelectability]:
    """Return normalized runtime selectability for all supported providers."""
    global _selectability_cache

    now = time.monotonic()
    cache_generation = get_llm_selectability_cache_generation()
    if (
        not force_refresh
        and _selectability_cache is not None
        and _selectability_cache.generation == cache_generation
        and now - _selectability_cache.created_at < SELECTABILITY_CACHE_TTL_SECONDS
    ):
        return copy.deepcopy(_selectability_cache.snapshot)

    stats = LLMPool.get_stats()
    request_selectable = set(stats.get("request_selectable_providers", []))
    active_provider = stats.get("active_provider")
    fallback_provider = stats.get("fallback_provider")

    audit_record, audit_payload = _load_runtime_audit_payload()
    audit_updated_at = audit_payload.get("audit_updated_at")
    audit_providers = audit_payload.get("providers", {})
    audit_available = bool(audit_record and audit_record.persisted and audit_updated_at)

    snapshot: list[ProviderSelectability] = []
    for provider_name in get_supported_provider_names():
        provider_obj = LLMPool.get_provider_info(provider_name)
        configured = _provider_flag(
            provider_obj,
            method_name="is_configured",
            key="configured",
        )
        runtime_available = _provider_flag(
            provider_obj,
            method_name="is_available",
            key="available",
        )
        is_request_selectable = provider_name in request_selectable
        selected_model = _selected_model_for_provider(provider_name)
        provider_state = (
            dict(audit_providers.get(provider_name, {}))
            if isinstance(audit_providers, dict)
            else {}
        )
        persisted_selected_model = provider_state.get("selected_model")
        model_changed = bool(
            selected_model
            and isinstance(persisted_selected_model, str)
            and persisted_selected_model.strip()
            and persisted_selected_model.strip() != selected_model
        )
        if model_changed:
            _clear_stale_provider_state_for_model_change(
                provider_state,
                selected_model=selected_model,
            )
        provider_audit_available = (
            audit_available
            and not model_changed
            and _has_provider_audit_truth(provider_state)
        )
        if selected_model and not provider_state.get("selected_model"):
            provider_state["selected_model"] = selected_model

        state: ProviderSelectabilityState
        reason_code: ProviderDisabledReasonCode | None = None
        reason_label: str | None = None

        if not configured or not is_request_selectable:
            state = "hidden"
        else:
            reason_code = _resolve_disabled_reason(
                provider_name,
                runtime_available=runtime_available,
                audit_available=provider_audit_available,
                state=provider_state,
            )
            if reason_code == "verifying" and provider_audit_available and runtime_available:
                capability_reason = _resolve_required_capability_reason(
                    provider_state,
                    provider=provider_name,
                )
                if capability_reason is None and provider_state.get("selected_model_in_catalog", False):
                    reason_code = None
            if reason_code is None:
                state = "selectable"
            else:
                state = "disabled"
                reason_label = _friendly_reason_label(reason_code or "busy")

        verified_at = (
            provider_state.get("last_live_probe_success_at")
            or provider_state.get("last_live_probe_attempt_at")
            or (audit_updated_at if provider_audit_available else None)
        )
        snapshot.append(
            ProviderSelectability(
                provider=provider_name,
                display_name=_provider_display_name(provider_name),
                state=state,
                reason_code=reason_code,
                reason_label=reason_label,
                selected_model=provider_state.get("selected_model") or selected_model,
                strict_pin=True,
                verified_at=verified_at,
                available=(state == "selectable"),
                configured=configured,
                request_selectable=is_request_selectable,
                is_primary=(provider_name == active_provider),
                is_fallback=(provider_name == fallback_provider),
            )
        )

    _selectability_cache = _CacheEntry(
        created_at=now,
        generation=cache_generation,
        snapshot=copy.deepcopy(snapshot),
    )
    return snapshot


def get_provider_selectability(provider: str) -> Optional[ProviderSelectability]:
    normalized = str(provider).strip().lower()
    for item in get_llm_selectability_snapshot():
        if item.provider == normalized:
            return item
    return None


def _refresh_provider_selectability(provider: str) -> Optional[ProviderSelectability]:
    normalized = str(provider).strip().lower()
    for item in get_llm_selectability_snapshot(force_refresh=True):
        if item.provider == normalized:
            return item
    return None


def choose_best_runtime_provider(
    *,
    preferred_provider: str | None = None,
    provider_order: list[str] | tuple[str, ...] | None = None,
    allow_degraded_fallback: bool = True,
    force_refresh: bool = False,
) -> Optional[ProviderSelectability]:
    """Choose the best currently-runnable provider for auto-mode routing.

    Priority order:
      1. selectable providers
      2. degraded-but-routable providers (for example stale capability audit)
      3. everything else is ignored

    This keeps auto mode aligned with runtime truth while still avoiding
    needless loops back into a provider that is already known to be busy.
    """

    snapshot = get_llm_selectability_snapshot(force_refresh=force_refresh)
    by_provider = {item.provider: item for item in snapshot}
    preferred = str(preferred_provider or "").strip().lower() or None

    ordered_names: list[str] = []
    if provider_order:
        for raw_name in provider_order:
            name = str(raw_name or "").strip().lower()
            if name and name not in ordered_names:
                ordered_names.append(name)
    for item in snapshot:
        if item.provider not in ordered_names:
            ordered_names.append(item.provider)

    ranked_candidates: list[tuple[int, int, int, ProviderSelectability]] = []
    degraded_rank = {
        "capability_missing": 1,
        "verifying": 2,
    }

    for index, provider_name in enumerate(ordered_names):
        item = by_provider.get(provider_name)
        if item is None or not item.configured or not item.request_selectable:
            continue

        rank = 99
        if item.state == "selectable":
            rank = 0
        elif (
            allow_degraded_fallback
            and item.state == "disabled"
            and item.reason_code in _DEGRADED_BUT_ROUTABLE_REASON_CODES
        ):
            rank = degraded_rank.get(item.reason_code or "", 3)

        if rank >= 99:
            continue

        preference_penalty = 0 if preferred and provider_name == preferred else 1
        ranked_candidates.append((rank, preference_penalty, index, item))

    if not ranked_candidates:
        return None

    ranked_candidates.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
    return ranked_candidates[0][3]


def ensure_provider_is_selectable(provider: str | None) -> ProviderSelectability | None:
    normalized = str(provider).strip().lower() if provider else ""
    if not normalized or normalized == "auto":
        return None

    item = get_provider_selectability(normalized)
    if (
        normalized == "ollama"
        and item is not None
        and item.state == "disabled"
        and item.reason_code == "host_down"
    ):
        refreshed = _refresh_provider_selectability(normalized)
        if refreshed is not None:
            item = refreshed

    if item is not None and item.state == "selectable":
        return item
    # Explicit user pin: allow degraded-but-routable states (e.g.
    # capability_missing, verifying) — the user accepted the trade-off when
    # they chose this provider. Selectable fallback ranking still treats
    # these as second-tier candidates.
    if (
        item is not None
        and item.configured
        and item.request_selectable
        and item.state == "disabled"
        and item.reason_code in _DEGRADED_BUT_ROUTABLE_REASON_CODES
    ):
        logger.info(
            "[LLM_SELECTABILITY] Allowing pinned degraded provider=%s reason=%s "
            "(explicit user pin overrides degraded-but-routable state)",
            normalized,
            item.reason_code,
        )
        return item

    reason_code = item.reason_code if item and item.reason_code else "verifying"
    if item and item.state == "hidden":
        reason_label = "Provider nay hien khong duoc bat cho request-level selection."
    else:
        reason_label = item.reason_label if item and item.reason_label else _friendly_reason_label("verifying")
    raise ProviderUnavailableError(
        provider=normalized,
        reason_code=reason_code or "verifying",
        message=reason_label,
    )
