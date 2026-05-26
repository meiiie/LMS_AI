"""Failover runtime helpers extracted from llm_pool."""

from __future__ import annotations

import re
from inspect import isawaitable
from typing import Any, Callable, Optional


from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_model_health import record_model_failure, record_model_success
from app.engine.llm_same_provider_runtime import extract_runtime_model_name_impl
from app.engine.llm_timeout_policy import resolve_timeout_override


def is_rate_limit_error_impl(error: Exception) -> bool:
    """Check if an exception is a rate-limit (429) error from any provider."""
    err_str = str(error).lower()
    return any(
        marker in err_str
        for marker in [
            "429",
            "resource_exhausted",
            "rate_limit",
            "rate limit",
            "quota",
            "too many requests",
        ]
    )


def resolve_primary_timeout_seconds_impl(
    *,
    tier: str,
    timeout_profile: Optional[str],
    provider: Optional[str],
    settings_obj,
    timeout_profile_by_name: dict[str, str],
    timeout_profile_settings: dict[str, str],
    loads_timeout_provider_overrides_fn,
    primary_timeout_default: float,
    pool_cls,
    timeout_profile_structured: str,
    timeout_profile_background: str,
    model_name: Optional[str] = None,
) -> float | None:
    """Resolve the first-response timeout for one invocation."""
    normalized_profile = str(timeout_profile or "").strip().lower()
    if normalized_profile == timeout_profile_background:
        profile_key = timeout_profile_by_name["background"]
    elif normalized_profile == timeout_profile_structured:
        profile_key = timeout_profile_by_name["structured"]
    else:
        normalized_tier = pool_cls._normalize_tier_key(tier)
        profile_key = timeout_profile_by_name.get(normalized_tier, "moderate_seconds")

    attr_name = timeout_profile_settings[profile_key]
    normalized_provider = pool_cls._normalize_provider(provider)
    if normalized_provider:
        overrides = loads_timeout_provider_overrides_fn(
            getattr(settings_obj, "llm_timeout_provider_overrides", "{}")
        )
        override_value = resolve_timeout_override(
            overrides=overrides,
            provider=normalized_provider,
            profile_key=profile_key,
            model_name=model_name,
        )
        if override_value is not None:
            return override_value if override_value > 0 else None

    fallback_default = {
        "llm_primary_timeout_light_seconds": primary_timeout_default,
        "llm_primary_timeout_moderate_seconds": 25.0,
        "llm_primary_timeout_deep_seconds": 45.0,
        "llm_primary_timeout_structured_seconds": 60.0,
        "llm_primary_timeout_background_seconds": 0.0,
    }[attr_name]
    timeout = float(getattr(settings_obj, attr_name, fallback_default) or 0.0)
    return timeout if timeout > 0 else None


def is_failover_eligible_error_impl(error: Exception) -> bool:
    """Check if an exception should trigger cross-provider failover."""
    if isinstance(error, ProviderUnavailableError):
        return True

    err_str = str(error).lower()
    err_type = type(error).__name__.lower()
    markers = (
        "401",
        "403",
        "429",
        "500",
        "502",
        "503",
        "504",
        "api key invalid",
        "invalid api key",
        "api_key_invalid",
        "permission denied",
        "permission_denied",
        "forbidden",
        "unauthenticated",
        "authentication",
        "auth error",
        "service unavailable",
        "temporarily unavailable",
        "resource_exhausted",
        "rate_limit",
        "rate limit",
        "quota",
        "too many requests",
        "host unreachable",
        "unreachable",
        "connection refused",
        "connection reset",
        "connecterror",
        "remoteprotocolerror",
        "dependency_missing",
        "readtimeout",
        "connecttimeout",
        "timed out",
        "timeout",
    )
    if any(marker in err_str for marker in markers):
        return True

    return any(
        marker in err_type
        for marker in (
            "timeout",
            "connecterror",
            "readerror",
            "protocolerror",
            "apierror",
            "authenticationerror",
            "permissiondenied",
        )
    )


_FAILOVER_REASON_LABELS: dict[str, str] = {
    "rate_limit": "Provider vượt giới hạn hoặc đang bị quota/rate limit.",
    "auth_error": "Xác thực provider thất bại.",
    "provider_unavailable": "Provider tạm thời không khả dụng.",
    "host_down": "Host dịch vụ hoặc local runtime hiện không sẵn sàng.",
    "server_error": "Provider trả về lỗi máy chủ.",
    "timeout": "Provider phản hồi quá lâu và đã bị timeout.",
    "provider_stream_interrupted": "Luồng phản hồi từ provider bị ngắt giữa chừng.",
}


def _compact_failover_detail(value: Any, *, max_length: int = 220) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def classify_failover_reason_impl(
    *,
    reason: str | None = None,
    error: Exception | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Map raw retry/failover signals to a stable taxonomy."""
    raw_reason = str(reason or "").strip()
    normalized_reason = raw_reason.lower()
    err = error
    err_text = str(err or "").lower()
    err_type = type(err).__name__ if err is not None else None

    reason_code = "provider_unavailable"
    reason_category = "provider_unavailable"

    if timeout_seconds is not None or normalized_reason.startswith("timeout"):
        reason_code = "timeout"
        reason_category = "timeout"
    elif isinstance(err, ProviderUnavailableError):
        if err.reason_code == "host_down":
            reason_code = "host_down"
            reason_category = "host_down"
        elif err.reason_code == "busy":
            reason_code = "rate_limit"
            reason_category = "rate_limit"
        else:
            reason_code = "provider_unavailable"
            reason_category = "provider_unavailable"
    elif is_rate_limit_error_impl(err or Exception("")):
        reason_code = "rate_limit"
        reason_category = "rate_limit"
    elif any(
        marker in err_text
        for marker in (
            "401",
            "403",
            "invalid api key",
            "api key invalid",
            "permission denied",
            "forbidden",
            "unauthenticated",
            "authentication",
            "auth error",
        )
    ):
        reason_code = "auth_error"
        reason_category = "auth_error"
    elif any(
        marker in err_text
        for marker in (
            "incomplete chunked read",
            "peer closed connection without sending complete message body",
        )
    ):
        reason_code = "provider_stream_interrupted"
        reason_category = "provider_stream_interrupted"
    elif any(
        marker in err_text
        for marker in (
            "host unreachable",
            "connection refused",
            "connection reset",
            "connecterror",
            "dependency_missing",
            "remoteprotocolerror",
            "unreachable",
        )
    ) or normalized_reason == "circuit_breaker_open":
        reason_code = "host_down"
        reason_category = "host_down"
    elif any(
        marker in err_text
        for marker in (
            "500",
            "502",
            "503",
            "504",
            "service unavailable",
            "temporarily unavailable",
            "server error",
        )
    ):
        reason_code = "server_error"
        reason_category = "server_error"

    return {
        "reason_code": reason_code,
        "reason_category": reason_category,
        "reason_label": _FAILOVER_REASON_LABELS.get(reason_category),
        "raw_reason": raw_reason or None,
        "error_type": err_type,
        "detail": _compact_failover_detail(err or raw_reason),
        "timeout_seconds": timeout_seconds,
    }


def build_failover_event_impl(
    *,
    from_provider: str,
    to_provider: str,
    reason: str | None = None,
    error: Exception | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    classified = classify_failover_reason_impl(
        reason=reason,
        error=error,
        timeout_seconds=timeout_seconds,
    )
    return {
        "from_provider": str(from_provider or "").strip().lower() or None,
        "to_provider": str(to_provider or "").strip().lower() or None,
        **classified,
    }


async def ainvoke_with_failover_impl(
    llm,
    messages,
    *,
    tier: str,
    provider: Optional[str],
    failover_mode: str,
    prefer_selectable_fallback: bool,
    allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None,
    on_primary: Optional[Callable[[Any], Any]],
    on_fallback: Optional[Callable[[Any], Any]],
    on_switch: Optional[Callable[[str, str, str], Any]],
    on_failover: Optional[Callable[[dict[str, Any]], Any]],
    primary_timeout: Optional[float],
    timeout_profile: Optional[str],
    pool_cls,
    resolve_primary_timeout_seconds_fn,
    is_rate_limit_error_fn,
    is_failover_eligible_error_fn,
    logger_obj,
    failover_mode_pinned: str,
    provider_unavailable_error_cls,
    resolve_same_provider_model_fallback_fn,
    create_llm_with_model_for_provider_fn,
    thinking_tier_cls,
):
    """Invoke LLM with automatic runtime failover on provider-side failures."""
    import asyncio

    normalized_failover_mode = pool_cls._normalize_failover_mode(failover_mode)
    route = pool_cls.resolve_runtime_route(
        provider,
        tier,
        failover_mode=normalized_failover_mode,
        prefer_selectable_fallback=prefer_selectable_fallback,
        allowed_fallback_providers=allowed_fallback_providers,
    )
    primary_llm = route.llm
    if on_primary is not None:
        primary_llm = on_primary(primary_llm)
    elif getattr(llm, "_wiii_provider_name", None) == route.provider or route.provider is None:
        primary_llm = llm

    primary_model_name = extract_runtime_model_name_impl(primary_llm)
    timeout = (
        primary_timeout
        if primary_timeout is not None
        else resolve_primary_timeout_seconds_fn(
            tier=tier,
            timeout_profile=timeout_profile,
            provider=route.provider,
            model_name=primary_model_name,
        )
    )

    def _prepare_fallback():
        fallback_llm = route.fallback_llm
        if fallback_llm is None:
            return None
        if on_fallback is not None:
            fallback_llm = on_fallback(fallback_llm)
        return fallback_llm

    def _prepare_same_provider_fallback():
        plan = resolve_same_provider_model_fallback_fn(
            route.provider,
            tier,
            current_model_name=primary_model_name,
        )
        if not plan:
            return None, None

        fallback_tier = getattr(thinking_tier_cls, plan["to_tier"].upper(), None)
        if fallback_tier is None:
            return None, None

        fallback_llm = create_llm_with_model_for_provider_fn(
            route.provider,
            plan["to_model"],
            fallback_tier,
        )
        if fallback_llm is None:
            return None, None
        if on_fallback is not None:
            fallback_llm = on_fallback(fallback_llm)
        return plan, fallback_llm

    async def _invoke_callback(callback, *args):
        if callback is None:
            return None
        result = callback(*args)
        if isawaitable(result):
            return await result
        return result

    async def _emit_switch(*, reason: str, error: Exception | None = None) -> None:
        primary_name = route.provider or "unknown"
        fallback_name = route.fallback_provider or "unknown"
        event = build_failover_event_impl(
            from_provider=primary_name,
            to_provider=fallback_name,
            reason=reason,
            error=error,
            timeout_seconds=timeout if isinstance(error, asyncio.TimeoutError) else None,
        )
        logger_obj.warning(
            "[LLM_FAILOVER] %s -> %s reason=%s category=%s detail=%s tier=%s",
            primary_name,
            fallback_name,
            event["reason_code"],
            event["reason_category"],
            event.get("detail"),
            tier,
        )
        if route.fallback_provider:
            await _invoke_callback(
                on_switch,
                primary_name,
                fallback_name,
                event["reason_code"],
            )
            await _invoke_callback(on_failover, event)

    async def _emit_same_provider_switch(
        plan: dict[str, str],
        *,
        reason: str,
        error: Exception | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        event = build_failover_event_impl(
            from_provider=plan["provider"],
            to_provider=plan["provider"],
            reason=reason,
            error=error,
            timeout_seconds=timeout_seconds,
        )
        event["fallback_scope"] = "same_provider_model"
        event["from_model"] = plan["from_model"]
        event["to_model"] = plan["to_model"]
        event["from_tier"] = plan["from_tier"]
        event["to_tier"] = plan["to_tier"]
        logger_obj.warning(
            "[LLM_MODEL_FALLBACK] %s/%s -> %s/%s reason=%s category=%s detail=%s",
            plan["provider"],
            plan["from_model"],
            plan["provider"],
            plan["to_model"],
            event["reason_code"],
            event["reason_category"],
            event.get("detail"),
        )
        await _invoke_callback(
            on_switch,
            plan["provider"],
            plan["provider"],
            event["reason_code"],
        )
        await _invoke_callback(on_failover, event)

    cb = route.circuit_breaker
    if cb is not None and not cb.is_available():
        fb = _prepare_fallback()
        if fb is not None:
            await _emit_switch(reason="circuit_breaker_open")
            return await fb.ainvoke(messages)
        if normalized_failover_mode == failover_mode_pinned:
            raise provider_unavailable_error_cls(
                provider=route.provider or (provider or "unknown"),
                reason_code="busy",
                message="Provider duoc chon tam thoi ban hoac da cham gioi han.",
            )

    try:
        if timeout and timeout > 0:
            result = await asyncio.wait_for(primary_llm.ainvoke(messages), timeout=timeout)
        else:
            result = await primary_llm.ainvoke(messages)
        record_model_success(route.provider, primary_model_name)
        await asyncio.shield(pool_cls.record_success_for_provider(route.provider))
        return result
    except (asyncio.TimeoutError, Exception) as exc:
        is_timeout = isinstance(exc, asyncio.TimeoutError)
        is_failover_eligible = (
            is_timeout
            or is_rate_limit_error_fn(exc)
            or is_failover_eligible_error_fn(exc)
        )
        if not is_failover_eligible:
            raise

        await asyncio.shield(pool_cls.record_failure_for_provider(route.provider))
        classified_primary_failure = classify_failover_reason_impl(
            error=exc,
            timeout_seconds=timeout if is_timeout else None,
        )
        record_model_failure(
            route.provider,
            primary_model_name,
            reason_code=classified_primary_failure["reason_code"],
            error=exc,
            timeout_seconds=timeout if is_timeout else None,
        )

        same_provider_plan = None
        same_provider_llm = None
        same_provider_error: Exception | None = None
        if is_timeout or is_rate_limit_error_fn(exc):
            same_provider_plan, same_provider_llm = _prepare_same_provider_fallback()
        if same_provider_plan is not None and same_provider_llm is not None:
            same_timeout = resolve_primary_timeout_seconds_fn(
                tier=same_provider_plan["to_tier"],
                timeout_profile=timeout_profile,
                provider=route.provider,
                model_name=same_provider_plan["to_model"],
            )
            reason = f"timeout_{timeout}s" if is_timeout else type(exc).__name__
            await _emit_same_provider_switch(
                same_provider_plan,
                reason=reason,
                error=exc,
                timeout_seconds=timeout if is_timeout else None,
            )
            try:
                if same_timeout and same_timeout > 0:
                    result = await asyncio.wait_for(
                        same_provider_llm.ainvoke(messages),
                        timeout=same_timeout,
                    )
                else:
                    result = await same_provider_llm.ainvoke(messages)
                record_model_success(
                    same_provider_plan["provider"],
                    same_provider_plan["to_model"],
                )
                await asyncio.shield(pool_cls.record_success_for_provider(route.provider))
                return result
            except Exception as same_exc:
                same_provider_error = same_exc
                same_is_timeout = isinstance(same_exc, asyncio.TimeoutError)
                classified_same_failure = classify_failover_reason_impl(
                    error=same_exc,
                    timeout_seconds=same_timeout if same_is_timeout else None,
                )
                record_model_failure(
                    same_provider_plan["provider"],
                    same_provider_plan["to_model"],
                    reason_code=classified_same_failure["reason_code"],
                    error=same_exc,
                    timeout_seconds=same_timeout if same_is_timeout else None,
                )
                logger_obj.warning(
                    "[LLM_MODEL_FALLBACK] Same-provider fallback failed: provider=%s model=%s detail=%s",
                    same_provider_plan["provider"],
                    same_provider_plan["to_model"],
                    _compact_failover_detail(same_exc),
                )

        fb = _prepare_fallback()
        if fb is None:
            if same_provider_error is not None:
                if is_timeout:
                    raise TimeoutError(
                        "Primary LLM timed out after "
                        f"{timeout}s and same-provider fallback also failed"
                    ) from same_provider_error
                raise same_provider_error
            if is_timeout:
                raise TimeoutError(
                    f"Primary LLM timed out after {timeout}s, no fallback available"
                )
            raise

        reason = f"timeout_{timeout}s" if is_timeout else type(exc).__name__
        await _emit_switch(reason=reason, error=exc)
        fallback_timeout = timeout * 2 if (timeout and timeout > 0) else None
        fallback_model_name = extract_runtime_model_name_impl(fb)
        try:
            if fallback_timeout:
                result = await asyncio.wait_for(
                    fb.ainvoke(messages),
                    timeout=fallback_timeout,
                )
            else:
                result = await fb.ainvoke(messages)
        except Exception as fallback_exc:
            fallback_is_timeout = isinstance(fallback_exc, asyncio.TimeoutError)
            classified_fallback_failure = classify_failover_reason_impl(
                error=fallback_exc,
                timeout_seconds=fallback_timeout if fallback_is_timeout else None,
            )
            record_model_failure(
                route.fallback_provider,
                fallback_model_name,
                reason_code=classified_fallback_failure["reason_code"],
                error=fallback_exc,
                timeout_seconds=fallback_timeout if fallback_is_timeout else None,
            )
            await asyncio.shield(
                pool_cls.record_failure_for_provider(route.fallback_provider)
            )
            raise
        record_model_success(route.fallback_provider, fallback_model_name)
        await asyncio.shield(pool_cls.record_success_for_provider(route.fallback_provider))
        return result
