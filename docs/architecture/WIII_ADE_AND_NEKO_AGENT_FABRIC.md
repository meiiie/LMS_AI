# Wiii ADE and Neko Agent Fabric

**Status:** Ontology and in-process durable runtime authority implemented;
product shell and standalone daemon planned

**Updated:** 2026-08-23

**Issues:** [#939](https://github.com/meiiie/wiii/issues/939),
[#941](https://github.com/meiiie/wiii/issues/941)

**Specifications:** [`specs/939-wiii-ade-neko-control/`](../../specs/939-wiii-ade-neko-control/),
[`specs/941-neko-durable-runtime/`](../../specs/941-neko-durable-runtime/)

## Product boundary

Wiii is evolving from a Workbench organized around local/managed conversation
surfaces into an Agentic Development Environment organized around durable work.

```text
Wiii ADE
Human + Project + Task + Spec + Run + Review + Evidence
    |
    | Neko Control Protocol
    v
Neko Chill
Local agent fabric + provider adapters + execution lifecycle
    |
    +-- Neko Core (ACP)
    +-- Gemini CLI (ACP)
    `-- Codex (App Server)

Wiii Service
Optional managed/data plane: identity, organization, sync, managed runners,
Knowledge, Memory, Connect, policy and audit
```

The ownership rule is:

> **Wiii owns work. Neko Chill owns execution. Providers own their sessions.
> Wiii Service owns managed and organization-scoped state.**

Neko Chill is not a local mode and Wiii Service is not a cloud mode. They are
different planes that may be composed in one run. For example, Codex can run
in a local worktree while Wiii Knowledge supplies authorized evidence through
Wiii Service.

## Work identity

The canonical work hierarchy is:

```text
Project -> Task -> Run -> AgentSession
```

- A `Task` describes the desired result.
- A `Run` is one attempt, environment or strategy for that task.
- An `AgentSession` is one provider-owned conversation bound to a run.
- An `Environment` describes where execution happens and is not a product
  mode.
- `Artifact`, `Evidence`, `Approval` and `AttentionItem` remain independently
  addressable records.

Therefore `Task != Run != AgentSession != Worktree`. Provider resume never
creates a new task, and best-of-N may create several runs for one task.

The dependency-free contract lives in
[`wiii-desktop/src/ade/domain.ts`](../../wiii-desktop/src/ade/domain.ts). Its
validator rejects dangling and cross-project relationships without inventing
repairs.

## Neko Control boundary

The versioned Neko Control Protocol is Wiii-native. ACP, Codex App Server and
future OpenCode/Claude interfaces remain adapters behind it; ACP is not the
internal ontology of Wiii.

The first contract defines initialization, provider/session lifecycle,
approval resolution, normalized execution events, typed errors and bounded
provider extensions. Unsupported versions, methods and providers fail before
process side effects.

The current authority is an in-process Rust `NekoRuntime` behind provider- and
session-scoped Tauri commands. React asks for an operation by provider, run,
environment and agent-session identity; Rust resolves the approved executable
and arguments, owns the child process, journals lifecycle facts and returns
replayable state. The TypeScript control client is a thin protocol adapter and
does not receive executable paths, PIDs or argument vectors.

On Workbench hydration, React lists the native records and consumes each
matching run stream from its last persisted cursor before the restored session
becomes usable, then re-reads the native session projection after replay. This
closes the race where a process becomes terminal during pagination. It is
read-model reconciliation, not a second authority: native `unknown_outcome`
and active sessions without a live renderer transport stay locked against
automatic respawn.

For a fresh start, Rust atomically commits the request identity, durable
`Starting/Accepted` session projection and `session.created` before any unlocked
workspace or provider-discovery I/O. A UI
reload during a slow filesystem lookup or probe therefore sees the accepted
owner and cannot infer that the Task is idle. Cancellation is terminal only after process-tree
termination succeeds; an unavailable process owner or failed OS tree kill is
recorded as `unknown_outcome`, never as permission to launch a replacement.
Windows launches are assigned to a kill-on-close Job Object while the leader is
still suspended; only then is execution resumed. Unix local-provider launches
currently reject before spawn: a POSIX process group is escapable, and a
same-UID provider can migrate out of a writable cgroup leaf. Linux and macOS
packages still build, but local Neko execution remains unavailable there until
an approved boundary prevents that migration. Live exit IPC carries both `terminationProven` and
`terminalStatePersisted`, so the renderer cannot mistake leader exit—or an
uncommitted journal transition—for complete cleanup. A verified exit whose
terminal transaction temporarily fails is retained in a dedicated durable
SQLite recovery record and retried on explicit cancellation or session-list
hydration. Recovery and retention skip the linked projection/request until the
exact terminal state, event and optional cancellation result reconcile
atomically. Exit handlers are
withheld until both proofs are true.

The compatibility client also bounds bootstrap output before a provider
adapter attaches: at most 256 frames and 8 MiB are retained. Overflow detaches
the renderer listeners and asks the native authority to cancel the same
logical start; a visible session cannot be deleted while that cancellation is
uncertain. When terminal native projections age out of the complete catalog,
Workbench records an explicit checkpoint-retirement fact instead of leaving a
permanent phantom respawn lock. Active and `unknown_outcome` projections are
never pruned automatically, and any uncertain live cleanup (close, delete,
workspace change, recovery, idle reap, or mode exit) persists a blocking
tombstone until a later native reconciliation proves a safe terminal state.
Cleanup success is a tagged outcome; it never depends on whether a JavaScript
rejection reason is truthy, so even `undefined`, `null`, `false`, `0`, or `""`
remain failures. Reason formatting is non-throwing; hostile or non-stringifiable
values fall back to a bounded generic explanation without losing the tombstone.
These runtime-only facts live in `neko-chill-native-runtime.json`; the shared
Workbench v2 transcript retains its previous-release vocabulary for rollback.

Phase 2A intentionally remains inside `Wiii.exe`. It is **not** a standalone,
crash-independent daemon: a graceful Wiii exit cancels owned children, while a
hard restart conservatively reports continuity loss or `unknown_outcome` from
the journal. Extracting the stable boundary to `neko-daemon` is a later phase.

## Provider registry and capability truth

The TypeScript `ProviderRegistry` is the product catalog for provider identity,
label, integration level, protocol and authentication owner. The Rust provider
registry is the only launch authority for executable candidates, probes,
approved arguments and profile validation. `RuntimeRegistry` separately owns
live TypeScript driver bindings and disposal. These catalogs and live bindings
solve different problems and must not be merged.

Current implemented provider paths are:

| Provider | Integration | Protocol | Authentication owner |
| --- | --- | --- | --- |
| Neko Core | ACP | ACP v1 | Neko Core/provider profile |
| Gemini CLI | ACP | ACP v1 | Gemini CLI |
| Codex | Native structured | Codex App Server | Codex/OpenAI |

Every newly attached known provider records a versioned capability snapshot.
The snapshot contains only normalized booleans and bounded JSON-scalar
extensions. It preserves what that historical session established even if the
installed provider later changes. Legacy events without the snapshot remain
readable; unknown providers do not receive guessed capabilities.

## What Wiii Service means

Wiii Service is the optional managed/data plane. It can supply:

- account and organization identity;
- managed or remote runners;
- Knowledge/RAG and citations;
- Memory and synchronization;
- Wiii Connect, MCP and external integrations;
- organization policy, approvals, audit and remote artifacts.

Using Wiii Service does not require moving local execution to the cloud. A run
may independently select a local provider/environment and remote knowledge.
Hosted web requires remote execution because a browser has no local process or
filesystem authority; that host constraint does not change the product model.

## Implementation truth on 2026-08-23

Implemented across the foundation and Phase 2A slices:

- ADE entity contracts and deterministic graph validation;
- Neko Control Protocol v1 envelopes, methods, events and typed errors;
- one provider registry for Neko Core, Gemini CLI and Codex;
- an in-process Rust runtime with one-writer file lease and SQLite WAL;
- Rust-owned provider resolution, approved arguments and process/session maps;
- request-id idempotency for start, provider-frame write and cancellation;
- atomic request/`Starting/Accepted`/creation-event admission and verified
  process-tree cancellation, with unproven termination converted to
  `unknown_outcome`;
- caller-level start retry retains the same logical identity after unresolved
  IPC delivery, including its original Run/Environment binding and buffered
  bootstrap/exit events across a fresh RuntimeRegistry preparation; the Codex
  account probe derives one host-aware workspace caller identity across retry,
  remount and WebView reload, including Windows drive/UNC separator and casing
  aliases; each new attempt receives a fresh Run, while a durable non-terminal
  Run blocks duplicate bootstrap;
  completed/failed identities have a 90-day replay window while uncertain
  identities are not automatically pruned;
- conservative recovery phases: `accepted`, `dispatched`,
  `side_effect_started`, `committed`, `completed`, `failed` and
  `unknown_outcome`;
- durable per-run event streams with monotonic sequence and bounded cursor
  replay;
- provider/session/events Tauri commands with no WebView permission for raw
  executable, argument vector, PID or unscoped stdin primitives;
- one TypeScript control client for discovery, replay and live transport;
- bounded aggregate bootstrap buffering, retained-start cancellation before
  deletion, explicit stale-checkpoint retirement, and strict newline-delimited
  provider frames even at EOF;
- rollback-readable v2 conversation snapshots plus an additive native runtime
  checkpoint companion; a validated native-first partial generation repairs
  only its sequence high-water mark, and uncertain close cleanup remains a
  durable respawn lock;
- exit supervision is published before the process-map hand-off, so hydration
  and cancellation fail closed instead of inventing missing ownership;
- shutdown releases lifecycle serialization and waits for every published exit
  supervisor to finish exact terminal reconciliation before native authority
  exits;
- shutdown admission closes before process drain; Windows probes use a
  producer-bounded pipe, and checked tree cleanup plus bounded reaping gate
  successful discovery; Unix provider discovery and execution both reject
  before spawn until non-escapable containment exists;
- provider discovery reports host containment as unsupported instead of
  mislabelling every Unix provider as not installed; one renderer write is one
  delimiter-free frame, and suspended Windows setup cleanup is checked and
  deadline-bounded;
- provider launch and discovery preserve post-spawn cleanup uncertainty as a
  machine-readable outcome; an admitted start becomes `unknown_outcome` rather
  than a retryable provider rejection when cleanup cannot be proven;
- Codex account bootstrap cleanup is serialized by a module-level owner outside
  React; failed cleanup remains retryable and blocks replacement launch;
- leaving Neko Chill enumerates retained control-client starts, refreshes that
  set after runtime preparation settles, and requires authoritative
  cancellation before recording a clean mode exit;
- failed renderer runtime cleanup retains a retryable scope instead of a cached
  rejection; later lifecycle operations reuse the provider's durable
  cancellation identity, retry only failed disposers, and block replacement
  until cleanup is proven;
- the Unix SQLite parent, database and WAL/SHM sidecars remain owner-only even
  though Windows is currently the only host authorized to probe or launch local
  providers;
- driver-observed capability facts and durable attach snapshots;
- backward-compatible loading of pre-snapshot local session events.

Not yet implemented and not implied by this document:

- a standalone Rust `neko-daemon` that survives `Wiii.exe` termination;
- durable provider stdout, transcript, tool delta or terminal replay (these
  remain live-only and provider/session persistence keeps its existing owner);
- persistent ADE Project/Task/Run UI and Attention Inbox;
- worktree/environment manager or OS sandbox;
- OpenCode, Claude, ACP v2 or generic PTY adapters;
- ADE editor/LSP/terminal/diff/preview shell;
- local/cloud handoff, best-of-N scheduler or autonomous agent teams.

Those features build on the contracts above in separate reviewable changes.
This distinction prevents in-process lifecycle durability from being mistaken
for provider-transcript replay or an independent daemon.

## Next dependency order

1. Extract the stable in-process Neko boundary to a standalone service only
   after its recovery and IPC contract is proven.
2. Add environment/worktree ownership and explicit isolation policy.
3. Build Attention and read models from durable facts before a fleet dashboard.
4. Replace the local/managed surface switch with task/run/environment
   composition in the Wiii ADE shell.
5. Add richer provider adapters through capability negotiation.
6. Add editor, terminal, diff, LSP, preview, evidence and review surfaces.

Advanced orchestration follows only after these deterministic boundaries are
durable.

## Native runtime risk and rollback

The native runtime changes executable authority, process ownership, Tauri
permissions and durable lifecycle state as one release boundary. Its main
risks are an incompatible renderer/native command pair, an unavailable journal,
or recovery semantics that disagree with a process side effect. Rollback must
therefore revert the **complete desktop release**. Do not partially restore raw
WebView spawn/stdin/PID permissions.

Keep `neko-runtime-v1.sqlite3`, `neko-chill-native-runtime.json`, session
snapshots, provider thread IDs, account records and recovery evidence intact.
The companion file contains the new runtime-only event vocabulary, leaving the
shared v2 session snapshots readable by the previous desktop release. An older
release may leave the additive journal/companion unused, but rollback must never
delete or reinterpret uncertain operations. Re-entry to a newer release must
run the documented recovery path.
