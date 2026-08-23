# Data Model: Desktop ADE Activation

## Persisted envelope

```ts
interface AdeWorkSnapshotV1 {
  v: 1;
  updatedAt: string;
  graph: AdeGraph;
}
```

Loading applies structural schema validation and then `validateAdeGraph`. Any diagnostic rejects the snapshot.

## Initial work chain

```text
Project
├── Workspace (local root)
├── Environment (local_workspace)
└── Task
    ├── Spec revision 1
    └── Run (single, starting)
        └── AgentSession (after provider attachment)
```

## Neko execution binding

```ts
interface NekoExecutionBinding {
  taskId: string;
  runId: string;
  environmentId: string;
}
```

The binding is persisted with the visible Neko session before dispatch. It contains no executable path, credential, prompt or provider token.

## Compatibility

- Missing ADE snapshot means an empty graph.
- Unsupported or malformed ADE snapshot is an error, not an empty graph.
- Missing `NekoSession.execution` means legacy/manual session.
- Existing transcript event discriminators remain unchanged.
