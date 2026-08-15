/**
 * ACP driver (T203) — maps the ACP wire protocol onto the provider-agnostic
 * DriverEvent union. Shapes verified against a REAL neko-core v0.24.0 session
 * (fixtures/neko-acp-session.ndjson) and agentclientprotocol.com; see
 * PROTOCOL-NOTES.md. This is the ONLY file allowed to know ACP payloads.
 */

import type {
  Driver,
  DriverActivity,
  DriverCommand,
  DriverConfigChoice,
  DriverConfigOption,
  DriverEvent,
  DriverEventHandler,
  PermissionDecision,
  PermissionOption,
  TurnStopReason,
} from "../types";
import { APP_VERSION } from "../../../lib/constants";
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
  /** Provider-owned durable ACP session id from a previous process. */
  resumeSessionId?: string | null;
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

function activityOperation(
  kind: unknown,
  toolName: unknown,
): DriverActivity["operation"] | undefined {
  if (kind === "read") return "read";
  if (kind === "delete") return "delete";
  if (kind === "move") return "move";
  if (kind === "edit") {
    return typeof toolName === "string" && /create/i.test(toolName)
      ? "create"
      : "update";
  }
  return undefined;
}

function activityLocations(value: unknown): DriverActivity["locations"] {
  if (!Array.isArray(value)) return undefined;
  const locations = value.flatMap((item) => {
    const location = record(item);
    if (!location || typeof location.path !== "string" || !location.path) return [];
    return [{
      path: location.path,
      ...(typeof location.line === "number" && Number.isFinite(location.line)
        ? { line: location.line }
        : {}),
    }];
  });
  return locations.length ? locations : undefined;
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

type AcpRecord = Record<string, unknown>;

type ControlRoute =
  | { kind: "config"; wireId: string }
  | { kind: "mode" }
  | { kind: "model" };

function record(value: unknown): AcpRecord | null {
  return value && typeof value === "object" ? (value as AcpRecord) : null;
}

function optionCategory(value: unknown): DriverConfigOption["category"] {
  switch (value) {
    case "mode":
    case "model":
    case "model_config":
    case "thought_level":
      return value;
    default:
      return "other";
  }
}

function flattenConfigChoices(value: unknown): DriverConfigChoice[] {
  if (!Array.isArray(value)) return [];
  const choices: DriverConfigChoice[] = [];
  for (const item of value) {
    const candidate = record(item);
    if (!candidate) continue;
    if (typeof candidate.value === "string" && typeof candidate.name === "string") {
      choices.push({
        value: candidate.value,
        label: candidate.name,
        description:
          typeof candidate.description === "string" ? candidate.description : undefined,
      });
      continue;
    }
    choices.push(...flattenConfigChoices(candidate.options));
  }
  return choices;
}

function normalizeConfigOptions(value: unknown): DriverConfigOption[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): DriverConfigOption[] => {
    const option = record(item);
    if (!option || typeof option.id !== "string" || typeof option.name !== "string") {
      return [];
    }
    const description =
      typeof option.description === "string" ? option.description : undefined;
    if (option.type === "boolean" && typeof option.currentValue === "boolean") {
      return [
        {
          id: `config:${option.id}`,
          label: option.name,
          description,
          category: optionCategory(option.category),
          kind: "boolean",
          currentValue: option.currentValue,
        },
      ];
    }
    if (option.type !== "select" || typeof option.currentValue !== "string") return [];
    const choices = flattenConfigChoices(option.options);
    return [
      {
        id: `config:${option.id}`,
        label: option.name,
        description,
        category: optionCategory(option.category),
        kind: "select",
        currentValue: option.currentValue,
        choices,
      },
    ];
  });
}

function normalizeLegacyMode(value: unknown): DriverConfigOption | null {
  const modes = record(value);
  if (!modes || typeof modes.currentModeId !== "string") return null;
  const choices = Array.isArray(modes.availableModes)
    ? modes.availableModes.flatMap((item): DriverConfigChoice[] => {
        const mode = record(item);
        if (!mode || typeof mode.id !== "string") return [];
        return [
          {
            value: mode.id,
            label: typeof mode.name === "string" ? mode.name : mode.id,
            description: typeof mode.description === "string" ? mode.description : undefined,
          },
        ];
      })
    : [];
  if (!choices.length) return null;
  return {
    id: "mode",
    label: "Chế độ",
    category: "mode",
    kind: "select",
    currentValue: modes.currentModeId,
    choices,
  };
}

function normalizeLegacyModel(value: unknown): DriverConfigOption | null {
  const models = record(value);
  if (!models || typeof models.currentModelId !== "string") return null;
  const choices = Array.isArray(models.availableModels)
    ? models.availableModels.flatMap((item): DriverConfigChoice[] => {
        const model = record(item);
        if (!model || typeof model.modelId !== "string") return [];
        return [
          {
            value: model.modelId,
            label: typeof model.name === "string" ? model.name : model.modelId,
            description: typeof model.description === "string" ? model.description : undefined,
          },
        ];
      })
    : [];
  if (!choices.length) return null;
  return {
    id: "model",
    label: "Model",
    category: "model",
    kind: "select",
    currentValue: models.currentModelId,
    choices,
  };
}

function normalizeCommands(value: unknown): DriverCommand[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): DriverCommand[] => {
    const command = record(item);
    if (!command || typeof command.name !== "string") return [];
    const input = record(command.input);
    return [
      {
        name: command.name.replace(/^\/+/, ""),
        description:
          typeof command.description === "string" ? command.description : command.name,
        inputHint: input && typeof input.hint === "string" ? input.hint : undefined,
      },
    ];
  });
}

interface PendingPermission {
  resolve: (result: unknown) => void;
  /** Option ids the agent offered — decisions outside this set fail closed. */
  offered: Set<string>;
}

export class AcpDriver implements Driver {
  readonly kind = "acp" as const;
  readonly sessionId: string;
  readonly runtime: Driver["runtime"] = {
    capabilities: [
      "prompt",
      "cancel",
      "permission-resolution",
      "session-config",
    ],
    // Upgraded after initialize only when the agent advertises session/resume.
    contextContinuity: "process",
    // cwd scopes the session semantically, but no OS sandbox is enforced.
    workspaceIsolation: "advisory",
  };

  private readonly cwd: string;
  private readonly resumeSessionId: string | null;
  private readonly emit: DriverEventHandler;
  private readonly client: AcpJsonRpcClient;
  private acpSessionId: string | null = null;
  private supportsClose = false;
  get backendSessionId(): string | null {
    return this.acpSessionId;
  }
  private turnRunning = false;
  private permissionSeq = 0;
  private readonly pendingPermissions = new Map<string, PendingPermission>();
  /** Per-session activity cache so tool_call_update can merge partial data. */
  private readonly activities = new Map<string, DriverActivity>();
  private stableControls: DriverConfigOption[] = [];
  private legacyMode: DriverConfigOption | null = null;
  private legacyModel: DriverConfigOption | null = null;
  private controls: DriverConfigOption[] = [];
  private readonly controlRoutes = new Map<string, ControlRoute>();

  constructor(options: AcpDriverOptions) {
    this.sessionId = options.sessionId;
    this.cwd = options.cwd;
    this.resumeSessionId = options.resumeSessionId ?? null;
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
    const init = (await this.client.request("initialize", {
      protocolVersion: ACP_PROTOCOL_VERSION,
      // v0 policy (PROTOCOL-NOTES): no client fs/terminal — every side effect
      // must surface through session/request_permission (FR-006).
      clientCapabilities: {
        fs: { readTextFile: false, writeTextFile: false },
        terminal: false,
      },
      clientInfo: {
        name: "wiii-neko-chill",
        title: "Wiii Workbench · Neko Chill",
        version: APP_VERSION,
      },
    })) as { protocolVersion?: unknown; agentCapabilities?: unknown };
    // T602: version drift between agents (neko acp vs Gemini CLI) must be an
    // actionable error, not a stream of confusing protocol failures.
    if (
      typeof init?.protocolVersion === "number" &&
      init.protocolVersion !== ACP_PROTOCOL_VERSION
    ) {
      throw new Error(
        `Agent nói ACP v${init.protocolVersion}, Wiii cần v${ACP_PROTOCOL_VERSION} — hãy cập nhật agent hoặc Wiii.`,
      );
    }
    const capabilities = record(init?.agentCapabilities);
    const sessionCapabilities = record(capabilities?.sessionCapabilities);
    const canResume = capabilities?.loadSession === true && record(sessionCapabilities?.resume) !== null;
    this.supportsClose = record(sessionCapabilities?.close) !== null;
    if (this.resumeSessionId && !canResume) {
      throw new Error(
        "Phiên này có checkpoint ACP bền vững nhưng agent hiện tại không hỗ trợ session/resume; Wiii sẽ không âm thầm tạo phiên mới và làm mất ngữ cảnh.",
      );
    }
    const method = this.resumeSessionId ? "session/resume" : "session/new";
    const session = (await this.client.request(method, {
      ...(this.resumeSessionId ? { sessionId: this.resumeSessionId } : {}),
      cwd: this.cwd,
      // Neko refuses client-supplied MCP servers; Wiii never expands authority here.
      mcpServers: [],
    })) as {
      sessionId?: unknown;
      configOptions?: unknown;
      modes?: unknown;
      models?: unknown;
    };
    const backendSessionId = method === "session/resume"
      ? this.resumeSessionId
      : session?.sessionId;
    if (typeof backendSessionId !== "string" || !backendSessionId) {
      throw new Error(`${method} returned no sessionId`);
    }
    this.acpSessionId = backendSessionId;
    this.runtime.contextContinuity = canResume ? "resumable" : "process";
    this.stableControls = normalizeConfigOptions(session.configOptions);
    this.legacyMode = normalizeLegacyMode(session.modes);
    this.legacyModel = normalizeLegacyModel(session.models);
    this.rebuildControls();
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

  async setConfigOption(optionId: string, value: string | boolean): Promise<void> {
    if (!this.acpSessionId) throw new Error("driver not started");
    if (this.turnRunning) throw new Error("cannot change session controls while a turn is running");
    const route = this.controlRoutes.get(optionId);
    const option = this.controls.find((candidate) => candidate.id === optionId);
    if (!route || !option) throw new Error(`unknown session option ${optionId}`);
    if (option.kind === "boolean" && typeof value !== "boolean") {
      throw new Error(`session option ${optionId} expects a boolean`);
    }
    if (option.kind === "select") {
      if (typeof value !== "string") throw new Error(`session option ${optionId} expects a value id`);
      if (!option.choices?.some((choice) => choice.value === value)) {
        throw new Error(`unsupported value for session option ${optionId}`);
      }
    }

    if (route.kind === "config") {
      const result = (await this.client.request("session/set_config_option", {
        sessionId: this.acpSessionId,
        configId: route.wireId,
        value,
        ...(typeof value === "boolean" ? { type: "boolean" } : {}),
      })) as { configOptions?: unknown };
      if (Array.isArray(result?.configOptions)) {
        this.stableControls = normalizeConfigOptions(result.configOptions);
      } else {
        this.updateControl(optionId, value);
      }
      this.rebuildControls();
      return;
    }

    if (typeof value !== "string") throw new Error(`session option ${optionId} expects a value id`);
    if (route.kind === "mode") {
      await this.client.request("session/set_mode", {
        sessionId: this.acpSessionId,
        modeId: value,
      });
      if (this.legacyMode) this.legacyMode = { ...this.legacyMode, currentValue: value };
    } else {
      await this.client.request("session/set_model", {
        sessionId: this.acpSessionId,
        modelId: value,
      });
      if (this.legacyModel) this.legacyModel = { ...this.legacyModel, currentValue: value };
    }
    this.rebuildControls();
  }

  async dispose(): Promise<void> {
    // Unanswered permission requests fail closed before the process dies.
    for (const [, pending] of this.pendingPermissions) {
      pending.resolve({ outcome: { outcome: "cancelled" } });
    }
    this.pendingPermissions.clear();
    if (this.acpSessionId && this.supportsClose) {
      await this.client
        .request("session/close", { sessionId: this.acpSessionId }, 1_000)
        .catch(() => {
          /* A crashed or legacy agent may not answer; transport cleanup still wins. */
        });
    }
    await this.client.dispose();
  }

  // -------------------------------------------------------------------- //

  private emitEvent(event: DriverEvent): void {
    this.emit(event);
  }

  private updateControl(optionId: string, value: string | boolean): void {
    this.stableControls = this.stableControls.map((option) =>
      option.id === optionId ? { ...option, currentValue: value } : option,
    );
  }

  private rebuildControls(): void {
    const categories = new Set(this.stableControls.map((option) => option.category));
    this.controls = [
      ...this.stableControls,
      ...(this.legacyMode && !categories.has("mode") ? [this.legacyMode] : []),
      ...(this.legacyModel && !categories.has("model") ? [this.legacyModel] : []),
    ];
    this.controlRoutes.clear();
    for (const option of this.stableControls) {
      this.controlRoutes.set(option.id, { kind: "config", wireId: option.id.slice(7) });
    }
    if (this.controls.some((option) => option.id === "mode")) {
      this.controlRoutes.set("mode", { kind: "mode" });
    }
    if (this.controls.some((option) => option.id === "model")) {
      this.controlRoutes.set("model", { kind: "model" });
    }
    this.emitEvent({
      type: "session-controls",
      sessionId: this.sessionId,
      controls: this.controls.map((option) => ({
        ...option,
        choices: option.choices?.map((choice) => ({ ...choice })),
      })),
    });
  }

  private handleNotification(method: string, params: unknown): void {
    if (method !== "session/update") return;
    const update = (params as { update?: Record<string, unknown> })?.update;
    if (!update || typeof update !== "object") return;

    switch (update.sessionUpdate) {
      case "available_commands_update": {
        this.emitEvent({
          type: "available-commands",
          sessionId: this.sessionId,
          commands: normalizeCommands(update.availableCommands),
        });
        return;
      }
      case "config_option_update": {
        this.stableControls = normalizeConfigOptions(update.configOptions);
        this.rebuildControls();
        return;
      }
      case "current_mode_update": {
        if (this.legacyMode && typeof update.currentModeId === "string") {
          this.legacyMode = { ...this.legacyMode, currentValue: update.currentModeId };
          this.rebuildControls();
        }
        return;
      }
      case "session_info_update": {
        const meta = record(update._meta);
        const continuityLevel = meta?.continuityLevel === "durable" || meta?.continuityLevel === "recovered"
          ? meta.continuityLevel
          : undefined;
        this.emitEvent({
          type: "session-info",
          sessionId: this.sessionId,
          title:
            typeof update.title === "string" || update.title === null
              ? update.title
              : undefined,
          updatedAt:
            typeof update.updatedAt === "string" || update.updatedAt === null
              ? update.updatedAt
              : undefined,
          ...(continuityLevel ? { continuityLevel } : {}),
          ...(typeof meta?.revision === "number" && Number.isFinite(meta.revision)
            ? { revision: meta.revision }
            : {}),
        });
        return;
      }
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
          toolName:
            typeof update.name === "string" && update.name
              ? update.name
              : previous?.toolName,
          operation:
            activityOperation(update.kind, update.name) ?? previous?.operation,
          locations: activityLocations(update.locations) ?? previous?.locations,
          rawInput: update.rawInput ?? previous?.rawInput,
          rawOutput: update.rawOutput ?? previous?.rawOutput,
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
