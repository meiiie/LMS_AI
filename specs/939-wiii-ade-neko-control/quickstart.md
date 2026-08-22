# Verification Quickstart

From `wiii-desktop/`:

```powershell
npx vitest run src/__tests__/ade/domain.test.ts src/__tests__/neko/control-protocol.test.ts src/__tests__/neko/provider-registry.test.ts src/__tests__/neko-chill/runtime-manager.test.ts src/__tests__/neko-chill/session-events.test.ts
npx tsc --noEmit
```

Repository checks:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
specify check
git diff --check
git status --short
```

Expected behavior:

- valid task/run/session graphs return no diagnostics;
- dangling and cross-project relationships return stable diagnostic codes;
- unknown control versions/methods/providers fail closed;
- Neko/Gemini/Codex launch contracts resolve from one registry;
- newly attached runtimes include a capability snapshot;
- legacy runtime-attached events without the snapshot remain valid.
