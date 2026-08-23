/**
 * Driver factory: resolves one provider definition, asks Neko Control to own
 * its process transport, then selects the protocol adapter. Provider launch
 * arguments and raw Tauri commands live outside this module.
 */
import { getNekoControlClient } from "@/neko/control-client";
import type { NekoExecutionBinding } from "@/neko/control-client";
import { requireProviderDefinition } from "@/neko/provider-registry";
import { AcpDriver } from "./acp/driver";
import { CodexAppServerDriver } from "./codex/driver";
import type { Driver, DriverEventHandler } from "./types";
import type { DetectedAgent } from "../stores/neko-agent-store";
import { isAbsoluteWorkspacePath, type WorkspaceRef } from "../workspace";

export interface DriverLaunchConfig {
  workspace: WorkspaceRef;
  /** Wiii-owned work identity. Omitted only for manual/legacy Neko sessions. */
  execution?: NekoExecutionBinding;
  /** One RuntimeRegistry replacement attempt; creates a fresh Neko Run. */
  executionId?: string;
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
  if (!isAbsoluteWorkspacePath(launch.workspace.path)) {
    throw new Error("Hãy chọn thư mục dự án trước khi bắt đầu.");
  }

  const control = getNekoControlClient();
  const spawned = await control.spawnProvider({
    providerId: agent.id,
    clientSessionId: sessionId,
    ...(launch.executionId ? { clientRunId: launch.executionId } : {}),
    ...(launch.execution ? { execution: launch.execution } : {}),
    workspacePath: launch.workspace.path,
    ...(launch.profileId ? { profileId: launch.profileId } : {}),
  });
  const { transport } = spawned;
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
  driver.runtime.providerVersion = spawned.provider.version;
  driver.runtime.providerExtensions = {
    ...(driver.runtime.providerExtensions ?? {}),
    nativeAgentSessionId: spawned.agentSessionId,
    nativeRunId: spawned.runId,
  };
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
