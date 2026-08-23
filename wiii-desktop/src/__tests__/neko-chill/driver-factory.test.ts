import { beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauri.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauri.listen }));

import type { Driver } from "@/neko-chill/drivers/types";
import { createDriverForAgent } from "@/neko-chill/drivers/factory";
import { RuntimeRegistry } from "@/neko-chill/runtime-manager";
import { useNekoAgentStore } from "@/neko-chill/stores/neko-agent-store";
import {
  getNekoControlClient,
  type NekoSpawnedProvider,
} from "@/neko/control-client";

const PROVIDER = {
  id: "neko",
  name: "Neko Core",
  version: "0.25.0",
  found: true,
  supportsProfiles: true,
};

describe("Neko driver factory resource ownership", () => {
  beforeEach(() => {
    tauri.invoke.mockReset();
    tauri.listen.mockReset();
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_provider_list") {
        return [
          { ...PROVIDER, name: "stale probe label" },
          {
            id: "unknown",
            name: "Unknown executable",
            version: "1.0.0",
            found: true,
            supportsProfiles: false,
          },
        ];
      }
      if (command === "neko_control_session_start") {
        return {
          agentSessionId: payload?.request.agentSessionId,
          runId: payload?.request.runId,
          provider: PROVIDER,
        };
      }
      if (command === "neko_control_session_cancel") {
        return {
          agentSessionId: payload?.request.agentSessionId,
          cancelled: true,
        };
      }
      return undefined;
    });
  });

  it("normalizes detected metadata and never receives an executable path", async () => {
    await expect(getNekoControlClient().listProviders()).resolves.toEqual([PROVIDER]);
    expect(tauri.invoke).toHaveBeenCalledWith("neko_control_provider_list");
    expect(JSON.stringify(tauri.invoke.mock.results)).not.toContain("binary");
  });

  it("propagates native authority failures instead of faking an empty session list", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    tauri.invoke.mockRejectedValueOnce(new Error("journal unavailable"));
    try {
      await expect(getNekoControlClient().listSessions()).rejects.toThrow(
        "journal unavailable",
      );
    } finally {
      Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    }
  });

  it("finishes provider discovery and exposes a retryable native error", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      value: {},
      configurable: true,
    });
    tauri.invoke.mockRejectedValueOnce("journal unavailable");
    try {
      await useNekoAgentStore.getState().detect();
      expect(useNekoAgentStore.getState()).toMatchObject({
        agents: [],
        isLoading: false,
        error: "Không thể dò agent cục bộ: journal unavailable",
      });
    } finally {
      useNekoAgentStore.setState({ agents: [], isLoading: false, error: null });
      Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    }
  });

  it("subscribes before start and performs no cleanup side effect when setup fails", async () => {
    const unlistenLine = vi.fn();
    tauri.listen
      .mockResolvedValueOnce(unlistenLine)
      .mockRejectedValueOnce(new Error("event bridge unavailable"));

    await expect(getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-1",
      workspacePath: "C:/tmp/project",
    })).rejects.toThrow("event bridge unavailable");

    expect(unlistenLine).toHaveBeenCalledOnce();
    expect(tauri.invoke).not.toHaveBeenCalledWith(
      "neko_control_session_start",
      expect.anything(),
    );
    expect(tauri.invoke).not.toHaveBeenCalledWith(
      "neko_control_session_cancel",
      expect.anything(),
    );
  });

  it("owns listener cleanup and native session cancellation idempotently", async () => {
    const unlistenLine = vi.fn();
    const unlistenExit = vi.fn();
    tauri.listen
      .mockResolvedValueOnce(unlistenLine)
      .mockResolvedValueOnce(unlistenExit);

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-1",
      workspacePath: "C:/tmp/project",
    });
    await transport.kill();
    await transport.kill();

    expect(unlistenLine).toHaveBeenCalledOnce();
    expect(unlistenExit).toHaveBeenCalledOnce();
    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    )).toHaveLength(1);
  });

  it("keeps the visible session as Task while each runtime replacement gets a fresh Run", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-1",
      clientRunId: "runtime-instance-2",
      workspacePath: "C:/tmp/project",
    });

    const start = tauri.invoke.mock.calls.find(
      ([command]) => command === "neko_control_session_start",
    );
    expect(start?.[1].request).toMatchObject({
      taskId: "legacy-local/task/session-1",
      runId: "legacy-local/run/runtime-instance-2",
      environmentId: "legacy-local/environment/runtime-instance-2",
    });
    await transport.kill();
  });

  it("retries a lost start response with the same request and session identities", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command !== "neko_control_session_start") return undefined;
      starts += 1;
      if (starts === 1) throw new Error("response bridge interrupted");
      return {
        agentSessionId: payload?.request.agentSessionId,
        runId: payload?.request.runId,
        provider: PROVIDER,
      };
    });

    const spawned = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-retry",
      workspacePath: "C:/tmp/project",
    });
    const startsCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startsCalls).toHaveLength(2);
    expect(startsCalls[0][1]).toEqual(startsCalls[1][1]);
    expect(spawned.agentSessionId).toBe(startsCalls[0][1].request.agentSessionId);
  });

  it("preserves an unresolved start identity across caller-level retries", async () => {
    tauri.listen.mockResolvedValue(vi.fn());
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command !== "neko_control_session_start") return undefined;
      starts += 1;
      if (starts <= 2) throw new Error("both IPC responses were lost");
      return {
        agentSessionId: payload?.request.agentSessionId,
        runId: payload?.request.runId,
        provider: PROVIDER,
      };
    });

    const firstRequest = {
      providerId: "neko",
      clientSessionId: "session-caller-retry",
      clientRunId: "runtime-caller-attempt-1",
      workspacePath: "C:/tmp/project",
    };
    await expect(getNekoControlClient().spawnProvider(firstRequest)).rejects.toThrow(
      "both IPC responses were lost",
    );
    const spawned = await getNekoControlClient().spawnProvider({
      ...firstRequest,
      // RuntimeRegistry creates a new instanceId for this preparation. The
      // control client must still recover the unresolved first logical start.
      clientRunId: "runtime-caller-attempt-2",
    });

    const startCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCalls).toHaveLength(3);
    expect(startCalls.map(([, payload]) => payload.request.requestId)).toEqual([
      startCalls[0][1].request.requestId,
      startCalls[0][1].request.requestId,
      startCalls[0][1].request.requestId,
    ]);
    expect(startCalls.map(([, payload]) => payload.request.agentSessionId)).toEqual([
      startCalls[0][1].request.agentSessionId,
      startCalls[0][1].request.agentSessionId,
      startCalls[0][1].request.agentSessionId,
    ]);
    expect(startCalls.map(([, payload]) => payload.request.runId)).toEqual([
      "legacy-local/run/runtime-caller-attempt-1",
      "legacy-local/run/runtime-caller-attempt-1",
      "legacy-local/run/runtime-caller-attempt-1",
    ]);
    expect(spawned.agentSessionId).toBe(startCalls[0][1].request.agentSessionId);
  });

  it("recovers a lost start through real RuntimeRegistry retries without losing transport events", async () => {
    let onLine: ((event: { payload: string }) => void) | null = null;
    let onExit: ((event: { payload: number | null }) => void) | null = null;
    const unlistenLine = vi.fn();
    const unlistenExit = vi.fn();
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/line/")) {
        onLine = handler;
        return unlistenLine;
      }
      onExit = handler;
      return unlistenExit;
    });
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command !== "neko_control_session_start") return undefined;
      starts += 1;
      if (starts === 1) onLine?.({ payload: "bootstrap-before-lost-response" });
      if (starts === 2) {
        onExit?.({ payload: 17 });
        throw new Error("both IPC responses were lost");
      }
      if (starts === 1) throw new Error("both IPC responses were lost");
      return {
        agentSessionId: payload?.request.agentSessionId,
        runId: payload?.request.runId,
        provider: PROVIDER,
      };
    });

    const registry = new RuntimeRegistry();
    const instanceIds: string[] = [];
    let recoveredTransport: NekoSpawnedProvider["transport"] | null = null;
    const replace = () => registry.replace(
      "visible-session",
      "neko",
      async (instanceId) => {
        instanceIds.push(instanceId);
        const spawned = await getNekoControlClient().spawnProvider({
          providerId: "neko",
          clientSessionId: "visible-session",
          clientRunId: instanceId,
          workspacePath: "C:/tmp/project",
        });
        recoveredTransport = spawned.transport;
        return {
          kind: "acp",
          sessionId: "visible-session",
          runtime: {
            capabilities: ["prompt", "cancel", "permission-resolution", "session-config"],
            contextContinuity: "process",
            workspaceIsolation: "advisory",
          },
          start: async () => {},
          prompt: async () => {},
          cancel: async () => {},
          resolvePermission: async () => {},
          setConfigOption: async () => {},
          dispose: async () => {},
        } satisfies Driver;
      },
    );

    await expect(replace()).rejects.toThrow("both IPC responses were lost");
    await expect(replace()).resolves.toBeDefined();
    expect(instanceIds).toHaveLength(2);
    expect(instanceIds[0]).not.toBe(instanceIds[1]);

    const startCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCalls).toHaveLength(3);
    expect(new Set(startCalls.map(([, payload]) => payload.request.requestId)).size).toBe(1);
    expect(new Set(startCalls.map(([, payload]) => payload.request.agentSessionId)).size).toBe(1);
    expect(new Set(startCalls.map(([, payload]) => payload.request.runId)).size).toBe(1);
    expect(startCalls[0][1].request.runId).toContain(instanceIds[0]);
    expect(startCalls[2][1].request.runId).not.toContain(instanceIds[1]);
    expect(tauri.listen).toHaveBeenCalledTimes(2);

    const lines: string[] = [];
    const exits: Array<number | null> = [];
    recoveredTransport!.onLine((line) => lines.push(line));
    recoveredTransport!.onExit((code) => exits.push(code));
    await Promise.resolve();
    expect(lines).toEqual(["bootstrap-before-lost-response"]);
    expect(exits).toEqual([17]);
  });

  it("does not retry deterministic native command rejections", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    tauri.invoke.mockRejectedValue("invalid workspace");

    await expect(getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-invalid",
      workspacePath: "C:/tmp/project",
    })).rejects.toBe("invalid workspace");

    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    )).toHaveLength(1);
  });

  it("retains a write identity when the caller retries an unresolved frame", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let writes = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        return {
          agentSessionId: payload?.request.agentSessionId,
          runId: payload?.request.runId,
          provider: PROVIDER,
        };
      }
      if (command === "neko_control_session_write") {
        writes += 1;
        if (writes <= 2) throw new Error("response bridge interrupted");
        return undefined;
      }
      return undefined;
    });

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-write-retry",
      workspacePath: "C:/tmp/project",
    });
    const frame = JSON.stringify({ jsonrpc: "2.0", id: 7, method: "session/prompt" });
    await expect(transport.send(frame)).rejects.toThrow("response bridge interrupted");
    await expect(transport.send(frame)).resolves.toBeUndefined();

    const writeCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_write",
    );
    expect(writeCalls).toHaveLength(3);
    expect(writeCalls.map(([, payload]) => payload.request.requestId)).toEqual([
      writeCalls[0][1].request.requestId,
      writeCalls[0][1].request.requestId,
      writeCalls[0][1].request.requestId,
    ]);
  });

  it("uses a fresh write identity after a proven queue rejection", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let writes = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        return {
          agentSessionId: payload?.request.agentSessionId,
          runId: payload?.request.runId,
          provider: PROVIDER,
        };
      }
      if (command === "neko_control_session_write") {
        writes += 1;
        if (writes === 1) {
          throw "provider_busy: provider stdin queue is full; retry with a new request identity";
        }
        return undefined;
      }
      return undefined;
    });

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-queue-full",
      workspacePath: "C:/tmp/project",
    });
    const frame = JSON.stringify({ jsonrpc: "2.0", id: 8, method: "session/prompt" });
    await expect(transport.send(frame)).rejects.toContain("provider_busy:");
    await expect(transport.send(frame)).resolves.toBeUndefined();

    const writeCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_write",
    );
    expect(writeCalls).toHaveLength(2);
    expect(writeCalls[0][1].request.requestId).not.toBe(
      writeCalls[1][1].request.requestId,
    );
  });

  it("replays bootstrap output and exit observed before transport handlers attach", async () => {
    let onLine: ((event: { payload: string }) => void) | null = null;
    let onExit: ((event: { payload: number | null }) => void) | null = null;
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/line/")) onLine = handler;
      if (event.includes("/exit/")) onExit = handler;
      return vi.fn();
    });
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        onLine?.({ payload: "bootstrap-ready" });
        onExit?.({ payload: 17 });
        return {
          agentSessionId: payload?.request.agentSessionId,
          runId: payload?.request.runId,
          provider: PROVIDER,
        };
      }
      return undefined;
    });

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-fast-exit",
      workspacePath: "C:/tmp/project",
    });
    const lines: string[] = [];
    const exits: Array<number | null> = [];
    transport.onLine((line) => lines.push(line));
    transport.onExit((code) => exits.push(code));
    await Promise.resolve();

    expect(lines).toEqual(["bootstrap-ready"]);
    expect(exits).toEqual([17]);
  });

  it("exposes ownership before ACP initialization completes", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let owned: Driver | null = null;

    const creating = createDriverForAgent(
      PROVIDER,
      "session-1",
      { workspace: { path: "C:/tmp/project", name: "project" } },
      vi.fn(),
      (driver) => {
        owned = driver;
      },
    );
    await vi.waitFor(() => expect(owned).not.toBeNull());

    expect(owned!.runtime.providerVersion).toBe("0.25.0");
    const startCall = tauri.invoke.mock.calls.find(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCall?.[1]).toEqual({
      request: expect.objectContaining({
        requestId: expect.any(String),
        agentSessionId: expect.any(String),
        taskId: "legacy-local/task/session-1",
        runId: "legacy-local/run/session-1",
        environmentId: "legacy-local/environment/session-1",
        providerId: "neko",
        workspacePath: "C:/tmp/project",
      }),
    });
    expect(JSON.stringify(startCall)).not.toContain("program");
    expect(JSON.stringify(startCall)).not.toContain("args");

    await owned!.dispose();
    await expect(creating).rejects.toThrow("client disposed");
    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    )).toHaveLength(1);
  });
});
