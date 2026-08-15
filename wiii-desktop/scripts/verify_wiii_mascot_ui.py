"""Visual smoke for the approved Wiii Neko Peek identity."""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT.parent / "docs" / "assets" / "screenshots" / "tmp"
BASE_URL = "http://127.0.0.1:1420"


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 480, "height": 340})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto(f"{BASE_URL}/splashscreen.html", wait_until="domcontentloaded")
        mascot = page.locator('img[src="/wiii-mascot-full.png"]')
        mascot.wait_for(state="visible")
        assert mascot.evaluate("node => node.naturalWidth") > 0
        page.wait_for_timeout(900)
        page.screenshot(path=ARTIFACTS / "wiii-neko-splash-smoke.png")

        # The splash intentionally redirects after its staged progress. Use a
        # separate page for the app so that redirect cannot race this probe's
        # explicit navigation.
        page.close()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(800)
        compact_marks = page.locator('img[src="/icon-192.png"]')
        assert compact_marks.count() >= 1
        assert compact_marks.first.evaluate("node => node.naturalWidth") > 0
        page.screenshot(
            path=ARTIFACTS / "wiii-neko-app-smoke.png",
            full_page=True,
        )

        print(
            json.dumps({
                "title": page.title(),
                "compact_marks": compact_marks.count(),
                "console_errors": console_errors,
            }, ensure_ascii=True)
        )
        browser.close()


if __name__ == "__main__":
    main()
