/**
 * T501–T503 — local persistence: debounced writes, restart-surviving
 * restore, respawn-on-prompt for restored sessions, delete.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";

const storage = new Map<string, unknown>();
let failTranscriptWrites = false;
let transcriptWritesBeforeFailure: number | null = null;
let strictWriteGate: Promise<void> | null = null;
let strictBlockedKey: string | null = null;
let gateOnlyWhenFailurePending = false;
let notifyStrictGateEntered: (() => void) | null = null;

async function saveToMemory(store: string, key: string, value: unknown): Promise<void> {
  if (key.startsWith("session:")) {
    if (failTranscriptWrites) throw new Error("disk unavailable");
    if (transcriptWritesBeforeFailure !== null) {
      if (transcriptWritesBeforeFailure === 0) throw new Error("commit disk failure");
      transcriptWritesBeforeFailure -= 1;
    }
  }
  storage.set(`${store}:${key}`, JSON.parse(JSON.stringify(value)));
}

async function saveStrictToMemory(store: string, key: string, value: unknown): Promise<void> {
  const shouldWait =
    strictWriteGate &&
    (!strictBlockedKey || key === strictBlockedKey) &&
    (!gateOnlyWhenFailurePending || transcriptWritesBeforeFailure === 0);
  if (shouldWait) {
    notifyStrictGateEntered?.();
    await strictWriteGate;
  }
  await saveToMemory(store, key, value);
}

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, dflt: unknown) => {
    const hit = storage.get(`${store}:${key}`);
    return hit === undefined ? dflt : JSON.parse(JSON.stringify(hit));
  }),
  saveStore: vi.fn(saveToMemory),
  saveStoreStrict: vi.fn(saveStrictToMemory),
  deleteStore: vi.fn(async (store: string, key: string) => {
    storage.delete(`${store}:${key}`);
  }),
  clearStore: vi.fn(async () => {}),
}));

import { useNekoAgentStore } from "@/neko-chill/stores/neko-agent-store";
import {
  useNekoSessionStore,
  _setDriverFactoryForTests,
  _clearLiveDriversForTests,
} from "@/neko-chill/stores/neko-session-store";
import { persistSessionNow } from "@/neko-chill/persistence";
import { saveStoreStrict } from "@/lib/storage";

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
  promptSawDurableEvents: unknown[][] = [];
  configErrorForValue: string | boolean | null = null;
  failStorageOnConfigError = false;
  configChanges: Array<{ optionId: string; value: string | boolean }> = [];
  disposed = 0;
  constructor(
    readonly sessionId: string,
    readonly emit: (event: DriverEvent) => void,
  ) {}
  async start(): Promise<void> {}
  async prompt(text: string): Promise<void> {
    const snapshot = storage.get(`neko-chill-sessions.json:session:${this.sessionId}`) as
      | { events?: unknown[] }
      | undefined;
    this.promptSawDurableEvents.push(snapshot?.events ?? []);
    this.prompts.push(text);
  }
  async cancel(): Promise<void> {}
  async resolvePermission(_: PermissionDecision): Promise<void> {}
  async setConfigOption(optionId: string, value: string | boolean): Promise<void> {
    if (value === this.configErrorForValue) {
      if (this.failStorageOnConfigError) failTranscriptWrites = true;
      throw new Error("compensation rejected");
    }
    this.configChanges.push({ optionId, value });
  }
  async dispose(): Promise<void> { this.disposed += 1; }
}

let spawned: FakeDriver[] = [];

function useFakeFactory(): void {
  _setDriverFactoryForTests(async (agent, sessionId, _launch, onEvent) => {
    const driver = new FakeDriver(sessionId, onEvent);
    spawned.push(driver);
    return driver;
  });
}

const emit = (event: DriverEvent) => useNekoSessionStore.getState().handleEvent(event);

async function flushDebounce(): Promise<void> {
  await vi.advanceTimersByTimeAsync(500);
}

describe("neko-chill persistence", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    storage.clear();
    failTranscriptWrites = false;
    transcriptWritesBeforeFailure = null;
    strictWriteGate = null;
    strictBlockedKey = null;
    gateOnlyWhenFailurePending = false;
    notifyStrictGateEntered = null;
    spawned = [];
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    useNekoAgentStore.setState({ agents: [AGENT], isLoading: false });
    useFakeFactory();
  });
  afterEach(() => {
    vi.useRealTimers();
    _setDriverFactoryForTests(undefined);
  });

  it("persists a streamed session and restores it after a restart", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("Xin chào neko");
    emit({ type: "turn-started", sessionId: id });
    emit({ type: "answer-delta", sessionId: id, text: "Meo! " });
    emit({ type: "answer-delta", sessionId: id, text: "Chào bạn." });
    emit({ type: "turn-finished", sessionId: id, stopReason: "end_turn" });
    await flushDebounce();

    // Simulate app restart: fresh in-memory state, same storage.
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored).toBeDefined();
    expect(restored.status).toBe("exited");
    expect(restored.title).toBe("Xin chào neko");
    expect(restored.workspace).toEqual(WORKSPACE);
    expect(restored.messages).toHaveLength(2);
    expect(restored.messages[0]).toMatchObject({ role: "user", text: "Xin chào neko" });
    expect(restored.messages[1].blocks?.[0]).toMatchObject({
      type: "answer",
      content: "Meo! Chào bạn.",
    });
    expect(storage.get("neko-chill-sessions.json:index")).toMatchObject([
      { v: 2, workspace: WORKSPACE },
    ]);
    const persisted = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      v: number;
      events: Array<{ seq: number; data: { type: string; text?: string } }>;
    };
    expect(persisted.v).toBe(2);
    expect(spawned[0].promptSawDurableEvents[0]).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({ type: "model-input", text: "Xin chào neko" }),
        }),
      ]),
    );
    expect(persisted.events.map((event) => event.seq)).toEqual(
      persisted.events.map((_, eventIndex) => eventIndex + 1),
    );
  });

  it("fails closed and never dispatches when the model-input log cannot persist", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().sendPrompt("không được gửi");

    expect(spawned[0].prompts).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id].statusDetail).toContain(
      "chưa gửi cho agent",
    );
  });

  it("propagates immediate background persistence failures to its caller", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    failTranscriptWrites = true;

    await expect(persistSessionNow(useNekoSessionStore.getState().sessions[id]))
      .rejects.toThrow("disk unavailable");
  });

  it("locks the composer while a prompt waits for durable storage", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });

    const first = useNekoSessionStore.getState().sendPrompt("lượt đầu");
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("dispatching");
    const second = useNekoSessionStore.getState().sendPrompt("không được chen ngang");

    expect(useNekoSessionStore.getState().sessions[id].messages).toEqual([
      expect.objectContaining({ role: "user", text: "lượt đầu" }),
    ]);
    release();
    await Promise.all([first, second]);

    expect(spawned[0].prompts).toEqual(["lượt đầu"]);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("idle");
  });

  it("cancels initial runtime creation when the session closes during persistence", async () => {
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });

    const creating = useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const id = useNekoSessionStore.getState().activeSessionId!;
    const closing = useNekoSessionStore.getState().closeSession(id);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("stopping");

    release();
    await Promise.all([creating, closing]);

    expect(spawned).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("exited");
  });

  it("cancels initial runtime creation when the session is deleted during persistence", async () => {
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });

    const creating = useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const id = useNekoSessionStore.getState().activeSessionId!;
    const deleting = useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("stopping");

    release();
    await Promise.all([creating, deleting]);

    expect(spawned).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("does not block one session behind another session's transcript write", async () => {
    const firstId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const secondId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${firstId}`;

    useNekoSessionStore.getState().setActiveSession(firstId);
    const blocked = useNekoSessionStore.getState().sendPrompt("phiên đang chờ đĩa");
    expect(useNekoSessionStore.getState().sessions[firstId].status).toBe("dispatching");

    useNekoSessionStore.getState().setActiveSession(secondId);
    await useNekoSessionStore.getState().sendPrompt("phiên độc lập");
    expect(spawned.find((driver) => driver.sessionId === secondId)?.prompts)
      .toEqual(["phiên độc lập"]);

    release();
    await blocked;
    expect(spawned.find((driver) => driver.sessionId === firstId)?.prompts)
      .toEqual(["phiên đang chờ đĩa"]);
  });

  it("holds the config lock until the committed event is durably persisted", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "session-controls",
      sessionId: id,
      controls: [{
        id: "mode",
        label: "Chế độ",
        category: "mode",
        kind: "select",
        currentValue: "default",
        choices: [
          { value: "default", label: "Default" },
          { value: "plan", label: "Plan" },
        ],
      }],
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    gateOnlyWhenFailurePending = true;
    transcriptWritesBeforeFailure = 1;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const changing = useNekoSessionStore.getState().setConfigOption("mode", "plan");
    await gateEntered;

    expect(useNekoSessionStore.getState().sessions[id].pendingControlId).toBe("mode");
    emit({
      type: "session-controls",
      sessionId: id,
      controls: [{
        id: "mode",
        label: "Chế độ",
        category: "mode",
        kind: "select",
        currentValue: "plan",
        choices: [
          { value: "default", label: "Default" },
          { value: "plan", label: "Plan" },
        ],
      }],
    });
    expect(useNekoSessionStore.getState().sessions[id].pendingControlId).toBe("mode");
    await useNekoSessionStore.getState().sendPrompt("không được chen vào commit");
    await useNekoSessionStore.getState().setConfigOption("mode", "default");
    expect(spawned[0].prompts).toEqual([]);
    expect(spawned[0].configChanges).toEqual([{ optionId: "mode", value: "plan" }]);

    transcriptWritesBeforeFailure = null;
    release();
    await changing;

    expect(useNekoSessionStore.getState().sessions[id].pendingControlId).toBeNull();
  });

  it("uses strict persistence for a post-dispatch rollback outcome", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
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
    vi.mocked(saveStoreStrict).mockClear();
    spawned[0].configErrorForValue = "preview";
    spawned[0].failStorageOnConfigError = true;

    await useNekoSessionStore.getState().setConfigOption("model", "preview");

    expect(useNekoSessionStore.getState().sessions[id].status).toBe("exited");
    expect(useNekoSessionStore.getState().sessions[id].runtime).toBeNull();
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id].statusDetail).toContain(
      "runtime đã được thu hồi",
    );
    const strictTranscriptWrites = vi.mocked(saveStoreStrict).mock.calls.filter(
      ([, key]) => key === `session:${id}`,
    );
    expect(strictTranscriptWrites).toHaveLength(2);
  });

  it("surfaces rollback-failed when commit persistence and compensation both fail", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
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
    spawned[0].configErrorForValue = "stable";
    // requested persists; committed write fails; compensation back to stable fails.
    transcriptWritesBeforeFailure = 1;

    await useNekoSessionStore.getState().setConfigOption("model", "preview");

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("exited");
    expect(session.runtime).toBeNull();
    expect(spawned[0].disposed).toBe(1);
    expect(session.events[session.events.length - 1].data).toMatchObject({
      type: "control-change",
      phase: "rollback-failed",
    });
  });

  it("does not compensate a failed commit through a detached provider", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
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
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    gateOnlyWhenFailurePending = true;
    transcriptWritesBeforeFailure = 1;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const changing = useNekoSessionStore.getState().setConfigOption("model", "preview");
    await gateEntered;
    const closing = useNekoSessionStore.getState().closeSession(id);
    await vi.waitFor(() => expect(spawned[0].disposed).toBe(1));
    release();
    await Promise.all([changing, closing]);

    expect(spawned[0].configChanges).toEqual([{ optionId: "model", value: "preview" }]);
    expect(useNekoSessionStore.getState().sessions[id].events.at(-1)?.data)
      .toMatchObject({ type: "control-change", phase: "rollback-failed" });
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("exited");

    transcriptWritesBeforeFailure = null;
    await useNekoSessionStore.getState().sendPrompt("phiên đã đóng vẫn tiếp tục");
    expect(spawned).toHaveLength(2);
    expect(spawned[1].prompts).toEqual(["phiên đã đóng vẫn tiếp tục"]);
  });

  it("hydrates a v1 index as a visible legacy session without losing transcript", async () => {
    storage.set("neko-chill-sessions.json:index", [
      {
        id: "legacy-1",
        agentId: "neko",
        agentName: "Neko Core",
        title: "Phiên cũ",
        createdAt: 100,
        updatedAt: 200,
      },
    ]);
    storage.set("neko-chill-sessions.json:session:legacy-1", {
      v: 1,
      messages: [{ id: "m1", role: "user", text: "không được mất" }],
    });

    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().sessions["legacy-1"]).toMatchObject({
      workspace: null,
      launchProfile: null,
      controls: [],
      commands: [],
      pendingControlId: null,
      messages: [{ text: "không được mất" }],
    });
    const migrated = storage.get("neko-chill-sessions.json:session:legacy-1") as {
      v: number;
      events: Array<{ data: { type: string; source?: string; text?: string } }>;
    };
    expect(migrated.v).toBe(2);
    expect(migrated.events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({
            type: "model-input",
            source: "legacy-migration",
            text: "không được mất",
          }),
        }),
      ]),
    );
  });

  it("hydrate is idempotent and never overwrites live sessions", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("bản sống");
    await flushDebounce();

    await useNekoSessionStore.getState().hydrate();
    await useNekoSessionStore.getState().hydrate();
    const session = useNekoSessionStore.getState().sessions[id];
    // Live session (idle, with driver) must not be downgraded to exited.
    expect(session.status).toBe("idle");
    expect(Object.keys(useNekoSessionStore.getState().sessions)).toHaveLength(1);
  });

  it("rebuilds effective controls from committed log events", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
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
    await useNekoSessionStore.getState().setConfigOption("model", "preview");

    // Simulate an index write lagging behind the log-bearing transcript key.
    const index = storage.get("neko-chill-sessions.json:index") as Array<{
      id: string;
      controls: Array<{ id: string; currentValue: string }>;
    }>;
    index.find((entry) => entry.id === id)!.controls[0].currentValue = "stable";
    storage.set("neko-chill-sessions.json:index", index);

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().sessions[id].controls[0].currentValue).toBe("preview");
  });

  it("does not replay configuration commits from an older provider epoch", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
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
    await useNekoSessionStore.getState().setConfigOption("model", "preview");
    await useNekoSessionStore.getState().closeSession(id);

    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("runtime mới");
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
    await flushDebounce();

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().sessions[id].controls[0].currentValue).toBe("stable");
  });

  it("a restored session respawns a fresh agent process on the next prompt", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("lần đầu");
    await flushDebounce();
    expect(spawned).toHaveLength(1);

    // Restart: state + live drivers cleared, hydrate → driverless session.
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    useNekoSessionStore.getState().setActiveSession(id);

    await useNekoSessionStore.getState().sendPrompt("còn nhớ mình không?");
    // Fresh process (spec US3-2), prompt delivered, session live again.
    expect(spawned).toHaveLength(2);
    expect(spawned[1].prompts).toEqual(["còn nhớ mình không?"]);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("idle");
  });

  it("deleteSession removes state, index, and transcript", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("sẽ bị xoá");
    await flushDebounce();
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(1);

    await useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
  });

  it("closeSession keeps the transcript and persists immediately", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("giữ lại nhé");
    await useNekoSessionStore.getState().closeSession(id);

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("exited");
    expect(session.messages).toHaveLength(1);
    // persistSessionNow does not wait for the debounce window.
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(1);
  });
});
