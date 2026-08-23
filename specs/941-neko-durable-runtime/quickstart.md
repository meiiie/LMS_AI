# Verification Quickstart

From repository root:

```powershell
cargo test --manifest-path wiii-desktop/src-tauri/Cargo.toml

Set-Location wiii-desktop
npx vitest run src/__tests__/neko/control-protocol.test.ts src/__tests__/neko/provider-registry.test.ts src/__tests__/neko-chill/driver-factory.test.ts src/__tests__/neko-chill/runtime-manager.test.ts src/__tests__/neko-chill/neko-persistence.test.ts src/__tests__/neko-chill/session-events.test.ts
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
- event sequence is monotonic within a run stream and replay is cursor-based;
- lifecycle state and its matching durable event commit or roll back together;
- provider probing and exit observation never block unrelated lifecycle work;
- shutdown closes start admission before process cleanup;
- Unix provider-probe captures and the journal database/WAL/SHM files are
  owner-only;
- stdout EOF alone never releases a still-running provider process;
- replacing a local runtime preserves Task identity but creates a fresh Run;
- uncertain recovery becomes `unknown_outcome`, never automatic retry;
- restored UI sessions reconcile native session state and replay cursor before
  hydration becomes usable;
- provider frames and credentials are absent from the SQLite lifecycle schema.
