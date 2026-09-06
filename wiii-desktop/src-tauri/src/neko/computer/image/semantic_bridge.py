#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlsplit
from urllib.request import Request, urlopen

import websocket

PROTOCOL_VERSION = "neko-computer.semantic.v1"
AI_FRAME_VERSION = "wiii-ai-frame.v1"
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
MAX_TEXT = 512
MAX_STATE_NODES = 1000
MAX_BROWSER_FRAMES = 32
MAX_DOM_ATTRIBUTE_LOOKUPS = 128
MAX_DOM_LABEL_LOOKUPS = 64
MAX_DOM_INTERACTION_LOOKUPS = 48
MAX_DOM_VISUAL_TARGETS = 64
MAX_CONTINUATION_BYTES = 4096
MAX_KNOWN_NODE_VERSIONS = 2000
DEFAULT_BROWSER_KEY_DWELL_SECONDS = 0.08
MAX_INPUT_SEQUENCE_STEPS = 64
MAX_INPUT_SEQUENCE_KEYS = 3
MAX_INPUT_SEQUENCE_DURATION_MS = 8000
MAX_VISUAL_PATCH_BYTES = 512 * 1024
MAX_VISUAL_PATCH_WIDTH = 720
MAX_VISUAL_PATCH_HEIGHT = 450
MAX_BRIDGE_REQUEST_BYTES = 256 * 1024
MAX_APP_EVENT_BUFFER = 2048
MAX_APP_EVENT_POLL = 512
MAX_OBSERVATION_SCOPE_CACHE = 256
MAX_NATIVE_OBSERVATION_CACHE = 8
MAX_BROWSER_OBSERVATION_CACHE = 8
SEMANTIC_BRIDGE_HOST = "127.0.0.1"
SEMANTIC_BRIDGE_PORT = 9234
REALTIME_CLOCK_DIR = "/tmp/wiii-computer-clock"
REALTIME_CLOCK_WATCHDOG_MS = 30_000
REALTIME_CLOCK_RESUME_GRACE_SECONDS = 0.35
REALTIME_CLOCK_SETTLE_SECONDS = 0.08
CONTINUATION_SECRET_PATH = "/run/secrets/wiii-vnc-password"
FORM_CONTROL_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "entry",
    "listbox",
    "radio",
    "slider",
    "spin button",
    "switch",
    "textarea",
}
ACCESSIBILITY_ACTIVATION_ACTIONS = {"activate", "click", "default", "invoke", "press"}
ACCESSIBILITY_POINTER_ROLES = {
    "button",
    "check box",
    "link",
    "menu item",
    "push button",
    "radio button",
    "tab",
}
INVOKE_TRANSIENT_STATES = {"active", "focused"}
SENSITIVE_FIELD_TERMS = (
    "password",
    "passwd",
    "passcode",
    "one time code",
    "otp",
    "api key",
    "api token",
    "access token",
    "secret",
    "card number",
    "credit card",
    "cvv",
    "cvc",
)
pyatspi = None
APP_EVENT_EPOCH = secrets.token_hex(8)
APP_EVENT_LOCK = threading.Lock()
APP_EVENT_CONDITION = threading.Condition(APP_EVENT_LOCK)
APP_EVENT_BUFFER: deque[dict[str, Any]] = deque(maxlen=MAX_APP_EVENT_BUFFER)
APP_EVENT_SEQUENCE = 0
APP_EVENT_GAP = False
APP_EVENT_WATCHER_STATE = "not_started"
OBSERVATION_SCOPE_LOCK = threading.Lock()
OBSERVATION_SCOPES: dict[tuple[str, str], str | None] = {}
NATIVE_OBSERVATION_LOCK = threading.Lock()
NATIVE_APP_GENERATIONS: dict[str, int] = {}
NATIVE_OBSERVATIONS: OrderedDict[
    tuple[str, str, int],
    tuple[int, dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]],
] = OrderedDict()
BROWSER_OBSERVATION_LOCK = threading.Lock()
BROWSER_OBSERVATIONS: OrderedDict[
    tuple[str, str],
    tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]],
] = OrderedDict()
ACTIVE_BROWSER_TARGET_LOCK = threading.Lock()
ACTIVE_BROWSER_TARGET_ID: str | None = None


def remember_observation_scope(
    environment_id: str,
    state_version: str,
    scope_ref: str | None,
) -> None:
    if not environment_id or not state_version:
        return
    key = (environment_id, state_version)
    with OBSERVATION_SCOPE_LOCK:
        OBSERVATION_SCOPES.pop(key, None)
        OBSERVATION_SCOPES[key] = scope_ref
        while len(OBSERVATION_SCOPES) > MAX_OBSERVATION_SCOPE_CACHE:
            OBSERVATION_SCOPES.pop(next(iter(OBSERVATION_SCOPES)))


def observation_scope_for(environment_id: str, state_version: str) -> str | None:
    with OBSERVATION_SCOPE_LOCK:
        return OBSERVATION_SCOPES.get((environment_id, state_version))


def remember_browser_observation(
    environment_id: str,
    snapshot: dict[str, Any],
    targets: dict[str, tuple[Any, dict[str, Any]]],
) -> None:
    browser_targets = {
        ref: target
        for ref, target in targets.items()
        if is_browser_target_ref(ref)
    }
    if not browser_targets:
        return
    key = (environment_id, str(snapshot.get("stateVersion") or ""))
    if not key[1]:
        return
    with BROWSER_OBSERVATION_LOCK:
        BROWSER_OBSERVATIONS.pop(key, None)
        BROWSER_OBSERVATIONS[key] = (copy.deepcopy(snapshot), copy.deepcopy(browser_targets))
        while len(BROWSER_OBSERVATIONS) > MAX_BROWSER_OBSERVATION_CACHE:
            BROWSER_OBSERVATIONS.popitem(last=False)


def cached_browser_target_observation(
    environment_id: str,
    state_version: str,
    target_ref: str,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]] | None:
    key = (environment_id, state_version)
    with BROWSER_OBSERVATION_LOCK:
        cached = BROWSER_OBSERVATIONS.get(key)
        if cached is None or target_ref not in cached[1]:
            return None
        BROWSER_OBSERVATIONS.move_to_end(key)
        return copy.deepcopy(cached[0]), copy.deepcopy(cached[1])


def remember_active_browser_target(target_id: Any) -> None:
    global ACTIVE_BROWSER_TARGET_ID
    if not isinstance(target_id, str) or not target_id:
        return
    with ACTIVE_BROWSER_TARGET_LOCK:
        ACTIVE_BROWSER_TARGET_ID = target_id


def known_active_browser_page() -> dict[str, str] | None:
    with ACTIVE_BROWSER_TARGET_LOCK:
        target_id = ACTIVE_BROWSER_TARGET_ID
    return browser_page_target(target_id) if target_id else None


def native_app_id_for_scope(scope_ref: str | None) -> str | None:
    if not isinstance(scope_ref, str) or not scope_ref.startswith("app:"):
        return None
    launcher = APP_LAUNCHERS_BY_REF.get(scope_ref)
    if launcher is None or launcher["appId"] in {"browser", "files"}:
        return None
    return launcher["appId"]


def native_app_generation(app_id: str) -> int:
    with NATIVE_OBSERVATION_LOCK:
        return NATIVE_APP_GENERATIONS.get(app_id, 0)


def invalidate_native_observations(app_id: str) -> None:
    with NATIVE_OBSERVATION_LOCK:
        NATIVE_APP_GENERATIONS[app_id] = NATIVE_APP_GENERATIONS.get(app_id, 0) + 1
        stale_keys = [key for key in NATIVE_OBSERVATIONS if key[1] == f"app:{app_id}"]
        for key in stale_keys:
            NATIVE_OBSERVATIONS.pop(key, None)


def cached_native_observation(
    environment_id: str,
    scope_ref: str | None,
    output_limit: int,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]] | None:
    app_id = native_app_id_for_scope(scope_ref)
    if app_id is None or APP_EVENT_WATCHER_STATE != "ready":
        return None
    key = (environment_id, scope_ref, output_limit)
    with NATIVE_OBSERVATION_LOCK:
        cached = NATIVE_OBSERVATIONS.get(key)
        if cached is None or cached[0] != NATIVE_APP_GENERATIONS.get(app_id, 0):
            NATIVE_OBSERVATIONS.pop(key, None)
            return None
        NATIVE_OBSERVATIONS.move_to_end(key)
        return copy.deepcopy(cached[1]), dict(cached[2])


def cached_native_target_observation(
    environment_id: str,
    scope_ref: str | None,
    target_ref: str,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]] | None:
    app_id = native_app_id_for_scope(scope_ref)
    if app_id is None or APP_EVENT_WATCHER_STATE != "ready":
        return None
    with NATIVE_OBSERVATION_LOCK:
        generation = NATIVE_APP_GENERATIONS.get(app_id, 0)
        selected_key = None
        for key in reversed(NATIVE_OBSERVATIONS):
            cached = NATIVE_OBSERVATIONS[key]
            if (
                key[0] == environment_id
                and key[1] == scope_ref
                and cached[0] == generation
                and target_ref in cached[2]
            ):
                selected_key = key
                break
        if selected_key is not None:
            cached = NATIVE_OBSERVATIONS[selected_key]
            NATIVE_OBSERVATIONS.move_to_end(selected_key)
            return copy.deepcopy(cached[1]), dict(cached[2])
    return None


def remember_native_observation(
    environment_id: str,
    scope_ref: str | None,
    output_limit: int,
    expected_generation: int,
    snapshot: dict[str, Any],
    targets: dict[str, tuple[Any, dict[str, Any]]],
) -> None:
    app_id = native_app_id_for_scope(scope_ref)
    if app_id is None or APP_EVENT_WATCHER_STATE != "ready":
        return
    key = (environment_id, scope_ref, output_limit)
    with NATIVE_OBSERVATION_LOCK:
        if NATIVE_APP_GENERATIONS.get(app_id, 0) != expected_generation:
            return
        NATIVE_OBSERVATIONS.pop(key, None)
        NATIVE_OBSERVATIONS[key] = (
            expected_generation,
            copy.deepcopy(snapshot),
            dict(targets),
        )
        while len(NATIVE_OBSERVATIONS) > MAX_NATIVE_OBSERVATION_CACHE:
            NATIVE_OBSERVATIONS.popitem(last=False)


def require_atspi() -> None:
    global pyatspi
    if pyatspi is None:
        import pyatspi as atspi_module
        pyatspi = atspi_module


def app_event_cursor(sequence: int) -> str:
    return f"atspi:{APP_EVENT_EPOCH}:{sequence}"


def parse_app_event_cursor(value: Any) -> tuple[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("The app-event cursor is invalid.")
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "atspi" or len(parts[1]) != 16:
        raise ValueError("The app-event cursor is invalid.")
    try:
        sequence = int(parts[2])
    except ValueError as error:
        raise ValueError("The app-event cursor is invalid.") from error
    if sequence < 0:
        raise ValueError("The app-event cursor is invalid.")
    return parts[1], sequence


def app_event_kind(event_type: str) -> str:
    if event_type.startswith(("object:text-changed", "object:children-changed")):
        return "content_changed"
    if event_type.startswith(("window:activate", "object:state-changed:focused")):
        return "attention_required"
    return "state_changed"


def record_app_event(event: Any) -> None:
    global APP_EVENT_GAP, APP_EVENT_SEQUENCE
    source = safe(lambda: event.source)
    application_name = bounded_text(
        safe(lambda: source.getApplication().name, ""),
        160,
    )
    launcher = launcher_for_application(application_name)
    if launcher is None:
        return
    event_type = bounded_text(safe(lambda: event.type, ""), 120)
    if not event_type:
        return
    invalidate_native_observations(launcher["appId"])
    observed_at = (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    with APP_EVENT_CONDITION:
        APP_EVENT_SEQUENCE += 1
        sequence = APP_EVENT_SEQUENCE
        if len(APP_EVENT_BUFFER) == MAX_APP_EVENT_BUFFER:
            APP_EVENT_GAP = True
        APP_EVENT_BUFFER.append(
            {
                "sequence": sequence,
                "eventId": f"atspi-event:{APP_EVENT_EPOCH}:{sequence}",
                "cursor": app_event_cursor(sequence),
                "appId": launcher["appId"],
                "resourceRef": launcher["ref"],
                "kind": app_event_kind(event_type),
                "observedAt": observed_at,
            }
        )
        APP_EVENT_CONDITION.notify_all()


def poll_app_events(request: dict[str, Any]) -> dict[str, Any]:
    global APP_EVENT_GAP
    environment_id = request.get("environmentId")
    if not isinstance(environment_id, str) or not environment_id or len(environment_id) > 160:
        raise ValueError("The app-event environment is invalid.")
    limit = request.get("limit", 128)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_APP_EVENT_POLL:
        raise ValueError(f"The app-event limit must be between 1 and {MAX_APP_EVENT_POLL}.")
    wait_ms = request.get("waitMs", 0)
    if not isinstance(wait_ms, int) or isinstance(wait_ms, bool) or not 0 <= wait_ms <= 15_000:
        raise ValueError("The app-event waitMs must be between 0 and 15000.")
    parsed_cursor = parse_app_event_cursor(request.get("afterCursor"))

    def page_after_cursor() -> tuple[list[dict[str, Any]], int, bool]:
        current_sequence = APP_EVENT_SEQUENCE
        oldest_sequence = APP_EVENT_BUFFER[0]["sequence"] if APP_EVENT_BUFFER else current_sequence + 1
        gap_detected = APP_EVENT_GAP
        after_sequence = 0
        if parsed_cursor is not None:
            epoch, after_sequence = parsed_cursor
            if epoch != APP_EVENT_EPOCH:
                gap_detected = True
                after_sequence = oldest_sequence - 1
            elif after_sequence > current_sequence:
                raise ValueError("The app-event cursor is ahead of the source.")
            elif after_sequence < oldest_sequence - 1:
                gap_detected = True
                after_sequence = oldest_sequence - 1
        page = [
            record
            for record in APP_EVENT_BUFFER
            if record["sequence"] > after_sequence
        ][:limit]
        return page, current_sequence, gap_detected

    with APP_EVENT_CONDITION:
        page, current_sequence, gap_detected = page_after_cursor()
        if not page and not gap_detected and wait_ms > 0:
            APP_EVENT_CONDITION.wait(wait_ms / 1000)
            page, current_sequence, gap_detected = page_after_cursor()
        page_sequence = page[-1]["sequence"] if page else current_sequence
        records = [
            {key: value for key, value in record.items() if key != "sequence"}
            for record in page
        ]
        APP_EVENT_GAP = False
    return {
        "status": "ok",
        "batch": {
            "source": "at_spi",
            "sourceId": "atspi",
            "cursor": app_event_cursor(page_sequence),
            "gapDetected": gap_detected,
            "events": records,
        },
    }


def app_event_watcher_main() -> None:
    global APP_EVENT_WATCHER_STATE
    try:
        require_atspi()
        for event_type in (
            "object:children-changed",
            "object:text-changed",
            "object:state-changed:focused",
            "object:property-change:accessible-name",
            "window:activate",
            "window:create",
            "window:destroy",
        ):
            pyatspi.Registry.registerEventListener(record_app_event, event_type)
        APP_EVENT_WATCHER_STATE = "ready"
        pyatspi.Registry.start()
    except Exception:
        APP_EVENT_WATCHER_STATE = "failed"


def start_app_event_watcher() -> None:
    global APP_EVENT_WATCHER_STATE
    if APP_EVENT_WATCHER_STATE != "not_started":
        return
    APP_EVENT_WATCHER_STATE = "starting"
    threading.Thread(
        target=app_event_watcher_main,
        name="wiii-atspi-events",
        daemon=True,
    ).start()

WORKSTATION_NODE = {
    "ref": "workstation:main",
    "parentRef": None,
    "appId": None,
    "role": "workstation",
    "name": "Máy tính công việc của Neko",
    "description": "Không gian làm việc bền vững với ứng dụng và hồ sơ riêng của Neko.",
    "value": None,
    "states": ["available"],
    "actions": [],
    "bounds": None,
    "sources": ["workstation"],
}

CORE_APP_LAUNCHERS = (
    {
        "ref": "app:browser",
        "appId": "browser",
        "name": "Trình duyệt",
        "description": "invoke mở Chrome; set_text tìm kiếm hoặc mở URL bằng hồ sơ của Neko.",
        "argv": ("wiii-browser", "about:blank"),
        "matchTerms": ("google chrome",),
        "processNames": ("chrome",),
        "adapter": {
            "id": "wiii.chrome.v1",
            "version": "1",
            "capabilities": ("navigate", "search", "keyboard", "semantic_controls", "persistent_profile"),
        },
    },
    {
        "ref": "app:terminal",
        "appId": "terminal",
        "name": "Terminal",
        "description": "Mở Terminal tại Project đang được cấp quyền.",
        "argv": ("lxterminal", "--working-directory=/workspace/project"),
        "matchTerms": ("terminal", "lxterminal"),
        "processNames": ("lxterminal",),
        "adapter": {
            "id": "wiii.terminal.v1",
            "version": "1",
            "capabilities": ("open_project", "terminal_exec", "semantic_controls"),
        },
    },
    {
        "ref": "app:files",
        "appId": "files",
        "name": "Tệp dự án",
        "description": "Mở trình quản lý tệp tại Project đang được cấp quyền.",
        "argv": ("pcmanfm", "--new-win", "--role=wiii-project-files", "/workspace/project"),
        "matchTerms": ("file manager", "pcmanfm", "tệp dự án"),
        "processNames": ("pcmanfm",),
        "adapter": {
            "id": "wiii.files.v1",
            "version": "1",
            "capabilities": ("open_project", "browse_project", "semantic_controls"),
        },
    },
)
OPTIONAL_APP_LAUNCHERS = (
    {
        "ref": "app:wechat",
        "appId": "wechat",
        "name": "WeChat",
        "description": "Mở WeChat bằng hồ sơ bền vững riêng của Neko.",
        "argv": ("/home/neko/.local/share/wiii/apps/wechat/4.1.1/runtime/AppRun",),
        "matchTerms": ("wechat", "weixin", "微信"),
        "processNames": ("wechat", "weixin"),
        "requiredPath": "/home/neko/.local/share/wiii/apps/wechat/4.1.1/runtime/AppRun",
        "environment": {"QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"},
        "adapter": {
            "id": "wiii.wechat.v2",
            "version": "2",
            "capabilities": (
                "launch",
                "semantic_controls",
                "persistent_profile",
                "conversation_identity",
                "unread_state",
                "message_delta",
                "select_conversation",
                "composer_readback",
                "send_evidence",
            ),
        },
    },
    {
        "ref": "app:office",
        "appId": "office",
        "name": "Office",
        "description": "Mở bộ ứng dụng tài liệu, bảng tính và trình chiếu của Neko.",
        "argv": ("libreoffice", "--startcenter"),
        "matchTerms": ("libreoffice", "writer", "calc", "impress"),
        "processNames": ("soffice.bin",),
        "requiredCommand": "libreoffice",
        "adapter": {
            "id": "wiii.libreoffice.v1",
            "version": "1",
            "capabilities": ("launch", "documents", "spreadsheets", "presentations", "semantic_controls"),
        },
    },
)


def available_app_launchers() -> tuple[dict[str, Any], ...]:
    optional = tuple(
        launcher
        for launcher in OPTIONAL_APP_LAUNCHERS
        if (
            ("requiredPath" in launcher and os.access(launcher["requiredPath"], os.X_OK))
            or ("requiredCommand" in launcher and shutil.which(launcher["requiredCommand"]) is not None)
        )
    )
    return (*CORE_APP_LAUNCHERS, *optional)


APP_LAUNCHERS = available_app_launchers()
APP_LAUNCHERS_BY_REF = {launcher["ref"]: launcher for launcher in APP_LAUNCHERS}
APP_LAUNCHERS_BY_ID = {launcher["appId"]: launcher for launcher in APP_LAUNCHERS}
GMAIL_ADAPTER = {
    "id": "wiii.gmail.rendered.v1",
    "version": "1",
    "capabilities": (
        "scan_inbox",
        "open_thread",
        "compose",
        "semantic_controls",
        "persistent_profile",
    ),
}


def launcher_node(launcher: dict[str, Any]) -> dict[str, Any]:
    actions = ["invoke"]
    states = ["enabled", "sensitive"]
    if launcher["appId"] == "browser":
        actions.extend(("set_text", "press_key", "input_sequence"))
        states.append("accepts_text_query")
    return {
        "ref": launcher["ref"],
        "parentRef": WORKSTATION_NODE["ref"],
        "appId": launcher["appId"],
        "role": "browser" if launcher["appId"] == "browser" else "application_launcher",
        "name": launcher["name"],
        "description": launcher["description"],
        "value": None,
        "states": states,
        "actions": actions,
        "bounds": None,
        "sources": ["workstation"],
        "adapter": {
            **launcher["adapter"],
            "capabilities": list(launcher["adapter"]["capabilities"]),
        },
    }


def browser_navigation_target(text: str) -> str:
    value = text.strip()
    if not value:
        raise ValueError("Browser navigation requires a URL or search query.")
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return f"https://www.google.com/search?q={quote_plus(value)}"


class CdpConnection:
    def __init__(self, page: dict[str, Any], timeout: float = 5) -> None:
        self.socket = websocket.create_connection(
            page["webSocketDebuggerUrl"],
            timeout=timeout,
            suppress_origin=True,
        )
        self.message_id = 0

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.message_id += 1
        message_id = self.message_id
        self.socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.socket.recv())
            if response.get("method") == "Page.javascriptDialogOpening":
                dialog_type = bounded_text(response.get("params", {}).get("type"), 40) or "JavaScript"
                raise RuntimeError(f"{dialog_type} dialog requires human takeover.")
            if response.get("id") != message_id:
                continue
            if "error" in response:
                raise RuntimeError(bounded_text(response["error"].get("message"), 500))
            return response.get("result", {})

    def __enter__(self) -> CdpConnection:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()


def browser_debug_targets() -> list[dict[str, Any]]:
    with urlopen("http://127.0.0.1:9222/json/list", timeout=0.8) as response:
        targets = json.load(response)
    if not isinstance(targets, list):
        return []
    return [
        target
        for target in targets
        if isinstance(target, dict)
        and isinstance(target.get("webSocketDebuggerUrl"), str)
        and not str(target.get("url") or "").startswith("chrome://")
    ]


def browser_pages() -> list[dict[str, Any]]:
    return [target for target in browser_debug_targets() if target.get("type") == "page"]


def browser_control_target() -> dict[str, str]:
    try:
        with open(
            "/home/neko/.wiii/google-chrome/DevToolsActivePort",
            encoding="utf-8",
        ) as handle:
            lines = [line.strip() for line in handle.readlines()[:2]]
        port = int(lines[0])
        path = lines[1]
        if not 0 < port <= 65535 or not path.startswith("/devtools/browser/"):
            raise ValueError("invalid DevTools control endpoint")
        return {"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}{path}"}
    except (FileNotFoundError, OSError, ValueError, IndexError):
        with urlopen("http://127.0.0.1:9222/json/version", timeout=2.0) as response:
            control = json.load(response)
        if not isinstance(control, dict) or not isinstance(
            control.get("webSocketDebuggerUrl"), str
        ):
            raise RuntimeError("Chrome did not expose its browser control target.")
        return control


def create_browser_target(target: str) -> str:
    try:
        with CdpConnection(browser_control_target(), timeout=3.0) as cdp:
            created = cdp.call("Target.createTarget", {"url": target})
    except Exception as control_error:
        try:
            endpoint = "http://127.0.0.1:9222/json/new?" + quote(target, safe="")
            with urlopen(Request(endpoint, method="PUT"), timeout=3.0) as response:
                created = json.load(response)
        except Exception as fallback_error:
            raise RuntimeError(
                "Chrome replacement target creation failed: "
                f"control={bounded_text(control_error, 200)}; "
                f"fallback={bounded_text(fallback_error, 200)}"
            ) from fallback_error
    target_id = (
        created.get("targetId") or created.get("id")
        if isinstance(created, dict)
        else None
    )
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("Chrome did not return a replacement page target.")
    return target_id


def close_browser_target(target_id: str) -> None:
    try:
        with CdpConnection(browser_control_target(), timeout=3.0) as cdp:
            result = cdp.call("Target.closeTarget", {"targetId": target_id})
        if result.get("success") is not True:
            raise RuntimeError("Chrome did not acknowledge target closure.")
    except Exception as control_error:
        try:
            endpoint = "http://127.0.0.1:9222/json/close/" + quote(target_id, safe="")
            with urlopen(endpoint, timeout=3.0) as response:
                response.read(4096)
        except Exception as fallback_error:
            raise RuntimeError(
                "Chrome target closure failed: "
                f"control={bounded_text(control_error, 200)}; "
                f"fallback={bounded_text(fallback_error, 200)}"
            ) from fallback_error


def browser_control_pages() -> list[dict[str, Any]]:
    control = browser_control_target()
    endpoint = urlsplit(control["webSocketDebuggerUrl"])
    with CdpConnection(control, timeout=2.0) as cdp:
        target_infos = cdp.call("Target.getTargets").get("targetInfos", [])
    return [
        {
            "id": info["targetId"],
            "type": "page",
            "title": bounded_text(info.get("title"), 500),
            "url": bounded_text(info.get("url"), 2000),
            "webSocketDebuggerUrl": (
                f"{endpoint.scheme}://{endpoint.netloc}/devtools/page/{info['targetId']}"
            ),
        }
        for info in target_infos
        if isinstance(info, dict)
        and info.get("type") == "page"
        and isinstance(info.get("targetId"), str)
    ]


def close_browser_origin_pages(
    origin: tuple[str, str, int | None] | None,
    retained_target_id: str,
) -> None:
    if origin is None:
        return
    try:
        pages = browser_control_pages()
    except Exception:
        return
    for page in pages:
        target_id = str(page.get("id") or "")
        if target_id == retained_target_id or url_origin(page.get("url")) != origin:
            continue
        try:
            close_browser_target(target_id)
        except Exception:
            continue


def browser_frame_targets(root_target_id: str) -> list[dict[str, Any]]:
    candidates = [target for target in browser_debug_targets() if target.get("type") == "iframe"]
    descendants = {root_target_id}
    selected: list[dict[str, Any]] = []
    for _ in range(MAX_BROWSER_FRAMES):
        added = [target for target in candidates if target.get("parentId") in descendants and target not in selected]
        if not added:
            break
        selected.extend(added)
        descendants.update(str(target["id"]) for target in added if isinstance(target.get("id"), str))
    return selected[:MAX_BROWSER_FRAMES]


def active_browser_page() -> dict[str, Any] | None:
    pages = browser_pages()
    if len(pages) == 1:
        remember_active_browser_target(pages[0].get("id"))
        return pages[0]
    for page in pages:
        try:
            with CdpConnection(page) as cdp:
                result = cdp.call(
                    "Runtime.evaluate",
                    {"expression": "document.hasFocus()", "returnByValue": True},
                )
            if result.get("result", {}).get("value") is True:
                remember_active_browser_target(page.get("id"))
                return page
        except Exception:
            continue
    selected = pages[0] if pages else None
    if selected is not None:
        remember_active_browser_target(selected.get("id"))
    return selected


def realtime_clock_path(target_id: str) -> str:
    digest = hashlib.sha256(target_id.encode("utf-8")).hexdigest()
    return os.path.join(REALTIME_CLOCK_DIR, f"{digest}.json")


def realtime_clock_state(page: dict[str, Any] | None) -> dict[str, Any] | None:
    target_id = page.get("id") if page is not None else None
    if not isinstance(target_id, str) or not target_id:
        return None
    try:
        with open(realtime_clock_path(target_id), encoding="utf-8") as handle:
            state = json.load(handle)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("targetId") != target_id:
        return None
    if os.name == "posix":
        pid = state.get("pid")
        token = state.get("token")
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                command = handle.read(8192)
        except (FileNotFoundError, OSError, TypeError):
            command = b""
        if (
            not isinstance(pid, int)
            or pid <= 0
            or not isinstance(token, str)
            or b"clock-watchdog" not in command
            or token.encode("utf-8") not in command
        ):
            try:
                os.remove(realtime_clock_path(target_id))
            except FileNotFoundError:
                pass
            return None
    return state


def realtime_clock_write(target_id: str, token: str, deadline_ms: int) -> None:
    os.makedirs(REALTIME_CLOCK_DIR, mode=0o700, exist_ok=True)
    path = realtime_clock_path(target_id)
    temporary = f"{path}.{token}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "targetId": target_id,
                "token": token,
                "deadlineMs": deadline_ms,
                "pid": os.getpid(),
            },
            handle,
            separators=(",", ":"),
        )
    os.replace(temporary, path)


def realtime_clock_clear(target_id: str, token: str | None = None) -> None:
    path = realtime_clock_path(target_id)
    if token is not None:
        state = realtime_clock_state({"id": target_id})
        if state is None or state.get("token") != token:
            return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def realtime_clock_resume(cdp: CdpConnection) -> None:
    cdp.call("Debugger.enable")
    try:
        cdp.call("Debugger.resume")
    except RuntimeError as error:
        if "while paused" not in str(error):
            raise


def realtime_clock_resume_page(page: dict[str, Any]) -> bool:
    target_id = page.get("id")
    if not isinstance(target_id, str) or not target_id:
        return False
    state = realtime_clock_state(page)
    try:
        with CdpConnection(page) as cdp:
            realtime_clock_resume(cdp)
    except Exception:
        return False
    realtime_clock_clear(
        target_id,
        state.get("token") if isinstance(state, dict) else None,
    )
    return True


def realtime_clock_resume_all() -> int:
    pages = {
        page.get("id"): page
        for page in browser_pages()
        if isinstance(page.get("id"), str)
    }
    resumed = 0
    try:
        names = os.listdir(REALTIME_CLOCK_DIR)
    except FileNotFoundError:
        return 0
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(REALTIME_CLOCK_DIR, name)
        try:
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            continue
        target_id = state.get("targetId") if isinstance(state, dict) else None
        page = pages.get(target_id)
        if page is not None and realtime_clock_resume_page(page):
            resumed += 1
        elif isinstance(target_id, str):
            realtime_clock_clear(target_id)
    return resumed


def realtime_clock_hold(page: dict[str, Any]) -> dict[str, Any]:
    target_id = page.get("id")
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("Realtime step clock requires a browser page target.")
    token = secrets.token_hex(16)
    deadline_ms = int(time.time() * 1000) + REALTIME_CLOCK_WATCHDOG_MS
    process = subprocess.Popen(
        [
            sys.executable,
            os.path.abspath(__file__),
            "clock-watchdog",
            "--target-id",
            target_id,
            "--token",
            token,
            "--deadline-ms",
            str(deadline_ms),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    ready_deadline = time.monotonic() + 2.0
    while time.monotonic() < ready_deadline:
        state = realtime_clock_state(page)
        if state is not None and state.get("token") == token:
            break
        if process.poll() is not None:
            break
        time.sleep(0.01)
    else:
        state = None
    if state is None or state.get("token") != token:
        process.terminate()
        realtime_clock_clear(target_id, token)
        raise RuntimeError("Realtime step clock did not pause the browser page.")
    return {
        "mode": "stepped",
        "watchdogMs": REALTIME_CLOCK_WATCHDOG_MS,
        "deadlineMs": deadline_ms,
    }


def realtime_clock_watchdog(target_id: str, token: str, deadline_ms: int) -> None:
    page = next((candidate for candidate in browser_pages() if candidate.get("id") == target_id), None)
    if page is None:
        return
    try:
        with CdpConnection(page) as cdp:
            cdp.call("Debugger.enable")
            cdp.call("Debugger.pause")
            realtime_clock_write(target_id, token, deadline_ms)
            while True:
                remaining = deadline_ms - int(time.time() * 1000)
                if remaining <= 0:
                    realtime_clock_resume(cdp)
                    return
                state = realtime_clock_state(page)
                if state is None or state.get("token") != token:
                    return
                cdp.socket.settimeout(min(5.0, remaining / 1000))
                try:
                    message = json.loads(cdp.socket.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if message.get("method") == "Debugger.resumed":
                    return
    finally:
        realtime_clock_clear(target_id, token)


def wait_for_browser_navigation(
    target: str,
    before: dict[str, Any] | None,
    timeout: float,
    target_id: str | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser_navigation_completed(target, before, target_id):
            return True
        time.sleep(0.05)
    return browser_navigation_completed(target, before, target_id)


def browser_page_target(target_id: str) -> dict[str, str]:
    control = browser_control_target()
    endpoint = urlsplit(control["webSocketDebuggerUrl"])
    if endpoint.scheme not in {"ws", "wss"} or not endpoint.netloc:
        raise RuntimeError("Chrome exposed an invalid browser control socket.")
    return {
        "id": target_id,
        "type": "page",
        "webSocketDebuggerUrl": f"{endpoint.scheme}://{endpoint.netloc}/devtools/page/{target_id}",
    }


def replace_browser_page(
    target: str,
    old_target_id: str | None,
    release_busy_target: bool = False,
    release_origin: tuple[str, str, int | None] | None = None,
) -> str:
    released_target = False
    if release_busy_target and isinstance(old_target_id, str):
        close_browser_target(old_target_id)
        released_target = True
    creation_error = None
    new_target_id = None
    for attempt in range(2):
        try:
            new_target_id = create_browser_target("about:blank")
            break
        except Exception as error:
            creation_error = error
            if attempt == 0:
                time.sleep(0.25)
    if new_target_id is None:
        raise RuntimeError(
            "Chrome could not allocate a clean replacement page: "
            f"{bounded_text(creation_error, 500)}"
        ) from creation_error
    navigated = False
    for attempt in range(2):
        try:
            with CdpConnection(browser_page_target(new_target_id), timeout=2.0) as cdp:
                result = cdp.call("Page.navigate", {"url": target})
            error = result.get("errorText")
            if error and error != "net::ERR_ABORTED":
                raise RuntimeError(bounded_text(error, 500))
        except Exception:
            pass
        if wait_for_browser_navigation(target, None, 3.0, new_target_id):
            navigated = True
            break
        if attempt == 0:
            time.sleep(0.2)
    if not navigated:
        close_browser_target(new_target_id)
        raise RuntimeError("Chrome could not recover navigation from the busy page.")
    if release_busy_target:
        close_browser_origin_pages(release_origin, new_target_id)
    if (
        not released_target
        and isinstance(old_target_id, str)
        and old_target_id != new_target_id
    ):
        close_browser_target(old_target_id)
    return new_target_id


def navigate_browser(target: str) -> dict[str, Any] | None:
    try:
        page = active_browser_page()
    except Exception:
        try:
            page = known_active_browser_page()
        except Exception:
            page = None
    if page is None:
        try:
            target_id = replace_browser_page(target, None)
            remember_active_browser_target(target_id)
            return {"pageId": None, "url": None, "navigationTargetId": target_id}
        except Exception:
            if launcher_process_ids(APP_LAUNCHERS_BY_REF["app:browser"]):
                raise
            launch_application(APP_LAUNCHERS_BY_REF["app:browser"], target)
            return None
    before = {
        "pageId": page.get("id"),
        "url": bounded_text(page.get("url"), 2000),
        "navigationTargetId": page.get("id"),
    }
    try:
        with CdpConnection(page, timeout=1.0) as cdp:
            cdp.call("Page.stopLoading")
            result = cdp.call("Page.navigate", {"url": target})
    except Exception:
        before["navigationTargetId"] = replace_browser_page(
            target,
            page.get("id"),
            release_busy_target=True,
            release_origin=url_origin(page.get("url")),
        )
        remember_active_browser_target(before["navigationTargetId"])
        return before
    error = result.get("errorText")
    if not error:
        remember_active_browser_target(page.get("id"))
        return before
    if error != "net::ERR_ABORTED":
        raise RuntimeError(bounded_text(error, 500))
    if wait_for_browser_navigation(target, before, 1.0, page.get("id")):
        remember_active_browser_target(page.get("id"))
        return before

    before["navigationTargetId"] = replace_browser_page(
        target,
        page.get("id"),
        release_busy_target=True,
        release_origin=url_origin(page.get("url")),
    )
    remember_active_browser_target(before["navigationTargetId"])
    return before


def launch_application(launcher: dict[str, Any], target: str | None = None) -> subprocess.Popen:
    argv = launcher["argv"]
    if target is not None:
        if launcher["appId"] != "browser":
            raise ValueError("Only the browser launcher accepts a navigation target.")
        argv = (*argv[:-1], target)
    environment = os.environ.copy()
    environment.update(launcher.get("environment", {}))
    return subprocess.Popen(
        argv,
        cwd="/workspace/project",
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def browser_url_matches_target(current_value: str, target: str) -> bool:
    expected = urlsplit(target)
    expected_query = parse_qs(expected.query)
    if current_value == target:
        return True
    current = urlsplit(current_value)
    return bool(
        current.hostname == expected.hostname
        and expected_query
        and all(parse_qs(current.query).get(key) == values for key, values in expected_query.items())
    )


def browser_reached_target(target: str) -> bool:
    try:
        pages = browser_pages()
    except Exception:
        return False
    for page in pages:
        current_value = page.get("url") if isinstance(page, dict) else None
        if not isinstance(current_value, str):
            continue
        if browser_url_matches_target(current_value, target):
            return True
    return False


def browser_page_state(page: dict[str, Any] | None = None) -> dict[str, Any] | None:
    selected = page or active_browser_page()
    if selected is None:
        return None
    try:
        with CdpConnection(selected) as cdp:
            result = cdp.call(
                "Runtime.evaluate",
                {
                    "expression": "({url:location.href,ready:document.readyState,timeOrigin:performance.timeOrigin})",
                    "returnByValue": True,
                },
            )
    except Exception:
        return None
    facts = result.get("result", {}).get("value")
    if not isinstance(facts, dict):
        return None
    return {
        "pageId": selected.get("id"),
        "url": bounded_text(facts.get("url"), 2000),
        "ready": facts.get("ready"),
        "timeOrigin": facts.get("timeOrigin"),
    }


def browser_navigation_completed(
    target: str,
    before: dict[str, Any] | None,
    target_id: str | None = None,
) -> bool:
    try:
        page = browser_page_target(target_id) if target_id is not None else None
    except Exception:
        return False
    after = browser_page_state(page)
    if after is None or after.get("ready") not in {"interactive", "complete"}:
        return False
    current_url = after.get("url")
    if isinstance(current_url, str) and browser_url_matches_target(current_url, target):
        return True
    if before is None:
        expected_scheme = urlsplit(target).scheme.casefold()
        current_scheme = urlsplit(str(current_url or "")).scheme.casefold()
        return bool(
            target_id is not None
            and expected_scheme in {"http", "https"}
            and current_scheme in {"http", "https"}
        )
    return any(after.get(field) != before.get(field) for field in ("pageId", "url", "timeOrigin"))


def workstation_nodes() -> list[dict[str, Any]]:
    return [
        dict(WORKSTATION_NODE),
        *(launcher_node(launcher) for launcher in APP_LAUNCHERS),
    ]


def project_file_nodes(root: str = "/workspace/project", max_entries: int = 256) -> list[dict[str, Any]]:
    adapter = adapter_payload(APP_LAUNCHERS_BY_REF.get("app:files"))
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    entries.sort(
        key=lambda entry: (
            not entry.is_dir(follow_symlinks=False),
            entry.name.casefold(),
        )
    )
    limit = max(1, min(max_entries, MAX_STATE_NODES - len(APP_LAUNCHERS) - 1))
    nodes: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        try:
            is_directory = entry.is_dir(follow_symlinks=False)
            is_symlink = entry.is_symlink()
        except OSError:
            continue
        relative_path = bounded_text(entry.name, 512)
        material = json.dumps(
            {"root": "project", "path": relative_path},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        states = ["enabled", "directory" if is_directory else "regular"]
        if is_symlink:
            states.append("symlink")
        node = {
            "ref": "file-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16],
            "parentRef": "app:files",
            "appId": "files",
            "role": "folder" if is_directory else "file",
            "name": bounded_text(entry.name, 160),
            "description": "Thư mục trong Project" if is_directory else "Tệp trong Project",
            "value": relative_path,
            "states": states,
            "actions": [],
            "bounds": None,
            "sources": ["filesystem"],
        }
        if adapter is not None:
            node["adapter"] = adapter
        nodes.append(node)
    return nodes


def launcher_for_application(name: str) -> dict[str, Any] | None:
    folded = name.casefold()
    return next(
        (
            launcher
            for launcher in APP_LAUNCHERS
            if any(term.casefold() in folded for term in launcher["matchTerms"])
        ),
        None,
    )


def adapter_payload(launcher: dict[str, Any] | None) -> dict[str, Any] | None:
    if launcher is None:
        return None
    adapter = launcher["adapter"]
    return {
        "id": adapter["id"],
        "version": adapter["version"],
        "capabilities": list(adapter["capabilities"]),
    }


def semantic_node_version(node: dict[str, Any]) -> str:
    material = json.dumps(
        {key: value for key, value in node.items() if key != "version"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def versioned_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in nodes:
        node = dict(source)
        node["version"] = semantic_node_version(node)
        result.append(node)
    return result


def scoped_nodes(nodes: list[dict[str, Any]], scope_ref: str | None) -> list[dict[str, Any]]:
    if scope_ref is None:
        return nodes
    by_ref = {node["ref"]: node for node in nodes}
    if scope_ref not in by_ref:
        raise ValueError("The requested semantic scope is no longer available.")
    if scope_ref == WORKSTATION_NODE["ref"]:
        return [
            node
            for node in nodes
            if node["ref"] == scope_ref
            or (node.get("parentRef") == scope_ref and str(node["ref"]).startswith("app:"))
        ]
    return [
        node
        for node in nodes
        if node["ref"] == scope_ref or node_descends_from(node, scope_ref, by_ref)
    ]


def normalize_known_versions(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, list) or len(value) > MAX_KNOWN_NODE_VERSIONS:
        raise ValueError("knownNodeVersions must be a bounded list.")
    result: dict[str, str] = {}
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("knownNodeVersions contains an invalid entry.")
        node_ref = entry.get("ref")
        version = entry.get("version")
        if not isinstance(node_ref, str) or not node_ref or len(node_ref) > 256:
            raise ValueError("knownNodeVersions contains an invalid ref.")
        if not isinstance(version, str) or not version.startswith("sha256:") or len(version) > 96:
            raise ValueError("knownNodeVersions contains an invalid version.")
        result[node_ref] = version
    return result


def known_versions_digest(known_versions: dict[str, str]) -> str:
    material = json.dumps(known_versions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def continuation_signing_key(environment_id: str) -> bytes:
    with open(CONTINUATION_SECRET_PATH, "rb") as secret_file:
        secret = secret_file.read(4096)
    if len(secret) < 16:
        raise RuntimeError("The workstation continuation secret is unavailable.")
    return hmac.new(secret, environment_id.encode("utf-8"), hashlib.sha256).digest()


def encode_continuation(environment_id: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(continuation_signing_key(environment_id), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + signature).rstrip(b"=").decode("ascii")


def decode_continuation(environment_id: str, token: str) -> dict[str, Any]:
    if not token or len(token) > MAX_CONTINUATION_BYTES:
        raise ValueError("The semantic continuation is invalid.")
    try:
        padded = token + "=" * (-len(token) % 4)
        packed = base64.urlsafe_b64decode(padded.encode("ascii"))
        canonical = base64.urlsafe_b64encode(packed).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(token, canonical):
            raise ValueError
        raw, signature = packed[:-32], packed[-32:]
        expected = hmac.new(continuation_signing_key(environment_id), raw, hashlib.sha256).digest()
        if len(raw) == 0 or not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(raw)
    except Exception as error:
        raise ValueError("The semantic continuation is invalid.") from error
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("e") != environment_id:
        raise ValueError("The semantic continuation is invalid.")
    return payload


def project_scene(
    environment_id: str,
    nodes: list[dict[str, Any]],
    max_nodes: int,
    base_scope: str,
    capture_truncated: bool = False,
    scope_ref: str | None = None,
    continuation: str | None = None,
    since_state_version: str | None = None,
    known_node_versions: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_nodes = versioned_nodes(nodes)
    scoped = scoped_nodes(all_nodes, scope_ref)
    state_version = snapshot_version(
        scoped,
        f"{base_scope}:{scope_ref or '*'}",
        capture_truncated,
    )
    known = normalize_known_versions(known_node_versions)
    projection = "delta" if since_state_version is not None or known else "full"
    if projection == "full":
        candidates = scoped
    elif since_state_version == state_version and not known:
        candidates = []
    else:
        candidates = [node for node in scoped if known.get(node["ref"]) != node["version"]]
    offset = 0
    digest = known_versions_digest(known)
    if continuation is not None:
        cursor = decode_continuation(environment_id, continuation)
        if (
            cursor.get("s") != (scope_ref or "")
            or cursor.get("m") != projection
            or cursor.get("sv") != state_version
            or cursor.get("k") != digest
        ):
            raise ValueError("The semantic continuation is stale.")
        offset = cursor.get("o")
        if not isinstance(offset, int) or offset < 0 or offset > len(candidates):
            raise ValueError("The semantic continuation is invalid.")
    limit = max(1, min(int(max_nodes), MAX_STATE_NODES))
    visible = candidates[offset:offset + limit]
    next_offset = offset + len(visible)
    next_continuation = None
    if next_offset < len(candidates):
        next_continuation = encode_continuation(
            environment_id,
            {
                "v": 1,
                "e": environment_id,
                "s": scope_ref or "",
                "m": projection,
                "o": next_offset,
                "sv": state_version,
                "k": digest,
            },
        )
    current_refs = {node["ref"] for node in scoped}
    removed_refs = sorted(set(known) - current_refs) if projection == "delta" and offset == 0 else []
    return visible, {
        "stateVersion": state_version,
        "scopeRef": scope_ref,
        "projection": projection,
        "nextContinuation": next_continuation,
        "deltaFromStateVersion": since_state_version if projection == "delta" else None,
        "removedRefs": removed_refs,
        "truncated": capture_truncated or next_continuation is not None,
        "scopedNodes": scoped,
    }


def snapshot_version(nodes: list[dict[str, Any]], scope: str, capture_truncated: bool) -> str:
    material = json.dumps(
        {"scope": scope, "nodes": nodes, "captureTruncated": capture_truncated},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def ai_frame(scope: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    modalities = sorted({
        source
        for node in nodes
        for source in node.get("sources", [])
        if isinstance(source, str)
    })
    focused = sorted(
        (node for node in nodes if "focused" in node.get("states", [])),
        key=lambda node: (
            node.get("role") != "canvas",
            "set_text" not in node.get("actions", []),
            not node.get("actions"),
        ),
    )
    target = focused[0] if focused else None
    role = str(target.get("role") or "") if target is not None else ""
    actions = list(target.get("actions", [])) if target is not None else []
    shortcuts = list(target.get("shortcuts", [])) if target is not None else []
    clock_state = None
    if role == "canvas":
        try:
            clock_state = realtime_clock_state(active_browser_page())
        except Exception:
            clock_state = None
    if role == "canvas":
        mode = "canvas_keyboard"
        feedback = "post_action_visual"
        keymap_source = "declared" if shortcuts else "unknown"
    elif "set_text" in actions:
        mode = "text_entry"
        feedback = "semantic_delta"
        keymap_source = "declared" if shortcuts else "none"
    elif role in {"document", "document web"}:
        mode = "document_navigation"
        feedback = "semantic_delta"
        keymap_source = "declared" if shortcuts else "none"
    elif target is not None:
        mode = "semantic_control"
        feedback = "semantic_delta"
        keymap_source = "declared" if shortcuts else "none"
    else:
        mode = "semantic_control"
        feedback = "observe"
        keymap_source = "none"
    return {
        "version": AI_FRAME_VERSION,
        "scope": scope,
        "observationModel": "scene_graph",
        "actionModel": "typed_refs",
        "coordinates": "adapter_private",
        "modalities": modalities,
        "interaction": {
            "mode": mode,
            "targetRef": target.get("ref") if target is not None else None,
            "inputActions": actions,
            "keymapSource": keymap_source,
            "shortcuts": shortcuts,
            "feedback": feedback,
            "clockMode": "stepped" if clock_state is not None else "continuous",
            "clockModes": ["continuous", "stepped"] if role == "canvas" else ["continuous"],
            "clockWatchdogMs": REALTIME_CLOCK_WATCHDOG_MS if role == "canvas" else None,
        },
    }


def semantic_node_ref(_index: int, node: dict[str, Any], native_identity: str | None = None) -> str:
    identity = (
        {"appId": node["appId"], "nativeIdentity": native_identity}
        if native_identity
        else {
            "parentRef": node["parentRef"],
            "appId": node["appId"],
            "role": node["role"],
            "name": node["name"],
            "value": node["value"],
        }
    )
    material = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return f"ui-{fingerprint}"


def accessibility_object_identity(accessible) -> str | None:
    path = bounded_text(safe(lambda: accessible.path, ""), 512)
    process_id = safe(lambda: accessible.get_process_id(), -1)
    if not path or not isinstance(process_id, int) or process_id < 0:
        return None
    return f"{process_id}:{path}"


def web_node_ref(
    target_id: str,
    frame_id: str,
    node_id: Any,
    backend_node_id: Any,
) -> str:
    material = json.dumps(
        {
            "target": target_id,
            "frame": frame_id,
            "node": node_id,
            "backend": backend_node_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "web-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def workstation_snapshot(
    environment_id: str,
    output_limit: int,
    scope_ref: str | None = None,
    continuation: str | None = None,
    since_state_version: str | None = None,
    known_node_versions: Any = None,
) -> dict[str, Any]:
    nodes = workstation_nodes()
    visible_nodes, projection = project_scene(
        environment_id,
        nodes,
        output_limit,
        "workstation",
        scope_ref=scope_ref,
        continuation=continuation,
        since_state_version=since_state_version,
        known_node_versions=known_node_versions,
    )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "environmentId": environment_id,
        "stateVersion": projection["stateVersion"],
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "linux_atspi",
        "screen": {"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
        "activeWindowRef": None,
        "frame": ai_frame("workstation", projection["scopedNodes"]),
        "nodes": visible_nodes,
        "truncated": projection["truncated"],
        "scopeRef": projection["scopeRef"],
        "projection": projection["projection"],
        "nextContinuation": projection["nextContinuation"],
        "deltaFromStateVersion": projection["deltaFromStateVersion"],
        "removedRefs": projection["removedRefs"],
    }


def files_snapshot(
    environment_id: str,
    output_limit: int,
    scope_ref: str | None = "app:files",
    continuation: str | None = None,
    since_state_version: str | None = None,
    known_node_versions: Any = None,
) -> dict[str, Any]:
    nodes = [*workstation_nodes(), *project_file_nodes()]
    visible_nodes, projection = project_scene(
        environment_id,
        nodes,
        output_limit,
        "files",
        scope_ref=scope_ref,
        continuation=continuation,
        since_state_version=since_state_version,
        known_node_versions=known_node_versions,
    )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "environmentId": environment_id,
        "stateVersion": projection["stateVersion"],
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "linux_atspi",
        "screen": {"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
        "activeWindowRef": None,
        "frame": ai_frame("files", projection["scopedNodes"]),
        "nodes": visible_nodes,
        "truncated": projection["truncated"],
        "scopeRef": projection["scopeRef"],
        "projection": projection["projection"],
        "nextContinuation": projection["nextContinuation"],
        "deltaFromStateVersion": projection["deltaFromStateVersion"],
        "removedRefs": projection["removedRefs"],
    }


def launcher_process_ids(launcher: dict[str, Any]) -> set[int]:
    process_ids: set[int] = set()
    for process_name in launcher["processNames"]:
        completed = subprocess.run(
            ("pgrep", "-x", process_name),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            continue
        process_ids.update(
            int(value)
            for value in completed.stdout.split()
            if value.isdigit()
        )
    return process_ids


def launcher_window_ids(launcher: dict[str, Any]) -> set[str]:
    try:
        completed = subprocess.run(
            ("wmctrl", "-lx"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
            timeout=0.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    if completed.returncode != 0:
        return set()
    terms = tuple(term.casefold() for term in launcher["matchTerms"])
    return {
        fields[0]
        for line in completed.stdout.splitlines()
        if len(fields := line.split(maxsplit=1)) == 2
        and any(term in fields[1].casefold() for term in terms)
    }


def bounded_text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\x00", "").split())[:limit]


def bounded_shortcuts(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [shortcut[:64] for shortcut in value.split()[:16] if shortcut]


def safe(call, fallback=None):
    try:
        return call()
    except Exception:
        return fallback


def state_names(accessible) -> list[str]:
    states = safe(lambda: accessible.getState().getStates(), []) or []
    names = []
    for state in states:
        name = bounded_text(safe(lambda state=state: pyatspi.stateToString(state), ""), 80)
        if name:
            names.append(name.replace("ATSPI_STATE_", "").lower())
    return sorted(set(names))


def normalized_actions(
    accessible,
    states: list[str],
    role: str,
    allow_pointer_invoke: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    actions: list[str] = []
    interfaces: dict[str, Any] = {}
    action_iface = safe(accessible.queryAction)
    action_names = [
        bounded_text(safe(lambda index=index: action_iface.getName(index), ""), 80).lower()
        for index in range(int(safe(lambda: action_iface.nActions, 0) or 0))
    ] if action_iface is not None else []
    if any(name in ACCESSIBILITY_ACTIVATION_ACTIONS for name in action_names):
        actions.append("invoke")
        interfaces["invoke"] = action_iface
    editable_iface = safe(accessible.queryEditableText)
    if editable_iface is not None and "editable" in states:
        actions.append("set_text")
        interfaces["set_text"] = editable_iface
    component_iface = safe(accessible.queryComponent)
    if (
        "invoke" not in actions
        and (role in ACCESSIBILITY_POINTER_ROLES or allow_pointer_invoke)
        and component_iface is not None
        and "showing" in states
        and "visible" in states
    ):
        extents = safe(lambda: component_iface.getExtents(pyatspi.DESKTOP_COORDS))
        if extents is not None and int(extents.width) > 0 and int(extents.height) > 0:
            actions.append("invoke")
            interfaces["invoke_pointer"] = component_iface
    if component_iface is not None and ("focusable" in states or "focused" in states):
        actions.append("focus")
        interfaces["focus"] = component_iface
    return actions, interfaces


def node_value(accessible, role: str) -> str | None:
    if "password" in role:
        return None
    text_iface = safe(accessible.queryText)
    if text_iface is not None:
        text = bounded_text(safe(lambda: text_iface.getText(0, -1), ""))
        if text:
            return text
    value_iface = safe(accessible.queryValue)
    if value_iface is not None:
        value = safe(lambda: value_iface.currentValue)
        if value is not None:
            return bounded_text(value)
    return None


def node_bounds(accessible) -> dict[str, int] | None:
    component = safe(accessible.queryComponent)
    if component is None:
        return None
    extents = safe(lambda: component.getExtents(pyatspi.DESKTOP_COORDS))
    if extents is None:
        return None
    return {
        "x": int(extents.x),
        "y": int(extents.y),
        "width": max(0, int(extents.width)),
        "height": max(0, int(extents.height)),
    }


WECHAT_CHAT_LIST_NAMES = {"chats", "chat list", "聊天"}
WECHAT_MESSAGE_LIST_NAMES = {"messages", "message list", "chat history", "消息"}
WECHAT_COMPOSER_NAMES = {"message", "send a message", "type a message", "消息"}
WECHAT_SEND_NAMES = {"send", "send(s)", "发送"}
WECHAT_UNREAD_TERMS = ("unread", "new message", "未读")


def with_semantic_state(node: dict[str, Any], state: str) -> None:
    node["states"] = sorted({*node.get("states", []), state})


def wechat_semantic_kind(node: dict[str, Any]) -> str | None:
    states = set(node.get("states", []))
    for kind in ("conversation", "composer", "send_control", "message"):
        if kind in states:
            return kind
    return None


def enrich_wechat_semantics(
    nodes: list[dict[str, Any]],
) -> None:
    by_ref = {
        node["ref"]: node
        for node in nodes
        if node.get("appId") == "wechat" and isinstance(node.get("ref"), str)
    }
    children: dict[str, list[dict[str, Any]]] = {}
    for node in by_ref.values():
        parent_ref = node.get("parentRef")
        if isinstance(parent_ref, str):
            children.setdefault(parent_ref, []).append(node)

    def descendants(root_ref: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        pending = list(children.get(root_ref, []))
        while pending and len(found) < MAX_STATE_NODES:
            child = pending.pop()
            found.append(child)
            pending.extend(children.get(str(child.get("ref") or ""), []))
        return found

    chat_lists = {
        node["ref"]
        for node in by_ref.values()
        if node.get("role") == "list"
        and bounded_text(node.get("name"), 80).casefold() in WECHAT_CHAT_LIST_NAMES
    }
    message_lists = {
        node["ref"]
        for node in by_ref.values()
        if node.get("role") == "list"
        and bounded_text(node.get("name"), 80).casefold() in WECHAT_MESSAGE_LIST_NAMES
    }
    for list_ref in chat_lists:
        with_semantic_state(by_ref[list_ref], "conversation_list")
        for conversation in children.get(list_ref, []):
            if conversation.get("role") != "list item":
                continue
            with_semantic_state(conversation, "conversation")
            conversation["description"] = "WeChat conversation"
            text = " ".join(
                bounded_text(candidate.get(field), 160).casefold()
                for candidate in (conversation, *descendants(conversation["ref"]))
                for field in ("name", "description")
            )
            if any(term in text for term in WECHAT_UNREAD_TERMS):
                with_semantic_state(conversation, "unread")

    for list_ref in message_lists:
        with_semantic_state(by_ref[list_ref], "message_list")
        for message in descendants(list_ref):
            if message.get("role") in {"label", "text", "list item"} and not message.get("actions"):
                with_semantic_state(message, "message")

    for node in by_ref.values():
        name = bounded_text(node.get("name"), 80).casefold()
        actions = set(node.get("actions", []))
        if "set_text" in actions and name in WECHAT_COMPOSER_NAMES:
            with_semantic_state(node, "composer")
            node["description"] = "WeChat message composer"
        elif "invoke" in actions and name in WECHAT_SEND_NAMES:
            with_semantic_state(node, "send_control")
            node["description"] = "Send the current WeChat message"


def ax_value(node: dict[str, Any], field: str) -> Any:
    value = node.get(field)
    return value.get("value") if isinstance(value, dict) else None


def ax_state_is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.casefold() == "true")


def normalized_ax_role(value: Any) -> str:
    compact = bounded_text(value, 100).replace("_", " ").lower()
    return {
        "rootwebarea": "document web",
        "statictext": "static",
        "inlinetextbox": "static",
        "textfield": "entry",
        "textbox": "entry",
        "searchbox": "entry",
    }.get(compact.replace(" ", ""), compact or "unknown")


def cdp_node_actions(
    role: str,
    backend_node_id: int | None,
    disabled: bool = False,
    editable: bool = False,
    pointer_interactive: bool = False,
) -> list[str]:
    if backend_node_id is None or disabled:
        return []
    actions = []
    role_invokable = role in {
        "button",
        "link",
        "checkbox",
        "radio",
        "switch",
        "menu item",
        "tab",
        "canvas",
    }
    if role_invokable:
        actions.append("invoke")
    elif pointer_interactive:
        actions.append("invoke")
    if editable or role in {"entry", "combobox", "listbox", "textarea"}:
        actions.append("set_text")
    if role == "canvas":
        actions.extend(("press_key", "input_sequence"))
    if role_invokable or editable or role in {"slider", "spin button", "listbox", "entry", "combobox", "textarea"}:
        actions.insert(0, "focus")
    return actions


def cdp_dom_interaction_hint(cdp: CdpConnection, backend_node_id: int) -> dict[str, Any]:
    object_id = cdp_resolve_object(cdp, backend_node_id)
    result = cdp.call(
        "Runtime.callFunctionOn",
        {
            "objectId": object_id,
            "functionDeclaration": """function(){const clean=value=>String(value||'').replace(/\\s+/g,' ').trim();const style=getComputedStyle(this);const parentStyle=this.parentElement?getComputedStyle(this.parentElement):null;const rect=this.getBoundingClientRect();const visible=style.visibility!=='hidden'&&style.display!=='none'&&rect.width>0&&rect.height>0;const pointerBoundary=visible&&style.cursor==='pointer'&&parentStyle?.cursor!=='pointer';const nested=this.querySelector?.('[aria-label],[title],img[alt]');const name=clean(this.getAttribute?.('aria-label')||this.getAttribute?.('title')||this.innerText||nested?.getAttribute?.('aria-label')||nested?.getAttribute?.('title')||nested?.getAttribute?.('alt'));const canvasVisual=this instanceof HTMLCanvasElement?(()=>{try{const data=this.toDataURL('image/webp',0.1),step=Math.max(1,Math.floor(data.length/2048));let hash=2166136261;for(let i=0;i<data.length;i+=step)hash=Math.imul(hash^data.charCodeAt(i),16777619);return (hash>>>0).toString(16)}catch{return ''}})():'';const visual=[style.backgroundColor,style.backgroundImage,style.color,style.opacity,style.visibility,style.display,style.transform,style.filter,style.boxShadow,Math.round(rect.x),Math.round(rect.y),Math.round(rect.width),Math.round(rect.height),canvasVisual].join('|');const history=window[Symbol.for('dev.wiii.semantic.visual-history')]?.tracked?.get(this);return {visible,pointerBoundary,name:name.slice(0,160),visual,visualRevision:Number(history?.revision||0)}}""",
            "returnByValue": True,
        },
    )
    value = result.get("result", {}).get("value")
    return value if isinstance(value, dict) else {}


def cdp_dom_visual_targets(cdp: CdpConnection) -> list[tuple[int, dict[str, Any]]]:
    cdp.call("DOM.enable")
    cdp.call("DOM.getDocument", {"depth": 0})
    evaluated = cdp.call(
        "Runtime.evaluate",
        {
            "expression": """(()=>{const blocked='a,button,input,select,textarea,[role=button],[role=link],[role=checkbox],[role=radio]',all=Array.from(document.querySelectorAll('*')),group=e=>{const r=e.getBoundingClientRect();return [e.tagName,String(e.className||''),Math.round(r.width),Math.round(r.height)].join('|')},counts=new Map();for(const e of all){const r=e.getBoundingClientRect(),text=(e.innerText||'').trim();if(!text&&r.width>=12&&r.height>=12&&r.width<=160&&r.height<=160)counts.set(group(e),(counts.get(group(e))||0)+1)}const signature=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return [s.backgroundColor,s.backgroundImage,s.color,s.opacity,s.visibility,s.display,s.transform,s.filter,s.boxShadow,Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)].join('|')};const raw=all.filter(e=>{if(e.closest(blocked))return false;const s=getComputedStyle(e),parent=e.parentElement?getComputedStyle(e.parentElement):null,r=e.getBoundingClientRect(),text=(e.innerText||'').trim(),visible=s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>0&&r.width>=16&&r.height>=16,pointerBoundary=visible&&s.cursor==='pointer'&&parent?.cursor!=='pointer',pointerVisual=visible&&s.cursor==='pointer'&&!text&&r.width<=320&&r.height<=320,repeated=visible&&!text&&r.width<=160&&r.height<=160&&Math.max(r.width,r.height)/Math.min(r.width,r.height)<=1.5&&(counts.get(group(e))||0)>=8&&(s.backgroundImage!=='none'||s.backgroundColor!=='rgba(0, 0, 0, 0)'||s.borderStyle!=='none');return pointerBoundary||pointerVisual||repeated});const selected=[];for(const e of raw){const r=e.getBoundingClientRect(),cx=Math.round(r.x+r.width/2),cy=Math.round(r.y+r.height/2),area=r.width*r.height;const match=selected.findIndex(item=>Math.abs(item.cx-cx)<=2&&Math.abs(item.cy-cy)<=2);if(match<0)selected.push({e,cx,cy,area});else if(area<selected[match].area)selected[match]={e,cx,cy,area}}const elements=selected.slice(0,64).map(item=>item.e),key=Symbol.for('dev.wiii.semantic.visual-history');let state=window[key];if(!state){state={tracked:new Map(),running:false};window[key]=state}for(const e of elements){if(!state.tracked.has(e))state.tracked.set(e,{signature:signature(e),revision:0})}if(!state.running){state.running=true;const tick=()=>{for(const [e,item] of state.tracked){if(!e.isConnected){state.tracked.delete(e);continue}const next=signature(e);if(next!==item.signature){item.signature=next;item.revision++}}requestAnimationFrame(tick)};requestAnimationFrame(tick)}return elements})()""",
            "returnByValue": False,
        },
    ).get("result", {})
    object_id = evaluated.get("objectId")
    if not isinstance(object_id, str):
        return []
    properties = cdp.call(
        "Runtime.getProperties",
        {"objectId": object_id, "ownProperties": True},
    ).get("result", [])
    targets: list[tuple[int, dict[str, Any]]] = []
    for item in properties:
        if not str(item.get("name") or "").isdigit():
            continue
        candidate_id = item.get("value", {}).get("objectId")
        if not isinstance(candidate_id, str):
            continue
        node_id = cdp.call("DOM.requestNode", {"objectId": candidate_id}).get("nodeId")
        if not isinstance(node_id, int) or node_id <= 0:
            continue
        described = cdp.call("DOM.describeNode", {"nodeId": node_id, "depth": 0})
        backend_node_id = described.get("node", {}).get("backendNodeId")
        if not isinstance(backend_node_id, int):
            continue
        hint = cdp_dom_interaction_hint(cdp, backend_node_id)
        if hint.get("visible") is True:
            targets.append((backend_node_id, hint))
        if len(targets) >= MAX_DOM_VISUAL_TARGETS:
            break
    try:
        cdp.call("Runtime.releaseObject", {"objectId": object_id})
    except Exception:
        pass
    return targets


def cdp_dom_attributes(cdp: CdpConnection, backend_node_id: int) -> dict[str, str]:
    described = cdp.call(
        "DOM.describeNode",
        {"backendNodeId": backend_node_id, "depth": 0, "pierce": True},
    )
    values = described.get("node", {}).get("attributes", [])
    if not isinstance(values, list):
        return {}
    allowed = {
        "type",
        "autocomplete",
        "contenteditable",
        "name",
        "id",
        "aria-label",
        "aria-labelledby",
        "placeholder",
        "title",
        "aria-keyshortcuts",
    }
    return {
        str(values[index]).casefold(): bounded_text(values[index + 1], 160)
        for index in range(0, len(values) - 1, 2)
        if str(values[index]).casefold() in allowed
    }


def cdp_dom_label(cdp: CdpConnection, backend_node_id: int) -> str:
    object_id = cdp_resolve_object(cdp, backend_node_id)
    result = cdp.call(
        "Runtime.callFunctionOn",
        {
            "objectId": object_id,
            "functionDeclaration": """function(){const clean=value=>String(value||'').replace(/\\s+/g,' ').trim();const labels=Array.from(this.labels||[]).map(node=>clean(node.innerText||node.textContent)).filter(Boolean);if(labels.length)return labels.join(' ');const labelledBy=clean(this.getAttribute?.('aria-labelledby'));if(labelledBy){const text=labelledBy.split(/\\s+/).map(id=>document.getElementById(id)).filter(Boolean).map(node=>clean(node.innerText||node.textContent)).filter(Boolean).join(' ');if(text)return text}const parent=this.closest?.('label');if(parent){const text=clean(parent.innerText||parent.textContent);if(text)return text}const type=clean(this.getAttribute?.('type')).toLowerCase();const directions=['checkbox','radio'].includes(type)?['nextSibling','previousSibling']:['previousSibling','nextSibling'];for(const direction of directions){let sibling=this[direction];for(let step=0;sibling&&step<4;step++,sibling=sibling[direction]){const text=clean(sibling.innerText||sibling.textContent);if(text)return text}}return ''}""",
            "returnByValue": True,
        },
    )
    return bounded_text(result.get("result", {}).get("value"), 160)


def semantic_control_name(ax_name: str, attributes: dict[str, str], dom_label: str) -> str:
    return next(
        (
            bounded_text(candidate, 160)
            for candidate in (
                ax_name,
                dom_label,
                attributes.get("aria-label"),
                attributes.get("placeholder"),
                attributes.get("title"),
                attributes.get("name"),
                attributes.get("id"),
            )
            if bounded_text(candidate, 160)
        ),
        "",
    )


def url_origin(value: Any) -> tuple[str, str, int | None] | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return parsed.scheme, parsed.hostname.casefold(), parsed.port


def flatten_frame_tree(
    frame_tree: dict[str, Any],
    allowed_origin: tuple[str, str, int | None] | None = None,
) -> list[tuple[str, str | None]]:
    frames: list[tuple[str, str | None]] = []
    pending: list[tuple[dict[str, Any], str | None]] = [(frame_tree, None)]
    while pending and len(frames) < MAX_BROWSER_FRAMES:
        item, parent_frame_id = pending.pop()
        frame_id = item.get("frame", {}).get("id")
        if not isinstance(frame_id, str) or not frame_id:
            continue
        frame_url = item.get("frame", {}).get("url")
        inherited_origin = not frame_url or str(frame_url).startswith(("about:", "data:"))
        if parent_frame_id is not None and allowed_origin is not None and not inherited_origin:
            if url_origin(frame_url) != allowed_origin:
                continue
        frames.append((frame_id, parent_frame_id))
        children = item.get("childFrames", [])
        if isinstance(children, list):
            pending.extend((child, frame_id) for child in reversed(children) if isinstance(child, dict))
    return frames


def nearest_visible_parent_ref(
    target_id: str,
    frame_id: str,
    parent_node_id: Any,
    refs: dict[tuple[str, str, str], str],
    raw_nodes: dict[tuple[str, str, str], dict[str, Any]],
) -> str | None:
    current = str(parent_node_id) if parent_node_id is not None else None
    for _ in range(64):
        if current is None:
            return None
        ref = refs.get((target_id, frame_id, current))
        if ref is not None:
            return ref
        raw = raw_nodes.get((target_id, frame_id, current))
        if raw is None:
            return None
        parent = raw.get("parentId")
        current = str(parent) if parent is not None else None
    return None


def is_sensitive_field(name: str, properties: dict[str, Any], attributes: dict[str, str]) -> bool:
    if properties.get("protected") is True or attributes.get("type", "").casefold() == "password":
        return True
    autocomplete = attributes.get("autocomplete", "").casefold()
    if autocomplete in {"current-password", "new-password", "one-time-code", "cc-number", "cc-csc"}:
        return True
    identity = " ".join((name, *attributes.values())).casefold().replace("_", " ").replace("-", " ")
    return any(term in identity for term in SENSITIVE_FIELD_TERMS)


def is_sensitive_accessibility_field(role: str, name: str, description: str | None) -> bool:
    return is_sensitive_field(
        " ".join(part for part in (role, name, description or "") if part),
        {"protected": "password" in role},
        {},
    )


def browser_application_kind(page: dict[str, Any]) -> str | None:
    try:
        hostname = (urlsplit(str(page.get("url") or "")).hostname or "").casefold()
    except ValueError:
        return None
    return "gmail" if hostname == "mail.google.com" else None


def gmail_message_summary(node: dict[str, Any]) -> bool:
    name = str(node.get("name") or "").strip()
    role = str(node.get("role") or "")
    if len(name) < 32:
        return False
    if role == "checkbox":
        return name.count(",") >= 3
    return role == "link" and " - " in name


def gmail_stable_ref(node: dict[str, Any]) -> str | None:
    if not gmail_message_summary(node):
        return None
    identity = json.dumps(
        {
            "role": str(node.get("role") or ""),
            "name": " ".join(str(node.get("name") or "").split()),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"gmail-{node['role']}-{digest}"


def is_browser_target_ref(target_ref: str) -> bool:
    return target_ref.startswith(("web-", "gmail-"))


def apply_gmail_adapter(
    nodes: list[dict[str, Any]],
    targets: dict[str, tuple[Any, dict[str, Any]]],
) -> dict[str, tuple[Any, dict[str, Any]]]:
    gmail_adapter = {
        **GMAIL_ADAPTER,
        "capabilities": list(GMAIL_ADAPTER["capabilities"]),
    }
    remapped_refs: dict[str, str] = {}
    claimed_refs: set[str] = set()
    for node in nodes:
        node["adapter"] = gmail_adapter
        if "app_adapter" not in node["sources"]:
            node["sources"].append("app_adapter")
        stable_ref = gmail_stable_ref(node)
        if stable_ref is None or stable_ref in claimed_refs:
            continue
        claimed_refs.add(stable_ref)
        remapped_refs[node["ref"]] = stable_ref
        node["ref"] = stable_ref
        if "stable_app_identity" not in node["sources"]:
            node["sources"].append("stable_app_identity")
    for node in nodes:
        parent_ref = node.get("parentRef")
        if parent_ref in remapped_refs:
            node["parentRef"] = remapped_refs[parent_ref]
    remapped_targets: dict[str, tuple[Any, dict[str, Any]]] = {}
    for target_ref, target in targets.items():
        remapped_targets[remapped_refs.get(target_ref, target_ref)] = target
    return remapped_targets


def web_node_priority(node: dict[str, Any], application_kind: str | None = None) -> tuple[int, int]:
    if node["role"] == "document web":
        return (0, 0)
    if application_kind == "gmail" and gmail_message_summary(node):
        return (1, 0 if node["role"] == "checkbox" else 1)
    if "focused" in node["states"]:
        return (2, 0)
    if application_kind == "gmail" and node["actions"]:
        name = str(node.get("name") or "").casefold()
        if node["role"] in {"entry", "textbox"} and any(
            term in name for term in ("search", "tìm kiếm")
        ):
            return (3, 0)
        if node["role"] == "button" and name in {"compose", "soạn thư"}:
            return (3, 1)
    if node["actions"]:
        return (4, 0)
    if node["role"] == "heading":
        return (5, 0)
    return (6, 0)


def cdp_semantic_nodes() -> tuple[list[dict[str, Any]], dict[str, tuple[Any, dict[str, Any]]]]:
    page = active_browser_page()
    if page is None:
        return [], {}
    application_kind = browser_application_kind(page)
    runtime_enrichment = realtime_clock_state(page) is None
    page_id = str(page["id"])
    page_origin = url_origin(page.get("url"))
    context_targets = [
        page,
        *(
            target
            for target in browser_frame_targets(page_id)
            if page_origin is None or url_origin(target.get("url")) == page_origin
        ),
    ]
    target_by_id = {
        str(target["id"]): target
        for target in context_targets
        if isinstance(target.get("id"), str)
    }
    raw_records: list[tuple[str, str, str | None, dict[str, Any]]] = []
    frame_owners: dict[tuple[str, str], tuple[str, int]] = {}
    field_attributes: dict[tuple[str, str, int], dict[str, str]] = {}
    field_labels: dict[tuple[str, str, int], str] = {}
    interaction_hints: dict[tuple[str, str, int], dict[str, Any]] = {}
    visual_targets: list[tuple[str, int, dict[str, Any]]] = []
    attribute_lookups = 0
    label_lookups = 0
    interaction_lookups = 0
    for context in context_targets:
        target_id = str(context.get("id") or "")
        if not target_id:
            continue
        try:
            with CdpConnection(context) as cdp:
                cdp.call("Accessibility.enable")
                frame_tree = cdp.call("Page.getFrameTree").get("frameTree", {})
                frames = flatten_frame_tree(frame_tree, page_origin) if isinstance(frame_tree, dict) else []
                if not frames:
                    frames = [(target_id, None)]
                context_records: list[tuple[str, str, str | None, dict[str, Any]]] = []
                for frame_id, parent_frame_id in frames:
                    try:
                        frame_nodes = cdp.call(
                            "Accessibility.getFullAXTree",
                            {"frameId": frame_id},
                        ).get("nodes", [])
                        context_records.extend(
                            (target_id, frame_id, parent_frame_id, raw)
                            for raw in frame_nodes
                            if isinstance(raw, dict)
                        )
                        if parent_frame_id is not None:
                            owner = cdp.call("DOM.getFrameOwner", {"frameId": frame_id})
                            backend_node_id = owner.get("backendNodeId")
                            if isinstance(backend_node_id, int):
                                frame_owners[(target_id, frame_id)] = (target_id, backend_node_id)
                    except Exception:
                        continue
                raw_records.extend(context_records)
                for _target_id, frame_id, _parent_frame_id, raw in context_records:
                    backend_node_id = raw.get("backendDOMNodeId")
                    if backend_node_id is None:
                        continue
                    role = normalized_ax_role(ax_value(raw, "role"))
                    raw_name = bounded_text(ax_value(raw, "name"))
                    is_editable_candidate = role == "generic" and bool(raw_name)
                    key = (target_id, frame_id, int(backend_node_id))
                    if (
                        (role in FORM_CONTROL_ROLES or is_editable_candidate)
                        and attribute_lookups < MAX_DOM_ATTRIBUTE_LOOKUPS
                    ):
                        attribute_lookups += 1
                        try:
                            field_attributes[key] = cdp_dom_attributes(cdp, int(backend_node_id))
                        except Exception:
                            field_attributes[key] = {}
                        if (
                            runtime_enrichment
                            and not raw_name
                            and label_lookups < MAX_DOM_LABEL_LOOKUPS
                        ):
                            label_lookups += 1
                            try:
                                field_labels[key] = cdp_dom_label(cdp, int(backend_node_id))
                            except Exception:
                                field_labels[key] = ""
                    if (
                        runtime_enrichment
                        and target_id == page_id
                        and role == "canvas"
                        and interaction_lookups < MAX_DOM_INTERACTION_LOOKUPS
                    ):
                        interaction_lookups += 1
                        try:
                            interaction_hints[key] = cdp_dom_interaction_hint(cdp, int(backend_node_id))
                        except Exception:
                            interaction_hints[key] = {}
                if runtime_enrichment and target_id == page_id:
                    try:
                        visual_targets.extend(
                            (target_id, backend_node_id, hint)
                            for backend_node_id, hint in cdp_dom_visual_targets(cdp)
                        )
                    except Exception:
                        pass
                if context.get("type") == "iframe" and frames:
                    parent_target_id = context.get("parentId")
                    parent_target = target_by_id.get(str(parent_target_id))
                    if parent_target is not None:
                        try:
                            with CdpConnection(parent_target) as parent_cdp:
                                owner = parent_cdp.call("DOM.getFrameOwner", {"frameId": target_id})
                            backend_node_id = owner.get("backendNodeId")
                            if isinstance(backend_node_id, int):
                                frame_owners[(target_id, frames[0][0])] = (
                                    str(parent_target_id),
                                    backend_node_id,
                                )
                        except Exception:
                            pass
        except Exception:
            continue
    visible = [
        (target_id, frame_id, parent_frame_id, node)
        for target_id, frame_id, parent_frame_id, node in raw_records
        if not node.get("ignored")
        and bounded_text(ax_value(node, "role"), 100).replace(" ", "").casefold() != "inlinetextbox"
    ]
    refs: dict[tuple[str, str, str], str] = {}
    backend_refs: dict[tuple[str, int], str] = {}
    raw_lookup = {
        (target_id, frame_id, str(raw.get("nodeId"))): raw
        for target_id, frame_id, _parent_frame_id, raw in raw_records
    }
    for target_id, frame_id, _parent_frame_id, raw in visible:
        ref = web_node_ref(
            target_id,
            frame_id,
            raw.get("nodeId"),
            raw.get("backendDOMNodeId"),
        )
        refs[(target_id, frame_id, str(raw.get("nodeId")))] = ref
        backend_node_id = raw.get("backendDOMNodeId")
        if isinstance(backend_node_id, int):
            backend_refs[(target_id, backend_node_id)] = ref
    nodes: list[dict[str, Any]] = []
    targets: dict[str, tuple[Any, dict[str, Any]]] = {}
    for target_id, frame_id, parent_frame_id, raw in visible:
        node_id = str(raw.get("nodeId"))
        ref = refs[(target_id, frame_id, node_id)]
        role = normalized_ax_role(ax_value(raw, "role"))
        backend_node_id = raw.get("backendDOMNodeId")
        backend_key = (
            (target_id, frame_id, int(backend_node_id))
            if backend_node_id is not None
            else None
        )
        properties = {
            str(item.get("name")): ax_value(item, "value")
            for item in raw.get("properties", [])
            if isinstance(item, dict)
        }
        disabled = ax_state_is_true(properties.get("disabled"))
        states = ["disabled"] if disabled else ["enabled"]
        for state in ("focused", "selected", "checked", "expanded", "required", "readonly"):
            if ax_state_is_true(properties.get(state)):
                states.append(state)
        attributes = field_attributes.get(backend_key, {}) if backend_key is not None else {}
        interaction = interaction_hints.get(backend_key, {}) if backend_key is not None else {}
        pointer_interactive = interaction.get("pointerBoundary") is True
        visibly_unavailable = interaction and interaction.get("visible") is False
        content_editable = (
            "contenteditable" in attributes
            and attributes["contenteditable"].casefold() in {"", "true", "plaintext-only"}
        )
        actions = cdp_node_actions(
            role,
            backend_node_id,
            disabled or visibly_unavailable,
            content_editable,
            pointer_interactive,
        )
        protected = is_sensitive_field(
            bounded_text(ax_value(raw, "name")),
            properties,
            attributes,
        )
        if protected:
            actions = [action for action in actions if action != "set_text"]
        raw_name = bounded_text(ax_value(raw, "name"))
        name = semantic_control_name(
            raw_name,
            attributes,
            field_labels.get(backend_key, "") if backend_key is not None else "",
        ) if role in FORM_CONTROL_ROLES else raw_name
        if actions and not name:
            name = bounded_text(interaction.get("name"), 160) or f"Unlabeled {role}"
        visual = bounded_text(interaction.get("visual"), 500)
        if visual and (actions or role == "canvas"):
            states.append("visual:" + hashlib.sha256(visual.encode("utf-8")).hexdigest()[:12])
        visual_revision = interaction.get("visualRevision")
        if actions and isinstance(visual_revision, int) and visual_revision > 0:
            states.append(f"visual_revision:{visual_revision}")
        sources = ["browser", "accessibility"]
        if backend_node_id is not None:
            sources.extend(("dom", "layout"))
        if visual:
            sources.append("visual_fingerprint")
        if role == "canvas":
            sources.append("canvas_fingerprint")
        shortcuts = bounded_shortcuts(
            properties.get("keyshortcuts") or attributes.get("aria-keyshortcuts")
        )
        parent_ref = nearest_visible_parent_ref(
            target_id,
            frame_id,
            raw.get("parentId"),
            refs,
            raw_lookup,
        )
        if parent_ref is None:
            owner = frame_owners.get((target_id, frame_id))
            if owner is not None:
                parent_ref = backend_refs.get(owner)
        node = {
            "ref": ref,
            "parentRef": parent_ref or "app:browser",
            "appId": "browser",
            "role": role,
            "name": name,
            "description": bounded_text(ax_value(raw, "description")) or None,
            "value": None if protected else bounded_text(ax_value(raw, "value")) or None,
            "states": states,
            "actions": actions,
            "bounds": None,
            "sources": sources,
            "shortcuts": shortcuts,
        }
        nodes.append(node)
        if actions or role == "canvas":
            targets[ref] = (
                None,
                {
                    "node": node,
                    "interfaces": {},
                    "cdp": {
                        "targetId": target_id,
                        "frameId": frame_id,
                        "backendDOMNodeId": backend_node_id,
                    },
                },
            )
    for target_id, backend_node_id, interaction in visual_targets:
        existing_ref = backend_refs.get((target_id, backend_node_id))
        if existing_ref is not None and existing_ref in targets:
            continue
        visual = bounded_text(interaction.get("visual"), 500)
        ref = web_node_ref(target_id, target_id, None, backend_node_id)
        states = ["enabled"]
        if visual:
            states.append("visual:" + hashlib.sha256(visual.encode("utf-8")).hexdigest()[:12])
        visual_revision = interaction.get("visualRevision")
        if isinstance(visual_revision, int) and visual_revision > 0:
            states.append(f"visual_revision:{visual_revision}")
        node = {
            "ref": ref,
            "parentRef": "app:browser",
            "appId": "browser",
            "role": "visual target",
            "name": bounded_text(interaction.get("name"), 160) or "Visual target",
            "description": "A visible pointer target without an accessibility control.",
            "value": None,
            "states": states,
            "actions": ["invoke"],
            "bounds": None,
            "sources": ["browser", "dom", "layout", "temporal_visual"],
        }
        nodes.append(node)
        targets[ref] = (
            None,
            {
                "node": node,
                "interfaces": {},
                "cdp": {
                    "targetId": target_id,
                    "frameId": target_id,
                    "backendDOMNodeId": backend_node_id,
                },
            },
        )
    if application_kind == "gmail":
        targets = apply_gmail_adapter(nodes, targets)
    nodes.sort(key=lambda node: web_node_priority(node, application_kind))
    return nodes, targets


def browser_snapshot(
    environment_id: str,
    output_limit: int,
    scope_ref: str | None = None,
    continuation: str | None = None,
    since_state_version: str | None = None,
    known_node_versions: Any = None,
    retained_target_ref: str | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]]:
    web_nodes, web_targets = cdp_semantic_nodes()
    browser_adapter = adapter_payload(APP_LAUNCHERS_BY_REF.get("app:browser"))
    if browser_adapter is not None:
        for node in web_nodes:
            node.setdefault("adapter", browser_adapter)
    nodes = [*workstation_nodes(), *web_nodes]
    visible_nodes, projection = project_scene(
        environment_id,
        nodes,
        output_limit,
        "browser",
        scope_ref=scope_ref,
        continuation=continuation,
        since_state_version=since_state_version,
        known_node_versions=known_node_versions,
    )
    visible_refs = {node["ref"] for node in visible_nodes}
    return (
        {
            "protocolVersion": PROTOCOL_VERSION,
            "environmentId": environment_id,
            "stateVersion": projection["stateVersion"],
            "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "platform": "linux_atspi",
            "screen": {"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
            "activeWindowRef": next(
                (
                    node["ref"]
                    for node in visible_nodes
                    if "focused" in node["states"] and node["role"] == "document web"
                ),
                None,
            ),
            "frame": ai_frame("browser", projection["scopedNodes"]),
            "nodes": visible_nodes,
            "truncated": projection["truncated"],
            "scopeRef": projection["scopeRef"],
            "projection": projection["projection"],
            "nextContinuation": projection["nextContinuation"],
            "deltaFromStateVersion": projection["deltaFromStateVersion"],
            "removedRefs": projection["removedRefs"],
        },
        {
            ref: target
            for ref, target in web_targets.items()
            if ref in visible_refs or ref == retained_target_ref
        },
    )


def fast_browser_canvas_target(target_ref: str) -> tuple[Any, dict[str, Any]] | None:
    page = active_browser_page()
    if page is None:
        return None
    page_id = str(page.get("id") or "")
    if not page_id:
        return None
    page_origin = url_origin(page.get("url"))
    contexts = [
        page,
        *(
            target
            for target in browser_frame_targets(page_id)
            if page_origin is None or url_origin(target.get("url")) == page_origin
        ),
    ]
    for context in contexts:
        target_id = str(context.get("id") or "")
        if not target_id:
            continue
        try:
            with CdpConnection(context) as cdp:
                cdp.call("Accessibility.enable")
                frame_tree = cdp.call("Page.getFrameTree").get("frameTree", {})
                frames = flatten_frame_tree(frame_tree, page_origin) if isinstance(frame_tree, dict) else []
                if not frames:
                    frames = [(target_id, None)]
                for frame_id, _parent_frame_id in frames:
                    raw_nodes = cdp.call(
                        "Accessibility.getFullAXTree",
                        {"frameId": frame_id},
                    ).get("nodes", [])
                    for raw in raw_nodes:
                        if not isinstance(raw, dict) or raw.get("ignored"):
                            continue
                        if normalized_ax_role(ax_value(raw, "role")) != "canvas":
                            continue
                        backend_node_id = raw.get("backendDOMNodeId")
                        if not isinstance(backend_node_id, int):
                            continue
                        node_ref = web_node_ref(
                            target_id,
                            frame_id,
                            raw.get("nodeId"),
                            backend_node_id,
                        )
                        if node_ref != target_ref:
                            continue
                        properties = {
                            str(item.get("name")): ax_value(item, "value")
                            for item in raw.get("properties", [])
                            if isinstance(item, dict)
                        }
                        disabled = ax_state_is_true(properties.get("disabled"))
                        states = ["disabled" if disabled else "enabled"]
                        if ax_state_is_true(properties.get("focused")):
                            states.append("focused")
                        name = bounded_text(ax_value(raw, "name"), 160) or "Unlabeled canvas"
                        node = {
                            "ref": node_ref,
                            "parentRef": "app:browser",
                            "appId": "browser",
                            "role": "canvas",
                            "name": name,
                            "description": bounded_text(ax_value(raw, "description")) or None,
                            "value": None,
                            "states": states,
                            "actions": cdp_node_actions("canvas", backend_node_id, disabled=disabled),
                            "bounds": None,
                            "sources": ["browser", "accessibility", "dom"],
                            "adapter": adapter_payload(APP_LAUNCHERS_BY_REF.get("app:browser")),
                        }
                        return (
                            None,
                            {
                                "node": node,
                                "interfaces": {},
                                "cdp": {
                                    "targetId": target_id,
                                    "frameId": frame_id,
                                    "backendDOMNodeId": backend_node_id,
                                },
                            },
                        )
        except Exception:
            continue
    return None


def cdp_target_page(target_id: str) -> dict[str, Any]:
    return browser_page_target(target_id)


def capture_visual_patch(
    visual_ref: str,
    targets: dict[str, tuple[Any, dict[str, Any]]],
) -> dict[str, Any]:
    target = targets.get(visual_ref)
    if target is None:
        raise ValueError("visualRef must identify a visible semantic target.")
    facts = target[1]
    node = facts.get("node", {})
    if node.get("role") not in {"canvas", "visual target"} or "cdp" not in facts:
        raise ValueError("visualRef may capture only a canvas or visual target.")
    cdp_facts = facts["cdp"]
    page = cdp_target_page(str(cdp_facts["targetId"]))
    backend_node_id = int(cdp_facts["backendDOMNodeId"])
    with CdpConnection(page) as cdp:
        cdp.call("Page.enable")
        model = cdp.call("DOM.getBoxModel", {"backendNodeId": backend_node_id}).get("model", {})
        quad = model.get("border") or model.get("content")
        if not isinstance(quad, list) or len(quad) != 8:
            raise ValueError("visualRef has no visible capture surface.")
        left = max(0.0, min(float(quad[index]) for index in (0, 2, 4, 6)))
        top = max(0.0, min(float(quad[index]) for index in (1, 3, 5, 7)))
        right = min(float(SCREEN_WIDTH), max(float(quad[index]) for index in (0, 2, 4, 6)))
        bottom = min(float(SCREEN_HEIGHT), max(float(quad[index]) for index in (1, 3, 5, 7)))
        width = right - left
        height = bottom - top
        if width < 1 or height < 1:
            raise ValueError("visualRef is outside the visible browser viewport.")
        scale = min(1.0, MAX_VISUAL_PATCH_WIDTH / width, MAX_VISUAL_PATCH_HEIGHT / height)
        capture = {
            "fromSurface": True,
            "captureBeyondViewport": False,
            "clip": {"x": left, "y": top, "width": width, "height": height, "scale": scale},
        }
        encoded, raw = capture_screenshot(cdp, {"format": "png", **capture})
        mime_type = "image/png"
        if len(raw) > MAX_VISUAL_PATCH_BYTES:
            encoded, raw = capture_screenshot(
                cdp,
                {"format": "jpeg", "quality": 70, **capture},
            )
            mime_type = "image/jpeg"
    if len(raw) > MAX_VISUAL_PATCH_BYTES:
        raise ValueError("The visual patch exceeds the bounded payload.")
    return {
        "ref": visual_ref,
        "mimeType": mime_type,
        "width": max(1, round(width * scale)),
        "height": max(1, round(height * scale)),
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "data": encoded,
    }


def capture_screenshot(
    cdp: CdpConnection,
    options: dict[str, Any],
) -> tuple[str, bytes]:
    encoded = cdp.call("Page.captureScreenshot", options).get("data")
    if not isinstance(encoded, str):
        raise RuntimeError("Chrome returned no visual patch.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise RuntimeError("Chrome returned an invalid visual patch.") from error
    if not raw:
        raise RuntimeError("Chrome returned an empty visual patch.")
    return encoded, raw


def attach_visual_patch(
    snapshot: dict[str, Any],
    targets: dict[str, tuple[Any, dict[str, Any]]],
    visual_ref: str | None,
) -> dict[str, Any]:
    snapshot["visualPatch"] = capture_visual_patch(visual_ref, targets) if visual_ref else None
    return snapshot


def cdp_resolve_object(cdp: CdpConnection, backend_node_id: int) -> str:
    resolved = cdp.call("DOM.resolveNode", {"backendNodeId": backend_node_id})
    object_id = resolved.get("object", {}).get("objectId")
    if not isinstance(object_id, str):
        raise RuntimeError("Chrome could not resolve the semantic web target.")
    return object_id


def cdp_invoke(cdp: CdpConnection, backend_node_id: int) -> None:
    cdp.call("Page.enable")
    cdp.call("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_node_id})
    box = cdp.call("DOM.getBoxModel", {"backendNodeId": backend_node_id}).get("model", {})
    quad = box.get("content") or box.get("border")
    if not isinstance(quad, list) or len(quad) != 8:
        raise RuntimeError("The semantic target has no visible click surface.")
    x = sum(float(quad[index]) for index in (0, 2, 4, 6)) / 4
    y = sum(float(quad[index]) for index in (1, 3, 5, 7)) / 4
    common = {"x": x, "y": y, "button": "left", "clickCount": 1}
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", **common})
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **common})


def cdp_focus(cdp: CdpConnection, backend_node_id: int, already_focused: bool = False) -> None:
    cdp.call("Page.bringToFront")
    cdp.call("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_node_id})
    if already_focused:
        return
    try:
        cdp.call("DOM.focus", {"backendNodeId": backend_node_id})
    except Exception:
        object_id = cdp_resolve_object(cdp, backend_node_id)
        cdp.call(
            "Runtime.callFunctionOn",
            {
                "objectId": object_id,
                "functionDeclaration": "function(){if(!this.hasAttribute('tabindex'))this.setAttribute('tabindex','-1');this.focus({preventScroll:true});return document.activeElement===this}",
                "returnByValue": True,
            },
        )


def cdp_action_readback_on_connection(
    cdp: CdpConnection,
    backend_node_id: int,
    action: str,
    requested_text: Any,
    object_id: str | None = None,
) -> bool:
    if action not in {"focus", "set_text"}:
        return False
    resolved_object_id = object_id or cdp_resolve_object(cdp, backend_node_id)
    result = cdp.call(
        "Runtime.callFunctionOn",
        {
            "objectId": resolved_object_id,
            "functionDeclaration": "function(){return {focused:document.activeElement===this,value:this instanceof HTMLSelectElement?(this.selectedOptions[0]?.text||this.value):this.isContentEditable?this.textContent:this.value}}",
            "returnByValue": True,
        },
    )
    value = result.get("result", {}).get("value", {})
    if action == "focus":
        return value.get("focused") is True
    return isinstance(requested_text, str) and value.get("value") == requested_text


def cdp_act(facts: dict[str, Any], action: str, text: str | None) -> bool:
    page = cdp_target_page(facts["cdp"]["targetId"])
    backend_node_id = int(facts["cdp"]["backendDOMNodeId"])
    with CdpConnection(page, timeout=2.0) as cdp:
        if action == "focus":
            cdp_focus(cdp, backend_node_id)
            return cdp_action_readback_on_connection(
                cdp,
                backend_node_id,
                action,
                text,
            )
        if action == "invoke":
            cdp_invoke(cdp, backend_node_id)
            return False
        object_id = cdp_resolve_object(cdp, backend_node_id)
        if action == "set_text" and text is not None:
            cdp.call(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "functionDeclaration": "function(value){this.focus();if(this instanceof HTMLSelectElement){const choice=Array.from(this.options).find(option=>option.text.trim()===value||option.label.trim()===value||option.value===value);if(!choice)throw new Error('No select option matches the requested semantic value.');this.value=choice.value}else if(this.isContentEditable){this.textContent=value}else{const owner=Object.getPrototypeOf(this);const setter=Object.getOwnPropertyDescriptor(owner,'value')?.set;setter?setter.call(this,value):this.value=value}this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}))}",
                    "arguments": [{"value": text}],
                    "returnByValue": True,
                },
            )
            return cdp_action_readback_on_connection(
                cdp,
                backend_node_id,
                action,
                text,
                object_id,
            )
    raise RuntimeError("Chrome rejected the semantic web action.")


def refresh_cdp_target(facts: dict[str, Any]) -> tuple[Any, dict[str, Any]] | None:
    cdp_facts = facts.get("cdp", {})
    target_id = str(cdp_facts.get("targetId") or "")
    backend_node_id = cdp_facts.get("backendDOMNodeId")
    if not target_id or not isinstance(backend_node_id, int):
        return None
    try:
        page = cdp_target_page(target_id)
        with CdpConnection(page, timeout=2.0) as cdp:
            cdp.call("Accessibility.enable")
            raw_nodes = cdp.call(
                "Accessibility.getPartialAXTree",
                {"backendNodeId": backend_node_id, "fetchRelatives": False},
            ).get("nodes", [])
            raw = next(
                (
                    item
                    for item in raw_nodes
                    if isinstance(item, dict)
                    and item.get("backendDOMNodeId") == backend_node_id
                    and not item.get("ignored")
                ),
                None,
            )
            if raw is None:
                return None
            role = normalized_ax_role(ax_value(raw, "role"))
            properties = {
                str(item.get("name")): ax_value(item, "value")
                for item in raw.get("properties", [])
                if isinstance(item, dict)
            }
            attributes = (
                cdp_dom_attributes(cdp, backend_node_id)
                if role in FORM_CONTROL_ROLES
                else {}
            )
            raw_name = bounded_text(ax_value(raw, "name"))
            name = (
                semantic_control_name(
                    raw_name,
                    attributes,
                    cdp_dom_label(cdp, backend_node_id) if not raw_name else "",
                )
                if role in FORM_CONTROL_ROLES
                else raw_name
            )
    except Exception:
        return None
    node = copy.deepcopy(facts.get("node", {}))
    node["role"] = role
    node["name"] = name
    states = ["disabled"] if ax_state_is_true(properties.get("disabled")) else ["enabled"]
    for state in ("focused", "selected", "checked", "expanded", "required", "readonly"):
        if ax_state_is_true(properties.get(state)):
            states.append(state)
    node["states"] = states
    if is_sensitive_field(name, properties, attributes):
        node["actions"] = [
            action for action in node.get("actions", []) if action != "set_text"
        ]
    return None, {"node": node, "interfaces": {}, "cdp": dict(cdp_facts)}


def cdp_action_readback(
    facts: dict[str, Any],
    action: str,
    requested_text: Any,
) -> bool:
    if action not in {"focus", "set_text"}:
        return False
    cdp_facts = facts.get("cdp", {})
    target_id = str(cdp_facts.get("targetId") or "")
    backend_node_id = cdp_facts.get("backendDOMNodeId")
    if not target_id or not isinstance(backend_node_id, int):
        return False
    try:
        with CdpConnection(cdp_target_page(target_id), timeout=2.0) as cdp:
            return cdp_action_readback_on_connection(
                cdp,
                backend_node_id,
                action,
                requested_text,
            )
    except Exception:
        return False


def node_descends_from(
    node: dict[str, Any],
    ancestor_ref: str,
    by_ref: dict[str, dict[str, Any]],
) -> bool:
    parent_ref = node.get("parentRef")
    for _ in range(32):
        if parent_ref == ancestor_ref:
            return True
        parent = by_ref.get(parent_ref)
        if parent is None:
            return False
        parent_ref = parent.get("parentRef")
    return False


def selected_option_matches(nodes: list[dict[str, Any]], control_ref: str, requested_text: str) -> bool:
    by_ref = {node["ref"]: node for node in nodes}
    for node in nodes:
        if node.get("role") != "option" or "selected" not in node.get("states", []):
            continue
        if requested_text not in {node.get("name"), node.get("value")}:
            continue
        if node_descends_from(node, control_ref, by_ref):
            return True
    return False


def editable_content_matches(nodes: list[dict[str, Any]], control_ref: str, requested_text: str) -> bool:
    by_ref = {node["ref"]: node for node in nodes}
    return any(
        requested_text in {node.get("name"), node.get("value")}
        and node_descends_from(node, control_ref, by_ref)
        for node in nodes
    )


KEYS = {
    "Alt": ("Alt", "AltLeft", 18),
    "Control": ("Control", "ControlLeft", 17),
    "Shift": ("Shift", "ShiftLeft", 16),
    "Meta": ("Meta", "MetaLeft", 91),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37),
    "ArrowUp": ("ArrowUp", "ArrowUp", 38),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40),
    "Enter": ("Enter", "Enter", 13),
    "Escape": ("Escape", "Escape", 27),
    "Tab": ("Tab", "Tab", 9),
    "Space": (" ", "Space", 32),
    "Backspace": ("Backspace", "Backspace", 8),
    "Delete": ("Delete", "Delete", 46),
    "Home": ("Home", "Home", 36),
    "End": ("End", "End", 35),
    "PageUp": ("PageUp", "PageUp", 33),
    "PageDown": ("PageDown", "PageDown", 34),
}

MODIFIER_MASKS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


def browser_key_parameters(key: str) -> dict[str, Any] | None:
    named = KEYS.get(key)
    if named is not None:
        key_value, code, virtual_key = named
        return {
            "key": key_value,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
            "nativeVirtualKeyCode": virtual_key,
        }
    if len(key) != 1 or not key.isprintable() or key in {"\r", "\n", "\t"}:
        return None
    upper = key.upper()
    if "A" <= upper <= "Z":
        code = f"Key{upper}"
        virtual_key = ord(upper)
    elif "0" <= key <= "9":
        code = f"Digit{key}"
        virtual_key = ord(key)
    else:
        code = "Unidentified"
        virtual_key = ord(key)
    return {
        "key": key,
        "code": code,
        "text": key,
        "unmodifiedText": key,
        "windowsVirtualKeyCode": virtual_key,
        "nativeVirtualKeyCode": virtual_key,
    }


def press_browser_key(key: str) -> None:
    dispatch_browser_input_sequence([{"keys": [key], "holdMs": round(DEFAULT_BROWSER_KEY_DWELL_SECONDS * 1000), "waitMs": 0}])


def normalize_input_sequence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_INPUT_SEQUENCE_STEPS:
        raise ValueError("inputSequence must contain 1 to 64 steps")
    total_ms = 0
    normalized = []
    for step in value:
        if not isinstance(step, dict):
            raise ValueError("inputSequence steps must be objects")
        keys = step.get("keys")
        hold_ms = step.get("holdMs")
        wait_ms = step.get("waitMs", 0)
        if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_INPUT_SEQUENCE_KEYS:
            raise ValueError("inputSequence step keys must contain 1 to 3 entries")
        if any(not isinstance(key, str) or browser_key_parameters(key) is None for key in keys):
            raise ValueError("inputSequence contains an unsupported key")
        if len(set(keys)) != len(keys):
            raise ValueError("inputSequence step keys must be unique")
        if type(hold_ms) is not int or not 16 <= hold_ms <= 2000:
            raise ValueError("inputSequence holdMs must be between 16 and 2000")
        if type(wait_ms) is not int or not 0 <= wait_ms <= 1000:
            raise ValueError("inputSequence waitMs must be between 0 and 1000")
        total_ms += hold_ms + wait_ms
        if total_ms > MAX_INPUT_SEQUENCE_DURATION_MS:
            raise ValueError("inputSequence must finish within 8000 ms")
        normalized.append({"keys": keys, "holdMs": hold_ms, "waitMs": wait_ms})
    return normalized


def normalize_realtime_mode(
    value: Any,
    facts: dict[str, Any],
    action: str,
    return_observation: bool,
) -> str:
    mode = "continuous" if value is None else value
    if mode not in {"continuous", "stepped"}:
        raise ValueError("realtimeMode must be continuous or stepped")
    if mode == "stepped":
        node = facts.get("node", {})
        if "cdp" not in facts or node.get("role") != "canvas":
            raise ValueError("stepped realtime mode requires an exact browser canvas target")
        if action not in {"focus", "press_key", "input_sequence"}:
            raise ValueError("stepped realtime mode supports focus, press_key, or input_sequence")
        if not return_observation:
            raise ValueError("stepped realtime mode requires returnObservation")
    return mode


def dispatch_browser_input_sequence(steps: list[dict[str, Any]]) -> None:
    normalized = normalize_input_sequence(steps)
    page = active_browser_page()
    if page is None:
        raise RuntimeError("No active browser page is available.")
    with CdpConnection(page) as cdp:
        dispatch_input_sequence(cdp, normalized)


def dispatch_input_sequence(cdp: CdpConnection, normalized: list[dict[str, Any]]) -> None:
    for step in normalized:
        pressed: list[tuple[str, dict[str, Any]]] = []
        modifiers = 0
        pending_error: BaseException | None = None
        try:
            for key in step["keys"]:
                params = browser_key_parameters(key)
                if params is None:
                    raise ValueError("Unsupported browser key")
                modifiers |= MODIFIER_MASKS.get(key, 0)
                event_type = "keyDown" if "text" in params and modifiers & 7 == 0 else "rawKeyDown"
                event = {"type": event_type, **params, "modifiers": modifiers}
                if event_type == "rawKeyDown":
                    event.pop("text", None)
                    event.pop("unmodifiedText", None)
                cdp.call("Input.dispatchKeyEvent", event)
                pressed.append((key, params))
            time.sleep(step["holdMs"] / 1000)
        except BaseException as error:
            pending_error = error
        finally:
            for key, params in reversed(pressed):
                try:
                    modifiers &= ~MODIFIER_MASKS.get(key, 0)
                    event = {"type": "keyUp", **params, "modifiers": modifiers}
                    event.pop("text", None)
                    event.pop("unmodifiedText", None)
                    cdp.call("Input.dispatchKeyEvent", event)
                except BaseException as error:
                    if pending_error is None:
                        pending_error = error
        if pending_error is not None:
            raise pending_error
        if step["waitMs"]:
            time.sleep(step["waitMs"] / 1000)


def cdp_input_sequence(facts: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    page = cdp_target_page(facts["cdp"]["targetId"])
    backend_node_id = int(facts["cdp"]["backendDOMNodeId"])
    normalized = normalize_input_sequence(steps)
    with CdpConnection(page) as cdp:
        cdp_focus(cdp, backend_node_id, "focused" in facts.get("node", {}).get("states", []))
        dispatch_input_sequence(cdp, normalized)


def browser_state_token() -> str:
    page = active_browser_page()
    if page is None:
        return ""
    expression = """(()=>{const key=Symbol.for('dev.wiii.semantic.mutation');let state=window[key];if(!state){state={revision:0};new MutationObserver(()=>{state.revision++}).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});window[key]=state}const active=document.activeElement,canvas=Array.from(document.querySelectorAll('canvas')).slice(0,4).map(node=>{try{const data=node.toDataURL('image/webp',0.05),step=Math.max(1,Math.floor(data.length/512));let hash=2166136261;for(let i=0;i<data.length;i+=step)hash=Math.imul(hash^data.charCodeAt(i),16777619);return (hash>>>0).toString(16)}catch{return ''}}).join(',');return [location.href,state.revision,active?.tagName||'',active?.getAttribute?.('type')||'',active?.getAttribute?.('role')||'',active?.getAttribute?.('aria-label')||'',canvas].join('|')})()"""
    with CdpConnection(page) as cdp:
        result = cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return bounded_text(result.get("result", {}).get("value"), 500)


def browser_effect_version(before_version: str, state_token: str, page_ids: set[str]) -> str:
    material = json.dumps(
        {
            "before": before_version,
            "state": state_token,
            "pages": sorted(page_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def should_emit(role: str, name: str, value: str | None, states: list[str], actions: list[str], depth: int) -> bool:
    if depth <= 2 or name or value or actions:
        return True
    meaningful_roles = (
        "application",
        "frame",
        "dialog",
        "window",
        "panel",
        "menu",
        "button",
        "entry",
        "document",
        "link",
        "tab",
        "table",
        "list",
    )
    return any(value in role for value in meaningful_roles) or "focused" in states


def should_collect_browser_scene(scope_ref: str | None) -> bool:
    return scope_ref is None


def observe(
    environment_id: str,
    max_nodes: int,
    scope_ref: str | None = None,
    continuation: str | None = None,
    since_state_version: str | None = None,
    known_node_versions: Any = None,
    visual_ref: str | None = None,
    native_only: bool = False,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]]:
    output_limit = max(1, min(int(max_nodes), MAX_STATE_NODES))
    if scope_ref == WORKSTATION_NODE["ref"] or (
        scope_ref is None and output_limit <= len(APP_LAUNCHERS) + 1
    ):
        snapshot = workstation_snapshot(
            environment_id,
            output_limit,
            scope_ref,
            continuation,
            since_state_version,
            known_node_versions,
        )
        return attach_visual_patch(snapshot, {}, visual_ref), {}
    if scope_ref == "app:browser":
        snapshot, targets = browser_snapshot(
            environment_id,
            output_limit,
            scope_ref,
            continuation,
            since_state_version,
            known_node_versions,
            visual_ref,
        )
        return attach_visual_patch(snapshot, targets, visual_ref), targets
    if scope_ref == "app:files":
        snapshot = files_snapshot(
            environment_id,
            output_limit,
            scope_ref,
            continuation,
            since_state_version,
            known_node_versions,
        )
        return attach_visual_patch(snapshot, {}, visual_ref), {}

    cacheable_native_observation = (
        continuation is None
        and since_state_version is None
        and known_node_versions is None
        and visual_ref is None
        and native_app_id_for_scope(scope_ref) is not None
    )
    if cacheable_native_observation:
        cached = cached_native_observation(environment_id, scope_ref, output_limit)
        if cached is not None:
            return cached
    native_app_id = native_app_id_for_scope(scope_ref)
    scoped_native_launcher = APP_LAUNCHERS_BY_REF.get(scope_ref or "")
    scoped_native_process_ids = (
        launcher_process_ids(scoped_native_launcher)
        if scoped_native_launcher is not None
        else set()
    )
    observation_generation = (
        native_app_generation(native_app_id)
        if native_app_id is not None
        else 0
    )

    require_atspi()
    desktop = pyatspi.Registry.getDesktop(0)
    nodes = [*workstation_nodes(), *project_file_nodes()]
    targets: dict[str, tuple[Any, dict[str, Any]]] = {}
    if not native_only and should_collect_browser_scene(scope_ref):
        try:
            web_nodes, web_targets = cdp_semantic_nodes()
        except Exception:
            web_nodes, web_targets = [], {}
    else:
        web_nodes, web_targets = [], {}
    browser_adapter = adapter_payload(APP_LAUNCHERS_BY_REF.get("app:browser"))
    if browser_adapter is not None:
        for node in web_nodes:
            node.setdefault("adapter", browser_adapter)
    nodes.extend(web_nodes)
    targets.update(web_targets)
    active_window_ref: str | None = None
    capture_truncated = False
    ref_counts: dict[str, int] = {}
    nodes_by_ref = {
        node["ref"]: node
        for node in nodes
        if isinstance(node.get("ref"), str)
    }

    def visit(accessible, parent_ref: str | None, app_id: str | None, depth: int) -> None:
        nonlocal active_window_ref, capture_truncated
        if len(nodes) >= MAX_STATE_NODES:
            capture_truncated = True
            return
        role = bounded_text(safe(accessible.getRoleName, "unknown"), 100).lower() or "unknown"
        if "application" in role and scoped_native_process_ids:
            process_id = safe(accessible.get_process_id, -1)
            if process_id not in scoped_native_process_ids:
                return
        name = bounded_text(safe(lambda: accessible.name, ""))
        description = bounded_text(safe(lambda: accessible.description, "")) or None
        states = state_names(accessible)
        value = node_value(accessible, role)
        current_app = app_id
        current_launcher = APP_LAUNCHERS_BY_ID.get(current_app or "")
        recognized_application = False
        if "application" in role:
            application_name = name or bounded_text(safe(lambda: accessible.getApplication().name, "")) or ""
            current_launcher = launcher_for_application(application_name)
            if current_launcher is not None and current_launcher["appId"] == "browser":
                return
            if scope_ref is not None and scope_ref.startswith("app:") and (
                current_launcher is None or current_launcher["ref"] != scope_ref
            ):
                return
            if current_launcher is not None:
                current_app = current_launcher["appId"]
                parent_ref = current_launcher["ref"]
                recognized_application = True
            else:
                current_app = application_name or None

        parent_node = nodes_by_ref.get(parent_ref)
        is_wechat_conversation = bool(
            current_app == "wechat"
            and role == "list item"
            and "selectable" in states
            and parent_node is not None
            and parent_node.get("role") == "list"
            and parent_node.get("name") == "Chats"
        )
        actions, interfaces = normalized_actions(
            accessible,
            states,
            role,
            allow_pointer_invoke=is_wechat_conversation,
        )
        if is_sensitive_accessibility_field(role, name, description):
            actions = [action for action in actions if action != "set_text"]
            interfaces.pop("set_text", None)
            states = sorted({*states, "protected"})

        emitted_ref = parent_ref
        if not recognized_application and should_emit(role, name, value, states, actions, depth):
            node = {
                "ref": "",
                "parentRef": parent_ref,
                "appId": current_app,
                "role": role,
                "name": name,
                "description": description,
                "value": value,
                "states": states,
                "actions": actions,
                "bounds": node_bounds(accessible),
                "sources": ["desktop", "accessibility", "layout"],
            }
            adapter = adapter_payload(current_launcher)
            if adapter is not None:
                node["adapter"] = adapter
            base_ref = semantic_node_ref(
                len(nodes) + 1,
                node,
                accessibility_object_identity(accessible),
            )
            ordinal = ref_counts.get(base_ref, 0)
            ref_counts[base_ref] = ordinal + 1
            node_ref = base_ref if ordinal == 0 else f"{base_ref}-{ordinal}"
            node["ref"] = node_ref
            nodes.append(node)
            nodes_by_ref[node_ref] = node
            targets[node_ref] = (accessible, {"node": node, "interfaces": interfaces})
            emitted_ref = node_ref
            if active_window_ref is None and "active" in states and any(
                token in role for token in ("frame", "dialog", "window")
            ):
                active_window_ref = node_ref

        child_count = int(safe(lambda: accessible.childCount, 0) or 0)
        for index in range(child_count):
            if len(nodes) >= MAX_STATE_NODES:
                capture_truncated = True
                return
            child = safe(lambda index=index: accessible.getChildAtIndex(index))
            if child is not None:
                visit(child, emitted_ref, current_app, depth + 1)

    visit(desktop, WORKSTATION_NODE["ref"], None, 0)
    enrich_wechat_semantics(nodes)
    visible_nodes, projection = project_scene(
        environment_id,
        nodes,
        output_limit,
        "desktop",
        capture_truncated,
        scope_ref,
        continuation,
        since_state_version,
        known_node_versions,
    )
    visible_refs = {node["ref"] for node in visible_nodes}
    snapshot = {
        "protocolVersion": PROTOCOL_VERSION,
        "environmentId": environment_id,
        "stateVersion": projection["stateVersion"],
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": "linux_atspi",
        "screen": {"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
        "activeWindowRef": active_window_ref if active_window_ref in visible_refs else None,
        "frame": ai_frame("desktop", projection["scopedNodes"]),
        "nodes": visible_nodes,
        "truncated": projection["truncated"],
        "scopeRef": projection["scopeRef"],
        "projection": projection["projection"],
        "nextContinuation": projection["nextContinuation"],
        "deltaFromStateVersion": projection["deltaFromStateVersion"],
        "removedRefs": projection["removedRefs"],
    }
    retained_refs = visible_refs | ({visual_ref} if visual_ref else set())
    visible_targets = {
        ref: target for ref, target in targets.items() if ref in retained_refs
    }
    snapshot = attach_visual_patch(snapshot, visible_targets, visual_ref)
    if cacheable_native_observation:
        remember_native_observation(
            environment_id,
            scope_ref,
            output_limit,
            observation_generation,
            snapshot,
            visible_targets,
        )
    return snapshot, visible_targets


def rejection_escalation(code: str) -> str:
    if code in {"semantic_stale_snapshot", "semantic_target_missing", "semantic_target_mismatch"}:
        return "observe"
    if code in {"semantic_action_unsupported", "semantic_action_invalid"}:
        return "choose_supported_action"
    return "stop"


def semantic_action_route(
    launcher: dict[str, Any] | None,
    facts: dict[str, Any],
    action: str,
) -> str:
    if launcher is not None:
        if launcher["appId"] == "browser" and action == "set_text":
            return "browser_navigation"
        if launcher["appId"] == "browser" and action == "press_key":
            return "browser_keyboard"
        if launcher["appId"] == "browser" and action == "input_sequence":
            return "browser_input_sequence"
        return "workstation_launcher"
    if "cdp" in facts:
        return {
            "focus": "browser_dom_focus",
            "invoke": "browser_trusted_pointer",
            "set_text": "browser_dom_text",
            "press_key": "browser_target_keyboard",
            "input_sequence": "browser_target_input_sequence",
        }.get(action, "browser_input")
    if facts.get("node", {}).get("appId") == "wechat":
        semantic_kind = wechat_semantic_kind(facts["node"])
        if semantic_kind == "conversation" and action == "invoke":
            return "wechat_select_conversation"
        if semantic_kind == "composer" and action == "set_text":
            return "wechat_composer_text"
        if semantic_kind == "send_control" and action == "invoke":
            return "wechat_send_message"
    if action == "invoke" and "invoke_pointer" in facts.get("interfaces", {}):
        return "accessibility_trusted_pointer"
    return {
        "focus": "accessibility_focus",
        "invoke": "accessibility_action",
        "set_text": "accessibility_text",
    }.get(action, "accessibility")


def semantic_action_evidence(route: str, action: str, verified: bool) -> list[str]:
    if not verified:
        return []
    if route == "browser_navigation":
        return ["document_identity_readback"]
    if route == "browser_keyboard":
        return ["input_dispatch_ack"]
    if route == "browser_input_sequence":
        return ["bounded_input_sequence", "input_dispatch_ack"]
    if route == "browser_target_keyboard":
        return ["semantic_target_focus", "input_dispatch_ack"]
    if route == "browser_target_input_sequence":
        return ["semantic_target_focus", "bounded_input_sequence", "input_dispatch_ack"]
    if route == "workstation_launcher":
        return ["process_or_window_readback"]
    if route == "wechat_select_conversation":
        return ["conversation_selection_readback"]
    if route == "wechat_composer_text":
        return ["composer_value_readback"]
    if route == "wechat_send_message":
        return ["composer_clear_readback", "application_send_acceptance"]
    if route == "accessibility_trusted_pointer":
        return ["semantic_target_bounds", "trusted_pointer_dispatch", "semantic_state_change"]
    if action == "focus":
        return ["focus_readback"]
    if action == "set_text":
        return ["value_readback"]
    return ["semantic_state_change"]


def invoke_effect_fingerprint(nodes: list[dict[str, Any]], app_id: str | None) -> str:
    relevant = []
    for source in nodes:
        if source.get("appId") != app_id:
            continue
        node = {
            key: value
            for key, value in source.items()
            if key not in {"bounds", "version"}
        }
        node["states"] = sorted(
            state
            for state in source.get("states", [])
            if state not in INVOKE_TRANSIENT_STATES
        )
        relevant.append(node)
    material = json.dumps(
        sorted(relevant, key=lambda node: str(node.get("ref") or "")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def invoke_effect_observed(
    before_nodes: list[dict[str, Any]],
    after_nodes: list[dict[str, Any]],
    app_id: str | None,
) -> bool:
    return invoke_effect_fingerprint(before_nodes, app_id) != invoke_effect_fingerprint(after_nodes, app_id)


def native_action_readback(
    target: tuple[Any, dict[str, Any]] | None,
    action: str,
    requested_text: Any,
) -> bool:
    if target is None:
        return False
    accessible, facts = target
    node = facts.get("node", {})
    if action == "set_text" and isinstance(requested_text, str):
        try:
            return node_value(accessible, str(node.get("role") or "")) == requested_text
        except Exception:
            return False
    if action == "focus":
        try:
            return "focused" in state_names(accessible)
        except Exception:
            return False
    if action == "invoke" and wechat_semantic_kind(node) == "conversation":
        deadline = time.monotonic() + 0.8
        while True:
            try:
                current_states = set(state_names(accessible))
            except Exception:
                return False
            if current_states.intersection({"selected", "checked"}):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.04)
    return False


def wechat_composer_before_send(
    targets: dict[str, tuple[Any, dict[str, Any]]],
) -> tuple[Any, str] | None:
    for accessible, facts in targets.values():
        node = facts.get("node", {})
        if node.get("appId") != "wechat" or wechat_semantic_kind(node) != "composer":
            continue
        value = node_value(accessible, str(node.get("role") or ""))
        if value:
            return accessible, value
    return None


def wait_for_wechat_send_readback(
    composer_before: tuple[Any, str] | None,
) -> bool:
    if composer_before is None:
        return False
    accessible, previous_value = composer_before
    deadline = time.monotonic() + 1.2
    while True:
        current_value = node_value(accessible, "text")
        if previous_value and not current_value:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.04)


def action_effect_version(
    before_version: str,
    target_ref: str,
    action: str,
) -> str:
    material = json.dumps(
        {
            "before": before_version,
            "target": target_ref,
            "action": action,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def reject(request: dict[str, Any], code: str, detail: str, before: str, after: str | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "result": {
            "environmentId": request.get("environmentId", ""),
            "outcome": "rejected",
            "code": code,
            "detail": detail,
            "action": request.get("action", "focus"),
            "targetRef": request.get("targetRef", ""),
            "beforeStateVersion": before,
            "afterStateVersion": after or before,
            "verified": False,
            "effect": "refused",
            "route": "none",
            "evidence": [],
            "escalation": rejection_escalation(code),
            "visualPatch": None,
        },
    }


def native_action_snapshot(
    environment_id: str,
    target_ref: str,
    scope_ref: str | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[Any, dict[str, Any]]]]:
    cached = cached_native_target_observation(
        environment_id,
        scope_ref,
        target_ref,
    )
    if cached is not None:
        return cached
    snapshot, targets = observe(
        environment_id,
        1000,
        scope_ref=scope_ref,
        native_only=True,
    )
    if target_ref in targets:
        return snapshot, targets
    time.sleep(0.04)
    return observe(
        environment_id,
        1000,
        scope_ref=scope_ref,
        native_only=True,
    )


def requested_action_visual_patch(
    enabled: bool,
    target_ref: str,
    target: tuple[Any, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not enabled or target is None:
        return None
    role = target[1].get("node", {}).get("role")
    if role not in {"canvas", "visual target"}:
        return None
    try:
        return capture_visual_patch(target_ref, {target_ref: target})
    except Exception:
        return None


def capture_then_hold_realtime(
    page: dict[str, Any],
    return_observation: bool,
    target_ref: str,
    target: tuple[Any, dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    time.sleep(REALTIME_CLOCK_SETTLE_SECONDS)
    visual_patch = requested_action_visual_patch(
        return_observation,
        target_ref,
        target,
    )
    return visual_patch, realtime_clock_hold(page)


def act(request: dict[str, Any]) -> dict[str, Any]:
    environment_id = bounded_text(request.get("environmentId"), 200)
    target_ref = bounded_text(request.get("targetRef"), 100)
    requested_action = request.get("action")
    requested_realtime_mode = request.get("realtimeMode")
    return_observation = request.get("returnObservation", False)
    request_state_version = bounded_text(request.get("stateVersion"), 96)
    observed_scope = observation_scope_for(environment_id, request_state_version)
    if type(return_observation) is not bool:
        return reject(
            request,
            "semantic_observation_invalid",
            "returnObservation must be a boolean.",
            bounded_text(request.get("stateVersion"), 96),
        )
    launcher = APP_LAUNCHERS_BY_REF.get(target_ref)
    fast_snapshot = workstation_snapshot(environment_id, len(APP_LAUNCHERS) + 1)
    fast_launcher = (
        launcher is not None
        and request.get("stateVersion") == fast_snapshot["stateVersion"]
    )
    fast_canvas_target = (
        fast_browser_canvas_target(target_ref)
        if is_browser_target_ref(target_ref)
        and request.get("expectedRole") == "canvas"
        and requested_action in {"press_key", "input_sequence"}
        else None
    )
    browser_token_before = ""
    if (
        fast_launcher
        and requested_action in {"press_key", "input_sequence"}
        and launcher["appId"] == "browser"
    ) or is_browser_target_ref(target_ref):
        browser_token_before = browser_state_token()
    if fast_launcher:
        snapshot, targets = fast_snapshot, {}
    elif fast_canvas_target is not None:
        snapshot = {
            "stateVersion": request.get("stateVersion", ""),
            "nodes": [fast_canvas_target[1]["node"]],
        }
        targets = {target_ref: fast_canvas_target}
    elif is_browser_target_ref(target_ref):
        cached = cached_browser_target_observation(
            environment_id,
            request_state_version,
            target_ref,
        )
        if cached is None:
            snapshot, targets = browser_snapshot(environment_id, 1000)
        else:
            snapshot, targets = cached
            refreshed = refresh_cdp_target(targets[target_ref][1])
            if refreshed is None:
                targets.pop(target_ref, None)
            else:
                targets[target_ref] = refreshed
    elif target_ref.startswith("ui-"):
        snapshot, targets = native_action_snapshot(
            environment_id,
            target_ref,
            observed_scope,
        )
    else:
        snapshot, targets = observe(environment_id, 1000)
    before_version = snapshot["stateVersion"]
    target = targets.get(target_ref)
    if launcher is None and target is None:
        if request.get("stateVersion") != before_version:
            return reject(request, "semantic_stale_snapshot", "The target changed after it was observed; observe again before acting.", before_version)
        return reject(request, "semantic_target_missing", "The semantic target is not present in the current snapshot.", before_version)
    if launcher is not None:
        facts = {"node": launcher_node(launcher), "interfaces": {}}
    else:
        _accessible, facts = target
    node = facts["node"]
    target_launcher = APP_LAUNCHERS_BY_ID.get(str(node.get("appId") or ""))
    native_post_scope = (
        target_launcher["ref"]
        if target_ref.startswith("ui-") and target_launcher is not None
        else observed_scope
    )
    identity_matches = request.get("expectedRole") == node["role"] and request.get("expectedName") == node["name"]
    if request.get("stateVersion") != before_version and not identity_matches:
        return reject(request, "semantic_stale_snapshot", "The target changed after it was observed; observe again before acting.", before_version)
    if not identity_matches:
        return reject(request, "semantic_target_mismatch", "The target identity no longer matches the observed control.", before_version)

    action = requested_action
    if action not in node["actions"]:
        return reject(request, "semantic_action_unsupported", "The target does not expose this normalized action.", before_version)
    route = semantic_action_route(launcher, facts, action)
    wechat_send_before = (
        wechat_composer_before_send(targets)
        if route == "wechat_send_message"
        else None
    )
    try:
        realtime_mode = normalize_realtime_mode(
            requested_realtime_mode,
            facts,
            action,
            return_observation,
        )
    except ValueError as error:
        return reject(request, "semantic_realtime_mode_invalid", str(error), before_version)

    if target_launcher is not None and target_launcher["appId"] not in {"browser", "files"}:
        invalidate_native_observations(target_launcher["appId"])

    realtime_page = None
    clock_was_held = False
    clock_active_started = None
    if facts.get("node", {}).get("role") == "canvas" and "cdp" in facts:
        realtime_page = cdp_target_page(facts["cdp"]["targetId"])
        clock_was_held = realtime_clock_state(realtime_page) is not None
        if realtime_mode == "stepped":
            clock_active_started = time.monotonic()
        if clock_was_held:
            realtime_clock_resume_page(realtime_page)
            time.sleep(REALTIME_CLOCK_RESUME_GRACE_SECONDS)

    browser_target = None
    browser_navigation_before = None
    direct_browser_readback = False
    web_page_ids_before: set[str] | None = None
    launcher_process_ids_before: set[int] | None = None
    launcher_window_ids_before: set[str] | None = None
    if launcher is not None:
        if action == "set_text" and launcher["appId"] == "browser":
            text = request.get("text")
            if not isinstance(text, str):
                return reject(request, "semantic_text_required", "set_text requires text.", before_version)
            try:
                browser_target = browser_navigation_target(text)
            except ValueError as error:
                return reject(request, "semantic_text_required", str(error), before_version)
            browser_navigation_before = navigate_browser(browser_target)
            launched_process = None
        elif action == "press_key" and launcher["appId"] == "browser":
            key = request.get("key")
            if not isinstance(key, str) or browser_key_parameters(key) is None:
                return reject(request, "semantic_key_unsupported", "press_key requires a portable named key or one printable character.", before_version)
            press_browser_key(key)
            launched_process = None
        elif action == "input_sequence" and launcher["appId"] == "browser":
            try:
                input_sequence = normalize_input_sequence(request.get("inputSequence"))
            except ValueError as error:
                return reject(request, "semantic_input_sequence_invalid", str(error), before_version)
            dispatch_browser_input_sequence(input_sequence)
            launched_process = None
        elif action == "invoke":
            launcher_process_ids_before = launcher_process_ids(launcher)
            launcher_window_ids_before = launcher_window_ids(launcher)
            if launcher["appId"] == "browser":
                web_page_ids_before = {
                    str(page.get("id"))
                    for page in browser_pages()
                    if isinstance(page.get("id"), str)
                }
            launched_process = launch_application(launcher)
        else:
            return reject(request, "semantic_action_unsupported", "This application launcher does not support the requested action.", before_version)
    elif "cdp" in facts:
        if action == "press_key":
            key = request.get("key")
            if not isinstance(key, str) or browser_key_parameters(key) is None:
                return reject(request, "semantic_key_unsupported", "press_key requires a portable named key or one printable character.", before_version)
            cdp_input_sequence(
                facts,
                [{"keys": [key], "holdMs": round(DEFAULT_BROWSER_KEY_DWELL_SECONDS * 1000), "waitMs": 0}],
            )
        elif action == "input_sequence":
            try:
                input_sequence = normalize_input_sequence(request.get("inputSequence"))
            except ValueError as error:
                return reject(request, "semantic_input_sequence_invalid", str(error), before_version)
            cdp_input_sequence(facts, input_sequence)
        else:
            text = request.get("text") if action == "set_text" else None
            if action == "set_text" and not isinstance(text, str):
                return reject(request, "semantic_text_required", "set_text requires text.", before_version)
            if action == "invoke":
                web_page_ids_before = {
                    str(page.get("id"))
                    for page in browser_pages()
                    if isinstance(page.get("id"), str)
                }
            direct_browser_readback = cdp_act(facts, action, text)
    elif action == "focus":
        facts["interfaces"]["focus"].grabFocus()
    elif action == "set_text":
        text = request.get("text")
        if not isinstance(text, str):
            return reject(request, "semantic_text_required", "set_text requires text.", before_version)
        facts["interfaces"]["set_text"].setTextContents(text)
    elif action == "invoke":
        pointer = facts["interfaces"].get("invoke_pointer")
        if pointer is not None:
            extents = pointer.getExtents(pyatspi.DESKTOP_COORDS)
            if int(extents.width) <= 0 or int(extents.height) <= 0:
                raise RuntimeError("The semantic target has no visible activation bounds")
            x = int(extents.x + extents.width / 2)
            y = int(extents.y + extents.height / 2)
            pyatspi.Registry.generateMouseEvent(x, y, "b1c")
        else:
            action_iface = facts["interfaces"]["invoke"]
            count = int(action_iface.nActions)
            names = [bounded_text(action_iface.getName(index), 80).lower() for index in range(count)]
            preferred = next(index for index, name in enumerate(names) if name in ACCESSIBILITY_ACTIVATION_ACTIONS)
            if not action_iface.doAction(preferred):
                raise RuntimeError("AT-SPI rejected the invoke action")
    else:
        return reject(request, "semantic_action_invalid", "Unknown semantic action.", before_version)

    clock_result = None
    stepped_visual_patch = None
    if realtime_page is not None and realtime_mode == "stepped":
        stepped_visual_patch, held = capture_then_hold_realtime(
            realtime_page,
            return_observation,
            target_ref,
            target,
        )
        active_ms = round((time.monotonic() - (clock_active_started or time.monotonic())) * 1000)
        clock_result = {**held, "activeMs": max(0, active_ms)}
    elif realtime_page is not None and clock_was_held:
        clock_result = {
            "mode": "continuous",
            "activeMs": round(REALTIME_CLOCK_RESUME_GRACE_SECONDS * 1000),
            "watchdogMs": REALTIME_CLOCK_WATCHDOG_MS,
            "deadlineMs": None,
        }

    after = None
    after_target = None
    direct_native_readback = (
        launcher is None
        and target_ref.startswith("ui-")
        and (
            native_action_readback(target, action, request.get("text"))
            or (
                route == "wechat_send_message"
                and wait_for_wechat_send_readback(wechat_send_before)
            )
        )
    )
    direct_action_readback = direct_native_readback or direct_browser_readback
    if launcher is not None and fast_launcher:
        if browser_target is not None:
            deadline = time.monotonic() + 2.0
            navigation_target_id = (
                browser_navigation_before.get("navigationTargetId")
                if isinstance(browser_navigation_before, dict)
                else None
            )
            verified = browser_navigation_completed(
                browser_target,
                browser_navigation_before,
                navigation_target_id,
            )
            while not verified and time.monotonic() < deadline:
                time.sleep(0.05)
                verified = browser_navigation_completed(
                    browser_target,
                    browser_navigation_before,
                    navigation_target_id,
                )
        elif action in {"press_key", "input_sequence"}:
            verified = True
        else:
            deadline = time.monotonic() + 1.5
            verified = False
            while not verified and time.monotonic() < deadline:
                process_ids_after = launcher_process_ids(launcher)
                window_ids_after = launcher_window_ids(launcher)
                verified = bool(
                    process_ids_after - (launcher_process_ids_before or set())
                    or window_ids_after - (launcher_window_ids_before or set())
                )
                if web_page_ids_before is not None:
                    verified = verified or any(
                        isinstance(page.get("id"), str) and page["id"] not in web_page_ids_before
                        for page in browser_pages()
                    )
                if verified or (launched_process.poll() not in (None, 0)):
                    break
                time.sleep(0.05)
        after_version = fast_snapshot["stateVersion"]
    elif is_browser_target_ref(target_ref) and action == "invoke":
        deadline = time.monotonic() + 1.8
        after_token = browser_state_token()
        pages_after = {
            str(page.get("id"))
            for page in browser_pages()
            if isinstance(page.get("id"), str)
        }
        verified = after_token != browser_token_before or bool(
            pages_after - (web_page_ids_before or set())
        )
        while not verified and time.monotonic() < deadline:
            time.sleep(0.04)
            after_token = browser_state_token()
            pages_after = {
                str(page.get("id"))
                for page in browser_pages()
                if isinstance(page.get("id"), str)
            }
            verified = after_token != browser_token_before or bool(
                pages_after - (web_page_ids_before or set())
            )
        after_version = (
            browser_effect_version(before_version, after_token, pages_after)
            if verified
            else before_version
        )
    elif is_browser_target_ref(target_ref) and action in {"press_key", "input_sequence"}:
        after_token = browser_state_token()
        pages_after = {
            str(page.get("id"))
            for page in browser_pages()
            if isinstance(page.get("id"), str)
        }
        verified = True
        after_version = browser_effect_version(before_version, after_token, pages_after)
    elif direct_action_readback:
        verified = True
        after_version = action_effect_version(before_version, target_ref, action)
    else:
        time.sleep(0.25 if launcher is not None else 0.08)
        verification_deadline = time.monotonic() + (
            1.8 if is_browser_target_ref(target_ref) and action == "invoke"
            else 1.0 if action == "invoke"
            else 0.0
        )
        while True:
            if is_browser_target_ref(target_ref):
                after, after_targets = browser_snapshot(environment_id, 1000)
            else:
                after, after_targets = observe(
                    environment_id,
                    1000,
                    scope_ref=native_post_scope,
                    native_only=target_ref.startswith("ui-"),
                )
            after_version = after["stateVersion"]
            after_target = after_targets.get(target_ref)
            if is_browser_target_ref(target_ref):
                verified = browser_state_token() != browser_token_before
            elif action == "invoke":
                verified = invoke_effect_observed(
                    snapshot["nodes"],
                    after["nodes"],
                    node.get("appId"),
                )
            else:
                verified = after_version != before_version
            if web_page_ids_before is not None:
                verified = verified or any(
                    isinstance(page.get("id"), str) and page["id"] not in web_page_ids_before
                    for page in browser_pages()
                )
            if verified or time.monotonic() >= verification_deadline:
                break
            time.sleep(0.08)
        if launcher is not None and action in {"press_key", "input_sequence"}:
            verified = after_version != before_version
        elif launcher is not None:
            verified = verified or bool(
                launcher_process_ids(launcher) - (launcher_process_ids_before or set())
                or launcher_window_ids(launcher) - (launcher_window_ids_before or set())
            )
    if not direct_action_readback and launcher is None and action == "focus" and after_target is not None:
        verified = "focused" in after_target[1]["node"]["states"]
    elif not direct_action_readback and launcher is None and action == "set_text" and after_target is not None:
        requested_text = request.get("text")
        verified = (
            after_target[1]["node"].get("value") == requested_text
            or selected_option_matches(after["nodes"], target_ref, requested_text)
            or editable_content_matches(after["nodes"], target_ref, requested_text)
        )

    visual_patch = (
        stepped_visual_patch
        if realtime_mode == "stepped"
        else requested_action_visual_patch(return_observation, target_ref, target)
    )
    input_delivered = verified and action in {"press_key", "input_sequence"} and route.startswith("browser")
    effect = "input_delivered" if input_delivered else "confirmed" if verified else "unverifiable"
    if input_delivered:
        detail = "Input was delivered to the exact semantic target. Inspect visualPatch or observe to judge the task-level effect."
    elif verified:
        detail = "Action completed and its effect was observed."
    else:
        detail = "Action completed, but the generic semantic adapter could not prove its effect. Observe before continuing."
    evidence = semantic_action_evidence(route, action, verified)
    if visual_patch is not None:
        evidence.append("post_action_visual")
    if clock_result is not None:
        evidence.append(
            "realtime_step_held"
            if clock_result["mode"] == "stepped"
            else "realtime_resumed"
        )
    observation = None
    if return_observation and realtime_mode != "stepped":
        observation_scope = (
            "app:browser"
            if is_browser_target_ref(target_ref)
            or (launcher is not None and launcher["appId"] == "browser")
            else launcher["ref"] if launcher is not None else native_post_scope
        )
        observation, _ = observe(
            environment_id,
            100,
            scope_ref=observation_scope,
        )
        after_version = observation["stateVersion"]
    return {
        "status": "ok",
        "result": {
            "environmentId": environment_id,
            "outcome": "completed",
            "code": None if verified else "semantic_effect_unverified",
            "detail": detail,
            "action": action,
            "targetRef": target_ref,
            "beforeStateVersion": before_version,
            "afterStateVersion": after_version,
            "verified": verified,
            "effect": effect,
            "route": route,
            "evidence": evidence,
            "escalation": None if verified else "observe",
            "visualPatch": visual_patch,
            "clock": clock_result,
            "observation": observation,
        },
    }


def bridge_request(path: str, request: dict[str, Any]) -> dict[str, Any]:
    if path == "/observe":
        snapshot, targets = observe(
            request["environmentId"],
            request.get("maxNodes", 400),
            request.get("scopeRef"),
            request.get("continuation"),
            request.get("sinceStateVersion"),
            request.get("knownNodeVersions"),
            request.get("visualRef"),
        )
        remember_observation_scope(
            request["environmentId"],
            snapshot["stateVersion"],
            snapshot.get("scopeRef"),
        )
        remember_browser_observation(request["environmentId"], snapshot, targets)
        return {"status": "ok", "snapshot": snapshot}
    if path == "/act":
        return act(request)
    if path == "/events":
        return poll_app_events(request)
    raise ValueError("Unknown semantic bridge route.")


class SemanticBridgeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self.write_json(200, {"status": "ok", "appEventWatcher": APP_EVENT_WATCHER_STATE})

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= MAX_BRIDGE_REQUEST_BYTES:
                raise ValueError("The semantic bridge request is too large.")
            request = json.loads(self.rfile.read(content_length).decode("utf-8-sig"))
            if not isinstance(request, dict):
                raise ValueError("The semantic bridge request must be an object.")
            self.write_json(200, bridge_request(self.path, request))
        except Exception as error:
            self.write_json(
                400,
                {
                    "status": "error",
                    "code": "semantic_bridge_failed",
                    "detail": bounded_text(error, 1000),
                },
            )

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def serve() -> None:
    start_app_event_watcher()
    HTTPServer((SEMANTIC_BRIDGE_HOST, SEMANTIC_BRIDGE_PORT), SemanticBridgeHandler).serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--environment-id", required=True)
    observe_parser.add_argument("--max-nodes", type=int, default=400)
    subparsers.add_parser("observe-json")
    subparsers.add_parser("act")
    subparsers.add_parser("serve")
    watchdog_parser = subparsers.add_parser("clock-watchdog")
    watchdog_parser.add_argument("--target-id", required=True)
    watchdog_parser.add_argument("--token", required=True)
    watchdog_parser.add_argument("--deadline-ms", required=True, type=int)
    subparsers.add_parser("clock-resume")
    args = parser.parse_args()

    try:
        if args.command == "serve":
            serve()
            return 0
        if args.command == "observe":
            snapshot, _ = observe(args.environment_id, args.max_nodes)
            payload = {"status": "ok", "snapshot": snapshot}
        elif args.command == "observe-json":
            raw_request = sys.stdin.buffer.read(MAX_BRIDGE_REQUEST_BYTES + 1)
            if len(raw_request) > MAX_BRIDGE_REQUEST_BYTES or sys.stdin.buffer.read(1):
                raise ValueError("The semantic observation request is too large.")
            request = json.loads(raw_request.decode("utf-8-sig"))
            snapshot, _ = observe(
                request["environmentId"],
                request.get("maxNodes", 400),
                request.get("scopeRef"),
                request.get("continuation"),
                request.get("sinceStateVersion"),
                request.get("knownNodeVersions"),
                request.get("visualRef"),
            )
            payload = {"status": "ok", "snapshot": snapshot}
        elif args.command == "act":
            request = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
            payload = act(request)
        elif args.command == "clock-watchdog":
            realtime_clock_watchdog(args.target_id, args.token, args.deadline_ms)
            payload = {"status": "ok"}
        else:
            payload = {"status": "ok", "resumed": realtime_clock_resume_all()}
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "code": "semantic_bridge_failed", "detail": bounded_text(error, 1000)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
