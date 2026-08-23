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
  /** Fresh local runtime identity. The visible session remains the Task. */
  clientRunId?: string;
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

interface StartTransportState {
  lineHandlers: Array<(line: string) => void>;
  exitHandlers: Array<(code: number | null) => void>;
  pendingLines: string[];
  exitObserved: boolean;
  pendingExitCode: number | null;
  killed: boolean;
  killPromise: Promise<void> | null;
  cancelRequestId: string;
  unresolvedWriteIds: Map<string, string>;
  unlistenLine: (() => void) | null;
  unlistenExit: (() => void) | null;
  listenerSetup: Promise<void> | null;
}

interface UnresolvedStartIdentity {
  requestId: string;
  agentSessionId: string;
  execution: NekoExecutionBinding;
  transport: StartTransportState;
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

function legacyExecution(
  clientSessionId: string,
  clientRunId: string = clientSessionId,
): NekoExecutionBinding {
  return {
    taskId: `legacy-local/task/${clientSessionId}`,
    runId: `legacy-local/run/${clientRunId}`,
    environmentId: `legacy-local/environment/${clientRunId}`,
  };
}

class TauriNekoControlClient implements NekoControlClient {
  /** Caller retries reuse this identity until Rust gives a certain outcome. */
  private readonly unresolvedStarts = new Map<string, UnresolvedStartIdentity>();

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
      throw new Error("Neko cần một thư mục dự án rõ ràng trước khi khởi động agent.");
    }
    const requestedExecution = request.execution ?? legacyExecution(
      request.clientSessionId,
      request.clientRunId,
    );
    // A visible Wiii session is the stable caller identity. RuntimeRegistry
    // deliberately mints a fresh instanceId for each preparation, so run and
    // environment IDs cannot participate in the unresolved-operation key.
    // Until Rust returns a certain outcome, a later preparation must recover
    // the original logical start rather than create another native process.
    const startKey = JSON.stringify([
      provider.id,
      requestedExecution.taskId,
      request.clientSessionId,
      request.workspacePath,
      request.profileId ?? null,
    ]);
    const priorStart = this.unresolvedStarts.get(startKey);
    const startIdentity = priorStart ?? {
      requestId: uuidv4(),
      agentSessionId: uuidv4(),
      execution: requestedExecution,
      transport: createStartTransportState(),
    };
    this.unresolvedStarts.set(startKey, startIdentity);
    const { requestId, agentSessionId, execution, transport: transportState } = startIdentity;
    const { invoke } = await import("@tauri-apps/api/core");
    const { listen } = await import("@tauri-apps/api/event");

    // Subscribe before the side effect so provider bootstrap output cannot
    // race ahead of the WebView listener registration. The listener and its
    // buffers belong to the unresolved logical start, not this one caller;
    // losing both IPC responses must not discard bootstrap output or exit.
    try {
      await ensureStartListeners(transportState, listen, agentSessionId);
    } catch (error) {
      detachStartListeners(transportState);
      if (this.unresolvedStarts.get(startKey) === startIdentity) {
        this.unresolvedStarts.delete(startKey);
      }
      throw error;
    }

    let started: NativeSessionStartResult;
    try {
      const result = await invokeIdempotently<unknown>(invoke, "neko_control_session_start", {
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
      if (!isNativeSessionStartResult(result)) {
        throw new Error("Neko trả về kết quả khởi động phiên không hợp lệ.");
      }
      started = result;
      if (this.unresolvedStarts.get(startKey) === startIdentity) {
        this.unresolvedStarts.delete(startKey);
      }
    } catch (error) {
      // A rejected start may represent unknown_outcome. Never issue a second
      // native side effect as cleanup without an authoritative start result.
      // Authoritative pre-side-effect rejections release the identity. An
      // explicit unknown_outcome or a bridge failure retains the original
      // execution binding, listener, and buffered transport state so a
      // caller-level retry cannot spawn twice or lose bootstrap events.
      if (
        typeof error === "string" &&
        !isUnknownStartOutcome(error) &&
        this.unresolvedStarts.get(startKey) === startIdentity
      ) {
        this.unresolvedStarts.delete(startKey);
        detachStartListeners(transportState);
      }
      throw error;
    }

    const transport: AcpTransport = {
      async send(line: string): Promise<void> {
        // Keep the logical write identity after an unresolved native response.
        // A caller retrying the same provider frame must reach Rust with the
        // same request ID so it cannot repeat a committed side effect.
        const requestId = transportState.unresolvedWriteIds.get(line) ?? uuidv4();
        transportState.unresolvedWriteIds.set(line, requestId);
        try {
          await invokeIdempotently(invoke, "neko_control_session_write", {
            request: {
              requestId,
              agentSessionId: started.agentSessionId,
              line,
            },
          });
          if (transportState.unresolvedWriteIds.get(line) === requestId) {
            transportState.unresolvedWriteIds.delete(line);
          }
        } catch (error) {
          // A full bounded writer queue proves Rust did not enqueue this
          // frame. Only that explicit rejection may mint a fresh identity on
          // retry; all uncertain outcomes retain the original request ID.
          if (
            isProviderBusy(error) &&
            transportState.unresolvedWriteIds.get(line) === requestId
          ) {
            transportState.unresolvedWriteIds.delete(line);
          }
          throw error;
        }
      },
      onLine(handler: (line: string) => void): void {
        transportState.lineHandlers.push(handler);
        if (transportState.pendingLines.length > 0) {
          const buffered = transportState.pendingLines.splice(0);
          for (const line of buffered) handler(line);
        }
      },
      onExit(handler: (code: number | null) => void): void {
        transportState.exitHandlers.push(handler);
        if (transportState.exitObserved) {
          queueMicrotask(() => handler(transportState.pendingExitCode));
        }
      },
      async kill(): Promise<void> {
        if (transportState.killed) return;
        if (!transportState.killPromise) {
          transportState.killPromise = (async () => {
            await invokeIdempotently(invoke, "neko_control_session_cancel", {
              request: {
                requestId: transportState.cancelRequestId,
                runId: started.runId,
                agentSessionId: started.agentSessionId,
              },
            });
            transportState.killed = true;
            transportState.unresolvedWriteIds.clear();
            detachStartListeners(transportState);
          })();
        }
        try {
          await transportState.killPromise;
        } catch (error) {
          // A caller may ask again, but it will reuse the same durable request
          // identity and therefore cannot repeat an uncertain cancellation.
          transportState.killPromise = null;
          detachStartListeners(transportState);
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

function createStartTransportState(): StartTransportState {
  return {
    lineHandlers: [],
    exitHandlers: [],
    pendingLines: [],
    exitObserved: false,
    pendingExitCode: null,
    killed: false,
    killPromise: null,
    cancelRequestId: uuidv4(),
    unresolvedWriteIds: new Map(),
    unlistenLine: null,
    unlistenExit: null,
    listenerSetup: null,
  };
}

function detachStartListeners(state: StartTransportState): void {
  state.unlistenLine?.();
  state.unlistenExit?.();
  state.unlistenLine = null;
  state.unlistenExit = null;
}

async function ensureStartListeners(
  state: StartTransportState,
  listen: typeof import("@tauri-apps/api/event").listen,
  agentSessionId: string,
): Promise<void> {
  if (state.listenerSetup) return state.listenerSetup;
  state.listenerSetup = (async () => {
    state.unlistenLine = await listen<string>(
      `neko-session://line/${agentSessionId}`,
      (event) => {
        if (state.lineHandlers.length === 0) state.pendingLines.push(event.payload);
        else for (const handler of state.lineHandlers) handler(event.payload);
      },
    );
    try {
      state.unlistenExit = await listen<number | null>(
        `neko-session://exit/${agentSessionId}`,
        (event) => {
          state.exitObserved = true;
          state.pendingExitCode = event.payload ?? null;
          for (const handler of state.exitHandlers) handler(state.pendingExitCode);
          state.killed = true;
          state.unresolvedWriteIds.clear();
          queueMicrotask(() => detachStartListeners(state));
        },
      );
    } catch (error) {
      detachStartListeners(state);
      throw error;
    }
  })();
  return state.listenerSetup;
}

function hasNativeAuthority(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function isProviderBusy(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.startsWith("provider_busy:");
}

function isUnknownStartOutcome(error: string): boolean {
  return error.startsWith("unknown_outcome:");
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

function isNativeSessionStartResult(value: unknown): value is NativeSessionStartResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.agentSessionId === "string" &&
    typeof result.runId === "string" &&
    isDetectedProvider(result.provider)
  );
}

async function invokeIdempotently<T>(
  invoke: <R>(command: string, args?: Record<string, unknown>) => Promise<R>,
  command: string,
  args: Record<string, unknown>,
): Promise<T> {
  try {
    return await invoke<T>(command, args);
  } catch (first) {
    // Rust command rejections are authoritative serialized strings. Retry only
    // bridge/runtime failures where response delivery itself is uncertain.
    if (typeof first === "string") throw first;
    // Retrying the identical request identity is safe: Rust either returns
    // the recorded result or reports unknown_outcome without repeating the
    // side effect. Never mint a replacement request here.
    try {
      return await invoke<T>(command, args);
    } catch (second) {
      if (typeof second === "string") throw second;
      const message = second instanceof Error ? second.message : String(second);
      const failure = new Error(`${command} failed after an uncertain IPC retry: ${message}`) as Error & {
        cause?: unknown;
      };
      failure.cause = first;
      throw failure;
    }
  }
}

const defaultClient: NekoControlClient = new TauriNekoControlClient();

export function getNekoControlClient(): NekoControlClient {
  return defaultClient;
}

export type { NekoControlEvent };
