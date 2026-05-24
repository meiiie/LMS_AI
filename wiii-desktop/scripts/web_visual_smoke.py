import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


DEFAULT_FIRST_PROMPT = (
    "Explain Kimi linear attention in charts. Compare standard attention vs "
    "linear attention and highlight the bottleneck."
)
DEFAULT_FOLLOWUP_PROMPT = (
    "Keep the same visual session, turn it into 3 process steps, and highlight "
    "where approximation error appears."
)
TECHNICAL_LEAKS = (
    "structured visual",
    "spec_merge",
    "filterable",
    "inline visual",
    "generate visual",
    "template",
    "de tom tat nhanh noi dung",
)


def configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    default_output_dir = repo_root / ".Codex" / "reports" / "visual-runtime-v3" / "artifacts"

    parser = argparse.ArgumentParser(
        description="Run a real web smoke test for Wiii inline visuals.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:1420")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument("--screenshot-name", default="visual-followup-rendered.png")
    parser.add_argument("--result-name", default="web-visual-patch-result.json")
    parser.add_argument("--viewport-width", type=int, default=1440)
    parser.add_argument("--viewport-height", type=int, default=2200)
    parser.add_argument("--user-id", default="visual-web-smoke-user")
    parser.add_argument("--display-name", default="Visual Web Smoke")
    parser.add_argument(
        "--stable-user-id",
        action="store_true",
        help="Reuse the provided user id exactly instead of appending a run-specific suffix.",
    )
    parser.add_argument("--first-prompt", default=DEFAULT_FIRST_PROMPT)
    parser.add_argument("--followup-prompt", default=DEFAULT_FOLLOWUP_PROMPT)
    parser.add_argument(
        "--expect-process-cue",
        nargs="*",
        default=[
            "buoc hien tai",
            "step 1",
            "quy trinh",
            "theo tung buoc",
            "approximation error",
            "diem can chu y",
        ],
        help="Lowercased cue strings that confirm the follow-up visual surface changed.",
    )
    return parser.parse_args()


def dump_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def send_prompt(page, prompt: str) -> None:
    input_box = page.locator('[data-wiii-id="chat-textarea"]').first
    input_box.wait_for(state="visible", timeout=60_000)
    input_box.fill(prompt)
    input_box.press("Enter")


def visual_signature(locator) -> str:
    title = locator.locator("h3").inner_text(timeout=30_000)
    text = locator.inner_text(timeout=30_000)
    return f"{title}\n{text}"


def wait_for_visual_surface_change(page, previous_signature: str, cue_tokens: list[str], timeout_ms: int = 120_000) -> None:
    page.wait_for_function(
        """
        ({ expectedSignature, cueTokens }) => {
          const block = document.querySelector('[data-testid="visual-block"]');
          if (!block) return false;
          const title = block.querySelector("h3")?.textContent || "";
          const text = block.textContent || "";
          const nextSignature = `${title}\\n${text}`;
          const normalized = nextSignature.toLowerCase();
          const hasCue = cueTokens.some((token) => normalized.includes(token));
          return nextSignature !== expectedSignature && hasCue;
        }
        """,
        arg={"expectedSignature": previous_signature, "cueTokens": cue_tokens},
        timeout=timeout_ms,
    )


def has_technical_leak(text: str) -> bool:
    normalized = text.lower()
    return any(token in normalized for token in TECHNICAL_LEAKS)


def build_effective_user_id(base_user_id: str, stable_user_id: bool) -> str:
    if stable_user_id:
        return base_user_id
    return f"{base_user_id}-{int(time.time() * 1000)}"


def safe_email(user_id: str) -> str:
    local_part = re.sub(r"[^a-z0-9-]+", "-", user_id.lower())[:48]
    return f"{local_part or 'playwright'}@localhost"


def build_authenticated_init_script(server_url: str, user_id: str, display_name: str, session: dict) -> str:
    user = session.get("user") or {}
    auth_user = {
        "id": user.get("id") or user_id,
        "email": user.get("email") or safe_email(user_id),
        "name": user.get("name") or display_name,
        "avatar_url": user.get("avatar_url") or "",
        "role": user.get("role") or "admin",
        "legacy_role": user.get("legacy_role") or user.get("role") or "admin",
        "platform_role": user.get("platform_role") or "platform_admin",
        "organization_role": user.get("organization_role") or "",
        "host_role": user.get("host_role") or "",
        "role_source": user.get("role_source") or "platform",
        "active_organization_id": user.get("active_organization_id") or session.get("organization_id") or "",
        "connector_id": "",
        "identity_version": "2",
    }
    settings_payload = {
        "server_url": server_url,
        "api_key": "",
        "user_id": auth_user["id"],
        "user_role": auth_user["role"],
        "display_name": auth_user["name"],
        "llm_provider": "google",
        "theme": "light",
        "default_domain": "maritime",
    }
    if auth_user["active_organization_id"]:
        settings_payload["organization_id"] = auth_user["active_organization_id"]
    auth_payload = {"data": {"user": auth_user, "authMode": "oauth"}}
    token_payload = {
        "tokens": {
            "access_token": session["access_token"],
            "refresh_token": session["refresh_token"],
            "expires_at": int(time.time() * 1000) + int(session.get("expires_in") or 900) * 1000,
        }
    }
    return (
        "localStorage.clear();"
        "sessionStorage.clear();"
        f"localStorage.setItem('wiii:app_settings', JSON.stringify({json.dumps(settings_payload)}));"
        f"localStorage.setItem('wiii:auth_state', JSON.stringify({json.dumps(auth_payload)}));"
        f"localStorage.setItem('wiii:wiii_auth_tokens', JSON.stringify({json.dumps(token_payload)}));"
    )


def bootstrap_local_chat(page, base_url: str, server_url: str, user_id: str, display_name: str) -> None:
    status = page.request.get(
        f"{server_url}/api/v1/auth/dev-login/status",
        timeout=30_000,
    )
    if not status.ok:
        raise RuntimeError(
            f"dev-login status probe failed ({status.status}); "
            "start the local backend with ENABLE_DEV_LOGIN=true",
        )
    status_json = status.json()
    if not status_json.get("enabled"):
        raise RuntimeError("dev-login is disabled; visual smoke requires ENABLE_DEV_LOGIN=true")

    login = page.request.post(
        f"{server_url}/api/v1/auth/dev-login",
        data={"email": safe_email(user_id), "name": display_name, "role": "admin"},
        timeout=30_000,
    )
    if not login.ok:
        raise RuntimeError(f"dev-login failed ({login.status}): {login.text()}")

    page.add_init_script(
        build_authenticated_init_script(server_url, user_id, display_name, login.json())
    )
    page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
    composer = page.locator('[data-wiii-id="chat-textarea"]').first
    composer.wait_for(state="visible", timeout=60_000)


def main() -> int:
    configure_stdio()
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_user_id = build_effective_user_id(args.user_id, args.stable_user_id)

    result: dict[str, object] = {
        "first_prompt": args.first_prompt,
        "followup_prompt": args.followup_prompt,
        "url": args.base_url,
        "server_url": args.server_url,
        "requested_user_id": args.user_id,
        "effective_user_id": effective_user_id,
        "viewport": {
            "width": args.viewport_width,
            "height": args.viewport_height,
        },
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": args.viewport_width, "height": args.viewport_height},
        )
        page = context.new_page()

        bootstrap_local_chat(page, args.base_url, args.server_url, effective_user_id, args.display_name)

        send_prompt(page, args.first_prompt)
        first_visual = page.locator('[data-testid="visual-block"]').first
        first_visual.wait_for(state="visible", timeout=120_000)
        page.wait_for_timeout(2_500)

        before_count = page.locator('[data-testid="visual-block"]').count()
        before_title = first_visual.locator("h3").inner_text(timeout=30_000)
        before_text = first_visual.inner_text(timeout=30_000)
        before_signature = visual_signature(first_visual)
        editorial_flow_count = page.locator('[data-testid="editorial-visual-flow"]').count()

        send_prompt(page, args.followup_prompt)
        wait_for_visual_surface_change(page, before_signature, args.expect_process_cue)
        page.wait_for_load_state("networkidle", timeout=60_000)
        page.wait_for_timeout(1_500)

        visuals = page.locator('[data-testid="visual-block"]')
        after_count = visuals.count()
        latest_visual = visuals.first
        after_title = latest_visual.locator("h3").inner_text(timeout=30_000)
        after_text = latest_visual.inner_text(timeout=30_000)
        has_overflow = page.evaluate(
            """
            () => ({
              documentWidth: document.documentElement.scrollWidth,
              viewportWidth: window.innerWidth,
              hasOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
            })
            """
        )

        page.screenshot(path=str(output_dir / args.screenshot_name), full_page=True)
        browser.close()

    result.update(
        {
            "before_count": before_count,
            "after_count": after_count,
            "before_title": before_title,
            "after_title": after_title,
            "before_excerpt": before_text[:600],
            "after_excerpt": after_text[:600],
            "editorial_flow_count": editorial_flow_count,
            "same_block_count": before_count == after_count == 1,
            "changed_visual_surface": before_title != after_title or before_text != after_text,
            "editorial_clean": not has_technical_leak(after_text),
            **has_overflow,
        }
    )

    dump_json(output_dir / args.result_name, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["same_block_count"]:
        return 2
    if not result["changed_visual_surface"]:
        return 3
    if not result["editorial_clean"]:
        return 4
    if result["hasOverflow"]:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
