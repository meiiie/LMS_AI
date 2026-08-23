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

interface NativeSessionCancelResult {
  agentSessionId: string;
  cancelled: boolean;
}

interface NativeProcessExitNotice {
  exitCode: number | null;
  terminationProven: boolean;
  terminalStatePersisted: boolean;
}

interface StartTransportState {
  lineHandlers: Array<(line: string) => void>;
  exitHandlers: Array<(code: number | null) => void>;
  pendingLines: string[];
  pendingLineBytes: number;
  terminalError: string | null;
  overflowCancellation: Promise<boolean> | null;
  exitObserved: boolean;
  pendingExitCode: number | null;
  killed: boolean;
  killPromise: Promise<void> | null;
  cancelRequestId: string;
  unlistenLine: (() => void) | null;
  unlistenExit: (() => void) | null;
  listenerSetup: Promise<void> | null;
}

interface UnresolvedStartIdentity {
  clientSessionId: string;
  requestId: string;
  agentSessionId: string;
  execution: NekoExecutionBinding;
  providerId: string;
  workspacePath: string;
  profileId: string | null;
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
  unresolvedStartSessionIds(): string[];
  cancelUnresolvedStarts(clientSessionId: string): Promise<number>;
  spawnProvider(request: NekoProviderSpawnRequest): Promise<NekoSpawnedProvider>;
}

const MAX_PENDING_BOOTSTRAP_FRAMES = 256;
const MAX_PENDING_BOOTSTRAP_BYTES = 8 * 1024 * 1024;
const NATIVE_TERMINAL_STATES = new Set(["completed", "failed", "cancelled"]);
const RECONCILE_CANCEL_REQUEST_PREFIX = "reconcile-retained-start-";

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

  unresolvedStartSessionIds(): string[] {
    return [...new Set(
      [...this.unresolvedStarts.values()].map((identity) => identity.clientSessionId),
    )].sort();
  }

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

  async cancelUnresolvedStarts(clientSessionId: string): Promise<number> {
    const retained = [...this.unresolvedStarts.entries()].filter(
      ([, identity]) => identity.clientSessionId === clientSessionId,
    );
    const representedNativeSessions = new Set(
      retained.map(([, identity]) => identity.agentSessionId),
    );
    const failures: unknown[] = [];
    let cancelled = 0;
    for (const [startKey, identity] of retained) {
      try {
        await this.cancelRetainedStart(startKey, identity);
        cancelled += 1;
      } catch (error) {
        failures.push(error);
      }
    }

    try {
      const durable = (await this.listSessions())
        .filter((session) => (
          session.taskId === legacyExecution(clientSessionId).taskId &&
          !representedNativeSessions.has(session.agentSessionId) &&
          !NATIVE_TERMINAL_STATES.has(session.state)
        ))
        .sort((a, b) => a.agentSessionId.localeCompare(b.agentSessionId));
      if (durable.length > 0) {
        const { invoke } = await import("@tauri-apps/api/core");
        for (const session of durable) {
          try {
            const result = await invokeIdempotently<unknown>(
              invoke,
              "neko_control_session_cancel",
              {
                request: {
                  requestId: `${RECONCILE_CANCEL_REQUEST_PREFIX}${session.agentSessionId}`,
                  runId: session.runId,
                  agentSessionId: session.agentSessionId,
                },
              },
            );
            await this.requireSafeCancellation(
              result,
              session.runId,
              session.agentSessionId,
              "phiên khởi động native bền vững",
            );
            cancelled += 1;
          } catch (error) {
            failures.push(error);
          }
        }
      }
    } catch (error) {
      failures.push(error);
    }

    if (failures.length > 0) {
      if (failures.length === 1) throw failures[0];
      throw new AggregateError(
        failures,
        `Neko could not safely reconcile ${failures.length} retained native start operation(s).`,
      );
    }
    return cancelled;
  }

  private async cancelRetainedStart(
    startKey: string,
    identity: UnresolvedStartIdentity,
  ): Promise<void> {
    if (identity.transport.overflowCancellation) {
      const cancelled = await this.confirmOverflowCancellation(identity);
      if (!cancelled) {
        throw new Error(identity.transport.terminalError ?? "Không thể dừng runtime native chưa đối soát.");
      }
    } else {
      const { invoke } = await import("@tauri-apps/api/core");
      const sessions = await this.listSessions(identity.execution.runId);
      let native = sessions.find(
        (candidate) => candidate.agentSessionId === identity.agentSessionId,
      );
      if (!native) {
        try {
          const replayed = await invokeIdempotently<unknown>(
            invoke,
            "neko_control_session_start",
            { request: nativeStartRequest(identity) },
          );
          if (!isNativeSessionStartResult(replayed)) {
            throw new Error("Neko trả về phản hồi phát lại phiên khởi động đã giữ không hợp lệ.");
          }
          native = {
            agentSessionId: replayed.agentSessionId,
            taskId: identity.execution.taskId,
            runId: replayed.runId,
            environmentId: identity.execution.environmentId,
            providerId: replayed.provider.id,
            providerVersion: replayed.provider.version,
            workspacePath: identity.workspacePath,
            state: "running",
            operationPhase: "committed",
            continuity: "active",
            pid: null,
            createdAt: new Date(0).toISOString(),
            updatedAt: new Date(0).toISOString(),
          };
        } catch (error) {
          if (!isRecordedStartFailure(error)) throw error;
        }
      }
      if (native && isNativeOutcomeUncertain(native)) {
        throw new Error(
          "unknown_outcome: Không thể tự quên hoặc hủy phiên khởi động native đã giữ khi kết quả còn chưa chắc chắn.",
        );
      }
      if (native && !NATIVE_TERMINAL_STATES.has(native.state)) {
        await this.cancelStartIdentity(invoke, identity);
      }
    }
    identity.transport.killed = true;
    identity.transport.pendingLines.length = 0;
    identity.transport.pendingLineBytes = 0;
    detachStartListeners(identity.transport);
    if (this.unresolvedStarts.get(startKey) === identity) {
      this.unresolvedStarts.delete(startKey);
    }
  }

  private async confirmOverflowCancellation(
    identity: UnresolvedStartIdentity,
  ): Promise<boolean> {
    if (await identity.transport.overflowCancellation) return true;
    const current = (await this.listSessions(identity.execution.runId)).find(
      (candidate) => candidate.agentSessionId === identity.agentSessionId,
    );
    if (!current || NATIVE_TERMINAL_STATES.has(current.state)) {
      return !current || !isNativeOutcomeUncertain(current);
    }
    if (isNativeOutcomeUncertain(current)) return false;
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await this.cancelStartIdentity(invoke, identity);
      return true;
    } catch {
      return false;
    }
  }

  private async cancelStartIdentity(
    invoke: <R>(command: string, args?: Record<string, unknown>) => Promise<R>,
    identity: UnresolvedStartIdentity,
  ): Promise<void> {
    const result = await invokeIdempotently<unknown>(
      invoke,
      "neko_control_session_cancel",
      {
        request: {
          requestId: identity.transport.cancelRequestId,
          runId: identity.execution.runId,
          agentSessionId: identity.agentSessionId,
        },
      },
    );
    await this.requireSafeCancellation(
      result,
      identity.execution.runId,
      identity.agentSessionId,
      "phiên khởi động native đã giữ",
    );
  }

  private async requireSafeCancellation(
    result: unknown,
    runId: string,
    agentSessionId: string,
    operation: string,
  ): Promise<void> {
    if (!isNativeSessionCancelResult(result) || result.agentSessionId !== agentSessionId) {
      throw new Error(`Neko trả về phản hồi hủy ${operation} không hợp lệ.`);
    }
    if (result.cancelled) return;

    const current = (await this.listSessions(runId)).find(
      (candidate) => candidate.agentSessionId === agentSessionId,
    );
    if (
      current &&
      (isNativeOutcomeUncertain(current) || !NATIVE_TERMINAL_STATES.has(current.state))
    ) {
      throw new Error(
        `unknown_outcome: Neko chưa chứng minh được ${operation} đã đạt trạng thái kết thúc an toàn.`,
      );
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
    if (!priorStart && request.clientSessionId.startsWith("codex-account-bootstrap-")) {
      // A fresh account-probe attempt receives a fresh Run, so duplicate
      // protection must search by its stable caller Task across the complete
      // native catalog rather than query only the newly minted Run.
      const existing = (await this.listSessions()).find(
        (candidate) =>
          candidate.taskId === requestedExecution.taskId &&
          candidate.providerId === provider.id &&
          !NATIVE_TERMINAL_STATES.has(candidate.state),
      );
      if (existing) {
        throw new Error(
          "unknown_outcome: Phiên khởi tạo tài khoản Codex đã thuộc quyền sở hữu của một Run native bền vững; " +
          "không được tự khởi chạy bản trùng sau khi renderer tải lại.",
        );
      }
    }
    if (priorStart?.transport.terminalError) {
      const cancelled = await this.confirmOverflowCancellation(priorStart);
      const message = priorStart.transport.terminalError;
      if (cancelled && this.unresolvedStarts.get(startKey) === priorStart) {
        this.unresolvedStarts.delete(startKey);
      }
      throw new Error(message);
    }
    const startIdentity = priorStart ?? {
      clientSessionId: request.clientSessionId,
      requestId: uuidv4(),
      agentSessionId: uuidv4(),
      execution: requestedExecution,
      providerId: provider.id,
      workspacePath: request.workspacePath,
      profileId: request.profileId ?? null,
      transport: createStartTransportState(),
    };
    this.unresolvedStarts.set(startKey, startIdentity);
    const { agentSessionId, transport: transportState } = startIdentity;
    const { invoke } = await import("@tauri-apps/api/core");
    const { listen } = await import("@tauri-apps/api/event");

    // Subscribe before the side effect so provider bootstrap output cannot
    // race ahead of the WebView listener registration. The listener and its
    // buffers belong to the unresolved logical start, not this one caller;
    // losing both IPC responses must not discard bootstrap output or exit.
    try {
      await ensureStartListeners(
        transportState,
        listen,
        agentSessionId,
        async () => {
          try {
            await this.cancelStartIdentity(invoke, startIdentity);
            transportState.killed = true;
            return true;
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            transportState.terminalError =
              `${transportState.terminalError ?? "Bootstrap buffer vượt giới hạn an toàn."} ` +
              `Không thể xác nhận runtime đã dừng: ${message}`;
            return false;
          }
        },
      );
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
        request: nativeStartRequest(startIdentity),
      });
      if (!isNativeSessionStartResult(result)) {
        throw new Error("Neko trả về kết quả khởi động phiên không hợp lệ.");
      }
      started = result;
      if (transportState.terminalError) {
        const cancelled = await this.confirmOverflowCancellation(startIdentity);
        if (cancelled && this.unresolvedStarts.get(startKey) === startIdentity) {
          this.unresolvedStarts.delete(startKey);
        }
        throw new Error(transportState.terminalError);
      }
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

    const requireSafeCancellation = this.requireSafeCancellation.bind(this);
    const transport: AcpTransport = {
      async send(line: string): Promise<void> {
        // One invocation is one logical write. invokeIdempotently retains this
        // ID for its bounded IPC retry; a later caller invocation, even with a
        // byte-identical frame, is a distinct operation and receives a new ID.
        const requestId = uuidv4();
        try {
          await invokeIdempotently(invoke, "neko_control_session_write", {
            request: {
              requestId,
              agentSessionId: started.agentSessionId,
              line,
            },
          });
        } catch (error) {
          // Unknown outcomes are deliberately not converted into an implicit
          // caller-level retry: that would require an explicit operation token.
          throw error;
        }
      },
      onLine(handler: (line: string) => void): void {
        transportState.lineHandlers.push(handler);
        if (transportState.pendingLines.length > 0) {
          const buffered = transportState.pendingLines.splice(0);
          transportState.pendingLineBytes = 0;
          for (const line of buffered) handler(line);
        }
      },
      onExit(handler: (code: number | null) => void): void {
        if (transportState.killed && transportState.exitObserved) {
          queueMicrotask(() => handler(transportState.pendingExitCode));
          return;
        }
        transportState.exitHandlers.push(handler);
      },
      async kill(): Promise<void> {
        if (transportState.killed) return;
        if (!transportState.killPromise) {
          transportState.killPromise = (async () => {
            const result = await invokeIdempotently<unknown>(
              invoke,
              "neko_control_session_cancel",
              {
                request: {
                  requestId: transportState.cancelRequestId,
                  runId: started.runId,
                  agentSessionId: started.agentSessionId,
                },
              },
            );
            await requireSafeCancellation(
              result,
              started.runId,
              started.agentSessionId,
              "phiên native",
            );
            transportState.killed = true;
            notifyProvenExit(transportState);
            detachStartListeners(transportState);
          })();
        }
        try {
          await transportState.killPromise;
        } catch (error) {
          // A caller may ask again, but it will reuse the same durable request
          // identity and therefore cannot repeat an uncertain cancellation.
          transportState.killPromise = null;
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
    pendingLineBytes: 0,
    terminalError: null,
    overflowCancellation: null,
    exitObserved: false,
    pendingExitCode: null,
    killed: false,
    killPromise: null,
    cancelRequestId: uuidv4(),
    unlistenLine: null,
    unlistenExit: null,
    listenerSetup: null,
  };
}

function nativeStartRequest(identity: UnresolvedStartIdentity): Record<string, string> {
  return {
    requestId: identity.requestId,
    agentSessionId: identity.agentSessionId,
    taskId: identity.execution.taskId,
    runId: identity.execution.runId,
    providerId: identity.providerId,
    environmentId: identity.execution.environmentId,
    workspacePath: identity.workspacePath,
    ...(identity.profileId ? { profileId: identity.profileId } : {}),
  };
}

function detachStartListeners(state: StartTransportState): void {
  state.unlistenLine?.();
  state.unlistenExit?.();
  state.unlistenLine = null;
  state.unlistenExit = null;
}

function notifyProvenExit(state: StartTransportState): void {
  if (!state.killed || !state.exitObserved) return;
  const handlers = state.exitHandlers.splice(0);
  for (const handler of handlers) handler(state.pendingExitCode);
}

async function ensureStartListeners(
  state: StartTransportState,
  listen: typeof import("@tauri-apps/api/event").listen,
  agentSessionId: string,
  cancelOverflow: () => Promise<boolean>,
): Promise<void> {
  if (state.listenerSetup) return state.listenerSetup;
  state.listenerSetup = (async () => {
    const unlistenLine = await listen<string>(
      `neko-session://line/${agentSessionId}`,
      (event) => {
        if (state.lineHandlers.length > 0) {
          for (const handler of state.lineHandlers) handler(event.payload);
          return;
        }
        const frameBytes = new TextEncoder().encode(event.payload).byteLength;
        if (
          state.pendingLines.length >= MAX_PENDING_BOOTSTRAP_FRAMES ||
          state.pendingLineBytes + frameBytes > MAX_PENDING_BOOTSTRAP_BYTES
        ) {
          if (!state.terminalError) {
            state.terminalError =
              "Bootstrap output vượt giới hạn an toàn; Neko đã yêu cầu dừng runtime thay vì giữ dữ liệu vô hạn.";
            state.pendingLines.length = 0;
            state.pendingLineBytes = 0;
            detachStartListeners(state);
            state.overflowCancellation = cancelOverflow();
          }
          return;
        }
        state.pendingLines.push(event.payload);
        state.pendingLineBytes += frameBytes;
      },
    );
    state.unlistenLine = unlistenLine;
    if (state.terminalError) {
      detachStartListeners(state);
      return;
    }
    try {
      const unlistenExit = await listen<unknown>(
        `neko-session://exit/${agentSessionId}`,
        (event) => {
          const notice = isNativeProcessExitNotice(event.payload)
            ? event.payload
            : { exitCode: null, terminationProven: false, terminalStatePersisted: false };
          state.exitObserved = true;
          state.pendingExitCode = notice.exitCode;
          // A leader exit is not proof that its process tree disappeared.
          // Renderer-facing exit is also withheld until native authority has
          // durably recorded the terminal lifecycle fact.
          state.killed = notice.terminationProven && notice.terminalStatePersisted;
          if (state.killed) {
            notifyProvenExit(state);
            queueMicrotask(() => detachStartListeners(state));
          }
        },
      );
      state.unlistenExit = unlistenExit;
      if (state.terminalError) detachStartListeners(state);
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

function isUnknownStartOutcome(error: string): boolean {
  return error.startsWith("unknown_outcome:");
}

function isRecordedStartFailure(error: unknown): boolean {
  return typeof error === "string" && (
    error.startsWith("recorded session start failed:") ||
    error.startsWith("decode recorded session start failed:")
  );
}

function isDetectedProvider(value: unknown): value is NekoDetectedProvider {
  if (!value || typeof value !== "object") return false;
  const provider = value as Record<string, unknown>;
  const availability = provider.availability;
  return (
    typeof provider.id === "string" &&
    typeof provider.name === "string" &&
    (provider.version === null || typeof provider.version === "string") &&
    typeof provider.found === "boolean" &&
    ["available", "not_installed", "host_unsupported"].includes(availability as string) &&
    (provider.found === (availability === "available")) &&
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

function isNativeProcessExitNotice(value: unknown): value is NativeProcessExitNotice {
  if (!value || typeof value !== "object") return false;
  const notice = value as Record<string, unknown>;
  return (
    (notice.exitCode === null || typeof notice.exitCode === "number") &&
    typeof notice.terminationProven === "boolean" &&
    typeof notice.terminalStatePersisted === "boolean"
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

function isNativeSessionCancelResult(value: unknown): value is NativeSessionCancelResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return typeof result.agentSessionId === "string" && typeof result.cancelled === "boolean";
}

function isNativeOutcomeUncertain(session: NekoNativeSessionRecord): boolean {
  return (
    session.state === "unknown_outcome" ||
    session.operationPhase === "unknown_outcome" ||
    session.continuity === "unknown_outcome"
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
