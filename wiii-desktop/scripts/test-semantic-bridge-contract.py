#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch


BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src-tauri"
    / "src"
    / "neko"
    / "computer"
    / "image"
    / "semantic_bridge.py"
)
SPEC = importlib.util.spec_from_file_location("wiii_semantic_bridge", BRIDGE_PATH)
assert SPEC is not None and SPEC.loader is not None
sys.dont_write_bytecode = True
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class StableWorkstationContractTest(unittest.TestCase):
    def setUp(self) -> None:
        with BRIDGE.APP_EVENT_LOCK:
            BRIDGE.APP_EVENT_BUFFER.clear()
            BRIDGE.APP_EVENT_SEQUENCE = 0
            BRIDGE.APP_EVENT_GAP = False
        with BRIDGE.OBSERVATION_SCOPE_LOCK:
            BRIDGE.OBSERVATION_SCOPES.clear()
        with BRIDGE.NATIVE_OBSERVATION_LOCK:
            BRIDGE.NATIVE_APP_GENERATIONS.clear()
            BRIDGE.NATIVE_OBSERVATIONS.clear()

    def test_long_poll_does_not_block_health_or_control_requests(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        poll_results = []

        def request_route(path, _request):
            if path == "/events":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test failed to release event poll")
            return {"status": "ok"}

        with BRIDGE.ThreadingHTTPServer(("127.0.0.1", 0), BRIDGE.SemanticBridgeHandler) as server:
            host, port = server.server_address
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()

            def poll():
                client = http.client.HTTPConnection(host, port, timeout=6)
                try:
                    client.request("POST", "/events", body=b"{}")
                    response = client.getresponse()
                    poll_results.append(response.status)
                    response.read()
                finally:
                    client.close()

            with patch.object(BRIDGE, "bridge_request", side_effect=request_route):
                poll_thread = threading.Thread(target=poll, daemon=True)
                poll_thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    for method, route, body in [("GET", "/health", None), ("POST", "/observe", b"{}")]:
                        client = http.client.HTTPConnection(host, port, timeout=1)
                        try:
                            client.request(method, route, body=body)
                            response = client.getresponse()
                            self.assertEqual(response.status, 200)
                            response.read()
                        finally:
                            client.close()
                    self.assertFalse(release.is_set())
                finally:
                    release.set()
                    poll_thread.join(2)
                    server.shutdown()
                    server_thread.join(2)
            self.assertEqual(poll_results, [200])

    def test_atspi_events_are_content_free_and_cursor_resumable(self) -> None:
        class FakeApplication:
            name = "Google Chrome"

        class FakeSource:
            def getApplication(self):
                return FakeApplication()

        class FakeEvent:
            source = FakeSource()
            type = "object:text-changed:insert"

        BRIDGE.record_app_event(FakeEvent())
        first = BRIDGE.bridge_request(
            "/events",
            {"environmentId": "computer-test", "afterCursor": None, "limit": 8},
        )
        batch = first["batch"]
        self.assertEqual(batch["source"], "at_spi")
        self.assertEqual(batch["sourceId"], "atspi")
        self.assertEqual(len(batch["events"]), 1)
        self.assertEqual(batch["events"][0]["appId"], "browser")
        self.assertEqual(batch["events"][0]["resourceRef"], "app:browser")
        self.assertEqual(batch["events"][0]["kind"], "content_changed")
        encoded = json.dumps(batch)
        for forbidden in ("text", "value", "description", "callback", "password"):
            self.assertNotIn(forbidden, encoded)

        resumed = BRIDGE.bridge_request(
            "/events",
            {
                "environmentId": "computer-test",
                "afterCursor": batch["cursor"],
                "limit": 8,
            },
        )
        self.assertEqual(resumed["batch"]["events"], [])
        self.assertFalse(resumed["batch"]["gapDetected"])

    def test_native_observation_cache_is_bounded_and_event_invalidated(self) -> None:
        snapshot = {
            "stateVersion": "sha256:terminal-cached",
            "scopeRef": "app:terminal",
            "nodes": [{"ref": "ui-composer", "value": "draft"}],
        }
        target = object()
        targets = {"ui-composer": (target, {"node": snapshot["nodes"][0]})}
        with patch.object(BRIDGE, "APP_EVENT_WATCHER_STATE", "ready"):
            generation = BRIDGE.native_app_generation("terminal")
            BRIDGE.remember_native_observation(
                "computer-test",
                "app:terminal",
                100,
                generation,
                snapshot,
                targets,
            )
            cached = BRIDGE.cached_native_observation(
                "computer-test",
                "app:terminal",
                100,
            )
            self.assertIsNotNone(cached)
            cached_snapshot, cached_targets = cached
            cached_snapshot["nodes"][0]["value"] = "changed-copy"
            self.assertEqual(snapshot["nodes"][0]["value"], "draft")
            self.assertIs(cached_targets["ui-composer"][0], target)

            BRIDGE.invalidate_native_observations("terminal")
            self.assertIsNone(BRIDGE.cached_native_observation(
                "computer-test",
                "app:terminal",
                100,
            ))

    def test_native_observation_cache_is_not_used_without_live_event_watcher(self) -> None:
        BRIDGE.remember_native_observation(
            "computer-test",
            "app:terminal",
            100,
            0,
            {"stateVersion": "sha256:cached", "nodes": []},
            {},
        )
        self.assertIsNone(BRIDGE.cached_native_observation(
            "computer-test",
            "app:terminal",
            100,
        ))

    def test_native_observation_cache_evicts_the_oldest_environment(self) -> None:
        with patch.object(BRIDGE, "APP_EVENT_WATCHER_STATE", "ready"):
            for index in range(BRIDGE.MAX_NATIVE_OBSERVATION_CACHE + 1):
                BRIDGE.remember_native_observation(
                    f"computer-{index}",
                    "app:terminal",
                    100,
                    0,
                    {"stateVersion": f"sha256:{index}", "nodes": []},
                    {},
                )

            self.assertIsNone(BRIDGE.cached_native_observation(
                "computer-0",
                "app:terminal",
                100,
            ))
            self.assertIsNotNone(BRIDGE.cached_native_observation(
                f"computer-{BRIDGE.MAX_NATIVE_OBSERVATION_CACHE}",
                "app:terminal",
                100,
            ))

    def test_atspi_event_cursor_epoch_change_requires_reconciliation(self) -> None:
        batch = BRIDGE.bridge_request(
            "/events",
            {
                "environmentId": "computer-test",
                "afterCursor": "atspi:0000000000000000:9",
                "limit": 8,
            },
        )["batch"]
        self.assertTrue(batch["gapDetected"])

    def test_atspi_event_pagination_advances_only_past_returned_events(self) -> None:
        class FakeApplication:
            name = "Google Chrome"

        class FakeSource:
            def getApplication(self):
                return FakeApplication()

        class FakeEvent:
            source = FakeSource()
            type = "object:text-changed:insert"

        for _ in range(3):
            BRIDGE.record_app_event(FakeEvent())

        first = BRIDGE.bridge_request(
            "/events",
            {"environmentId": "computer-test", "afterCursor": None, "limit": 2},
        )["batch"]
        second = BRIDGE.bridge_request(
            "/events",
            {
                "environmentId": "computer-test",
                "afterCursor": first["cursor"],
                "limit": 2,
            },
        )["batch"]

        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["cursor"].endswith(":2"))
        self.assertEqual(len(second["events"]), 1)
        self.assertTrue(second["cursor"].endswith(":3"))
        self.assertNotEqual(first["events"][-1]["eventId"], second["events"][0]["eventId"])

    def test_atspi_long_poll_wakes_on_the_next_content_free_event(self) -> None:
        class FakeApplication:
            name = "Google Chrome"

        class FakeSource:
            def getApplication(self):
                return FakeApplication()

        class FakeEvent:
            source = FakeSource()
            type = "window:activate"

        result: list[dict] = []
        started = time.monotonic()
        worker = threading.Thread(
            target=lambda: result.append(
                BRIDGE.bridge_request(
                    "/events",
                    {
                        "environmentId": "computer-test",
                        "afterCursor": None,
                        "limit": 8,
                        "waitMs": 1_000,
                    },
                )["batch"]
            )
        )
        worker.start()
        time.sleep(0.05)
        BRIDGE.record_app_event(FakeEvent())
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["events"][0]["kind"], "attention_required")

    def test_atspi_event_source_ignores_unknown_applications(self) -> None:
        class FakeApplication:
            name = "Unmanaged private app"

        class FakeSource:
            def getApplication(self):
                return FakeApplication()

        class FakeEvent:
            source = FakeSource()
            type = "object:text-changed:insert"

        BRIDGE.record_app_event(FakeEvent())
        self.assertEqual(list(BRIDGE.APP_EVENT_BUFFER), [])

    def test_javascript_dialogs_fail_fast_for_human_takeover(self) -> None:
        class FakeSocket:
            def send(self, _payload: str) -> None:
                return None

            def recv(self) -> str:
                return '{"method":"Page.javascriptDialogOpening","params":{"type":"confirm","message":"private"}}'

        connection = object.__new__(BRIDGE.CdpConnection)
        connection.socket = FakeSocket()
        connection.message_id = 0
        with self.assertRaisesRegex(RuntimeError, "confirm dialog requires human takeover"):
            connection.call("Runtime.callFunctionOn")

    def test_web_invoke_dispatches_a_semantically_grounded_pointer_sequence(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                calls.append((method, params))
                if method == "DOM.getBoxModel":
                    return {"model": {"content": [10, 20, 30, 20, 30, 40, 10, 40]}}
                return {}

        facts = {"cdp": {"targetId": "page", "backendDOMNodeId": 42}}
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE, "cdp_resolve_object", return_value="object"),
        ):
            BRIDGE.cdp_act(facts, "invoke", None)

        self.assertIn(("Page.enable", None), calls)
        pressed = next(params for method, params in calls if method == "Input.dispatchMouseEvent" and params["type"] == "mousePressed")
        released = next(params for method, params in calls if method == "Input.dispatchMouseEvent" and params["type"] == "mouseReleased")
        self.assertEqual((pressed["x"], pressed["y"]), (20, 30))
        self.assertEqual(released["button"], "left")
        self.assertFalse(any(method == "Runtime.callFunctionOn" for method, _params in calls))

    def test_web_focus_and_readback_share_one_cdp_session(self) -> None:
        connections = 0

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, _params: dict | None = None) -> dict:
                if method == "Runtime.callFunctionOn":
                    return {"result": {"value": {"focused": True, "value": ""}}}
                return {}

        def connect(*_args, **_kwargs):
            nonlocal connections
            connections += 1
            return FakeCdp()

        facts = {"cdp": {"targetId": "page", "backendDOMNodeId": 42}}
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", side_effect=connect),
            patch.object(BRIDGE, "cdp_resolve_object", return_value="object"),
        ):
            verified = BRIDGE.cdp_act(facts, "focus", None)

        self.assertTrue(verified)
        self.assertEqual(connections, 1)

    def test_canvas_exposes_target_scoped_keyboard_actions(self) -> None:
        self.assertEqual(
            BRIDGE.cdp_node_actions("canvas", 42),
            ["focus", "invoke", "press_key", "input_sequence"],
        )

    def test_canvas_input_sequence_focuses_without_a_pointer_side_effect(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                calls.append((method, params))
                if method == "DOM.getBoxModel":
                    return {"model": {"content": [10, 20, 30, 20, 30, 40, 10, 40]}}
                return {}

        facts = {"cdp": {"targetId": "page", "backendDOMNodeId": 42}}
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep"),
        ):
            BRIDGE.cdp_input_sequence(
                facts,
                [{"keys": ["ArrowUp"], "holdMs": 100, "waitMs": 0}],
            )

        focus_index = next(index for index, (method, _params) in enumerate(calls) if method == "DOM.focus")
        key_index = next(index for index, (method, _params) in enumerate(calls) if method == "Input.dispatchKeyEvent")
        self.assertLess(focus_index, key_index)
        self.assertFalse(any(method == "Input.dispatchMouseEvent" for method, _params in calls))

    def test_canvas_input_sequence_keeps_an_existing_focus_without_clicking(self) -> None:
        calls: list[str] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, _params: dict | None = None) -> dict:
                calls.append(method)
                return {}

        facts = {
            "node": {"states": ["enabled", "focused"]},
            "cdp": {"targetId": "page", "backendDOMNodeId": 42},
        }
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep"),
        ):
            BRIDGE.cdp_input_sequence(
                facts,
                [{"keys": ["ArrowUp"], "holdMs": 100, "waitMs": 0}],
            )

        self.assertIn("Page.bringToFront", calls)
        self.assertNotIn("DOM.focus", calls)
        self.assertNotIn("Input.dispatchMouseEvent", calls)

    def test_canvas_target_can_be_resolved_without_a_full_semantic_projection(self) -> None:
        raw_canvas = {
            "nodeId": "ax-canvas",
            "backendDOMNodeId": 42,
            "role": {"value": "canvas"},
            "name": {"value": ""},
            "properties": [{"name": "focused", "value": {"value": True}}],
        }
        expected_ref = BRIDGE.web_node_ref("page", "frame", "ax-canvas", 42)

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, _params: dict | None = None) -> dict:
                if method == "Page.getFrameTree":
                    return {"frameTree": {"frame": {"id": "frame", "url": "https://example.test/game"}}}
                if method == "Accessibility.getFullAXTree":
                    return {"nodes": [raw_canvas]}
                return {}

        with (
            patch.object(BRIDGE, "active_browser_page", return_value={
                "id": "page",
                "url": "https://example.test/game",
            }),
            patch.object(BRIDGE, "browser_frame_targets", return_value=[]),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
        ):
            target = BRIDGE.fast_browser_canvas_target(expected_ref)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target[1]["node"]["name"], "Unlabeled canvas")
        self.assertEqual(target[1]["node"]["actions"], ["focus", "invoke", "press_key", "input_sequence"])
        self.assertEqual(target[1]["cdp"]["backendDOMNodeId"], 42)

    def test_browser_launcher_accepts_invoke_and_direct_navigation(self) -> None:
        browser = BRIDGE.APP_LAUNCHERS_BY_REF["app:browser"]
        node = BRIDGE.launcher_node(browser)
        self.assertEqual(node["role"], "browser")
        self.assertIn("accepts_text_query", node["states"])
        self.assertEqual(node["actions"], ["invoke", "set_text", "press_key", "input_sequence"])

    def test_gmail_is_detected_from_the_owned_browser_origin(self) -> None:
        self.assertEqual(
            BRIDGE.browser_application_kind({"url": "https://mail.google.com/mail/u/0/#inbox"}),
            "gmail",
        )
        self.assertIsNone(
            BRIDGE.browser_application_kind({"url": "https://example.com/mail.google.com"})
        )

    def test_gmail_message_summaries_precede_generic_toolbar_controls(self) -> None:
        nodes = [
            {
                "role": "button",
                "name": "Settings",
                "states": ["enabled"],
                "actions": ["invoke"],
            },
            {
                "role": "link",
                "name": "Project update - The verified work summary is ready for review",
                "states": ["enabled"],
                "actions": ["invoke"],
            },
            {
                "role": "checkbox",
                "name": "Ada, team, Project update, 09:30, The verified work summary is ready",
                "states": ["enabled"],
                "actions": ["invoke"],
            },
        ]
        ordered = sorted(
            nodes,
            key=lambda node: BRIDGE.web_node_priority(node, "gmail"),
        )
        self.assertEqual([node["role"] for node in ordered], ["checkbox", "link", "button"])

    def test_gmail_message_refs_survive_browser_node_recreation(self) -> None:
        first = {
            "ref": "web-old",
            "parentRef": "app:browser",
            "role": "link",
            "name": "Project update - The verified work summary is ready for review",
            "states": ["enabled"],
            "actions": ["invoke"],
            "sources": ["browser", "accessibility"],
        }
        second = {**first, "ref": "web-new", "sources": list(first["sources"])}
        self.assertEqual(BRIDGE.gmail_stable_ref(first), BRIDGE.gmail_stable_ref(second))

        targets = {
            "web-old": (None, {"node": first, "interfaces": {}, "cdp": {"backendDOMNodeId": 7}})
        }
        remapped = BRIDGE.apply_gmail_adapter([first], targets)
        stable_ref = BRIDGE.gmail_stable_ref(first)
        self.assertEqual(first["ref"], stable_ref)
        self.assertIn(stable_ref, remapped)
        self.assertEqual(first["adapter"]["id"], "wiii.gmail.rendered.v1")
        self.assertIn("stable_app_identity", first["sources"])
        self.assertTrue(BRIDGE.is_browser_target_ref(stable_ref))

    def test_ai_frame_describes_a_typed_coordinate_private_scene_graph(self) -> None:
        snapshot = BRIDGE.workstation_snapshot("computer-test", 4)
        self.assertEqual(snapshot["frame"], {
            "version": "wiii-ai-frame.v1",
            "scope": "workstation",
            "observationModel": "scene_graph",
            "actionModel": "typed_refs",
            "coordinates": "adapter_private",
            "modalities": ["workstation"],
            "interaction": {
                "mode": "semantic_control",
                "targetRef": None,
                "inputActions": [],
                "keymapSource": "none",
                "shortcuts": [],
                "feedback": "observe",
                "clockMode": "continuous",
                "clockModes": ["continuous"],
                "clockWatchdogMs": None,
            },
        })
        self.assertTrue(all(node["sources"] == ["workstation"] for node in snapshot["nodes"]))

    def test_ai_frame_identifies_canvas_keyboard_mode_without_inventing_a_keymap(self) -> None:
        frame = BRIDGE.ai_frame("browser", [{
            "ref": "web-canvas",
            "role": "canvas",
            "states": ["enabled", "focused"],
            "actions": ["focus", "invoke", "press_key", "input_sequence"],
            "sources": ["browser", "canvas_fingerprint"],
            "shortcuts": [],
        }])

        self.assertEqual(frame["interaction"], {
            "mode": "canvas_keyboard",
            "targetRef": "web-canvas",
            "inputActions": ["focus", "invoke", "press_key", "input_sequence"],
            "keymapSource": "unknown",
            "shortcuts": [],
            "feedback": "post_action_visual",
            "clockMode": "continuous",
            "clockModes": ["continuous", "stepped"],
            "clockWatchdogMs": 30000,
        })

    def test_ai_frame_reports_a_live_stepped_canvas_clock(self) -> None:
        with (
            patch.object(BRIDGE, "active_browser_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "realtime_clock_state", return_value={"targetId": "page"}),
        ):
            frame = BRIDGE.ai_frame("browser", [{
                "ref": "web-canvas",
                "role": "canvas",
                "states": ["focused"],
                "actions": ["focus", "input_sequence"],
                "sources": ["browser", "canvas_fingerprint"],
                "shortcuts": [],
            }])

        self.assertEqual(frame["interaction"]["clockMode"], "stepped")
        self.assertEqual(frame["interaction"]["clockModes"], ["continuous", "stepped"])
        self.assertEqual(frame["interaction"]["clockWatchdogMs"], 30000)

    def test_realtime_mode_is_bounded_to_observed_browser_canvas_actions(self) -> None:
        canvas = {"node": {"role": "canvas"}, "cdp": {"targetId": "page"}}
        self.assertEqual(
            BRIDGE.normalize_realtime_mode("stepped", canvas, "input_sequence", True),
            "stepped",
        )
        with self.assertRaisesRegex(ValueError, "returnObservation"):
            BRIDGE.normalize_realtime_mode("stepped", canvas, "input_sequence", False)
        with self.assertRaisesRegex(ValueError, "exact browser canvas"):
            BRIDGE.normalize_realtime_mode(
                "stepped",
                {"node": {"role": "entry"}, "cdp": {"targetId": "page"}},
                "focus",
                True,
            )
        with self.assertRaisesRegex(ValueError, "continuous or stepped"):
            BRIDGE.normalize_realtime_mode("turbo", canvas, "focus", True)

    def test_realtime_clock_hold_and_resume_are_token_scoped(self) -> None:
        page = {"id": "page", "webSocketDebuggerUrl": "ws://page"}
        connection = MagicMock()
        connection.__enter__.return_value = connection

        def watchdog_open(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/cmdline"):
                return io.BytesIO(b"python\x00clock-watchdog\x00token\x00")
            return open(path, *args, **kwargs)

        def start_watchdog(*_args, **_kwargs):
            BRIDGE.realtime_clock_write("page", "token", 123456)
            process = MagicMock()
            process.poll.return_value = None
            return process

        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(BRIDGE, "REALTIME_CLOCK_DIR", root),
            patch.object(BRIDGE.secrets, "token_hex", return_value="token"),
            patch.object(BRIDGE.subprocess, "Popen", side_effect=start_watchdog) as popen,
            patch.object(BRIDGE, "CdpConnection", return_value=connection),
            patch.object(BRIDGE, "open", side_effect=watchdog_open, create=True),
        ):
            held = BRIDGE.realtime_clock_hold(page)
            state = BRIDGE.realtime_clock_state(page)
            resumed = BRIDGE.realtime_clock_resume_page(page)
            cleared = BRIDGE.realtime_clock_state(page)

        self.assertEqual(held["mode"], "stepped")
        self.assertEqual(held["watchdogMs"], 30000)
        self.assertEqual(state["targetId"], "page")
        self.assertTrue(resumed)
        self.assertIsNone(cleared)
        popen.assert_called_once()
        self.assertEqual(connection.call.call_args_list, [
            call("Debugger.enable"),
            call("Debugger.resume"),
        ])

    def test_realtime_clock_watchdog_owns_pause_until_resume_event(self) -> None:
        page = {"id": "page", "webSocketDebuggerUrl": "ws://page"}
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.socket.recv.return_value = json.dumps({"method": "Debugger.resumed"})
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(BRIDGE, "REALTIME_CLOCK_DIR", root),
            patch.object(BRIDGE, "browser_pages", return_value=[page]),
            patch.object(BRIDGE, "CdpConnection", return_value=connection),
        ):
            BRIDGE.realtime_clock_watchdog(
                "page",
                "token",
                int(time.time() * 1000) + 1000,
            )
            state = BRIDGE.realtime_clock_state(page)

        self.assertIsNone(state)
        self.assertEqual(connection.call.call_args_list, [
            call("Debugger.enable"),
            call("Debugger.pause"),
        ])

    @unittest.skipUnless(BRIDGE.os.name == "posix", "Linux watchdog process identity")
    def test_realtime_clock_rejects_a_reused_process_id(self) -> None:
        def unrelated_process_open(path, *args, **kwargs):
            if str(path).startswith("/proc/") and str(path).endswith("/cmdline"):
                return io.BytesIO(b"python\x00unrelated-process\x00")
            return open(path, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(BRIDGE, "REALTIME_CLOCK_DIR", root),
            patch.object(BRIDGE, "open", side_effect=unrelated_process_open, create=True),
        ):
            BRIDGE.realtime_clock_write("page", "token", 123456)
            self.assertIsNone(BRIDGE.realtime_clock_state({"id": "page"}))
            self.assertFalse(Path(BRIDGE.realtime_clock_path("page")).exists())

    def test_ai_frame_preserves_bounded_declared_shortcuts_for_the_focused_target(self) -> None:
        frame = BRIDGE.ai_frame("browser", [{
            "ref": "web-editor",
            "role": "entry",
            "states": ["enabled", "focused"],
            "actions": ["focus", "set_text"],
            "sources": ["browser", "accessibility"],
            "shortcuts": BRIDGE.bounded_shortcuts("Control+S Alt+Enter"),
        }])

        self.assertEqual(frame["interaction"]["mode"], "text_entry")
        self.assertEqual(frame["interaction"]["keymapSource"], "declared")
        self.assertEqual(frame["interaction"]["shortcuts"], ["Control+S", "Alt+Enter"])

    def test_launchers_publish_typed_app_adapters(self) -> None:
        adapters = {
            node["ref"]: node["adapter"]["id"]
            for node in BRIDGE.workstation_nodes()
            if node["ref"].startswith("app:")
        }
        self.assertEqual(adapters["app:browser"], "wiii.chrome.v1")
        self.assertEqual(adapters["app:terminal"], "wiii.terminal.v1")
        self.assertEqual(adapters["app:files"], "wiii.files.v1")

    def test_files_adapter_projects_only_relative_project_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            Path(root, "docs").mkdir()
            Path(root, "README.md").write_text("secret body", encoding="utf-8")
            nodes = BRIDGE.project_file_nodes(root)

        self.assertEqual([node["name"] for node in nodes], ["docs", "README.md"])
        self.assertEqual([node["role"] for node in nodes], ["folder", "file"])
        self.assertTrue(all(node["parentRef"] == "app:files" for node in nodes))
        self.assertTrue(all(root not in str(node) for node in nodes))
        self.assertTrue(all("secret body" not in str(node) for node in nodes))

    def test_scoped_observation_returns_only_the_requested_subtree(self) -> None:
        nodes = [
            {"ref": "workstation:main", "parentRef": None, "role": "workstation"},
            {"ref": "app:browser", "parentRef": "workstation:main", "role": "browser"},
            {"ref": "web:document", "parentRef": "app:browser", "role": "document web"},
            {"ref": "web:button", "parentRef": "web:document", "role": "button"},
            {"ref": "app:files", "parentRef": "workstation:main", "role": "application_launcher"},
        ]
        visible, projection = BRIDGE.project_scene(
            "computer-test",
            nodes,
            20,
            "desktop",
            scope_ref="app:browser",
        )
        self.assertEqual([node["ref"] for node in visible], ["app:browser", "web:document", "web:button"])
        self.assertEqual(projection["scopeRef"], "app:browser")
        self.assertFalse(projection["truncated"])

    def test_opaque_continuation_pages_a_stable_scene_without_overlap(self) -> None:
        nodes = [
            {"ref": f"node:{index}", "parentRef": None, "role": "item", "name": str(index)}
            for index in range(3)
        ]
        with patch.object(BRIDGE, "continuation_signing_key", return_value=b"k" * 32):
            first, first_projection = BRIDGE.project_scene("computer-test", nodes, 1, "desktop")
            second, second_projection = BRIDGE.project_scene(
                "computer-test",
                nodes,
                1,
                "desktop",
                continuation=first_projection["nextContinuation"],
            )
        self.assertEqual([node["ref"] for node in first], ["node:0"])
        self.assertEqual([node["ref"] for node in second], ["node:1"])
        self.assertIsNotNone(second_projection["nextContinuation"])

    def test_opaque_continuation_rejects_tampering(self) -> None:
        nodes = [
            {"ref": "node:1", "parentRef": None, "role": "item"},
            {"ref": "node:2", "parentRef": None, "role": "item"},
        ]
        with patch.object(BRIDGE, "continuation_signing_key", return_value=b"k" * 32):
            _, projection = BRIDGE.project_scene("computer-test", nodes, 1, "desktop")
            token = projection["nextContinuation"]
            replacement = "A" if token[-1] != "A" else "B"
            with self.assertRaisesRegex(ValueError, "continuation is invalid"):
                BRIDGE.project_scene(
                    "computer-test",
                    nodes,
                    1,
                    "desktop",
                    continuation=token[:-1] + replacement,
                )

    def test_opaque_continuation_rejects_noncanonical_base64(self) -> None:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        with patch.object(BRIDGE, "continuation_signing_key", return_value=b"k" * 32):
            token = BRIDGE.encode_continuation(
                "computer-test",
                {"v": 1, "e": "computer-test", "s": "workstation:main", "o": 1},
            )
            packed = BRIDGE.base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            alias = next(
                candidate
                for tail in alphabet
                if (candidate := token[:-1] + tail) != token
                and BRIDGE.base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4)) == packed
            )
            with self.assertRaisesRegex(ValueError, "continuation is invalid"):
                BRIDGE.decode_continuation("computer-test", alias)

    def test_semantic_delta_returns_changed_added_and_removed_refs(self) -> None:
        before = [
            {"ref": "same", "parentRef": None, "role": "item", "name": "same"},
            {"ref": "changed", "parentRef": None, "role": "item", "name": "before"},
            {"ref": "removed", "parentRef": None, "role": "item", "name": "removed"},
        ]
        known = [
            {"ref": node["ref"], "version": node["version"]}
            for node in BRIDGE.versioned_nodes(before)
        ]
        after = [
            {"ref": "same", "parentRef": None, "role": "item", "name": "same"},
            {"ref": "changed", "parentRef": None, "role": "item", "name": "after"},
            {"ref": "added", "parentRef": None, "role": "item", "name": "added"},
        ]
        visible, projection = BRIDGE.project_scene(
            "computer-test",
            after,
            20,
            "desktop",
            since_state_version="sha256:before",
            known_node_versions=known,
        )
        self.assertEqual([node["ref"] for node in visible], ["changed", "added"])
        self.assertEqual(projection["projection"], "delta")
        self.assertEqual(projection["removedRefs"], ["removed"])

    def test_unchanged_state_returns_an_empty_delta_without_known_versions(self) -> None:
        nodes = [{"ref": "same", "parentRef": None, "role": "item", "name": "same"}]
        _, full = BRIDGE.project_scene("computer-test", nodes, 20, "desktop")
        visible, delta = BRIDGE.project_scene(
            "computer-test",
            nodes,
            20,
            "desktop",
            since_state_version=full["stateVersion"],
        )
        self.assertEqual(visible, [])
        self.assertEqual(delta["projection"], "delta")

    def test_action_routes_and_evidence_are_explicit(self) -> None:
        browser = BRIDGE.APP_LAUNCHERS_BY_REF["app:browser"]
        self.assertEqual(BRIDGE.semantic_action_route(browser, {}, "set_text"), "browser_navigation")
        self.assertEqual(BRIDGE.semantic_action_route(None, {"cdp": {}}, "invoke"), "browser_trusted_pointer")
        self.assertEqual(
            BRIDGE.semantic_action_route(None, {"interfaces": {"invoke_pointer": object()}}, "invoke"),
            "accessibility_trusted_pointer",
        )
        self.assertEqual(BRIDGE.semantic_action_evidence("browser_keyboard", "press_key", True), ["input_dispatch_ack"])
        self.assertEqual(BRIDGE.semantic_action_evidence("browser_trusted_pointer", "invoke", False), [])

    def test_browser_action_can_return_the_next_scoped_observation(self) -> None:
        launcher = BRIDGE.APP_LAUNCHERS_BY_REF["app:browser"]
        node = BRIDGE.launcher_node(launcher)
        before = BRIDGE.workstation_snapshot("computer-test", len(BRIDGE.APP_LAUNCHERS) + 1)
        after = {
            **before,
            "stateVersion": "sha256:" + "b" * 64,
            "scopeRef": "app:browser",
        }
        request = {
            "requestId": "return-observation-test",
            "environmentId": "computer-test",
            "leaseId": "lease-test",
            "stateVersion": before["stateVersion"],
            "targetRef": node["ref"],
            "expectedRole": node["role"],
            "expectedName": node["name"],
            "action": "set_text",
            "text": "https://example.com",
            "returnObservation": True,
        }

        with (
            patch.object(BRIDGE, "browser_page_state", return_value={}),
            patch.object(BRIDGE, "navigate_browser"),
            patch.object(BRIDGE, "browser_navigation_completed", return_value=True),
            patch.object(BRIDGE, "observe", return_value=(after, {})) as observe,
        ):
            result = BRIDGE.act(request)["result"]

        self.assertTrue(result["verified"])
        self.assertEqual(result["afterStateVersion"], after["stateVersion"])
        self.assertEqual(result["observation"], after)
        observe.assert_called_once_with("computer-test", 100, scope_ref="app:browser")

    def test_bridge_request_reuses_the_same_observation_contract(self) -> None:
        snapshot = {"stateVersion": "sha256:" + "a" * 64}
        request = {"environmentId": "computer-test", "maxNodes": 20}
        with patch.object(BRIDGE, "observe", return_value=(snapshot, {})) as observe:
            envelope = BRIDGE.bridge_request("/observe", request)

        self.assertEqual(envelope, {"status": "ok", "snapshot": snapshot})
        observe.assert_called_once_with(
            "computer-test",
            20,
            None,
            None,
            None,
            None,
            None,
        )

    def test_focus_only_qt_button_uses_semantically_grounded_pointer_fallback(self) -> None:
        class Action:
            nActions = 1

            def getName(self, _index: int) -> str:
                return "SetFocus"

        class Extents:
            width = 44
            height = 40

        class Component:
            def getExtents(self, _coordinates):
                return Extents()

        class Accessible:
            def queryAction(self):
                return Action()

            def queryEditableText(self):
                return None

            def queryComponent(self):
                return Component()

        class Atspi:
            DESKTOP_COORDS = 0

        with patch.object(BRIDGE, "pyatspi", Atspi()):
            actions, interfaces = BRIDGE.normalized_actions(
                Accessible(),
                ["focusable", "showing", "visible"],
                "push button",
            )

        self.assertEqual(actions, ["invoke", "focus"])
        self.assertIn("invoke_pointer", interfaces)
        self.assertNotIn("invoke", interfaces)

    def test_adapter_can_enable_pointer_invoke_for_a_selectable_list_item(self) -> None:
        class Action:
            nActions = 0

        class Extents:
            width = 210
            height = 68

        class Component:
            def getExtents(self, _coordinates):
                return Extents()

        class Accessible:
            def queryAction(self):
                return Action()

            def queryEditableText(self):
                return None

            def queryComponent(self):
                return Component()

        class Atspi:
            DESKTOP_COORDS = 0

        with patch.object(BRIDGE, "pyatspi", Atspi()):
            default_actions, _ = BRIDGE.normalized_actions(
                Accessible(),
                ["selectable", "showing", "visible"],
                "list item",
            )
            adapter_actions, interfaces = BRIDGE.normalized_actions(
                Accessible(),
                ["selectable", "showing", "visible"],
                "list item",
                allow_pointer_invoke=True,
            )

        self.assertNotIn("invoke", default_actions)
        self.assertEqual(adapter_actions, ["invoke"])
        self.assertIn("invoke_pointer", interfaces)

    def test_wechat_adapter_projects_conversations_messages_and_composer(self) -> None:
        nodes = [
            {"ref": "app:wechat", "parentRef": "workstation:main", "appId": "wechat", "role": "application_launcher", "name": "WeChat", "states": [], "actions": ["invoke"]},
            {"ref": "chat-list", "parentRef": "app:wechat", "appId": "wechat", "role": "list", "name": "Chats", "states": [], "actions": []},
            {"ref": "conversation", "parentRef": "chat-list", "appId": "wechat", "role": "list item", "name": "Teammate", "description": None, "states": ["selectable"], "actions": ["invoke"]},
            {"ref": "unread", "parentRef": "conversation", "appId": "wechat", "role": "label", "name": "2 unread", "description": None, "states": [], "actions": []},
            {"ref": "messages", "parentRef": "app:wechat", "appId": "wechat", "role": "list", "name": "Messages", "states": [], "actions": []},
            {"ref": "message", "parentRef": "messages", "appId": "wechat", "role": "text", "name": "Hello", "states": [], "actions": []},
            {"ref": "composer", "parentRef": "app:wechat", "appId": "wechat", "role": "entry", "name": "Message", "description": None, "states": ["editable"], "actions": ["set_text"]},
            {"ref": "search", "parentRef": "app:wechat", "appId": "wechat", "role": "entry", "name": "Search", "description": None, "states": ["editable"], "actions": ["set_text"]},
            {"ref": "send", "parentRef": "app:wechat", "appId": "wechat", "role": "push button", "name": "Send(S)", "description": None, "states": [], "actions": ["invoke"]},
        ]

        BRIDGE.enrich_wechat_semantics(nodes)

        by_ref = {node["ref"]: node for node in nodes}
        self.assertIn("conversation_list", by_ref["chat-list"]["states"])
        self.assertIn("conversation", by_ref["conversation"]["states"])
        self.assertIn("unread", by_ref["conversation"]["states"])
        self.assertIn("message_list", by_ref["messages"]["states"])
        self.assertIn("message", by_ref["message"]["states"])
        self.assertIn("composer", by_ref["composer"]["states"])
        self.assertNotIn("composer", by_ref["search"]["states"])
        self.assertIn("send_control", by_ref["send"]["states"])
        self.assertEqual(
            BRIDGE.semantic_action_route(None, {"node": by_ref["conversation"]}, "invoke"),
            "wechat_select_conversation",
        )
        self.assertEqual(
            BRIDGE.semantic_action_evidence("wechat_send_message", "invoke", True),
            ["composer_clear_readback", "application_send_acceptance"],
        )

    def test_wechat_send_readback_requires_a_nonempty_composer_to_clear(self) -> None:
        class Composer:
            def __init__(self) -> None:
                self.values = ["draft", ""]

            def queryText(self):
                return self

            def getText(self, _start: int, _end: int) -> str:
                return self.values.pop(0)

            def queryValue(self):
                return None

        composer = Composer()
        targets = {
            "composer": (
                composer,
                {
                    "node": {
                        "appId": "wechat",
                        "role": "entry",
                        "states": ["composer"],
                    }
                },
            )
        }

        before = BRIDGE.wechat_composer_before_send(targets)

        self.assertIsNotNone(before)
        self.assertTrue(BRIDGE.wait_for_wechat_send_readback(before))

    def test_wechat_send_action_returns_app_owned_evidence_without_a_rescan(self) -> None:
        class Composer:
            value = "draft"

            def queryText(self):
                return self

            def getText(self, _start: int, _end: int) -> str:
                return self.value

            def queryValue(self):
                return None

        composer = Composer()

        class SendAction:
            nActions = 1

            def getName(self, _index: int) -> str:
                return "invoke"

            def doAction(self, _index: int) -> bool:
                composer.value = ""
                return True

        send_node = {
            "ref": "ui-wechat-send",
            "parentRef": "ui-wechat-window",
            "appId": "wechat",
            "role": "push button",
            "name": "Send(S)",
            "description": "Send the current WeChat message",
            "value": None,
            "states": ["send_control"],
            "actions": ["invoke"],
            "bounds": None,
        }
        composer_node = {
            "ref": "ui-wechat-composer",
            "parentRef": "ui-wechat-window",
            "appId": "wechat",
            "role": "entry",
            "name": "Message",
            "description": "WeChat message composer",
            "value": "draft",
            "states": ["composer", "editable"],
            "actions": ["set_text"],
            "bounds": None,
        }
        snapshot = {
            "stateVersion": "sha256:wechat-send-before",
            "nodes": [send_node, composer_node],
        }
        targets = {
            send_node["ref"]: (
                object(),
                {"node": send_node, "interfaces": {"invoke": SendAction()}},
            ),
            composer_node["ref"]: (
                composer,
                {"node": composer_node, "interfaces": {}},
            ),
        }
        BRIDGE.remember_observation_scope(
            "computer-test",
            snapshot["stateVersion"],
            "app:wechat",
        )
        request = {
            "environmentId": "computer-test",
            "stateVersion": snapshot["stateVersion"],
            "targetRef": send_node["ref"],
            "expectedRole": send_node["role"],
            "expectedName": send_node["name"],
            "action": "invoke",
        }

        with (
            patch.object(BRIDGE, "native_action_snapshot", return_value=(snapshot, targets)),
            patch.object(BRIDGE, "observe") as observe,
        ):
            result = BRIDGE.act(request)["result"]

        self.assertEqual(result["route"], "wechat_send_message")
        self.assertTrue(result["verified"])
        self.assertEqual(
            result["evidence"],
            ["composer_clear_readback", "application_send_acceptance"],
        )
        observe.assert_not_called()

    def test_wechat_adapter_declares_typed_v2_capabilities(self) -> None:
        adapter = BRIDGE.OPTIONAL_APP_LAUNCHERS[0]["adapter"]

        self.assertEqual(adapter["id"], "wiii.wechat.v2")
        self.assertEqual(adapter["version"], "2")
        self.assertTrue({
            "conversation_identity",
            "unread_state",
            "message_delta",
            "select_conversation",
            "composer_readback",
            "send_evidence",
        }.issubset(set(adapter["capabilities"])))

    def test_invoke_verification_ignores_focus_only_changes(self) -> None:
        before = [{
            "ref": "button",
            "appId": "wechat",
            "role": "push button",
            "name": "Network proxy settings",
            "value": None,
            "states": ["enabled", "showing", "visible"],
            "actions": ["invoke", "focus"],
            "bounds": {"x": 10, "y": 10, "width": 40, "height": 40},
            "version": "before",
        }]
        focused = [{**before[0], "states": [*before[0]["states"], "focused"], "version": "focused"}]
        dialog = [*focused, {
            "ref": "proxy-dialog",
            "appId": "wechat",
            "role": "dialog",
            "name": "Network proxy settings",
            "value": None,
            "states": ["showing", "visible"],
            "actions": [],
        }]

        self.assertFalse(BRIDGE.invoke_effect_observed(before, focused, "wechat"))
        self.assertTrue(BRIDGE.invoke_effect_observed(before, dialog, "wechat"))

    def test_file_launcher_always_requests_a_distinct_window(self) -> None:
        files = BRIDGE.APP_LAUNCHERS_BY_REF["app:files"]
        self.assertIn("--new-win", files["argv"])
        self.assertIn("--role=wiii-project-files", files["argv"])

    def test_native_app_scope_does_not_collect_the_browser_scene(self) -> None:
        self.assertFalse(BRIDGE.should_collect_browser_scene("app:wechat"))
        self.assertFalse(BRIDGE.should_collect_browser_scene("app:office"))
        self.assertTrue(BRIDGE.should_collect_browser_scene(None))

    def test_native_target_resolution_requests_a_native_only_snapshot(self) -> None:
        snapshot = {"stateVersion": "sha256:current", "nodes": []}
        request = {
            "environmentId": "computer-test",
            "stateVersion": "sha256:before",
            "targetRef": "ui-native-control",
            "expectedRole": "text",
            "expectedName": "Message",
            "action": "set_text",
            "text": "draft",
        }
        with patch.object(BRIDGE, "observe", return_value=(snapshot, {})) as observe:
            result = BRIDGE.act(request)

        self.assertEqual(result["result"]["code"], "semantic_stale_snapshot")
        self.assertTrue(observe.call_args.kwargs["native_only"])

    def test_native_target_resolution_retries_observation_once_before_mutation(self) -> None:
        target = (object(), {"node": {"ref": "ui-target"}, "interfaces": {}})
        snapshots = [
            ({"stateVersion": "sha256:first", "nodes": []}, {}),
            ({"stateVersion": "sha256:second", "nodes": []}, {"ui-target": target}),
        ]
        with (
            patch.object(BRIDGE, "observe", side_effect=snapshots) as observe,
            patch.object(BRIDGE.time, "sleep") as sleep,
        ):
            snapshot, targets = BRIDGE.native_action_snapshot("computer-test", "ui-target")

        self.assertEqual(snapshot["stateVersion"], "sha256:second")
        self.assertIs(targets["ui-target"], target)
        self.assertEqual(observe.call_count, 2)
        self.assertTrue(all(call.kwargs["native_only"] for call in observe.call_args_list))
        sleep.assert_called_once_with(0.04)

    def test_native_target_resolution_reuses_a_complete_smaller_cached_scope(self) -> None:
        target = (object(), {"node": {"ref": "ui-target"}, "interfaces": {}})
        snapshot = {
            "stateVersion": "sha256:cached-scope",
            "scopeRef": "app:terminal",
            "nodes": [{"ref": "ui-target"}],
            "truncated": False,
        }
        with patch.object(BRIDGE, "APP_EVENT_WATCHER_STATE", "ready"):
            BRIDGE.remember_native_observation(
                "computer-test",
                "app:terminal",
                100,
                0,
                snapshot,
                {"ui-target": target},
            )
            with patch.object(BRIDGE, "observe") as observe:
                resolved_snapshot, resolved_targets = BRIDGE.native_action_snapshot(
                    "computer-test",
                    "ui-target",
                    "app:terminal",
                )

        self.assertEqual(resolved_snapshot["stateVersion"], "sha256:cached-scope")
        self.assertIs(resolved_targets["ui-target"][0], target[0])
        observe.assert_not_called()

    def test_observe_remembers_the_exact_scope_for_a_following_action(self) -> None:
        snapshot = {
            "stateVersion": "sha256:wechat-scope",
            "scopeRef": "app:wechat",
        }
        with patch.object(BRIDGE, "observe", return_value=(snapshot, {})):
            BRIDGE.bridge_request(
                "/observe",
                {
                    "environmentId": "computer-test",
                    "maxNodes": 100,
                    "scopeRef": "app:wechat",
                },
            )

        self.assertEqual(
            BRIDGE.observation_scope_for(
                "computer-test",
                "sha256:wechat-scope",
            ),
            "app:wechat",
        )

    def test_native_action_reuses_app_scope_for_resolution_and_readback(self) -> None:
        class Editable:
            value = ""

            def setTextContents(self, value: str) -> None:
                self.value = value

            def queryText(self):
                return self

            def getText(self, _start: int, _end: int) -> str:
                return self.value

            def queryValue(self):
                return None

        editable = Editable()
        before_node = {
            "ref": "ui-wechat-composer",
            "parentRef": "ui-wechat-window",
            "appId": "wechat",
            "role": "entry",
            "name": "Message",
            "description": None,
            "value": "",
            "states": ["editable", "focused"],
            "actions": ["set_text"],
            "bounds": None,
        }
        snapshots = [
            (
                {
                    "stateVersion": "sha256:wechat-before",
                    "nodes": [before_node],
                },
                {
                    "ui-wechat-composer": (
                        editable,
                        {
                            "node": before_node,
                            "interfaces": {"set_text": editable},
                        },
                    ),
                },
            ),
        ]
        BRIDGE.remember_observation_scope(
            "computer-test",
            "sha256:wechat-before",
            "app:wechat",
        )
        request = {
            "environmentId": "computer-test",
            "stateVersion": "sha256:wechat-before",
            "targetRef": "ui-wechat-composer",
            "expectedRole": "entry",
            "expectedName": "Message",
            "action": "set_text",
            "text": "Xin chào",
        }

        with (
            patch.object(BRIDGE, "observe", side_effect=snapshots) as observe,
            patch.object(BRIDGE.time, "sleep"),
        ):
            result = BRIDGE.act(request)

        self.assertTrue(result["result"]["verified"])
        self.assertEqual(editable.value, "Xin chào")
        self.assertEqual(observe.call_count, 1)
        self.assertTrue(all(
            call.kwargs["scope_ref"] == "app:wechat"
            and call.kwargs["native_only"]
            for call in observe.call_args_list
        ))

    def test_launcher_window_detection_is_scoped_to_the_application(self) -> None:
        output = "\n".join((
            "0x01 host pcmanfm.Pcmanfm Project - File Manager",
            "0x02 host google-chrome.Google-chrome News",
        ))
        with patch.object(
            BRIDGE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(("wmctrl", "-lx"), 0, output, ""),
        ):
            files = BRIDGE.APP_LAUNCHERS_BY_REF["app:files"]
            self.assertEqual(BRIDGE.launcher_window_ids(files), {"0x01"})

    def test_browser_key_vocabulary_is_explicit_and_portable(self) -> None:
        self.assertEqual(
            set(BRIDGE.KEYS),
            {
                "Alt", "Control", "Shift", "Meta",
                "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown",
                "Enter", "Escape", "Tab", "Space", "Backspace", "Delete",
                "Home", "End", "PageUp", "PageDown",
            },
        )
        self.assertEqual(BRIDGE.browser_key_parameters("n")["code"], "KeyN")
        self.assertEqual(BRIDGE.browser_key_parameters("7")["code"], "Digit7")
        self.assertEqual(BRIDGE.browser_key_parameters("\u1ebf")["text"], "\u1ebf")
        self.assertIsNone(BRIDGE.browser_key_parameters("ab"))
        self.assertIsNone(BRIDGE.browser_key_parameters("\n"))

    def test_browser_key_is_held_long_enough_for_frame_polled_apps(self) -> None:
        events: list[tuple[str, object]] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                events.append((method, params))
                return {}

        with (
            patch.object(BRIDGE, "active_browser_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep", side_effect=lambda seconds: events.append(("sleep", seconds))),
        ):
            BRIDGE.press_browser_key("ArrowUp")

        self.assertEqual(events[0][1]["type"], "rawKeyDown")
        self.assertEqual(events[1], ("sleep", BRIDGE.DEFAULT_BROWSER_KEY_DWELL_SECONDS))
        self.assertEqual(events[2][1]["type"], "keyUp")

    def test_browser_input_sequence_supports_chords_and_releases_in_reverse_order(self) -> None:
        events: list[tuple[str, object]] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                events.append((method, params))
                return {}

        sequence = [{"keys": ["Space", "ArrowUp"], "holdMs": 240, "waitMs": 20}]
        with (
            patch.object(BRIDGE, "active_browser_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep", side_effect=lambda seconds: events.append(("sleep", seconds))),
        ):
            BRIDGE.dispatch_browser_input_sequence(sequence)

        self.assertEqual([event[1]["type"] for event in events if event[0] == "Input.dispatchKeyEvent"], [
            "rawKeyDown", "rawKeyDown", "keyUp", "keyUp",
        ])
        self.assertEqual(events[0][1]["key"], " ")
        self.assertEqual(events[1][1]["key"], "ArrowUp")
        self.assertEqual(events[3][1]["key"], "ArrowUp")
        self.assertEqual(events[4][1]["key"], " ")
        self.assertEqual(events[2], ("sleep", 0.24))
        self.assertEqual(events[5], ("sleep", 0.02))

    def test_browser_input_sequence_preserves_printable_web_key_events(self) -> None:
        events: list[dict] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                if method == "Input.dispatchKeyEvent":
                    events.append(params or {})
                return {}

        with (
            patch.object(BRIDGE, "active_browser_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep"),
        ):
            BRIDGE.dispatch_browser_input_sequence([
                {"keys": ["w"], "holdMs": 100, "waitMs": 0},
            ])

        self.assertEqual([event["type"] for event in events], ["keyDown", "keyUp"])
        self.assertEqual(events[0]["text"], "w")
        self.assertEqual(events[0]["unmodifiedText"], "w")
        self.assertEqual(events[0]["code"], "KeyW")
        self.assertEqual(events[0]["windowsVirtualKeyCode"], 87)

    def test_browser_input_sequence_is_bounded(self) -> None:
        valid = BRIDGE.normalize_input_sequence([
            {"keys": ["Space", "ArrowUp"], "holdMs": 2000, "waitMs": 0},
            {"keys": ["ArrowRight"], "holdMs": 1000, "waitMs": 100},
        ])
        self.assertEqual(valid[0]["keys"], ["Space", "ArrowUp"])
        for invalid in (
            [],
            [{"keys": ["ArrowUp", "ArrowUp"], "holdMs": 100}],
            [{"keys": ["ArrowUp"], "holdMs": 15}],
            [{"keys": ["ArrowUp"], "holdMs": 2001}],
            [{"keys": ["ArrowUp"], "holdMs": 2000}] * 5,
        ):
            with self.assertRaises(ValueError):
                BRIDGE.normalize_input_sequence(invalid)

    def test_browser_input_sequence_propagates_modifier_state(self) -> None:
        events: list[dict] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                if method == "Input.dispatchKeyEvent":
                    events.append(params or {})
                return {}

        with (
            patch.object(BRIDGE, "active_browser_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE.time, "sleep"),
        ):
            BRIDGE.dispatch_browser_input_sequence([
                {"keys": ["Alt", "ArrowRight"], "holdMs": 100, "waitMs": 0},
            ])

        self.assertEqual([event["type"] for event in events], [
            "rawKeyDown", "rawKeyDown", "keyUp", "keyUp",
        ])
        self.assertEqual([event["modifiers"] for event in events], [1, 1, 1, 0])
        self.assertEqual(events[1]["key"], "ArrowRight")
        self.assertEqual(events[2]["key"], "ArrowRight")

    def test_visual_patch_is_scoped_to_a_bounded_canvas(self) -> None:
        encoded = BRIDGE.base64.b64encode(b"png").decode("ascii")

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, _params: dict | None = None) -> dict:
                if method == "DOM.getBoxModel":
                    return {"model": {"border": [10, 20, 210, 20, 210, 120, 10, 120]}}
                if method == "Page.captureScreenshot":
                    return {"data": encoded}
                return {}

        targets = {
            "web:canvas": (
                None,
                {
                    "node": {"role": "canvas"},
                    "cdp": {"targetId": "page", "backendDOMNodeId": 42},
                },
            ),
        }
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
        ):
            visual = BRIDGE.capture_visual_patch("web:canvas", targets)

        self.assertEqual((visual["width"], visual["height"]), (200, 100))
        self.assertEqual(visual["mimeType"], "image/png")
        self.assertEqual(visual["data"], encoded)
        with self.assertRaises(ValueError):
            BRIDGE.capture_visual_patch("web:button", {
                "web:button": (None, {"node": {"role": "button"}, "cdp": {}}),
            })

    def test_visual_patch_falls_back_to_bounded_jpeg(self) -> None:
        calls: list[dict] = []
        oversized = BRIDGE.base64.b64encode(b"p" * (BRIDGE.MAX_VISUAL_PATCH_BYTES + 1)).decode("ascii")
        jpeg = BRIDGE.base64.b64encode(b"jpeg").decode("ascii")

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                if method == "DOM.getBoxModel":
                    return {"model": {"border": [10, 20, 210, 20, 210, 120, 10, 120]}}
                if method == "Page.captureScreenshot":
                    calls.append(params or {})
                    return {"data": oversized if params and params["format"] == "png" else jpeg}
                return {}

        targets = {
            "web:canvas": (
                None,
                {
                    "node": {"role": "canvas"},
                    "cdp": {"targetId": "page", "backendDOMNodeId": 42},
                },
            ),
        }
        with (
            patch.object(BRIDGE, "cdp_target_page", return_value={"id": "page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
        ):
            visual = BRIDGE.capture_visual_patch("web:canvas", targets)

        self.assertEqual([call["format"] for call in calls], ["png", "jpeg"])
        self.assertEqual(visual["mimeType"], "image/jpeg")
        self.assertEqual(visual["data"], jpeg)

    def test_action_can_return_a_scoped_visual_without_failing_the_action(self) -> None:
        target = (
            None,
            {
                "node": {"role": "canvas"},
                "cdp": {"targetId": "page", "backendDOMNodeId": 42},
            },
        )
        patch_value = {"ref": "web:canvas", "sha256": "sha256:visual"}
        with patch.object(BRIDGE, "capture_visual_patch", return_value=patch_value):
            self.assertIs(
                BRIDGE.requested_action_visual_patch(True, "web:canvas", target),
                patch_value,
            )
        with patch.object(BRIDGE, "capture_visual_patch", side_effect=RuntimeError("gone")):
            self.assertIsNone(BRIDGE.requested_action_visual_patch(True, "web:canvas", target))
        self.assertIsNone(BRIDGE.requested_action_visual_patch(False, "web:canvas", target))
        self.assertIsNone(BRIDGE.requested_action_visual_patch(
            True,
            "web:button",
            (None, {"node": {"role": "button"}}),
        ))

    def test_realtime_step_captures_evidence_before_holding_the_clock(self) -> None:
        calls = []
        target = (None, {"node": {"role": "canvas"}})
        with (
            patch.object(BRIDGE.time, "sleep", return_value=None),
            patch.object(
                BRIDGE,
                "requested_action_visual_patch",
                side_effect=lambda *_args: calls.append("capture") or {"sha256": "visual"},
            ),
            patch.object(
                BRIDGE,
                "realtime_clock_hold",
                side_effect=lambda _page: calls.append("hold") or {"mode": "stepped"},
            ),
        ):
            visual, clock = BRIDGE.capture_then_hold_realtime(
                {"id": "page"},
                True,
                "web:canvas",
                target,
            )

        self.assertEqual(calls, ["capture", "hold"])
        self.assertEqual(visual, {"sha256": "visual"})
        self.assertEqual(clock, {"mode": "stepped"})

    def test_scoped_visual_patch_retains_known_target_outside_node_page(self) -> None:
        canvas = {
            "ref": "web:canvas",
            "parentRef": "app:browser",
            "appId": "browser",
            "role": "canvas",
            "name": "Game",
            "description": None,
            "value": None,
            "states": ["enabled"],
            "actions": [],
            "bounds": None,
            "sources": ["browser", "canvas_fingerprint"],
        }
        target = (None, {"node": canvas, "cdp": {"targetId": "page", "backendDOMNodeId": 42}})
        with (
            patch.object(BRIDGE, "cdp_semantic_nodes", return_value=([canvas], {"web:canvas": target})),
            patch.object(BRIDGE, "continuation_signing_key", return_value=b"k" * 32),
        ):
            snapshot, targets = BRIDGE.browser_snapshot(
                "computer-test",
                1,
                scope_ref="app:browser",
                retained_target_ref="web:canvas",
            )

        self.assertNotIn("web:canvas", {node["ref"] for node in snapshot["nodes"]})
        self.assertIs(targets["web:canvas"], target)

    def test_browser_effect_version_is_order_independent(self) -> None:
        first = BRIDGE.browser_effect_version("sha256:before", "state", {"page-b", "page-a"})
        second = BRIDGE.browser_effect_version("sha256:before", "state", {"page-a", "page-b"})
        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")

    def test_web_controls_expose_actions_from_accessible_roles(self) -> None:
        self.assertEqual(BRIDGE.cdp_node_actions("button", 42), ["focus", "invoke"])
        self.assertEqual(
            BRIDGE.cdp_node_actions("canvas", 42),
            ["focus", "invoke", "press_key", "input_sequence"],
        )
        self.assertEqual(BRIDGE.cdp_node_actions("entry", 42), ["focus", "set_text"])
        self.assertEqual(BRIDGE.cdp_node_actions("listbox", 42), ["focus", "set_text"])
        self.assertEqual(BRIDGE.cdp_node_actions("generic", 42, editable=True), ["focus", "set_text"])
        self.assertEqual(
            BRIDGE.cdp_node_actions("generic", 42, pointer_interactive=True),
            ["invoke"],
        )
        self.assertEqual(BRIDGE.cdp_node_actions("static", 42), [])
        self.assertEqual(BRIDGE.cdp_node_actions("document web", 42), [])
        self.assertEqual(BRIDGE.cdp_node_actions("checkbox", 42, disabled=True), [])

    def test_pointer_interaction_hint_is_bounded_and_keeps_coordinates_opaque(self) -> None:
        class FakeCdp:
            def call(self, method: str, params: dict | None = None) -> dict:
                self.method = method
                self.params = params
                return {
                    "result": {
                        "value": {
                            "visible": True,
                            "pointerBoundary": True,
                            "name": "Click anywhere to start",
                            "visual": "rgb(1,2,3)|10|20|30|40",
                            "visualRevision": 3,
                        }
                    }
                }

        cdp = FakeCdp()
        with patch.object(BRIDGE, "cdp_resolve_object", return_value="object"):
            hint = BRIDGE.cdp_dom_interaction_hint(cdp, 42)

        self.assertEqual(hint["name"], "Click anywhere to start")
        self.assertEqual(hint["visualRevision"], 3)
        self.assertEqual(cdp.method, "Runtime.callFunctionOn")
        self.assertNotIn("rect", hint)

    def test_control_name_prefers_accessibility_then_rendered_label(self) -> None:
        attributes = {"aria-label": "ARIA fallback", "name": "machine_name"}
        self.assertEqual(BRIDGE.semantic_control_name("Accessible name", attributes, "Rendered label"), "Accessible name")
        self.assertEqual(BRIDGE.semantic_control_name("", attributes, "Rendered label"), "Rendered label")
        self.assertEqual(BRIDGE.semantic_control_name("", attributes, ""), "ARIA fallback")

    def test_nested_browser_frames_keep_parent_identity(self) -> None:
        tree = {
            "frame": {"id": "main"},
            "childFrames": [
                {
                    "frame": {"id": "child"},
                    "childFrames": [{"frame": {"id": "grandchild"}}],
                }
            ],
        }
        self.assertEqual(
            BRIDGE.flatten_frame_tree(tree),
            [("main", None), ("child", "main"), ("grandchild", "child")],
        )

    def test_browser_frame_tree_excludes_cross_origin_descendants(self) -> None:
        tree = {
            "frame": {"id": "main", "url": "https://game.example/play"},
            "childFrames": [
                {"frame": {"id": "same", "url": "https://game.example/embed"}},
                {"frame": {"id": "ad", "url": "https://ads.example/frame"}},
                {"frame": {"id": "inherited", "url": "about:blank"}},
            ],
        }
        self.assertEqual(
            BRIDGE.flatten_frame_tree(tree, ("https", "game.example", None)),
            [("main", None), ("same", "main"), ("inherited", "main")],
        )

    def test_accessibility_parent_walk_skips_ignored_nodes(self) -> None:
        refs = {
            ("target", "frame", "root"): "web-root",
            ("target", "frame", "child"): "web-child",
        }
        raw_nodes = {
            ("target", "frame", "root"): {"nodeId": "root"},
            ("target", "frame", "ignored"): {"nodeId": "ignored", "parentId": "root", "ignored": True},
            ("target", "frame", "child"): {"nodeId": "child", "parentId": "ignored"},
        }
        self.assertEqual(
            BRIDGE.nearest_visible_parent_ref("target", "frame", "ignored", refs, raw_nodes),
            "web-root",
        )

    def test_cross_origin_frame_targets_follow_only_the_active_page(self) -> None:
        targets = [
            {"id": "child", "type": "iframe", "parentId": "page"},
            {"id": "grandchild", "type": "iframe", "parentId": "child"},
            {"id": "unrelated", "type": "iframe", "parentId": "other-page"},
        ]
        with patch.object(BRIDGE, "browser_debug_targets", return_value=targets):
            self.assertEqual(
                [target["id"] for target in BRIDGE.browser_frame_targets("page")],
                ["child", "grandchild"],
            )

    def test_selected_option_verification_is_scoped_to_its_control(self) -> None:
        nodes = [
            {"ref": "select-a", "parentRef": "document", "role": "combobox", "name": "Choice", "states": []},
            {"ref": "popup-a", "parentRef": "select-a", "role": "listbox", "name": "", "states": []},
            {"ref": "option-a", "parentRef": "popup-a", "role": "option", "name": "Second", "states": ["selected"]},
            {"ref": "option-b", "parentRef": "select-b", "role": "option", "name": "Other", "states": ["selected"]},
        ]
        self.assertTrue(BRIDGE.selected_option_matches(nodes, "select-a", "Second"))
        self.assertFalse(BRIDGE.selected_option_matches(nodes, "select-b", "Second"))

    def test_content_edit_verification_is_scoped_to_its_editor(self) -> None:
        nodes = [
            {"ref": "editor", "parentRef": "document", "role": "generic", "name": "Editor", "states": []},
            {"ref": "paragraph", "parentRef": "editor", "role": "paragraph", "name": "", "states": []},
            {"ref": "text", "parentRef": "paragraph", "role": "static", "name": "Saved draft", "states": []},
            {"ref": "outside", "parentRef": "document", "role": "static", "name": "Other text", "states": []},
        ]
        self.assertTrue(BRIDGE.editable_content_matches(nodes, "editor", "Saved draft"))
        self.assertFalse(BRIDGE.editable_content_matches(nodes, "editor", "Other text"))

    def test_chrome_tristate_values_are_normalized(self) -> None:
        self.assertTrue(BRIDGE.ax_state_is_true(True))
        self.assertTrue(BRIDGE.ax_state_is_true("true"))
        self.assertFalse(BRIDGE.ax_state_is_true(False))
        self.assertFalse(BRIDGE.ax_state_is_true("false"))
        self.assertFalse(BRIDGE.ax_state_is_true("mixed"))

    def test_search_queries_become_google_search_urls(self) -> None:
        self.assertEqual(
            BRIDGE.browser_navigation_target("Cửu Âm Chân Kinh"),
            "https://www.google.com/search?q=C%E1%BB%ADu+%C3%82m+Ch%C3%A2n+Kinh",
        )

    def test_http_urls_are_preserved(self) -> None:
        target = "https://example.com/game?q=neko"
        self.assertEqual(BRIDGE.browser_navigation_target(target), target)

    def test_blank_navigation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BRIDGE.browser_navigation_target("   ")

    def test_wechat_launcher_enables_qt_accessibility_without_mutating_the_host_environment(self) -> None:
        launcher = dict(BRIDGE.OPTIONAL_APP_LAUNCHERS[0])
        with patch.object(BRIDGE.subprocess, "Popen") as popen:
            BRIDGE.launch_application(launcher)

        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["QT_LINUX_ACCESSIBILITY_ALWAYS_ON"], "1")
        self.assertNotIn("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", BRIDGE.os.environ)

    def test_browser_launch_keeps_navigation_out_of_command_options(self) -> None:
        launcher = BRIDGE.CORE_APP_LAUNCHERS[0]
        target = "https://example.com/?query=--user-data-dir%3D/tmp/other"
        with patch.object(BRIDGE.subprocess, "Popen") as popen:
            BRIDGE.launch_application(launcher, target)
        self.assertEqual(popen.call_args.args[0], ("wiii-browser", "--", target))

    def test_browser_launch_rejects_command_flags_and_active_scheme_targets(self) -> None:
        launcher = BRIDGE.CORE_APP_LAUNCHERS[0]
        for target in ("--user-data-dir=/tmp/other", "javascript:alert(1)", "file:///etc/passwd"):
            with self.subTest(target=target), patch.object(BRIDGE.subprocess, "Popen") as popen:
                with self.assertRaises(ValueError):
                    BRIDGE.launch_application(launcher, target)
                popen.assert_not_called()

    def test_wechat_launcher_uses_a_stable_application_identity(self) -> None:
        launcher = BRIDGE.OPTIONAL_APP_LAUNCHERS[0]

        self.assertEqual(Path(launcher["argv"][0]).name, "AppRun")
        self.assertEqual(Path(launcher["argv"][0]).parent.name, "runtime")
        self.assertEqual(launcher["requiredPath"], launcher["argv"][0])
        self.assertIn("wechat", launcher["processNames"])
        self.assertNotIn("apprun", tuple(term.casefold() for term in launcher["matchTerms"]))

    def test_busy_browser_page_is_replaced_without_leaking_the_old_target(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                calls.append((method, params))
                if method == "Page.navigate":
                    return {"errorText": "net::ERR_ABORTED"}
                if method == "Target.createTarget":
                    return {"targetId": "replacement-page"}
                return {}

        page = {"id": "busy-page", "webSocketDebuggerUrl": "ws://example.invalid"}
        with (
            patch.object(BRIDGE, "active_browser_page", return_value=page),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE, "browser_page_state", return_value={"pageId": "busy-page"}),
            patch.object(BRIDGE, "wait_for_browser_navigation", side_effect=[False, True]),
            patch.object(BRIDGE, "create_browser_target", return_value="replacement-page") as create,
            patch.object(BRIDGE, "browser_page_target", return_value=page),
            patch.object(BRIDGE, "close_browser_target") as close,
        ):
            BRIDGE.navigate_browser("https://example.com/")

        create.assert_called_once_with("about:blank")
        close.assert_called_once_with("busy-page")

    def test_replacement_target_uses_the_browser_control_socket(self) -> None:
        control = {"webSocketDebuggerUrl": "ws://browser.invalid"}

        class FakeControl:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, params: dict | None = None) -> dict:
                self.method = method
                self.params = params
                return {"targetId": "replacement-page"}

        connection = FakeControl()
        with (
            patch.object(BRIDGE, "browser_control_target", return_value=control),
            patch.object(BRIDGE, "CdpConnection", return_value=connection) as connect,
        ):
            target_id = BRIDGE.create_browser_target("https://example.com/")

        self.assertEqual(target_id, "replacement-page")
        connect.assert_called_once_with(control, timeout=3.0)
        self.assertEqual(connection.method, "Target.createTarget")
        self.assertEqual(connection.params, {"url": "https://example.com/"})

    def test_replacement_navigation_keeps_the_exact_target_for_readback(self) -> None:
        page = {"id": "busy-page", "webSocketDebuggerUrl": "ws://page.invalid"}

        class BusyCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, _method: str, _params: dict | None = None) -> dict:
                raise TimeoutError("busy renderer timed out")

        with (
            patch.object(BRIDGE, "active_browser_page", return_value=page),
            patch.object(BRIDGE, "CdpConnection", return_value=BusyCdp()),
            patch.object(BRIDGE, "replace_browser_page", return_value="replacement-page"),
        ):
            receipt = BRIDGE.navigate_browser("https://example.com/")

        self.assertEqual(receipt["navigationTargetId"], "replacement-page")

    def test_busy_replacement_releases_the_unresponsive_page_before_allocation(self) -> None:
        calls: list[tuple[str, str]] = []

        with (
            patch.object(
                BRIDGE,
                "close_browser_target",
                side_effect=lambda target_id: calls.append(("close", target_id)),
            ),
            patch.object(
                BRIDGE,
                "create_browser_target",
                side_effect=lambda target: (
                    calls.append(("create", target)) or "replacement-page"
                ),
            ),
            patch.object(BRIDGE, "browser_page_target", return_value={"id": "replacement-page"}),
            patch.object(BRIDGE, "CdpConnection") as connection,
            patch.object(BRIDGE, "wait_for_browser_navigation", return_value=True),
            patch.object(BRIDGE, "close_browser_origin_pages"),
        ):
            connection.return_value.__enter__.return_value.call.return_value = {}
            replacement = BRIDGE.replace_browser_page(
                "https://example.com/",
                "busy-page",
                release_busy_target=True,
            )

        self.assertEqual(replacement, "replacement-page")
        self.assertEqual(calls[:2], [("close", "busy-page"), ("create", "about:blank")])

    def test_navigation_uses_the_last_owned_target_when_discovery_is_busy(self) -> None:
        previous = {"id": "owned-page", "webSocketDebuggerUrl": "ws://page.invalid"}

        class BusyCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, _method: str, _params: dict | None = None) -> dict:
                raise TimeoutError("busy renderer timed out")

        with (
            patch.object(BRIDGE, "active_browser_page", side_effect=TimeoutError("busy discovery")),
            patch.object(BRIDGE, "known_active_browser_page", return_value=previous),
            patch.object(BRIDGE, "CdpConnection", return_value=BusyCdp()),
            patch.object(BRIDGE, "replace_browser_page", return_value="replacement-page") as replace,
        ):
            receipt = BRIDGE.navigate_browser("https://example.com/")

        replace.assert_called_once_with(
            "https://example.com/",
            "owned-page",
            release_busy_target=True,
            release_origin=None,
        )
        self.assertEqual(receipt["navigationTargetId"], "replacement-page")

    def test_targeted_navigation_readback_does_not_enumerate_busy_targets(self) -> None:
        target = {"id": "replacement-page", "webSocketDebuggerUrl": "ws://page.invalid"}
        state = {
            "pageId": "replacement-page",
            "url": "https://example.com/",
            "ready": "complete",
            "timeOrigin": 20,
        }
        with (
            patch.object(BRIDGE, "browser_page_target", return_value=target) as select,
            patch.object(BRIDGE, "browser_pages") as enumerate_pages,
            patch.object(BRIDGE, "browser_page_state", return_value=state),
        ):
            completed = BRIDGE.browser_navigation_completed(
                "https://example.com/",
                None,
                "replacement-page",
            )

        self.assertTrue(completed)
        select.assert_called_once_with("replacement-page")
        enumerate_pages.assert_not_called()

    def test_busy_origin_cleanup_preserves_the_replacement_and_other_origins(self) -> None:
        pages = [
            {"id": "replacement", "url": "https://example.com/clean"},
            {"id": "ad-heavy", "url": "https://play2048.co/classic"},
            {"id": "popup", "url": "https://play2048.co/popup"},
            {"id": "research", "url": "https://www.iana.org/help/example-domains"},
        ]
        with (
            patch.object(BRIDGE, "browser_control_pages", return_value=pages),
            patch.object(BRIDGE, "close_browser_target") as close,
        ):
            BRIDGE.close_browser_origin_pages(
                BRIDGE.url_origin("https://play2048.co"),
                "replacement",
            )

        self.assertEqual(
            [call.args[0] for call in close.call_args_list],
            ["ad-heavy", "popup"],
        )

    def test_browser_observation_cache_retains_an_isolated_action_locator(self) -> None:
        snapshot = {"stateVersion": "sha256:" + "a" * 64, "nodes": []}
        target = (
            None,
            {
                "node": {"ref": "web-control", "role": "button", "name": "Run"},
                "interfaces": {},
                "cdp": {"targetId": "page", "frameId": "page", "backendDOMNodeId": 42},
            },
        )
        with BRIDGE.BROWSER_OBSERVATION_LOCK:
            BRIDGE.BROWSER_OBSERVATIONS.clear()
        try:
            BRIDGE.remember_browser_observation(
                "computer-test",
                snapshot,
                {"web-control": target},
            )
            first = BRIDGE.cached_browser_target_observation(
                "computer-test",
                snapshot["stateVersion"],
                "web-control",
            )
            self.assertIsNotNone(first)
            first[1]["web-control"][1]["node"]["name"] = "Changed"
            second = BRIDGE.cached_browser_target_observation(
                "computer-test",
                snapshot["stateVersion"],
                "web-control",
            )
            self.assertEqual(second[1]["web-control"][1]["node"]["name"], "Run")
        finally:
            with BRIDGE.BROWSER_OBSERVATION_LOCK:
                BRIDGE.BROWSER_OBSERVATIONS.clear()

    def test_unresponsive_page_uses_browser_control_target_for_recovery(self) -> None:
        class BusyCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, _method: str, _params: dict | None = None) -> dict:
                raise TimeoutError("busy renderer timed out")

        page = {"id": "busy-page", "webSocketDebuggerUrl": "ws://page.invalid"}

        with (
            patch.object(BRIDGE, "active_browser_page", return_value=page),
            patch.object(BRIDGE, "browser_page_state", return_value={"pageId": "busy-page"}),
            patch.object(BRIDGE, "CdpConnection", return_value=BusyCdp()),
            patch.object(BRIDGE, "wait_for_browser_navigation", return_value=True),
            patch.object(BRIDGE, "create_browser_target", return_value="replacement-page") as create,
            patch.object(BRIDGE, "browser_page_target", return_value=page),
            patch.object(BRIDGE, "close_browser_target") as close,
        ):
            BRIDGE.navigate_browser("https://example.com/")

        create.assert_called_once_with("about:blank")
        close.assert_called_once_with("busy-page")

    def test_aborted_navigation_that_lands_at_target_does_not_retry(self) -> None:
        calls: list[str] = []

        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, method: str, _params: dict | None = None) -> dict:
                calls.append(method)
                return {"errorText": "net::ERR_ABORTED"} if method == "Page.navigate" else {}

        page = {"id": "page", "webSocketDebuggerUrl": "ws://example.invalid"}
        with (
            patch.object(BRIDGE, "active_browser_page", return_value=page),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
            patch.object(BRIDGE, "browser_page_state", return_value={"pageId": "page"}) as page_state,
            patch.object(BRIDGE, "wait_for_browser_navigation", return_value=True),
        ):
            BRIDGE.navigate_browser("https://example.com/")

        self.assertNotIn("Target.createTarget", calls)
        page_state.assert_not_called()

    def test_single_browser_page_does_not_open_a_probe_connection(self) -> None:
        page = {"id": "only-page", "webSocketDebuggerUrl": "ws://example.invalid"}
        with (
            patch.object(BRIDGE, "browser_pages", return_value=[page]),
            patch.object(BRIDGE, "CdpConnection") as connection,
        ):
            self.assertEqual(BRIDGE.active_browser_page(), page)

        connection.assert_not_called()

    def test_unapproved_redirect_is_not_verified_by_a_new_document_identity(self) -> None:
        class FakeCdp:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def call(self, _method: str, _params: dict | None = None) -> dict:
                return {"result": {"value": {"url": "https://httpbin.org/get", "ready": "complete", "timeOrigin": 20}}}

        page = {
            "id": "redirected-page",
            "url": "https://httpbin.org/get",
            "webSocketDebuggerUrl": "ws://example.invalid",
        }
        with (
            patch.object(BRIDGE, "browser_pages", return_value=[page]),
            patch.object(BRIDGE, "active_browser_page", return_value=page),
            patch.object(BRIDGE, "CdpConnection", return_value=FakeCdp()),
        ):
            self.assertFalse(
                BRIDGE.browser_navigation_completed(
                    "https://httpbin.org/redirect/2",
                    {"pageId": "redirected-page", "url": "https://example.com/", "ready": "complete", "timeOrigin": 10},
                )
            )

    def test_target_url_is_not_verified_before_document_is_ready(self) -> None:
        state = {"pageId": "page", "url": "https://example.com/", "ready": "loading", "timeOrigin": 20}
        with patch.object(BRIDGE, "browser_page_state", return_value=state):
            self.assertFalse(BRIDGE.browser_navigation_completed("https://example.com/", None))

    def test_blank_replacement_page_never_verifies_web_navigation(self) -> None:
        state = {"pageId": "page", "url": "about:blank", "ready": "complete", "timeOrigin": 20}
        with (
            patch.object(BRIDGE, "browser_page_target", return_value={"id": "page"}),
            patch.object(BRIDGE, "browser_page_state", return_value=state),
        ):
            self.assertFalse(
                BRIDGE.browser_navigation_completed(
                    "https://example.com/",
                    None,
                    "page",
                )
            )

    def test_unrelated_unchanged_page_does_not_verify_redirect(self) -> None:
        state = {"pageId": "page", "url": "https://example.com/", "ready": "complete", "timeOrigin": 10}
        with (
            patch.object(BRIDGE, "browser_reached_target", return_value=False),
            patch.object(BRIDGE, "browser_page_state", return_value=state),
        ):
            self.assertFalse(BRIDGE.browser_navigation_completed("https://example.invalid/", dict(state)))

    def test_native_protected_fields_omit_content_from_observation(self) -> None:
        entry = MagicMock()
        entry.getRoleName.return_value = "entry"
        entry.name = "API token"
        entry.description = "private-description-fixture"
        entry.childCount = 0
        atspi = MagicMock()
        atspi.Registry.getDesktop.return_value = entry
        with (
            patch.object(BRIDGE, "require_atspi"),
            patch.object(BRIDGE, "pyatspi", atspi),
            patch.object(BRIDGE, "project_file_nodes", return_value=[]),
            patch.object(BRIDGE, "state_names", return_value=["editable"]),
            patch.object(BRIDGE, "node_value", return_value="private-value-fixture"),
            patch.object(BRIDGE, "normalized_actions", return_value=(["focus", "set_text"], {"set_text": entry})),
            patch.object(BRIDGE, "node_bounds", return_value=None),
            patch.object(BRIDGE, "accessibility_object_identity", return_value="entry-1"),
        ):
            snapshot, targets = BRIDGE.observe("computer-test", 100, native_only=True)
        node = next(node for node in snapshot["nodes"] if node["name"] == "API token")
        self.assertIn("protected", node["states"])
        self.assertNotIn("set_text", node["actions"])
        self.assertNotIn("set_text", targets[node["ref"]][1]["interfaces"])
        self.assertIsNone(node["value"])
        self.assertIsNone(node["description"])
        self.assertNotIn("private-value-fixture", json.dumps(snapshot))
        self.assertNotIn("private-description-fixture", json.dumps(snapshot))

    def test_sensitive_dom_fields_are_read_only_to_the_agent(self) -> None:
        self.assertTrue(BRIDGE.is_sensitive_field("Password", {}, {"type": "password"}))
        self.assertTrue(BRIDGE.is_sensitive_field("Verification", {}, {"autocomplete": "one-time-code"}))
        self.assertTrue(BRIDGE.is_sensitive_field("API token", {}, {"type": "text"}))
        self.assertFalse(BRIDGE.is_sensitive_field("Project title", {}, {"type": "text"}))
        self.assertTrue(BRIDGE.is_sensitive_accessibility_field("password text", "Password", None))
        self.assertTrue(BRIDGE.is_sensitive_accessibility_field("entry", "OTP", "Verification"))
        self.assertFalse(BRIDGE.is_sensitive_accessibility_field("entry", "Account", None))

    def test_web_controls_are_prioritized_ahead_of_static_text(self) -> None:
        static = {"role": "static", "states": [], "actions": []}
        link = {"role": "link", "states": [], "actions": ["focus", "invoke"]}
        heading = {"role": "heading", "states": [], "actions": []}
        document = {"role": "document web", "states": ["focused"], "actions": ["focus"]}
        self.assertEqual(sorted([static, heading, link, document], key=BRIDGE.web_node_priority), [document, link, heading, static])

    def test_dynamic_ref_fingerprints_the_target_precondition(self) -> None:
        node = {
            "parentRef": "window-browser",
            "appId": "Google Chrome",
            "role": "entry",
            "name": "Address and search bar",
            "value": "",
            "states": ["editable", "focused"],
            "actions": ["focus", "set_text"],
        }
        original = BRIDGE.semantic_node_ref(42, node)
        self.assertEqual(original, BRIDGE.semantic_node_ref(42, dict(node)))
        self.assertNotEqual(original, BRIDGE.semantic_node_ref(42, {**node, "value": "changed"}))
        self.assertEqual(original, BRIDGE.semantic_node_ref(42, {**node, "states": ["editable"]}))
        self.assertEqual(original, BRIDGE.semantic_node_ref(42, {**node, "actions": ["focus"]}))

    def test_native_ref_tracks_atspi_identity_across_mutable_content(self) -> None:
        node = {
            "parentRef": "window-wechat",
            "appId": "wechat",
            "role": "text",
            "name": "Message",
            "value": "before",
            "states": ["editable"],
            "actions": ["set_text"],
        }
        identity = "447:/org/a11y/atspi/accessible/2147483878"
        original = BRIDGE.semantic_node_ref(1, node, identity)

        self.assertEqual(original, BRIDGE.semantic_node_ref(2, {**node, "value": "after"}, identity))
        self.assertNotEqual(original, BRIDGE.semantic_node_ref(1, node, identity + "9"))

    def test_web_ref_tracks_dom_identity_not_mutable_visual_state(self) -> None:
        original = BRIDGE.web_node_ref("page", "frame", "node", 42)
        self.assertEqual(original, BRIDGE.web_node_ref("page", "frame", "node", 42))
        self.assertNotEqual(original, BRIDGE.web_node_ref("page", "frame", "node", 43))

    def test_stale_snapshot_cannot_authorize_a_same_named_target(self) -> None:
        class Editable:
            value = ""

            def setTextContents(self, value: str) -> None:
                self.value = value

        editable = Editable()
        before_node = {
            "ref": "ui-0042",
            "parentRef": "ui-0003",
            "appId": "Google Chrome",
            "role": "entry",
            "name": "Address and search bar",
            "description": None,
            "value": "",
            "states": ["editable", "focused"],
            "actions": ["focus", "set_text"],
            "bounds": None,
        }
        after_node = {**before_node, "value": "Cửu Âm Chân Kinh"}
        snapshots = [
            (
                {"stateVersion": "sha256:changed-elsewhere"},
                {"ui-0042": (object(), {"node": before_node, "interfaces": {"set_text": editable}})},
            ),
            (
                {"stateVersion": "sha256:after-action", "nodes": [after_node]},
                {"ui-0042": (object(), {"node": after_node, "interfaces": {"set_text": editable}})},
            ),
        ]
        request = {
            "requestId": "target-precondition-test",
            "environmentId": "computer-test",
            "leaseId": "lease-test",
            "stateVersion": "sha256:observed-before-unrelated-change",
            "targetRef": "ui-0042",
            "expectedRole": "entry",
            "expectedName": "Address and search bar",
            "action": "set_text",
            "text": "Cửu Âm Chân Kinh",
        }

        with patch.object(BRIDGE, "observe", side_effect=snapshots), patch.object(BRIDGE.time, "sleep"):
            result = BRIDGE.act(request)

        self.assertEqual(result["result"]["outcome"], "rejected")
        self.assertEqual(result["result"]["code"], "semantic_stale_snapshot")
        self.assertEqual(editable.value, "")

    def test_changed_target_still_fails_closed(self) -> None:
        changed_node = {
            "ref": "ui-0042",
            "parentRef": "ui-0003",
            "appId": "Google Chrome",
            "role": "entry",
            "name": "Different field",
            "description": None,
            "value": "",
            "states": ["editable", "focused"],
            "actions": ["set_text"],
            "bounds": None,
        }
        current = (
            {"stateVersion": "sha256:changed-target"},
            {"ui-0042": (object(), {"node": changed_node, "interfaces": {}})},
        )
        request = {
            "requestId": "changed-target-test",
            "environmentId": "computer-test",
            "leaseId": "lease-test",
            "stateVersion": "sha256:old",
            "targetRef": "ui-0042",
            "expectedRole": "entry",
            "expectedName": "Address and search bar",
            "action": "set_text",
            "text": "Cửu Âm Chân Kinh",
        }

        with patch.object(BRIDGE, "observe", return_value=current):
            result = BRIDGE.act(request)

        self.assertEqual(result["result"]["outcome"], "rejected")
        self.assertEqual(result["result"]["code"], "semantic_stale_snapshot")
        self.assertEqual(result["result"]["effect"], "refused")
        self.assertEqual(result["result"]["escalation"], "observe")


if __name__ == "__main__":
    unittest.main()
