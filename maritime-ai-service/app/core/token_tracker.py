"""
Token & Cost Tracker — Per-Request LLM Usage Accounting.

SOTA 2026: Track token usage and estimated cost per request.
Uses ContextVar for request-scoped isolation (like Request-ID middleware).
"""

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

KNOWN_TRACKING_PROVIDER_PREFIXES = (
    "google",
    "openai",
    "openrouter",
    "ollama",
    "zhipu",
    "vertex",
)

_current_tracker: ContextVar[Optional["TokenTracker"]] = ContextVar(
    "token_tracker", default=None
)


@dataclass
class LLMCall:
    """Single LLM invocation record."""

    model: str
    tier: str  # deep / moderate / light
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    component: str = ""  # e.g. "supervisor", "rag_agent"


def split_tracking_tier(raw_tier: str) -> Tuple[str, str]:
    """Infer provider and normalized tier from callback tier labels."""
    tier_text = (raw_tier or "").strip()
    if not tier_text:
        return "", ""

    if tier_text.startswith("fallback_"):
        return "", tier_text.removeprefix("fallback_")

    if "_" not in tier_text:
        return "", tier_text

    provider, normalized_tier = tier_text.split("_", 1)
    if provider in KNOWN_TRACKING_PROVIDER_PREFIXES:
        return provider, normalized_tier
    return "", tier_text


@dataclass
class TokenTracker:
    """Accumulates token usage for a single request."""

    request_id: str = ""
    calls: List[LLMCall] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def record(self, call: LLMCall) -> None:
        """Record a single LLM call."""
        self.calls.append(call)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate cost based on Gemini Flash pricing (2026)."""
        # Gemini 3 Flash: $0.075/1M input, $0.30/1M output
        input_cost = self.total_input_tokens * 0.075 / 1_000_000
        output_cost = self.total_output_tokens * 0.30 / 1_000_000
        return input_cost + output_cost

    def summary(self) -> Dict:
        """Return summary dict suitable for API response metadata."""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "duration_ms": round((time.time() - self.start_time) * 1000, 1),
        }


def start_tracking(request_id: str = "") -> TokenTracker:
    """Start token tracking for the current request context."""
    tracker = TokenTracker(request_id=request_id)
    _current_tracker.set(tracker)
    return tracker


def get_tracker() -> Optional[TokenTracker]:
    """Get the current request's token tracker, if any."""
    return _current_tracker.get()


def record_llm_call(
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    provider: str = "",
    duration_ms: float = 0.0,
    estimated_cost_usd: float = 0.0,
    component: str = "",
) -> None:
    """Record an LLM call on the current request tracker."""
    tracker = _current_tracker.get()
    if tracker is not None:
        tracker.record(
            LLMCall(
                model=model,
                tier=tier,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                estimated_cost_usd=estimated_cost_usd,
                component=component,
            )
        )

