/**
 * T501–T503 — local persistence: debounced writes, restart-surviving
 * restore, respawn-on-prompt for restored sessions, delete.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";

const storage = new Map<string, unknown>();
const writeOrder: string[] = [];
let failTranscriptWrites = false;
let failIndexWrites = false;
let failCatalogWrites = false;
let failTranscriptReads = false;
let failCatalogReads = false;
let failTranscriptDeletes = false;
let transcriptDeleteAttempts = 0;
let firstTranscriptDeleteGate: Promise<void> | null = null;
let notifyFirstTranscriptDeleteEntered: (() => void) | null = null;
let failFirstTranscriptDeleteAfterGate = false;
let indexWriteGate: Promise<void> | null = null;
let notifyIndexWriteEntered: (() => void) | null = null;
let indexWriteAttempts = 0;
let transcriptWritesBeforeFailure: number | null = null;
let strictWriteGate: Promise<void> | null = null;
let strictBlockedKey: string | null = null;
let gateOnlyWhenFailurePending = false;
let notifyStrictGateEntered: (() => void) | null = null;
let driverDisposeGate: Promise<void> | null = null;
let notifyDriverDisposeEntered: (() => void) | null = null;
let driverConfigGate: Promise<void> | null = null;
let notifyDriverConfigEntered: (() => void) | null = null;
let driverPromptGate: Promise<void> | null = null;

async function saveToMemory(store: string, key: string, value: unknown): Promise<void> {
  if (key === "session-ids" && failCatalogWrites) {
    throw new Error("catalog unavailable");
  }
  if (key === "index") {
    indexWriteAttempts += 1;
    notifyIndexWriteEntered?.();
    if (indexWriteGate) await indexWriteGate;
    if (failIndexWrites) throw new Error("index unavailable");
  }
  if (store === "neko-chill-sessions.json" && key.startsWith("session:")) {
    if (failTranscriptWrites) throw new Error("disk unavailable");
    if (transcriptWritesBeforeFailure !== null) {
      if (transcriptWritesBeforeFailure === 0) throw new Error("commit disk failure");
      transcriptWritesBeforeFailure -= 1;
    }
  }
  writeOrder.push(`${store}:${key}`);
  storage.set(`${store}:${key}`, JSON.parse(JSON.stringify(value)));
}

async function saveStrictToMemory(store: string, key: string, value: unknown): Promise<void> {
  const shouldWait =
    store === "neko-chill-sessions.json" &&
    strictWriteGate &&
    (!strictBlockedKey || key === strictBlockedKey) &&
    (!gateOnlyWhenFailurePending || transcriptWritesBeforeFailure === 0);
  if (shouldWait) {
    notifyStrictGateEntered?.();
    await strictWriteGate;
  }
  await saveToMemory(store, key, value);
}

async function loadFromMemory(store: string, key: string, dflt: unknown): Promise<unknown> {
  const hit = storage.get(`${store}:${key}`);
  return hit === undefined ? dflt : JSON.parse(JSON.stringify(hit));
}

async function loadStrictFromMemory(
  store: string,
  key: string,
  dflt: unknown,
): Promise<unknown> {
  if (key === "session-ids" && failCatalogReads) throw new Error("catalog read unavailable");
  if (store === "neko-chill-sessions.json" && key.startsWith("session:") && failTranscriptReads) {
    throw new Error("transcript read unavailable");
  }
  return loadFromMemory(store, key, dflt);
}

async function deleteStrictFromMemory(store: string, key: string): Promise<void> {
  if (store === "neko-chill-sessions.json" && key.startsWith("session:")) {
    transcriptDeleteAttempts += 1;
    if (transcriptDeleteAttempts === 1 && firstTranscriptDeleteGate) {
      notifyFirstTranscriptDeleteEntered?.();
      await firstTranscriptDeleteGate;
      if (failFirstTranscriptDeleteAfterGate) {
        throw new Error("first transcript delete unavailable");
      }
    }
    if (failTranscriptDeletes) throw new Error("transcript delete unavailable");
  }
  storage.delete(`${store}:${key}`);
}

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(loadFromMemory),
  loadStoreStrict: vi.fn(loadStrictFromMemory),
  saveStore: vi.fn(saveToMemory),
  saveStoreStrict: vi.fn(saveStrictToMemory),
  deleteStore: vi.fn(async (store: string, key: string) => {
    storage.delete(`${store}:${key}`);
  }),
  deleteStoreStrict: vi.fn(deleteStrictFromMemory),
  clearStore: vi.fn(async () => {}),
}));

import { useNekoAgentStore } from "@/neko-chill/stores/neko-agent-store";
import {
  useNekoSessionStore,
  _setDriverFactoryForTests,
  _setNativeControlReaderForTests,
  _clearLiveDriversForTests,
  disposeAllNekoRuntimes,
  sweepIdleSessions,
} from "@/neko-chill/stores/neko-session-store";
import {
  deletePersistedSession,
  loadSessionSnapshot,
  persistSessionNow,
} from "@/neko-chill/persistence";
import { saveStoreStrict } from "@/lib/storage";
import { useKnowledgeConnectionStore } from "@/workbench/knowledge";

const AGENT: DetectedAgent = {
  id: "neko",
  name: "Neko Core",
  version: "0.24.0",
  found: true,
  availability: "available",
  supportsProfiles: true,
};
const WORKSPACE = { path: "C:/tmp/project", name: "project" };
const nativeControl = {
  listSessions: vi.fn(),
  readEvents: vi.fn(),
  unresolvedStartSessionIds: vi.fn(),
  reconcilableStartSessionIds: vi.fn(),
  cancelUnresolvedStarts: vi.fn(),
};

class FakeDriver implements Driver {
  readonly kind = "acp" as const;
  readonly backendSessionId: string;
  readonly runtime: Driver["runtime"] = {
    capabilities: ["prompt", "cancel", "permission-resolution", "session-config"],
    contextContinuity: "process",
    workspaceIsolation: "advisory",
  };
  prompts: string[] = [];
  promptSawDurableEvents: unknown[][] = [];
  promptError = false;
  cancelError = false;
  permissionError = false;
  configErrorForValue: string | boolean | null = null;
  failStorageOnConfigError = false;
  configChanges: Array<{ optionId: string; value: string | boolean }> = [];
  decisions: PermissionDecision[] = [];
  cancelled = 0;
  disposed = 0;
  failDispose = false;
  constructor(
    readonly sessionId: string,
    readonly emit: (event: DriverEvent) => void,
  ) {
    this.backendSessionId = `backend-${sessionId}`;
  }
  async start(): Promise<void> {}
  async prompt(text: string): Promise<void> {
    const snapshot = storage.get(`neko-chill-sessions.json:session:${this.sessionId}`) as
      | { events?: unknown[] }
      | undefined;
    this.promptSawDurableEvents.push(snapshot?.events ?? []);
    this.prompts.push(text);
    if (driverPromptGate) await driverPromptGate;
    if (this.promptError) throw new Error("provider prompt rejected");
  }
  async cancel(): Promise<void> {
    this.cancelled += 1;
    if (this.cancelError) throw new Error("provider cancel rejected");
  }
  async resolvePermission(decision: PermissionDecision): Promise<void> {
    this.decisions.push(decision);
    if (this.permissionError) throw new Error("provider permission rejected");
  }
  async setConfigOption(optionId: string, value: string | boolean): Promise<void> {
    notifyDriverConfigEntered?.();
    if (driverConfigGate) await driverConfigGate;
    if (value === this.configErrorForValue) {
      if (this.failStorageOnConfigError) failTranscriptWrites = true;
      throw new Error("compensation rejected");
    }
    this.configChanges.push({ optionId, value });
  }
  async dispose(): Promise<void> {
    this.disposed += 1;
    notifyDriverDisposeEntered?.();
    if (driverDisposeGate) await driverDisposeGate;
    if (this.failDispose) throw new Error("process kill failed");
  }
}

let spawned: FakeDriver[] = [];
let launches: Array<{ executionId?: string; backendSessionId?: string | null }> = [];

function useFakeFactory(): void {
  _setDriverFactoryForTests(async (agent, sessionId, launch, onEvent) => {
    launches.push(launch);
    const driver = new FakeDriver(sessionId, onEvent);
    driver.runtime.providerExtensions = {
      nativeAgentSessionId: `native/${launch.executionId ?? sessionId}`,
      nativeRunId: `legacy-local/run/${launch.executionId ?? sessionId}`,
    };
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
    writeOrder.length = 0;
    failTranscriptWrites = false;
    failIndexWrites = false;
    failCatalogWrites = false;
    failTranscriptReads = false;
    failCatalogReads = false;
    failTranscriptDeletes = false;
    transcriptDeleteAttempts = 0;
    firstTranscriptDeleteGate = null;
    notifyFirstTranscriptDeleteEntered = null;
    failFirstTranscriptDeleteAfterGate = false;
    indexWriteGate = null;
    notifyIndexWriteEntered = null;
    indexWriteAttempts = 0;
    transcriptWritesBeforeFailure = null;
    strictWriteGate = null;
    strictBlockedKey = null;
    gateOnlyWhenFailurePending = false;
    notifyStrictGateEntered = null;
    driverDisposeGate = null;
    notifyDriverDisposeEntered = null;
    driverConfigGate = null;
    notifyDriverConfigEntered = null;
    driverPromptGate = null;
    spawned = [];
    launches = [];
    nativeControl.listSessions.mockReset();
    nativeControl.readEvents.mockReset();
    nativeControl.unresolvedStartSessionIds.mockReset();
    nativeControl.reconcilableStartSessionIds.mockReset();
    nativeControl.cancelUnresolvedStarts.mockReset();
    nativeControl.listSessions.mockResolvedValue([]);
    nativeControl.readEvents.mockImplementation(async (streamId: string, afterSeq = 0) => ({
      streamId,
      events: [],
      nextAfterSeq: afterSeq,
      hasMore: false,
    }));
    nativeControl.unresolvedStartSessionIds.mockReturnValue([]);
    nativeControl.reconcilableStartSessionIds.mockResolvedValue([]);
    nativeControl.cancelUnresolvedStarts.mockResolvedValue(0);
    _setNativeControlReaderForTests(() => nativeControl);
    useNekoSessionStore.setState({
      sessions: {},
      activeSessionId: null,
      hydrated: false,
      hydrating: false,
      hydrationError: null,
    });
    useNekoAgentStore.setState({ agents: [AGENT], isLoading: false });
    useKnowledgeConnectionStore.setState({
      status: "disconnected",
      error: null,
    });
    useFakeFactory();
  });
  afterEach(() => {
    vi.useRealTimers();
    _setDriverFactoryForTests(undefined);
    _setNativeControlReaderForTests(undefined);
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
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored).toBeDefined();
    expect(restored.status).toBe("exited");
    expect(restored.title).toBe("Xin chào neko");
    expect(restored.workspace).toEqual(WORKSPACE);
    expect(restored.backendSessionId).toBe(`backend-${id}`);
    expect(restored.messages).toHaveLength(2);
    expect(restored.messages[0]).toMatchObject({ role: "user", text: "Xin chào neko",
    });
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
          data: expect.objectContaining({ type: "model-input", text: "Xin chào neko",
          }),
        }),
      ]),
    );
    expect(persisted.events.map((event) => event.seq)).toEqual(
      persisted.events.map((_, eventIndex) => eventIndex + 1),
    );
  });

  it("persists native lifecycle facts before the compatible transcript", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    writeOrder.length = 0;

    await persistSessionNow(useNekoSessionStore.getState().sessions[id]);

    expect(writeOrder.filter((key) => key.endsWith(`:session:${id}`))).toEqual([
      `neko-chill-native-runtime.json:session:${id}`,
      `neko-chill-sessions.json:session:${id}`,
    ]);
  });

  it("recovers a native-first partial write by advancing the event high-water mark", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await persistSessionNow(useNekoSessionStore.getState().sessions[id]);
    const transcriptKey = `neko-chill-sessions.json:session:${id}`;
    const nativeKey = `neko-chill-native-runtime.json:session:${id}`;
    const transcript = storage.get(transcriptKey) as {
      eventHighWaterMark: number;
      messages: unknown[];
    };
    const nativeSeq = transcript.eventHighWaterMark + 1;
    storage.set(nativeKey, {
      v: 1,
      events: [{
        v: 1,
        eventId: "native-after-transcript",
        seq: nativeSeq,
        at: Date.now(),
        visibility: "runtime",
        data: {
          type: "native-runtime-cleanup-uncertain",
          agentSessionId: "native-session-1",
          runId: "run-1",
          providerId: "neko",
          reason: "renderer interrupted after native commit",
        },
      }],
    });

    const restored = await loadSessionSnapshot(id);

    expect(restored.messages).toEqual(transcript.messages);
    expect(restored.eventHighWaterMark).toBe(nativeSeq);
    expect(restored.events.at(-1)).toEqual(expect.objectContaining({ seq: nativeSeq }));
  });

  it("reconciles native journal state and replay before enabling a restored session", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("mutation đang chạy");
    await flushDebounce();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();

    const runId = "legacy-local/run/runtime-lost-response";
    nativeControl.listSessions.mockResolvedValue([{
      agentSessionId: "native-session-1",
      taskId: `legacy-local/task/${id}`,
      runId,
      environmentId: "legacy-local/environment/runtime-lost-response",
      providerId: "neko",
      providerVersion: "0.25.0",
      workspacePath: WORKSPACE.path,
      state: "unknown_outcome",
      operationPhase: "unknown_outcome",
      continuity: "unknown_outcome",
      pid: null,
      createdAt: "2026-08-23T00:00:00.000Z",
      updatedAt: "2026-08-23T00:01:00.000Z",
    }]);
    const replayEvents = [
      {
        v: 1,
        eventId: "native-event-1",
        streamId: runId,
        seq: 1,
        at: "2026-08-23T00:00:00.000Z",
        type: "session.created",
        runId,
        agentSessionId: "native-session-1",
        payload: { providerId: "neko" },
      },
      {
        v: 1,
        eventId: "native-event-2",
        streamId: runId,
        seq: 2,
        at: "2026-08-23T00:01:00.000Z",
        type: "run.state_changed",
        runId,
        agentSessionId: "native-session-1",
        payload: { state: "unknown_outcome" },
      },
    ];
    nativeControl.readEvents.mockImplementation(async (_streamId: string, afterSeq = 0) => ({
      streamId: runId,
      events: afterSeq === 0 ? replayEvents : [],
      nextAfterSeq: afterSeq === 0 ? 2 : afterSeq,
      hasMore: false,
    }));

    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(useNekoSessionStore.getState().hydrated).toBe(true);
    expect(restored.status).toBe("error");
    expect(restored.statusDetail).toContain("kết quả chưa xác định");
    expect(nativeControl.readEvents).toHaveBeenCalledWith(runId, 0, 500);
    expect(restored.events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "native-runtime-reconciled",
          agentSessionId: "native-session-1",
          replayedFromSeq: 0,
          replayedThroughSeq: 2,
          replayedEventCount: 2,
        }),
      }),
    ]));
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toEqual(
      expect.objectContaining({
        events: expect.not.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              type: "native-runtime-reconciled",
              replayedThroughSeq: 2,
            }),
          }),
        ]),
      }),
    );
    expect(storage.get(`neko-chill-native-runtime.json:session:${id}`)).toEqual(
      expect.objectContaining({
        v: 1,
        events: expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              type: "native-runtime-reconciled",
              replayedThroughSeq: 2,
            }),
          }),
        ]),
      }),
    );
    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().closeSession(id);
    await useNekoSessionStore.getState().sendPrompt("không được chạy trùng");
    expect(spawned).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("error");

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    await useNekoSessionStore.getState().hydrate();
    expect(nativeControl.readEvents).toHaveBeenLastCalledWith(runId, 2, 500);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "native-runtime-reconciled",
    )).toHaveLength(1);
  });

  it("re-reads native state after replay so a concurrent terminal transition unlocks the session", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await flushDebounce();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();

    const runId = "legacy-local/run/runtime-finishes-during-replay";
    const running = {
      agentSessionId: "native-session-race",
      taskId: `legacy-local/task/${id}`,
      runId,
      environmentId: "legacy-local/environment/runtime-finishes-during-replay",
      providerId: "neko",
      providerVersion: "0.25.0",
      workspacePath: WORKSPACE.path,
      state: "running",
      operationPhase: "committed",
      continuity: "active",
      pid: 123,
      createdAt: "2026-08-23T00:00:00.000Z",
      updatedAt: "2026-08-23T00:01:00.000Z",
    };
    const completed = {
      ...running,
      state: "completed",
      operationPhase: "completed",
      pid: null,
      updatedAt: "2026-08-23T00:02:00.000Z",
    };
    nativeControl.listSessions
      .mockResolvedValueOnce([running])
      .mockResolvedValueOnce([completed]);
    nativeControl.readEvents.mockResolvedValue({
      streamId: runId,
      events: [{
        v: 1,
        eventId: "native-event-terminal",
        streamId: runId,
        seq: 3,
        at: completed.updatedAt,
        type: "run.state_changed",
        runId,
        agentSessionId: completed.agentSessionId,
        payload: { state: "completed" },
      }],
      nextAfterSeq: 3,
      hasMore: false,
    });

    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored.status).toBe("exited");
    expect(restored.statusDetail).toContain("đã hoàn tất");
    expect(nativeControl.listSessions).toHaveBeenCalledTimes(2);
    expect(restored.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-reconciled",
      state: "completed",
      operationPhase: "completed",
      replayedThroughSeq: 3,
    });
  });

  it("reconciles every native run so a newer terminal run cannot hide an older uncertain process", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("tạo lịch sử native");
    await flushDebounce();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();

    const completed = {
      agentSessionId: "native-session-newer",
      taskId: `legacy-local/task/${id}`,
      runId: "legacy-local/run/newer-terminal",
      environmentId: "legacy-local/environment/newer-terminal",
      providerId: "neko",
      providerVersion: "0.25.0",
      workspacePath: WORKSPACE.path,
      state: "completed",
      operationPhase: "completed",
      continuity: "active",
      pid: null,
      createdAt: "2026-08-23T00:02:00.000Z",
      updatedAt: "2026-08-23T00:03:00.000Z",
    };
    const uncertain = {
      ...completed,
      agentSessionId: "native-session-older",
      runId: "legacy-local/run/older-uncertain",
      environmentId: "legacy-local/environment/older-uncertain",
      state: "unknown_outcome",
      operationPhase: "unknown_outcome",
      continuity: "unknown_outcome",
      createdAt: "2026-08-23T00:00:00.000Z",
      updatedAt: "2026-08-23T00:01:00.000Z",
    };
    const natives = [completed, uncertain];
    nativeControl.listSessions.mockImplementation(async (runId?: string) => (
      runId ? natives.filter((candidate) => candidate.runId === runId) : natives
    ));

    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored.status).toBe("error");
    expect(restored.statusDetail).toContain("kết quả chưa xác định");
    expect(restored.events.filter(
      (event) => event.data.type === "native-runtime-reconciled",
    )).toHaveLength(2);
    expect(nativeControl.readEvents).toHaveBeenCalledWith(completed.runId, 0, 500);
    expect(nativeControl.readEvents).toHaveBeenCalledWith(uncertain.runId, 0, 500);

    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("không được chạy process thứ ba");
    expect(spawned).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("error");
  });

  it("retires a stale native checkpoint after its terminal projection is pruned", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("tạo checkpoint đang chạy");
    await flushDebounce();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();

    const terminal = {
      agentSessionId: "native-session-pruned-later",
      taskId: `legacy-local/task/${id}`,
      runId: "legacy-local/run/pruned-later",
      environmentId: "legacy-local/environment/pruned-later",
      providerId: "neko",
      providerVersion: "0.25.0",
      workspacePath: WORKSPACE.path,
      state: "completed",
      operationPhase: "completed",
      continuity: "active",
      pid: null,
      createdAt: "2026-05-01T00:00:00.000Z",
      updatedAt: "2026-05-01T00:01:00.000Z",
    };
    nativeControl.listSessions.mockImplementation(async (runId?: string) => (
      !runId || runId === terminal.runId ? [terminal] : []
    ));

    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("exited");

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    nativeControl.listSessions.mockResolvedValue([]);
    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-retired",
      agentSessionId: terminal.agentSessionId,
      runId: terminal.runId,
      reason: "projection-pruned",
    });
    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("được phép tạo runtime mới");
    expect(spawned).toHaveLength(2);
  });

  it("keeps an absent unknown-outcome checkpoint blocking respawn", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await flushDebounce();
    const unknown = {
      agentSessionId: "native-session-unknown-retained",
      taskId: `legacy-local/task/${id}`,
      runId: "legacy-local/run/unknown-retained",
      environmentId: "legacy-local/environment/unknown-retained",
      providerId: "neko",
      providerVersion: "0.25.0",
      workspacePath: WORKSPACE.path,
      state: "unknown_outcome",
      operationPhase: "unknown_outcome",
      continuity: "unknown_outcome",
      pid: null,
      createdAt: "2026-05-01T00:00:00.000Z",
      updatedAt: "2026-05-01T00:01:00.000Z",
    };
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    nativeControl.listSessions.mockImplementation(async (runId?: string) => (
      !runId || runId === unknown.runId ? [unknown] : []
    ));
    await useNekoSessionStore.getState().hydrate();

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    nativeControl.listSessions.mockResolvedValue([]);
    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored.events.some((event) => (
      event.data.type === "native-runtime-retired" &&
      event.data.agentSessionId === unknown.agentSessionId
    ))).toBe(false);
    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("không được respawn unknown");
    expect(spawned).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("error");
  });

  it("fails hydration closed when the native journal cannot be reconciled", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await flushDebounce();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    nativeControl.listSessions.mockRejectedValue(new Error("native journal unavailable"));

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState()).toMatchObject({
      sessions: {},
      hydrated: false,
      hydrating: false,
      hydrationError: "native journal unavailable",
    });
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toBeDefined();
  });

  it("does not migrate or overwrite a snapshot after a transient read failure", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await useNekoSessionStore.getState().sendPrompt("dữ liệu phải giữ nguyên");
    const storedBefore = JSON.parse(JSON.stringify(
      storage.get(`neko-chill-sessions.json:session:${id}`),
    ));
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    _clearLiveDriversForTests();
    failTranscriptReads = true;

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().hydrated).toBe(false);
    expect(useNekoSessionStore.getState().hydrating).toBe(false);
    expect(useNekoSessionStore.getState().hydrationError).toContain("transcript read unavailable");
    expect(useNekoSessionStore.getState().sessions).toEqual({});
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toEqual(storedBefore);

    failTranscriptReads = false;
    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().hydrationError).toBeNull();
    expect(useNekoSessionStore.getState().sessions[id].messages).toEqual([
      expect.objectContaining({ text: "dữ liệu phải giữ nguyên" }),
    ]);
  });

  it("fails closed and never dispatches when the model-input log cannot persist", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const originalTitle = useNekoSessionStore.getState().sessions[id].title;
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().sendPrompt("không được gửi");

    expect(spawned[0].prompts).toEqual([]);
    const failed = useNekoSessionStore.getState().sessions[id];
    expect(failed.messages).toEqual([]);
    expect(failed.title).toBe(originalTitle);
    expect(failed.events.some(
      (event) => event.data.type === "model-input" && event.data.text === "không được gửi",
    )).toBe(false);
    expect(failed.eventHighWaterMark).toBe(3);
    expect(failed.statusDetail).toContain(
      "chưa gửi cho agent",
    );

    failTranscriptWrites = false;
    await useNekoSessionStore.getState().sendPrompt("thử lại");
    expect(spawned[0].prompts).toEqual(["thử lại"]);
    expect(useNekoSessionStore.getState().sessions[id].messages).toEqual([
      expect.objectContaining({ text: "thử lại" }),
    ]);
    const retryEvent = useNekoSessionStore
      .getState()
      .sessions[id].events.find((event) => event.data.type === "model-input" && event.data.text === "thử lại");
    expect(retryEvent?.seq).toBe(4);
    expect(
      (
        storage.get(`neko-chill-sessions.json:session:${id}`) as {
          eventHighWaterMark: number;
        }
      ).eventHighWaterMark,
    ).toBe(5);

    useNekoSessionStore.setState({
      sessions: {},
      activeSessionId: null,
      hydrated: false,
    });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().sessions[id].eventHighWaterMark).toBe(5);
  });

  it("persists model-visible knowledge before dispatch and replays it without retrieval", async () => {
    const retrieve = vi.fn(async () => ({
      contextId: "context-1",
      query: "quy tắc 15",
      renderedContext: "[1] Bằng chứng quy tắc 15",
      sources: [{
        sourceId: "chunk-1",
        title: "COLREG",
        documentId: "colreg.pdf",
        pageNumber: 15,
        content: "Bằng chứng quy tắc 15",
        score: 0.9,
      }],
    }));
    useKnowledgeConnectionStore.setState({ status: "ready", retrieve });
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    await useNekoSessionStore.getState().sendPrompt("quy tắc 15");

    expect(retrieve).toHaveBeenCalledTimes(1);
    expect(spawned[0].prompts[0]).toContain("<wiii_knowledge>");
    expect(spawned[0].promptSawDurableEvents[0]).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "knowledge-context",
          contextId: "context-1",
          delivery: "staged",
        }),
      }),
    ]));
    expect(useNekoSessionStore.getState().sessions[id].events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "dispatch-invoked",
          action: "knowledge",
        }),
      }),
    ]));

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    expect(retrieve).toHaveBeenCalledTimes(1);
    expect(useNekoSessionStore.getState().sessions[id].events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({ type: "knowledge-context", contextId: "context-1" }),
      }),
    ]));
  });

  it("never exposes retrieved context when its durability barrier fails", async () => {
    const retrieve = vi.fn(async () => ({
      contextId: "context-failed",
      query: "private evidence",
      renderedContext: "[1] private evidence",
      sources: [],
    }));
    useKnowledgeConnectionStore.setState({ status: "ready", retrieve });
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().sendPrompt("private evidence");

    expect(retrieve).toHaveBeenCalledTimes(1);
    expect(spawned[0].prompts).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id].events.some(
      (event) => event.data.type === "knowledge-context",
    )).toBe(false);
  });

  it("recovers a self-contained session when the index cache write fails", async () => {
    failIndexWrites = true;

    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    await vi.waitFor(() => expect(indexWriteAttempts).toBeGreaterThan(0));
    expect(spawned).toHaveLength(1);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);
    expect(storage.get("neko-chill-sessions.json:index")).toBeUndefined();
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    _clearLiveDriversForTests();
    failIndexWrites = false;

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      workspace: WORKSPACE,
      agentId: AGENT.id,
      status: "exited",
    });
    expect(useNekoSessionStore.getState().sessions[id].events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({
            type: "session-context",
            workspacePath: WORKSPACE.path,
          }),
        }),
      ]),
    );
  });

  it("does not replace the catalog when its authoritative read fails", async () => {
    const firstId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    failCatalogReads = true;

    const secondId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    expect(storage.get("neko-chill-sessions.json:session-ids")).toEqual([firstId]);
    expect(spawned.map((driver) => driver.sessionId)).toEqual([firstId]);
    expect(useNekoSessionStore.getState().sessions[secondId]).toMatchObject({
      status: "error",
      runtime: null,
    });
  });

  it.each([
    null,
    { existing: ["session-a"] },
  ])("rejects malformed authoritative catalog value %# instead of replacing it", async (
    malformedCatalog,
  ) => {
    storage.set("neko-chill-sessions.json:session-ids", malformedCatalog);

    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    expect(storage.get("neko-chill-sessions.json:session-ids")).toEqual(malformedCatalog);
    expect(spawned).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      runtime: null,
    });
  });

  it("fails hydration on a malformed snapshot without migrating or overwriting it", async () => {
    const entry = {
      v: 2,
      id: "malformed-snapshot",
      agentId: AGENT.id,
      agentName: AGENT.name,
      title: "Dữ liệu cần phục hồi",
      createdAt: 100,
      updatedAt: 200,
      workspace: WORKSPACE,
    };
    const malformedSnapshot = { v: 2, messages: { not: "an array" }, entry };
    storage.set("neko-chill-sessions.json:session-ids", [entry.id]);
    storage.set("neko-chill-sessions.json:index", [entry]);
    storage.set(`neko-chill-sessions.json:session:${entry.id}`, malformedSnapshot);

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState()).toMatchObject({
      hydrated: false,
      hydrating: false,
      sessions: {},
    });
    expect(useNekoSessionStore.getState().hydrationError).toContain("schema không hợp lệ");
    expect(storage.get(`neko-chill-sessions.json:session:${entry.id}`))
      .toEqual(malformedSnapshot);
  });

  it.each([
    { field: "controls", value: [null] },
    { field: "commands", value: [null] },
  ])("rejects malformed nested snapshot $field without stranding hydration", async ({
    field,
    value,
  }) => {
    const id = `malformed-${field}`;
    const entry = {
      v: 2,
      id,
      agentId: AGENT.id,
      agentName: AGENT.name,
      title: "Metadata hỏng",
      createdAt: 100,
      updatedAt: 200,
      workspace: WORKSPACE,
      [field]: value,
    };
    const malformedSnapshot = {
      v: 2,
      messages: [],
      events: [{
        v: 1,
        seq: 1,
        at: 100,
        visibility: "model",
        data: {
          type: "session-context",
          source: "created",
          agentId: AGENT.id,
          workspacePath: WORKSPACE.path,
          launchProfileId: null,
        },
      }],
      entry,
    };
    storage.set("neko-chill-sessions.json:session-ids", [id]);
    storage.set("neko-chill-sessions.json:index", [entry]);
    storage.set(`neko-chill-sessions.json:session:${id}`, malformedSnapshot);

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState()).toMatchObject({
      hydrated: false,
      hydrating: false,
      sessions: {},
    });
    expect(useNekoSessionStore.getState().hydrationError).toContain("schema không hợp lệ");
    expect(storage.get(`neko-chill-sessions.json:session:${id}`))
      .toEqual(malformedSnapshot);
  });

  it("does not block another session or new catalog entry behind index-cache I/O", async () => {
    const firstId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const secondId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(
      (storage.get("neko-chill-sessions.json:index") as unknown[] | undefined)?.length,
    ).toBe(2));
    const initialIndexAttempts = indexWriteAttempts;
    let releaseIndex!: () => void;
    indexWriteGate = new Promise<void>((resolve) => { releaseIndex = resolve; });
    const indexEntered = new Promise<void>((resolve) => { notifyIndexWriteEntered = resolve; });

    useNekoSessionStore.getState().setActiveSession(firstId);
    await useNekoSessionStore.getState().sendPrompt("phiên một");
    await indexEntered;
    useNekoSessionStore.getState().setActiveSession(secondId);
    await useNekoSessionStore.getState().sendPrompt("phiên hai");
    const thirdId = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    expect(spawned.find((driver) => driver.sessionId === secondId)?.prompts)
      .toEqual(["phiên hai"]);
    expect(spawned.some((driver) => driver.sessionId === thirdId)).toBe(true);
    releaseIndex();
    indexWriteGate = null;
    await vi.waitFor(() => expect(indexWriteAttempts).toBeGreaterThanOrEqual(
      initialIndexAttempts + 3,
    ));
  });

  it("removes a permission decision whose durability barrier fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-retry",
        title: "Write(config.json)",
        options: [
          { optionId: "reject", label: "Từ chối", kind: "reject_once" },
          { optionId: "allow", label: "Cho phép", kind: "allow_once" },
        ],
      },
    });
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().resolvePermission("reject");

    const failed = useNekoSessionStore.getState().sessions[id];
    expect(failed.pendingPermission?.requestId).toBe("permission-retry");
    expect(failed.resolvingPermissionId).toBeNull();
    expect(failed.events.filter((event) => event.data.type === "permission-decision"))
      .toHaveLength(0);
    expect(spawned[0].decisions).toEqual([]);

    failTranscriptWrites = false;
    await useNekoSessionStore.getState().resolvePermission("allow");
    expect(spawned[0].decisions).toEqual([
      { requestId: "permission-retry", optionId: "allow" },
    ]);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "permission-decision",
    )).toHaveLength(1);
  });

  it("blocks cancel while a permission decision is crossing durability", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-cancel-race",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    failTranscriptWrites = true;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const resolving = useNekoSessionStore.getState().resolvePermission("allow");
    await gateEntered;
    await useNekoSessionStore.getState().cancelTurn();

    expect(spawned[0].cancelled).toBe(0);
    expect(
      useNekoSessionStore.getState().sessions[id].events.filter((event) => event.data.type === "runtime-command"),
    ).toHaveLength(0);

    release();
    await resolving;
    expect(spawned[0].decisions).toEqual([]);
    expect(
      useNekoSessionStore.getState().sessions[id].events.filter((event) => event.data.type === "permission-decision"),
    ).toHaveLength(0);
  });

  it("blocks permission decisions while cancellation is crossing durability", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "cancel-permission-race",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    failTranscriptWrites = true;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const cancelling = useNekoSessionStore.getState().cancelTurn();
    await gateEntered;
    await useNekoSessionStore.getState().resolvePermission("allow");

    expect(spawned[0].decisions).toEqual([]);
    expect(
      useNekoSessionStore.getState().sessions[id].events.filter(
        (event) => event.data.type === "permission-decision",
      ),
    ).toHaveLength(0);

    release();
    await cancelling;
    expect(spawned[0].cancelled).toBe(0);
    expect(
      useNekoSessionStore.getState().sessions[id].events.filter((event) => event.data.type === "runtime-command"),
    ).toHaveLength(0);
  });

  it("dispatches only permission when its successful barrier owns the cross-action lock", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-wins",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const resolving = useNekoSessionStore.getState().resolvePermission("allow");
    await gateEntered;
    await useNekoSessionStore.getState().cancelTurn();

    expect(useNekoSessionStore.getState().sessions[id].resolvingPermissionId).toBe("permission-wins");
    expect(spawned[0].cancelled).toBe(0);
    release();
    await resolving;

    expect(spawned[0].decisions).toEqual([{ requestId: "permission-wins", optionId: "allow" }]);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "permission-decision",
    )).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "runtime-command",
    )).toHaveLength(0);
  });

  it("dispatches only cancel when its successful barrier owns the cross-action lock", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "cancel-wins",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const cancelling = useNekoSessionStore.getState().cancelTurn();
    await gateEntered;
    await useNekoSessionStore.getState().resolvePermission("allow");

    expect(useNekoSessionStore.getState().sessions[id].cancelPending).toBe(true);
    expect(spawned[0].decisions).toEqual([]);
    release();
    await cancelling;

    expect(spawned[0].cancelled).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "runtime-command",
    )).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "permission-decision",
    )).toHaveLength(0);
  });

  it("removes a cancel command whose durability barrier fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    failTranscriptWrites = true;

    const first = useNekoSessionStore.getState().cancelTurn();
    const second = useNekoSessionStore.getState().cancelTurn();
    await Promise.all([first, second]);

    expect(spawned[0].cancelled).toBe(0);
    expect(useNekoSessionStore.getState().sessions[id].events.filter(
      (event) => event.data.type === "runtime-command",
    )).toHaveLength(0);
    expect(useNekoSessionStore.getState().sessions[id].cancelPending).toBe(false);
    const durable = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string } }>;
    };
    expect(durable.events.filter((event) => event.data.type === "runtime-command"))
      .toHaveLength(0);

    failTranscriptWrites = false;
    await useNekoSessionStore.getState().cancelTurn();
    expect(spawned[0].cancelled).toBe(1);
  });

  it("rolls back an undispatched fact without renumbering later events", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    failTranscriptWrites = true;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const cancelling = useNekoSessionStore.getState().cancelTurn();
    await gateEntered;
    emit({ type: "process-exited", sessionId: id, code: 0, signal: null });
    release();
    await cancelling;

    expect(useNekoSessionStore.getState().sessions[id].events.map((event) => event.seq))
      .toEqual([1, 2, 4]);

    strictWriteGate = null;
    failTranscriptWrites = false;
    await useNekoSessionStore.getState().sendPrompt("tiếp tục sau rollback");
    expect(useNekoSessionStore.getState().sessions[id].events.map((event) => event.seq))
      .toEqual([1, 2, 4, 5, 6, 7]);

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().sessions[id].events.map((event) => event.seq))
      .toEqual([1, 2, 4, 5, 6, 7]);
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

  it("waits for a prompt durability barrier before closing its provider", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const sending = useNekoSessionStore.getState().sendPrompt("ghi rồi mới đóng");
    await gateEntered;
    const closing = useNekoSessionStore.getState().closeSession(id);
    await Promise.resolve();

    expect(spawned[0].disposed).toBe(0);
    expect(useNekoSessionStore.getState().sessions[id].closePending).toBe(true);

    release();
    await Promise.all([sending, closing]);
    expect(spawned[0].prompts).toEqual(["ghi rồi mới đóng"]);
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "exited",
      closePending: false,
    });
  });

  it("waits for prompt durability before mode-exit teardown", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const sending = useNekoSessionStore.getState().sendPrompt("ghi rồi mới rời mode");
    await gateEntered;
    const exiting = disposeAllNekoRuntimes();
    let reentrySettled = false;
    const reentry = useNekoSessionStore
      .getState()
      .createSession(AGENT, { path: "C:/tmp/reentered", name: "reentered" })
      .finally(() => {
        reentrySettled = true;
      });
    await Promise.resolve();

    expect(spawned[0].disposed).toBe(0);
    expect(reentrySettled).toBe(false);
    expect(spawned).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "stopping",
      closePending: true,
    });

    release();
    await Promise.all([sending, exiting]);
    const reenteredId = await reentry;
    expect(spawned[0].prompts).toEqual(["ghi rồi mới rời mode"]);
    expect(spawned[0].disposed).toBe(1);
    expect(spawned).toHaveLength(2);
    expect(useNekoSessionStore.getState().sessions[reenteredId].status).toBe("idle");
    const session = useNekoSessionStore.getState().sessions[id];
    expect(session).toMatchObject({ status: "exited", closePending: false });
    expect(session.events.at(-1)?.data).toMatchObject({
      type: "runtime-detached",
      reason: "mode-exit",
    });
  });

  it("fails mode exit closed when a retained native start cannot be cancelled", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    nativeControl.unresolvedStartSessionIds.mockReturnValue([id]);
    nativeControl.cancelUnresolvedStarts.mockRejectedValueOnce(
      new Error("retained start cancellation unavailable"),
    );

    await disposeAllNekoRuntimes();

    expect(nativeControl.cancelUnresolvedStarts).toHaveBeenCalledWith(id);
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      status: "error",
      closePending: false,
    });
    expect(useNekoSessionStore.getState().sessions[id].statusDetail).toContain(
      "báo lỗi khi thu hồi tài nguyên",
    );
  });

  it("cancels a native start retained while mode-exit joins runtime preparation", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    nativeControl.unresolvedStartSessionIds.mockReturnValue([]);
    nativeControl.reconcilableStartSessionIds.mockResolvedValue([id]);

    await disposeAllNekoRuntimes();

    expect(nativeControl.unresolvedStartSessionIds).toHaveBeenCalledOnce();
    expect(nativeControl.reconcilableStartSessionIds).toHaveBeenCalledOnce();
    expect(nativeControl.cancelUnresolvedStarts).toHaveBeenCalledWith(id);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      status: "exited",
      closePending: false,
    });
  });

  it("cancels a durable Codex bootstrap found only after renderer reload", async () => {
    const bootstrapId = "codex-account-bootstrap-after-reload";
    nativeControl.unresolvedStartSessionIds.mockReturnValue([]);
    nativeControl.reconcilableStartSessionIds.mockResolvedValue([bootstrapId]);

    await disposeAllNekoRuntimes();

    expect(nativeControl.cancelUnresolvedStarts).toHaveBeenCalledWith(bootstrapId);
  });

  it("removes a staged prompt when the provider exits before invocation", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const sending = useNekoSessionStore.getState().sendPrompt("provider chưa thấy");
    await gateEntered;
    emit({ type: "process-exited", sessionId: id, code: 1 });
    release();
    await sending;

    expect(spawned[0].prompts).toEqual([]);
    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("exited");
    expect(session.messages).toEqual([]);
    expect(session.events.filter((event) => event.data.type === "model-input")).toHaveLength(0);
    const durable = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      messages: unknown[];
      events: Array<{ data: { type: string } }>;
    };
    expect(durable.messages).toEqual([]);
    expect(durable.events.filter((event) => event.data.type === "model-input")).toHaveLength(0);
  });

  it("does not hydrate a staged prompt when its corrective write also fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = `session:${id}`;
    transcriptWritesBeforeFailure = 1;
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const sending = useNekoSessionStore.getState().sendPrompt("không được hồi sinh");
    await gateEntered;
    emit({ type: "process-exited", sessionId: id, code: 1 });
    release();
    await sending;

    const stale = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      messages: Array<{ text?: string }>;
      events: Array<{ data: { type: string; delivery?: string } }>;
    };
    expect(stale.messages).toEqual([expect.objectContaining({ text: "không được hồi sinh" })]);
    expect(stale.events).toContainEqual(expect.objectContaining({
      data: expect.objectContaining({ type: "model-input", delivery: "staged" }),
    }));

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions[id];
    expect(restored.messages).toEqual([]);
    expect(restored.statusDetail).toContain("chưa xác nhận gửi");
    expect(restored.events.some((event) => event.data.type === "model-input")).toBe(true);
  });

  it("revokes an invoked prompt when its dispatch marker cannot become durable", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    // The staged input becomes durable; the dispatch marker and terminal retry fail.
    transcriptWritesBeforeFailure = 1;
    spawned[0].promptError = true;

    await useNekoSessionStore.getState().sendPrompt("provider đã thấy nhưng marker lỗi");

    expect(spawned[0].prompts).toEqual(["provider đã thấy nhưng marker lỗi"]);
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      status: "exited",
    });
    const stale = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      messages: Array<{ text?: string }>;
      events: Array<{ data: { type: string; delivery?: string } }>;
    };
    expect(stale.events.some((event) => event.data.type === "dispatch-invoked")).toBe(false);
    expect(stale.events).toContainEqual(expect.objectContaining({
      data: expect.objectContaining({ type: "model-input", delivery: "staged" }),
    }));

    transcriptWritesBeforeFailure = null;
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().sessions[id].messages).toEqual([]);
    expect(useNekoSessionStore.getState().sessions[id].statusDetail).toContain("chưa xác nhận gửi");
  });

  it("revokes immediately when marker persistence fails during a pending prompt", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let releasePrompt!: () => void;
    driverPromptGate = new Promise<void>((resolve) => { releasePrompt = resolve; });
    transcriptWritesBeforeFailure = 1;

    const sending = useNekoSessionStore.getState().sendPrompt("turn vẫn đang chạy");
    await vi.waitFor(() => expect(spawned[0].disposed).toBe(1));
    await sending;

    expect(spawned[0].prompts).toEqual(["turn vẫn đang chạy"]);
    expect(useNekoSessionStore.getState().sessions[id].runtime).toBeNull();
    releasePrompt();
  });

  it("revokes a rejected cancellation when its dispatch marker also fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    transcriptWritesBeforeFailure = 1;
    spawned[0].cancelError = true;

    await useNekoSessionStore.getState().cancelTurn();

    expect(spawned[0].cancelled).toBe(1);
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      status: "exited",
      cancelPending: false,
    });
    const stale = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string } }>;
    };
    expect(stale.events.some((event) => event.data.type === "dispatch-invoked")).toBe(false);
  });

  it("revokes a rejected permission when its dispatch marker also fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-marker-failure",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    transcriptWritesBeforeFailure = 1;
    spawned[0].permissionError = true;

    await useNekoSessionStore.getState().resolvePermission("allow");

    expect(spawned[0].decisions).toEqual([{
      requestId: "permission-marker-failure",
      optionId: "allow",
    }]);
    expect(spawned[0].disposed).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      status: "exited",
      pendingPermission: null,
      resolvingPermissionId: null,
    });
    const stale = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string } }>;
    };
    expect(stale.events.some((event) => event.data.type === "dispatch-invoked")).toBe(false);
  });

  it("keeps a permission request retryable when invoked delivery rejects", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-retry",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    spawned[0].permissionError = true;

    await useNekoSessionStore.getState().resolvePermission("allow");

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      pendingPermission: expect.objectContaining({ requestId: "permission-retry" }),
      resolvingPermissionId: null,
      runtime: expect.objectContaining({ instanceId: expect.any(String) }),
    });
    expect(useNekoSessionStore.getState().sessions[id].statusDetail)
      .toContain("provider permission rejected");

    spawned[0].permissionError = false;
    await useNekoSessionStore.getState().resolvePermission("allow");
    expect(spawned[0].decisions).toHaveLength(2);
    expect(useNekoSessionStore.getState().sessions[id].pendingPermission).toBeNull();
  });

  it("removes a staged cancellation when the provider exits before invocation", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const cancelling = useNekoSessionStore.getState().cancelTurn();
    await gateEntered;
    emit({ type: "process-exited", sessionId: id, code: 1 });
    release();
    await cancelling;

    expect(spawned[0].cancelled).toBe(0);
    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.events.filter((event) => event.data.type === "runtime-command")).toHaveLength(0);
    const durable = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string } }>;
    };
    expect(durable.events.filter((event) => event.data.type === "runtime-command")).toHaveLength(0);
  });

  it("removes a staged permission decision when the provider exits before invocation", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    emit({
      type: "permission-request",
      sessionId: id,
      request: {
        requestId: "permission-provider-exit",
        title: "Write(config.json)",
        options: [{ optionId: "allow", label: "Cho phép", kind: "allow_once" }],
      },
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    strictBlockedKey = `session:${id}`;
    const gateEntered = new Promise<void>((resolve) => {
      notifyStrictGateEntered = resolve;
    });

    const resolving = useNekoSessionStore.getState().resolvePermission("allow");
    await gateEntered;
    emit({ type: "process-exited", sessionId: id, code: 1 });
    release();
    await resolving;

    expect(spawned[0].decisions).toEqual([]);
    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.events.filter((event) => event.data.type === "permission-decision")).toHaveLength(0);
    const durable = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string } }>;
    };
    expect(durable.events.filter((event) => event.data.type === "permission-decision")).toHaveLength(0);
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
      ([store, key]) => store === "neko-chill-sessions.json" && key === `session:${id}`,
    );
    // Requested barrier, terminal rollback, then one terminal revocation retry.
    expect(strictTranscriptWrites).toHaveLength(3);
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
    expect(useNekoSessionStore.getState().sessions[id].events.filter((event) => event.data.type === "control-change")
        .at(-1)?.data,
    )
      .toMatchObject({ type: "control-change", phase: "rollback-failed" });
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("exited");

    transcriptWritesBeforeFailure = null;
    await useNekoSessionStore.getState().sendPrompt("phiên đã đóng vẫn tiếp tục");
    expect(spawned).toHaveLength(2);
    expect(spawned[1].prompts).toEqual(["phiên đã đóng vẫn tiếp tục"]);
  });

  it("finishes config recovery when joined process-exit cleanup rejects", async () => {
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
    let releaseConfig!: () => void;
    driverConfigGate = new Promise<void>((resolve) => { releaseConfig = resolve; });
    const configEntered = new Promise<void>((resolve) => { notifyDriverConfigEntered = resolve; });
    let releaseDispose!: () => void;
    driverDisposeGate = new Promise<void>((resolve) => { releaseDispose = resolve; });
    const disposeEntered = new Promise<void>((resolve) => { notifyDriverDisposeEntered = resolve; });
    spawned[0].failDispose = true;

    const changing = useNekoSessionStore.getState().setConfigOption("model", "preview");
    await configEntered;
    emit({ type: "process-exited", sessionId: id, code: 1 });
    await disposeEntered;
    releaseConfig();
    await vi.waitFor(() => expect(spawned[0].configChanges).toEqual([
      { optionId: "model", value: "preview" },
    ]));
    await Promise.resolve();
    releaseDispose();
    await changing;

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session).toMatchObject({
      pendingControlId: null,
      runtime: null,
      status: "error",
    });
    expect(session.statusDetail).toContain("process kill failed");
    expect(session.events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "native-runtime-cleanup-uncertain",
          reason: "process kill failed",
        }),
      }),
      expect.objectContaining({
        data: expect.objectContaining({
          type: "control-change",
          phase: "rollback-failed",
        }),
      }),
    ]));
    const durable = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      events: Array<{ data: { type: string; phase?: string } }>;
    };
    expect(durable.events).toContainEqual(expect.objectContaining({
      data: expect.objectContaining({
        type: "control-change",
        phase: "rollback-failed",
      }),
    }));
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

  it("keeps a legacy session fail-closed when log migration cannot persist", async () => {
    storage.set("neko-chill-sessions.json:index", [
      {
        id: "legacy-migration-failure",
        agentId: AGENT.id,
        agentName: AGENT.name,
        title: "Phiên cũ",
        createdAt: 100,
        updatedAt: 200,
        workspace: WORKSPACE,
      },
    ]);
    storage.set("neko-chill-sessions.json:session:legacy-migration-failure", {
      v: 1,
      messages: [{ id: "legacy-message", role: "user", text: "nội dung cũ" }],
    });
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().hydrate();

    const restored = useNekoSessionStore.getState().sessions["legacy-migration-failure"];
    expect(restored.status).toBe("error");
    expect(restored.runtime).toBeNull();
    expect(restored.statusDetail).toContain("nâng cấp log phiên");
    useNekoSessionStore.getState().setActiveSession("legacy-migration-failure");
    await useNekoSessionStore.getState().sendPrompt("không được respawn");
    expect(spawned).toEqual([]);
    expect((storage.get(
      "neko-chill-sessions.json:session:legacy-migration-failure",
    ) as { v: number }).v).toBe(1);
  });

  it("keeps a migrating legacy session closed until the strict write commits", async () => {
    storage.set("neko-chill-sessions.json:index", [
      {
        id: "legacy-migration-pending",
        agentId: AGENT.id,
        agentName: AGENT.name,
        title: "Phiên cũ",
        createdAt: 100,
        updatedAt: 200,
        workspace: WORKSPACE,
      },
    ]);
    storage.set("neko-chill-sessions.json:session:legacy-migration-pending", {
      v: 1,
      messages: [],
    });
    let release!: () => void;
    strictWriteGate = new Promise<void>((resolve) => { release = resolve; });
    strictBlockedKey = "session:legacy-migration-pending";
    const gateEntered = new Promise<void>((resolve) => { notifyStrictGateEntered = resolve; });

    const hydrating = useNekoSessionStore.getState().hydrate();
    await gateEntered;
    expect(useNekoSessionStore.getState().sessions["legacy-migration-pending"].status)
      .toBe("connecting");
    useNekoSessionStore.getState().setActiveSession("legacy-migration-pending");
    await useNekoSessionStore.getState().sendPrompt("không được chen vào migration");
    expect(spawned).toEqual([]);

    release();
    await hydrating;
    expect(useNekoSessionStore.getState().sessions["legacy-migration-pending"].status)
      .toBe("exited");
  });

  it("reconciles workspace metadata from a durable context event", async () => {
    storage.set("neko-chill-sessions.json:index", [
      {
        v: 2,
        id: "context-recovery",
        agentId: AGENT.id,
        agentName: AGENT.name,
        title: "Phiên cũ",
        createdAt: 100,
        updatedAt: 200,
        workspace: null,
        launchProfile: null,
        controls: [],
        commands: [],
      },
    ]);
    storage.set("neko-chill-sessions.json:session:context-recovery", {
      v: 2,
      messages: [],
      events: [
        {
          v: 1,
          seq: 1,
          at: 200,
          visibility: "model",
          data: {
            type: "session-context",
            source: "workspace-attached",
            agentId: AGENT.id,
            workspacePath: WORKSPACE.path,
            launchProfileId: null,
          },
        },
      ],
    });

    await useNekoSessionStore.getState().hydrate();

    expect(useNekoSessionStore.getState().sessions["context-recovery"].workspace)
      .toEqual(WORKSPACE);
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
    // Exercise backward compatibility: old v2 snapshots had no embedded
    // metadata, so the committed event must repair a stale cached baseline.
    const transcript = storage.get(`neko-chill-sessions.json:session:${id}`) as {
      entry?: unknown;
    };
    delete transcript.entry;
    storage.set(`neko-chill-sessions.json:session:${id}`, transcript);

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
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

    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
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
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    useNekoSessionStore.getState().setActiveSession(id);

    await useNekoSessionStore.getState().sendPrompt("còn nhớ mình không?");
    // Fresh process (spec US3-2), prompt delivered, session live again.
    expect(spawned).toHaveLength(2);
    expect(launches[0].executionId).toEqual(expect.any(String));
    expect(launches[1].executionId).toEqual(expect.any(String));
    expect(launches[1].executionId).not.toBe(launches[0].executionId);
    expect(launches[0].backendSessionId).toBeNull();
    expect(launches[1].backendSessionId).toBe(`backend-${id}`);
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
    expect(storage.get("neko-chill-sessions.json:session-ids")).toHaveLength(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
  });

  it("fails deletion closed until a retained unresolved native start is cancelled", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await flushDebounce();
    nativeControl.cancelUnresolvedStarts.mockRejectedValueOnce(
      new Error("native cancellation unavailable"),
    );

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      deletePending: false,
    });
    expect(useNekoSessionStore.getState().sessions[id].statusDetail).toContain(
      "native cancellation unavailable",
    );
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toBeDefined();

    nativeControl.cancelUnresolvedStarts.mockResolvedValueOnce(1);
    await useNekoSessionStore.getState().deleteSession(id);
    expect(nativeControl.cancelUnresolvedStarts).toHaveBeenCalledWith(id);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("keeps a session durable when runtime cleanup fails before deletion", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    spawned[0].failDispose = true;

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      deletePending: false,
      status: "error",
    });
    expect(useNekoSessionStore.getState().sessions[id].statusDetail)
      .toContain("runtime chưa đóng sạch");
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);

    // Losing live ownership is not proof that the process stopped. The durable
    // uncertainty tombstone must survive restart and keep deletion blocked.
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      runtime: null,
      deletePending: false,
      status: "error",
    });
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);
  });

  it("rolls back an unpersisted workspace attachment so it can be retried", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    useNekoSessionStore.setState((state) => {
      state.sessions[id].workspace = null;
    });
    const attached = { path: "C:/tmp/retry-workspace", name: "retry-workspace" };
    failTranscriptWrites = true;

    await useNekoSessionStore.getState().attachWorkspace(id, attached);

    const failed = useNekoSessionStore.getState().sessions[id];
    expect(failed.workspace).toBeNull();
    expect(failed.events.some((event) =>
      event.data.type === "session-context" &&
      event.data.source === "workspace-attached" &&
      event.data.workspacePath === attached.path,
    )).toBe(false);

    failTranscriptWrites = false;
    await useNekoSessionStore.getState().attachWorkspace(id, attached);
    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      workspace: attached,
      status: "exited",
    });
  });

  it("keeps a session visible when durable deletion metadata cannot persist", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(storage.get("neko-chill-sessions.json:index"))
      .toHaveLength(1));
    failIndexWrites = true;

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      runtime: null,
    });
    expect(useNekoSessionStore.getState().sessions[id].statusDetail)
      .toContain("Không thể xóa phiên");
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);

    failIndexWrites = false;
    await useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("keeps deletion discoverable when the authoritative snapshot delete fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(storage.get("neko-chill-sessions.json:index"))
      .toHaveLength(1));
    failTranscriptDeletes = true;

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      runtime: null,
    });
    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);

    failTranscriptDeletes = false;
    await useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("serializes duplicate deletion through authoritative compensation", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(storage.get("neko-chill-sessions.json:index"))
      .toHaveLength(1));
    let releaseFirstDelete!: () => void;
    firstTranscriptDeleteGate = new Promise<void>((resolve) => {
      releaseFirstDelete = resolve;
    });
    failFirstTranscriptDeleteAfterGate = true;
    const firstDeleteEntered = new Promise<void>((resolve) => {
      notifyFirstTranscriptDeleteEntered = resolve;
    });

    const first = deletePersistedSession(id).catch(() => {});
    await firstDeleteEntered;
    const second = deletePersistedSession(id);
    await Promise.resolve();
    expect(transcriptDeleteAttempts).toBe(1);

    releaseFirstDelete();
    await Promise.all([first, second]);

    expect(transcriptDeleteAttempts).toBe(2);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toEqual([]);
  });

  it("locks duplicate deletion before a stalled runtime disposer", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let releaseDispose!: () => void;
    driverDisposeGate = new Promise<void>((resolve) => { releaseDispose = resolve; });
    const disposeEntered = new Promise<void>((resolve) => {
      notifyDriverDisposeEntered = resolve;
    });

    const first = useNekoSessionStore.getState().deleteSession(id);
    await disposeEntered;
    emit({ type: "turn-finished", sessionId: id, stopReason: "end_turn" });
    const second = useNekoSessionStore.getState().deleteSession(id);
    await Promise.resolve();

    expect(useNekoSessionStore.getState().sessions[id].deletePending).toBe(true);
    expect(transcriptDeleteAttempts).toBe(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);

    releaseDispose();
    await Promise.all([first, second]);
    expect(transcriptDeleteAttempts).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("waits for an in-flight close before deleting durable state", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let releaseDispose!: () => void;
    driverDisposeGate = new Promise<void>((resolve) => {
      releaseDispose = resolve;
    });
    const disposeEntered = new Promise<void>((resolve) => {
      notifyDriverDisposeEntered = resolve;
    });

    const closing = useNekoSessionStore.getState().closeSession(id);
    await disposeEntered;
    const deleting = useNekoSessionStore.getState().deleteSession(id);
    await Promise.resolve();

    expect(useNekoSessionStore.getState().sessions[id].deletePending).toBe(true);
    expect(transcriptDeleteAttempts).toBe(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);

    releaseDispose();
    await Promise.all([closing, deleting]);
    expect(spawned[0].disposed).toBe(1);
    expect(transcriptDeleteAttempts).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("waits for an idle-reap disposal before deleting durable state", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    let releaseDispose!: () => void;
    driverDisposeGate = new Promise<void>((resolve) => {
      releaseDispose = resolve;
    });
    const disposeEntered = new Promise<void>((resolve) => {
      notifyDriverDisposeEntered = resolve;
    });

    const reaping = sweepIdleSessions(Date.now() + 31 * 60 * 1000);
    await disposeEntered;
    const deleting = useNekoSessionStore.getState().deleteSession(id);
    await Promise.resolve();

    expect(transcriptDeleteAttempts).toBe(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(true);

    releaseDispose();
    await Promise.all([reaping, deleting]);
    expect(spawned[0].disposed).toBe(1);
    expect(transcriptDeleteAttempts).toBe(1);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
  });

  it("restores a legacy snapshot and exact index when catalog deletion fails", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(storage.get("neko-chill-sessions.json:index"))
      .toHaveLength(1));
    const legacySnapshot = {
      v: 1,
      messages: [{ id: "legacy-message", role: "user", text: "phải khôi phục" }],
    };
    storage.set(`neko-chill-sessions.json:session:${id}`, legacySnapshot);
    const indexBefore = JSON.parse(JSON.stringify(
      storage.get("neko-chill-sessions.json:index"),
    ));
    failCatalogWrites = true;

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      deletePending: false,
    });
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toEqual(legacySnapshot);
    expect(storage.get("neko-chill-sessions.json:index")).toEqual(indexBefore);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);

    failCatalogWrites = false;
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: false,
    });
    _clearLiveDriversForTests();
    await useNekoSessionStore.getState().hydrate();
    expect(useNekoSessionStore.getState().sessions[id].messages)
      .toEqual([expect.objectContaining({ text: "phải khôi phục" })]);
  });

  it("republishes discovery after catalog deletion and rollback both fail", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    await vi.waitFor(() => expect(storage.get("neko-chill-sessions.json:session-ids"))
      .toContain(id));
    failCatalogWrites = true;

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]?.status).toBe("error");
    failCatalogWrites = false;
    storage.set("neko-chill-sessions.json:session-ids", []);
    await persistSessionNow(useNekoSessionStore.getState().sessions[id]);

    expect(storage.get("neko-chill-sessions.json:session-ids")).toContain(id);
  });

  it("can delete a loaded session even when its stored snapshot is malformed", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    storage.set(`neko-chill-sessions.json:session:${id}`, { v: 2, broken: true,
    });

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
    expect(storage.get("neko-chill-sessions.json:index")).toEqual([]);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toEqual([]);
  });

  it("validates the catalog before deleting an authoritative snapshot", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const snapshotBefore = storage.get(`neko-chill-sessions.json:session:${id}`);
    const indexBefore = storage.get("neko-chill-sessions.json:index");
    storage.set("neko-chill-sessions.json:session-ids", null);

    await useNekoSessionStore.getState().deleteSession(id);

    expect(useNekoSessionStore.getState().sessions[id]).toMatchObject({
      status: "error",
      runtime: null,
    });
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toEqual(snapshotBefore);
    expect(storage.get("neko-chill-sessions.json:index")).toEqual(indexBefore);
    expect(storage.get("neko-chill-sessions.json:session-ids")).toBeNull();
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

  it("keeps an uncertain live close durable and blocks a replacement runtime", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const executionId = launches[0].executionId!;
    spawned[0].failDispose = true;

    await useNekoSessionStore.getState().closeSession(id);

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session).toMatchObject({ status: "error", runtime: null, closePending: false });
    expect(session.statusDetail).toContain("chưa thể xác nhận runtime đã dừng");
    expect(session.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-cleanup-uncertain",
      agentSessionId: `native/${executionId}`,
      runId: `legacy-local/run/${executionId}`,
      providerId: "neko",
    });
    expect(session.events.some((event) => (
      event.data.type === "runtime-detached" && event.data.reason === "close"
    ))).toBe(false);
    expect(storage.get(`neko-chill-sessions.json:session:${id}`)).toEqual(
      expect.objectContaining({
        events: expect.not.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({ type: "native-runtime-cleanup-uncertain" }),
          }),
        ]),
      }),
    );
    expect(storage.get(`neko-chill-native-runtime.json:session:${id}`)).toEqual(
      expect.objectContaining({
        events: expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({ type: "native-runtime-cleanup-uncertain" }),
          }),
        ]),
      }),
    );

    useNekoSessionStore.setState((state) => {
      state.sessions[id].status = "exited";
    });
    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("cleanup vẫn chưa xác định");
    expect(spawned).toHaveLength(1);
    expect(useNekoSessionStore.getState().sessions[id].status).toBe("error");

    spawned[0].failDispose = false;
    useNekoSessionStore.setState((state) => {
      state.sessions[id].status = "exited";
    });
    await useNekoSessionStore.getState().sendPrompt("thử lại sau khi cleanup được xác nhận");

    const recovered = useNekoSessionStore.getState().sessions[id];
    expect(spawned).toHaveLength(2);
    expect(recovered.status).toBe("idle");
    expect(recovered.events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "native-runtime-cleanup-resolved",
          agentSessionId: `native/${executionId}`,
          runId: `legacy-local/run/${executionId}`,
          providerId: "neko",
        }),
      }),
    ]));
  });

  it("lets close retry a retained cleanup and records its resolution", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    const executionId = launches[0].executionId!;
    spawned[0].failDispose = true;
    await useNekoSessionStore.getState().closeSession(id);

    spawned[0].failDispose = false;
    await useNekoSessionStore.getState().closeSession(id);

    const session = useNekoSessionStore.getState().sessions[id];
    expect(spawned[0].disposed).toBe(2);
    expect(session).toMatchObject({ status: "exited", runtime: null, closePending: false });
    expect(session.events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        data: expect.objectContaining({
          type: "native-runtime-cleanup-resolved",
          agentSessionId: `native/${executionId}`,
        }),
      }),
      expect.objectContaining({
        data: expect.objectContaining({ type: "runtime-detached", reason: "close" }),
      }),
    ]));
  });

  it("lets delete retry a retained cleanup before removing durable state", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    spawned[0].failDispose = true;
    await useNekoSessionStore.getState().closeSession(id);

    spawned[0].failDispose = false;
    await useNekoSessionStore.getState().deleteSession(id);

    expect(spawned[0].disposed).toBe(2);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
    expect(storage.has(`neko-chill-native-runtime.json:session:${id}`)).toBe(false);
  });
});
