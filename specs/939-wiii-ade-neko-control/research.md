# Research and Architecture Decisions

**Issue**: #939

**Date**: 2026-08-23

## Decision 1: Wiii owns work; Neko owns execution

Wiii ADE is authoritative for project, task, specification, review, evidence
and human decision state. Neko Chill is authoritative for local execution
lifecycle, provider discovery, process ownership and normalized execution
events. Provider runtimes retain their opaque conversation/session state.
Wiii Service retains identity, organization, managed execution, knowledge,
memory, policy, audit and synchronization state.

This avoids duplicating provider history and prevents an agent process or chat
thread from becoming the product-level task identity.

## Decision 2: Task, run and session are separate

One task may have multiple runs for retry, best-of-N, local/cloud handoff or a
writer/reviewer workflow. One run may contain multiple agent sessions. A
provider resume does not create a new task. This feature encodes and validates
those relationships before adding persistence or UI.

## Decision 3: Neko Control Protocol is Wiii-native

ACP, Codex App Server and future OpenCode/Claude interfaces remain adapters.
Neko Control Protocol describes what the ADE needs from the execution fabric:
provider discovery, session lifecycle, approvals and normalized events. It is
not a wrapper that reduces every provider to ACP and it retains a bounded
provider-extension channel.

## Decision 4: Start with an in-process boundary

The current Tauri/Rust process table already owns spawned child processes more
safely than React state. The first implementation introduces a typed control
client and removes raw command knowledge from stores/factories. A later issue
can move the same boundary to a crash-independent Rust daemon plus SQLite WAL.

Shipping a pretend daemon, empty SQLite schema or generic RPC server now would
add complexity without improving runtime survival.

## Decision 5: One registry, two runtime objects

`ProviderRegistry` is the durable catalog: identity, integration, auth owner,
launch contract and baseline capability metadata. The existing
`RuntimeRegistry` remains the owner of live driver bindings and disposal.
They solve different problems and must not be merged.

## Decision 6: Capability snapshots fail closed

The snapshot stores normalized booleans for common capabilities. `false`
means the session did not establish that capability at snapshot time; the UI
does not guess whether it was unsupported or merely unreported. Bounded
JSON-scalar extensions preserve provider-specific facts without storing raw
events or secrets.

## Rejected alternatives

- **UI redesign first**: would entrench the Local/Managed mode taxonomy.
- **Add providers directly to the current factory**: duplicates metadata and
  conditionals.
- **ACP as internal ontology**: loses native provider semantics and couples
  Wiii to an evolving external protocol.
- **Go daemon now**: adds a fourth production language despite the existing
  Rust host.
- **Full Rust daemon in this PR**: too broad to review safely alongside the
  ontology and compatibility work.
