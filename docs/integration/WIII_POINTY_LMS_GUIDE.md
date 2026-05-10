# Wiii Pointy - LMS Integration Guide

Status: V1.1 production-supported contract

Owner: Wiii Lab

Last updated: 2026-05-10

Audience: LMS frontend team (`holilihu.online` Angular app)

## Purpose

Wiii Pointy is the cooperative iframe overlay that lets Wiii point at UI
elements, scroll to them, navigate safe LMS routes, and run guided tours. It is
the web-native path toward a collaborative-cursor UX: the host app keeps control
of the DOM, while Wiii requests actions through a typed bridge.

V1 is intentionally tutor-safe. The default actions highlight, scroll,
navigate, and run guided tours without mutating LMS state. V1.1 also supports
fail-closed safe-click for navigation-like elements, but only when the LMS host
marks the target with `data-wiii-click-safe="true"`. It does not auto-fill,
submit forms, delete, publish, grade, enroll, pay, or otherwise mutate LMS
state. Mutating actions belong to a future V2 contract and must be gated by
explicit confirmation plus per-tool `mutates_state=true`.

## Integration Contract

The LMS host ships two pieces:

1. Include the Pointy bundle on every page where the Wiii iframe is embedded.

```html
<script src="https://wiii.holilihu.online/pointy/wiii-pointy.umd.js"></script>
```

2. Initialize the bridge once and forward capabilities to the iframe.

```ts
import { Router } from "@angular/router";

declare global {
  interface Window {
    WiiiPointy: any;
  }
}

const wiiiOrigin = "https://wiii.holilihu.online";

const handle = window.WiiiPointy.init({
  iframeOrigin: wiiiOrigin,
  onNavigate: (route: string) => router.navigateByUrl(route),
});

const iframeEl = document.getElementById("wiii-iframe") as HTMLIFrameElement;
iframeEl.addEventListener("load", () => {
  iframeEl.contentWindow?.postMessage(handle.capabilities(), wiiiOrigin);
});
```

The bridge listens for `wiii:action-request` messages from the iframe and
replies with `wiii:action-response`. Wiii's backend `HostActionBridge` and the
iframe frontend already speak this protocol.

## V1 Actions

| Action | Mutates state | Requires confirmation | Purpose |
|---|---:|---:|---|
| `ui.highlight` | no | no | Spotlight and tooltip on a target element |
| `ui.scroll_to` | no | no | Scroll a target into view |
| `ui.navigate` | no | no | Navigate to an internal route or safe absolute URL |
| `ui.show_tour` | no | no | Run a 2-5 step guided walkthrough |
| `ui.click` | no | no | Click only host-marked safe navigation targets |

### `ui.highlight`

```json
{
  "selector": "[data-wiii-id=\"continue-lesson\"]",
  "message": "Day la nut de tiep tuc bai hoc.",
  "duration_ms": 2200
}
```

Expected reply:

```json
{
  "success": true,
  "data": {
    "summary": "Da tro vao element: #continue-lesson"
  }
}
```

### `ui.scroll_to`

```json
{
  "selector": "[data-wiii-id=\"profile-card\"]",
  "block": "center"
}
```

### `ui.navigate`

Prefer internal Angular routes:

```json
{
  "route": "/courses/123/lessons/4"
}
```

Safe absolute URLs are also accepted when they pass the allowlist:

```json
{
  "url": "https://holilihu.online/help"
}
```

Reject loopback, `.local`, `.internal`, and non-`http(s)` URLs fail closed.

### `ui.show_tour`

```json
{
  "steps": [
    {
      "selector": "[data-wiii-id=\"course-card\"]",
      "message": "Buoc 1 - khoa hoc hom nay.",
      "duration_ms": 1600
    },
    {
      "selector": "[data-wiii-id=\"quiz-card\"]",
      "message": "Buoc 2 - bai kiem tra sap toi.",
      "duration_ms": 1600
    }
  ],
  "start_at": 0
}
```

A new tour cancels any tour already running.

`ui.show_tour`, `ui.highlight`, `ui.scroll_to`, and `ui.click` all use the same
selector resolver. The LMS may pass either a normal CSS selector such as
`[data-wiii-id="continue-lesson"]` or the bare stable id `continue-lesson`.
Bare ids resolve to `[data-wiii-id="..."]` first, then fall back to CSS.

### `ui.click`

Safe-click is for low-risk navigation controls only. The host must explicitly
mark each eligible target:

```html
<button
  data-wiii-id="continue-lesson"
  data-wiii-click-safe="true"
  data-wiii-click-kind="navigation"
>
  Tiep tuc bai hoc
</button>
```

Request:

```json
{
  "selector": "continue-lesson",
  "message": "Minh mo tiep bai hoc cho ban nhe."
}
```

Expected reply:

```json
{
  "success": true,
  "data": {
    "clicked": true,
    "click_kind": "navigation"
  }
}
```

If the target lacks `data-wiii-click-safe="true"`, is disabled, hidden, detached,
or off-screen after validation, Pointy returns a failure such as
`unsafe_click_target`, `disabled_click_target`, or `target_not_visible` and does
not call `element.click()`.

### V1.1 Testing Strategy And Known Limitations

Verify `ui.click` at three layers before treating an LMS page as product-ready:

- Unit tests should cover shared selector resolution, including bare
  `data-wiii-id` values and normal selectors, so `ui.click`, `ui.highlight`,
  `ui.scroll_to`, and `ui.show_tour` resolve targets consistently.
- Integration or E2E tests should exercise safe-click success paths with
  `data-wiii-click-safe="true"` and `data-wiii-click-kind`, then verify
  fail-closed behavior for unsafe, disabled, hidden, detached, or off-screen
  targets.
- Product smoke should use real LMS pages and confirm that safe-click is only
  attached to navigation-like targets such as continue, open panel, help, or
  back-to-dashboard.

Current limits:

- `ui.click` only clicks host-marked targets with
  `data-wiii-click-safe="true"`; unmarked targets fail closed.
- `data-wiii-click-kind` is observability metadata, not a permission override.
- Pointy will not click quiz answers, submit, publish, enroll, payment,
  grading, logout, delete, or other mutating controls in V1.1.
- Pointy will not click elements that fail selector resolution or visibility
  validation, including detached and off-screen targets.
- Selector resolution prefers stable `data-wiii-id` values, then falls back to
  CSS. LMS pages should avoid raw class names and fragile `nth-child`
  selectors.

## Selector Discipline

Wiii can only point reliably when the host gives it stable targets.

- Prefer `data-wiii-id` for every interactive element Wiii may reference.
- Keep IDs semantic and durable, for example `continue-lesson`, `browse-courses`,
  `submit-quiz`, `profile-link`.
- Add `data-wiii-click-safe="true"` only to low-risk navigation helpers such as
  `continue-lesson`, `browse-courses`, `open-help`, or `back-to-dashboard`.
  Do not mark destructive, payment, quiz-answer, grading, publish, enrollment,
  logout, or final-submit actions as safe-click.
- Add `data-wiii-click-kind` for observability, for example `navigation`,
  `open_panel`, `help`, or `preview`.
- Use `id` only when uniqueness is guaranteed.
- Avoid raw class names and `nth-child` selectors.
- Add visible interactive elements to `HostContext.content.structured` as
  `{ role, name, data-wiii-id }` so the model can ground actions without guessing.

Quiz pages need an additional guardrail: Wiii may highlight navigation, submit,
hint, or explanation controls, but must not highlight answer options as the
answer. Keep quiz option IDs recognizable, such as `quiz-option-A`, so backend
filters can enforce the rule.

## Security Model

- Origin pinning: the bridge ignores messages whose `event.origin` is not the
  configured `iframeOrigin`, and replies use the same fixed `targetOrigin`.
- Selector hardening: bad selectors return `selector_not_found` instead of
  throwing into the host page.
- URL hardening: `ui.navigate` rejects loopback and internal targets to prevent
  SSRF-style behavior.
- State safety: V1/V1.1 actions are visual/navigation assistance only. Safe-click
  is fail-closed and limited to explicit navigation-like targets. Any future
  mutating action must require confirmation.
- CSP: the bundle is plain JS plus DOM. No `eval`, workers, or fetch are
  required. `script-src 'self' https://wiii.holilihu.online` is sufficient for
  the hosted bundle path.

## Operational Notes

- Bundle size is about 11 KB minified UMD.
- Calling `WiiiPointy.init(...)` twice replaces the previous bridge, which is
  useful during hot reload.
- Call `handle.destroy()` on route teardown if the Angular shell unmounts the
  Wiii iframe.
- Pass a `log: (level, message, context) => ...` callback into `init` to forward
  bridge telemetry to LMS logging.
- Pointy and Page-Aware Context are additive: Page-Aware Context tells Wiii where
  it is, and Pointy gives Wiii safe visual actions.

## Build And Ship

```bash
cd wiii-desktop
npm run build:pointy
```

The build emits:

```text
dist-pointy/wiii-pointy.umd.js
dist-pointy/wiii-pointy.es.js
```

Serve the UMD artifact behind:

```text
https://wiii.holilihu.online/pointy/wiii-pointy.umd.js
```

For visual QA, open:

```text
wiii-desktop/dev-demo/pointy/index.html
```

## Roadmap

- V1: read-only tutor primitives.
- V1.1: fail-closed `ui.click` for host-marked safe navigation targets.
- V2: `ui.fill_field` and any mutating click/apply path, gated by
  `mutates_state=true` and `requires_confirmation=true`.
- V3: voice-assisted guidance and an operator dashboard surface.
- Long-term: map `HostCapabilities.tools[]` to WebMCP once that surface is
  stable enough for production.
