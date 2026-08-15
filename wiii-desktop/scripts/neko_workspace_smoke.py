"""Headless browser smoke test for the Neko Chill workspace shell."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:1420")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def seed_browser_state(page, workspace_path: str) -> None:
    now = 1_786_684_800_000
    entry = {
        "v": 2,
        "id": "workspace-smoke",
        "agentId": "neko",
        "agentName": "Neko Core",
        "title": "Kiểm tra Workspace thời gian thực",
        "createdAt": now,
        "updatedAt": now + 1000,
        "workspace": {"path": workspace_path, "name": "wiii-desktop"},
        "launchProfile": {
            "id": "chatgpt",
            "provider": "chatgpt",
            "model": "gpt-5.6-sol",
            "active": True,
        },
        "controls": [
            {
                "id": "model",
                "label": "Model",
                "category": "model",
                "kind": "select",
                "currentValue": "gpt-5.6-sol",
                "choices": [
                    {"value": "gpt-5.6-sol", "label": "GPT-5.6 Sol"},
                    {"value": "gpt-5.6-luna", "label": "GPT-5.6 Luna"},
                ],
            }
        ],
        "commands": [{"name": "review", "description": "Rà soát thay đổi hiện tại"}],
    }
    events = [
        {
            "v": 1,
            "eventId": "event-context",
            "seq": 1,
            "at": now,
            "visibility": "model",
            "data": {
                "type": "session-context",
                "source": "created",
                "agentId": "neko",
                "workspacePath": workspace_path,
                "launchProfileId": "chatgpt",
            },
        },
        {
            "v": 1,
            "eventId": "event-input",
            "seq": 2,
            "at": now + 1,
            "visibility": "model",
            "data": {
                "type": "model-input",
                "source": "live",
                "messageId": "message-user",
                "text": "Rà soát và cải thiện workspace này.",
                "providerInstanceId": "runtime-smoke",
            },
        },
        {
            "v": 1,
            "eventId": "event-activity",
            "seq": 3,
            "at": now + 2,
            "visibility": "runtime",
            "data": {
                "type": "workspace-activity",
                "activityId": "activity-app",
                "title": "Update src/App.tsx",
                "status": "completed",
                "operation": "update",
                "locations": [{"path": f"{workspace_path}/src/App.tsx", "line": 180}],
                "toolName": "write_file",
                "detail": "Bootstrap flow updated",
            },
        },
    ]
    transcript = {
        "v": 2,
        "messages": [
            {"id": "message-user", "role": "user", "text": "Rà soát và cải thiện workspace này."},
            {
                "id": "message-assistant",
                "role": "assistant",
                "blocks": [
                    {
                        "id": "thinking-1",
                        "type": "thinking",
                        "content": "**Đang kiểm tra luồng workspace**",
                        "toolCalls": [],
                    },
                    {
                        "id": "tool-1",
                        "type": "tool_execution",
                        "status": "completed",
                        "tool": {
                            "id": "call-1",
                            "name": "write_file",
                            "result": "Updated src/App.tsx",
                        },
                    },
                    {
                        "id": "answer-1",
                        "type": "answer",
                        "content": "Đã hợp nhất **Files**, **Changes** và preview vào một Workspace có thể ghim.",
                    },
                ],
            },
        ],
        "events": events,
        "eventHighWaterMark": 3,
        "entry": entry,
    }
    payload = json.dumps({"entry": entry, "transcript": transcript}, ensure_ascii=False)
    init_script = """
        (() => {
          const { entry, transcript } = __PAYLOAD__;
          localStorage.clear();
          localStorage.setItem('wiii:neko-chill-mode.json', JSON.stringify({ mode: 'neko-chill' }));
          localStorage.setItem('wiii:neko-chill-sessions.json', JSON.stringify({
            'session-ids': [entry.id],
            index: [entry],
            [`session:${entry.id}`]: transcript,
          }));
        })();
        """.replace("__PAYLOAD__", payload)
    page.add_init_script(init_script)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = str(Path.cwd().resolve()).replace("\\", "/")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        seed_browser_state(page, workspace_path)
        # Vite keeps development channels alive; DOM readiness is the stable
        # boundary and the first semantic locator below gates app hydration.
        page.goto(args.base_url, wait_until="domcontentloaded", timeout=60_000)

        page.get_by_role("button", name="Mở phiên Kiểm tra Workspace thời gian thực").click()
        page.get_by_role("heading", name="Kiểm tra Workspace thời gian thực").wait_for()
        page.get_by_role("button", name="Mở workspace").click()
        pane = page.get_by_test_id("neko-workspace-pane")
        pane.wait_for()
        assert page.get_by_role("button", name="Theo agent").get_attribute("aria-pressed") == "true"
        page.get_by_role("button", name="Ghim nội dung").click()
        assert page.get_by_role("button", name="Ghim nội dung").get_attribute("aria-pressed") == "true"
        page.get_by_role("button", name="Changes 0").click()
        assert page.get_by_role("button", name="Changes 0").get_attribute("aria-pressed") == "true"
        page.screenshot(path=str(output_dir / "neko-workspace-desktop.png"), full_page=True)

        page.keyboard.press("Escape")
        pane.wait_for(state="detached")
        page.set_viewport_size({"width": 900, "height": 700})
        page.get_by_role("button", name="Mở workspace").click()
        pane.wait_for()
        page.get_by_test_id("session-sidebar").wait_for(state="detached")
        page.screenshot(path=str(output_dir / "neko-workspace-compact.png"), full_page=True)
        page.get_by_role("button", name="Đóng workspace").click()
        pane.wait_for(state="detached")

        result = {
            "desktop_workspace": True,
            "compact_workspace": True,
            "escape_close": True,
            "explicit_close": True,
            "page_errors": page_errors,
        }
        (output_dir / "neko-workspace-smoke.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        browser.close()

    if page_errors:
        raise AssertionError(f"Uncaught browser errors: {page_errors}")


if __name__ == "__main__":
    main()
