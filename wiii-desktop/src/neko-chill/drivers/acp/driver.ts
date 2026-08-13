/**
 * ACP driver (T203) — maps the ACP wire protocol onto the provider-agnostic
 * DriverEvent union. Shapes verified against a REAL neko-core v0.24.0 session
 * (fixtures/neko-acp-session.ndjson) and agentclientprotocol.com; see
 * PROTOCOL-NOTES.md. This is the ONLY file allowed to know ACP payloads.
 */

import type {
  Driver,
  DriverActivity,
  DriverEvent,
  DriverEventHandler,
  PermissionDecision,
  PermissionOption,
  TurnStopReason,
} from "../types";
import {
  AcpJsonRpcClient,
  UnsupportedMethodError,
  type AcpTransport,
} from "./client";

export const ACP_PROTOCOL_VERSION = 1;

const STOP_REASONS: readonly TurnStopReason[] = [
  "end_turn",
  "max_tokens",
  "max_turn_requests",
  "refusal",
  "cancelled",
];

interface AcpDriverOptions {
  /** Neko Chill session id — scopes every emitted event. */
  sessionId: string;
  /** Absolute project directory for `session/new` (ACP requires absolute). */
  cwd: string;
  transport: AcpTransport;
  onEvent: DriverEventHandler;
}

/** Extract text from ACP content shapes: `"str"` or `{ type:"text", text }`. */
function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (content && typeof content === "object") {
    const text = (content as { text?: unknown }).text;
    if (typeof text === "string") return text;
  }
  return "";
}

/** ACP tool kind → transcript activity kind (fixture kinds: edit, read). */
function activityKind(kind: unknown): DriverActivity["kind"] {
  switch (kind) {
    case "edit":
    case "read":
    case "delete":
    case "move":
      return "file";
    case "execute":
      return "command";
    case "search":
    case "fetch":
      return "search";
    case "think":
      return "plan";
    default:
      return "tool";
  }
}

function activityStatus(status: unknown): DriverActivity["status"] {
  switch (status) {
    case "pending":
    case "in_progress":
    case "completed":
    case "cancelled":
    case "failed":
      return status;
    default:
      return "pending";
  }
}

function permissionOptionKind(kind: unknown): PermissionOption["kind"] {
  switch (kind) {
    case "allow_once":
    case "allow_always":
    case "reject_once":
    case "reject_always":
      return kind;
    default:
      return "other";
  }
}

interface PendingPermission {
  resolve: (result: unknown) => void;
  /** Option ids the agent offered — decisions outside this set fail closed. */
  offered: Set<string>;
}

export class AcpDriver implements Driver {
  readonly kind = "acp" as const;
  readonly sessionId: string;

  private readonly cwd: string;
  private readonly emit: DriverEventHandler;
  private readonly client: AcpJsonRpcClient;
  private acpSessionId: string | null = null;
  private turnRunning = false;
  private permissionSeq = 0;
  private readonly pendingPermissions = new Map<string, PendingPermission>();
  /** Per-session activity cache so tool_call_update can merge partial data. */
  private readonly activities = new Map<string, DriverActivity>();

  constructor(options: AcpDriverOptions) {
    this.sessionId = options.sessionId;
    this.cwd = options.cwd;
    this.emit = options.onEvent;
    this.client = new AcpJsonRpcClient(options.transport, {
      onAgentRequest: (method, params) => this.handleAgentRequest(method, params),
      onNotification: (method, params) => this.handleNotification(method, params),
      onProtocolError: (message) =>
        this.emitEvent({ type: "error", sessionId: this.sessionId, message, fatal: true }),
    });
    options.transport.onExit((code) =>
      this.emitEvent({ type: "process-exited", sessionId: this.sessionId, code }),
    );
  }

  async start(): Promise<void> {
    await this.client.request("initialize", {
      protocolVersion: ACP_PROTOCOL_VERSION,
      // v0 policy (PROTOCOL-NOTES): no client fs/terminal — every side effect
      // must surface through session/request_permission (FR-006).
      clientCapabilities: {
        fs: { readTextFile: false, writeTextFile: false },
        terminal: false,
      },
      clientInfo: { name: "wiii-neko-chill", title: "Wiii — Neko Chill", version: "0.1.0" },
    });
    const session = (await this.client.request("session/new", {
      cwd: this.cwd,
      // neko-core refuses client-supplied MCP servers; always empty in v0.
      mcpServers: [],
    })) as { sessionId?: unknown };
    if (typeof session?.sessionId !== "string" || !session.sessionId) {
      throw new Error("session/new returned no sessionId");
    }
    this.acpSessionId = session.sessionId;
  }

  async prompt(text: string): Promise<void> {
    if (!this.acpSessionId) throw new Error("driver not started");
    if (this.turnRunning) throw new Error("a turn is already running");
    this.turnRunning = true;
    this.emitEvent({ type: "turn-started", sessionId: this.sessionId });
    try {
      const result = (await this.client.request("session/prompt", {
        sessionId: this.acpSessionId,
        prompt: [{ type: "text", text }],
      })) as { stopReason?: unknown };
      const stopReason = STOP_REASONS.includes(result?.stopReason as TurnStopReason)
        ? (result.stopReason as TurnStopReason)
        : "error";
      this.emitEvent({ type: "turn-finished", sessionId: this.sessionId, stopReason });
    } catch (err) {
      this.emitEvent({
        type: "error",
        sessionId: this.sessionId,
        message: err instanceof Error ? err.message : String(err),
        fatal: false,
      });
      this.emitEvent({ type: "turn-finished", sessionId: this.sessionId, stopReason: "error" });
    } finally {
      this.turnRunning = false;
    }
  }

  async cancel(): Promise<void> {
    if (!this.acpSessionId || !this.turnRunning) return;
    await this.client.notify("session/cancel", { sessionId: this.acpSessionId });
  }

  async resolvePermission(decision: PermissionDecision): Promise<void> {
    const pending = this.pendingPermissions.get(decision.requestId);
    if (!pending) return; // already resolved or unknown — nothing to approve
    this.pendingPermissions.delete(decision.requestId);
    // Fail closed (FR-006): null or an option the agent never offered → cancelled.
    if (decision.optionId !== null && pending.offered.has(decision.optionId)) {
      pending.resolve({ outcome: { outcome: "selected", optionId: decision.optionId } });
    } else {
      pending.resolve({ outcome: { outcome: "cancelled" } });
    }
  }

  async dispose(): Promise<void> {
    // Unanswered permission requests fail closed before the process dies.
    for (const [, pending] of this.pendingPermissions) {
      pending.resolve({ outcome: { outcome: "cancelled" } });
    }
    this.pendingPermissions.clear();
    await this.client.dispose();
  }

  // -------------------------------------------------------------------- //

  private emitEvent(event: DriverEvent): void {
    this.emit(event);
  }

  private handleNotification(method: string, params: unknown): void {
    if (method !== "session/update") return;
    const update = (params as { update?: Record<string, unknown> })?.update;
    if (!update || typeof update !== "object") return;

    switch (update.sessionUpdate) {
      case "agent_message_chunk": {
        const text = contentText(update.content);
        if (text) this.emitEvent({ type: "answer-delta", sessionId: this.sessionId, text });
        return;
      }
      case "agent_thought_chunk": {
        const text = contentText(update.content);
        if (text) this.emitEvent({ type: "reasoning-delta", sessionId: this.sessionId, text });
        return;
      }
      case "tool_call":
      case "tool_call_update": {
        const id = typeof update.toolCallId === "string" ? update.toolCallId : "";
        if (!id) return;
        const previous = this.activities.get(id);
        const detailSource = Array.isArray(update.content)
          ? update.content
              .map((entry) =>
                contentText((entry as { content?: unknown })?.content ?? entry),
              )
              .filter(Boolean)
              .join("\n")
          : "";
        const activity: DriverActivity = {
          id,
          title:
            typeof update.title === "string" && update.title
              ? update.title
              : previous?.title ?? "Tool call",
          kind: update.kind !== undefined ? activityKind(update.kind) : previous?.kind ?? "tool",
          status:
            update.status !== undefined
              ? activityStatus(update.status)
              : previous?.status ?? "pending",
          detail: detailSource || previous?.detail,
        };
        this.activities.set(id, activity);
        this.emitEvent({ type: "activity", sessionId: this.sessionId, activity });
        return;
      }
      case "plan": {
        const entries = Array.isArray(update.entries) ? update.entries : [];
        const detail = entries
          .map((entry) => contentText((entry as { content?: unknown })?.content))
          .filter(Boolean)
          .join("\n");
        this.emitEvent({
          type: "activity",
          sessionId: this.sessionId,
          activity: { id: "plan", title: "Plan", kind: "plan", status: "in_progress", detail },
        });
        return;
      }
      default:
        // usage_update, mode changes, future discriminators: ignored in v0.
        return;
    }
  }

  private handleAgentRequest(method: string, params: unknown): Promise<unknown> {
    if (method === "session/request_permission") {
      return new Promise((resolve) => {
        const p = params as {
          toolCall?: { toolCallId?: unknown; title?: unknown };
          options?: Array<{ optionId?: unknown; name?: unknown; kind?: unknown }>;
        };
        const requestId = `perm-${++this.permissionSeq}`;
        const options = (p?.options ?? []).flatMap((option): PermissionOption[] =>
          typeof option?.optionId === "string"
            ? [
                {
                  optionId: option.optionId,
                  label: typeof option.name === "string" ? option.name : option.optionId,
                  kind: permissionOptionKind(option.kind),
                },
              ]
            : [],
        );
        this.pendingPermissions.set(requestId, {
          resolve,
          offered: new Set(options.map((o) => o.optionId)),
        });
        this.emitEvent({
          type: "permission-request",
          sessionId: this.sessionId,
          request: {
            requestId,
            title:
              typeof p?.toolCall?.title === "string" && p.toolCall.title
                ? p.toolCall.title
                : "Agent requests permission",
            activityId:
              typeof p?.toolCall?.toolCallId === "string" ? p.toolCall.toolCallId : undefined,
            options,
          },
        });
      });
    }
    // fs/*, terminal/*: capabilities were declared false; refuse explicitly.
    return Promise.reject(new UnsupportedMethodError(`client does not implement ${method}`));
  }
}
