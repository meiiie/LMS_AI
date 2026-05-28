# Feature Specification: Wiii Connect Adapter V1

**Feature Branch**: `codex/730-audit-wiii-connect-adapter-v1`
**Created**: 2026-05-27
**Status**: Contract implemented; local live Composio acceptance passed #780
**Input**: User request to audit OpenHuman Connections/Composio and design Wiii
Connect Adapter V1 before enabling real Composio execution.

## User Scenarios & Testing

### User Story 1 - Safe Connection State (Priority: P1)

As a Wiii user, I can see whether a provider is connected without Wiii implying
the agent can already act through it.

**Why this priority**: This prevents false confidence and prevents connected
OAuth state from becoming accidental execution permission.

**Independent Test**: Unit tests normalize provider statuses and prove pending
connections are not baseline-ready.

**Acceptance Scenarios**:

1. Given a Composio-style `PENDING` connection, when Wiii normalizes it, then
   the state is `waiting` and baseline-ready is false.
2. Given an `ACTIVE` connection for an enabled provider, when Wiii normalizes it,
   then the state is `connected` but gateway checks still decide execution.

### User Story 2 - Fail-Closed Execution Gateway (Priority: P1)

As Wiii runtime, I can reject external actions unless provider, path, action,
scope, and approval evidence all pass.

**Why this priority**: External tools can read or mutate real user accounts.
Gateway policy must be deterministic before provider calls exist.

**Independent Test**: Unit tests call the gateway with wrong path, uncurated
action, missing approval, and allowed cases.

**Acceptance Scenarios**:

1. Given a connected provider, when the requested action is not curated, then
   execution is denied.
2. Given a curated apply action without approval evidence, when the gateway runs,
   then execution is denied.
3. Given connected provider, curated action, allowed path, required scope, and
   approval evidence, when the gateway runs, then execution is allowed.

### User Story 3 - Privacy-Safe Metadata (Priority: P2)

As a maintainer, I can inspect registry and connection metadata without exposing
tokens, API keys, provider payloads, or approval tokens.

**Why this priority**: Wiii needs observability, but connection metadata can be
sensitive.

**Independent Test**: Unit tests serialize public metadata and assert vault
paths and secret-like values are absent.

**Acceptance Scenarios**:

1. Given a vault secret reference, when public metadata is serialized, then only
   `vault_ref_present` is visible.
2. Given a provider required secret field, when public metadata is serialized,
   then the field key is visible but no secret value exists.

### Edge Cases

- OAuth state is pending or stale after a browser flow.
- Provider is connected but has no curated agent action catalog.
- User has read scope but asks Wiii to write or apply.
- Action belongs to a connected provider but the active product path is casual
  chat.
- Provider returns raw URLs or provider payloads in errors.

## Requirements

### Functional Requirements

- **FR-001**: System MUST distinguish connection state from agent-ready state.
- **FR-002**: System MUST normalize provider statuses into a provider-neutral
  lifecycle state.
- **FR-003**: System MUST define a registry entry for external provider
  adapters.
- **FR-004**: System MUST keep vault references opaque in public metadata.
- **FR-005**: System MUST deny external execution by default.
- **FR-006**: System MUST require provider enabled state, agent-ready state,
  matching live connection, allowed path, curated action, and required scope.
- **FR-007**: System MUST require approval evidence for apply-style external
  mutations.
- **FR-008**: System MUST produce privacy-safe audit event metadata.
- **FR-009**: System MUST document OpenHuman/Composio source findings before
  enabling Composio.

### Key Entities

- **Provider Registry Entry**: Declares provider kind, auth mode, enabled state,
  path allowlist, curated actions, and required fields.
- **Vault Secret Reference**: Opaque pointer to credential material.
- **Connection Record**: Live connection state and scope grants.
- **Execution Request**: Provider action request after path selection.
- **Execution Decision**: Deterministic allow/deny result.
- **Audit Event**: Privacy-safe ledger record around action execution.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Unit tests prove pending/error provider states do not become
  agent-ready.
- **SC-002**: Unit tests prove gateway denies uncurated action, wrong path, and
  missing approval.
- **SC-003**: Unit tests prove public metadata omits vault paths and raw secret
  values.
- **SC-004**: Architecture docs explicitly state Composio is not enabled until
  vault, OAuth callback, scope policy, gateway, and audit ledger are in place.

## Current Implementation Status

As of 2026-05-29, Wiii has implemented the Adapter V1 contract, backend-owned
provider registry, Composio adapter configuration boundary, provider-managed
vault references, signed callback state, durable connection and audit storage,
activation readiness projection, curated read-only action catalog, execution
gateway, desktop Wiii Connect surface, and operator acceptance harness.

Local #780 acceptance has proven the flow with real Composio credentials, a
Gmail auth config, a live connected account, sanitized harness output,
read-only Gmail execution, browser Wiii Connect evidence, and Facebook
connection-only OAuth. Production or staging rollout still requires operators
to configure the same flags/secrets in that target environment and rerun the
acceptance harness against the deployed backend before enabling users there.

## Assumptions

- Wiii will start with a server-side Composio adapter, not direct frontend API
  key mode.
- Existing Wiii auth/org boundaries remain the source of user and tenant
  identity.
- Composio is an adapter behind Wiii Connect, not the foundation of Wiii
  Connect.
