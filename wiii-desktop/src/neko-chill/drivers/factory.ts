/**
 * Driver factory (T303) — the only place that knows how to launch a
 * detected agent: Tauri transport over the Rust `neko_agent` commands,
 * then an AcpDriver speaking the wire protocol.
 *
 * Tests replace `createDriverForAgent` via vi.mock of this module.
 */
import type { AcpTransport } from "./acp/client";
import { AcpDriver } from "./acp/driver";
import { CodexAppServerDriver } from "./codex/driver";
import type { Driver, DriverEventHandler } from "./types";
import type { DetectedAgent } from "../stores/neko-agent-store";
import { isAbsoluteWorkspacePath, type WorkspaceRef } from "../workspace";

/** ACP launch spec per agent id (PROTOCOL-NOTES: verified invocations). */
const ACP_ARGS: Record<string, string[]> = {
  gemini: ["--experimental-acp"],
  neko: ["acp"],
  codex: ["app-server"],
};

/**
 * AcpTransport over the Rust process table: spawn → stdin writes via
 * invoke, stdout lines + exit via Tauri events (`neko-agent://line|exit/{id}`).
 */
export async function spawnTauriTransport(
  program: string,
  args: string[],
): Promise<AcpTransport> {
  const { invoke } = await import("@tauri-apps/api/core");
  const { listen } = await import("@tauri-apps/api/event");

  const procId = await invoke<number>("neko_spawn_agent", { program, args });

  const lineHandlers: Array<(line: string) => void> = [];
  const exitHandlers: Array<(code: number | null) => void> = [];
  let killed = false;
  let unlistenLine: (() => void) | null = null;
  let unlistenExit: (() => void) | null = null;

  try {
    unlistenLine = await listen<string>(`neko-agent://line/${procId}`, (event) => {
      for (const handler of lineHandlers) handler(event.payload);
    });
    unlistenExit = await listen<number | null>(`neko-agent://exit/${procId}`, (event) => {
      for (const handler of exitHandlers) handler(event.payload ?? null);
    });
  } catch (error) {
    unlistenLine?.();
    unlistenExit?.();
    await invoke("neko_kill_agent", { procId }).catch(() => {});
    throw error;
  }

  return {
    async send(line: string): Promise<void> {
      await invoke("neko_write_stdin", { procId, line });
    },
    onLine(handler: (line: string) => void): void {
      lineHandlers.push(handler);
    },
    onExit(handler: (code: number | null) => void): void {
      exitHandlers.push(handler);
    },
    async kill(): Promise<void> {
      if (killed) return;
      killed = true;
      unlistenLine?.();
      unlistenExit?.();
      await invoke("neko_kill_agent", { procId }).catch(() => {
        /* process already gone */
      });
    },
  };
}

export interface DriverLaunchConfig {
  workspace: WorkspaceRef;
  profileId?: string;
  backendSessionId?: string | null;
}

export async function createDriverForAgent(
  agent: DetectedAgent,
  sessionId: string,
  launch: DriverLaunchConfig,
  onEvent: DriverEventHandler,
  ownDriver?: (driver: Driver) => void,
): Promise<Driver> {
  const baseArgs = ACP_ARGS[agent.id];
  if (!baseArgs) throw new Error(`Không có cấu hình ACP cho agent "${agent.id}"`);
  if (!agent.binary) throw new Error(`Agent "${agent.name}" chưa được cài trên máy này`);
  if (!isAbsoluteWorkspacePath(launch.workspace.path)) {
    throw new Error("Hãy chọn thư mục dự án trước khi bắt đầu.");
  }

  const args = [
    ...baseArgs,
    ...(agent.id === "neko" && launch.profileId
      ? ["--profile", launch.profileId]
      : []),
  ];
  const transport = await spawnTauriTransport(agent.binary, args);
  const driver: Driver = agent.id === "codex"
    ? new CodexAppServerDriver({
        sessionId,
        cwd: launch.workspace.path,
        resumeThreadId: launch.backendSessionId,
        transport,
        onEvent,
      })
    : new AcpDriver({
        sessionId,
        cwd: launch.workspace.path,
        resumeSessionId: launch.backendSessionId,
        transport,
        onEvent,
      });
  try {
    // Let RuntimeRegistry own the process before initialize/session-new can hang.
    ownDriver?.(driver);
    await driver.start();
    return driver;
  } catch (error) {
    if (!ownDriver) await driver.dispose().catch(() => {});
    throw error;
  }
}
