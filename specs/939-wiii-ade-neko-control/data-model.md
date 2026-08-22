# Data Model: Wiii ADE Foundation

## Ownership map

| Authority | Canonical state |
| --- | --- |
| Git | Source, branches, commits and worktree contents |
| Wiii ADE | Project, task, spec, run intent, review, evidence and human decisions |
| Neko Chill | Provider discovery, local execution lifecycle, environment binding and normalized execution events |
| Provider | Provider conversation/session, authentication, model catalog and opaque continuation |
| Wiii Service | Identity, organization, managed state, knowledge, memory, policy, audit and sync |

## Core hierarchy

```text
Project
  +-- Workspace
  +-- Task
        +-- Spec revisions
        +-- Run
              +-- Environment
              +-- AgentSession
              +-- Artifact
              +-- Evidence
              +-- Approval
              `-- AttentionItem
```

The diagram shows navigation, not ownership by containment. Environment,
artifact, evidence, approval and attention records have stable IDs and may be
queried independently.

## Entity contracts

### Project

- `id`, `name`
- lifecycle timestamps
- no implicit repository requirement

### Workspace

- `id`, `projectId`
- one or more explicit roots
- source kind (`local`, `git`, `remote`)
- roots are authority boundaries, not display-only strings

### Task

- `id`, `projectId`, `title`, optional description
- state: `draft`, `ready`, `running`, `blocked`, `review`, `completed`, `cancelled`
- does not store provider session identity

### Spec

- `id`, `taskId`, integer revision
- requirements, constraints and acceptance criteria
- revisions are immutable observations; a new revision gets a new identity

### Run

- `id`, `taskId`, `environmentId`
- state: `queued`, `starting`, `running`, `waiting`, `verifying`, `review`,
  `completed`, `failed`, `cancelled`, `unknown_outcome`
- strategy: `single`, `best_of_n`, `specialist`, `writer_reviewer`,
  `plan_implement_verify`, `provider_native`
- a retry creates a run only when it is a new task attempt, not when a provider
  transport reconnects

### AgentSession

- `id`, `runId`, `providerId`
- provider-owned session ID remains opaque
- role: `primary`, `planner`, `implementer`, `reviewer`, `specialist`, `subagent`
- capability snapshot records the observed provider contract

### Environment

- `id`, `projectId`, optional `workspaceId`
- kind: `local_workspace`, `worktree`, `wsl`, `ssh`, `container`,
  `wiii_cloud`, `external_cloud`
- state and isolation descriptors are execution facts, not marketing labels

### Artifact

- `id`, `runId`, kind, URI/path, media type, optional hash and byte size
- large payloads remain outside the structured store

### Evidence

- `id`, `runId`, kind, outcome, summary, optional command and artifact IDs
- agent claims are not evidence unless backed by an observation or artifact

### Approval

- `id`, `runId`, optional `agentSessionId`
- request, risk, state and durable decision
- absence/dismissal never means approval

### AttentionItem

- `id`, `projectId`, `taskId`, optional run/session references
- reason: approval, question, authentication, test/CI failure, conflict,
  stalled, budget, review-ready, unknown-outcome
- presentation status is derived from durable facts where possible

## Graph invariants

1. Every workspace and task references an existing project.
2. Every spec references an existing task.
3. Every run references an existing task and environment.
4. A run's environment belongs to the same project as its task.
5. An environment's workspace, when present, belongs to the same project.
6. Every agent session, artifact, evidence and approval references an existing
   run.
7. Evidence artifact IDs belong to the same run; an approval's optional agent
   session belongs to the approval's run.
8. Attention references, when present, must form one consistent
   project/task/run/session chain.
9. Provider session IDs never determine task or run identity.

## Persistence direction

This feature validates JSON-compatible snapshots in memory. A later daemon
issue will map the same contracts to SQLite WAL, append-only facts and derived
read models. High-volume terminal output and binary artifacts will remain in
manifested files/object storage.
