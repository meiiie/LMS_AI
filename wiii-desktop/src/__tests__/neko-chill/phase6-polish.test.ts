/**
 * Phase 6 (T601/T602) — idle reap + honest error surfaces, including a
 * replay of the REAL Gemini CLI error-path fixture (invalid API key →
 * JSON-RPC error response → error event + turn-finished "error").
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import { AcpDriver } from "@/neko-chill/drivers/acp/driver";
import type { Driver, DriverEvent, PermissionDecision } from "@/neko-chill/drivers/types";
import type { DetectedAgent } from "@/neko-chill/stores/neko-agent-store";

const storage = new Map<string, unknown>();
vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (_s: string, _k: string, dflt: unknown) => dflt),
  loadStoreStrict: vi.fn(async (_s: string, _k: string, dflt: unknown) => dflt),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
  saveStoreStrict: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
  deleteStore: vi.fn(async () => {}),
  deleteStoreStrict: vi.fn(async () => {}),
  clearStore: vi.fn(async () => {}),
}));

import {
  useNekoSessionStore,
  _setDriverFactoryForTests,
  _clearLiveDriversForTests,
  disposeAllNekoRuntimes,
  sweepIdleSessions,
} from "@/neko-chill/stores/neko-session-store";

type Frame = Record<string, any>;

class FakeTransport implements AcpTransport {
  sent: Frame[] = [];
  private lineHandlers: Array<(line: string) => void> = [];
  private exitHandlers: Array<(code: number | null) => void> = [];
  async send(line: string): Promise<void> {
    this.sent.push(JSON.parse(line));
  }
  onLine(h: (line: string) => void): void {
    this.lineHandlers.push(h);
  }
  onExit(h: (code: number | null) => void): void {
    this.exitHandlers.push(h);
  }
  async kill(): Promise<void> {}
  inject(frame: Frame): void {
    for (const h of this.lineHandlers) h(JSON.stringify(frame));
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("T602 — honest error surfaces", () => {
  it("replays the real Gemini CLI error fixture into error + turn-finished(error)", async () => {
    const fixture: Array<{ dir: string; frame?: Frame }> = readFileSync(
      join(__dirname, "fixtures", "gemini-acp-session.ndjson"),
      "utf8",
    )
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    const responses = fixture
      .filter((r) => r.dir === "a2c" && r.frame && r.frame.id !== undefined && !r.frame.method)
      .map((r) => r.frame!);
    const notifications = fixture
      .filter((r) => r.dir === "a2c" && r.frame?.method === "session/update")
      .map((r) => r.frame!);
    // [initialize ok, session/new ok, prompt ERROR] — recorded from gemini 0.38.1
    expect(responses).toHaveLength(3);
    expect(responses[2].error?.message).toContain("API key");

    const events: DriverEvent[] = [];
    const transport = new FakeTransport();
    const driver = new AcpDriver({
      sessionId: "s-gem",
      cwd: "C:/tmp",
      transport,
      onEvent: (e) => events.push(e),
    });
    const starting = driver.start();
    await tick();
    transport.inject({ ...responses[0], id: transport.sent[0].id });
    await tick();
    transport.inject({ ...responses[1], id: transport.sent[1].id });
    await starting;

    const prompting = driver.prompt("chào gemini");
    await tick();
    for (const n of notifications) transport.inject(n);
    transport.inject({ ...responses[2], id: transport.sent[2].id });
    await prompting;

    const errors = events.filter((e) => e.type === "error");
    expect(errors).toHaveLength(1);
    if (errors[0].type === "error") {
      expect(errors[0].message).toContain("API key");
      expect(errors[0].fatal).toBe(false);
    }
    expect(events.at(-1)).toEqual({
      type: "turn-finished",
      sessionId: "s-gem",
      stopReason: "error",
    });
  });

  it("rejects a protocol version the client does not speak", async () => {
    const events: DriverEvent[] = [];
    const transport = new FakeTransport();
    const driver = new AcpDriver({
      sessionId: "s-v",
      cwd: "C:/tmp",
      transport,
      onEvent: (e) => events.push(e),
    });
    const starting = driver.start();
    await tick();
    transport.inject({
      jsonrpc: "2.0",
      id: transport.sent[0].id,
      result: { protocolVersion: 2 },
    });
    await expect(starting).rejects.toThrow(/ACP v2/);
  });
});

describe("T601 — idle reap", () => {
const AGENT: DetectedAgent = {
    id: "neko",
    name: "Neko Core",
    version: "0.24.0",
    found: true,
    supportsProfiles: true,
};
const WORKSPACE = { path: "C:/tmp/project", name: "project" };

  class FakeDriver implements Driver {
    readonly kind = "acp" as const;
    readonly runtime: Driver["runtime"];
    disposed = 0;
    failDispose = false;
    failDisposeWithoutReason = false;
    failDisposeWithoutStringifier = false;
    constructor(readonly sessionId: string, executionId: string) {
      this.runtime = {
        capabilities: ["prompt", "cancel", "permission-resolution", "session-config"],
        contextContinuity: "process",
        workspaceIsolation: "advisory",
        providerExtensions: {
          nativeAgentSessionId: `native/${executionId}`,
          nativeRunId: `run/${executionId}`,
        },
      };
    }
    async start(): Promise<void> {}
    async prompt(): Promise<void> {}
    async cancel(): Promise<void> {}
    async resolvePermission(_: PermissionDecision): Promise<void> {}
    async setConfigOption(): Promise<void> {}
    async dispose(): Promise<void> {
      this.disposed += 1;
      if (this.failDisposeWithoutReason) return Promise.reject(undefined);
      if (this.failDisposeWithoutStringifier) return Promise.reject(Object.create(null));
      if (this.failDispose) throw new Error("native cancellation outcome lost");
    }
  }

  let driver: FakeDriver;
  let createdDrivers: number;

  beforeEach(() => {
    storage.clear();
    useNekoSessionStore.setState({
      sessions: {},
      activeSessionId: null,
      hydrated: false,
      hydrating: false,
      hydrationError: null,
    });
    _clearLiveDriversForTests();
    createdDrivers = 0;
    _setDriverFactoryForTests(async (_agent, sessionId, launch) => {
      createdDrivers += 1;
      driver = new FakeDriver(sessionId, launch.executionId ?? sessionId);
      return driver;
    });
  });
  afterEach(() => _setDriverFactoryForTests(undefined));

  it("reaps an idle session past the threshold; keeps fresh and busy ones", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    // Fresh session: not reaped.
    await sweepIdleSessions();
    expect(driver.disposed).toBe(0);

    // Push activity 31 minutes into the past.
    useNekoSessionStore.setState((state) => {
      state.sessions[id].lastActivityAt = Date.now() - 31 * 60 * 1000;
    });
    await sweepIdleSessions();
    expect(driver.disposed).toBe(1);
    const reaped = useNekoSessionStore.getState().sessions[id];
    expect(reaped.status).toBe("exited");
    expect(reaped.statusDetail).toContain("30 phút");

    // Streaming session with stale timestamp: never reaped.
    const id2 = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    useNekoSessionStore.getState().handleEvent({ type: "turn-started", sessionId: id2 });
    useNekoSessionStore.setState((state) => {
      state.sessions[id2].lastActivityAt = Date.now() - 31 * 60 * 1000;
    });
    await sweepIdleSessions();
    expect(driver.disposed).toBe(0);
    expect(useNekoSessionStore.getState().sessions[id2].status).toBe("streaming");
  });

  it("mode exit disposes the runtime once and records the owner teardown", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);

    await disposeAllNekoRuntimes();
    await disposeAllNekoRuntimes();

    expect(driver.disposed).toBe(1);
    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.runtime).toBeNull();
    expect(session.status).toBe("exited");
    expect(session.events[session.events.length - 1]?.data).toMatchObject({
      type: "runtime-detached",
      reason: "mode-exit",
    });
  });

  it("keeps an idle-reap cleanup failure uncertain and blocks respawn", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    driver.failDisposeWithoutReason = true;
    useNekoSessionStore.setState((state) => {
      state.sessions[id].lastActivityAt = Date.now() - 31 * 60 * 1000;
    });

    await sweepIdleSessions();

    const reaped = useNekoSessionStore.getState().sessions[id];
    expect(reaped.status).toBe("error");
    expect(reaped.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-cleanup-uncertain",
      providerId: "neko",
      reason: "Unknown native runtime cleanup failure.",
    });
    expect(reaped.events.some((event) => (
      event.data.type === "runtime-detached" && event.data.reason === "idle"
    ))).toBe(false);

    useNekoSessionStore.setState((state) => {
      state.sessions[id].status = "exited";
    });
    useNekoSessionStore.getState().setActiveSession(id);
    await useNekoSessionStore.getState().sendPrompt("do not respawn after uncertain reap");
    expect(createdDrivers).toBe(1);
  });

  it("keeps a mode-exit cleanup failure uncertain instead of recording exit", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    driver.failDisposeWithoutStringifier = true;

    await disposeAllNekoRuntimes();

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("error");
    expect(session.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-cleanup-uncertain",
      providerId: "neko",
      reason: "Unknown native runtime cleanup failure.",
    });
    expect(session.events.some((event) => (
      event.data.type === "runtime-detached" && event.data.reason === "mode-exit"
    ))).toBe(false);
  });

  it("treats a runtime missing from the registry as unobserved cleanup", async () => {
    const id = await useNekoSessionStore.getState().createSession(AGENT, WORKSPACE);
    _clearLiveDriversForTests();

    await disposeAllNekoRuntimes();

    const session = useNekoSessionStore.getState().sessions[id];
    expect(session.status).toBe("error");
    expect(session.events.at(-1)?.data).toMatchObject({
      type: "native-runtime-cleanup-uncertain",
      providerId: "neko",
      reason: "Runtime không thuộc registry khi rời Neko Chill; cleanup không được quan sát.",
    });
    expect(session.events.some((event) => (
      event.data.type === "runtime-detached" && event.data.reason === "mode-exit"
    ))).toBe(false);
  });
});
