# Wiii Local E2E Harness

Status: Active

Owner: Project leadership

Last updated: 2026-05-26

## Purpose

The local E2E harness exists to prove that Wiii can enter the real chat UI on
localhost and complete a deterministic browser chat baseline before longer
visual, Code Studio, LMS, or voice scenarios run. A test failure should say
whether auth/bootstrap, browser stream assembly, or the product runtime under
test is broken.

## Contract

- Playwright visual tests start a local backend and frontend through
  `wiii-desktop/playwright.visual.config.ts`.
- The backend test server is forced into `ENVIRONMENT=development` with
  `ENABLE_DEV_LOGIN=true`.
- The frontend test server receives `VITE_API_URL` pointing at that backend.
- Browser tests authenticate by calling the real `/api/v1/auth/dev-login`
  endpoint through Playwright's request context, then seed the same
  `auth_state` and secure token stores that `loginWithTokens()` writes. They do
  not fake a legacy `local-dev-key` session in localStorage.
- Production auth is not bypassed. `/auth/dev-login` remains gated by backend
  settings, production validation, and private-source checks.

## Smoke Command

```bash
cd wiii-desktop
npx playwright test -c playwright.visual.config.ts playwright/local-chat-harness.spec.ts
```

To avoid an already-running local app, use isolated ports. PowerShell:

```powershell
cd wiii-desktop
$env:WIII_PLAYWRIGHT_BACKEND_PORT="8030"
$env:WIII_PLAYWRIGHT_FRONTEND_PORT="1430"
$env:WIII_PLAYWRIGHT_SERVER_URL="http://127.0.0.1:8030"
$env:WIII_PLAYWRIGHT_BASE_URL="http://127.0.0.1:1430"
npx playwright test -c playwright.visual.config.ts playwright/local-chat-harness.spec.ts
```

## Chat Baseline Acceptance Command

```bash
cd wiii-desktop
npx playwright test -c playwright.visual.config.ts playwright/chat-baseline-acceptance.spec.ts
```

This test uses the real browser UI, dev-login bootstrap, chat composer,
frontend SSE parser, stream buffers, Markdown renderer, and chat persistence.
It mocks only the `/api/v1/chat/stream/v3` SSE response at the Playwright
network boundary so the acceptance signal is deterministic and does not require
provider keys, production, or full Docker.

The required evidence is:

- ordinary Vietnamese prompts are submitted through `[data-wiii-id="chat-textarea"]`
- a daily-status prompt containing "hôm nay" stays on chat instead of web search
- final assistant answers render in `[data-message-role="assistant"]`
- Markdown code renders as a chat code block, not Code Studio
- stream events include `status`, `answer`, `metadata`, and terminal `done`
- terminal `runtime_flow_ledger` says `host_surface=desktop_chat`,
  `route.lane=native_turn`, no observed tools, host/Pointy/visual/Code Studio
  suppressed, and `finalization.status=saved`
- turn-path metadata is preserved in the stream/persisted message and reports
  `casual_chat`, `bind_tools=false`, and `force_tools=false`
- visible and persisted answers contain no raw provider/tool payload markers
- no host action preview, Pointy spotlight/action surface, visual block, or
  Code Studio surface appears

## Visual Runtime Command

```bash
cd wiii-desktop
npx playwright test -c playwright.visual.config.ts
```

This runs the chat baseline acceptance, lightweight auth harness, visual
runtime, and Code Studio runtime specs.

## Expected Evidence

- `local-chat-harness.spec.ts` reaches `[data-wiii-id="chat-textarea"]`.
- `chat-baseline-acceptance.spec.ts` sends real UI prompts and proves
  prompt-to-answer browser assembly with a deterministic SSE baseline.
- Login screen text is absent after bootstrap.
- Backend `/api/v1/auth/dev-login/status` reports enabled for the local test
  server.
- If a test stops at login, treat it as harness/auth failure before debugging
  chat, visual runtime, or Code Studio behavior.

## Rollback

Revert the harness commit. The product auth surface is unaffected because all
dev-login behavior remains behind existing backend gates.
