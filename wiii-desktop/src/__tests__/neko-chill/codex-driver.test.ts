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
  completeSynchronously = false;

  async send(line: string): Promise<void> {
    const frame = JSON.parse(line) as Record<string, unknown>;
    this.sent.push(frame);
    if (typeof frame.id !== "number" || typeof frame.method !== "string") return;
    const id = frame.id;
    const respond = (result: unknown) => this.emit({ jsonrpc: "2.0", id, result });
    if (frame.method === "initialize") respond({ userAgent: "codex", codexHome: "C:/Codex", platformFamily: "windows", platformOs: "windows" });
    else if (frame.method === "account/read") respond({ account: { type: "chatgpt", email: null, planType: "plus" }, requiresOpenaiAuth: true });
    else if (frame.method === "model/list") respond({
      data: [{
        model: "gpt-test",
        displayName: "GPT Test",
        description: "fixture model",
        hidden: false,
        isDefault: true,
        supportedReasoningEfforts: [{ reasoningEffort: "high", description: "High" }],
      }],
      nextCursor: null,
    });
    else if (frame.method === "thread/start") respond({
      thread: { id: "thread-1", name: null, preview: "", updatedAt: 1 },
      model: "gpt-test",
    });
    else if (frame.method === "turn/start") {
      respond({ turn: { id: "turn-1", status: "inProgress", items: [] } });
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
    this.killed = true;
  }

  emit(frame: unknown): void {
    this.lineHandler?.(JSON.stringify(frame));
  }

  exit(code: number | null): void {
    this.exitHandler?.(code);
  }
}

async function startFixture(completeSynchronously = false) {
  const transport = new FakeCodexTransport();
  transport.completeSynchronously = completeSynchronously;
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

  it("does not lose a completion delivered before the turn waiter is installed", async () => {
    const { driver, events } = await startFixture(true);
    await driver.prompt("fast turn");
    expect(events).toContainEqual({
      type: "turn-finished",
      sessionId: "local-1",
      stopReason: "end_turn",
    });
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
