/**
 * T302 — neko-session-store: DriverEvent → ContentBlock streaming, turn
 * lifecycle, permission pass-through, cancel, process exit.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";
import {
  useNekoSessionStore,
  _setDriverFactoryForTests,
} from "@/neko-chill/stores/neko-session-store";

const AGENT: DetectedAgent = {
  id: "neko",
  name: "Neko Core",
  binary: "neko",
  version: "0.24.0",
  found: true,
};

class FakeDriver implements Driver {
  readonly kind = "acp" as const;
  prompts: string[] = [];
  cancelled = 0;
  disposed = 0;
  decisions: PermissionDecision[] = [];
  constructor(
    readonly sessionId: string,
    readonly emit: (event: DriverEvent) => void,
  ) {}
  async start(): Promise<void> {}
  async prompt(text: string): Promise<void> {
    this.prompts.push(text);
  }
  async cancel(): Promise<void> {
    this.cancelled += 1;
  }
  async resolvePermission(decision: PermissionDecision): Promise<void> {
    this.decisions.push(decision);
  }
  async dispose(): Promise<void> {
    this.disposed += 1;
  }
}

let driver: FakeDriver;

async function setup(): Promise<string> {
  _setDriverFactoryForTests(async (agent, sessionId, onEvent) => {
    driver = new FakeDriver(sessionId, onEvent);
    return driver;
  });
  return useNekoSessionStore.getState().createSession(AGENT);
}

const emit = (event: DriverEvent) => useNekoSessionStore.getState().handleEvent(event);
const session = (id: string) => useNekoSessionStore.getState().sessions[id];

describe("neko-session-store", () => {
  beforeEach(() => {
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null });
    _setDriverFactoryForTests(undefined);
  });

  it("creates a session, becomes idle, and records the user prompt", async () => {
    const id = await setup();
    expect(session(id).status).toBe("idle");
    expect(useNekoSessionStore.getState().activeSessionId).toBe(id);

    await useNekoSessionStore.getState().sendPrompt("Xin chào");
    expect(driver.prompts).toEqual(["Xin chào"]);
    expect(session(id).messages[0]).toMatchObject({ role: "user", text: "Xin chào" });
    expect(session(id).title).toBe("Xin chào");
  });

  it("streams interleaved thinking/answer/tool blocks in ContentBlock vocabulary", async () => {
    const id = await setup();
    emit({ type: "turn-started", sessionId: id });
    expect(session(id).status).toBe("streaming");

    emit({ type: "reasoning-delta", sessionId: id, text: "Nghĩ " });
    emit({ type: "reasoning-delta", sessionId: id, text: "đã…" });
    emit({
      type: "activity",
      sessionId: id,
      activity: { id: "t1", title: "Write(hello.txt)", kind: "file", status: "pending" },
    });
    emit({ type: "answer-delta", sessionId: id, text: "Chào " });
    emit({ type: "answer-delta", sessionId: id, text: "bạn!" });
    emit({
      type: "activity",
      sessionId: id,
      activity: {
        id: "t1",
        title: "Write(hello.txt)",
        kind: "file",
        status: "failed",
        detail: "Denied by user",
      },
    });
    emit({ type: "turn-finished", sessionId: id, stopReason: "end_turn" });

    const blocks = session(id).messages.at(-1)!.blocks!;
    expect(blocks.map((b) => b.type)).toEqual(["thinking", "tool_execution", "answer"]);
    expect(blocks[0]).toMatchObject({ content: "Nghĩ đã…" });
    // Tool upsert: one block, terminal state renders completed + detail kept.
    expect(blocks[1]).toMatchObject({
      status: "completed",
      tool: { name: "Write(hello.txt)", result: "Denied by user" },
    });
    expect(blocks[2]).toMatchObject({ content: "Chào bạn!" });
    expect(session(id).status).toBe("idle");
  });

  it("passes permission requests through and resolves them on the driver", async () => {
    const id = await setup();
    emit({ type: "turn-started", sessionId: id });
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "perm-1",
        title: "Write(hello.txt)",
        options: [
          { optionId: "allow_once", label: "Cho phép", kind: "allow_once" },
          { optionId: "reject_once", label: "Từ chối", kind: "reject_once" },
        ],
      },
    });
    expect(session(id).pendingPermission?.requestId).toBe("perm-1");

    await useNekoSessionStore.getState().resolvePermission("reject_once");
    expect(session(id).pendingPermission).toBeNull();
    expect(driver.decisions).toEqual([{ requestId: "perm-1", optionId: "reject_once" }]);
  });

  it("cancel reaches the driver; process exit marks the session honestly", async () => {
    const id = await setup();
    emit({ type: "turn-started", sessionId: id });
    await useNekoSessionStore.getState().cancelTurn();
    expect(driver.cancelled).toBe(1);

    emit({ type: "process-exited", sessionId: id, code: 1 });
    expect(session(id).status).toBe("exited");
    expect(session(id).statusDetail).toContain("mã lỗi 1");
    // Driver gone → a further prompt is a no-op, not a crash.
    await useNekoSessionStore.getState().sendPrompt("còn đó không?");
    expect(driver.prompts).toEqual([]);
  });

  it("closeSession disposes the driver and clears active state", async () => {
    const id = await setup();
    await useNekoSessionStore.getState().closeSession(id);
    expect(driver.disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
    expect(useNekoSessionStore.getState().activeSessionId).toBeNull();
  });

  it("marks the session as error when the driver factory fails", async () => {
    _setDriverFactoryForTests(async () => {
      throw new Error("spawn thất bại");
    });
    const id = await useNekoSessionStore.getState().createSession(AGENT);
    expect(session(id).status).toBe("error");
    expect(session(id).statusDetail).toContain("spawn thất bại");
    vi.restoreAllMocks();
  });
});
