/**
 * Neko Chill driver contract — the provider-agnostic seam (FR-010).
 *
 * A Driver connects one session to one agent backend and emits DriverEvents.
 * The session store consumes ONLY this union; protocol-specific shapes (ACP
 * today, Wiii SSE V3 later) must never leak past a driver implementation.
 * Spec: specs/731-neko-chill-mode/ (issue #886).
 */

/** Stable identifier vocabulary shared by all drivers. */
export type DriverKind = "acp" | "wiii-cloud";

/** Why a turn stopped — superset across backends (ACP stopReason ⊆ this). */
export type TurnStopReason =
  | "end_turn"
  | "max_tokens"
  | "max_turn_requests"
  | "refusal"
  | "cancelled"
  | "error";

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

/**
 * Everything a driver may emit. `sessionId` scopes every event so concurrent
 * sessions can never cross streams (spec edge case).
 */
export type DriverEvent =
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
  start(): Promise<void>;
  /** Send one user prompt; events stream via the subscribed handler. */
  prompt(text: string): Promise<void>;
  /** Interrupt the running turn (FR-007). No-op when idle. */
  cancel(): Promise<void>;
  /** Deliver the user's permission decision (FR-006). */
  resolvePermission(decision: PermissionDecision): Promise<void>;
  /** Terminate transport + process. Idempotent. */
  dispose(): Promise<void>;
}

/** Event sink the store registers with a driver on creation. */
export type DriverEventHandler = (event: DriverEvent) => void;
