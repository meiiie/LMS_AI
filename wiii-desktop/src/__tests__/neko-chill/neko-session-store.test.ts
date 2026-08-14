/**
 * T302 — neko-session-store: DriverEvent → ContentBlock streaming, turn
 * lifecycle, permission pass-through, cancel, process exit.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";

const storage = new Map<string, unknown>();
vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, dflt: unknown) =>
    storage.get(`${store}:${key}`) ?? dflt),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
  saveStoreStrict: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
  deleteStore: vi.fn(async (store: string, key: string) => {
    storage.delete(`${store}:${key}`);
  }),
  clearStore: vi.fn(async () => {}),
}));

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
const WORKSPACE = { path: "C:/tmp/project", name: "project" };

class FakeDriver implements Driver {
  readonly kind = "acp" as const;
  readonly runtime: Driver["runtime"] = {
    capabilities: ["prompt", "cancel", "permission-resolution", "session-config"],
    contextContinuity: "process",
    workspaceIsolation: "advisory",
  };
  prompts: string[] = [];
  cancelled = 0;
  disposed = 0;
  decisions: PermissionDecision[] = [];
  configChanges: Array<{ optionId: string; value: string | boolean }> = [];
  configError: Error | null = null;
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
  async setConfigOption(optionId: string, value: string | boolean): Promise<void> {
    if (this.configError) throw this.configError;
    this.configChanges.push({ optionId, value });
  }
  async dispose(): Promise<void> {
    this.disposed += 1;
  }
}

let driver: FakeDriver;
let launchConfig: { workspace: typeof WORKSPACE; profileId?: string } | undefined;

async function setup(): Promise<string> {
  _setDriverFactoryForTests(async (agent, sessionId, launch, onEvent) => {
    launchConfig = launch;
    driver = new FakeDriver(sessionId, onEvent);
    return driver;
  });
  return useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
}

const emit = (event: DriverEvent) => useNekoSessionStore.getState().handleEvent(event);
const session = (id: string) => useNekoSessionStore.getState().sessions[id];

describe("neko-session-store", () => {
  beforeEach(() => {
    storage.clear();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null });
    launchConfig = undefined;
    _setDriverFactoryForTests(undefined);
  });

  it("creates a session, becomes idle, and records the user prompt", async () => {
    const id = await setup();
    expect(session(id).status).toBe("idle");
    expect(useNekoSessionStore.getState().activeSessionId).toBe(id);
    expect(session(id).workspace).toEqual(WORKSPACE);
    expect(launchConfig?.workspace).toEqual(WORKSPACE);

    await useNekoSessionStore.getState().sendPrompt("Xin chào");
    expect(driver.prompts).toEqual(["Xin chào"]);
    expect(session(id).messages[0]).toMatchObject({ role: "user", text: "Xin chào" });
    expect(session(id).title).toBe("Xin chào");
  });

  it("refuses to create a session without an explicit workspace", async () => {
    await expect(
      useNekoSessionStore.getState().createSession(AGENT, undefined as never),
    ).rejects.toThrow("thư mục dự án tuyệt đối");
    await expect(
      useNekoSessionStore.getState().createSession(AGENT, {
        path: "relative/project",
        name: "project",
      }),
    ).rejects.toThrow("thư mục dự án tuyệt đối");
    expect(Object.keys(useNekoSessionStore.getState().sessions)).toHaveLength(0);
  });

  it("stores controls, commands, session info, and routes a control change", async () => {
    const id = await setup();
    emit({
      type: "session-controls",
      sessionId: id,
      controls: [
        {
          id: "mode",
          label: "Chế độ",
          category: "mode",
          kind: "select",
          currentValue: "default",
          choices: [{ value: "default", label: "Default" }, { value: "plan", label: "Plan" }],
        },
      ],
    });
    emit({
      type: "available-commands",
      sessionId: id,
      commands: [{ name: "memory show", description: "Show memory" }],
    });
    emit({
      type: "session-info",
      sessionId: id,
      title: "Tiêu đề từ agent",
      updatedAt: "2026-08-13T12:00:00.000Z",
    });

    expect(session(id)).toMatchObject({
      title: "Tiêu đề từ agent",
      controls: [{ id: "mode", currentValue: "default" }],
      commands: [{ name: "memory show" }],
    });
    expect(session(id).updatedAt).toBeGreaterThanOrEqual(
      Date.parse("2026-08-13T12:00:00.000Z"),
    );
    await useNekoSessionStore.getState().setConfigOption("mode", "plan");
    expect(driver.configChanges).toEqual([{ optionId: "mode", value: "plan" }]);
    expect(session(id).pendingControlId).toBeNull();
  });

  it("rolls a failed config transaction back to the previous effective value", async () => {
    const id = await setup();
    emit({
      type: "session-controls",
      sessionId: id,
      controls: [{
        id: "model",
        label: "Model",
        category: "model",
        kind: "select",
        currentValue: "stable",
        choices: [
          { value: "stable", label: "Stable" },
          { value: "preview", label: "Preview" },
        ],
      }],
    });
    driver.configError = new Error("provider rejected preview");

    await useNekoSessionStore.getState().setConfigOption("model", "preview");

    expect(session(id).controls[0].currentValue).toBe("stable");
    expect(session(id).pendingControlId).toBeNull();
    expect(session(id).statusDetail).toContain("provider rejected preview");
    const phases = session(id).events.flatMap((event) =>
      event.data.type === "control-change" ? [event.data.phase] : [],
    );
    expect(phases.slice(-2)).toEqual(["requested", "rolled-back"]);
  });

  it("blocks prompts until a configuration transaction finishes", async () => {
    const id = await setup();
    emit({
      type: "session-controls",
      sessionId: id,
      controls: [{
        id: "mode",
        label: "Chế độ",
        category: "mode",
        kind: "select",
        currentValue: "default",
        choices: [{ value: "default", label: "Default" }, { value: "plan", label: "Plan" }],
      }],
    });

    const changing = useNekoSessionStore.getState().setConfigOption("mode", "plan");
    expect(session(id).pendingControlId).toBe("mode");
    await useNekoSessionStore.getState().sendPrompt("không được chạy giữa giao dịch");
    await changing;

    expect(driver.prompts).toEqual([]);
    expect(driver.configChanges).toEqual([{ optionId: "mode", value: "plan" }]);
    expect(session(id).pendingControlId).toBeNull();
  });

  it("attaches a workspace to a legacy transcript and restarts on the next prompt", async () => {
    const id = await setup();
    useNekoSessionStore.setState((state) => {
      state.sessions[id].workspace = null;
      state.sessions[id].messages.push({ id: "old", role: "user", text: "old turn" });
    });

    const attached = { path: "C:/tmp/legacy", name: "legacy" };
    await useNekoSessionStore.getState().attachWorkspace(id, attached);
    expect(driver.disposed).toBe(1);
    expect(session(id)).toMatchObject({ workspace: attached, status: "exited" });
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

    const firstDecision = useNekoSessionStore.getState().resolvePermission("reject_once");
    expect(session(id).resolvingPermissionId).toBe("perm-1");
    const conflictingDecision = useNekoSessionStore.getState().resolvePermission("allow_once");
    await Promise.all([firstDecision, conflictingDecision]);
    expect(session(id).pendingPermission).toBeNull();
    expect(session(id).resolvingPermissionId).toBeNull();
    expect(driver.decisions).toEqual([{ requestId: "perm-1", optionId: "reject_once" }]);
    expect(session(id).events.filter((event) => event.data.type === "permission-decision"))
      .toHaveLength(1);
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

  it("closeSession disposes the driver but keeps the transcript (exited)", async () => {
    const id = await setup();
    await useNekoSessionStore.getState().closeSession(id);
    expect(driver.disposed).toBe(1);
    const closed = session(id);
    expect(closed.status).toBe("exited");
    expect(closed.pendingPermission).toBeNull();
  });

  it("marks the session as error when the driver factory fails", async () => {
    _setDriverFactoryForTests(async () => {
      throw new Error("spawn thất bại");
    });
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    expect(session(id).status).toBe("error");
    expect(session(id).statusDetail).toContain("spawn thất bại");
    vi.restoreAllMocks();
  });
});
