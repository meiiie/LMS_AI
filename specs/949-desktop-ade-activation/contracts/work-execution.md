# Contract: Wiii Work To Neko Execution

## Authority

```text
Wiii ADE      Project, Task, Spec, Run, human work state
Neko Chill    provider execution lifecycle and visible local session
Provider      native conversation/session continuation
Git/files     source state
Wiii Service  optional managed/org/data capabilities
```

## Start sequence

1. Validate task draft and provider selection.
2. Build Project/Workspace/Task/Spec/Environment/Run records.
3. Validate the complete candidate graph.
4. Commit the versioned work snapshot.
5. Create the visible Neko session with the exact execution binding.
6. Persist the Neko session/index before provider dispatch.
7. Neko Control starts the provider with the binding.
8. Record AgentSession and transition Run to `running` only after attachment.

No step before 4 may launch a provider. No failure after 4 may delete the Task.

## Failure classification

| Observation | Run state | Retry |
|---|---|---|
| Rejected/proven safe launch failure | `failed` | Explicit new Run |
| Native side effect cannot be proven | `unknown_outcome` | Never automatic |
| Provider attached and Wiii binding committed | `running` | N/A |

Manual Neko sessions omit the binding and retain explicit `legacy-local` compatibility identities. They do not manufacture Wiii Task records.
