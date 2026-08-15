"""Browser smoke probe for the standalone Neko Motion Lab."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    screenshot = Path(
        os.environ.get(
            "NEKO_MOTION_SCREENSHOT",
            str(Path(tempfile.gettempdir()) / "neko-motion-lab-live.png"),
        )
    )
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto("http://127.0.0.1:1420/?preview=neko-motion")
        page.wait_for_load_state("networkidle")

        page.get_by_role("heading", name="Neko Motion Lab").wait_for()
        assert page.locator(".neko-lab-state").count() == 8
        assert page.get_by_role("button", name="Chạy 1 vòng").is_enabled()

        page.get_by_role("button", name="Đang suy nghĩ").click()
        assert page.get_by_role("button", name="Đang suy nghĩ").get_attribute("aria-pressed") == "true"
        assert "Đang suy nghĩ" in page.locator(".neko-lab-character").get_attribute("aria-label")

        page.get_by_role("button", name="Chất liệu 3D").click()
        assert page.locator("[data-testid='neko-rig']").get_attribute("data-render-mode") == "material"
        assert page.get_by_role("button", name="Theo con trỏ").is_disabled()
        assert page.get_by_role("button", name="Chớp mắt").is_disabled()

        page.get_by_role("button", name="Rig tham số").click()
        page.get_by_role("button", name="Reduced motion").click()
        assert page.get_by_role("button", name="Chạy 1 vòng").is_disabled()
        page.get_by_role("button", name="Reduced motion").click()

        page.get_by_role("button", name="Đặt lại lab").click()
        page.get_by_role("button", name="Chạy 1 vòng").click()
        page.get_by_role("button", name="Dừng demo").wait_for()
        page.get_by_role("button", name="Dừng demo").click()

        page.screenshot(path=str(screenshot), full_page=True)
        browser.close()

    report = {
        "status": "pass" if not console_errors else "fail",
        "screenshot": str(screenshot),
        "console_errors": console_errors,
        "checks": {
            "state_buttons": 8,
            "thinking_state": True,
            "render_modes": True,
            "reduced_motion_gate": True,
            "demo_interrupt": True,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if console_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
