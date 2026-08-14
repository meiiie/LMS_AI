import type { DriverKind } from "./drivers/types";
import type { RuntimeProviderSnapshot } from "./runtime-manager";

export const NEKO_SESSION_EVENT_VERSION = 1;

export type ModelValue = string | boolean | null;

export type NekoSessionEventData =
  | {
      type: "session-context";
      source: "created" | "legacy-migration" | "workspace-attached";
      agentId: string;
      workspacePath: string | null;
      launchProfileId: string | null;
    }
  | {
      type: "model-input";
      source: "live" | "legacy-migration";
      messageId: string;
      text: string;
      providerInstanceId: string | null;
    }
  | {
      type: "permission-decision";
      requestId: string;
      optionId: string | null;
      providerInstanceId: string;
    }
  | {
      type: "runtime-command";
      action: "cancel";
      providerInstanceId: string;
    }
  | {
      type: "control-change";
      phase: "requested" | "committed" | "rolled-back" | "rollback-failed";
      optionId: string;
      previousValue: ModelValue;
      nextValue: ModelValue;
      reason?: string;
    }
  | {
      type: "runtime-attached";
      provider: RuntimeProviderSnapshot;
    }
  | {
      type: "runtime-detached";
      providerId: string;
      instanceId: string;
      kind: DriverKind;
      reason: "close" | "delete" | "idle" | "mode-exit" | "process-exit" | "workspace-change";
    }
  | {
      type: "runtime-attach-failed";
      providerId: string;
      reason: string;
    };

/**
 * Append-only audit record. `model` marks an input/transition that can cross
 * Wiii's model boundary; its phase says whether it committed or rolled back.
 */
export interface NekoSessionEvent {
  v: typeof NEKO_SESSION_EVENT_VERSION;
  seq: number;
  at: number;
  visibility: "model" | "runtime";
  data: NekoSessionEventData;
}

export function appendSessionEvent(
  events: NekoSessionEvent[],
  visibility: NekoSessionEvent["visibility"],
  data: NekoSessionEventData,
  at: number = Date.now(),
): NekoSessionEvent {
  const event: NekoSessionEvent = {
    v: NEKO_SESSION_EVENT_VERSION,
    seq: (events[events.length - 1]?.seq ?? 0) + 1,
    at,
    visibility,
    data,
  };
  events.push(event);
  return event;
}

export function isNekoSessionEvent(value: unknown): value is NekoSessionEvent {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<NekoSessionEvent>;
  const eventType = (candidate.data as { type?: unknown } | undefined)?.type;
  return (
    candidate.v === NEKO_SESSION_EVENT_VERSION &&
    typeof candidate.seq === "number" &&
    Number.isInteger(candidate.seq) &&
    candidate.seq > 0 &&
    typeof candidate.at === "number" &&
    (candidate.visibility === "model" || candidate.visibility === "runtime") &&
    typeof eventType === "string" &&
    [
      "session-context",
      "model-input",
      "permission-decision",
      "runtime-command",
      "control-change",
      "runtime-attached",
      "runtime-detached",
      "runtime-attach-failed",
    ].includes(eventType)
  );
}
