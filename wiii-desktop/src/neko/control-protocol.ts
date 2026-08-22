import { findProviderDefinition } from "./provider-registry";

export const NEKO_CONTROL_PROTOCOL_VERSION = 1 as const;

export type NekoControlMethod =
  | "initialize"
  | "provider/list"
  | "provider/profiles"
  | "session/list"
  | "session/start"
  | "session/write"
  | "session/resume"
  | "session/cancel"
  | "approval/resolve"
  | "events/read";

export type NekoControlErrorCode =
  | "unsupported_version"
  | "unsupported_method"
  | "provider_not_found"
  | "provider_unavailable"
  | "invalid_request"
  | "invalid_state"
  | "permission_required"
  | "continuity_lost"
  | "unknown_outcome"
  | "internal_error";

export interface NekoControlError {
  code: NekoControlErrorCode;
  message: string;
}

export type NekoControlResponse<T = unknown> =
  | {
      v: typeof NEKO_CONTROL_PROTOCOL_VERSION;
      requestId: string;
      result: T;
    }
  | {
      v: typeof NEKO_CONTROL_PROTOCOL_VERSION;
      requestId: string;
      error: NekoControlError;
    };

export const NEKO_CONTROL_EVENT_TYPES = [
  "session.created",
  "session.started",
  "session.resumed",
  "run.state_changed",
  "message.started",
  "message.delta",
  "message.completed",
  "plan.updated",
  "tool.started",
  "tool.updated",
  "tool.completed",
  "terminal.output",
  "file.changed",
  "approval.requested",
  "approval.resolved",
  "artifact.created",
  "usage.updated",
  "process.exited",
] as const;

export type NekoControlEventType = (typeof NEKO_CONTROL_EVENT_TYPES)[number];

export interface NekoControlEvent {
  v: typeof NEKO_CONTROL_PROTOCOL_VERSION;
  eventId: string;
  /** Durable run stream identity. Sequence is monotonic only inside this stream. */
  streamId: string;
  seq: number;
  at: string;
  type: NekoControlEventType;
  projectId?: string;
  taskId?: string;
  runId?: string;
  agentSessionId?: string;
  payload: Record<string, unknown>;
  providerExtensions?: Record<string, string | number | boolean | null>;
}

interface BaseRequest<M extends NekoControlMethod, P> {
  v: typeof NEKO_CONTROL_PROTOCOL_VERSION;
  requestId: string;
  method: M;
  params: P;
}

export type NekoControlRequest =
  | BaseRequest<"initialize", { clientName: string; clientVersion: string }>
  | BaseRequest<"provider/list", Record<string, never>>
  | BaseRequest<"provider/profiles", { providerId: string; workspacePath: string }>
  | BaseRequest<"session/list", { projectId?: string; runId?: string }>
  | BaseRequest<"session/start", {
      agentSessionId: string;
      taskId: string;
      runId: string;
      providerId: string;
      environmentId: string;
      workspacePath: string;
      profileId?: string;
    }>
  | BaseRequest<"session/write", { agentSessionId: string; line: string }>
  | BaseRequest<"session/resume", {
      runId: string;
      agentSessionId: string;
      providerSessionId: string;
    }>
  | BaseRequest<"session/cancel", { runId: string; agentSessionId: string }>
  | BaseRequest<"approval/resolve", {
      approvalId: string;
      decision: "approved" | "rejected" | "cancelled";
    }>
  | BaseRequest<"events/read", { streamId: string; afterSeq: number; limit: number }>;

export interface NekoControlReplayPage {
  streamId: string;
  events: NekoControlEvent[];
  nextAfterSeq: number;
  hasMore: boolean;
}

export type NekoControlParseResult =
  | { ok: true; request: NekoControlRequest }
  | { ok: false; error: NekoControlError };

const METHODS = new Set<NekoControlMethod>([
  "initialize",
  "provider/list",
  "provider/profiles",
  "session/list",
  "session/start",
  "session/write",
  "session/resume",
  "session/cancel",
  "approval/resolve",
  "events/read",
]);

const ERROR_CODES = new Set<NekoControlErrorCode>([
  "unsupported_version",
  "unsupported_method",
  "provider_not_found",
  "provider_unavailable",
  "invalid_request",
  "invalid_state",
  "permission_required",
  "continuity_lost",
  "unknown_outcome",
  "internal_error",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function string(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function validParams(method: NekoControlMethod, params: Record<string, unknown>): boolean {
  switch (method) {
    case "initialize":
      return string(params.clientName) && string(params.clientVersion);
    case "provider/list":
      return Object.keys(params).length === 0;
    case "provider/profiles":
      return (
        string(params.providerId) &&
        findProviderDefinition(params.providerId) !== null &&
        string(params.workspacePath)
      );
    case "session/list":
      return (
        (params.projectId === undefined || string(params.projectId)) &&
        (params.runId === undefined || string(params.runId))
      );
    case "session/start":
      return (
        string(params.agentSessionId) &&
        string(params.taskId) &&
        string(params.runId) &&
        string(params.providerId) &&
        findProviderDefinition(params.providerId) !== null &&
        string(params.environmentId) &&
        string(params.workspacePath) &&
        (params.profileId === undefined || string(params.profileId))
      );
    case "session/write":
      return string(params.agentSessionId) && string(params.line);
    case "session/resume":
      return string(params.runId) && string(params.agentSessionId) && string(params.providerSessionId);
    case "session/cancel":
      return string(params.runId) && string(params.agentSessionId);
    case "approval/resolve":
      return (
        string(params.approvalId) &&
        ["approved", "rejected", "cancelled"].includes(params.decision as string)
      );
    case "events/read":
      return (
        string(params.streamId) &&
        Number.isSafeInteger(params.afterSeq) &&
        (params.afterSeq as number) >= 0 &&
        Number.isSafeInteger(params.limit) &&
        (params.limit as number) >= 1 &&
        (params.limit as number) <= 500
      );
  }
}

export function isNekoControlEvent(value: unknown): value is NekoControlEvent {
  const event = record(value);
  const extensions = event?.providerExtensions;
  return Boolean(
    event &&
    event.v === NEKO_CONTROL_PROTOCOL_VERSION &&
    string(event.eventId) &&
    string(event.streamId) &&
    Number.isSafeInteger(event.seq) &&
    (event.seq as number) > 0 &&
    string(event.at) &&
    typeof event.type === "string" &&
    NEKO_CONTROL_EVENT_TYPES.includes(event.type as NekoControlEventType) &&
    (event.projectId === undefined || string(event.projectId)) &&
    (event.taskId === undefined || string(event.taskId)) &&
    string(event.runId) &&
    (event.agentSessionId === undefined || string(event.agentSessionId)) &&
    record(event.payload) &&
    (
      extensions === undefined ||
      (
        record(extensions) !== null &&
        Object.values(extensions as Record<string, unknown>).every((item) =>
          item === null || ["string", "number", "boolean"].includes(typeof item)
        )
      )
    )
  );
}

export function isNekoControlReplayPage(
  value: unknown,
  expectedStreamId?: string,
  afterSeq: number = 0,
): value is NekoControlReplayPage {
  const page = record(value);
  if (
    !page ||
    !string(page.streamId) ||
    (expectedStreamId !== undefined && page.streamId !== expectedStreamId) ||
    !Array.isArray(page.events) ||
    !Number.isSafeInteger(page.nextAfterSeq) ||
    (page.nextAfterSeq as number) < afterSeq ||
    typeof page.hasMore !== "boolean"
  ) return false;

  let previous = afterSeq;
  for (const event of page.events) {
    if (
      !isNekoControlEvent(event) ||
      event.streamId !== page.streamId ||
      event.seq <= previous
    ) return false;
    previous = event.seq;
  }
  return page.nextAfterSeq === previous;
}

export function parseNekoControlRequest(value: unknown): NekoControlParseResult {
  const request = record(value);
  if (!request || !string(request.requestId)) {
    return { ok: false, error: { code: "invalid_request", message: "Missing request identity." } };
  }
  if (request.v !== NEKO_CONTROL_PROTOCOL_VERSION) {
    return {
      ok: false,
      error: { code: "unsupported_version", message: `Unsupported Neko Control version "${String(request.v)}".` },
    };
  }
  if (typeof request.method !== "string" || !METHODS.has(request.method as NekoControlMethod)) {
    return {
      ok: false,
      error: { code: "unsupported_method", message: `Unsupported Neko Control method "${String(request.method)}".` },
    };
  }
  const params = record(request.params);
  const method = request.method as NekoControlMethod;
  if (!params || !validParams(method, params)) {
    return {
      ok: false,
      error: { code: "invalid_request", message: `Invalid parameters for "${method}".` },
    };
  }
  return { ok: true, request: request as unknown as NekoControlRequest };
}

export function isNekoControlResponse(value: unknown): value is NekoControlResponse {
  const response = record(value);
  if (
    !response ||
    response.v !== NEKO_CONTROL_PROTOCOL_VERSION ||
    !string(response.requestId)
  ) return false;
  const hasResult = Object.prototype.hasOwnProperty.call(response, "result");
  const hasError = Object.prototype.hasOwnProperty.call(response, "error");
  if (hasResult === hasError) return false;
  if (hasResult) return true;
  const error = record(response.error);
  return Boolean(
    error &&
    ERROR_CODES.has(error.code as NekoControlErrorCode) &&
    typeof error.message === "string",
  );
}
