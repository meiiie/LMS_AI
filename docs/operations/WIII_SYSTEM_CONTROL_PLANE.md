# Wiii System Control Plane

Status: Active

Owner: Project leadership

Last updated: 2026-05-25

Related issue: #638

## Purpose

This document is Wiii's operating map for understanding the whole system before
debugging or changing it. It exists because patch-by-patch repair is too costly
for a product with chat, RAG, LMS host actions, visuals, Code Studio, memory,
auth, and deployment in the same active path.

The control plane answers four questions:

1. Which Wiii layer owns this behavior?
2. Which runtime flow is the request on?
3. Which signal proves that flow is healthy?
4. Where should debugging start when the signal is missing?

It complements:

- `docs/WIII_PROJECT_MENTAL_MODEL.md` for the five-layer product model.
- `docs/architecture/WIII_CODEBASE_MAP.md` for source navigation.
- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md` for external
  systems Wiii should compare against before deeper runtime changes.
- `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md` for the
  OpenClaw-derived control-plane, runtime ledger, and chat-baseline
  requirements.
- `docs/operations/WIII_SELF_HARNESS.md` for static contract harnessing.
- `docs/operations/WIII_LOCAL_E2E_HARNESS.md` for local browser entry.
- `docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md` for pinned production
  deploy and smoke.

## Current Operating Snapshot

As of 2026-05-25:

- Last accepted production deploy SHA:
  `3cc3f829eb2dcf674d11f97a3e4335334fddee3d`.
- Last production deploy workflow:
  `https://github.com/meiiie/wiii/actions/runs/26373158277`.
- Last external production smoke result: `19 passed, 0 failed`, including
  structured visual SSE `visual_open` and `visual_commit`.
- The Wiii GCP VM `wiii-production` in project `the-wiii-lab`,
  zone `asia-southeast1-c`, was intentionally stopped on 2026-05-25 to reduce
  cost. Public health checks may fail while the VM is stopped. Treat that as an
  operating state, not a code regression, until the VM is started again.
- `tools/wiii_self_harness/run_wiii_self_harness.py` passes against the current
  scenario manifest.

## Control Plane Model

Wiii should be operated through five product layers and one governance layer:

| Layer | Owns | Typical failure symptom | First place to inspect |
|---|---|---|---|
| Wiii Core | turn routing, provider calls, tool loops, SSE events | wrong lane, silence, raw payloads, slow turn | `maritime-ai-service/app/services/chat_*`, `app/engine/multi_agent/**` |
| Wiii Living | continuity, identity, post-turn memory behavior | Wiii forgets, repeats, or changes persona incoherently | memory/living services and post-turn hooks |
| Wiii Host | desktop, embed, LMS, Pointy, visual/code frames | preview missing, Pointy wrong action, visual clipped | `wiii-desktop/src/**`, LMS/host bridge modules |
| Wiii Org | auth, membership, tenant boundaries, permissions | wrong user/org, auth loop, cross-tenant risk | `app/auth/**`, org middleware, repositories |
| Wiii Data | PostgreSQL, pgvector, MinIO, Valkey, migrations | missing history, citations, uploads, memory, or source refs | repositories, migrations, document context paths |
| Governance | issue/branch/PR/release/harness controls | risky or unreviewable changes keep landing | `.github/**`, `docs/operations/**`, `tools/wiii_self_harness/**` |

Do not start with a code edit until the failing symptom is mapped to one of
these layers and one active runtime flow.

## Active Runtime Flows

| Flow | User outcome | Layers | Primary entry points | Healthy signals |
|---|---|---|---|---|
| Chat stream | Wiii responds in real time with readable SSE V3 output | Core, Host, Org, Data | `chat_stream.py`, `chat_stream_coordinator.py`, `useSSEStream.ts` | `status/thinking/answer/metadata/done`, no raw tool JSON, final turn persisted |
| Uploaded document to LMS lesson | Teacher gets preview, citations/source refs, then applies with approval | Host, Core, Data, Org | `document_preview_contract.py`, `direct_node_document_preview_runtime.py`, `PreviewPanel.tsx` | preview host action emitted, source refs present, no mutation before `approval_token` |
| Visual/article figure | Inline figure appears in the answer and can be patched | Core, Host | `visual_intent_resolver.py`, `tool_collection.py`, `visual_events.py`, `VisualBlock.tsx` | required visual tool bound, `visual_open/patch`, `visual_commit`, no raw widget fences |
| Code Studio app/artifact | App-like output opens in host-owned preview shell | Core, Host | `code_studio_*`, `CodeStudioPanel.tsx`, `InlineVisualFrame.tsx` | typed tool-round outcome, safe-stop or preview, viewport frame not clipped |
| Pointy and host control | Wiii can guide or act on host UI only in the right mode | Host, Core, Org | Pointy host code, host action tools, audit route | explicit mode/capability, audit event, safe click policy respected |
| RAG and memory answer | Answer is grounded, cited, and tenant-safe | Core, Data, Org, Living | repositories, RAG services, memory services | tenant filters, source refs/citations, no unsupported facts from uploaded docs |
| Auth and org session | User identity and org context are stable across surfaces | Org, Host, Data | auth routers, middleware, desktop stores | verified auth, correct org, refresh works, no cross-surface token drift |
| Voice | Pointy voice status and provider-backed audio UX work safely | Host, Core | `voice.py`, desktop voice controls | feature flag/provider visible, graceful disabled state, no secret leakage |
| Production release | Reviewed `main` SHA runs through pinned images | Governance, Core, Host, Data | deploy workflow, release runbook, smoke script | image tags exist, app/nginx healthy, external smoke green |

## Flow Monitoring Ladder

This ladder is the minimum set of observations that should exist for a healthy
turn. Some signals already exist; missing signals are the next monitoring work.

| Stage | Signal that should exist | Current evidence | Gap to close |
|---|---|---|---|
| Edge/deploy | deploy SHA, image tag, VM state, public health | deploy workflow, release smoke, GCP VM status | keep a single release status note after stop/start events |
| API ingress | request ID, user ID, org ID, session ID, endpoint | API headers and auth context | ensure the same correlation ID reaches stream metadata and logs |
| Context build | host surface, document context, source refs, memory context | document context tests and preview contract | add an explicit context-summary event for debugging slow or wrong turns |
| Intent/routing | selected lane and reason | typed visual/tool requirements, Code Studio outcomes | emit a compact route decision record per turn |
| Retrieval/memory | query scope, tenant filters, source IDs, citation count | repository tests and source-reference helpers | add golden source-backed replay cases for active LMS documents |
| Provider/tool loop | provider/model, tool bound, tool started/result/error | tool events, visual telemetry, focused unit tests | centralize a turn ledger instead of scattering log-only evidence |
| SSE assembly | event order, first useful chunk, final `done` | stream coordinator tests and production smoke | assert sync/stream parity for high-risk lanes |
| Frontend assembly | visible answer, previews, sources, visual frames | Vitest, local E2E harness, visual frame tests | browser acceptance matrix for authenticated LMS/visual flows |
| Host mutation | preview request ID, approval token hash, apply result | host action audit route, token hash tests | real LMS test course acceptance run |
| Finalization | saved turn, metadata, post-turn hooks | orchestrator finalization tests | observable finalization failure metric |

## Debugging Protocol

When Wiii feels "bad", classify the symptom before changing code:

| Symptom | Start here | First proof to collect |
|---|---|---|
| Public site is down | release/deploy flow | VM status, deploy run, `/api/v1/health/live` |
| Chat is silent or slow | chat stream flow | SSE event sequence and provider/tool latency |
| Answer ignores uploaded document | document/RAG flow | document context payload, source refs, route decision |
| LMS content mutates unsafely | host mutation flow | host action preview event, audit row, approval token handling |
| Visual appears as raw payload | visual flow | `visual_open/commit` events and frontend renderer state |
| Code Studio opens wrong surface | Code Studio flow | tool-round outcome and requested preview/code view |
| Pointy clicks at the wrong time | Pointy/host control flow | mode/capability decision and host action audit |
| User/org looks wrong | auth/org flow | auth context, org middleware, persisted frontend state |
| Memory feels incoherent | Living/Data flow | memory write/read path and post-turn hooks |

The expected loop is:

1. Reproduce with the smallest real surface.
2. Identify the runtime flow and layer.
3. Collect the nearest signal from the monitoring ladder.
4. Form one hypothesis about the missing or wrong signal.
5. Patch the narrow contract, then add a test or harness scenario.

## Harness Relationship

Wiii currently has three harness levels:

| Harness | Purpose | What it proves | What it does not prove |
|---|---|---|---|
| Wiii Self-Harness | static contract manifest | critical evidence files and tokens still exist | runtime behavior works |
| Local E2E Harness | browser/bootstrap smoke | local app can authenticate and reach chat UI | LMS production acceptance works |
| Production Smoke | deployed release smoke | public health, embed, Pointy, structured visual SSE | deep document/LMS apply flow works |

The missing layer is a runtime flow ledger: a compact per-turn record that links
request ID, session ID, route decision, provider/tool calls, SSE lifecycle,
host-action IDs, source refs, and finalization status. That should be the next
implementation target after the current documentation map is merged.

## Next Execution Order

Proceed in this order unless production risk forces a hotfix:

1. **Reference systems audit**
   - Start with OpenHuman for memory/context/living-agent structure.
   - Start with OpenClaw for gateway/session/tool/trace structure.
   - Convert findings into concrete Wiii flow-ledger and chat-baseline
     requirements.
   - Current OpenClaw output:
     `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`.

2. **Chat stream baseline**
   - Run ordinary Vietnamese chat prompts with no document, no LMS, no visual,
     and no Pointy action.
   - Verify route decision, SSE order, frontend rendering, no raw payload, and
     finalization.

3. **LMS document preview/apply acceptance**
   - Use a safe test tenant/course.
   - Upload real DOCX/PDF.
   - Ask for a lesson in Vietnamese.
   - Verify preview, source refs, citations, `approval_token`, and final draft.

4. **Runtime flow ledger**
   - Add a typed, privacy-safe turn trace surface.
   - Keep it log/metadata first; avoid a dashboard until the schema is stable.
   - Include route decision, selected tools, source counts, visual/host events,
     provider/model, and finalization status.

5. **Stream and route replay cases**
   - Add golden replay scenarios for uploaded document, visual, Code Studio,
     RAG, and Pointy no-action cases.
   - Keep production smoke lightweight; keep mutation acceptance isolated.

6. **Frontend acceptance matrix**
   - Authenticated LMS/embed browser run.
   - Visual/Code Studio frame screenshots.
   - Markdown/code streaming and source-reference visibility.

7. **Living/memory audit**
   - Map post-turn hooks and memory write/read paths.
   - Add tenant-safe replay checks before changing memory behavior.

## Operating Rules

- Do not treat a green unit suite as product readiness when the active flow is
  LMS/host/browser-visible.
- Do not treat a green production smoke as proof that LMS mutation acceptance is
  safe.
- Do not mutate LMS content without preview plus approval evidence.
- Do not debug visuals or Code Studio without checking the lane decision first.
- Do not restart the GCP VM just to inspect code; start it only when a public
  smoke or production acceptance run is needed.
- Promote durable findings into this document, the codebase map, Self-Harness,
  or a GitHub issue. Chat memory is not an operating control.
