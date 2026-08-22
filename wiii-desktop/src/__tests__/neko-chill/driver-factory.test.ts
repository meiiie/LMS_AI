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

describe("Neko driver factory resource ownership", () => {
  beforeEach(() => {
    tauri.invoke.mockReset();
    tauri.listen.mockReset();
    tauri.invoke.mockImplementation(async (command: string) => {
      if (command === "neko_spawn_agent") return 42;
      if (command === "neko_detect_agents") {
        return [
          {
            id: "neko",
            name: "stale probe label",
            binary: "C:/tools/neko.exe",
            version: "0.25.0",
            found: true,
          },
          {
            id: "unknown",
            name: "Unknown executable",
            binary: "unknown",
            version: "1.0.0",
            found: true,
          },
        ];
      }
      return undefined;
    });
  });

  it("normalizes detected metadata and hides providers Neko cannot launch", async () => {
    await expect(getNekoControlClient().listProviders()).resolves.toEqual([{
      id: "neko",
      name: "Neko Core",
      binary: "C:/tools/neko.exe",
      version: "0.25.0",
      found: true,
    }]);
  });

  it("kills the spawned process if listener setup fails", async () => {
    const unlistenLine = vi.fn();
    tauri.listen
      .mockResolvedValueOnce(unlistenLine)
      .mockRejectedValueOnce(new Error("event bridge unavailable"));

    await expect(getNekoControlClient().spawnProvider({
      providerId: "neko",
    })).rejects.toThrow(
      "event bridge unavailable",
    );

    expect(unlistenLine).toHaveBeenCalledOnce();
    expect(tauri.invoke).toHaveBeenCalledWith("neko_kill_agent", { procId: 42,
    });
  });

  it("owns listener cleanup and process kill idempotently", async () => {
    const unlistenLine = vi.fn();
    const unlistenExit = vi.fn();
    tauri.listen
      .mockResolvedValueOnce(unlistenLine)
      .mockResolvedValueOnce(unlistenExit);

    const { transport } = await getNekoControlClient().spawnProvider({
      providerId: "neko",
    });
    await transport.kill();
    await transport.kill();

    expect(unlistenLine).toHaveBeenCalledOnce();
    expect(unlistenExit).toHaveBeenCalledOnce();
    expect(tauri.invoke.mock.calls.filter(([command]) => command === "neko_kill_agent"))
      .toHaveLength(1);
  });

  it("exposes ownership before ACP initialization completes", async () => {
    tauri.listen.mockResolvedValueOnce(vi.fn()).mockResolvedValueOnce(vi.fn());
    let owned: Driver | null = null;

    const creating = createDriverForAgent(
      {
        id: "neko",
        name: "Neko Core",
        binary: "neko",
        version: "0.24.0",
        found: true,
      },
      "session-1",
      { workspace: { path: "C:/tmp/project", name: "project" } },
      vi.fn(),
      (driver) => {
        owned = driver;
      },
    );
    await vi.waitFor(() => expect(owned).not.toBeNull());

    expect(owned!.runtime.providerVersion).toBe("0.25.0");
    expect(tauri.invoke).toHaveBeenCalledWith("neko_spawn_agent", {
      program: "C:/tools/neko.exe",
      args: ["acp"],
    });

    await owned!.dispose();
    await expect(creating).rejects.toThrow("client disposed");
    expect(tauri.invoke.mock.calls.filter(([command]) => command === "neko_kill_agent")).toHaveLength(1);
  });
});
