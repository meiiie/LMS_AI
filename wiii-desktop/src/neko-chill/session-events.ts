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

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isModelValue(value: unknown): value is ModelValue {
  return typeof value === "string" || typeof value === "boolean" || value === null;
}

function isRuntimeProvider(value: unknown): value is RuntimeProviderSnapshot {
  if (!value || typeof value !== "object") return false;
  const provider = value as Record<string, unknown>;
  return (
    typeof provider.sessionId === "string" &&
    typeof provider.providerId === "string" &&
    typeof provider.instanceId === "string" &&
    (provider.kind === "acp" || provider.kind === "wiii-cloud") &&
    Array.isArray(provider.capabilities) &&
    provider.capabilities.every((capability) =>
      ["prompt", "cancel", "permission-resolution", "session-config"].includes(
        capability as string,
      )) &&
    (provider.contextContinuity === "process" || provider.contextContinuity === "resumable") &&
    (provider.workspaceIsolation === "advisory" || provider.workspaceIsolation === "enforced")
  );
}

function isValidEventData(data: Record<string, unknown>): boolean {
  switch (data.type) {
    case "session-context":
      return (
        ["created", "legacy-migration", "workspace-attached"].includes(data.source as string) &&
        typeof data.agentId === "string" &&
        isStringOrNull(data.workspacePath) &&
        isStringOrNull(data.launchProfileId)
      );
    case "model-input":
      return (
        (data.source === "live" || data.source === "legacy-migration") &&
        typeof data.messageId === "string" &&
        typeof data.text === "string" &&
        isStringOrNull(data.providerInstanceId)
      );
    case "permission-decision":
      return (
        typeof data.requestId === "string" &&
        isStringOrNull(data.optionId) &&
        typeof data.providerInstanceId === "string"
      );
    case "runtime-command":
      return data.action === "cancel" && typeof data.providerInstanceId === "string";
    case "control-change":
      return (
        ["requested", "committed", "rolled-back", "rollback-failed"].includes(
          data.phase as string,
        ) &&
        typeof data.optionId === "string" &&
        isModelValue(data.previousValue) &&
        isModelValue(data.nextValue) &&
        (data.reason === undefined || typeof data.reason === "string")
      );
    case "runtime-attached":
      return isRuntimeProvider(data.provider);
    case "runtime-detached":
      return (
        typeof data.providerId === "string" &&
        typeof data.instanceId === "string" &&
        (data.kind === "acp" || data.kind === "wiii-cloud") &&
        ["close", "delete", "idle", "mode-exit", "process-exit", "workspace-change"].includes(
          data.reason as string,
        )
      );
    case "runtime-attach-failed":
      return typeof data.providerId === "string" && typeof data.reason === "string";
    default:
      return false;
  }
}

export function isNekoSessionEvent(value: unknown): value is NekoSessionEvent {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<NekoSessionEvent>;
  const data = candidate.data as Record<string, unknown> | undefined;
  return (
    candidate.v === NEKO_SESSION_EVENT_VERSION &&
    typeof candidate.seq === "number" &&
    Number.isInteger(candidate.seq) &&
    candidate.seq > 0 &&
    typeof candidate.at === "number" &&
    Number.isFinite(candidate.at) &&
    (candidate.visibility === "model" || candidate.visibility === "runtime") &&
    data !== undefined &&
    isValidEventData(data)
  );
}
