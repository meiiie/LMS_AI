# Research and Architecture Decisions

**Issue**: #941

**Date**: 2026-08-23

## Decision 1: Authority moves before process separation

Phase 2A creates a Rust `NekoRuntime` inside the Tauri process. React becomes
a client of provider/session commands but the process still exits with Wiii.
This removes the privileged raw-spawn boundary without prematurely adding a
second executable, IPC authentication, installation or updater concerns.

Phase 2B may later move the same contract behind `neko-daemon`, where UI
restart can stop affecting live agents.

## Decision 2: One stream per Run

`eventId` is globally unique. `streamId` is the exact durable run stream ID.
`seq` starts at one and increases strictly inside that stream. Separate runs
can both contain sequence 1. This supports efficient replay and avoids using a
SQLite row ID as domain ordering.

Provider stdout is deliberately live-only in this phase. Durable lifecycle
events include session creation/start, run-state change and process exit.
Visible transcript remains Workbench-owned and provider conversation remains
provider-owned.

## Decision 3: At-most-once side effects by request identity

Every native start, write and cancel request is journaled before its side
effect. Completed requests replay their recorded result. Requests that may
have crossed the side-effect boundary return `unknown_outcome` and are never
automatically repeated.

The journal stores method and logical target identity, not raw request bodies.
This prevents credential or prompt capture and detects request-ID collisions.

## Decision 4: SQLite is an implementation of contracts

SQLite uses WAL, foreign keys, a busy timeout and transactions. It stores
sessions, idempotency records and bounded lifecycle events. Sequence is
allocated by `(stream_id, MAX(seq)+1)` inside the same immediate transaction
that inserts the event. Session creation and every lifecycle state transition
commit atomically with their matching durable event, so neither half can
become authoritative alone.

Startup maintenance keeps at most 10,000 lifecycle events per run and removes
events older than 30 days, while retaining each stream's latest event as its
sequence high-water mark. Terminal session detail is retained for 90 days;
active sessions and request-identity records are not pruned. The WAL is then
checkpointed with `TRUNCATE`. A retained stream therefore never reuses a prior
sequence after history compaction.

Large logs, terminal lines, provider frames, prompts, credentials and binary
artifacts remain outside the database. A later manifested-file store can add
replay for approved high-volume artifacts without changing event semantics.

## Decision 5: Recovery is conservative

- `accepted` or `dispatched`: no side effect was declared; recover as
  `continuity_lost`/failed without executing it.
- `side_effect_started` or `committed` without completion: outcome may exist;
  recover as `unknown_outcome`.
- terminal sessions and completed requests remain terminal.

The in-process service cannot reattach inherited stdin/stdout after a hard
process crash, so it must not claim recovered live ownership.

## Decision 6: Rust registry owns launch truth

Rust holds binary candidates, version probes, launch arguments and profile
rules for Neko Core, Gemini CLI and Codex. TypeScript retains product-facing
metadata and adapter selection but no executable path or launch argument
table. Detection does not reveal resolved paths to the WebView. Rust resolves
and probes an absolute canonical executable and launches that exact path; a
later workspace `cwd` therefore cannot change which executable is selected.
Slow provider probes run outside the global lifecycle lock. Request identity
is durably accepted first and completed idempotent replay is resolved before a
new probe, so unrelated sessions remain responsive without making replay
depend on current provider availability.

## Decision 7: Runtime replacement is a new Run

The compatibility UI still uses one visible Neko session as its Task identity.
Each `RuntimeRegistry` instance ID becomes a fresh Run and Environment ID.
Provider continuation remains the opaque `backendSessionId`; it never makes a
new OS process reopen a terminal Run. This preserves the invariant
`Task != Run != AgentSession != process` before the full ADE task UI exists.

Provider stdout EOF is not an exit signal. The Rust reaper retains the child
in the authority map and uses non-blocking exit polling, so cancellation and
other lifecycle operations remain available even when a provider closes or
redirects stdout while continuing to run.

## Rejected alternatives

- **Keep raw spawn behind TypeScript**: application abstraction is not a
  native security boundary.
- **Standalone daemon immediately**: broadens packaging and recovery surface
  before the protocol is proven.
- **Persist every provider line**: creates secret, volume and ownership risks.
- **Global SQLite autoincrement as event order**: couples domain ordering to a
  single database and complicates future local/cloud stream composition.
- **Worktree in the same PR**: adds a second durable resource owner before
  session authority is stable.
