"""Product smoke for the Wiii Pointy LMS host contract.

This smoke intentionally requires credentials and target course IDs via env vars.
Do not hard-code production credentials in this file.

Required env:
  LMS_TEACHER_EMAIL
  LMS_TEACHER_PASSWORD
  LMS_COURSE_ID
  LMS_CHAPTER_ID
  LMS_LESSON_ID

Optional env:
  LMS_BASE_URL=https://holilihu.online
  WIII_EMBED_ORIGIN=https://wiii.holilihu.online
  WIII_PRODUCT_SMOKE_OUT_DIR=artifacts/product-smoke
  WIII_PRODUCT_SMOKE_HEADLESS=1
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Frame, Page, sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


LMS_BASE_URL = os.getenv("LMS_BASE_URL", "https://holilihu.online").rstrip("/")
WIII_EMBED_ORIGIN = os.getenv("WIII_EMBED_ORIGIN", "https://wiii.holilihu.online").rstrip("/")
OUT_DIR = Path(os.getenv("WIII_PRODUCT_SMOKE_OUT_DIR", "artifacts/product-smoke"))
HEADLESS = os.getenv("WIII_PRODUCT_SMOKE_HEADLESS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TEACHER_EMAIL = required_env("LMS_TEACHER_EMAIL")
TEACHER_PASSWORD = required_env("LMS_TEACHER_PASSWORD")
COURSE_ID = required_env("LMS_COURSE_ID")
CHAPTER_ID = required_env("LMS_CHAPTER_ID")
LESSON_ID = required_env("LMS_LESSON_ID")


def step(report: dict[str, Any], name: str, ok: bool = True, **data: Any) -> None:
    payload = {"name": name, "ok": ok, **data}
    report.setdefault("steps", []).append(payload)
    if not ok:
        report.setdefault("errors", []).append(payload)
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def screenshot(page: Page, name: str) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def login(page: Page, report: dict[str, Any]) -> None:
    page.goto(f"{LMS_BASE_URL}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    screenshot(page, "pointy-contract-01-login.png")

    if "/teacher/" in page.url:
        step(report, "already_logged_in", url=page.url)
        return

    email = page.locator(
        "input[type='email'], input[name='email'], input[autocomplete='username']",
    ).first
    password = page.locator(
        "input[type='password'], input[name='password'], input[autocomplete='current-password']",
    ).first
    if not email.is_visible(timeout=1500):
        for selector in [
            "a:has-text('Đăng nhập')",
            "button:has-text('Đăng nhập')",
            "button:has-text('Tiếp tục với email')",
            "button:has-text('Email')",
        ]:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=800):
                locator.click()
                break
        page.wait_for_timeout(1500)
        screenshot(page, "pointy-contract-01b-login-form.png")

    email.wait_for(state="visible", timeout=15_000)
    email.fill(TEACHER_EMAIL)

    if not password.is_visible(timeout=1000):
        page.locator("button[type='submit']").first.click()
        password.wait_for(state="visible", timeout=15_000)
    password.fill(TEACHER_PASSWORD)
    page.locator("button[type='submit']").first.click()
    page.wait_for_url(re.compile(r"/teacher/"), timeout=30_000)
    page.wait_for_timeout(2500)
    screenshot(page, "pointy-contract-02-after-login.png")
    step(report, "login_ok", url=page.url)


def inventory(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-wiii-id]')).map((el) => ({
          id: el.getAttribute('data-wiii-id') || '',
          tag: el.tagName.toLowerCase(),
          text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '')
            .trim().replace(/\\s+/g, ' ').slice(0, 160),
          safe: el.getAttribute('data-wiii-click-safe'),
          kind: el.getAttribute('data-wiii-click-kind'),
          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
          disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
        }))"""
    )


def has_id(items: list[dict[str, Any]], target_id: str) -> bool:
    return any(item.get("id") == target_id for item in items)


def get_item(items: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("id") == target_id), None)


def require_ids(
    report: dict[str, Any],
    name: str,
    items: list[dict[str, Any]],
    required_ids: list[str],
) -> None:
    missing = [target_id for target_id in required_ids if not has_id(items, target_id)]
    step(
        report,
        name,
        ok=not missing,
        required_ids=required_ids,
        missing_ids=missing,
        inventory_count=len(items),
    )


def require_safe_ids(
    report: dict[str, Any],
    name: str,
    items: list[dict[str, Any]],
    required_ids: list[str],
) -> None:
    bad: list[dict[str, Any]] = []
    for target_id in required_ids:
        item = get_item(items, target_id)
        if not item or item.get("safe") != "true" or not item.get("visible"):
            bad.append({"id": target_id, "item": item})
    step(report, name, ok=not bad, bad=bad)


def require_unsafe_mutations(report: dict[str, Any], items: list[dict[str, Any]]) -> None:
    dangerous_exact = {"open-publish-menu", "save-lesson"}
    dangerous_prefixes = ("delete-section-",)
    dangerous_safe = [
        item
        for item in items
        if item.get("safe") == "true"
        and (
            item.get("id") in dangerous_exact
            or any(str(item.get("id", "")).startswith(prefix) for prefix in dangerous_prefixes)
        )
    ]
    step(
        report,
        "unsafe_mutations_not_safe_clickable",
        ok=not dangerous_safe,
        dangerous_safe=dangerous_safe,
    )


def get_wiii_frame(page: Page) -> Frame:
    deadline = time.time() + 40
    last_urls: list[str] = []
    while time.time() < deadline:
        for frame in page.frames:
            if frame.url.startswith(f"{WIII_EMBED_ORIGIN}/embed"):
                return frame
        last_urls = [frame.url for frame in page.frames]
        page.wait_for_timeout(500)
    raise RuntimeError(f"Wiii iframe not found. frames={last_urls}")


def open_wiii_frame(page: Page, report: dict[str, Any]) -> Frame:
    opener = page.locator("[data-wiii-id='open-wiii-widget']").first
    if opener.count() and opener.is_visible(timeout=1000):
        opener.click()
        page.wait_for_timeout(1200)

    frame = get_wiii_frame(page)
    frame_url = re.sub(r"token=[^&]+", "token=<redacted>", frame.url)
    step(report, "wiii_frame_found", frame_url=frame_url)
    return frame


def send_pointy_action(
    frame: Frame,
    action: str,
    params: dict[str, Any],
    timeout_ms: int = 7000,
) -> dict[str, Any]:
    return frame.evaluate(
        """async ({ action, params, timeoutMs }) => {
          const id = `smoke-${Date.now()}-${Math.random().toString(16).slice(2)}`;
          return await new Promise((resolve) => {
            const timer = setTimeout(() => {
              window.removeEventListener('message', onMessage);
              resolve({ success: false, error: 'pointy_response_timeout', id });
            }, timeoutMs);
            function onMessage(event) {
              if (event.data && event.data.type === 'wiii:action-response' && event.data.id === id) {
                clearTimeout(timer);
                window.removeEventListener('message', onMessage);
                resolve(event.data.result || event.data);
              }
            }
            window.addEventListener('message', onMessage);
            window.parent.postMessage({ type: 'wiii:action-request', id, action, params }, '*');
          });
        }""",
        {"action": action, "params": params, "timeoutMs": timeout_ms},
    )


def assert_pointy_result(
    report: dict[str, Any],
    name: str,
    result: dict[str, Any],
    expected_success: bool,
    expected_error_prefix: str | None = None,
) -> None:
    success = bool(result.get("success"))
    error = str(result.get("error", ""))
    ok = success is expected_success
    if expected_error_prefix:
        ok = ok and error.startswith(expected_error_prefix)
    step(report, name, ok=ok, result=result)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "base_url": LMS_BASE_URL,
        "wiii_embed_origin": WIII_EMBED_ORIGIN,
        "course_id": COURSE_ID,
        "chapter_id": CHAPTER_ID,
        "lesson_id": LESSON_ID,
        "steps": [],
        "errors": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        try:
            login(page, report)

            dashboard_url = f"{LMS_BASE_URL}/teacher/courses"
            page.goto(dashboard_url, wait_until="domcontentloaded")
            page.locator("body").wait_for(state="visible", timeout=15_000)
            page.wait_for_timeout(2500)
            dashboard_inventory = inventory(page)
            screenshot(page, "pointy-contract-03-dashboard.png")
            require_ids(
                report,
                "dashboard_required_targets",
                dashboard_inventory,
                [
                    "teacher-dashboard",
                    "create-course",
                    f"open-course-editor-{COURSE_ID}",
                ],
            )
            require_safe_ids(
                report,
                "dashboard_safe_navigation_targets",
                dashboard_inventory,
                ["create-course", f"open-course-editor-{COURSE_ID}"],
            )

            editor_url = (
                f"{LMS_BASE_URL}/teacher/courses/{COURSE_ID}/editor/curriculum"
                f"?chapterId={CHAPTER_ID}&lessonId={LESSON_ID}"
            )
            page.goto(editor_url, wait_until="domcontentloaded")
            page.locator("body").wait_for(state="visible", timeout=15_000)
            page.wait_for_timeout(3500)
            editor_inventory = inventory(page)
            screenshot(page, "pointy-contract-04-editor.png")
            require_ids(
                report,
                "editor_required_targets",
                editor_inventory,
                [
                    "course-editor-shell",
                    "course-editor-sidebar",
                    "lesson-editor",
                    "lesson-title-input",
                    "open-publish-menu",
                    "save-lesson",
                    "open-wiii-widget",
                    f"select-chapter-{CHAPTER_ID}",
                    f"select-lesson-{LESSON_ID}",
                ],
            )
            require_safe_ids(
                report,
                "editor_safe_navigation_targets",
                editor_inventory,
                [
                    "back-to-courses",
                    "course-editor-tab-info",
                    "course-editor-tab-curriculum",
                    f"select-chapter-{CHAPTER_ID}",
                    f"select-lesson-{LESSON_ID}",
                    "open-wiii-widget",
                ],
            )
            require_unsafe_mutations(report, editor_inventory)

            frame = open_wiii_frame(page, report)
            assert_pointy_result(
                report,
                "pointy_highlight_lesson_editor",
                send_pointy_action(
                    frame,
                    "ui.highlight",
                    {"selector": "lesson-editor", "message": "Smoke highlight", "duration_ms": 300},
                ),
                expected_success=True,
            )
            assert_pointy_result(
                report,
                "pointy_two_step_tour",
                send_pointy_action(
                    frame,
                    "ui.show_tour",
                    {
                        "steps": [
                            {
                                "selector": "course-editor-sidebar",
                                "message": "Sidebar",
                                "duration_ms": 120,
                            },
                            {
                                "selector": "lesson-editor",
                                "message": "Lesson editor",
                                "duration_ms": 120,
                            },
                        ]
                    },
                ),
                expected_success=True,
            )
            assert_pointy_result(
                report,
                "pointy_publish_menu_click_fails_closed",
                send_pointy_action(
                    frame,
                    "ui.click",
                    {"selector": "open-publish-menu", "message": "Should fail closed"},
                ),
                expected_success=False,
                expected_error_prefix="unsafe_click_target:",
            )
            assert_pointy_result(
                report,
                "pointy_save_click_fails_closed",
                send_pointy_action(
                    frame,
                    "ui.click",
                    {"selector": "save-lesson", "message": "Should fail closed"},
                ),
                expected_success=False,
                expected_error_prefix="unsafe_click_target:",
            )
            safe_click_result = send_pointy_action(
                frame,
                "ui.click",
                {"selector": "course-editor-tab-info", "message": "Safe navigation smoke"},
            )
            assert_pointy_result(
                report,
                "pointy_safe_navigation_click_succeeds",
                safe_click_result,
                expected_success=True,
            )
            page.wait_for_url(re.compile(r"/editor/info"), timeout=10_000)
            step(
                report,
                "safe_navigation_reached_info_tab",
                ok="/editor/info" in page.url,
                url=page.url,
            )
            screenshot(page, "pointy-contract-05-after-safe-click.png")
        except Exception as exc:
            step(report, "smoke_exception", ok=False, error=repr(exc))
            try:
                screenshot(page, "pointy-contract-error.png")
            except Exception:
                pass
        finally:
            browser.close()

    report["ok"] = not report.get("errors")
    report_path = OUT_DIR / "lms-pointy-contract-smoke-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "ok": report["ok"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
