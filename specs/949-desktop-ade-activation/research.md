# Research: Desktop ADE Activation

## Existing truths

- `src/ade/domain.ts` already defines the canonical work graph.
- `src/ade/lifecycle.ts` already separates lifecycle validation from graph validation.
- Rust Neko runtime already owns native provider lifecycle and durable native facts in-process.
- `NekoControlClient.spawnProvider` already accepts an explicit execution binding; the visible Neko session path currently does not supply it.
- Neko transcript persistence already commits a new visible session before `driver.start`, providing the barrier this feature must preserve.
- The current Neko layout and manual launcher are useful execution surfaces; the architectural defect is their position as Wiii's home.

## Decision: activate, do not redesign

The minimal complete slice is a Wiii work shell above Neko, plus a real identity binding. Adding editor, terminal, worktrees or fleet orchestration would obscure whether Task is genuinely the product authority.

## Decision: one authoritative local graph

Persist one versioned `AdeGraph` envelope. Use schema validation followed by `validateAdeGraph`; do not infer missing references. This mirrors the runtime's fail-closed durability discipline.

## Decision: Knowledge is context

Wiii Knowledge retrieval already augments the prompt at dispatch. Its UI belongs with Context controls, not beside local/Service navigation. No retrieval logic changes in this slice.

## Rejected alternatives

- **Make sessions look like tasks**: preserves conversation as authority and cannot represent multiple Runs.
- **Store work in Neko session snapshots**: couples Wiii work truth to provider transcript rollback.
- **Build standalone daemon first**: users still could not create a Task.
- **Add worktrees now**: `local_workspace` must be represented honestly before isolation exists.
