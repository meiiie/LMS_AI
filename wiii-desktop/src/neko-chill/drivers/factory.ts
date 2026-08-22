/**
 * Driver factory: resolves one provider definition, asks Neko Control to own
 * its process transport, then selects the protocol adapter. Provider launch
 * arguments and raw Tauri commands live outside this module.
 */
import { getNekoControlClient } from "@/neko/control-client";
import { requireProviderDefinition } from "@/neko/provider-registry";
import { AcpDriver } from "./acp/driver";
import { CodexAppServerDriver } from "./codex/driver";
import type { Driver, DriverEventHandler } from "./types";
import type { DetectedAgent } from "../stores/neko-agent-store";
import { isAbsoluteWorkspacePath, type WorkspaceRef } from "../workspace";

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
  const provider = requireProviderDefinition(agent.id);
  if (!agent.binary) throw new Error(`Agent "${agent.name}" chưa được cài trên máy này`);
  if (!isAbsoluteWorkspacePath(launch.workspace.path)) {
    throw new Error("Hãy chọn thư mục dự án trước khi bắt đầu.");
  }

  const transport = await getNekoControlClient().spawnProvider({
    providerId: agent.id,
    program: agent.binary,
    ...(launch.profileId ? { profileId: launch.profileId } : {}),
  });
  const driver: Driver = provider.protocol === "codex-app-server"
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
    // RuntimeRegistry owns the process before initialize/session-new can hang.
    ownDriver?.(driver);
    await driver.start();
    return driver;
  } catch (error) {
    if (!ownDriver) await driver.dispose().catch(() => {});
    throw error;
  }
}
