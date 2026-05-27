# Tasks: Wiii Connect Adapter V1

**Input**: Design documents from `specs/730-wiii-connect-adapter-v1/`
**Prerequisites**: `plan.md`, `spec.md`

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

- [ ] T014 Add persistent provider registry API.
- [x] T014 Add backend-owned static provider registry for disabled Composio catalog.
- [ ] T015 Add persistent provider registry API.
- [ ] T016 Add OAuth start/callback routes for disabled Composio adapter.
- [ ] T017 Add vault integration or provider-managed secret reference storage.
- [ ] T018 Add frontend connection modal using Wiii backend routes.
- [ ] T019 Add browser acceptance for connect, poll, disconnect, gated scope, and denied execute cases.
