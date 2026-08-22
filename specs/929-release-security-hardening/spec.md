# Feature Specification: Release and Desktop Trust Hardening

**Feature Branch**: `929-release-security-hardening`

**Created**: 2026-08-23

**Status**: Ready for implementation

**Issue**: [#929](https://github.com/meiiie/wiii/issues/929)

## User Scenarios & Testing

### User Story 1 - Trust the installed desktop boundary (Priority: P1)

As a desktop user, I can open Wiii knowing the short-lived splash page cannot
read local state, open URLs, call network services, show notifications, select
files, or start an agent process.

**Independent Test**: Build the Tauri application, inspect the compiled
capability manifest, and prove that only `close_splash` is available to the
`splashscreen` label while the main window retains its required workflows.

**Acceptance Scenarios**:

1. **Given** the splash window is running, **when** it completes startup,
   **then** it may close itself and reveal the main window.
2. **Given** the splash window is compromised, **when** it attempts a store,
   dialog, shell, notification, HTTP, file, or agent command, **then** Tauri
   denies the request.
3. **Given** the production desktop bundle, **when** its pages load, **then** a
   non-null Content Security Policy constrains executable and network content.

---

### User Story 2 - Read one authoritative license (Priority: P1)

As a user, contributor, or distributor, I see AGPL-3.0-only for Wiii core and
Apache-2.0 only at the reserved SDK boundary in every first-party metadata
surface.

**Independent Test**: Run the release metadata checker and mutate each guarded
license field in a fixture; every mismatch must fail with the affected path.

**Acceptance Scenarios**:

1. **Given** the repository root, desktop bundle, Python package, npm package,
   and Cargo package, **when** license metadata is inspected, **then** each core
   surface reports AGPL-3.0-only.
2. **Given** the `sdk/` boundary, **when** its license and SPDX notice are
   inspected, **then** they report Apache-2.0 without relicensing core code.

---

### User Story 3 - Distinguish candidate source from a stable release (Priority: P1)

As an operator or downloader, I can tell whether a version is only being
prepared or has a real immutable tag and GitHub Release.

**Independent Test**: Run release validation in candidate mode and tag mode.
Candidate validation accepts non-empty Unreleased notes; tag validation fails
unless a dated matching version section exists.

**Acceptance Scenarios**:

1. **Given** no `wiii-v1.2.0` tag or GitHub Release exists, **when** README,
   SECURITY, and changelog are read, **then** none calls 1.2.0 stable or offers
   nonexistent downloads.
2. **Given** a stable tag workflow, **when** the changelog lacks a dated matching
   section, **then** publication fails before packaging.
3. **Given** signing credentials are absent, **when** a stable Windows build is
   attempted, **then** the existing signing gate fails closed.

### Edge Cases

- A user-configured remote Wiii Service endpoint must not justify unrestricted
  `https://**` access for every Tauri plugin request.
- Local development ports vary; loopback compatibility must be bounded and
  documented rather than silently widened to all remote origins.
- Visual artifacts use sandboxed blob iframes and may load approved runtime
  assets; the application CSP and the artifact-local CSP are separate controls.
- A previous MIT copy remains MIT under its historical grant; current metadata
  must not imply that new AGPL distributions revoke that grant.
- Copyright text such as "All rights reserved" is not itself a package license
  declaration and is not mechanically rewritten.

## Requirements

### Functional Requirements

- **FR-001**: The desktop bundle license MUST be `AGPL-3.0-only`.
- **FR-002**: Release validation MUST compare canonical core and SDK license
  surfaces and report path-specific drift.
- **FR-003**: The desktop application MUST ship with a non-null CSP derived from
  its actual local assets, fonts, IPC, loopback, WebSocket, blob, and worker use.
- **FR-004**: Capability files MUST be split by window and concern; only the
  splash capability may target `splashscreen`.
- **FR-005**: Tauri application commands MUST be declared to the app manifest so
  command permissions can be granted explicitly.
- **FR-006**: The splash command MUST reject calls from any window label other
  than `splashscreen`, even if capability configuration regresses.
- **FR-007**: Main-window HTTP plugin scope MUST remove unrestricted
  `https://**` and retain only origins required by supported desktop operation.
- **FR-008**: Candidate validation MUST not require a release tag or dated
  release section; stable tag validation MUST require both.
- **FR-009**: Public documentation MUST state the actual current release state
  and MUST NOT link a nonexistent version as though it were downloadable.
- **FR-010**: No implementation may publish an unsigned candidate as stable.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Zero shared capability files target both `main` and
  `splashscreen`.
- **SC-002**: Zero `https://**` entries remain in Tauri HTTP scopes.
- **SC-003**: `app.security.csp` is non-null and production desktop, web, and
  embed builds complete without CSP/schema errors.
- **SC-004**: Release-tool tests cover one success and at least one drift
  failure for license, candidate changelog, and stable changelog validation.
- **SC-005**: The GitHub repository, README, SECURITY, changelog, and release
  automation agree that no stable desktop release exists until a matching tag
  workflow publishes it.

## Assumptions

- `VERSION` remains the next coordinated product version; it is not proof of a
  published stable release.
- The current protected stable workflow and its Windows signing requirement
  remain authoritative.
- Configurable remote service endpoints remain a product requirement, but Tauri
  plugin access may be narrower than browser-native web access.
- P1 module refactors, feature-flag cleanup, dependency locking, and Docker
  hardening are tracked after these P0 gates and are not prerequisites here.
