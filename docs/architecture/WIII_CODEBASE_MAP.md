# Wiii codebase map

**Status:** Canonical
**Updated:** 2026-08-16

## Top-level ownership

| Path | Owner and purpose |
| --- | --- |
| `wiii-desktop/` | Wiii Workbench: shared React UI, Tauri/web hosts, local and managed runtimes, sessions, workspace, previews, artifacts |
| `maritime-ai-service/` | Wiii Core: FastAPI, orchestration, providers, RAG, memory, policy, organizations, integrations, deployment |
| `docs/` | Current architecture, operations, research, release, and brand sources |
| `tools/release/` | Version synchronization, notes, hashes, and release manifest |
| `tools/wiii_self_harness/` | Repository contracts and runtime evidence registry |
| `specs/` | Spec Kit artifacts for active architecture-sensitive work |
| `.github/` | CI, release automation, issue forms, review, ownership, and dependency policy |
| `chaos/`, `loadtest/` | Explicitly invoked resilience and load tooling |

## Desktop map

| Path | Responsibility |
| --- | --- |
| `wiii-desktop/src/neko-chill/` | Local ACP workspace, durable session projection, runtime manager |
| `wiii-desktop/src/workbench/` | Host/capability derivation, surface bootstrap, provider ownership policy, optional Wiii Knowledge connection |
| `wiii-desktop/src/neko-chill/drivers/codex/` | Codex App Server account, model, thread, turn, approval, and stream adapter |
| `wiii-desktop/src/components/layout/` | Main shell, workspace panes, artifact and preview surfaces, window controls |
| `wiii-desktop/src/stores/` | Persisted UI, connection, settings, and Code Studio state |
| `wiii-desktop/src-tauri/src/` | Native commands, file access, tray, lifecycle, platform integration |
| `wiii-desktop/src-tauri/icons/` | Generated shipping derivatives of the approved Neko mark |
| `wiii-desktop/src/__tests__/` | UI and state contract tests |
| `wiii-desktop/scripts/` | Brand verification, browser probes, and build helpers |

The Tauri identifier, executable namespace, storage keys, and public product
name are separate concerns. Keep technical identifiers stable unless an
explicit migration protects installed state.

## Backend map

| Path | Responsibility |
| --- | --- |
| `app/api/v1/` | HTTP, SSE, admin, organization, host-action, Wiii Connect, and adapter routes |
| `app/services/` | Request lifecycle, orchestration, output, model policy, memory and background workflows |
| `app/engine/runtime/` | Wiii-owned runtime contracts and execution lanes |
| `app/engine/multi_agent/` | Agent planning, tool rounds, runtime ledgers, visual/document paths |
| `app/engine/wiii_connect/` | Provider/action planning and narrowed external capability execution |
| `app/engine/semantic_memory/` | Memory extraction, retrieval, maintenance, and provenance |
| `app/auth/`, `app/core/` | Authentication, authorization, configuration, middleware, tenant context |
| `app/repositories/`, `alembic/` | Durable data access and schema migrations |
| `tests/` | Unit, integration, property, security, and runtime contract tests |

## Change routing

- Session replay, ACP continuation, slash commands, model controls: start in
  `wiii-desktop/src/neko-chill/` and the ACP provider contract.
- Desktop/web authority or runtime/knowledge composition: start in
  `wiii-desktop/src/workbench/`; browser capabilities must fail closed.
- Files, diff, HTML/Markdown preview, workspace layout: start in desktop layout,
  workspace stores, and native file commands.
- Chat/SSE behavior: start at `app/api/v1/chat_stream.py`, then the coordinator,
  runtime, presenter, and desktop stream hook.
- External actions: start in Wiii Connect policy and provider workers. Treat LMS
  as an adapter, not a special global path.
- Identity, organization, ownership, approval, or secrets: include backend
  enforcement and adversarial tests; UI gating alone is insufficient.
- Release metadata or installer: use `tools/release/wiii_release.py` and the
  [release standard](../releases/WIII_RELEASE_STANDARD.md).

## Verification rule

Run the smallest focused suite during iteration, then the owning surface's full
gate. Cross-layer changes need both producer and consumer tests. Live external
claims require a registered, guarded evidence probe; synthetic output may prove
shape but not real provider success.
