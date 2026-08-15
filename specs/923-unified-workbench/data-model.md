# Data model: Unified Wiii Workbench

No backend database migration is introduced. These are frontend/runtime
contracts and persisted local references.

## WorkbenchHost

```ts
type WorkbenchHostKind = "desktop" | "web";

interface WorkbenchHost {
  kind: WorkbenchHostKind;
  capabilities: {
    localProcess: boolean;
    localWorkspace: boolean;
    nativeWindow: boolean;
    tray: boolean;
    secureSecretStore: boolean;
    remoteRuntime: boolean;
  };
}
```

Host state is derived per process and is not user-editable or persisted.

## RuntimeDefinition

```ts
interface RuntimeDefinition {
  id: string;
  label: string;
  transport: "acp-stdio" | "codex-app-server" | "wiii-sse";
  location: "local" | "remote";
  authOwner: "runtime" | "wiii" | "api-credential" | "none";
  hostRequirements: Array<keyof WorkbenchHost["capabilities"]>;
}
```

The catalog describes honest availability. It never stores credentials.

## CapabilityConnection

```ts
type ConnectionStatus =
  | "unavailable"
  | "disconnected"
  | "connecting"
  | "ready"
  | "degraded"
  | "error";

interface CapabilityConnection {
  id: string;
  status: ConnectionStatus;
  authOwner: RuntimeDefinition["authOwner"];
  detail?: string;
}
```

Runtime, knowledge, Wiii account, and provider account connections use the same
status vocabulary but remain separate records.

## WorkbenchSession extension

Existing Neko session records remain authoritative. New optional references are
additive:

```ts
interface SessionCapabilityRefs {
  runtimeId: string;
  providerSessionId?: string | null;
  knowledgeConnectionIds: string[];
  toolsetIds: string[];
  syncPolicy: "local-only" | "wiii-service";
}
```

Legacy snapshots without these fields resolve to the ACP runtime represented by
their existing `agentId` and remain valid.

## ModelVisibleContextEvent

```ts
interface ModelVisibleContextEvent {
  type: "model-context-attached";
  sourceId: string;
  sourceKind: "project" | "wiii-knowledge" | "web" | "memory";
  query: string;
  content: string;
  contentSha256: string;
  citation?: {
    title: string;
    uri?: string;
    documentId?: string;
    chunkId?: string;
  };
}
```

The event is durably committed before a provider request. Tenant authorization
remains server-side and is not inferred from event metadata.
