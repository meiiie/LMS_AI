# Feature Specification: Unified Wiii Workbench

**Feature Branch**: `codex/923-feat-unified-workbench`
**Created**: 2026-08-16
**Status**: In progress
**Issue**: #923
**Input**: Make the Neko Chill workbench the local-first Wiii experience without losing RAG, memory, managed services, provider-owned accounts, or a future hosted-web path.

## User Scenarios & Testing

### User Story 1 - Open one local-first workbench (Priority: P1)

A desktop user opens Wiii directly into a useful workspace. They can create or
resume a local agent session without configuring a server or Wiii account, and
they do not have to choose between two separate applications.

**Why this priority**: The current pre-auth mode split is the main cause of the
broken first-run flow and prevents capabilities from composing naturally.

**Independent Test**: Clear persisted app selection and authentication, start
the app, choose a workspace and detected local runtime, and complete a turn
without any network request to Wiii Service.

**Acceptance Scenarios**:

1. **Given** a fresh desktop install, **When** Wiii starts, **Then** the unified
   Workbench opens without a server or account gate.
2. **Given** a prior local session, **When** Wiii restarts, **Then** its local
   transcript and provider continuation resume through the existing durable
   session contract.
3. **Given** a user needs managed capabilities, **When** they open Connections,
   **Then** Wiii Service appears as an optional connection rather than another
   product mode.

---

### User Story 2 - Compose knowledge without changing agent (Priority: P1)

A user can keep the selected runtime while enabling project files, Wiii
Knowledge, or other knowledge sources. If a remote source is unavailable, the
local agent continues and the missing capability is shown clearly.

**Why this priority**: RAG and memory are valuable product capabilities and
must not disappear when the shell becomes local-first.

**Independent Test**: Run the same local session with Wiii Knowledge connected,
disconnect the service, and verify citations/context are recorded when used
while local prompts remain available after disconnection.

**Acceptance Scenarios**:

1. **Given** an authenticated Wiii Service connection, **When** a session uses
   Wiii Knowledge, **Then** retrieved evidence and citations reach the runtime
   through an explicit model-visible event.
2. **Given** Wiii Knowledge is disconnected, **When** the user sends a local
   prompt, **Then** the prompt proceeds without remote RAG and the UI displays
   the degraded knowledge state.
3. **Given** evidence belongs to an organization, **When** retrieval runs,
   **Then** the existing server-authorized tenant scope remains authoritative.

---

### User Story 3 - Connect a provider-owned agent account (Priority: P2)

A user can select Codex as an installed runtime and use the official Codex
App Server account flow. Codex owns ChatGPT/API credentials, plan state, model
catalog, approvals, and provider thread continuation; Wiii owns the visible
workspace ledger and never copies provider secrets.

**Why this priority**: It provides subscription-backed runtime choice without
turning Wiii into a credential broker.

**Independent Test**: With a disposable Codex test process, initialize,
observe signed-out state, complete a device-code/browser challenge, list models,
start a thread, stream a turn, resolve an approval, interrupt, dispose, and
resume by provider thread id.

**Acceptance Scenarios**:

1. **Given** Codex is installed but signed out, **When** the user connects it,
   **Then** Wiii displays the challenge returned by App Server and never handles
   raw ChatGPT tokens.
2. **Given** Codex reports available models, **When** a model is selected,
   **Then** Wiii stores only the stable model id and displays provider-reported
   metadata.
3. **Given** a provider approval request, **When** the user dismisses it,
   **Then** Wiii sends a deny/cancel decision and never infers approval.

---

### User Story 4 - Use the same product on hosted web (Priority: P2)

A web user sees the same Wiii product language and capability model, but the
browser only offers remote runtimes and remote knowledge services. Native
process, arbitrary local filesystem, tray, and window capabilities are absent.

**Why this priority**: A host-aware contract now prevents a desktop-only
architecture from forcing a future rewrite or an unsafe browser polyfill.

**Independent Test**: Build and open the hosted target with no Tauri globals;
verify native capabilities are absent, local runtime actions are unavailable,
and the managed-service connection path remains usable.

**Acceptance Scenarios**:

1. **Given** the hosted build, **When** the shell evaluates capabilities,
   **Then** it reports a web host with no local process or unrestricted
   filesystem access.
2. **Given** no remote runtime connection, **When** a web user opens Wiii,
   **Then** a useful connection-first empty state appears rather than inert
   local runtime controls.
3. **Given** an authenticated remote runtime later exists, **When** it exposes
   the shared driver contract, **Then** the same transcript/workspace shell can
   consume its events.

---

### User Story 5 - Keep account and legal boundaries honest (Priority: P3)

A user can distinguish a Wiii account, a provider subscription, and an API key.
Claude is offered through API/cloud credentials unless Anthropic explicitly
approves a subscription-backed third-party integration.

**Why this priority**: Clear ownership prevents credential leaks, surprise
billing, misleading UX, and provider-policy violations.

**Independent Test**: Inspect runtime cards and connection states for local,
Codex, Claude API, and Wiii Service; verify each card identifies who owns auth,
billing, and data transport.

**Acceptance Scenarios**:

1. **Given** the user signs into Wiii Service, **When** they inspect Codex,
   **Then** Codex remains independently signed in or signed out.
2. **Given** no Anthropic partner approval is configured, **When** the user
   selects Claude, **Then** Wiii offers supported API/cloud credentials and
   does not offer Claude.ai subscription login.

### Edge Cases

- Persisted legacy mode is `wiii`: migrate the preference to the unified shell
  without deleting either local sessions or cloud authentication.
- Wiii Service is configured but offline: keep local runtime actions enabled.
- A model-visible knowledge event cannot be durably written: fail before the
  runtime request instead of sending unreplayable context.
- A provider process exits during mutation: retain `unknown_outcome`; do not
  silently replay.
- Hosted web code is opened inside Tauri or desktop code in a normal browser:
  derive capability from runtime evidence, never user-agent strings.
- Codex changes an event shape: ignore unknown notifications safely and surface
  a protocol error for required response fields.
- A provider has multiple auth sources: display the source reported by the
  provider and do not infer billing from environment variables.

## Requirements

### Functional Requirements

- **FR-001**: Wiii MUST expose one Workbench entry on desktop instead of a
  binary pre-auth product mode gate.
- **FR-002**: The Workbench MUST start local-first and MUST NOT initialize Wiii
  Service polling or OAuth until the user connects or opens a managed surface.
- **FR-003**: Runtime, model, knowledge, tools, Wiii account, and provider
  account MUST remain independently represented capabilities.
- **FR-004**: Existing ACP session persistence, permission, cancellation,
  workspace, artifact, and `unknown_outcome` contracts MUST remain intact.
- **FR-005**: `maritime-ai-service` MUST remain the authoritative managed
  service for organization-scoped RAG, memory, integrations, and sync.
- **FR-006**: Remote knowledge failure MUST degrade only that capability and
  MUST NOT block a healthy local runtime.
- **FR-007**: Every retrieved fact sent to a model MUST be represented in the
  ordered session event ledger with source identity and citation metadata.
- **FR-008**: The host contract MUST explicitly advertise process, filesystem,
  native window, secure secret store, and remote transport capabilities.
- **FR-009**: Hosted web MUST fail closed for process spawn, arbitrary local
  filesystem, native window, and tray capabilities.
- **FR-010**: Codex integration MUST use the official App Server protocol,
  provider-owned login, and provider thread identifiers.
- **FR-011**: Wiii MUST NOT read or copy Codex/Claude browser cookies, token
  stores, or subscription credentials.
- **FR-012**: Public Claude integration MUST use supported API/cloud
  authentication unless written Anthropic approval enables another path.
- **FR-013**: Unknown runtime capabilities, models, commands, and auth states
  MUST remain unavailable rather than being guessed by the UI.
- **FR-014**: Desktop, hosted web, and existing embed builds MUST compile from
  the same typed capability vocabulary.
- **FR-015**: Legacy Wiii Cloud UI and stores MUST remain available as a
  compatibility surface until driver parity is proven; removal requires a
  separate evidenced change.

### Key Entities

- **WorkbenchHost**: The execution environment and the native/remote
  capabilities it can honestly provide.
- **RuntimeDefinition**: A discoverable agent runtime with transport, account
  ownership, model ownership, and host requirements.
- **RuntimeConnection**: One live provider instance attached to a Wiii session.
- **KnowledgeConnection**: One local or remote evidence source with readiness,
  scope, and citation support.
- **AccountConnection**: Wiii-managed or provider-managed identity metadata;
  never a copied provider secret.
- **WorkbenchSession**: Local UI/event authority plus opaque provider session id
  and selected capability references.
- **ModelVisibleContextEvent**: Durable evidence that reconstructs exactly what
  external knowledge entered a model request.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A fresh desktop user reaches a local new-session surface without
  entering a server URL or account credential.
- **SC-002**: Existing Neko session contract tests remain green and no local
  transcript is migrated destructively.
- **SC-003**: A Wiii Service outage leaves local send, cancel, resume, file, and
  permission actions available.
- **SC-004**: Contract tests prove hosted web exposes zero native-only
  capabilities.
- **SC-005**: Codex fixture tests cover initialize, account state, model list,
  thread start/resume, streaming, approval, interruption, and disposal.
- **SC-006**: TypeScript, focused/full Vitest, web/embed builds, Cargo checks,
  and native/browser acceptance pass with documented evidence.

## Assumptions

- The current ACP driver/event ledger is retained and generalized, not
  rewritten.
- Hosted web initially relies on Wiii Service; it does not execute agents in
  the browser.
- Wiii Service auth remains independent of external runtime auth.
- Codex App Server is available only when the official Codex binary is
  installed; Wiii does not bundle it in this feature.
- Claude subscription login remains unavailable in public Wiii unless provider
  terms or written approval change.
