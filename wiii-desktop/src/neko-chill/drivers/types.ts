import type {
  NekoProviderCapabilityMap,
  NekoProviderExtensionValue,
} from "@/neko/contracts";

/**
 * Neko Chill driver contract — the provider-agnostic seam (FR-010).
 *
 * A Driver connects one session to one agent backend and emits DriverEvents.
 * The session store consumes ONLY this union; protocol-specific shapes (ACP
 * today, Wiii SSE V3 later) must never leak past a driver implementation.
 * Spec: specs/731-neko-chill-mode/ (issue #886).
 */

/** Stable identifier vocabulary shared by all drivers. */
export type DriverKind = "acp" | "codex-app-server" | "wiii-cloud";

/**
 * Operations a live provider explicitly promises to support. Consumers must
 * require one of these capabilities instead of inferring support from the
 * driver's kind or from a stale object reference.
 */
export type DriverCapability =
  | "prompt"
  | "cancel"
  | "permission-resolution"
  | "session-config";

/** Honest context/safety metadata for one driver implementation. */
export interface DriverRuntimeDescriptor {
  capabilities: DriverCapability[];
  /** `process` means context lasts only as long as this live process. */
  contextContinuity: "process" | "resumable";
  /** `advisory` is a cwd hint, not an OS-enforced sandbox boundary. */
  workspaceIsolation: "advisory" | "enforced";
  /** Provider-neutral facts established by this live adapter. */
  observedProviderCapabilities?: Partial<NekoProviderCapabilityMap>;
  /** Bounded JSON scalar facts only; raw provider events and secrets are forbidden. */
  providerExtensions?: Record<string, NekoProviderExtensionValue>;
  /** Version re-probed by Neko Control for the process being attached. */
  providerVersion?: string | null;
}

/** Why a turn stopped — superset across backends (ACP stopReason ⊆ this). */
export type TurnStopReason =
  | "end_turn"
  | "max_tokens"
  | "max_turn_requests"
  | "refusal"
  | "cancelled"
  | "error";

export type DriverFileOperation = "read" | "create" | "update" | "delete" | "move";

export interface DriverFileLocation {
  /** Absolute path reported by the provider. Native file commands revalidate it. */
  path: string;
  line?: number;
}

/** One tool/command/plan row in the transcript, upserted by id. */
export interface DriverActivity {
  /** Backend-scoped id (ACP toolCallId); unique within a turn. */
  id: string;
  /** Human title, e.g. "Read src/App.tsx" — already display-ready. */
  title: string;
  /** Coarse activity class for icon/row selection. */
  kind: "tool" | "command" | "file" | "search" | "plan" | "other";
  status: "pending" | "in_progress" | "completed" | "cancelled" | "failed";
  /** Optional display detail (tool output snippet, plan entries). */
  detail?: string;
  /** Structured tool identity and file facts; never infer these from the title. */
  toolName?: string;
  operation?: DriverFileOperation;
  locations?: DriverFileLocation[];
  rawInput?: unknown;
  rawOutput?: unknown;
}

/** An option offered by the agent on a permission request. */
export interface PermissionOption {
  optionId: string;
  label: string;
  /** Fail-closed policy hinges on this: only explicit allow kinds approve. */
  kind: "allow_once" | "allow_always" | "reject_once" | "reject_always" | "other";
}

export interface PermissionRequest {
  /** Correlates the eventual resolution back to the agent's request. */
  requestId: string;
  /** What the agent wants to do, display-ready. */
  title: string;
  /** The activity this request belongs to, when the agent links one. */
  activityId?: string;
  options: PermissionOption[];
}

/** One value in a driver-owned select control. */
export interface DriverConfigChoice {
  value: string;
  label: string;
  description?: string;
}

/**
 * Provider-neutral session control. ACP stable config options, legacy ACP
 * modes, and Gemini's legacy model picker all normalize to this shape.
 */
export interface DriverConfigOption {
  id: string;
  label: string;
  description?: string;
  category: "mode" | "model" | "model_config" | "thought_level" | "other";
  kind: "select" | "boolean";
  currentValue: string | boolean;
  choices?: DriverConfigChoice[];
}

/** Slash command reported by the active agent. */
export interface DriverCommand {
  name: string;
  description: string;
  inputHint?: string;
}

/**
 * Everything a driver may emit. `sessionId` scopes every event so concurrent
 * sessions can never cross streams (spec edge case).
 */
export type DriverEvent =
  | { type: "session-controls"; sessionId: string; controls: DriverConfigOption[] }
  | { type: "available-commands"; sessionId: string; commands: DriverCommand[] }
  | {
      type: "session-info";
      sessionId: string;
      title?: string | null;
      updatedAt?: string | null;
      continuityLevel?: "durable" | "recovered";
      revision?: number;
    }
  | { type: "turn-started"; sessionId: string }
  | { type: "reasoning-delta"; sessionId: string; text: string }
  | { type: "answer-delta"; sessionId: string; text: string }
  | { type: "activity"; sessionId: string; activity: DriverActivity }
  | { type: "permission-request"; sessionId: string; request: PermissionRequest }
  | { type: "turn-finished"; sessionId: string; stopReason: TurnStopReason }
  | { type: "error"; sessionId: string; message: string; fatal: boolean }
  | { type: "process-exited"; sessionId: string; code: number | null };

export type DriverEventType = DriverEvent["type"];

/** User's answer to a permission request. Absence of an answer NEVER approves. */
export interface PermissionDecision {
  requestId: string;
  /** `null` = dismissed/cancelled → driver must fail closed (FR-006). */
  optionId: string | null;
}

/**
 * One live connection between a session and an agent backend.
 *
 * Lifecycle: `start()` resolves once the backend is ready for prompts;
 * `dispose()` must always terminate the underlying process/transport —
 * it is called on session close, mode exit, and app quit (FR-009).
 */
export interface Driver {
  readonly kind: DriverKind;
  readonly sessionId: string;
  readonly runtime: DriverRuntimeDescriptor;
  /** Durable provider-owned session id, when the backend advertises resume. */
  readonly backendSessionId?: string | null;
  start(): Promise<void>;
  /** Send one user prompt; events stream via the subscribed handler. */
  prompt(text: string): Promise<void>;
  /** Interrupt the running turn (FR-007). No-op when idle. */
  cancel(): Promise<void>;
  /** Deliver the user's permission decision (FR-006). */
  resolvePermission(decision: PermissionDecision): Promise<void>;
  /** Change one capability-backed session option. */
  setConfigOption(optionId: string, value: string | boolean): Promise<void>;
  /** Terminate transport + process. Idempotent. */
  dispose(): Promise<void>;
}

/** Event sink the store registers with a driver on creation. */
export type DriverEventHandler = (event: DriverEvent) => void;
