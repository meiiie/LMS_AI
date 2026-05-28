# Implementation Plan: Wiii Connect Adapter V1

**Branch**: `codex/730-audit-wiii-connect-adapter-v1` | **Date**: 2026-05-27 | **Spec**: `specs/730-wiii-connect-adapter-v1/spec.md`
**Input**: Feature specification from `specs/730-wiii-connect-adapter-v1/spec.md`

## Summary

Audit OpenHuman's Composio connection architecture and implement the first Wiii
Connect Adapter V1 contract. This slice adds deterministic policy objects and
unit tests, while keeping real Composio OAuth/execution disabled until vault and
runtime endpoints exist.

Status update 2026-05-29: follow-up slices have implemented the runtime
endpoints, provider-managed vault references, durable connection/audit storage,
Composio Connect Link and callback boundary, activation readiness, read-only
execution gateway, desktop Wiii Connect surface, and operator acceptance
harness. Local #780 acceptance passed with real Composio
credentials, a Gmail auth config, a live connected Gmail account, read-only
Gmail execution, browser Wiii Connect evidence, and Facebook connection-only
OAuth. Production or staging rollout still requires the same acceptance run
against that target environment before enabling general users.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastAPI backend codebase, dataclasses, pytest
**Storage**: Adapter V1 now has durable connection records and audit ledger
storage in `wiii_connect_connections` and `wiii_connect_audit_ledger`.
Provider registry remains static backend configuration by design for V1.
**Testing**: pytest unit tests
**Target Platform**: Wiii backend service
**Project Type**: backend contract and architecture docs
**Performance Goals**: Gateway decision is in-process and deterministic.
**Constraints**: No secrets, no provider payloads, no raw approval tokens in
public metadata.
**Scale/Scope**: One contract module plus docs/tests. No real provider calls.

## Constitution Check

- Preserve tenant/auth safety: pass, no provider calls or persistence added.
- Fail closed on external actions: pass, gateway denies by default.
- Keep changes scoped: pass, backend contract plus docs/tests only.
- No secrets committed: pass, tests use fake opaque strings only.
- Vietnamese-first UI: not applicable, no user-facing UI copy in this slice.

## Project Structure

```text
docs/
  architecture/wiii-connect/ADAPTER_V1_DESIGN.md
  operations/WIII_OPENHUMAN_COMPOSIO_SOURCE_AUDIT_2026-05-28.md
maritime-ai-service/
  app/engine/wiii_connect/adapter_v1.py
  tests/unit/test_wiii_connect_adapter_v1.py
specs/
  730-wiii-connect-adapter-v1/
    spec.md
    plan.md
    tasks.md
```

**Structure Decision**: Keep Adapter V1 inside the monorepo until Wiii-native
and at least one external provider prove the contract.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |
