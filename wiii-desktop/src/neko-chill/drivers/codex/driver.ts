/**
 * Codex App Server adapter.
 *
 * Codex owns its account tokens, model catalog, thread checkpoints and tool
 * sandbox. Wiii only speaks the documented JSON-RPC protocol and normalizes
 * observable events into the provider-neutral Driver contract.
 */
import { v4 as uuidv4 } from "uuid";
import { APP_VERSION } from "@/lib/constants";
import {
  AcpJsonRpcClient,
  UnsupportedMethodError,
  type AcpTransport,
} from "../acp/client";
import type {
  Driver,
  DriverActivity,
  DriverConfigOption,
  DriverEvent,
  DriverEventHandler,
  PermissionDecision,
  TurnStopReason,
} from "../types";

type JsonRecord = Record<string, unknown>;

interface CodexDriverOptions {
  sessionId: string;
  cwd: string;
  resumeThreadId?: string | null;
  transport: AcpTransport;
  onEvent: DriverEventHandler;
}

interface PendingApproval {
  kind: "command" | "file";
  resolve: (result: unknown) => void;
}

interface CodexModelCatalog {
  controls: DriverConfigOption[];
  reasoningChoicesByModel: Map<string, NonNullable<DriverConfigOption["choices"]>>;
}

function record(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function turnStopReason(status: unknown): TurnStopReason {
  if (status === "completed") return "end_turn";
  if (status === "interrupted") return "cancelled";
  return "error";
}

function activityStatus(value: unknown): DriverActivity["status"] {
  switch (value) {
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "declined":
      return "cancelled";
    default:
      return "in_progress";
  }
}

function patchOperation(change: JsonRecord): DriverActivity["operation"] {
  const kind = record(change.kind);
  if (kind?.type === "add") return "create";
  if (kind?.type === "delete") return "delete";
  if (kind?.type === "update" && typeof kind.move_path === "string") return "move";
  return "update";
}

export function normalizeCodexItem(
  value: unknown,
  completed: boolean,
): DriverActivity | null {
  const item = record(value);
  const id = text(item?.id);
  const type = text(item?.type);
  if (!item || !id || !type) return null;

  if (type === "commandExecution") {
    const command = text(item.command) ?? "Lệnh terminal";
    return {
      id,
      title: command,
      kind: "command",
      status: completed ? activityStatus(item.status) : "in_progress",
      toolName: "commandExecution",
      rawInput: { command, cwd: item.cwd },
      rawOutput: item.aggregatedOutput,
    };
  }

  if (type === "fileChange") {
    const changes: JsonRecord[] = Array.isArray(item.changes)
      ? item.changes.flatMap((candidate) => {
          const change = record(candidate);
          return change ? [change] : [];
        })
      : [];
    const locations = changes.flatMap((change) =>
      typeof change.path === "string" ? [{ path: change.path }] : [],
    );
    return {
      id,
      title: locations.length === 1
        ? `${completed ? "Đã cập nhật" : "Đang cập nhật"} ${locations[0].path}`
        : `${completed ? "Đã cập nhật" : "Đang cập nhật"} ${locations.length} tệp`,
      kind: "file",
      status: completed ? activityStatus(item.status) : "in_progress",
      toolName: "fileChange",
      operation: changes[0] ? patchOperation(changes[0]) : "update",
      locations,
      rawInput: item.changes,
    };
  }

  if (type === "mcpToolCall" || type === "dynamicToolCall") {
    const tool = text(item.tool) ?? "tool";
    const server = text(item.server);
    return {
      id,
      title: server ? `${server} · ${tool}` : tool,
      kind: "tool",
      status: completed ? activityStatus(item.status) : "in_progress",
      toolName: tool,
      rawInput: item.arguments,
      rawOutput: item.result ?? item.contentItems,
    };
  }

  if (type === "webSearch") {
    return {
      id,
      title: text(item.query) ?? "Tìm kiếm web",
      kind: "search",
      status: completed ? "completed" : "in_progress",
      toolName: "webSearch",
      rawInput: item,
    };
  }

  if (type === "plan") {
    return {
      id,
      title: "Cập nhật kế hoạch",
      kind: "plan",
      status: completed ? "completed" : "in_progress",
      detail: text(item.text) ?? undefined,
      toolName: "plan",
    };
  }

  return null;
}

function modelControls(models: unknown): CodexModelCatalog {
  if (!Array.isArray(models)) {
    return { controls: [], reasoningChoicesByModel: new Map() };
  }
  const choices = models.flatMap((value) => {
    const model = record(value);
    if (!model || typeof model.model !== "string" || model.hidden === true) return [];
    return [{
      value: model.model,
      label: typeof model.displayName === "string" ? model.displayName : model.model,
      description: typeof model.description === "string" ? model.description : undefined,
      isDefault: model.isDefault === true,
      efforts: Array.isArray(model.supportedReasoningEfforts)
        ? model.supportedReasoningEfforts
        : [],
    }];
  });
  if (!choices.length) {
    return { controls: [], reasoningChoicesByModel: new Map() };
  }
  const selected = choices.find((choice) => choice.isDefault) ?? choices[0];
  const reasoningChoicesByModel = new Map(
    choices.map((choice) => [
      choice.value,
      choice.efforts.flatMap((value) => {
        const effort = record(value);
        return typeof effort?.reasoningEffort === "string"
          ? [{
              value: effort.reasoningEffort,
              label: effort.reasoningEffort,
              description: typeof effort.description === "string" ? effort.description : undefined,
            }]
          : [];
      }),
    ]),
  );
  const effortChoices = reasoningChoicesByModel.get(selected.value) ?? [];
  return {
    controls: [
      {
        id: "model",
        label: "Model",
        category: "model",
        kind: "select",
        currentValue: selected.value,
        choices: choices.map(({ value, label, description }) => ({ value, label, description })),
      },
      ...(effortChoices.length
        ? [{
            id: "reasoning-effort",
            label: "Mức suy luận",
            category: "thought_level" as const,
            kind: "select" as const,
            currentValue: effortChoices[0].value,
            choices: effortChoices,
          }]
        : []),
    ],
    reasoningChoicesByModel,
  };
}

export class CodexAppServerDriver implements Driver {
  readonly kind = "codex-app-server" as const;
  readonly sessionId: string;
  readonly runtime: Driver["runtime"] = {
    capabilities: ["prompt", "cancel", "permission-resolution", "session-config"],
    contextContinuity: "resumable",
    workspaceIsolation: "enforced",
  };

  private readonly cwd: string;
  private readonly resumeThreadId: string | null;
  private readonly emit: DriverEventHandler;
  private readonly client: AcpJsonRpcClient;
  private threadId: string | null = null;
  private turnId: string | null = null;
  private controls: DriverConfigOption[] = [];
  private reasoningChoicesByModel = new Map<
    string,
    NonNullable<DriverConfigOption["choices"]>
  >();
  private readonly approvals = new Map<string, PendingApproval>();
  private readonly completedBeforeWait = new Map<string, TurnStopReason>();
  private finishTurn: ((reason: TurnStopReason) => void) | null = null;
  private disposed = false;

  get backendSessionId(): string | null {
    return this.threadId;
  }

  constructor(options: CodexDriverOptions) {
    this.sessionId = options.sessionId;
    this.cwd = options.cwd;
    this.resumeThreadId = options.resumeThreadId ?? null;
    this.emit = options.onEvent;
    this.client = new AcpJsonRpcClient(options.transport, {
      onAgentRequest: (method, params) => this.handleServerRequest(method, params),
      onNotification: (method, params) => this.handleNotification(method, params),
      onProtocolError: (message) => this.emitEvent({
        type: "error",
        sessionId: this.sessionId,
        message: `Codex App Server: ${message}`,
        fatal: false,
      }),
    });
    options.transport.onExit((code) => {
      this.finishTurn?.("error");
      this.finishTurn = null;
      this.emitEvent({ type: "process-exited", sessionId: this.sessionId, code });
    });
  }

  async start(): Promise<void> {
    await this.client.request("initialize", {
      clientInfo: {
        name: "wiii-workbench",
        title: "Wiii Workbench",
        version: APP_VERSION,
      },
      capabilities: {
        experimentalApi: true,
        requestAttestation: false,
      },
    });
    await this.client.notify("initialized", {});

    const accountResult = record(await this.client.request("account/read", {
      refreshToken: false,
    }));
    if (accountResult?.requiresOpenaiAuth === true && !accountResult.account) {
      throw new Error(
        "Codex chưa đăng nhập. Hãy chạy `codex login`, rồi thử lại; Wiii không đọc hoặc lưu token Codex.",
      );
    }

    const modelsResult = record(await this.client.request("model/list", {
      includeHidden: false,
    }));
    const catalog = modelControls(modelsResult?.data);
    this.controls = catalog.controls;
    this.reasoningChoicesByModel = catalog.reasoningChoicesByModel;

    const model = this.controls.find((option) => option.id === "model")?.currentValue;
    const method = this.resumeThreadId ? "thread/resume" : "thread/start";
    const result = record(await this.client.request(method, {
      ...(this.resumeThreadId ? { threadId: this.resumeThreadId } : {}),
      cwd: this.cwd,
      ...(typeof model === "string" ? { model } : {}),
      approvalPolicy: "on-request",
      sandbox: "workspace-write",
    }));
    const thread = record(result?.thread);
    this.threadId = text(thread?.id) ?? this.resumeThreadId;
    if (!this.threadId) throw new Error(`${method} không trả về thread.id`);
    this.emitEvent({
      type: "session-controls",
      sessionId: this.sessionId,
      controls: this.controls,
    });
    this.emitEvent({
      type: "session-info",
      sessionId: this.sessionId,
      title: text(thread?.name) ?? text(thread?.preview),
      updatedAt: typeof thread?.updatedAt === "number"
        ? new Date(thread.updatedAt * 1000).toISOString()
        : null,
      continuityLevel: "durable",
    });
  }

  async prompt(promptText: string): Promise<void> {
    if (!this.threadId) throw new Error("Codex driver chưa khởi động");
    if (this.finishTurn) throw new Error("Một lượt Codex đang chạy");

    const result = record(await this.client.request("turn/start", {
      threadId: this.threadId,
      clientUserMessageId: uuidv4(),
      input: [{ type: "text", text: promptText, text_elements: [] }],
      cwd: this.cwd,
      ...(this.controlValue("model") ? { model: this.controlValue("model") } : {}),
      ...(this.controlValue("reasoning-effort")
        ? { effort: this.controlValue("reasoning-effort") }
        : {}),
    }));
    const turn = record(result?.turn);
    this.turnId = text(turn?.id);
    if (!this.turnId) throw new Error("turn/start không trả về turn.id");
    this.emitEvent({ type: "turn-started", sessionId: this.sessionId });

    const completedReason = this.completedBeforeWait.get(this.turnId);
    if (completedReason) this.completedBeforeWait.delete(this.turnId);
    const reason = completedReason ?? await new Promise<TurnStopReason>((resolve) => {
      this.finishTurn = resolve;
    });
    this.finishTurn = null;
    this.turnId = null;
    this.emitEvent({ type: "turn-finished", sessionId: this.sessionId, stopReason: reason });
  }

  async cancel(): Promise<void> {
    if (!this.threadId || !this.turnId) return;
    await this.client.request("turn/interrupt", {
      threadId: this.threadId,
      turnId: this.turnId,
    });
  }

  async resolvePermission(decision: PermissionDecision): Promise<void> {
    const pending = this.approvals.get(decision.requestId);
    if (!pending) return;
    this.approvals.delete(decision.requestId);
    const selected = decision.optionId;
    const wireDecision = selected === "allow_once"
      ? "accept"
      : selected === "allow_session"
        ? "acceptForSession"
        : selected === "reject_once"
          ? "decline"
          : "cancel";
    pending.resolve({ decision: wireDecision });
  }

  async setConfigOption(optionId: string, value: string | boolean): Promise<void> {
    if (this.finishTurn) throw new Error("Không thể đổi cấu hình khi Codex đang chạy");
    const option = this.controls.find((candidate) => candidate.id === optionId);
    if (!option) throw new Error(`Tùy chọn Codex không tồn tại: ${optionId}`);
    if (option.kind !== "select" || typeof value !== "string") {
      throw new Error(`Tùy chọn Codex không chấp nhận giá trị này: ${optionId}`);
    }
    if (!option.choices?.some((choice) => choice.value === value)) {
      throw new Error(`Giá trị Codex không được hỗ trợ: ${value}`);
    }
    option.currentValue = value;
    if (optionId === "model") this.syncReasoningControl(value);
    this.emitEvent({
      type: "session-controls",
      sessionId: this.sessionId,
      controls: this.controls.map((control) => ({ ...control })),
    });
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    for (const [, pending] of this.approvals) pending.resolve({ decision: "cancel" });
    this.approvals.clear();
    this.completedBeforeWait.clear();
    this.finishTurn?.("cancelled");
    this.finishTurn = null;
    await this.client.dispose();
  }

  private controlValue(id: string): string | undefined {
    const value = this.controls.find((option) => option.id === id)?.currentValue;
    return typeof value === "string" ? value : undefined;
  }

  private syncReasoningControl(model: string): void {
    const choices = this.reasoningChoicesByModel.get(model) ?? [];
    const existingIndex = this.controls.findIndex(
      (option) => option.id === "reasoning-effort",
    );
    const existing = existingIndex >= 0 ? this.controls[existingIndex] : null;

    if (!choices.length) {
      if (existingIndex >= 0) this.controls.splice(existingIndex, 1);
      return;
    }

    const currentValue =
      typeof existing?.currentValue === "string" &&
        choices.some((choice) => choice.value === existing.currentValue)
        ? existing.currentValue
        : choices[0].value;
    const next: DriverConfigOption = {
      id: "reasoning-effort",
      label: "Mức suy luận",
      category: "thought_level",
      kind: "select",
      currentValue,
      choices,
    };
    if (existingIndex >= 0) this.controls[existingIndex] = next;
    else this.controls.push(next);
  }

  private async handleServerRequest(method: string, paramsValue: unknown): Promise<unknown> {
    if (
      method !== "item/commandExecution/requestApproval" &&
      method !== "item/fileChange/requestApproval"
    ) {
      throw new UnsupportedMethodError(`Wiii chưa hỗ trợ Codex request ${method}`);
    }
    const params = record(paramsValue) ?? {};
    const requestId = uuidv4();
    const kind = method.includes("commandExecution") ? "command" : "file";
    const title = kind === "command"
      ? text(params.command) ?? text(params.reason) ?? "Codex muốn chạy một lệnh"
      : text(params.reason) ?? "Codex muốn thay đổi tệp";

    return new Promise((resolve) => {
      this.approvals.set(requestId, { kind, resolve });
      this.emitEvent({
        type: "permission-request",
        sessionId: this.sessionId,
        request: {
          requestId,
          title,
          activityId: text(params.itemId) ?? undefined,
          options: [
            { optionId: "allow_once", label: "Cho phép lần này", kind: "allow_once" },
            { optionId: "allow_session", label: "Cho phép trong phiên", kind: "allow_always" },
            { optionId: "reject_once", label: "Từ chối", kind: "reject_once" },
          ],
        },
      });
    });
  }

  private handleNotification(method: string, paramsValue: unknown): void {
    const params = record(paramsValue) ?? {};
    if (method === "item/agentMessage/delta" && typeof params.delta === "string") {
      this.emitEvent({ type: "answer-delta", sessionId: this.sessionId, text: params.delta });
      return;
    }
    if (
      (method === "item/reasoning/textDelta" ||
        method === "item/reasoning/summaryTextDelta") &&
      typeof params.delta === "string"
    ) {
      this.emitEvent({ type: "reasoning-delta", sessionId: this.sessionId, text: params.delta });
      return;
    }
    if (method === "item/started" || method === "item/completed") {
      const activity = normalizeCodexItem(params.item, method === "item/completed");
      if (activity) {
        this.emitEvent({ type: "activity", sessionId: this.sessionId, activity });
      }
      return;
    }
    if (method === "turn/completed") {
      const turn = record(params.turn);
      const completedTurnId = text(turn?.id);
      if (!completedTurnId) return;
      const reason = turnStopReason(turn?.status);
      if (this.turnId === completedTurnId && this.finishTurn) {
        this.finishTurn(reason);
      } else {
        // App Server may complete before the turn/start continuation installs
        // its waiter. Preserve that terminal fact so Wiii cannot hang.
        this.completedBeforeWait.set(completedTurnId, reason);
        if (this.completedBeforeWait.size > 8) {
          const oldest = this.completedBeforeWait.keys().next().value;
          if (oldest) this.completedBeforeWait.delete(oldest);
        }
      }
      return;
    }
    if (method === "error") {
      const error = record(params.error);
      this.emitEvent({
        type: "error",
        sessionId: this.sessionId,
        message: text(error?.message) ?? text(params.message) ?? "Codex App Server báo lỗi",
        fatal: false,
      });
    }
  }

  private emitEvent(event: DriverEvent): void {
    if (!this.disposed) this.emit(event);
  }
}
