# Wiii Local E2E Harness

Status: Active

Owner: Project leadership

Last updated: 2026-05-24

## Purpose

The local E2E harness exists to prove that Wiii can enter the real chat UI on
localhost before longer visual, Code Studio, LMS, or voice scenarios run. A
test failure should say whether auth/bootstrap is broken or whether the product
runtime under test is broken.

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

## Visual Runtime Command

```bash
cd wiii-desktop
npx playwright test -c playwright.visual.config.ts
```

This runs the lightweight auth harness first, then the visual runtime and Code
Studio runtime specs.

## Expected Evidence

- `local-chat-harness.spec.ts` reaches `[data-wiii-id="chat-textarea"]`.
- Login screen text is absent after bootstrap.
- Backend `/api/v1/auth/dev-login/status` reports enabled for the local test
  server.
- If a test stops at login, treat it as harness/auth failure before debugging
  visual runtime.

## Rollback

Revert the harness commit. The product auth surface is unaffected because all
dev-login behavior remains behind existing backend gates.
