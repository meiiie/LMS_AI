# Verification Quickstart

From repository root:

```powershell
cargo test --manifest-path wiii-desktop/src-tauri/Cargo.toml

Set-Location wiii-desktop
npx vitest run src/__tests__/neko/control-protocol.test.ts src/__tests__/neko/provider-registry.test.ts src/__tests__/neko-chill/driver-factory.test.ts src/__tests__/neko-chill/runtime-manager.test.ts
npx tsc --noEmit
npm run build:embed
```

Repository checks:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
specify check
git diff --check
git status --short
```

Expected invariants:

- the WebView cannot name an executable, argument vector or PID;
- Rust resolves only registered Neko/Gemini/Codex launch contracts;
- repeated request IDs never repeat a side effect;
- event sequence is monotonic within a run stream and replay is cursor-based;
- uncertain recovery becomes `unknown_outcome`, never automatic retry;
- provider frames and credentials are absent from the SQLite lifecycle schema.

