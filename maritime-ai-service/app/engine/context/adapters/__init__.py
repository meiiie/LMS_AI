"""Host Adapter registry — returns the right adapter for each host_type.

Sprint 222: Universal Context Engine.
Usage:
    from app.engine.context.adapters import get_host_adapter
    adapter = get_host_adapter("lms")
    prompt_block = adapter.format_context_for_prompt(host_context)
"""
import logging
from functools import lru_cache

from app.engine.context.adapters.base import HostAdapter

logger = logging.getLogger(__name__)

_adapters: dict[str, HostAdapter] = {}


@lru_cache(maxsize=16)
def get_host_adapter(host_type: str) -> HostAdapter:
    """Get the adapter for a host_type. Falls back to GenericHostAdapter."""
    if not _adapters:
        _register_builtin_adapters()
    adapter = _adapters.get(host_type)
    if adapter:
        return adapter
    logger.debug("No adapter for host_type=%s, using generic", host_type)
    return _adapters["generic"]


def register_host_adapter(adapter: HostAdapter) -> None:
    """Register a custom adapter (e.g., from a domain plugin)."""
    _adapters[adapter.host_type] = adapter
    get_host_adapter.cache_clear()


def _register_builtin_adapters() -> None:
    """Lazy-load and register the built-in adapters."""
    from app.engine.context.adapters.generic import GenericHostAdapter
    from app.engine.context.adapters.lms import LMSHostAdapter
    from app.engine.context.adapters.wiii_desktop import (
        WiiiDesktopHostAdapter,
        WiiiWebHostAdapter,
    )

    # Sprint 222 Phase F2 (2026-05-06): WiiiDesktop / WiiiWeb adapters
    # added so AI knows when user is on standalone Wiii (not embedded
    # in LMS) — prevents "panel LMS / làm mới trang LMS" hallucination.
    for cls in [LMSHostAdapter, WiiiDesktopHostAdapter, WiiiWebHostAdapter, GenericHostAdapter]:
        instance = cls()
        _adapters[instance.host_type] = instance
