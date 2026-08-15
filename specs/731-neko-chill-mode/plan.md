# Implementation Plan: Neko Chill Mode — No-Login Local-Agent Surface (ACP)

**Branch**: `731-neko-chill-mode` · **Spec**: `specs/731-neko-chill-mode/spec.md` · **Issue**: #886

## Summary

Add a second shell-level mode to `wiii-desktop` that drives local ACP agents
through Tauri sidecar processes. Three layers: (1) a Rust transport in
`src-tauri` that owns process lifecycle and the stdio JSON-RPC pump, (2) a
TypeScript **driver layer** that normalizes ACP into provider-agnostic
`DriverEvent`s, (3) a `neko-chill` store family + minimal chat surface that
reuses the existing `ContentBlock` vocabulary and markdown stack. The
authenticated Wiii mode is untouched except for the mode switch at the
`App.tsx` pre-auth seam.

## Technical Context

**Grounding (audit 2026-08-12, `E:\Sach\Sua\NekoChill\docs\audit-wiii-2026-08-12.md` § C):**

- Entry seam: `wiii-desktop/src/App.tsx` already early-returns pre-auth
  surfaces (`?preview=avatar|pointy`, lines 61–78); the auth gate is at
  line 291. The mode check slots at that altitude, before `initClient`,
  health/org polling, and OAuth effects.
- `src-tauri` is greenfield: 90 lines of Rust, plugins `store`/`http`/`dialog`/
  `shell`/`notification` registered, 3 commands, mobile entry stubbed.
- Transcript vocabulary: `ContentBlock` union in `src/api/types.ts`; the
  presentation-pure markdown stack lives in `src/components/common/`
  (`MarkdownRenderer`, `RichMarkdownSegment`, `MathMarkdownSegment`,
  `CodeBlock`/`ShikiMinimalHighlighter`, `MermaidDiagram`, sanitize schema).
- Do NOT touch: `chat-store.ts` (2,922-line cloud monolith), `api/client.ts`
  (auth-coupled global).
- Driver-shape proof: the SSE V3 handler surface in `src/api/sse.ts`
  (`onThinking/onAnswer/onToolCall/onToolResult/onStatus/onDone/onError`)
  already matches the normalized event set — the future Wiii-cloud driver
  maps ~1:1 onto the same `DriverEvent` union (FR-010).
- ACP: JSON-RPC 2.0 over stdio; client spawns the agent with an ACP flag
  (e.g. `gemini --experimental-acp`), then `initialize` →
  `session/new` → `session/prompt`; agent streams `session/update`
  notifications (message/thought/tool-call chunks), requests approvals via
  `session/request_permission`, prompt turns end with a `stopReason`;
  cancellation via `session/cancel`. Verify exact method/field names against
  the current public ACP schema + Gemini CLI docs during T201 — do not trust
  memory or this plan for wire names.
- **License wall**: egoist/waku (GPL-3.0) is an architecture reference only —
  its `docs/providers.md` driver-contract *ideas* (session-per-driver,
  normalized activity rows, idle reaping, stdin-close termination) are used;
  no code is read-adjacent while writing ours.

## Constitution Check

- **I. Native Runtime Ownership**: the driver layer is Wiii-owned; ACP shapes
  stay inside `drivers/acp/`; no framework dependency added. ✅
- **II. Memory/Tenant Safety**: mode stores nothing in cloud state; local
  persistence only; no cross-tenant surface. ✅
- **III. Streaming-First**: DriverEvents render incrementally; turn lifecycle
  is explicit; no silent work. ✅
- **IV. Safe Tools**: `session/request_permission` renders an explicit gate;
  unanswered ⇒ fail-closed (terminate process on exit). Mutating actions gated
  stronger than reads by surfacing the agent-declared action kind. ✅
- **V. Change Discipline**: issue #886; PR slices per phase below; desktop
  verification gate on every slice; no backend changes. ✅

## Project Structure

### Documentation (this feature)

```
specs/731-neko-chill-mode/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```
wiii-desktop/
├── src-tauri/src/
│   ├── commands/
│   │   └── neko_agent.rs      # NEW: detect/spawn/write/kill ACP agent processes
│   └── lib.rs                 # register commands + emit agent events to webview
├── src/
│   ├── App.tsx                # mode check at the pre-auth seam (early return)
│   ├── neko-chill/            # NEW: everything mode-specific lives here
│   │   ├── NekoChillApp.tsx   # mode shell: sidebar (sessions) + chat surface
│   │   ├── components/        # AgentPicker, PermissionCard, NekoComposer,
│   │   │                      # NekoTranscript (thin list over shared blocks)
│   │   ├── drivers/
│   │   │   ├── types.ts       # DriverEvent union + Driver interface (FR-010)
│   │   │   └── acp/           # ACP JSON-RPC client over the Tauri transport
│   │   ├── stores/
│   │   │   ├── mode-store.ts      # persisted mode selection (FR-001)
│   │   │   ├── neko-session-store.ts  # sessions, transcript blocks, streaming
│   │   │   └── neko-agent-store.ts    # detected agents
│   │   └── persistence.ts     # tauri plugin-store read/write, incremental
│   └── __tests__/neko-chill/  # vitest: driver mapping, stores, gating
```

**Structure Decision**: single new `src/neko-chill/` subtree so the mode is
grep-able, reviewable, and deletable as a unit; only `App.tsx`, `lib.rs`, and
`capabilities` are touched outside it. Shared components are imported FROM
`components/common/` — never modified in this feature; if a shared component
needs prop-injection to decouple from cloud stores, that lands as its own
micro-PR first.

## Architecture Decisions

1. **Process transport in Rust, protocol in TypeScript.** `src-tauri` owns
   spawn/stdin-write/stdout-lines/kill and emits raw NDJSON lines as Tauri
   events (`neko-agent://line/{procId}`); the ACP JSON-RPC state machine,
   request/response correlation, and event normalization live in TS
   (`drivers/acp/`). Rationale: protocol iterates fast in TS with vitest;
   Rust stays a dumb, robust pipe (kill-on-drop, no orphans — FR-009).
2. **DriverEvent is the contract** (`drivers/types.ts`): `turn-started`,
   `reasoning-delta`, `activity`, `answer-delta`, `permission-request`,
   `turn-finished`, `error`, `process-exited`. The store consumes ONLY this
   union; ACP mapping happens in exactly one file. The future Wiii-cloud
   driver implements the same interface from the SSE V3 handler surface.
3. **Store speaks ContentBlock.** `neko-session-store` converts DriverEvents
   into the existing `ContentBlock` shapes so `MarkdownRenderer` + block
   components render Neko transcripts with zero component forks. New block
   needs (permission card) get a mode-local component, not a `types.ts` edit.
4. **Fail-closed process discipline.** Every spawned proc is registered in a
   Rust-side table; app-exit and window-destroy hooks kill the table; idle
   sessions reap after 30 minutes (waku-lesson, reimplemented).
5. **Persistence is incremental.** Append-oriented writes via tauri
   plugin-store (session index + per-session transcript file), debounced;
   no full-store rewrite per token (edge case: long transcripts).

## Verification Plan

- Unit (vitest): ACP→DriverEvent mapping fixtures (golden NDJSON transcripts
  recorded from real Gemini CLI runs); store lifecycle (streaming append,
  cancel, permission resolution, fail-closed on unanswered); mode-store
  persistence.
- Type/build gates per AGENTS.md: `npx vitest run`, `npx tsc --noEmit`,
  `npm run build:embed` (proves cloud surface untouched — SC-005).
- Manual acceptance on Windows against real Gemini CLI: the five SC items,
  plus 10× open/work/quit orphan check (SC-006) via Task Manager/`tasklist`.
- Rust: `cargo check` in `src-tauri` (a `cargo test` for the process table
  if logic warrants).

## Complexity Tracking

- Deliberately deferred: Wiii-cloud driver in-mode, agent-native session
  resume (`session/load`), MCP passthrough, checkpoint/rewind, mobile.
- Risk: ACP versioning drift between Gemini CLI and `neko acp` → pin the
  protocol version in `initialize` and surface a clear mismatch error.
- Risk: Windows process-tree kill semantics (agents spawning children) →
  use Job Objects semantics via Tauri/std where available; verify in SC-006.

## Runtime Integrity Follow-up (#908)

The follow-up remains inside `src/neko-chill/` and adds no framework or backend
dependency:

1. `session-events.ts` defines the versioned append-only boundary log. The
   materialized `messages` transcript remains for rendering/backward
   compatibility; transcript schema v2 stores both and migrates v1 user inputs.
2. `runtime-manager.ts` owns live drivers through `RuntimeScope`, assigns a new
   provider `instanceId` on each attach, and resolves operations by declared
   capability. Driver events are accepted only from the current identity.
3. Critical persistence is a dispatch barrier. Writes are serialized so an
   older debounced snapshot cannot overwrite a newer model-input record.
4. Runtime prepare failure leaves the current binding untouched. Session
   control changes persist `requested`, then `committed` or `rolled-back`;
   commit-persistence failure triggers compensation and surfaces
   `rollback-failed` if compensation also fails.
5. React mode entry owns the idle-reaper timer and disposes all runtimes on
   unmount. The Rust process table remains the final app-exit safety net.

Risk is limited to local session persistence/provider lifecycle. Rollback is a
revert of #908: v2 retains the `messages` snapshot, while the new reader accepts
v1 transcripts. No cloud state, auth, tenant boundary, or backend API changes.
