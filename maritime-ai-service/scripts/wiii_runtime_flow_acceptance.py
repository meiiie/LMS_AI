#!/usr/bin/env python3
"""Runtime flow acceptance harness for Wiii chat.

This is a backend-only harness: it talks to Wiii HTTP endpoints, reads the
terminal SSE runtime trace/ledger, and verifies path/tool invariants that should
stay true regardless of prompt wording. It does not call external providers and
does not mutate LMS, host, or third-party apps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_evidence_output import emit_json_payload  # noqa: E402


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_ORG_ID = "default"
DEFAULT_DEMO_EMAIL = "dev@localhost"
DEFAULT_DEMO_NAME = "Dev User"
DEFAULT_DEMO_ROLE = "admin"
TOKEN_ENV = "WIII_ACCEPTANCE_BEARER_TOKEN"
TARGET_ENV = "WIII_ACCEPTANCE_TARGET_ENV"
COMMIT_SHA_ENV = "WIII_ACCEPTANCE_COMMIT_SHA"
TRACE_VERSION = "wiii.runtime_flow_acceptance.v1"
BROWSER_REPLAY_SCHEMA_VERSION = "wiii.runtime_flow_browser_replay.v1"
RUNTIME_FLOW_LEDGER_SCHEMA_VERSION = "wiii.runtime_flow_ledger.v1"
POST_TURN_LIFECYCLE_SUMMARY_VERSION = "wiii.post_turn_lifecycle.v1"
SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION = "wiii.subagent_boundary_trace.v1"
CONTEXT_PROVENANCE_SCHEMA_VERSION = "wiii.context_provenance_ledger.v1"

RAW_CHAT_MARKERS = (
    '"tool_calls"',
    '"function_call"',
    '"runtime_flow_ledger"',
    '"turn_path_decision"',
    "<wiii-widget",
    "[POINT:",
)
GLOBAL_FORBIDDEN_RUNTIME_TOOLS = (
    "tool_wiii_connect_execute_action",
    "host_action__wiii_connect__facebook_post__preview",
    "host_action__wiii_connect__facebook_post__apply",
)
MODEL_SURFACE_FORBIDDEN_KEYS = {
    "connection_ref",
    "connected_account_id",
    "connection_id",
    "image_base64",
    "image_filename",
    "image_media_type",
    "image_url",
    "page_id",
    "provider_payload",
    "raw_prompt",
}
RAW_CONTEXT_FORBIDDEN_KEYS = {
    "assistant_text",
    "body",
    "content",
    "core_memory",
    "document_markdown",
    "file_name",
    "filename",
    "markdown",
    "prompt",
    "raw_content",
    "raw_prompt",
    "raw_text",
    "semantic_context",
    "text",
    "user_text",
}
PUBLIC_TOOL_RESULT_RAW_CONTENT_KEYS = {
    "code_html",
    "course_patch",
    "course_plan",
    "document_text",
    "fallback_html",
    "full_code",
    "html",
    "lesson_patch",
    "markdown",
    "raw_html",
    "source_code",
    "visual_payload",
}
CONTEXT_PROVENANCE_REQUIRED_SECTIONS = (
    "conversation",
    "documents",
    "memory",
    "host",
    "privacy",
)
CONTEXT_PROVENANCE_STRING_MAX_LENGTH = 128
SUBAGENT_BOUNDARY_REPORT_COUNT_KEYS = (
    "state_projected_key_count",
    "state_dropped_key_count",
    "output_char_count",
    "source_count",
    "tool_count",
)
SUBAGENT_BOUNDARY_REPORT_RAW_KEYS = {
    "content",
    "data",
    "documents",
    "error_message",
    "output",
    "raw_child_output",
    "raw_output",
    "result",
    "sources",
    "summary",
    "thinking",
    "tool_result",
    "tools_used",
}

VALID_DOCTOR_STATUSES = frozenset({"ready", "degraded", "blocked"})
VALID_PATH_DOCTOR_STATUSES = frozenset({"ready", "guarded", "blocked"})
VALID_PROVIDER_DOCTOR_STATUSES = frozenset({"ready", "guarded", "blocked"})
VALID_PROVIDER_STAGE_STATUSES = frozenset({"ready", "pending", "blocked"})
DOCTOR_REQUIRED_SUMMARY_KEYS = (
    "total_paths",
    "ready_paths",
    "guarded_paths",
    "blocked_paths",
    "total_connections",
    "agent_ready_connections",
    "external_provider_connections",
    "external_agent_ready_connections",
    "warning_count",
)
DOCTOR_REQUIRED_PATHS = (
    "casual_chat",
    "weather_lookup",
    "external_app_action",
    "lms_document_preview",
    "lms_document_apply",
)
DOCTOR_REQUIRED_PROVIDER_STAGES = (
    "registry",
    "adapter",
    "account",
    "agent_policy",
    "gateway",
)
SNAPSHOT_REQUIRED_CAPABILITY_LISTS = (
    "active_connection_slugs",
    "agent_ready_connection_slugs",
    "connected_provider_slugs",
    "agent_ready_provider_slugs",
    "connected_scope_names",
    "suppressed_tool_groups",
    "path_readiness",
)
POST_TURN_LIFECYCLE_STATUSES = frozenset({"scheduled", "skipped", "error"})
POST_TURN_LIFECYCLE_POLICIES = frozenset(
    {"extract_facts", "skip_fact_extraction", "not_applicable"}
)
POST_TURN_LIFECYCLE_FORBIDDEN_KEYS = frozenset(
    {
        "domain_id",
        "message",
        "organization_id",
        "prompt",
        "request_id",
        "response",
        "response_text",
        "session_id",
        "text",
        "user_id",
    }
)

SENSITIVE_EXACT_KEYS = {
    "access_token",
    "api_key",
    "approval_token",
    "authorization",
    "authorization_url",
    "code",
    "connected_account_id",
    "connection_id",
    "connection_ref",
    "credential",
    "password",
    "provider_payload",
    "raw_prompt",
    "refresh_token",
    "secret",
    "state",
    "token",
    "vault_key_id",
}
SENSITIVE_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "connected_account",
    "connection_id",
    "provider_payload",
    "vault",
)
SAFE_SENSITIVE_DERIVED_KEY_SUFFIXES = (
    "_hash",
    "_hashes",
    "_present",
    "_ready",
    "_count",
    "_counts",
)


class AcceptanceFailure(RuntimeError):
    """Raised when an acceptance invariant is violated."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        return parse_json_object(self.text(), source=self.url)


@dataclass(frozen=True)
class SseEvent:
    name: str
    data: str

    def json(self) -> dict[str, Any] | None:
        return decode_json_object(self.data)


@dataclass(frozen=True)
class SseReadResult:
    events: list[SseEvent]
    first_event_seconds: float | None
    first_answer_seconds: float | None
    total_seconds: float


@dataclass(frozen=True)
class ScenarioExpectation:
    id: str
    prompt: str
    expected_path: str
    prelude_prompts: tuple[str, ...] = ()
    required_visible_tools: tuple[str, ...] = ()
    required_observed_tools: tuple[str, ...] = ()
    expected_stream_events: tuple[str, ...] = ()
    forbidden_stream_events: tuple[str, ...] = ()
    forbidden_tool_names: tuple[str, ...] = ()
    forbidden_tool_prefixes: tuple[str, ...] = ()
    require_no_visible_tools: bool = False
    require_answer: bool = True
    require_done: bool = True
    answer_must_contain_any: tuple[str, ...] = ()
    expected_external_plan_status: str = ""
    expected_external_provider: str = ""
    expected_external_kind: str = ""
    expected_worker_outcome: str = ""
    expected_final_answer_source: str = ""
    expected_min_uploaded_documents: int = 0
    expected_min_source_refs: int = 0
    expected_min_memory_contexts: int = 0
    expected_memory_retrieval_status: str = ""
    expected_min_relevant_memories: int = 0
    expected_min_user_facts: int = 0
    expected_min_subagent_reports: int = 0
    expected_subagent_warning_codes: tuple[str, ...] = ()
    expected_document_media_kinds: tuple[str, ...] = ()
    expected_document_source_ref_kinds: tuple[str, ...] = ()
    expected_host_surface: str = ""
    expected_host_capabilities: tuple[str, ...] = ()
    expected_context_warning_codes: tuple[str, ...] = ()
    expected_suppressed_tools: tuple[str, ...] = ()
    expect_preview_required: bool = False
    expect_no_apply_attempted: bool = False
    user_context: Mapping[str, Any] | None = None
    require_ledger_done_seen: bool = True
    sync_parity: bool = False


@dataclass
class ScenarioResult:
    scenario: ScenarioExpectation
    event_names: list[str]
    answer: str
    trace: dict[str, Any]
    ledger: dict[str, Any]
    first_event_seconds: float | None
    first_answer_seconds: float | None
    total_seconds: float
    events: list[SseEvent] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        path = path_from_trace(self.trace, self.ledger)
        visible_tools = visible_tool_names_from_trace(self.trace, self.ledger)
        observed_tools = observed_tool_names_from_ledger(self.ledger)
        suppressed_tools = suppressed_tool_names_from_ledger(self.ledger)
        plan = external_action_plan_from_trace(self.trace, self.ledger)
        return {
            "id": self.scenario.id,
            "prompt_hash": opaque_hash(self.scenario.prompt),
            "path": path,
            "visible_tools": visible_tools,
            "observed_tools": observed_tools,
            "suppressed_tools": suppressed_tools,
            "external_plan": redact_for_log(plan),
            "event_names": self.event_names,
            "answer_char_count": len(self.answer),
            "answer_hash": opaque_hash(self.answer) if self.answer else None,
            "first_event_seconds": self.first_event_seconds,
            "first_answer_seconds": self.first_answer_seconds,
            "total_seconds": round(self.total_seconds, 3),
        }

    def browser_replay_case(self) -> dict[str, Any]:
        """Return terminal metadata that can seed browser Runtime-tab acceptance.

        The browser replay contract intentionally carries the public terminal
        ledger/trace but not raw prompt text, raw answer text, or SSE event
        payloads. A Playwright harness can place ``assistant_metadata`` on a
        seeded assistant message and exercise the same UI path used by live
        browser sessions.
        """

        safe_ledger = redact_for_log(self.ledger)
        safe_trace = redact_for_log(self.trace)
        assert_no_sensitive_payload(
            safe_ledger,
            path=f"{self.scenario.id}.browser_replay.runtime_flow_ledger",
        )
        assert_no_sensitive_payload(
            safe_trace,
            path=f"{self.scenario.id}.browser_replay.runtime_flow_trace",
        )
        summary = self.summary()
        return {
            "schema": BROWSER_REPLAY_SCHEMA_VERSION,
            "scenario_id": self.scenario.id,
            "prompt_hash": opaque_hash(self.scenario.prompt),
            "path": summary["path"],
            "event_names": list(self.event_names),
            "assistant_content": "Runtime flow acceptance evidence replay.",
            "assistant_metadata": {
                "runtime_flow_ledger": safe_ledger,
                "runtime_flow_trace": safe_trace,
            },
            "timing": {
                "first_event_seconds": self.first_event_seconds,
                "first_answer_seconds": self.first_answer_seconds,
                "total_seconds": round(self.total_seconds, 3),
            },
        }


DEFAULT_SCENARIOS: tuple[ScenarioExpectation, ...] = (
    ScenarioExpectation(
        id="casual_chat_no_tools",
        prompt="xin chào Wiii",
        expected_path="casual_chat",
        sync_parity=True,
        require_no_visible_tools=True,
        forbidden_tool_prefixes=("tool_",),
        expected_suppressed_tools=(
            "host_action",
            "pointy_action",
            "visual_runtime",
            "code_studio",
        ),
        forbidden_stream_events=(
            "host_action",
            "host_action_result",
            "pointy_action",
            "visual_open",
            "visual_commit",
            "code_open",
            "code_complete",
        ),
    ),
    ScenarioExpectation(
        id="weather_intent_weather_only",
        prompt="nay thời tiết nóng nhỉ",
        expected_path="weather_lookup",
        sync_parity=True,
        required_visible_tools=("tool_current_weather",),
        forbidden_tool_names=("tool_web_search", "tool_fetch_url"),
        forbidden_tool_prefixes=("tool_pointy_", "tool_wiii_connect_"),
    ),
    ScenarioExpectation(
        id="facebook_connection_status_control_plane",
        prompt="Wiii có kết nối được Facebook không?",
        expected_path="external_connection_status",
        sync_parity=True,
        require_no_visible_tools=True,
        answer_must_contain_any=("Facebook", "Wiii Connect", "kết nối"),
    ),
    ScenarioExpectation(
        id="facebook_action_blocks_without_agent_ready_provider",
        prompt="Wiii đăng một bài bất kỳ lên Facebook đi",
        expected_path="external_app_action",
        sync_parity=True,
        require_no_visible_tools=True,
        answer_must_contain_any=("Facebook", "Wiii Connect", "kết nối"),
        expected_external_plan_status="blocked",
        expected_external_provider="facebook",
        expected_external_kind="facebook_post_direct_apply",
    ),
    ScenarioExpectation(
        id="facebook_action_continuation_blocks_without_agent_ready_provider",
        prelude_prompts=("Wiii co the dang bai len Facebook khong?",),
        prompt='dang bai: "xin chao minh la AI" la duoc',
        expected_path="external_app_action",
        require_no_visible_tools=True,
        answer_must_contain_any=("Facebook", "Wiii Connect", "agent-ready"),
        expected_external_plan_status="blocked",
        expected_external_provider="facebook",
        expected_external_kind="facebook_post_direct_apply",
    ),
    ScenarioExpectation(
        id="gmail_capability_status_control_plane",
        prompt="Wiii co the doc Gmail khong?",
        expected_path="external_connection_status",
        sync_parity=True,
        require_no_visible_tools=True,
        answer_must_contain_any=("Gmail", "Wiii Connect", "agent-ready"),
    ),
    ScenarioExpectation(
        id="gmail_action_continuation_blocks_without_agent_ready_provider",
        prelude_prompts=("Wiii co the doc Gmail khong?",),
        prompt="doc email moi nhat di",
        expected_path="external_app_action",
        require_no_visible_tools=True,
        answer_must_contain_any=("Gmail", "Wiii Connect", "agent-ready"),
        expected_external_plan_status="blocked",
        expected_external_provider="gmail",
        expected_external_kind="provider_action",
    ),
    ScenarioExpectation(
        id="external_action_missing_provider_blocks_before_tools",
        prompt="dang bai len mang xa hoi di",
        expected_path="external_app_action",
        sync_parity=True,
        require_no_visible_tools=True,
        answer_must_contain_any=("provider", "Wiii Connect"),
        expected_external_plan_status="blocked",
        expected_external_kind="provider_action",
    ),
    ScenarioExpectation(
        id="semantic_memory_turn_context_replay",
        prelude_prompts=(
            "Hay ghi nho: toi thich hoc bang vi du ngan va dang on COLREG Rule 15.",
        ),
        prompt=(
            "Dua tren dieu ban da nho ve cach hoc cua toi, "
            "goi y 2 cach on chu de do."
        ),
        expected_path="casual_chat",
        require_no_visible_tools=True,
        forbidden_tool_prefixes=("tool_",),
        answer_must_contain_any=("COLREG", "Rule 15", "vi du ngan"),
        expected_min_memory_contexts=1,
        expected_memory_retrieval_status="ready",
        expected_min_relevant_memories=1,
    ),
    ScenarioExpectation(
        id="visual_inline_figure_stream_replay",
        prompt=(
            "Tao mot visual inline dang timeline ve quy trinh abandon ship, "
            "dung hinh minh hoa trong cau tra loi."
        ),
        expected_path="visual_generation",
        required_visible_tools=("tool_generate_visual",),
        required_observed_tools=("visual_runtime",),
        expected_stream_events=("visual_open", "visual_commit"),
        forbidden_tool_prefixes=("tool_pointy_", "tool_wiii_connect_"),
    ),
    ScenarioExpectation(
        id="code_studio_app_stream_replay",
        prompt=(
            "Tao mot mini app Code Studio mo phong COLREG Rule 15 co slider "
            "va vung preview tuong tac."
        ),
        expected_path="visual_generation",
        required_visible_tools=("tool_create_visual_code",),
        required_observed_tools=("code_studio",),
        expected_stream_events=("code_open", "code_complete"),
        forbidden_tool_prefixes=("tool_pointy_", "tool_wiii_connect_"),
    ),
    ScenarioExpectation(
        id="uploaded_document_lms_preview_source_replay",
        prompt=(
            "Dua tren tai lieu vua upload, hay tao preview_lesson_patch "
            "co citation va source_references cho bai hoc hien tai."
        ),
        expected_path="lms_document_preview",
        expected_min_uploaded_documents=1,
        expected_min_source_refs=1,
        expected_document_media_kinds=("document",),
        expected_document_source_ref_kinds=("heading",),
        expected_host_surface="embed_lms",
        expected_host_capabilities=("lms", "host_action", "document_preview"),
        expect_preview_required=True,
        expect_no_apply_attempted=True,
        user_context={
            "display_name": "Teacher Replay",
            "role": "teacher",
            "language": "vi",
            "current_course_id": "acceptance-course",
            "current_course_name": "Khoa hoc replay",
            "current_module_id": "acceptance-lesson",
            "host_context": {
                "surface": "embed_lms",
                "host_type": "lms",
                "connector_id": "acceptance-lms",
                "host_user_id": "teacher-replay",
                "capabilities": ["lms", "host_action", "document_preview"],
            },
            "host_capabilities": {
                "host_type": "lms",
                "connector_id": "acceptance-lms",
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "authoring.apply_lesson_patch"},
                ],
            },
            "document_context": {
                "attachments": [
                    {
                        "file_name": "wiii-acceptance-source.docx",
                        "markdown": (
                            "WIII_ACCEPTANCE_DOC_MARKER\n"
                            "Noi dung kiem thu ve muc tieu bai hoc va tieu chi danh gia."
                        ),
                        "parser": "markitdown",
                        "parser_chain": ["mammoth"],
                        "media_kind": "document",
                        "provenance_level": "page",
                        "source_references": [
                            {
                                "content_type": "heading",
                                "page_start": 1,
                                "page_end": 1,
                            }
                        ],
                    }
                ],
                "source_refs": [{"kind": "heading", "page_start": 1}],
            },
        },
    ),
)


def join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def parse_json_object(raw_text: str, *, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure(f"Invalid JSON from {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"Expected JSON object from {source}")
    return payload


def decode_json_object(data: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def decode_json_value(data: str) -> Any | None:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def request_bytes(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    raise_http_errors: bool = True,
) -> HttpResponse:
    request_headers = {
        "User-Agent": "wiii-runtime-flow-acceptance/1.0",
        **dict(headers or {}),
    }
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
                url=url,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        if not raise_http_errors:
            return HttpResponse(
                status=exc.code,
                headers=dict(exc.headers.items()),
                body=body,
                url=url,
            )
        body_text = body.decode("utf-8", errors="replace")
        raise AcceptanceFailure(
            f"{method.upper()} {url} -> HTTP {exc.code}: {json_for_log(body_text)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AcceptanceFailure(f"{method.upper()} {url} failed: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AcceptanceFailure(
            f"{method.upper()} {url} timed out after {timeout:.1f}s"
        ) from exc


def request_sse_events(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    idle_timeout: float = 20.0,
    max_total_seconds: float = 120.0,
) -> SseReadResult:
    request_headers = {
        "User-Agent": "wiii-runtime-flow-acceptance/1.0",
        **dict(headers or {}),
    }
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method.upper(),
    )
    started_at = time.monotonic()
    events: list[SseEvent] = []
    event_name = "message"
    data_lines: list[str] = []
    first_event_seconds: float | None = None
    first_answer_seconds: float | None = None

    def elapsed() -> float:
        return time.monotonic() - started_at

    def flush() -> None:
        nonlocal event_name, data_lines, first_event_seconds, first_answer_seconds
        if event_name != "message" or data_lines:
            data = "\n".join(data_lines)
            events.append(SseEvent(name=event_name, data=data))
            current_elapsed = elapsed()
            if first_event_seconds is None:
                first_event_seconds = current_elapsed
            if event_name == "answer" and data.strip() and first_answer_seconds is None:
                first_answer_seconds = current_elapsed
        event_name = "message"
        data_lines = []

    try:
        with urllib.request.urlopen(request, timeout=idle_timeout) as response:
            if response.status != 200:
                raise AcceptanceFailure(f"{method.upper()} {url} -> HTTP {response.status}")
            while True:
                if max_total_seconds and elapsed() > max_total_seconds:
                    raise AcceptanceFailure(
                        f"{method.upper()} {url} exceeded SSE total budget "
                        f"{max_total_seconds:.1f}s"
                    )
                raw_line = response.readline()
                if raw_line == b"":
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
                if not line:
                    flush()
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip() or "message"
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
                    continue
            flush()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise AcceptanceFailure(
            f"{method.upper()} {url} -> HTTP {exc.code}: {json_for_log(body_text)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AcceptanceFailure(f"{method.upper()} {url} failed: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        if events:
            event_names = ",".join(dict.fromkeys(event.name for event in events))
            raise AcceptanceFailure(
                f"{method.upper()} {url} SSE idle timeout after {idle_timeout:.1f}s "
                f"(events so far: {event_names})"
            ) from exc
        raise AcceptanceFailure(
            f"{method.upper()} {url} had no SSE data for {idle_timeout:.1f}s"
        ) from exc

    return SseReadResult(
        events=events,
        first_event_seconds=first_event_seconds,
        first_answer_seconds=first_answer_seconds,
        total_seconds=elapsed(),
    )


def parse_sse_events(text: str) -> list[SseEvent]:
    events: list[SseEvent] = []
    event_name = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if event_name != "message" or data_lines:
            events.append(SseEvent(name=event_name, data="\n".join(data_lines)))
        event_name = "message"
        data_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
            continue

    flush()
    return events


def extract_event_content(event: SseEvent) -> str:
    payload = event.json()
    if payload is None:
        return event.data.strip()
    for key in ("content", "text", "delta"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract_answer(events: Iterable[SseEvent]) -> str:
    return "".join(
        extract_event_content(event)
        for event in events
        if event.name == "answer"
    ).strip()


def terminal_payload(events: Iterable[SseEvent], event_name: str) -> dict[str, Any]:
    for event in reversed(list(events)):
        if event.name != event_name:
            continue
        payload = event.json()
        if payload is not None:
            return payload
    return {}


def runtime_trace_from_events(events: list[SseEvent]) -> dict[str, Any]:
    done = terminal_payload(events, "done")
    metadata = terminal_payload(events, "metadata")
    for payload in (done, metadata):
        trace = payload.get("runtime_flow_trace") if isinstance(payload, dict) else None
        if isinstance(trace, dict):
            return trace
    return {}


def runtime_ledger_from_events(events: list[SseEvent]) -> dict[str, Any]:
    done = terminal_payload(events, "done")
    metadata = terminal_payload(events, "metadata")
    for payload in (done, metadata):
        ledger = payload.get("runtime_flow_ledger") if isinstance(payload, dict) else None
        if isinstance(ledger, dict):
            return ledger
    return {}


def chat_response_answer(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("answer") or "").strip()


def chat_response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def assert_sync_stream_parity_contract(
    *,
    scenario_id: str,
    scenario: ScenarioExpectation,
    sync_payload: Mapping[str, Any],
    stream_result: ScenarioResult,
) -> None:
    """Assert the sync JSON path and SSE path preserve the same public contract."""

    if sync_payload.get("status") != "success":
        raise AcceptanceFailure(
            f"{scenario_id}: sync parity response status={sync_payload.get('status')!r}"
        )
    sync_answer = chat_response_answer(sync_payload)
    if scenario.require_answer and not sync_answer:
        raise AcceptanceFailure(f"{scenario_id}: sync parity answer is empty")

    sync_metadata = chat_response_metadata(sync_payload)
    if not sync_metadata:
        raise AcceptanceFailure(f"{scenario_id}: sync parity metadata is missing")
    sync_post_turn = sync_metadata.get("post_turn_lifecycle")
    assert_post_turn_lifecycle_contract(
        sync_post_turn,
        path=f"{scenario_id}.sync.post_turn_lifecycle",
    )
    sync_trace = sync_metadata.get("runtime_flow_trace")
    if not isinstance(sync_trace, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: sync parity runtime_flow_trace missing")
    assert_runtime_surface_invariants(
        scenario_id=f"{scenario_id}.sync",
        trace=sync_trace,
        runtime_tools=visible_tool_names_from_trace(sync_trace, {}),
    )
    assert_sync_tool_surface_contract(
        scenario_id=scenario_id,
        scenario=scenario,
        sync_trace=sync_trace,
    )
    sync_path = path_from_trace(sync_trace, {})
    stream_path = path_from_trace(stream_result.trace, stream_result.ledger)
    if sync_path and stream_path and sync_path != stream_path:
        raise AcceptanceFailure(
            f"{scenario_id}: sync path {sync_path!r} != stream path {stream_path!r}"
        )

    stream_runtime = stream_result.ledger.get("runtime")
    if isinstance(stream_runtime, Mapping):
        stream_provider = str(stream_runtime.get("provider") or "").strip()
        sync_provider = str(sync_metadata.get("provider") or "").strip()
        if stream_provider and sync_provider and stream_provider != sync_provider:
            raise AcceptanceFailure(
                f"{scenario_id}: sync provider {sync_provider!r} != "
                f"stream provider {stream_provider!r}"
            )
    stream_finalization = stream_result.ledger.get("finalization")
    if isinstance(stream_finalization, Mapping):
        stream_post_turn = stream_finalization.get("post_turn_lifecycle")
        assert_post_turn_lifecycle_contract(
            stream_post_turn,
            path=f"{scenario_id}.stream.finalization.post_turn_lifecycle",
        )
        if (
            isinstance(sync_post_turn, Mapping)
            and isinstance(stream_post_turn, Mapping)
            and sync_post_turn.get("schema_version") != stream_post_turn.get("schema_version")
        ):
            raise AcceptanceFailure(
                f"{scenario_id}: sync/stream post-turn lifecycle schema mismatch"
            )
    assert_sync_external_plan_contract(
        scenario_id=scenario_id,
        scenario=scenario,
        sync_trace=sync_trace,
        stream_result=stream_result,
    )


def assert_sync_tool_surface_contract(
    *,
    scenario_id: str,
    scenario: ScenarioExpectation,
    sync_trace: Mapping[str, Any],
) -> None:
    sync_visible_tools = visible_tool_names_from_trace(sync_trace, {})
    if scenario.require_no_visible_tools and sync_visible_tools:
        raise AcceptanceFailure(
            f"{scenario_id}: sync visible tools not empty: {sync_visible_tools}"
        )
    for tool_name in scenario.required_visible_tools:
        if tool_name not in sync_visible_tools:
            raise AcceptanceFailure(
                f"{scenario_id}: sync required visible tool {tool_name!r} missing; "
                f"saw {sync_visible_tools}"
            )
    for tool_name in scenario.forbidden_tool_names:
        if tool_name in sync_visible_tools:
            raise AcceptanceFailure(
                f"{scenario_id}: sync forbidden tool {tool_name!r} visible"
            )
    for prefix in scenario.forbidden_tool_prefixes:
        leaked = [tool for tool in sync_visible_tools if tool.startswith(prefix)]
        if leaked:
            raise AcceptanceFailure(
                f"{scenario_id}: sync forbidden tool prefix {prefix!r} matched {leaked}"
            )


def assert_sync_external_plan_contract(
    *,
    scenario_id: str,
    scenario: ScenarioExpectation,
    sync_trace: Mapping[str, Any],
    stream_result: ScenarioResult,
) -> None:
    if not (
        scenario.expected_external_plan_status
        or scenario.expected_external_provider
        or scenario.expected_external_kind
    ):
        return

    sync_plan = external_action_plan_from_trace(sync_trace, {})
    stream_plan = external_action_plan_from_trace(
        stream_result.trace,
        stream_result.ledger,
    )
    expected_fields = (
        ("status", scenario.expected_external_plan_status),
        ("provider_slug", scenario.expected_external_provider),
        ("kind", scenario.expected_external_kind),
    )
    for key, expected in expected_fields:
        if not expected:
            continue
        sync_value = str(sync_plan.get(key) or "").strip()
        if sync_value != expected:
            raise AcceptanceFailure(
                f"{scenario_id}: sync external plan {key}={sync_value!r}; "
                f"expected {expected!r}; plan={json_for_log(sync_plan)}"
            )
        stream_value = str(stream_plan.get(key) or "").strip()
        if stream_value and stream_value != sync_value:
            raise AcceptanceFailure(
                f"{scenario_id}: sync external plan {key}={sync_value!r} "
                f"!= stream {stream_value!r}"
            )


def path_from_trace(trace: Mapping[str, Any], ledger: Mapping[str, Any]) -> str:
    direct = trace.get("turn_path_decision")
    if isinstance(direct, Mapping):
        path = str(direct.get("path") or "").strip()
        if path:
            return path
    session = trace.get("tool_policy_session")
    if isinstance(session, Mapping):
        path = str(session.get("path") or "").strip()
        if path:
            return path
    route = ledger.get("route")
    if isinstance(route, Mapping):
        decision = route.get("turn_path_decision")
        if isinstance(decision, Mapping):
            path = str(decision.get("path") or "").strip()
            if path:
                return path
    return ""


def visible_tool_names_from_trace(
    trace: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> list[str]:
    session = trace.get("tool_policy_session")
    if not isinstance(session, Mapping):
        tools = ledger.get("tools")
        session = tools.get("policy_session") if isinstance(tools, Mapping) else {}
    if isinstance(session, Mapping):
        return safe_string_list(session.get("visible_tool_names"))
    return []


def observed_tool_names_from_ledger(ledger: Mapping[str, Any]) -> list[str]:
    tools = ledger.get("tools")
    if isinstance(tools, Mapping):
        return safe_string_list(tools.get("observed"))
    return []


def suppressed_tool_names_from_ledger(ledger: Mapping[str, Any]) -> list[str]:
    tools = ledger.get("tools")
    if isinstance(tools, Mapping):
        return safe_string_list(tools.get("suppressed"))
    return []


def external_action_plan_from_trace(
    trace: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    plan = trace.get("external_app_action_plan")
    if isinstance(plan, dict):
        return plan
    external = ledger.get("external_app")
    if isinstance(external, Mapping):
        plan = external.get("action_plan")
        if isinstance(plan, dict):
            return plan
    return {}


def external_action_trace_from_trace(
    trace: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    action_trace = trace.get("external_action_trace")
    if isinstance(action_trace, dict):
        return action_trace
    external = ledger.get("external_app")
    if isinstance(external, Mapping):
        action_trace = external.get("action_trace")
        if isinstance(action_trace, dict):
            return action_trace
    return {}


def final_answer_from_trace(
    trace: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    final_answer = trace.get("final_answer")
    if isinstance(final_answer, dict):
        return final_answer
    final_answer = ledger.get("final_answer")
    if isinstance(final_answer, dict):
        return final_answer
    return {}


def assert_scenario_result(result: ScenarioResult) -> None:
    scenario = result.scenario
    if "error" in result.event_names:
        error_payload = terminal_payload(
            [SseEvent(name=name, data="") for name in result.event_names],
            "error",
        )
        raise AcceptanceFailure(f"{scenario.id}: stream emitted error: {error_payload}")
    if scenario.require_done and "done" not in result.event_names:
        raise AcceptanceFailure(f"{scenario.id}: stream did not emit done")
    if scenario.require_answer and not result.answer:
        raise AcceptanceFailure(f"{scenario.id}: stream did not emit a non-empty answer")
    if not result.trace:
        raise AcceptanceFailure(f"{scenario.id}: terminal runtime_flow_trace missing")
    if not result.ledger:
        raise AcceptanceFailure(f"{scenario.id}: terminal runtime_flow_ledger missing")
    assert_runtime_ledger_contract(
        scenario_id=scenario.id,
        ledger=result.ledger,
        scenario=scenario,
    )
    assert_context_provenance_contract(
        scenario_id=scenario.id,
        ledger=result.ledger,
        scenario=scenario,
    )

    path = path_from_trace(result.trace, result.ledger)
    if path != scenario.expected_path:
        raise AcceptanceFailure(
            f"{scenario.id}: path={path!r}; expected {scenario.expected_path!r}"
        )

    visible_tools = visible_tool_names_from_trace(result.trace, result.ledger)
    observed_tools = observed_tool_names_from_ledger(result.ledger)
    suppressed_tools = suppressed_tool_names_from_ledger(result.ledger)
    all_runtime_tools = tuple(dict.fromkeys((*visible_tools, *observed_tools)))
    assert_runtime_surface_invariants(
        scenario_id=scenario.id,
        trace=result.trace,
        runtime_tools=all_runtime_tools,
    )
    assert_public_tool_call_events_safe(
        scenario_id=scenario.id,
        events=result.events,
    )
    if scenario.require_no_visible_tools and all_runtime_tools:
        raise AcceptanceFailure(
            f"{scenario.id}: expected no visible/observed tools; saw {all_runtime_tools}"
        )
    for tool_name in scenario.required_visible_tools:
        if tool_name not in visible_tools:
            raise AcceptanceFailure(
                f"{scenario.id}: required visible tool {tool_name!r} missing; "
                f"saw {visible_tools}"
            )
    for tool_name in scenario.required_observed_tools:
        if tool_name not in observed_tools:
            raise AcceptanceFailure(
                f"{scenario.id}: required observed tool {tool_name!r} missing; "
                f"saw {observed_tools}"
            )
    for forbidden in scenario.forbidden_tool_names:
        if forbidden in all_runtime_tools:
            raise AcceptanceFailure(
                f"{scenario.id}: forbidden tool {forbidden!r} was visible/observed"
            )
    for prefix in scenario.forbidden_tool_prefixes:
        leaked = [name for name in all_runtime_tools if name.startswith(prefix)]
        if leaked:
            raise AcceptanceFailure(
                f"{scenario.id}: forbidden tool prefix {prefix!r} matched {leaked}"
            )
    for tool_name in scenario.expected_suppressed_tools:
        if tool_name not in suppressed_tools:
            raise AcceptanceFailure(
                f"{scenario.id}: expected suppressed tool {tool_name!r} missing; "
                f"saw {suppressed_tools}"
            )

    if scenario.answer_must_contain_any and not any(
        fragment in result.answer for fragment in scenario.answer_must_contain_any
    ):
        raise AcceptanceFailure(
            f"{scenario.id}: answer did not contain any expected fragment "
            f"{scenario.answer_must_contain_any}; preview={safe_preview(result.answer)}"
        )
    for marker in RAW_CHAT_MARKERS:
        if marker in result.answer:
            raise AcceptanceFailure(
                f"{scenario.id}: answer leaked raw runtime marker {marker!r}"
            )

    plan = external_action_plan_from_trace(result.trace, result.ledger)
    if scenario.expected_external_plan_status:
        status = str(plan.get("status") or "").strip()
        if status != scenario.expected_external_plan_status:
            raise AcceptanceFailure(
                f"{scenario.id}: external plan status={status!r}; "
                f"expected {scenario.expected_external_plan_status!r}; plan={json_for_log(plan)}"
            )
    if scenario.expected_external_provider:
        provider = str(plan.get("provider_slug") or "").strip()
        if provider != scenario.expected_external_provider:
            raise AcceptanceFailure(
                f"{scenario.id}: external provider={provider!r}; "
                f"expected {scenario.expected_external_provider!r}; plan={json_for_log(plan)}"
            )
    if scenario.expected_external_kind:
        kind = str(plan.get("kind") or "").strip()
        if kind != scenario.expected_external_kind:
            raise AcceptanceFailure(
                f"{scenario.id}: external kind={kind!r}; "
                f"expected {scenario.expected_external_kind!r}; plan={json_for_log(plan)}"
            )
    if scenario.expected_worker_outcome:
        action_trace = external_action_trace_from_trace(result.trace, result.ledger)
        worker_outcome = str(action_trace.get("worker_outcome") or "").strip()
        if not worker_outcome:
            worker = action_trace.get("integration_worker")
            if isinstance(worker, Mapping):
                classification = worker.get("result_classification")
                if isinstance(classification, Mapping):
                    worker_outcome = str(classification.get("outcome") or "").strip()
        if worker_outcome != scenario.expected_worker_outcome:
            raise AcceptanceFailure(
                f"{scenario.id}: worker outcome={worker_outcome!r}; "
                f"expected {scenario.expected_worker_outcome!r}; "
                f"trace={json_for_log(action_trace)}"
            )
    if scenario.expected_final_answer_source:
        final_answer = final_answer_from_trace(result.trace, result.ledger)
        source = str(final_answer.get("source") or "").strip()
        if source != scenario.expected_final_answer_source:
            raise AcceptanceFailure(
                f"{scenario.id}: final answer source={source!r}; "
                f"expected {scenario.expected_final_answer_source!r}; "
                f"trace={json_for_log(final_answer)}"
            )


def assert_runtime_surface_invariants(
    *,
    scenario_id: str,
    trace: Mapping[str, Any],
    runtime_tools: Iterable[str],
) -> None:
    leaked_tools = [
        tool_name
        for tool_name in runtime_tools
        if tool_name in GLOBAL_FORBIDDEN_RUNTIME_TOOLS
    ]
    if leaked_tools:
        raise AcceptanceFailure(
            f"{scenario_id}: forbidden runtime tool surface leaked {leaked_tools}"
        )
    assert_no_sensitive_payload(trace, path=f"{scenario_id}.runtime_trace")
    assert_no_model_control_keys(trace, path=f"{scenario_id}.runtime_trace")


def assert_post_turn_lifecycle_contract(value: Any, *, path: str) -> None:
    """Validate status-only post-turn lifecycle evidence."""

    if not isinstance(value, Mapping):
        raise AcceptanceFailure(f"{path} missing")
    if value.get("schema_version") != POST_TURN_LIFECYCLE_SUMMARY_VERSION:
        raise AcceptanceFailure(
            f"{path}.schema_version={value.get('schema_version')!r}"
        )
    status = str(value.get("status") or "").strip()
    if status not in POST_TURN_LIFECYCLE_STATUSES:
        raise AcceptanceFailure(f"{path}.status={status!r}")
    policy = str(value.get("semantic_memory_policy") or "").strip()
    if policy not in POST_TURN_LIFECYCLE_POLICIES:
        raise AcceptanceFailure(f"{path}.semantic_memory_policy={policy!r}")
    if not isinstance(value.get("background_tasks_scheduled"), bool):
        raise AcceptanceFailure(f"{path}.background_tasks_scheduled is not boolean")

    privacy = value.get("privacy")
    if not isinstance(privacy, Mapping):
        raise AcceptanceFailure(f"{path}.privacy missing")
    if privacy.get("raw_content_included") is not False:
        raise AcceptanceFailure(f"{path}.privacy.raw_content_included is not false")
    if privacy.get("identifier_strategy") != "status_only":
        raise AcceptanceFailure(f"{path}.privacy.identifier_strategy mismatch")

    for key in value.keys():
        if str(key).strip().lower() in POST_TURN_LIFECYCLE_FORBIDDEN_KEYS:
            raise AcceptanceFailure(f"{path}.{key} exposes raw turn scope")
    assert_no_sensitive_payload(value, path=path)


def assert_runtime_ledger_contract(
    *,
    scenario_id: str,
    ledger: Mapping[str, Any],
    scenario: ScenarioExpectation,
) -> None:
    if ledger.get("schema_version") != RUNTIME_FLOW_LEDGER_SCHEMA_VERSION:
        raise AcceptanceFailure(
            f"{scenario_id}: runtime ledger schema mismatch "
            f"{ledger.get('schema_version')!r}"
        )

    tools = ledger.get("tools")
    if not isinstance(tools, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: runtime ledger tools section missing")
    assert_bounded_string_list(
        tools.get("observed"),
        path=f"{scenario_id}.runtime_ledger.tools.observed",
    )
    assert_bounded_string_list(
        tools.get("suppressed"),
        path=f"{scenario_id}.runtime_ledger.tools.suppressed",
    )

    stream = ledger.get("stream")
    if not isinstance(stream, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: runtime ledger stream section missing")
    if stream.get("transport") != "sse_v3":
        raise AcceptanceFailure(
            f"{scenario_id}: runtime ledger stream transport mismatch "
            f"{stream.get('transport')!r}"
        )
    event_counts = stream.get("event_counts")
    if not isinstance(event_counts, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: runtime ledger event counts missing")
    for event_name, count in event_counts.items():
        require_non_negative_int(
            count,
            path=f"{scenario_id}.runtime_ledger.stream.event_counts.{event_name}",
        )

    if scenario.require_done and scenario.require_ledger_done_seen:
        if stream.get("done_seen") is not True:
            raise AcceptanceFailure(f"{scenario_id}: runtime ledger did not record done_seen")
        done_count = event_counts.get("done")
        if type(done_count) is not int or done_count < 1:
            raise AcceptanceFailure(f"{scenario_id}: runtime ledger missing done event count")
    for event_name in scenario.expected_stream_events:
        event_count = event_counts.get(event_name)
        if type(event_count) is not int or event_count < 1:
            raise AcceptanceFailure(
                f"{scenario_id}: expected stream event {event_name!r} missing from "
                f"runtime ledger counts"
            )
    for event_name in scenario.forbidden_stream_events:
        event_count = event_counts.get(event_name)
        if type(event_count) is int and event_count > 0:
            raise AcceptanceFailure(
                f"{scenario_id}: forbidden stream event {event_name!r} was recorded "
                f"in runtime ledger counts"
            )

    finalization = ledger.get("finalization")
    if not isinstance(finalization, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: runtime ledger finalization missing")
    if str(finalization.get("status") or "").strip() == "saved":
        assert_post_turn_lifecycle_contract(
            finalization.get("post_turn_lifecycle"),
            path=f"{scenario_id}.runtime_ledger.finalization.post_turn_lifecycle",
        )

    if scenario.expected_host_surface or scenario.expected_host_capabilities:
        request = ledger.get("request")
        if not isinstance(request, Mapping):
            raise AcceptanceFailure(f"{scenario_id}: runtime ledger request section missing")
        if (
            scenario.expected_host_surface
            and request.get("host_surface") != scenario.expected_host_surface
        ):
            raise AcceptanceFailure(
                f"{scenario_id}: host surface={request.get('host_surface')!r}; "
                f"expected {scenario.expected_host_surface!r}"
            )
        request_capabilities = set(
            assert_bounded_string_list(
                request.get("host_capabilities"),
                path=f"{scenario_id}.runtime_ledger.request.host_capabilities",
            )
        )
        missing_capabilities = [
            capability
            for capability in scenario.expected_host_capabilities
            if capability not in request_capabilities
        ]
        if missing_capabilities:
            raise AcceptanceFailure(
                f"{scenario_id}: host capabilities missing {missing_capabilities}; "
                f"saw {sorted(request_capabilities)}"
            )

    if scenario.expect_preview_required or scenario.expect_no_apply_attempted:
        host_actions = ledger.get("host_actions")
        if not isinstance(host_actions, Mapping):
            raise AcceptanceFailure(f"{scenario_id}: runtime ledger host_actions section missing")
        if scenario.expect_preview_required and host_actions.get("preview_required") is not True:
            raise AcceptanceFailure(f"{scenario_id}: expected preview_required=true")
        if scenario.expect_no_apply_attempted and host_actions.get("apply_attempted") is True:
            raise AcceptanceFailure(f"{scenario_id}: apply attempted before approval")

    assert_subagent_boundary_contract(
        scenario_id=scenario_id,
        ledger=ledger,
        scenario=scenario,
    )


def assert_subagent_boundary_contract(
    *,
    scenario_id: str,
    ledger: Mapping[str, Any],
    scenario: ScenarioExpectation,
) -> None:
    subagents = ledger.get("subagents")
    if not isinstance(subagents, Mapping) or not subagents:
        if scenario.expected_min_subagent_reports:
            raise AcceptanceFailure(
                f"{scenario_id}: subagent boundary trace missing; expected at least "
                f"{scenario.expected_min_subagent_reports} report(s)"
            )
        if scenario.expected_subagent_warning_codes:
            raise AcceptanceFailure(
                f"{scenario_id}: subagent boundary warnings missing; expected "
                f"{scenario.expected_subagent_warning_codes}"
            )
        return

    if subagents.get("schema_version") != SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION:
        raise AcceptanceFailure(
            f"{scenario_id}: subagent boundary schema mismatch "
            f"{subagents.get('schema_version')!r}"
        )
    if subagents.get("raw_content_included") is not False:
        raise AcceptanceFailure(
            f"{scenario_id}: subagent raw content flag must be false"
        )

    report_count = require_non_negative_int(
        subagents.get("report_count"),
        path=f"{scenario_id}.runtime_ledger.subagents.report_count",
    )
    reports = subagents.get("reports")
    if not isinstance(reports, list):
        raise AcceptanceFailure(
            f"{scenario_id}: runtime ledger subagents.reports must be a list"
        )
    if report_count < len(reports):
        raise AcceptanceFailure(
            f"{scenario_id}: subagent report_count is lower than reports length"
        )
    if report_count < scenario.expected_min_subagent_reports:
        raise AcceptanceFailure(
            f"{scenario_id}: subagent reports={report_count}; expected at least "
            f"{scenario.expected_min_subagent_reports}"
        )

    warning_codes = set(
        assert_bounded_string_list(
            subagents.get("warning_codes"),
            path=f"{scenario_id}.runtime_ledger.subagents.warning_codes",
        )
    )
    missing_warnings = [
        code
        for code in scenario.expected_subagent_warning_codes
        if code not in warning_codes
    ]
    if missing_warnings:
        raise AcceptanceFailure(
            f"{scenario_id}: subagent warnings missing {missing_warnings}; "
            f"saw {sorted(warning_codes)}"
        )

    assert_no_sensitive_payload(
        subagents,
        path=f"{scenario_id}.runtime_ledger.subagents",
    )
    assert_no_raw_context_keys(
        subagents,
        path=f"{scenario_id}.runtime_ledger.subagents",
    )

    for index, item in enumerate(reports):
        item_path = f"{scenario_id}.runtime_ledger.subagents.reports[{index}]"
        if not isinstance(item, Mapping):
            raise AcceptanceFailure(f"{item_path} must be an object")
        raw_keys = sorted(
            key
            for key in item
            if str(key).strip().lower() in SUBAGENT_BOUNDARY_REPORT_RAW_KEYS
        )
        if raw_keys:
            raise AcceptanceFailure(
                f"{item_path}: raw child payload key(s) leaked {raw_keys}"
            )
        for key in (
            "agent_name",
            "agent_type",
            "status",
            "handoff_schema_version",
            "result_schema_version",
        ):
            value = item.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise AcceptanceFailure(f"{item_path}.{key} must be a string")
                assert_context_provenance_string_bounded(
                    value,
                    path=f"{item_path}.{key}",
                )
        for key in SUBAGENT_BOUNDARY_REPORT_COUNT_KEYS:
            require_non_negative_int(item.get(key), path=f"{item_path}.{key}")
        if not isinstance(item.get("thinking_dropped"), bool):
            raise AcceptanceFailure(f"{item_path}.thinking_dropped must be boolean")


def assert_context_provenance_contract(
    *,
    scenario_id: str,
    ledger: Mapping[str, Any],
    scenario: ScenarioExpectation,
) -> None:
    context = ledger.get("context")
    if not isinstance(context, Mapping):
        raise AcceptanceFailure(f"{scenario_id}: runtime_flow_ledger.context missing")
    provenance = context.get("context_provenance")
    if not isinstance(provenance, Mapping):
        raise AcceptanceFailure(
            f"{scenario_id}: context provenance ledger missing from terminal SSE"
        )
    if provenance.get("schema_version") != CONTEXT_PROVENANCE_SCHEMA_VERSION:
        raise AcceptanceFailure(
            f"{scenario_id}: context provenance schema mismatch "
            f"{provenance.get('schema_version')!r}"
        )

    for section in CONTEXT_PROVENANCE_REQUIRED_SECTIONS:
        if not isinstance(provenance.get(section), Mapping):
            raise AcceptanceFailure(
                f"{scenario_id}: context provenance section {section!r} missing"
            )
    warnings = provenance.get("warnings")
    if not isinstance(warnings, list):
        raise AcceptanceFailure(f"{scenario_id}: context provenance warnings missing")

    path = f"{scenario_id}.runtime_ledger.context.context_provenance"
    assert_no_sensitive_payload(provenance, path=path)
    assert_no_raw_context_keys(provenance, path=path)
    assert_context_provenance_values_bounded(provenance, path=path)

    privacy = provenance["privacy"]
    if privacy.get("raw_content_included") is not False:
        raise AcceptanceFailure(
            f"{scenario_id}: context provenance privacy.raw_content_included must be false"
        )
    if privacy.get("identifier_strategy") != "hash_or_count_only":
        raise AcceptanceFailure(
            f"{scenario_id}: context provenance identifier strategy mismatch"
        )

    documents = provenance["documents"]
    memory = provenance["memory"]
    host = provenance["host"]
    warning_codes = set(assert_bounded_string_list(warnings, path=f"{path}.warnings"))

    uploaded_document_count = require_non_negative_int(
        context.get("uploaded_document_count"),
        path=f"{scenario_id}.runtime_ledger.context.uploaded_document_count",
    )
    source_ref_count = require_non_negative_int(
        context.get("source_ref_count"),
        path=f"{scenario_id}.runtime_ledger.context.source_ref_count",
    )
    memory_context_count = require_non_negative_int(
        context.get("memory_context_count"),
        path=f"{scenario_id}.runtime_ledger.context.memory_context_count",
        allow_none=True,
    )

    attachment_count = require_non_negative_int(
        documents.get("attachment_count"),
        path=f"{path}.documents.attachment_count",
    )
    usable_attachment_count = require_non_negative_int(
        documents.get("usable_attachment_count"),
        path=f"{path}.documents.usable_attachment_count",
    )
    require_non_negative_int(
        documents.get("total_markdown_chars"),
        path=f"{path}.documents.total_markdown_chars",
    )
    require_non_negative_int(
        documents.get("truncated_count"),
        path=f"{path}.documents.truncated_count",
    )
    document_source_ref_count = require_non_negative_int(
        documents.get("source_ref_count"),
        path=f"{path}.documents.source_ref_count",
    )
    if uploaded_document_count < usable_attachment_count:
        raise AcceptanceFailure(
            f"{scenario_id}: runtime uploaded document count is lower than provenance"
        )
    if source_ref_count < document_source_ref_count:
        raise AcceptanceFailure(
            f"{scenario_id}: runtime source-ref count is lower than provenance"
        )
    if usable_attachment_count > attachment_count:
        raise AcceptanceFailure(
            f"{scenario_id}: usable attachment count exceeds attachment count"
        )

    for list_key in (
        "parser_names",
        "parser_chain_names",
        "media_kinds",
        "provenance_levels",
        "source_ref_kinds",
    ):
        assert_bounded_string_list(
        documents.get(list_key),
        path=f"{path}.documents.{list_key}",
    )
    media_kinds = set(
        assert_bounded_string_list(
            documents.get("media_kinds"),
            path=f"{path}.documents.media_kinds",
        )
    )
    missing_media_kinds = [
        kind for kind in scenario.expected_document_media_kinds if kind not in media_kinds
    ]
    if missing_media_kinds:
        raise AcceptanceFailure(
            f"{scenario_id}: document media kinds missing {missing_media_kinds}; "
            f"saw {sorted(media_kinds)}"
        )
    source_ref_kinds = set(
        assert_bounded_string_list(
            documents.get("source_ref_kinds"),
            path=f"{path}.documents.source_ref_kinds",
        )
    )
    missing_source_ref_kinds = [
        kind
        for kind in scenario.expected_document_source_ref_kinds
        if kind not in source_ref_kinds
    ]
    if missing_source_ref_kinds:
        raise AcceptanceFailure(
            f"{scenario_id}: document source-ref kinds missing {missing_source_ref_kinds}; "
            f"saw {sorted(source_ref_kinds)}"
        )
    assert_bounded_string_list(
        documents.get("attachment_id_hashes"),
        path=f"{path}.documents.attachment_id_hashes",
        require_hash=True,
    )

    semantic_memory_count = require_non_negative_int(
        memory.get("semantic_memory_count"),
        path=f"{path}.memory.semantic_memory_count",
        allow_none=True,
    )
    require_non_negative_int(
        memory.get("semantic_context_char_count"),
        path=f"{path}.memory.semantic_context_char_count",
    )
    require_non_negative_int(
        memory.get("core_memory_char_count"),
        path=f"{path}.memory.core_memory_char_count",
    )
    require_non_negative_int(
        memory.get("user_fact_count"),
        path=f"{path}.memory.user_fact_count",
        allow_none=True,
    )
    assert_bounded_string_list(
        memory.get("semantic_memory_types"),
        path=f"{path}.memory.semantic_memory_types",
    )
    retrieval_status = str(memory.get("retrieval_status") or "").strip()
    relevant_memory_count = require_non_negative_int(
        memory.get("relevant_memory_count"),
        path=f"{path}.memory.relevant_memory_count",
        allow_none=True,
    )
    require_non_negative_int(
        memory.get("insight_count"),
        path=f"{path}.memory.insight_count",
        allow_none=True,
    )
    if (
        semantic_memory_count is not None
        and memory_context_count is not None
        and memory_context_count < semantic_memory_count
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: runtime memory context count is lower than provenance"
        )
    if (
        scenario.expected_memory_retrieval_status
        and retrieval_status != scenario.expected_memory_retrieval_status
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: memory retrieval status={retrieval_status!r}; "
            f"expected {scenario.expected_memory_retrieval_status!r}"
        )
    if scenario.expected_min_relevant_memories and (
        relevant_memory_count is None
        or relevant_memory_count < scenario.expected_min_relevant_memories
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: relevant memories={relevant_memory_count}; "
            f"expected at least {scenario.expected_min_relevant_memories}"
        )
    if scenario.expected_min_user_facts and (
        user_fact_count is None
        or user_fact_count < scenario.expected_min_user_facts
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: user facts={user_fact_count}; "
            f"expected at least {scenario.expected_min_user_facts}"
        )

    assert_bounded_string_list(
        host.get("capability_names"),
        path=f"{path}.host.capability_names",
    )
    if (
        scenario.expected_host_surface
        and host.get("surface") != scenario.expected_host_surface
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: provenance host surface={host.get('surface')!r}; "
            f"expected {scenario.expected_host_surface!r}"
        )
    host_capability_names = set(
        assert_bounded_string_list(
            host.get("capability_names"),
            path=f"{path}.host.capability_names",
        )
    )
    missing_provenance_capabilities = [
        capability
        for capability in scenario.expected_host_capabilities
        if capability not in host_capability_names
    ]
    if missing_provenance_capabilities:
        raise AcceptanceFailure(
            f"{scenario_id}: provenance host capabilities missing "
            f"{missing_provenance_capabilities}; saw {sorted(host_capability_names)}"
        )

    if (
        usable_attachment_count > 0
        and document_source_ref_count == 0
        and "document_context_without_source_refs" not in warning_codes
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: document provenance warning missing for source-less upload"
        )
    if (
        memory.get("semantic_context_present") is True
        and semantic_memory_count is None
        and "memory_context_without_typed_items" not in warning_codes
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: memory provenance warning missing for untyped context"
        )
    if (
        host.get("host_context_present") is True
        and not host.get("capability_names")
        and not host.get("host_capabilities_present")
        and "host_context_without_capabilities" not in warning_codes
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: host provenance warning missing for capability-less host"
        )

    if (
        scenario.expected_min_uploaded_documents
        and uploaded_document_count < scenario.expected_min_uploaded_documents
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: uploaded documents={uploaded_document_count}; "
            f"expected at least {scenario.expected_min_uploaded_documents}"
        )
    if (
        scenario.expected_min_source_refs
        and source_ref_count < scenario.expected_min_source_refs
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: source refs={source_ref_count}; "
            f"expected at least {scenario.expected_min_source_refs}"
        )
    if scenario.expected_min_memory_contexts and (
        memory_context_count is None
        or memory_context_count < scenario.expected_min_memory_contexts
    ):
        raise AcceptanceFailure(
            f"{scenario_id}: memory contexts={memory_context_count}; "
            f"expected at least {scenario.expected_min_memory_contexts}"
        )
    for code in scenario.expected_context_warning_codes:
        if code not in warning_codes:
            raise AcceptanceFailure(
                f"{scenario_id}: context warning {code!r} missing; saw {sorted(warning_codes)}"
            )


def require_non_negative_int(
    value: Any,
    *,
    path: str,
    allow_none: bool = False,
) -> int | None:
    if allow_none and value is None:
        return None
    if type(value) is not int or value < 0:
        raise AcceptanceFailure(f"{path} must be a non-negative integer")
    return value


def assert_bounded_string_list(
    value: Any,
    *,
    path: str,
    require_hash: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise AcceptanceFailure(f"{path} must be a list")
    tokens: list[str] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            raise AcceptanceFailure(f"{item_path} must be a non-empty string")
        assert_context_provenance_string_bounded(item, path=item_path)
        if require_hash and not item.startswith("sha256:"):
            raise AcceptanceFailure(f"{item_path} exposes unhashed attachment identifier")
        tokens.append(item)
    return tokens


def assert_context_provenance_values_bounded(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_context_provenance_values_bounded(item, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            assert_context_provenance_values_bounded(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        assert_context_provenance_string_bounded(value, path=path)


def assert_context_provenance_string_bounded(value: str, *, path: str) -> None:
    if "\n" in value or "\r" in value:
        raise AcceptanceFailure(f"{path} contains multiline raw-looking context")
    if len(value) > CONTEXT_PROVENANCE_STRING_MAX_LENGTH:
        raise AcceptanceFailure(f"{path} exceeds bounded context string length")


def assert_no_raw_context_keys(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).strip()
            if key_text.lower() in RAW_CONTEXT_FORBIDDEN_KEYS:
                raise AcceptanceFailure(f"{path}.{key_text} exposes raw context key")
            assert_no_raw_context_keys(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            assert_no_raw_context_keys(item, path=f"{path}[{index}]")


def assert_public_tool_call_events_safe(
    *,
    scenario_id: str,
    events: Iterable[SseEvent],
) -> None:
    for index, event in enumerate(events):
        if event.name not in {"tool_call", "tool_result"}:
            continue
        payload = event.json()
        if not isinstance(payload, Mapping):
            continue
        content = payload.get("content")
        if not isinstance(content, Mapping):
            continue
        if event.name == "tool_call":
            args = content.get("args")
            if not isinstance(args, Mapping):
                continue
            path = f"{scenario_id}.sse_tool_call[{index}].args"
            assert_no_sensitive_payload(args, path=path)
            assert_no_model_control_keys(args, path=path)
            continue

        result = content.get("result")
        assert_public_tool_result_safe(
            result,
            path=f"{scenario_id}.sse_tool_result[{index}].result",
        )


def assert_public_tool_result_safe(value: Any, *, path: str) -> None:
    if isinstance(value, str):
        parsed = decode_json_value(value)
        if parsed is not None:
            assert_public_tool_result_safe(parsed, path=path)
            return
        assert_no_sensitive_payload(value, path=path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).strip()
            normalized = key_text.lower()
            if normalized in PUBLIC_TOOL_RESULT_RAW_CONTENT_KEYS:
                if not (
                    isinstance(item, Mapping)
                    and item.get("redacted") is True
                ):
                    raise AcceptanceFailure(
                        f"{path}.{key_text} exposes unredacted raw tool content"
                    )
            assert_no_sensitive_payload({key_text: item}, path=path)
            assert_no_model_control_keys({key_text: item}, path=path)
            assert_public_tool_result_safe(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            assert_public_tool_result_safe(item, path=f"{path}[{index}]")
        return
    assert_no_sensitive_payload(value, path=path)


def assert_no_model_control_keys(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).strip()
            if key_text.lower() in MODEL_SURFACE_FORBIDDEN_KEYS:
                raise AcceptanceFailure(f"{path}.{key_text} exposes model-control key")
            assert_no_model_control_keys(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            assert_no_model_control_keys(item, path=f"{path}[{index}]")


def assert_doctor_contract(payload: Mapping[str, Any]) -> None:
    """Validate the OpenHuman-style connection lifecycle contract."""

    if payload.get("version") != "wiii_connect_doctor.v0":
        raise AcceptanceFailure("doctor report version mismatch")

    status = str(payload.get("status") or "").strip()
    if status not in VALID_DOCTOR_STATUSES:
        raise AcceptanceFailure(f"doctor status {status!r} is not recognized")

    assert_no_sensitive_payload(payload, path="doctor")

    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise AcceptanceFailure("doctor summary missing")
    for key in DOCTOR_REQUIRED_SUMMARY_KEYS:
        value = summary.get(key)
        if not isinstance(value, int) or value < 0:
            raise AcceptanceFailure(f"doctor summary {key!r} must be a non-negative integer")
    if summary["total_paths"] != (
        summary["ready_paths"] + summary["guarded_paths"] + summary["blocked_paths"]
    ):
        raise AcceptanceFailure("doctor path summary counts do not add up")
    if summary["external_agent_ready_connections"] > summary["external_provider_connections"]:
        raise AcceptanceFailure("doctor external agent-ready count exceeds provider count")
    if summary["agent_ready_connections"] > summary["total_connections"]:
        raise AcceptanceFailure("doctor agent-ready count exceeds total connections")

    path_diagnostics = payload.get("path_diagnostics")
    if not isinstance(path_diagnostics, list) or not path_diagnostics:
        raise AcceptanceFailure("doctor path diagnostics missing")
    path_by_name: dict[str, Mapping[str, Any]] = {}
    for item in path_diagnostics:
        if not isinstance(item, Mapping):
            raise AcceptanceFailure("doctor path diagnostic must be an object")
        path = str(item.get("path") or "").strip()
        item_status = str(item.get("status") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not path:
            raise AcceptanceFailure("doctor path diagnostic missing path")
        if item_status not in VALID_PATH_DOCTOR_STATUSES:
            raise AcceptanceFailure(f"doctor path {path!r} has invalid status {item_status!r}")
        if not reason:
            raise AcceptanceFailure(f"doctor path {path!r} missing reason")
        path_by_name[path] = item
    for path in DOCTOR_REQUIRED_PATHS:
        if path not in path_by_name:
            raise AcceptanceFailure(f"doctor required path {path!r} missing")
    if path_by_name["casual_chat"].get("status") != "ready":
        raise AcceptanceFailure("doctor casual_chat path must be ready")
    if path_by_name["weather_lookup"].get("status") != "ready":
        raise AcceptanceFailure(
            "doctor weather_lookup path must be ready when runtime binds tool_current_weather"
        )
    external_status = str(path_by_name["external_app_action"].get("status") or "")
    if external_status not in {"guarded", "blocked"}:
        raise AcceptanceFailure(
            "doctor external_app_action must stay guarded/blocked until a gateway-selected action runs"
        )

    provider_diagnostics = payload.get("provider_diagnostics")
    if not isinstance(provider_diagnostics, list) or not provider_diagnostics:
        raise AcceptanceFailure("doctor provider diagnostics missing")
    provider_by_slug: dict[str, Mapping[str, Any]] = {}
    for item in provider_diagnostics:
        if not isinstance(item, Mapping):
            raise AcceptanceFailure("doctor provider diagnostic must be an object")
        provider_slug = str(item.get("provider_slug") or "").strip()
        provider_kind = str(item.get("provider_kind") or "").strip()
        item_status = str(item.get("status") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not provider_slug:
            raise AcceptanceFailure("doctor provider diagnostic missing provider_slug")
        if not provider_kind:
            raise AcceptanceFailure(f"doctor provider {provider_slug!r} missing provider_kind")
        if item_status not in VALID_PROVIDER_DOCTOR_STATUSES:
            raise AcceptanceFailure(
                f"doctor provider {provider_slug!r} has invalid status {item_status!r}"
            )
        if not reason:
            raise AcceptanceFailure(f"doctor provider {provider_slug!r} missing reason")
        stages = item.get("stages")
        if not isinstance(stages, list) or not stages:
            raise AcceptanceFailure(f"doctor provider {provider_slug!r} missing stages")
        stage_by_key: dict[str, Mapping[str, Any]] = {}
        for stage in stages:
            if not isinstance(stage, Mapping):
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} stage must be an object"
                )
            key = str(stage.get("key") or "").strip()
            stage_status = str(stage.get("status") or "").strip()
            stage_reason = str(stage.get("reason") or "").strip()
            if not key:
                raise AcceptanceFailure(f"doctor provider {provider_slug!r} stage missing key")
            if stage_status not in VALID_PROVIDER_STAGE_STATUSES:
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} stage {key!r} "
                    f"has invalid status {stage_status!r}"
                )
            if not stage_reason:
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} stage {key!r} missing reason"
                )
            stage_by_key[key] = stage
        for key in DOCTOR_REQUIRED_PROVIDER_STAGES:
            if key not in stage_by_key:
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} missing lifecycle stage {key!r}"
                )
        if bool(item.get("active")) and not bool(item.get("agent_ready")):
            if item_status == "ready":
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} cannot be ready when account is active but agent policy is not ready"
                )
            required_next = item.get("required_next")
            if not isinstance(required_next, list) or not required_next:
                raise AcceptanceFailure(
                    f"doctor provider {provider_slug!r} must explain next policy/gateway step"
                )
        if bool(item.get("agent_ready")) and item_status == "ready":
            raise AcceptanceFailure(
                f"doctor provider {provider_slug!r} must remain guarded until per-action gateway evaluation"
            )
        provider_by_slug[provider_slug] = item
    if "facebook" not in provider_by_slug:
        raise AcceptanceFailure("doctor must include facebook provider diagnostics")


def assert_wiii_connect_snapshot_contract(payload: Mapping[str, Any]) -> None:
    """Validate the privacy-safe capability snapshot used by browser replay."""

    if payload.get("version") != "wiii_connect_snapshot.v0":
        raise AcceptanceFailure("snapshot version mismatch")
    assert_no_sensitive_payload(payload, path="snapshot")

    connections = payload.get("connections")
    if not isinstance(connections, list) or not connections:
        raise AcceptanceFailure("snapshot connections missing")
    path_capabilities = payload.get("path_capabilities")
    if not isinstance(path_capabilities, list) or not path_capabilities:
        raise AcceptanceFailure("snapshot path capabilities missing")
    summary = payload.get("capability_summary")
    if not isinstance(summary, Mapping):
        raise AcceptanceFailure("snapshot capability_summary missing")

    for key in SNAPSHOT_REQUIRED_CAPABILITY_LISTS:
        if not isinstance(summary.get(key), list):
            raise AcceptanceFailure(f"snapshot capability_summary {key!r} missing")

    path_readiness = summary.get("path_readiness")
    by_path: dict[str, Mapping[str, Any]] = {}
    for item in path_readiness:
        if not isinstance(item, Mapping):
            raise AcceptanceFailure("snapshot path_readiness item must be an object")
        path = str(item.get("path") or "").strip()
        status = str(item.get("status") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not path:
            raise AcceptanceFailure("snapshot path_readiness item missing path")
        if status not in VALID_PATH_DOCTOR_STATUSES:
            raise AcceptanceFailure(
                f"snapshot path {path!r} has invalid status {status!r}"
            )
        if not reason:
            raise AcceptanceFailure(f"snapshot path {path!r} missing reason")
        by_path[path] = item
    for path in DOCTOR_REQUIRED_PATHS:
        if path not in by_path:
            raise AcceptanceFailure(f"snapshot required path {path!r} missing")

    provider_slugs = safe_string_list(summary.get("connected_provider_slugs"))
    agent_ready_provider_slugs = safe_string_list(
        summary.get("agent_ready_provider_slugs")
    )
    if any(slug not in provider_slugs for slug in agent_ready_provider_slugs):
        raise AcceptanceFailure(
            "snapshot agent-ready providers must be a subset of connected providers"
        )


def hashed_string_list(value: Any) -> list[str]:
    return [opaque_hash(item) for item in safe_string_list(value)]


def wiii_connect_capability_summary_from_snapshot(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    summary = payload.get("capability_summary")
    summary_map = summary if isinstance(summary, Mapping) else {}
    connections = payload.get("connections") if isinstance(payload.get("connections"), list) else []
    path_capabilities = (
        payload.get("path_capabilities")
        if isinstance(payload.get("path_capabilities"), list)
        else []
    )
    path_readiness = (
        summary_map.get("path_readiness")
        if isinstance(summary_map.get("path_readiness"), list)
        else []
    )
    connection_status_counts: dict[str, int] = {}
    for item in connections:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "unknown").strip() or "unknown"
        connection_status_counts[status] = connection_status_counts.get(status, 0) + 1
    path_status_counts: dict[str, int] = {}
    safe_paths: list[dict[str, Any]] = []
    for item in path_readiness:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        status = str(item.get("status") or "unknown").strip() or "unknown"
        reason = str(item.get("reason") or "").strip()
        if not path:
            continue
        path_status_counts[status] = path_status_counts.get(status, 0) + 1
        safe_paths.append(
            {
                "path": path,
                "status": status,
                "reason_hash": opaque_hash(reason) if reason else "",
            }
        )

    return {
        "snapshot_version": str(payload.get("version") or ""),
        "surface": str(payload.get("surface") or ""),
        "connection_count": len(connections),
        "path_capability_count": len(path_capabilities),
        "path_readiness_count": len(path_readiness),
        "active_connection_count": len(
            safe_string_list(summary_map.get("active_connection_slugs"))
        ),
        "agent_ready_connection_count": len(
            safe_string_list(summary_map.get("agent_ready_connection_slugs"))
        ),
        "connected_provider_count": len(
            safe_string_list(summary_map.get("connected_provider_slugs"))
        ),
        "agent_ready_provider_count": len(
            safe_string_list(summary_map.get("agent_ready_provider_slugs"))
        ),
        "connected_scope_count": len(
            safe_string_list(summary_map.get("connected_scope_names"))
        ),
        "suppressed_tool_group_count": len(
            safe_string_list(summary_map.get("suppressed_tool_groups"))
        ),
        "active_connection_slug_hashes": hashed_string_list(
            summary_map.get("active_connection_slugs")
        ),
        "agent_ready_connection_slug_hashes": hashed_string_list(
            summary_map.get("agent_ready_connection_slugs")
        ),
        "connected_provider_slug_hashes": hashed_string_list(
            summary_map.get("connected_provider_slugs")
        ),
        "agent_ready_provider_slug_hashes": hashed_string_list(
            summary_map.get("agent_ready_provider_slugs")
        ),
        "connected_scope_name_hashes": hashed_string_list(
            summary_map.get("connected_scope_names")
        ),
        "suppressed_tool_group_hashes": hashed_string_list(
            summary_map.get("suppressed_tool_groups")
        ),
        "connection_status_counts": connection_status_counts,
        "path_status_counts": path_status_counts,
        "paths": safe_paths,
        "raw_content_included": False,
        "identifier_strategy": "hash_or_count_only",
    }


def safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def assert_no_sensitive_payload(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).strip()
            normalized = key_text.lower()
            is_safe_derivative = normalized.endswith(
                SAFE_SENSITIVE_DERIVED_KEY_SUFFIXES
            )
            if (
                not is_safe_derivative
                and (
                    normalized in SENSITIVE_EXACT_KEYS
                    or any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)
                )
            ):
                raise AcceptanceFailure(f"{path}.{key_text} exposes sensitive key")
            assert_no_sensitive_payload(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            assert_no_sensitive_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and looks_sensitive_string(value):
        raise AcceptanceFailure(f"{path} exposes sensitive value")


def safe_preview(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def opaque_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def json_for_log(value: Any) -> str:
    return json.dumps(redact_for_log(value), ensure_ascii=False, sort_keys=True)


def redact_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            is_safe_derivative = normalized.endswith(
                SAFE_SENSITIVE_DERIVED_KEY_SUFFIXES
            )
            if (
                not is_safe_derivative
                and (
                    normalized in SENSITIVE_EXACT_KEYS
                    or any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)
                )
            ):
                safe[str(key)] = "[redacted]"
            else:
                safe[str(key)] = redact_for_log(item)
        return safe
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple | set):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        if looks_sensitive_string(value):
            return "[redacted]"
        return value
    return value


def looks_sensitive_string(value: str) -> bool:
    text = str(value or "").strip()
    lower = text.lower()
    if not text:
        return False
    if lower.startswith("bearer "):
        return True
    if "access_token=" in lower or "refresh_token=" in lower:
        return True
    if "wiii_state=" in lower or "approval_token=" in lower:
        return True
    if text.startswith("eyJ") and text.count(".") >= 2:
        return True
    if text.startswith(("sk-", "ak_", "tp-", "wcn_", "ca_")):
        return True
    return False


def validate_evidence_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise AcceptanceFailure("--evidence-json path must not be empty")
    path = Path(text).expanduser()
    parts = [part.lower() for part in path.parts]
    filename = path.name.lower()
    blocked_parts = {
        ".git",
        ".env",
        ".venv",
        "node_modules",
        "dist",
        "dist-embed",
        "coverage",
        "logs",
        "screenshots",
        "__pycache__",
    }
    if filename.startswith(".env") or any(part in blocked_parts for part in parts):
        raise AcceptanceFailure(
            "--evidence-json path points at a forbidden local/secret/generated location"
        )
    if path.suffix.lower() != ".json":
        raise AcceptanceFailure("--evidence-json path must end with .json")
    return path


class RuntimeFlowAcceptance:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.token = ""
        self.user: dict[str, Any] = {}
        self.results: list[ScenarioResult] = []
        self.check_records: list[dict[str, Any]] = []
        self.doctor_payload: dict[str, Any] = {}
        self.wiii_connect_snapshot_payload: dict[str, Any] = {}

    def api_url(self, path: str) -> str:
        return join_url(self.args.backend_url, path)

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise AcceptanceFailure("No bearer token available")
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.args.org_id:
            headers["X-Organization-ID"] = self.args.org_id
        return headers

    def run_check(self, name: str, func) -> bool:  # type: ignore[no-untyped-def]
        start = time.monotonic()
        try:
            detail = func()
        except AcceptanceFailure as exc:
            self.check_records.append(
                self.check_record(name, "failed", time.monotonic() - start, str(exc))
            )
            print(f"[FAIL] {name} - {exc}")
            return False
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            self.check_records.append(
                self.check_record(
                    name,
                    "failed",
                    time.monotonic() - start,
                    f"unexpected error: {exc}",
                )
            )
            print(f"[FAIL] {name} - unexpected error: {exc}")
            return False
        elapsed = time.monotonic() - start
        self.check_records.append(self.check_record(name, "passed", elapsed, str(detail)))
        print(f"[PASS] {name} ({elapsed:.1f}s) {detail}")
        return True

    def check_record(
        self,
        name: str,
        status: str,
        elapsed: float,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "elapsed_seconds": round(elapsed, 3),
            "detail": redact_for_log(safe_preview(detail, limit=320)),
        }

    def check_backend_health(self) -> str:
        for path in ("/health", "/api/v1/health", "/api/v1/health/live"):
            response = request_bytes(
                "GET",
                self.api_url(path),
                timeout=self.args.timeout,
                raise_http_errors=False,
            )
            if response.status == 200:
                return path
        raise AcceptanceFailure("No health endpoint returned HTTP 200")

    def authenticate(self) -> str:
        token = (self.args.bearer_token or os.environ.get(TOKEN_ENV, "")).strip()
        if token:
            self.token = token
            return f"bearer={opaque_hash(token)}"
        if self.args.auth_mode == "bearer":
            raise AcceptanceFailure(
                f"--auth-mode=bearer requires --bearer-token or {TOKEN_ENV}"
            )
        status = request_bytes(
            "GET",
            self.api_url("/api/v1/auth/dev-login/status"),
            timeout=self.args.timeout,
        ).json()
        if status.get("enabled") is not True:
            raise AcceptanceFailure(
                "dev-login is disabled; pass --bearer-token for this target"
            )
        payload = request_bytes(
            "POST",
            self.api_url("/api/v1/auth/dev-login"),
            payload={
                "email": self.args.demo_email,
                "name": self.args.demo_name,
                "role": self.args.demo_role,
            },
            timeout=self.args.timeout,
        ).json()
        token = payload.get("access_token")
        user = payload.get("user")
        if not isinstance(token, str) or not token:
            raise AcceptanceFailure("dev-login did not return access_token")
        if not isinstance(user, dict):
            raise AcceptanceFailure("dev-login did not return user")
        self.token = token
        self.user = user
        return f"dev-login user={opaque_hash(str(user.get('id') or ''))}"

    def check_doctor(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/doctor"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        self.doctor_payload = payload
        assert_doctor_contract(payload)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return (
            f"status={payload.get('status')} ready_paths={summary.get('ready_paths')} "
            f"blocked_paths={summary.get('blocked_paths')}"
        )

    def check_wiii_connect_capability_snapshot(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/snapshot"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        self.wiii_connect_snapshot_payload = payload
        assert_wiii_connect_snapshot_contract(payload)
        capability = wiii_connect_capability_summary_from_snapshot(payload)
        return (
            f"connections={capability['connection_count']} "
            f"path_readiness={capability['path_readiness_count']} "
            f"connected_providers={capability['connected_provider_count']}"
        )

    def chat_payload(
        self,
        scenario: ScenarioExpectation,
        *,
        prompt: str | None = None,
        session_suffix: str = "",
    ) -> dict[str, Any]:
        user_id = str(self.user.get("id") or "runtime-flow-acceptance")
        session_key = f"{self.args.session_id}-{scenario.id}{session_suffix}"
        payload: dict[str, Any] = {
            "user_id": user_id,
            "message": scenario.prompt if prompt is None else prompt,
            "role": self.args.demo_role,
            "session_id": session_key,
            "thread_id": session_key,
            "organization_id": self.args.org_id,
            "domain_id": self.args.domain_id,
            "thinking_effort": self.args.thinking_effort,
        }
        if self.args.provider:
            payload["provider"] = self.args.provider
        if self.args.model:
            payload["model"] = self.args.model
        if scenario.user_context:
            payload["user_context"] = dict(scenario.user_context)
        return payload

    def run_sync_parity(
        self,
        scenario: ScenarioExpectation,
        stream_result: ScenarioResult,
    ) -> str:
        if scenario.prelude_prompts:
            raise AcceptanceFailure(
                f"{scenario.id}: sync parity does not support prelude scenarios"
            )
        response = request_bytes(
            "POST",
            self.api_url("/api/v1/chat"),
            headers=self.auth_headers(),
            payload=self.chat_payload(scenario, session_suffix="-sync"),
            timeout=self.args.stream_timeout,
        )
        payload = response.json()
        assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload=payload,
            stream_result=stream_result,
        )
        metadata = chat_response_metadata(payload)
        return (
            f"sync_provider={metadata.get('provider')} "
            f"sync_model={metadata.get('model')}"
        )

    def run_scenario(self, scenario: ScenarioExpectation) -> str:
        for index, prompt in enumerate(scenario.prelude_prompts, start=1):
            prelude = request_sse_events(
                "POST",
                self.api_url("/api/v1/chat/stream/v3"),
                headers={
                    **self.auth_headers(),
                    "Accept": "text/event-stream",
                },
                payload=self.chat_payload(scenario, prompt=prompt),
                idle_timeout=self.args.stream_idle_timeout,
                max_total_seconds=self.args.stream_timeout,
            )
            event_names = [event.name for event in prelude.events]
            if "error" in event_names:
                raise AcceptanceFailure(
                    f"{scenario.id}: prelude {index} emitted error"
                )
            if "done" not in event_names:
                raise AcceptanceFailure(
                    f"{scenario.id}: prelude {index} did not emit done"
                )

        sse = request_sse_events(
            "POST",
            self.api_url("/api/v1/chat/stream/v3"),
            headers={
                **self.auth_headers(),
                "Accept": "text/event-stream",
            },
            payload=self.chat_payload(scenario),
            idle_timeout=self.args.stream_idle_timeout,
            max_total_seconds=self.args.stream_timeout,
        )
        events = sse.events
        event_names = [event.name for event in events]
        result = ScenarioResult(
            scenario=scenario,
            event_names=event_names,
            answer=extract_answer(events),
            trace=runtime_trace_from_events(events),
            ledger=runtime_ledger_from_events(events),
            first_event_seconds=sse.first_event_seconds,
            first_answer_seconds=sse.first_answer_seconds,
            total_seconds=sse.total_seconds,
            events=events,
        )
        assert_scenario_result(result)
        parity_detail = ""
        if bool(getattr(self.args, "sync_parity", False)) and scenario.sync_parity:
            parity_detail = f" sync_parity=ok {self.run_sync_parity(scenario, result)}"
        self.results.append(result)
        summary = result.summary()
        return (
            f"path={summary['path']} visible={summary['visible_tools']} "
            f"observed={summary['observed_tools']} total={summary['total_seconds']}s"
            f"{parity_detail}"
        )

    def run(self) -> int:
        print("=== Wiii Runtime Flow Acceptance ===")
        print(f"Backend: {self.args.backend_url}")
        print(f"Org:     {self.args.org_id}")
        print("")

        passed = 0
        failed = 0
        for name, func in (
            ("backend health", self.check_backend_health),
            ("authentication", self.authenticate),
            ("wiii connect doctor", self.check_doctor),
            ("wiii connect capability snapshot", self.check_wiii_connect_capability_snapshot),
        ):
            if self.run_check(name, func):
                passed += 1
            else:
                failed += 1
                if name in {"backend health", "authentication"}:
                    return self.finish(passed, failed)

        selected = selected_scenarios(self.args.scenario)
        for scenario in selected:
            if self.run_check(f"scenario:{scenario.id}", lambda s=scenario: self.run_scenario(s)):
                passed += 1
            else:
                failed += 1

        return self.finish(passed, failed)

    def finish(self, passed: int, failed: int) -> int:
        if self.args.evidence_json:
            self.write_evidence_json()
        print("")
        print(f"=== Results: {passed} passed, {failed} failed ===")
        if failed:
            print("Runtime flow acceptance failed.")
            return 1
        print("Runtime flow acceptance passed.")
        return 0

    def evidence_payload(self) -> dict[str, Any]:
        summary = (
            self.doctor_payload.get("summary")
            if isinstance(self.doctor_payload.get("summary"), dict)
            else {}
        )
        return redact_for_log(
            {
                "schema": TRACE_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "target": {
                    "backend_url": self.args.backend_url,
                    "target_env": self.args.target_env or os.environ.get(TARGET_ENV, ""),
                    "commit_sha": self.args.commit_sha or os.environ.get(COMMIT_SHA_ENV, ""),
                    "org_id_hash": opaque_hash(str(self.args.org_id or "")),
                },
                "doctor": {
                    "status": self.doctor_payload.get("status"),
                    "summary": summary,
                    "warnings": self.doctor_payload.get("warnings", []),
                    "top_blockers": self.doctor_payload.get("top_blockers", []),
                },
                "wiii_connect_capability": wiii_connect_capability_summary_from_snapshot(
                    self.wiii_connect_snapshot_payload
                ),
                "checks": self.check_records,
                "scenarios": [result.summary() for result in self.results],
                "browser_replay": {
                    "schema": BROWSER_REPLAY_SCHEMA_VERSION,
                    "cases": [result.browser_replay_case() for result in self.results],
                },
            }
        )

    def write_evidence_json(self) -> None:
        path = validate_evidence_path(self.args.evidence_json)
        emit_json_payload(self.evidence_payload(), path)
        print(f"[INFO] Wrote redacted evidence JSON: {path}")


def selected_scenarios(raw: str) -> tuple[ScenarioExpectation, ...]:
    selection = str(raw or "default").strip()
    if selection in {"", "default", "all"}:
        return DEFAULT_SCENARIOS
    requested = [
        item.strip()
        for item in selection.split(",")
        if item.strip()
    ]
    by_id = {scenario.id: scenario for scenario in DEFAULT_SCENARIOS}
    missing = sorted(item for item in requested if item not in by_id)
    if missing:
        raise AcceptanceFailure(f"Unknown scenario id(s): {', '.join(missing)}")
    return tuple(by_id[item] for item in requested)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Wiii chat runtime path/tool invariants through SSE runtime "
            "trace. No external providers or mutating app actions are called."
        )
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID)
    parser.add_argument(
        "--auth-mode",
        choices=("auto", "bearer", "dev-login"),
        default="auto",
        help=f"auto uses --bearer-token/{TOKEN_ENV}, then localhost dev-login.",
    )
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--demo-email", default=DEFAULT_DEMO_EMAIL)
    parser.add_argument("--demo-name", default=DEFAULT_DEMO_NAME)
    parser.add_argument(
        "--demo-role",
        choices=("student", "teacher", "admin"),
        default=DEFAULT_DEMO_ROLE,
    )
    parser.add_argument("--domain-id", default="maritime")
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--thinking-effort",
        choices=("low", "medium", "high", "max"),
        default="low",
    )
    parser.add_argument("--session-id", default=f"runtime-flow-{int(time.time())}")
    parser.add_argument(
        "--scenario",
        default="default",
        help="default/all or comma-separated scenario ids.",
    )
    parser.add_argument(
        "--sync-parity",
        action="store_true",
        help=(
            "For scenarios marked sync_parity, also call /api/v1/chat and "
            "compare answer/metadata/trace authority with the SSE path."
        ),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--stream-timeout", type=float, default=150.0)
    parser.add_argument("--stream-idle-timeout", type=float, default=25.0)
    parser.add_argument(
        "--target-env",
        default="",
        help=f"Optional target environment label; env fallback {TARGET_ENV}.",
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help=f"Optional deployed commit SHA; env fallback {COMMIT_SHA_ENV}.",
    )
    parser.add_argument(
        "--evidence-json",
        default="",
        help=(
            "Write sanitized JSON evidence. Do not point this at .env, logs, "
            "screenshots, coverage, dist, or dependency folders."
        ),
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return RuntimeFlowAcceptance(args).run()
    except AcceptanceFailure as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
