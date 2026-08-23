# Verification Quickstart

From repository root:

```powershell
cargo test --manifest-path wiii-desktop/src-tauri/Cargo.toml

Set-Location wiii-desktop
npx vitest run src/__tests__/neko/control-protocol.test.ts src/__tests__/neko/provider-registry.test.ts src/__tests__/neko-chill/driver-factory.test.ts src/__tests__/neko-chill/runtime-manager.test.ts src/__tests__/neko-chill/neko-persistence.test.ts src/__tests__/neko-chill/session-events.test.ts src/__tests__/neko-chill/codex-bootstrap-identity.test.ts src/__tests__/neko-chill/phase6-polish.test.ts
npx tsc --noEmit
npm run build:embed
```

Repository checks:

```powershell
& .\.specify\scripts\powershell\check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks
git diff --check
git status --short
```

Expected invariants:

- the WebView cannot name an executable, argument vector or PID;
- Rust resolves only registered Neko/Gemini/Codex launch contracts;
- Rust launches the exact canonical executable that passed its bounded probe;
- repeated request IDs never repeat a side effect;
- caller retries after an unresolved start response reuse one request/session
  identity;
- completed/failed request IDs have a 90-day replay window, while uncertain
  identities are never pruned automatically;
- a proven `provider_busy` rejection retries only with a fresh request ID;
- overlapping identical provider frames receive distinct request IDs, while a
  bounded IPC retry of one logical frame reuses that frame's original ID;
- a later caller invocation with identical bytes receives a fresh ID; unresolved
  caller-level retry is never inferred from frame content;
- event sequence is monotonic within a run stream and replay is cursor-based;
- lifecycle state and its matching durable event commit or roll back together;
- start request identity, `Starting/Accepted` projection and creation event
  commit or roll back together;
- provider probing and exit observation never block unrelated lifecycle work;
- shutdown closes start admission before process cleanup;
- Unix provider-probe captures and the journal database/WAL/SHM files are
  owner-only;
- Unix desktop packages build, but local provider launch rejects before spawn
  until Wiii has containment that a same-UID child cannot escape;
- stdout EOF alone never releases a still-running provider process;
- Windows provider descendants remain owned by one Job Object even after an
  intermediate and leader exit;
- live exit delivery cannot mark cleanup complete without
  `terminationProven: true` and `terminalStatePersisted: true`;
- live exit handlers remain silent while either proof is missing, and
  `session/list` flushes any retained verified terminal fact before hydration;
- Windows drive/UNC casing aliases derive one bootstrap identity while POSIX
  case and legal backslash distinctions remain intact;
- native lifecycle checkpoints commit before the compatible transcript, so a
  transcript failure cannot silently hide a native side effect;
- hydration repairs the sequence high-water mark when a validated native-first
  checkpoint is one generation ahead of the compatible transcript;
- cancellation and session hydration fail closed during the process monitor's
  explicit exit-supervision hand-off;
- a runtime missing from the live registry is unobserved cleanup and therefore
  produces a blocking uncertainty fact rather than a successful detach;
- replacing a local runtime preserves Task identity but creates a fresh Run;
- uncertain recovery becomes `unknown_outcome`, never automatic retry;
- restored UI sessions reconcile native session state and replay cursor before
  hydration becomes usable;
- provider frames and credentials are absent from the SQLite lifecycle schema.
