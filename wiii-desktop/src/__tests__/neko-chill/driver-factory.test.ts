import { beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauri.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauri.listen }));

import type { Driver } from "@/neko-chill/drivers/types";
import { createDriverForAgent, spawnTauriTransport } from "@/neko-chill/drivers/factory";

describe("Neko driver factory resource ownership", () => {
  beforeEach(() => {
    tauri.invoke.mockReset();
    tauri.listen.mockReset();
    tauri.invoke.mockImplementation(async (command: string) =>
      command === "neko_spawn_agent" ? 42 : undefined,
    );
  });

  it("kills the spawned process if listener setup fails", async () => {
    const unlistenLine = vi.fn();
    tauri.listen
      .mockResolvedValueOnce(unlistenLine)
      .mockRejectedValueOnce(new Error("event bridge unavailable"));

    await expect(spawnTauriTransport("neko", ["acp"])).rejects.toThrow(
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

    const transport = await spawnTauriTransport("neko", ["acp"]);
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

    await owned!.dispose();
    await expect(creating).rejects.toThrow("client disposed");
    expect(tauri.invoke.mock.calls.filter(([command]) => command === "neko_kill_agent")).toHaveLength(1);
  });
});
