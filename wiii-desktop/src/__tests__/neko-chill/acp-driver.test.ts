/**
 * T203 — AcpDriver golden-fixture tests.
 *
 * Replays the REAL neko-core v0.24.0 ACP session recorded by
 * scripts/record-acp-fixture.mjs (103 frames) through the driver and asserts
 * the normalized DriverEvent stream, plus fail-closed permission behavior.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { DriverEvent } from "@/neko-chill/drivers/types";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import { AcpDriver } from "@/neko-chill/drivers/acp/driver";

type Frame = Record<string, any>;

const FIXTURE: Array<{ dir: "c2a" | "a2c"; frame?: Frame; raw?: string }> = readFileSync(
  join(__dirname, "fixtures", "neko-acp-session.ndjson"),
  "utf8",
)
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line));

class FakeTransport implements AcpTransport {
  sent: Frame[] = [];
  killed = false;
  private lineHandlers: Array<(line: string) => void> = [];
  private exitHandlers: Array<(code: number | null) => void> = [];

  async send(line: string): Promise<void> {
    this.sent.push(JSON.parse(line));
  }
  onLine(handler: (line: string) => void): void {
    this.lineHandlers.push(handler);
  }
  onExit(handler: (code: number | null) => void): void {
    this.exitHandlers.push(handler);
  }
  async kill(): Promise<void> {
    this.killed = true;
  }
  inject(frame: Frame): void {
    for (const h of this.lineHandlers) h(JSON.stringify(frame));
  }
  exit(code: number | null): void {
    for (const h of this.exitHandlers) h(code);
  }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function agentResponses(): Frame[] {
  // a2c frames that are RESPONSES (id, no method) in recorded order:
  // [initialize, session/new, session/prompt]
  return FIXTURE.filter(
    (r) => r.dir === "a2c" && r.frame && r.frame.id !== undefined && !r.frame.method,
  ).map((r) => r.frame!);
}

function agentMidTurnFrames(): Frame[] {
  // Everything the agent pushed during the turn: notifications + its
  // permission request, in original order.
  return FIXTURE.filter(
    (r) =>
      r.dir === "a2c" &&
      r.frame &&
      r.frame.method !== undefined &&
      (r.frame.id === undefined || r.frame.method === "session/request_permission"),
  ).map((r) => r.frame!);
}

async function startDriver(events: DriverEvent[], transport: FakeTransport): Promise<AcpDriver> {
  const driver = new AcpDriver({
    sessionId: "local-1",
    cwd: "C:/tmp/project",
    transport,
    onEvent: (event) => events.push(event),
  });
  const [initResp, newResp] = agentResponses();
  const starting = driver.start();
  await tick();
  transport.inject({ ...initResp, id: transport.sent[0].id });
  await tick();
  transport.inject({ ...newResp, id: transport.sent[1].id });
  await starting;
  return driver;
}

describe("AcpDriver golden replay (real neko-core v0.24.0 fixture)", () => {
  it("normalizes the full recorded session into DriverEvents", async () => {
    const events: DriverEvent[] = [];
    const transport = new FakeTransport();
    const driver = await startDriver(events, transport);

    // Auto-answer the permission request the way the recorder did: reject.
    const decisions: string[] = [];
    const origPush = events.push.bind(events);
    events.push = (event: DriverEvent) => {
      const result = origPush(event);
      if (event.type === "permission-request") {
        decisions.push(event.request.requestId);
        void driver.resolvePermission({
          requestId: event.request.requestId,
          optionId: "reject_once",
        });
      }
      return result;
    };

    const prompting = driver.prompt("Hãy tạo file hello.txt ...");
    await tick();
    const promptRequestId = transport.sent[2].id;

    let permissionRpcId: number | null = null;
    for (const frame of agentMidTurnFrames()) {
      if (frame.method === "session/request_permission") {
        permissionRpcId = 991;
        transport.inject({ ...frame, id: permissionRpcId });
        await tick(); // let resolvePermission respond
      } else {
        transport.inject(frame);
      }
    }
    const [, , promptResp] = agentResponses();
    transport.inject({ ...promptResp, id: promptRequestId });
    await prompting;

    // Counts derived from the fixture itself — stays valid if re-recorded.
    const updates = agentMidTurnFrames().filter((f) => f.method === "session/update");
    const count = (kind: string) =>
      updates.filter((f) => f.params.update.sessionUpdate === kind).length;

    const byType = (type: DriverEvent["type"]) => events.filter((e) => e.type === type);
    expect(byType("turn-started")).toHaveLength(1);
    expect(byType("reasoning-delta")).toHaveLength(count("agent_thought_chunk"));
    expect(byType("answer-delta")).toHaveLength(count("agent_message_chunk"));
    expect(byType("activity")).toHaveLength(count("tool_call") + count("tool_call_update"));
    expect(byType("permission-request")).toHaveLength(1);
    expect(byType("turn-finished")).toEqual([
      { type: "turn-finished", sessionId: "local-1", stopReason: "end_turn" },
    ]);
    expect(byType("error")).toHaveLength(0);

    // The recorded reject produced a failed tool call — merge must preserve
    // the title from tool_call while taking status from tool_call_update.
    const failed = byType("activity").filter(
      (e) => e.type === "activity" && e.activity.status === "failed",
    );
    expect(failed.length).toBeGreaterThan(0);
    for (const e of failed) {
      if (e.type === "activity") expect(e.activity.title).not.toBe("Tool call");
    }

    // Our permission answer went back on the agent's rpc id, fail-closed shape.
    const answer = transport.sent.find((f) => f.id === permissionRpcId);
    expect(answer?.result?.outcome).toEqual({ outcome: "selected", optionId: "reject_once" });
    expect(decisions).toHaveLength(1);

    // Every emitted event carries the local session id.
    for (const event of events) expect(event.sessionId).toBe("local-1");
  });

  it("fails closed: null decisions, unknown options, and dispose all cancel", async () => {
    const events: DriverEvent[] = [];
    const transport = new FakeTransport();
    const driver = await startDriver(events, transport);

    const permFixture = agentMidTurnFrames().find(
      (f) => f.method === "session/request_permission",
    )!;

    // Case 1: option the agent never offered → cancelled outcome.
    transport.inject({ ...permFixture, id: 501 });
    await tick();
    let request = events.filter((e) => e.type === "permission-request").at(-1)!;
    if (request.type !== "permission-request") throw new Error("unreachable");
    await driver.resolvePermission({ requestId: request.request.requestId, optionId: "hack" });
    expect(transport.sent.find((f) => f.id === 501)?.result?.outcome).toEqual({
      outcome: "cancelled",
    });

    // Case 2: explicit null decision → cancelled outcome.
    transport.inject({ ...permFixture, id: 502 });
    await tick();
    request = events.filter((e) => e.type === "permission-request").at(-1)!;
    if (request.type !== "permission-request") throw new Error("unreachable");
    await driver.resolvePermission({ requestId: request.request.requestId, optionId: null });
    expect(transport.sent.find((f) => f.id === 502)?.result?.outcome).toEqual({
      outcome: "cancelled",
    });

    // Case 3: dispose with a pending request → cancelled, transport killed.
    transport.inject({ ...permFixture, id: 503 });
    await tick();
    await driver.dispose();
    await tick();
    expect(transport.sent.find((f) => f.id === 503)?.result?.outcome).toEqual({
      outcome: "cancelled",
    });
    expect(transport.killed).toBe(true);
  });

  it("surfaces malformed frames as fatal protocol errors", async () => {
    const events: DriverEvent[] = [];
    const transport = new FakeTransport();
    await startDriver(events, transport);

    // FakeTransport.inject stringifies valid JSON, so reach the raw line
    // handlers directly to deliver a malformed frame.
    const anyTransport = transport as unknown as {
      lineHandlers: Array<(line: string) => void>;
    };
    for (const h of anyTransport.lineHandlers) h("not-json{");

    const errors = events.filter((e) => e.type === "error");
    expect(errors).toHaveLength(1);
    if (errors[0].type === "error") {
      expect(errors[0].fatal).toBe(true);
      expect(errors[0].message).toContain("malformed");
    }
  });
});
