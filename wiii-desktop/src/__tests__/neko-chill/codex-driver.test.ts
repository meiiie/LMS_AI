import { describe, expect, it, vi } from "vitest";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import {
  CodexAppServerDriver,
  normalizeCodexItem,
} from "@/neko-chill/drivers/codex/driver";
import type { DriverEvent } from "@/neko-chill/drivers/types";

class FakeCodexTransport implements AcpTransport {
  readonly sent: Array<Record<string, unknown>> = [];
  private lineHandler: ((line: string) => void) | null = null;
  private exitHandler: ((code: number | null) => void) | null = null;
  killed = false;
  killCalls = 0;
  killFailures = 0;
  completeSynchronously = false;
  returnTurnId = true;
  modelData: unknown[] = [
    {
      model: "gpt-test",
      displayName: "GPT Test",
      description: "fixture model",
      hidden: false,
      isDefault: true,
      supportedReasoningEfforts: [{ reasoningEffort: "high", description: "High" }],
    },
    {
      model: "gpt-fast",
      displayName: "GPT Fast",
      description: "fixture fast model",
      hidden: false,
      isDefault: false,
      supportedReasoningEfforts: [{ reasoningEffort: "low", description: "Low" }],
    },
  ];

  async send(line: string): Promise<void> {
    const frame = JSON.parse(line) as Record<string, unknown>;
    this.sent.push(frame);
    if (typeof frame.id !== "number" || typeof frame.method !== "string") return;
    const id = frame.id;
    const respond = (result: unknown) => this.emit({ jsonrpc: "2.0", id, result });
    if (frame.method === "initialize") respond({ userAgent: "codex", codexHome: "C:/Codex", platformFamily: "windows", platformOs: "windows" });
    else if (frame.method === "account/read") respond({ account: { type: "chatgpt", email: null, planType: "plus" }, requiresOpenaiAuth: true });
    else if (frame.method === "model/list") respond({
      data: this.modelData,
      nextCursor: null,
    });
    else if (frame.method === "thread/start") respond({
      thread: { id: "thread-1", name: null, preview: "", updatedAt: 1 },
      model: "gpt-test",
    });
    else if (frame.method === "turn/start") {
      respond({
        turn: {
          ...(this.returnTurnId ? { id: "turn-1" } : {}),
          status: "inProgress",
          items: [],
        },
      });
      if (!this.returnTurnId) return;
      const complete = () => {
        this.emit({ jsonrpc: "2.0", method: "item/reasoning/textDelta", params: { delta: "nghĩ" } });
        this.emit({ jsonrpc: "2.0", method: "item/agentMessage/delta", params: { delta: "xong" } });
        this.emit({
          jsonrpc: "2.0",
          method: "turn/completed",
          params: { turn: { id: "turn-1", status: "completed" } },
        });
      };
      if (this.completeSynchronously) complete();
      else setTimeout(complete, 0);
    } else if (frame.method === "turn/interrupt") respond({});
  }

  onLine(handler: (line: string) => void): void {
    this.lineHandler = handler;
  }

  onExit(handler: (code: number | null) => void): void {
    this.exitHandler = handler;
  }

  async kill(): Promise<void> {
    this.killCalls += 1;
    if (this.killFailures > 0) {
      this.killFailures -= 1;
      throw new Error("cancel response lost");
    }
    this.killed = true;
  }

  emit(frame: unknown): void {
    this.lineHandler?.(JSON.stringify(frame));
  }

  exit(code: number | null): void {
    this.exitHandler?.(code);
  }
}

async function startFixture(completeSynchronously = false, modelData?: unknown[]) {
  const transport = new FakeCodexTransport();
  transport.completeSynchronously = completeSynchronously;
  if (modelData) transport.modelData = modelData;
  const events: DriverEvent[] = [];
  const driver = new CodexAppServerDriver({
    sessionId: "local-1",
    cwd: "C:/project",
    transport,
    onEvent: (event) => events.push(event),
  });
  await driver.start();
  return { driver, events, transport };
}

describe("Codex App Server driver", () => {
  it("initializes provider-owned account, models, and a durable thread", async () => {
    const { driver, events, transport } = await startFixture();
    expect(driver.kind).toBe("codex-app-server");
    expect(driver.backendSessionId).toBe("thread-1");
    expect(driver.runtime.observedProviderCapabilities).toEqual(expect.objectContaining({
      resume: true,
      modelSelection: true,
      reasoning: true,
      approvals: true,
      toolEvents: true,
      diff: true,
    }));
    expect(events).toContainEqual(expect.objectContaining({
      type: "session-controls",
      controls: expect.arrayContaining([
        expect.objectContaining({ id: "model", currentValue: "gpt-test" }),
      ]),
    }));
    expect(transport.sent.find((frame) => frame.method === "thread/start")?.params).toEqual(
      expect.objectContaining({ approvalPolicy: "on-request", sandbox: "workspace-write" }),
    );
  });

  it("normalizes reasoning, answer, and turn completion", async () => {
    const { driver, events } = await startFixture();
    await driver.prompt("hello");
    expect(events.map((event) => event.type)).toEqual(expect.arrayContaining([
      "turn-started",
      "reasoning-delta",
      "answer-delta",
      "turn-finished",
    ]));
    expect(events).toContainEqual({
      type: "turn-finished",
      sessionId: "local-1",
      stopReason: "end_turn",
    });
  });

  it("does not advertise model or reasoning controls when the catalog is empty", async () => {
    const { driver } = await startFixture(false, []);

    expect(driver.runtime.observedProviderCapabilities).toEqual(expect.objectContaining({
      modelSelection: false,
      reasoning: false,
    }));
  });

  it("does not lose a completion delivered before the turn waiter is installed", async () => {
    const { driver, events } = await startFixture(true);
    await driver.prompt("fast turn");
    expect(events).toContainEqual({
      type: "turn-finished",
      sessionId: "local-1",
      stopReason: "end_turn",
    });
  });

  it("does not announce a turn until App Server returns a durable turn id", async () => {
    const { driver, events, transport } = await startFixture();
    transport.returnTurnId = false;
    await expect(driver.prompt("broken turn")).rejects.toThrow("turn.id");
    expect(events.some((event) => event.type === "turn-started")).toBe(false);

    transport.returnTurnId = true;
    await expect(driver.prompt("retry")).resolves.toBeUndefined();
    expect(events.some((event) => event.type === "turn-started")).toBe(true);
  });

  it("rebuilds reasoning choices when the selected model changes", async () => {
    const { driver, events, transport } = await startFixture();
    await driver.setConfigOption("model", "gpt-fast");
    const controlsEvent = [...events].reverse().find(
      (event) => event.type === "session-controls",
    );
    expect(controlsEvent).toEqual(expect.objectContaining({
      controls: expect.arrayContaining([
        expect.objectContaining({
          id: "reasoning-effort",
          currentValue: "low",
          choices: [expect.objectContaining({ value: "low" })],
        }),
      ]),
    }));

    await driver.prompt("use the selected model");
    const request = [...transport.sent].reverse().find(
      (frame) => frame.method === "turn/start",
    );
    expect(request?.params).toEqual(expect.objectContaining({
      model: "gpt-fast",
      effort: "low",
    }));
  });

  it("routes explicit approvals and fails closed on dismiss", async () => {
    const { driver, events, transport } = await startFixture();
    transport.emit({
      jsonrpc: "2.0",
      id: "approval-77",
      method: "item/commandExecution/requestApproval",
      params: { itemId: "cmd-1", command: "npm test" },
    });
    await vi.waitFor(() => expect(events.some((event) => event.type === "permission-request")).toBe(true));
    const request = events.find((event) => event.type === "permission-request");
    if (!request || request.type !== "permission-request") throw new Error("missing request");
    await driver.resolvePermission({ requestId: request.request.requestId, optionId: null });
    await vi.waitFor(() => {
      expect(transport.sent).toContainEqual(expect.objectContaining({
        id: "approval-77",
        result: { decision: "cancel" },
      }));
    });
  });

  it("ignores unknown notifications and rejects unsupported server requests", async () => {
    const { transport } = await startFixture();
    transport.emit({ jsonrpc: "2.0", method: "future/event", params: { value: 1 } });
    transport.emit({ jsonrpc: "2.0", id: 91, method: "future/request", params: {} });
    await vi.waitFor(() => {
      expect(transport.sent).toContainEqual(expect.objectContaining({
        id: 91,
        error: expect.objectContaining({ code: -32601 }),
      }));
    });
  });

  it("retries cleanup with the same transport after a lost cancellation response", async () => {
    const { driver, transport } = await startFixture();
    transport.killFailures = 1;

    await expect(driver.dispose()).rejects.toThrow("cancel response lost");
    await expect(driver.dispose()).resolves.toBeUndefined();
    await expect(driver.dispose()).resolves.toBeUndefined();

    expect(transport.killCalls).toBe(2);
    expect(transport.killed).toBe(true);
  });
});

describe("Codex item normalization", () => {
  it("keeps structured file locations and operations", () => {
    expect(normalizeCodexItem({
      type: "fileChange",
      id: "file-1",
      status: "completed",
      changes: [{ path: "C:/project/src/App.tsx", kind: { type: "add" }, diff: "+hello" }],
    }, true)).toEqual(expect.objectContaining({
      kind: "file",
      operation: "create",
      locations: [{ path: "C:/project/src/App.tsx" }],
      status: "completed",
    }));
  });
});
