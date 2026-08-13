# Data Model: Neko Chill Workspace Shell

## WorkspaceRef

```ts
interface WorkspaceRef {
  path: string; // absolute, selected through the native folder dialog
  name: string; // final path segment for display only
}
```

Identity is the normalized path string. No filesystem contents are persisted.

## AgentLaunchProfile

```ts
interface AgentLaunchProfile {
  id: string;
  provider: string;
  model: string | null;
  active: boolean;
}
```

Profiles are read-only probe results. The selected snapshot is persisted on a
session so the UI can explain which model/provider launched it.

## DriverConfigOption

```ts
interface DriverConfigOption {
  id: string;
  label: string;
  description?: string;
  category: "mode" | "model" | "model_config" | "thought_level" | "other";
  kind: "select" | "boolean";
  currentValue: string | boolean;
  choices?: Array<{ value: string; label: string; description?: string }>;
}
```

The UI never receives ACP source/wire ids. The live driver owns a private map
from normalized ids to stable config, legacy mode, or legacy model operations.

## DriverCommand

```ts
interface DriverCommand {
  name: string;
  description: string;
  inputHint?: string;
}
```

Agent commands arrive from the driver. Neko-Chill-owned commands are composed
at the UI boundary and carry an explicit source label there.

## NekoSession additions

```ts
interface NekoSession {
  // existing fields omitted
  workspace: WorkspaceRef | null;
  updatedAt: number;
  launchProfile: AgentLaunchProfile | null;
  controls: DriverConfigOption[];
  commands: DriverCommand[];
  pendingControlId: string | null;
}
```

### State transitions

- New -> connecting only after workspace + agent are selected.
- Restored v1 -> exited, workspace null, legacy group.
- Legacy attach -> exited with workspace set; next prompt starts a new driver.
- Control request -> pendingControlId set -> driver success event replaces
  controls -> pending cleared; failure keeps prior controls and reports detail.
- Session-info update -> title/updatedAt patched if valid.

## Persistence compatibility

Index entries add `v: 2`, workspace, updatedAt, launchProfile, controls, and
commands. Missing fields from v1 are interpreted as null/empty; transcript
records remain at their existing schema because message shape is unchanged.
