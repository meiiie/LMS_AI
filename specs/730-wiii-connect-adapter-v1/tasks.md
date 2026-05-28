# Tasks: Wiii Connect Adapter V1

**Input**: Design documents from `specs/730-wiii-connect-adapter-v1/`
**Prerequisites**: `plan.md`, `spec.md`
**Status Update 2026-05-29**: Adapter V1 contract and Wiii-owned Composio
control plane are implemented through follow-up slices. Local live Composio
acceptance in #780 passed with real credentials, a Gmail auth config, a live
connected account, read-only Gmail execution, browser Wiii Connect evidence,
and Facebook connection-only OAuth.

## Phase 1: Audit And Design

- [x] T001 Read repository governance and Wiii Connect V0 docs.
- [x] T002 Audit OpenHuman frontend Composio RPC, hooks, modal, required-field registry.
- [x] T003 Audit OpenHuman core Composio client, ops, OAuth handoff, and action tool policy.
- [x] T004 Review current Composio docs for sessions, connected accounts, connect links, and meta tools.
- [x] T005 Write source audit doc in `docs/operations/WIII_OPENHUMAN_COMPOSIO_SOURCE_AUDIT_2026-05-28.md`.

## Phase 2: Contract Implementation

- [x] T006 Add Adapter V1 dataclasses and gateway decision helper in `maritime-ai-service/app/engine/wiii_connect/adapter_v1.py`.
- [x] T007 Export Adapter V1 helpers from `maritime-ai-service/app/engine/wiii_connect/__init__.py`.
- [x] T008 Document Adapter V1 architecture in `docs/architecture/wiii-connect/ADAPTER_V1_DESIGN.md`.

## Phase 3: Verification

- [x] T009 Add unit tests for state normalization and agent-ready gating.
- [x] T010 Add unit tests for fail-closed gateway decisions.
- [x] T011 Add unit tests for public metadata redaction.
- [x] T012 Run focused pytest and ruff checks.
- [x] T013 Run `git diff --check` and inspect worktree.

## Phase 4: Next Slices

- [x] T014 Add backend-owned static provider registry for disabled Composio catalog.
- [x] T015 Add read-only provider registry and action catalog APIs.
- [x] T016 Decide persistent provider registry is out of scope for Adapter V1;
      the static backend registry remains the source of truth until provider
      onboarding needs runtime admin writes.
- [x] T017 Add authenticated Composio Connect Link and callback routes behind
      Wiii backend policy.
- [x] T018 Add provider-managed vault reference storage and durable
      connection/audit storage.
- [x] T019 Add frontend Wiii Connect surface using Wiii backend routes for
      provider registry, readiness, Connect Link, polling, and disconnect.
- [x] T020 Add backend/operator acceptance harness for readiness, Connect Link,
      connection polling, denied execute, optional read-only execute, and
      disconnect checks.
- [x] T021 Run live Composio acceptance with real credentials, Gmail auth
      config, and a connected account. Local #780 evidence passed on
      2026-05-29: readiness/gateway 12/12 and read-only execute 13/13.
- [x] T022 Run browser acceptance against the live connected Gmail account and
      confirm Wiii Connect shows connected/agent-ready state without raw
      connection IDs, provider payloads, or secrets. Local #780 browser smoke
      passed on 2026-05-29.

## Current Evidence

- Provider registry and API:
  `maritime-ai-service/app/engine/wiii_connect/provider_registry.py`,
  `maritime-ai-service/app/api/v1/wiii_connect.py`,
  `tests/unit/api/test_wiii_connect_api.py`.
- OAuth/session/callback boundary:
  `maritime-ai-service/app/engine/wiii_connect/connection_sessions.py`,
  `callback_state.py`, `callback_boundary.py`, and
  `app/api/v1/wiii_connect.py`.
- Vault and durable storage:
  `maritime-ai-service/app/engine/wiii_connect/vault.py`,
  `persistent_storage.py`, and
  `alembic/versions/049_create_wiii_connect_storage.py`.
- Scope policy, curated action catalog, and execution gateway:
  `adapter_v1.py`, `action_catalog.py`, `execution_gateway.py`, and
  `activation_readiness.py`.
- Composio provider adapter:
  `composio_adapter.py`.
- Frontend Wiii Connect surface:
  `wiii-desktop/src/components/connect/WiiiConnectPage.tsx` and
  `wiii-desktop/src/__tests__/wiii-connect-page.test.tsx`.
- Operator acceptance harness:
  `maritime-ai-service/scripts/wiii_connect_composio_acceptance.py` and
  `docs/operations/WIII_CONNECT_COMPOSIO_ACCEPTANCE_RUNBOOK.md`.
