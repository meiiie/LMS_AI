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
  availability: "available",
  supportsProfiles: true,
};

type ExitNotice = {
  exitCode: number | null;
  terminationProven: boolean;
  terminalStatePersisted: boolean;
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
            availability: "available",
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

  it("preserves an explicit host-unsupported provider state", async () => {
    tauri.invoke.mockResolvedValueOnce([{
      ...PROVIDER,
      version: null,
      found: false,
      availability: "host_unsupported",
    }]);

    await expect(getNekoControlClient().listProviders()).resolves.toEqual([{
      ...PROVIDER,
      version: null,
      found: false,
      availability: "host_unsupported",
    }]);
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

  it("does not duplicate a durable Codex account bootstrap after a renderer reload", async () => {
    const identity = "codex-account-bootstrap-4f088e4d-13bc-58e4-8439-a80235ae7e44";
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_control_session_list") {
        return [{
          agentSessionId: "native-account-probe",
          taskId: `legacy-local/task/${identity}`,
          runId: `legacy-local/run/${identity}`,
          environmentId: `legacy-local/environment/${identity}`,
          providerId: "codex",
          providerVersion: "0.149.0",
          workspacePath: "C:/tmp/project",
          state: "starting",
          operationPhase: "accepted",
          continuity: "active",
          pid: null,
          createdAt: "2026-08-23T00:00:00Z",
          updatedAt: "2026-08-23T00:00:00Z",
        }];
      }
      return undefined;
    });

    await expect(getNekoControlClient().spawnProvider({
      providerId: "codex",
      clientSessionId: identity,
      clientRunId: "new-account-probe-attempt",
      workspacePath: "C:/tmp/project",
    })).rejects.toThrow("không được tự khởi chạy bản trùng");

    expect(tauri.listen).not.toHaveBeenCalled();
    expect(tauri.invoke).toHaveBeenCalledWith("neko_control_session_list", { runId: null });
    expect(tauri.invoke).not.toHaveBeenCalledWith(
      "neko_control_session_start",
      expect.anything(),
    );
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

  it("bounds aggregate bootstrap output and cancels the unresolved native start", async () => {
    let onLine: ((event: { payload: string }) => void) | null = null;
    const unlistenLine = vi.fn();
    const unlistenExit = vi.fn();
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/line/")) {
        onLine = handler;
        return unlistenLine;
      }
      return unlistenExit;
    });
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        starts += 1;
        if (starts === 1) {
          for (let index = 0; index < 257; index += 1) {
            onLine?.({ payload: `bootstrap-${index}` });
          }
        }
        throw new Error("start response bridge interrupted");
      }
      if (command === "neko_control_session_cancel") {
        return { agentSessionId: payload?.request.agentSessionId, cancelled: true };
      }
      return undefined;
    });
    const request = {
      providerId: "neko",
      clientSessionId: "session-bootstrap-overflow",
      workspacePath: "C:/tmp/project",
    };

    await expect(getNekoControlClient().spawnProvider(request)).rejects.toThrow(
      "start response bridge interrupted",
    );
    await expect(getNekoControlClient().spawnProvider(request)).rejects.toThrow(
      "Bootstrap output",
    );

    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    )).toHaveLength(2);
    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    )).toHaveLength(1);
    expect(unlistenLine).toHaveBeenCalledOnce();
    expect(unlistenExit).toHaveBeenCalledOnce();
  });

  it("cancels a retained unresolved start before its visible session is deleted", async () => {
    tauri.listen.mockResolvedValue(vi.fn());
    let retainedStart: Record<string, any> | null = null;
    let exposeNativeSession = false;
    let nativeState = "running";
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        starts += 1;
        retainedStart = payload?.request;
        if (starts <= 2) throw new Error("both start responses were lost");
        throw "unknown_outcome: original start is still running";
      }
      if (command === "neko_control_session_list") {
        return exposeNativeSession ? [{
          agentSessionId: retainedStart?.agentSessionId,
          taskId: retainedStart?.taskId,
          runId: retainedStart?.runId,
          environmentId: retainedStart?.environmentId,
          providerId: "neko",
          providerVersion: "0.25.0",
          workspacePath: "C:/tmp/project",
          state: nativeState,
          operationPhase: nativeState === "unknown_outcome" ? "unknown_outcome" : "committed",
          continuity: nativeState === "unknown_outcome" ? "unknown_outcome" : "active",
          pid: 123,
          createdAt: "2026-08-23T00:00:00.000Z",
          updatedAt: "2026-08-23T00:01:00.000Z",
        }] : [];
      }
      if (command === "neko_control_session_cancel") {
        nativeState = "cancelled";
        return { agentSessionId: payload?.request.agentSessionId, cancelled: true };
      }
      return undefined;
    });

    await expect(getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-retained-delete",
      workspacePath: "C:/tmp/project",
    })).rejects.toThrow("both start responses were lost");
    expect(getNekoControlClient().unresolvedStartSessionIds()).toEqual([
      "session-retained-delete",
    ]);
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-retained-delete"),
    ).rejects.toContain("unknown_outcome");
    exposeNativeSession = true;
    nativeState = "unknown_outcome";
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-retained-delete"),
    ).rejects.toThrow("unknown_outcome");
    nativeState = "running";
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-retained-delete"),
    ).resolves.toBe(1);
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-retained-delete"),
    ).resolves.toBe(0);
    expect(getNekoControlClient().unresolvedStartSessionIds()).toEqual([]);

    const startCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    const cancelCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    );
    expect(startCalls).toHaveLength(3);
    expect(new Set(startCalls.map(([, payload]) => payload.request.requestId)).size).toBe(1);
    expect(new Set(startCalls.map(([, payload]) => payload.request.agentSessionId)).size).toBe(1);
    expect(cancelCalls).toHaveLength(1);
    expect(cancelCalls[0][1].request).toMatchObject({
      runId: startCalls[0][1].request.runId,
      agentSessionId: startCalls[0][1].request.agentSessionId,
      requestId: expect.any(String),
    });
  });

  it("cancels a durable retained start after renderer ownership is lost", async () => {
    const clientSessionId = "codex-account-bootstrap-durable";
    const agentSessionId = "native-durable-bootstrap";
    const runId = "native-durable-run";
    let nativeState = "running";
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_list") {
        return [
          {
            agentSessionId,
            taskId: `legacy-local/task/${clientSessionId}`,
            runId,
            environmentId: "native-durable-environment",
            providerId: "codex",
            providerVersion: "0.149.0",
            workspacePath: "C:/tmp/old-project",
            state: nativeState,
            operationPhase: "committed",
            continuity: "active",
            pid: nativeState === "running" ? 123 : null,
            createdAt: "2026-08-23T00:00:00.000Z",
            updatedAt: "2026-08-23T00:01:00.000Z",
          },
          {
            agentSessionId: "native-gemini-sibling",
            taskId: `legacy-local/task/${clientSessionId}`,
            runId: "native-gemini-run",
            environmentId: "native-gemini-environment",
            providerId: "gemini",
            providerVersion: "0.1.0",
            workspacePath: "C:/tmp/old-project",
            state: "running",
            operationPhase: "committed",
            continuity: "active",
            pid: 456,
            createdAt: "2026-08-23T00:00:00.000Z",
            updatedAt: "2026-08-23T00:01:00.000Z",
          },
        ];
      }
      if (command === "neko_control_session_cancel") {
        nativeState = "cancelled";
        return { agentSessionId: payload?.request.agentSessionId, cancelled: true };
      }
      return undefined;
    });

    expect(getNekoControlClient().unresolvedStartSessionIds()).not.toContain(clientSessionId);
    await expect(
      getNekoControlClient().reconcilableStartSessionIds(),
    ).resolves.toEqual([clientSessionId]);
    await expect(
      getNekoControlClient().cancelUnresolvedStarts(clientSessionId),
    ).resolves.toBe(1);
    await expect(
      getNekoControlClient().cancelUnresolvedStarts(clientSessionId),
    ).resolves.toBe(0);

    const cancelCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    );
    expect(cancelCalls).toHaveLength(1);
    expect(cancelCalls[0][1].request).toEqual({
      requestId: `reconcile-retained-start-${agentSessionId}`,
      runId,
      agentSessionId,
    });
  });

  it("releases a retained start whose recorded result cannot be decoded", async () => {
    tauri.listen.mockResolvedValue(vi.fn());
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_control_session_start") {
        starts += 1;
        if (starts <= 2) throw new Error("both start responses were lost");
        throw "decode recorded session start failed: invalid result payload";
      }
      if (command === "neko_control_session_list") return [];
      return undefined;
    });

    await expect(getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-undecodable-start",
      workspacePath: "C:/tmp/project",
    })).rejects.toThrow("both start responses were lost");
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-undecodable-start"),
    ).resolves.toBe(1);
    await expect(
      getNekoControlClient().cancelUnresolvedStarts("session-undecodable-start"),
    ).resolves.toBe(0);
  });

  it("recovers a lost start through real RuntimeRegistry retries without losing transport events", async () => {
    let onLine: ((event: { payload: string }) => void) | null = null;
    let onExit: ((event: { payload: ExitNotice }) => void) | null = null;
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
        onExit?.({
          payload: { exitCode: 17, terminationProven: true, terminalStatePersisted: true },
        });
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

  it("retains the original start identity after an authoritative unknown outcome", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    tauri.invoke.mockRejectedValue(
      "unknown_outcome: provider spawned but ownership commit failed",
    );
    const request = {
      providerId: "neko",
      clientSessionId: "session-unknown-start",
      workspacePath: "C:/tmp/project",
    };

    await expect(getNekoControlClient().spawnProvider(request)).rejects.toContain(
      "unknown_outcome",
    );
    await expect(getNekoControlClient().spawnProvider(request)).rejects.toContain(
      "unknown_outcome",
    );

    const startCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCalls).toHaveLength(2);
    expect(startCalls[1][1].request.requestId).toBe(startCalls[0][1].request.requestId);
    expect(startCalls[1][1].request.agentSessionId).toBe(
      startCalls[0][1].request.agentSessionId,
    );
    expect(tauri.listen).toHaveBeenCalledTimes(2);
  });

  it("does not release a start identity while the original caller is still in flight", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let resolveOriginal: ((value: unknown) => void) | null = null;
    let markOriginalInvoked: (() => void) | null = null;
    const originalInvoked = new Promise<void>((resolve) => {
      markOriginalInvoked = resolve;
    });
    let starts = 0;
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command !== "neko_control_session_start") return undefined;
      starts += 1;
      if (starts === 1) {
        markOriginalInvoked?.();
        return new Promise((resolve) => {
          resolveOriginal = resolve;
        });
      }
      throw "unknown_outcome: session start cannot be replayed automatically";
    });
    const request = {
      providerId: "neko",
      clientSessionId: "session-concurrent-start",
      workspacePath: "C:/tmp/project",
    };

    const original = getNekoControlClient().spawnProvider(request);
    await originalInvoked;
    await expect(getNekoControlClient().spawnProvider(request)).rejects.toContain(
      "unknown_outcome",
    );
    await expect(getNekoControlClient().spawnProvider(request)).rejects.toContain(
      "unknown_outcome",
    );

    const startCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCalls).toHaveLength(3);
    expect(new Set(startCalls.map(([, payload]) => payload.request.requestId)).size).toBe(1);
    expect(new Set(startCalls.map(([, payload]) => payload.request.agentSessionId)).size).toBe(1);
    resolveOriginal?.({
      agentSessionId: startCalls[0][1].request.agentSessionId,
      runId: startCalls[0][1].request.runId,
      provider: PROVIDER,
    });
    await expect(original).resolves.toMatchObject({
      agentSessionId: startCalls[0][1].request.agentSessionId,
    });
    expect(tauri.listen).toHaveBeenCalledTimes(2);
  });

  it("scopes write identity to one invocation and its bounded IPC retry", async () => {
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
    expect(writeCalls[1][1].request.requestId).toBe(writeCalls[0][1].request.requestId);
    expect(writeCalls[2][1].request.requestId).not.toBe(writeCalls[0][1].request.requestId);
  });

  it("uses independent identities for overlapping identical frames", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    const writeResolvers: Array<() => void> = [];
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        return {
          agentSessionId: payload?.request.agentSessionId,
          runId: payload?.request.runId,
          provider: PROVIDER,
        };
      }
      if (command === "neko_control_session_write") {
        return new Promise<void>((resolve) => writeResolvers.push(resolve));
      }
      return undefined;
    });

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-overlapping-writes",
      workspacePath: "C:/tmp/project",
    });
    const frame = JSON.stringify({ jsonrpc: "2.0", method: "session/cancel" });
    const first = transport.send(frame);
    const second = transport.send(frame);
    await vi.waitFor(() => {
      expect(tauri.invoke.mock.calls.filter(
        ([command]) => command === "neko_control_session_write",
      )).toHaveLength(2);
    });

    const writeCalls = tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_write",
    );
    expect(writeCalls).toHaveLength(2);
    expect(writeCalls[0][1].request.requestId).not.toBe(
      writeCalls[1][1].request.requestId,
    );
    writeResolvers.forEach((resolve) => resolve());
    await Promise.all([first, second]);
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
    let onExit: ((event: { payload: ExitNotice }) => void) | null = null;
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/line/")) onLine = handler;
      if (event.includes("/exit/")) onExit = handler;
      return vi.fn();
    });
    tauri.invoke.mockImplementation(async (command: string, payload?: Record<string, any>) => {
      if (command === "neko_control_session_start") {
        onLine?.({ payload: "bootstrap-ready" });
        onExit?.({
          payload: { exitCode: 17, terminationProven: true, terminalStatePersisted: true },
        });
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

  it("does not treat an unproven process-tree exit as completed cleanup", async () => {
    let onExit: ((event: { payload: ExitNotice }) => void) | null = null;
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/exit/")) onExit = handler;
      return vi.fn();
    });
    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-unproven-exit",
      workspacePath: "C:/tmp/project",
    });
    onExit?.({
      payload: { exitCode: null, terminationProven: false, terminalStatePersisted: false },
    });
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_control_session_cancel") {
        throw "unknown_outcome: provider process-tree termination is unproven";
      }
      return undefined;
    });

    await expect(transport.kill()).rejects.toContain("unknown_outcome:");
    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_cancel",
    )).toHaveLength(1);
  });

  it("rejects a false cancellation result while native state remains uncertain", async () => {
    let onExit: ((event: { payload: ExitNotice }) => void) | null = null;
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/exit/")) onExit = handler;
      return vi.fn();
    });
    const { transport, agentSessionId, runId } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-unpersisted-exit",
      workspacePath: "C:/tmp/project",
    });
    const exits: Array<number | null> = [];
    transport.onExit((code) => exits.push(code));
    onExit?.({
      payload: { exitCode: 17, terminationProven: true, terminalStatePersisted: false },
    });
    expect(exits).toEqual([]);
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_control_session_cancel") {
        return { agentSessionId, cancelled: false };
      }
      if (command === "neko_control_session_list") {
        return [{
          agentSessionId,
          taskId: "legacy-local/task/session-unpersisted-exit",
          runId,
          environmentId: "legacy-local/environment/session-unpersisted-exit",
          providerId: "neko",
          providerVersion: "0.25.0",
          workspacePath: "C:/tmp/project",
          state: "unknown_outcome",
          operationPhase: "unknown_outcome",
          continuity: "unknown_outcome",
          pid: null,
          createdAt: "2026-08-23T00:00:00Z",
          updatedAt: "2026-08-23T00:00:01Z",
        }];
      }
      return undefined;
    });

    await expect(transport.kill()).rejects.toThrow("unknown_outcome:");
    expect(exits).toEqual([]);
    expect(tauri.invoke.mock.calls.filter(
      ([command]) => command === "neko_control_session_list",
    )).toHaveLength(1);
  });

  it("delivers a withheld exit once cancellation reconciles a terminal projection", async () => {
    let onExit: ((event: { payload: ExitNotice }) => void) | null = null;
    tauri.listen.mockImplementation(async (event: string, handler: any) => {
      if (event.includes("/exit/")) onExit = handler;
      return vi.fn();
    });
    const { transport, agentSessionId, runId } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
      clientSessionId: "session-late-terminal-commit",
      workspacePath: "C:/tmp/project",
    });
    const exits: Array<number | null> = [];
    transport.onExit((code) => exits.push(code));
    onExit?.({
      payload: { exitCode: 17, terminationProven: true, terminalStatePersisted: false },
    });
    expect(exits).toEqual([]);

    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_control_session_cancel") {
        return { agentSessionId, cancelled: false };
      }
      if (command === "neko_control_session_list") {
        return [{
          agentSessionId,
          taskId: "legacy-local/task/session-late-terminal-commit",
          runId,
          environmentId: "legacy-local/environment/session-late-terminal-commit",
          providerId: "neko",
          providerVersion: "0.25.0",
          workspacePath: "C:/tmp/project",
          state: "failed",
          operationPhase: "failed",
          continuity: "continuity_lost",
          pid: null,
          createdAt: "2026-08-23T00:00:00Z",
          updatedAt: "2026-08-23T00:00:01Z",
        }];
      }
      return undefined;
    });

    await expect(transport.kill()).resolves.toBeUndefined();
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

  it("forwards Wiii Task, Run, and Environment identity instead of legacy-local IDs", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let owned: Driver | null = null;
    const execution = {
      taskId: "task-wiii",
      runId: "run-wiii",
      environmentId: "environment-wiii",
    };

    const creating = createDriverForAgent(
      PROVIDER,
      "visible-session",
      {
        workspace: { path: "C:/tmp/project", name: "project" },
        execution,
      },
      vi.fn(),
      (driver) => {
        owned = driver;
      },
    );
    await vi.waitFor(() => expect(owned).not.toBeNull());

    const startCall = tauri.invoke.mock.calls.find(
      ([command]) => command === "neko_control_session_start",
    );
    expect(startCall?.[1]).toEqual({
      request: expect.objectContaining(execution),
    });

    await owned!.dispose();
    await expect(creating).rejects.toThrow("client disposed");
  });
});
