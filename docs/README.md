# Wiii documentation

This is the canonical documentation map for Wiii. It describes the product as
it exists now: an open AI workbench and durable agent runtime. Historical
audits, sprint handoffs, and superseded host-specific guides remain available in
Git history but are not product documentation.

## Start here

| Document | Use it for |
| --- | --- |
| [Project mental model](WIII_PROJECT_MENTAL_MODEL.md) | Product boundaries and shared vocabulary |
| [Codebase map](architecture/WIII_CODEBASE_MAP.md) | Finding the owning package and tests |
| [Workbench identity and ACP](architecture/WIII_WORKBENCH_IDENTITY_AND_ACP.md) | Product naming and durable local-agent sessions |
| [Unified Workbench](architecture/WIII_UNIFIED_WORKBENCH.md) | Desktop/web host authority, runtime/account ownership, and optional knowledge composition |
| [Wiii operating model](operations/WIII_SYSTEM_CONTROL_PLANE.md) | Runtime invariants and diagnosis |
| [Release standard](releases/WIII_RELEASE_STANDARD.md) | Versioning, signing, provenance, and publication |

## Product and architecture

- [Wiii Connect](architecture/wiii-connect/README.md) — governed external
  capabilities and adapters.
- [Backend architecture](../maritime-ai-service/docs/architecture/SYSTEM_ARCHITECTURE.md)
  — Wiii Core runtime and service boundaries.
- [Backend request flow](../maritime-ai-service/docs/architecture/SYSTEM_FLOW.md)
  — HTTP/SSE execution and side-effect lifecycle.
- [Backend API guide](../maritime-ai-service/docs/api/README.md) — endpoint
  families, authentication, and OpenAPI discovery.
- [Wiii Connect LMS adapter](../maritime-ai-service/docs/integration/WIII_CONNECT_LMS_ADAPTER.md)
  — the retained LMS interoperability and security contract.
- [Desktop engineering guide](../wiii-desktop/README.md) — Wiii Workbench,
  Neko Chill, workspace pane, and local development.

## Operations and governance

- [Operations index](operations/README.md)
- [Repository harness](operations/WIII_REPOSITORY_HARNESS.md)
- [GitHub governance](operations/WIII_GITHUB_GOVERNANCE.md)
- [Branch protection](operations/WIII_BRANCH_PROTECTION.md)
- [Documentation governance](operations/WIII_DOCUMENTATION_GOVERNANCE.md)
- [Security policy](../SECURITY.md)

## Brand and research

- [Neko Family v1](assets/brand/neko-family-v1/README.md) — approved identity,
  source assets, exports, and verification.
- [Neko Motion Lab](research/neko-motion-lab/README.md) — mascot state and
  animation research.
- [Assets policy](assets/README.md) — what belongs in source control.

## Documentation policy

- A canonical page describes current behavior and names a source of truth.
- Integration-specific behavior lives under the adapter, not in the Wiii
  product definition.
- Plans are retained only while active or when they record a durable decision.
- Generated reports, test output, release binaries, and local research clones
  stay outside canonical documentation.
- Superseded documents are deleted after durable conclusions are promoted;
  Git history is the archive.
