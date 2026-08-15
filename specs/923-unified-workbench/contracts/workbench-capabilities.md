# Contract: Workbench capabilities

## Host invariants

| Capability | Desktop | Hosted web |
| --- | --- | --- |
| Local process | May be true when Tauri IPC is available | Always false |
| Local workspace | May be true through approved native commands | Always false |
| Native window/tray | May be true | Always false |
| Secure native secret store | May be true | False until a separate web credential design exists |
| Remote runtime/service | True when network policy allows | True when configured |

Unknown host evidence resolves to the hosted-web-safe capability set.

## Runtime driver invariants

- The shell consumes normalized `DriverEvent` values only.
- A driver declares capabilities before use.
- Provider sessions stay opaque; Wiii stores only stable identifiers required
  for resume.
- Missing capability throws/fails visibly. It is never inferred by driver kind.
- Permission dismissal resolves to decline/cancel.
- Provider process exit does not confirm an in-flight mutation.

## Account invariants

- Wiii account and provider account are separate.
- Account metadata may include non-secret auth mode, plan label, and readiness.
- Tokens, cookies, refresh credentials, and provider credential files are not
  copied into Wiii stores, logs, telemetry, or backend requests.
- Codex browser/device login is initiated and owned by App Server.
- Claude subscription login is unavailable in public builds without provider
  approval.

## Knowledge invariants

- Runtime readiness and knowledge readiness are independent.
- A failed knowledge connection cannot disable local prompt/cancel/resume.
- Tenant-scoped retrieval is authorized by Wiii Service.
- Evidence becomes model-visible only after its context event is durably
  committed.
- Replay uses the recorded evidence; it does not silently rerun retrieval and
  pretend the result is identical.
