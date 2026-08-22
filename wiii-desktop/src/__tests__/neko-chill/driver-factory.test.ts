import { beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauri.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauri.listen }));

import type { Driver } from "@/neko-chill/drivers/types";
import { createDriverForAgent } from "@/neko-chill/drivers/factory";
import { getNekoControlClient } from "@/neko/control-client";

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
