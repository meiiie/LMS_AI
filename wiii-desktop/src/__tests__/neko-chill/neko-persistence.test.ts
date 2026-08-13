/**
 * T501–T503 — local persistence: debounced writes, restart-surviving
 * restore, respawn-on-prompt for restored sessions, delete.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";

const storage = new Map<string, unknown>();

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, dflt: unknown) => {
    const hit = storage.get(`${store}:${key}`);
    return hit === undefined ? dflt : JSON.parse(JSON.stringify(hit));
  }),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, JSON.parse(JSON.stringify(value)));
  }),
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
  constructor(
    readonly sessionId: string,
    readonly emit: (event: DriverEvent) => void,
  ) {}
  async start(): Promise<void> {}
  async prompt(text: string): Promise<void> {
    this.prompts.push(text);
  }
  async cancel(): Promise<void> {}
  async resolvePermission(_: PermissionDecision): Promise<void> {}
  async dispose(): Promise<void> {}
}

let spawned: FakeDriver[] = [];

function useFakeFactory(): void {
  _setDriverFactoryForTests(async (agent, sessionId, onEvent) => {
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
    const id = await useNekoSessionStore.getState().createSession(AGENT);
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
    expect(restored.messages).toHaveLength(2);
    expect(restored.messages[0]).toMatchObject({ role: "user", text: "Xin chào neko" });
    expect(restored.messages[1].blocks?.[0]).toMatchObject({
      type: "answer",
      content: "Meo! Chào bạn.",
    });
  });

  it("hydrate is idempotent and never overwrites live sessions", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT);
    await useNekoSessionStore.getState().sendPrompt("bản sống");
    await flushDebounce();

    await useNekoSessionStore.getState().hydrate();
    await useNekoSessionStore.getState().hydrate();
    const session = useNekoSessionStore.getState().sessions[id];
    // Live session (idle, with driver) must not be downgraded to exited.
    expect(session.status).toBe("idle");
    expect(Object.keys(useNekoSessionStore.getState().sessions)).toHaveLength(1);
  });

  it("a restored session respawns a fresh agent process on the next prompt", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT);
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
    const id = await useNekoSessionStore.getState().createSession(AGENT);
    await useNekoSessionStore.getState().sendPrompt("sẽ bị xoá");
    await flushDebounce();
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(1);

    await useNekoSessionStore.getState().deleteSession(id);
    expect(useNekoSessionStore.getState().sessions[id]).toBeUndefined();
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(0);
    expect(storage.has(`neko-chill-sessions.json:session:${id}`)).toBe(false);
  });

  it("closeSession keeps the transcript and persists immediately", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT);
    await useNekoSessionStore.getState().sendPrompt("giữ lại nhé");
    await useNekoSessionStore.getState().closeSession(id);

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("exited");
    expect(session.messages).toHaveLength(1);
    // persistSessionNow does not wait for the debounce window.
    expect(storage.get("neko-chill-sessions.json:index")).toHaveLength(1);
  });
});
