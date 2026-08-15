# Wiii Operating Model

**Status:** Canonical
**Scope:** Product runtime, desktop shell, integrations, evidence, and release

## System boundary

Wiii is an open AI workbench composed of independently testable surfaces:

```text
Wiii Workbench (desktop/web)
        |
        | sessions, workspaces, approvals, artifacts
        v
Wiii Core runtime ---- ACP/provider runtimes
        |
        +---- Wiii Living (memory and context)
        +---- Wiii Host (files, tools, previews, actions)
        +---- Wiii Org (tenant and policy boundaries)
        +---- Wiii Connect (LMS, Composio, social, future adapters)
        +---- Wiii Data (retrieval and evidence)
```

The desktop shell owns interaction state and inspectability. Wiii Core owns
agent execution and durable runtime semantics. Connect adapters translate an
external system into governed capabilities; no adapter defines the product.

## Source-of-truth rules

| Concern | Source of truth |
| --- | --- |
| Product version | `VERSION` |
| User-visible changes | `CHANGELOG.md` |
| Durable ACP session | append/replay log plus checkpoint metadata |
| Model-visible facts | ordered session events presented to the model |
| Workspace state | explicit file/artifact records, not chat prose |
| External side effect | tool ledger with approval and outcome state |
| Live capability claim | runtime evidence registry plus raw probe artifact |
| Public binary | signed installer, checksum, manifest, commit, and provenance |

“Model-visible” means a fact can influence the model only after it has been
recorded as an ordered input/event in the session trace. UI-only state, an
unrecorded tool result, or a side effect inferred after a crash cannot silently
be treated as model knowledge. This makes replay, debugging, and recovery
honest.

## Runtime invariants

1. A session can be listed, loaded, replayed, resumed, and closed after the
   process that created it has exited.
2. A mutating tool call is checkpointed before execution.
3. After interruption, an unconfirmed mutation becomes `unknown_outcome`; it is
   not automatically repeated.
4. Permission grants are scoped and never broadened by session restoration.
5. Provider/model/profile/reasoning changes are explicit session events.
6. Workspace and artifact changes remain inspectable beside the conversation.
7. Tenant, identity, approval, and adapter boundaries are enforced server-side.

## Diagnose in this order

1. **Presentation:** Did the shell render the event, controls, file, or artifact?
2. **Transport:** Did ACP/SSE deliver an ordered, parseable event?
3. **Session:** Was the event appended and checkpointed under the right writer?
4. **Runtime:** Did the intended model, tool, memory, and policy path execute?
5. **Side effect:** Is the outcome confirmed, failed, denied, or unknown?
6. **Evidence:** Does a raw artifact support the claimed behavior?

Start with the first layer where expected and observed state diverge. Preserve
the event IDs, session ID, tool-call ID, artifact hash, and commit SHA needed to
reproduce the failure. Do not compensate for a lower-layer fault with UI state.

## Release and rollback

Repository gates are defined by the [Wiii Repository Harness](WIII_REPOSITORY_HARNESS.md).
Binary promotion is defined by the
[Wiii Release Standard](../releases/WIII_RELEASE_STANDARD.md). A rollback is a
new traceable change or release; published tags and evidence are never silently
rewritten.
