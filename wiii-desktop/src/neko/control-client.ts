import { v4 as uuidv4 } from "uuid";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import type {
  NekoDetectedProvider,
  NekoLaunchProfile,
} from "./contracts";
import type {
  NekoControlEvent,
  NekoControlReplayPage,
} from "./control-protocol";
import {
  findProviderDefinition,
  requireProviderDefinition,
} from "./provider-registry";
import { isNekoControlReplayPage } from "./control-protocol";

export interface NekoExecutionBinding {
  taskId: string;
  runId: string;
  environmentId: string;
}

export interface NekoProviderSpawnRequest {
  providerId: string;
  clientSessionId: string;
  workspacePath: string;
  profileId?: string;
  execution?: NekoExecutionBinding;
}

export interface NekoProviderProfileRequest {
  providerId: string;
  workspacePath: string;
}

export interface NekoNativeSessionRecord {
  agentSessionId: string;
  taskId: string;
  runId: string;
  environmentId: string;
  providerId: string;
  providerVersion: string | null;
  workspacePath: string;
  state: string;
  operationPhase: string;
  continuity: string;
  pid: number | null;
  createdAt: string;
  updatedAt: string;
}

interface NativeSessionStartResult {
  agentSessionId: string;
  runId: string;
  provider: NekoDetectedProvider;
}

export interface NekoSpawnedProvider {
  provider: NekoDetectedProvider;
  agentSessionId: string;
  runId: string;
  transport: AcpTransport;
}

/** Replaceable bridge from Wiii clients to Neko's native authority. */
export interface NekoControlClient {
  listProviders(): Promise<NekoDetectedProvider[]>;
  listProfiles(request: NekoProviderProfileRequest): Promise<NekoLaunchProfile[]>;
  listSessions(runId?: string): Promise<NekoNativeSessionRecord[]>;
  readEvents(streamId: string, afterSeq?: number, limit?: number): Promise<NekoControlReplayPage>;
  spawnProvider(request: NekoProviderSpawnRequest): Promise<NekoSpawnedProvider>;
}

function legacyExecution(clientSessionId: string): NekoExecutionBinding {
  return {
    taskId: `legacy-local/task/${clientSessionId}`,
    runId: `legacy-local/run/${clientSessionId}`,
    environmentId: `legacy-local/environment/${clientSessionId}`,
  };
}

class TauriNekoControlClient implements NekoControlClient {
  async listProviders(): Promise<NekoDetectedProvider[]> {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const providers = await invoke<unknown>("neko_control_provider_list");
      if (!Array.isArray(providers) || !providers.every(isDetectedProvider)) {
        throw new Error("Neko returned an invalid provider registry response.");
      }
      return providers.flatMap((provider) => {
        const definition = findProviderDefinition(provider.id);
        return definition ? [{ ...provider, name: definition.name }] : [];
      });
    } catch (error) {
      // Browser/web hosts have no local process authority.
      if (!hasNativeAuthority()) return [];
      throw error;
    }
  }

  async listProfiles(request: NekoProviderProfileRequest): Promise<NekoLaunchProfile[]> {
    requireProviderDefinition(request.providerId);
    if (!request.workspacePath) return [];
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const profiles = await invoke<unknown>("neko_control_provider_profiles", {
        providerId: request.providerId,
        cwd: request.workspacePath,
      });
      if (!Array.isArray(profiles) || !profiles.every(isLaunchProfile)) {
        throw new Error("Neko returned an invalid provider profile response.");
      }
      return profiles;
    } catch (error) {
      if (!hasNativeAuthority()) return [];
      throw error;
    }
  }

  async listSessions(runId?: string): Promise<NekoNativeSessionRecord[]> {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const sessions = await invoke<unknown>("neko_control_session_list", {
        runId: runId ?? null,
      });
      if (!Array.isArray(sessions) || !sessions.every(isNativeSessionRecord)) {
        throw new Error("Neko returned an invalid durable session response.");
      }
      return sessions;
    } catch (error) {
      if (!hasNativeAuthority()) return [];
      throw error;
    }
  }

  async readEvents(
    streamId: string,
    afterSeq: number = 0,
    limit: number = 100,
  ): Promise<NekoControlReplayPage> {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const page = await invoke<unknown>("neko_control_events_read", {
        streamId,
        afterSeq,
        limit,
      });
      if (!isNekoControlReplayPage(page, streamId, afterSeq)) {
        throw new Error("Neko returned an invalid durable event page.");
      }
      return page;
    } catch (error) {
      if (!hasNativeAuthority()) {
        return { streamId, events: [], nextAfterSeq: afterSeq, hasMore: false };
      }
      throw error;
    }
  }

  async spawnProvider(request: NekoProviderSpawnRequest): Promise<NekoSpawnedProvider> {
    const provider = requireProviderDefinition(request.providerId);
    if (!request.workspacePath) {
      throw new Error("Neko requires an explicit workspace before starting a provider.");
    }
    const execution = request.execution ?? legacyExecution(request.clientSessionId);
    const requestId = uuidv4();
    const agentSessionId = uuidv4();
    const { invoke } = await import("@tauri-apps/api/core");
    const { listen } = await import("@tauri-apps/api/event");

    const lineHandlers: Array<(line: string) => void> = [];
    const exitHandlers: Array<(code: number | null) => void> = [];
    let killed = false;
    let killPromise: Promise<void> | null = null;
    const cancelRequestId = uuidv4();
    let unlistenLine: (() => void) | null = null;
    let unlistenExit: (() => void) | null = null;

    // Subscribe before the side effect so provider bootstrap output cannot
    // race ahead of the WebView listener registration.
    try {
      unlistenLine = await listen<string>(`neko-session://line/${agentSessionId}`, (event) => {
        for (const handler of lineHandlers) handler(event.payload);
      });
      unlistenExit = await listen<number | null>(`neko-session://exit/${agentSessionId}`, (event) => {
        for (const handler of exitHandlers) handler(event.payload ?? null);
      });
    } catch (error) {
      unlistenLine?.();
      unlistenExit?.();
      throw error;
    }

    let started: NativeSessionStartResult;
    try {
      started = await invokeIdempotently<NativeSessionStartResult>(invoke, "neko_control_session_start", {
        request: {
          requestId,
          agentSessionId,
          taskId: execution.taskId,
          runId: execution.runId,
          providerId: provider.id,
          environmentId: execution.environmentId,
          workspacePath: request.workspacePath,
          ...(request.profileId ? { profileId: request.profileId } : {}),
        },
      });
    } catch (error) {
      unlistenLine?.();
      unlistenExit?.();
      // A rejected start may represent unknown_outcome. Never issue a second
      // native side effect as cleanup without an authoritative start result.
      throw error;
    }

    const transport: AcpTransport = {
      async send(line: string): Promise<void> {
        await invokeIdempotently(invoke, "neko_control_session_write", {
          request: {
            requestId: uuidv4(),
            agentSessionId: started.agentSessionId,
            line,
          },
        });
      },
      onLine(handler: (line: string) => void): void {
        lineHandlers.push(handler);
      },
      onExit(handler: (code: number | null) => void): void {
        exitHandlers.push(handler);
      },
      async kill(): Promise<void> {
        if (killed) return;
        if (!killPromise) {
          killPromise = (async () => {
            await invokeIdempotently(invoke, "neko_control_session_cancel", {
              request: {
                requestId: cancelRequestId,
                runId: started.runId,
                agentSessionId: started.agentSessionId,
              },
            });
            killed = true;
            unlistenLine?.();
            unlistenExit?.();
          })();
        }
        try {
          await killPromise;
        } catch (error) {
          // A caller may ask again, but it will reuse the same durable request
          // identity and therefore cannot repeat an uncertain cancellation.
          killPromise = null;
          throw error;
        }
      },
    };
    return {
      provider: started.provider,
      agentSessionId: started.agentSessionId,
      runId: started.runId,
      transport,
    };
  }
}

function hasNativeAuthority(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function isDetectedProvider(value: unknown): value is NekoDetectedProvider {
  if (!value || typeof value !== "object") return false;
  const provider = value as Record<string, unknown>;
  return (
    typeof provider.id === "string" &&
    typeof provider.name === "string" &&
    (provider.version === null || typeof provider.version === "string") &&
    typeof provider.found === "boolean" &&
    typeof provider.supportsProfiles === "boolean"
  );
}

function isLaunchProfile(value: unknown): value is NekoLaunchProfile {
  if (!value || typeof value !== "object") return false;
  const profile = value as Record<string, unknown>;
  return (
    typeof profile.id === "string" &&
    typeof profile.provider === "string" &&
    (profile.model === null || typeof profile.model === "string") &&
    typeof profile.active === "boolean"
  );
}

function isNativeSessionRecord(value: unknown): value is NekoNativeSessionRecord {
  if (!value || typeof value !== "object") return false;
  const session = value as Record<string, unknown>;
  return (
    [
      "agentSessionId",
      "taskId",
      "runId",
      "environmentId",
      "providerId",
      "workspacePath",
      "state",
      "operationPhase",
      "continuity",
      "createdAt",
      "updatedAt",
    ].every((field) => typeof session[field] === "string") &&
    (session.providerVersion === null || typeof session.providerVersion === "string") &&
    (session.pid === null || Number.isSafeInteger(session.pid))
  );
}

async function invokeIdempotently<T>(
  invoke: <R>(command: string, args?: Record<string, unknown>) => Promise<R>,
  command: string,
  args: Record<string, unknown>,
): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch {
    // Retrying the identical request identity is safe: Rust either returns
    // the recorded result or reports unknown_outcome without repeating the
    // side effect. Never mint a replacement request here.
    return invoke<T>(command, args);
  }
}

const defaultClient: NekoControlClient = new TauriNekoControlClient();

export function getNekoControlClient(): NekoControlClient {
  return defaultClient;
}

export type { NekoControlEvent };
