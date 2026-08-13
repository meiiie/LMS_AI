/**
 * Driver factory (T303) — the only place that knows how to launch a
 * detected agent: Tauri transport over the Rust `neko_agent` commands,
 * then an AcpDriver speaking the wire protocol.
 *
 * Tests replace `createDriverForAgent` via vi.mock of this module.
 */
import type { AcpTransport } from "./acp/client";
import { AcpDriver } from "./acp/driver";
import type { Driver, DriverEventHandler } from "./types";
import type { DetectedAgent } from "../stores/neko-agent-store";

/** ACP launch spec per agent id (PROTOCOL-NOTES: verified invocations). */
const ACP_ARGS: Record<string, string[]> = {
  gemini: ["--experimental-acp"],
  neko: ["acp"],
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

  const unlistenLine = await listen<string>(`neko-agent://line/${procId}`, (event) => {
    for (const handler of lineHandlers) handler(event.payload);
  });
  const unlistenExit = await listen<number | null>(`neko-agent://exit/${procId}`, (event) => {
    for (const handler of exitHandlers) handler(event.payload ?? null);
  });

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
      unlistenLine();
      unlistenExit();
      await invoke("neko_kill_agent", { procId }).catch(() => {
        /* process already gone */
      });
    },
  };
}

/** Absolute project directory for `session/new` (ACP requires absolute). */
async function resolveSessionCwd(): Promise<string> {
  try {
    const { homeDir } = await import("@tauri-apps/api/path");
    return await homeDir();
  } catch {
    return "/";
  }
}

export async function createDriverForAgent(
  agent: DetectedAgent,
  sessionId: string,
  onEvent: DriverEventHandler,
): Promise<Driver> {
  const args = ACP_ARGS[agent.id];
  if (!args) throw new Error(`Không có cấu hình ACP cho agent "${agent.id}"`);
  if (!agent.binary) throw new Error(`Agent "${agent.name}" chưa được cài trên máy này`);

  const [transport, cwd] = await Promise.all([
    spawnTauriTransport(agent.binary, args),
    resolveSessionCwd(),
  ]);
  const driver = new AcpDriver({ sessionId, cwd, transport, onEvent });
  await driver.start();
  return driver;
}
