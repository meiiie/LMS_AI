/**
 * Neko Chill session store (T302, FR-005/FR-007) — sessions, transcript
 * streaming, turn lifecycle.
 *
 * Consumes ONLY the normalized DriverEvent union and appends blocks in the
 * cloud transcript's ContentBlock vocabulary so the shared rendering stack
 * applies unchanged. Mirrors the cloud chat store's immer streaming
 * discipline WITHOUT importing it (audit: chat-store is a do-not-touch
 * monolith). Live Driver instances stay OUTSIDE zustand state (not
 * serializable); persistence arrives in Phase 5.
 */
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { v4 as uuidv4 } from "uuid";
import type { AnswerBlockData, ContentBlock, ThinkingBlockData, ToolExecutionBlockData } from "@/api/types";
import type {
  Driver,
  DriverActivity,
  DriverCommand,
  DriverConfigOption,
  DriverEvent,
  PermissionRequest,
} from "../drivers/types";
import type { AgentLaunchProfile, DetectedAgent } from "./neko-agent-store";
import { useNekoAgentStore } from "./neko-agent-store";
import { isAbsoluteWorkspacePath, workspaceFromPath, type WorkspaceRef } from "../workspace";
import {
  deletePersistedSession,
  loadSessionIndex,
  loadSessionSnapshot,
  persistSessionDebounced,
  persistSessionBeforeDispatch,
  persistSessionNow,
  persistSessionStrict,
} from "../persistence";
import { appendSessionEvent, type NekoSessionEvent, type NekoSessionEventData } from "../session-events";
import {
  RuntimeRegistry,
  type RuntimeDisposalResult,
  type RuntimeProviderSnapshot,
} from "../runtime-manager";

export interface NekoMessage {
  id: string;
  role: "user" | "assistant";
  /** Plain text for user messages. */
  text?: string;
  /** Streamed blocks for assistant messages (ContentBlock vocabulary). */
  blocks?: ContentBlock[];
}

export type NekoSessionStatus = "connecting" | "stopping" | "dispatching" | "idle" | "streaming" | "exited" | "error";

export interface NekoSession {
  id: string;
  agentId: string;
  agentName: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  /** Exact ACP cwd. Legacy v1 sessions hydrate with null until attached. */
  workspace: WorkspaceRef | null;
  /** Neko's config-first launch choice; null for other agents/default launch. */
  launchProfile: AgentLaunchProfile | null;
  /** Last complete capability snapshot reported by the live driver. */
  controls: DriverConfigOption[];
  commands: DriverCommand[];
  pendingControlId: string | null;
  /** Last user/agent activity — drives the 30-minute idle reap (T601). */
  lastActivityAt: number;
  status: NekoSessionStatus;
  messages: NekoMessage[];
  /** Durable, append-only facts at Wiii's model/runtime boundary. */
  events: NekoSessionEvent[];
  /** Highest sequence ever allocated, including rolled-back staged facts. */
  eventHighWaterMark: number;
  /** Current provider identity; null for a restored or stopped session. */
  runtime: RuntimeProviderSnapshot | null;
  /** Set while the agent waits on an approval (FR-006); UI must resolve it. */
  pendingPermission: PermissionRequest | null;
  /** Prevents two UI decisions from racing across the durability barrier. */
  resolvingPermissionId: string | null;
  /** True while a cancel command crosses its durability barrier. */
  cancelPending: boolean;
  /** Lifecycle lock held through runtime teardown and terminal persistence. */
  closePending: boolean;
  /** Lifecycle lock held from delete intent through durable deletion. */
  deletePending: boolean;
  /** Honest error text for the banner when status is error/exited. */
  statusDetail?: string;
}

/** Live runtimes stay outside Zustand but are owned by RuntimeRegistry. */
const runtimes = new RuntimeRegistry();
const closeOperations = new Map<string, Promise<void>>();
const dispatchBarriers = new Map<string, Set<Promise<void>>>();
const runtimeOperations = new Map<string, Set<Promise<void>>>();
let modeExitOperation: Promise<void> | null = null;

function acquireHold(registry: Map<string, Set<Promise<void>>>, sessionId: string): () => void {
  let resolve!: () => void;
  const hold = new Promise<void>((done) => {
    resolve = done;
  });
  const holds = registry.get(sessionId) ?? new Set<Promise<void>>();
  holds.add(hold);
  registry.set(sessionId, holds);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holds.delete(hold);
    if (holds.size === 0) registry.delete(sessionId);
    resolve();
  };
}

async function waitForHolds(registry: Map<string, Set<Promise<void>>>, sessionId: string): Promise<void> {
  while (registry.get(sessionId)?.size) {
    await Promise.allSettled([...(registry.get(sessionId) ?? [])]);
  }
}

/** Injected so tests can fake the driver without Tauri (vi.mock factory). */
type DriverFactory = (
  agent: DetectedAgent,
  sessionId: string,
  launch: { workspace: WorkspaceRef; profileId?: string },
  onEvent: (event: DriverEvent) => void,
  ownDriver: (driver: Driver) => void,
) => Promise<Driver>;

async function defaultDriverFactory(
  agent: DetectedAgent,
  sessionId: string,
  launch: { workspace: WorkspaceRef; profileId?: string },
  onEvent: (event: DriverEvent) => void,
  ownDriver: (driver: Driver) => void,
): Promise<Driver> {
  const { createDriverForAgent } = await import("../drivers/factory");
  return createDriverForAgent(agent, sessionId, launch, onEvent, ownDriver);
}

interface NekoSessionState {
  sessions: Record<string, NekoSession>;
  activeSessionId: string | null;
  hydrated: boolean;
  hydrating: boolean;
  hydrationError: string | null;
  /** Load persisted sessions from local storage (T502, FR-008). */
  hydrate: () => Promise<void>;
  createSession: (
    agent: DetectedAgent,
    workspace: WorkspaceRef,
    launchProfile?: AgentLaunchProfile | null,
  ) => Promise<string>;
  /** One-time migration path for a legacy transcript with no workspace. */
  attachWorkspace: (sessionId: string, workspace: WorkspaceRef) => Promise<void>;
  sendPrompt: (text: string) => Promise<void>;
  cancelTurn: () => Promise<void>;
  resolvePermission: (optionId: string | null) => Promise<void>;
  setConfigOption: (optionId: string, value: string | boolean) => Promise<void>;
  /** End the live agent process but KEEP the transcript (persisted). */
  closeSession: (sessionId: string) => Promise<void>;
  /** Remove a session from state AND local storage. */
  deleteSession: (sessionId: string) => Promise<void>;
  setActiveSession: (sessionId: string | null) => void;
  /** DriverEvent intake — exported on the store for direct unit testing. */
  handleEvent: (event: DriverEvent) => void;
}

function lastBlock(message: NekoMessage): ContentBlock | undefined {
  return message.blocks?.[message.blocks.length - 1];
}

/** The streaming assistant message of a session (last message when open). */
function openAssistant(session: NekoSession): NekoMessage | undefined {
  const last = session.messages[session.messages.length - 1];
  return last?.role === "assistant" ? last : undefined;
}

function toToolBlock(activity: DriverActivity): ToolExecutionBlockData {
  return {
    type: "tool_execution",
    id: activity.id,
    tool: {
      id: activity.id,
      name: activity.title,
      result: activity.detail,
    },
    // ContentBlock's tool status is binary; running states stay "pending",
    // every terminal state (completed/failed/cancelled) renders "completed"
    // with the outcome carried in tool.result.
    status: activity.status === "pending" || activity.status === "in_progress" ? "pending" : "completed",
  };
}

/** Rebuild effective session-control values from the durable transition log. */
function projectControls(controls: DriverConfigOption[], events: NekoSessionEvent[]): DriverConfigOption[] {
  const projected = controls.map((option) => ({
    ...option,
    choices: option.choices?.map((choice) => ({ ...choice })),
  }));
  // Index controls are the latest provider-reported baseline. Historical
  // commits from an earlier process must never override a fresh provider's
  // defaults, so replay only the current provider epoch.
  let epochStart = 0;
  for (const [eventIndex, event] of events.entries()) {
    if (event.data.type === "runtime-attached") epochStart = eventIndex + 1;
  }
  for (const event of events.slice(epochStart)) {
    const transition = event.data;
    if (transition.type !== "control-change") continue;
    const value =
      transition.phase === "committed"
        ? transition.nextValue
        : transition.phase === "rolled-back"
          ? transition.previousValue
          : null;
    if (value === null) continue;
    const option = projected.find((candidate) => candidate.id === transition.optionId);
    if (option) option.currentValue = value;
  }
  return projected;
}

function appendOwnedSessionEvent(
  session: NekoSession,
  visibility: NekoSessionEvent["visibility"],
  data: NekoSessionEventData,
  at?: number,
): NekoSessionEvent {
  const event = appendSessionEvent(
    session.events as NekoSessionEvent[],
    visibility,
    data,
    at,
    session.eventHighWaterMark,
  );
  session.eventHighWaterMark = event.seq;
  return event;
}

function removeEventById(events: NekoSessionEvent[], eventId: string | null): void {
  if (eventId === null) return;
  const eventIndex = events.findIndex((event) => event.eventId === eventId);
  if (eventIndex < 0) return;
  events.splice(eventIndex, 1);
}

function projectAuthoritativeMessages(
  messages: NekoMessage[],
  events: NekoSessionEvent[],
): NekoMessage[] {
  const stagedPrompts = new Map(
    events.flatMap((event) =>
      event.eventId &&
      event.data.type === "model-input" &&
      event.data.delivery === "staged"
        ? [[event.eventId, event] as const]
        : []),
  );
  const invokedEventIds = new Set<string>();
  for (const event of events) {
    if (event.data.type !== "dispatch-invoked" || event.data.action !== "prompt") continue;
    const target = stagedPrompts.get(event.data.targetEventId);
    if (
      target &&
      event.seq > target.seq &&
      target.data.type === "model-input" &&
      event.data.providerInstanceId === target.data.providerInstanceId
    ) {
      invokedEventIds.add(event.data.targetEventId);
    }
  }
  const stagedMessageIds = new Set(
    events.flatMap((event) =>
      event.data.type === "model-input" &&
      event.data.delivery === "staged" &&
      (!event.eventId || !invokedEventIds.has(event.eventId))
        ? [event.data.messageId]
        : []),
  );
  if (stagedMessageIds.size === 0) return messages;
  return messages.filter((message) => !stagedMessageIds.has(message.id));
}

export const useNekoSessionStore = create<NekoSessionState>()(
  immer((set, get) => ({
    sessions: {},
    activeSessionId: null,
    hydrated: false,
    hydrating: false,
    hydrationError: null,

    hydrate: async () => {
      if (get().hydrated || get().hydrating) return;
      set((state) => {
        state.hydrating = true;
        state.hydrationError = null;
      });
      const migratedIds: string[] = [];
      try {
        let index: Awaited<ReturnType<typeof loadSessionIndex>>;
        try {
          index = await loadSessionIndex();
        } catch (error) {
          set((state) => {
            state.hydrating = false;
            state.hydrationError = error instanceof Error ? error.message : String(error);
          });
          return;
        }
        const restored: Record<string, NekoSession> = {};
        for (const entry of index) {
          // Live sessions in state win over their persisted snapshot.
          if (get().sessions[entry.id]) continue;
          let snapshot: Awaited<ReturnType<typeof loadSessionSnapshot>>;
          try {
            snapshot = await loadSessionSnapshot(entry.id);
          } catch (error) {
            set((state) => {
              state.hydrating = false;
              state.hydrationError = error instanceof Error ? error.message : String(error);
            });
            return;
          }
          const events = [...snapshot.events];
          const needsMigration = snapshot.needsEventMigration || events.length === 0;
          if (needsMigration) {
            appendSessionEvent(
              events,
              "model",
              {
                type: "session-context",
                source: "legacy-migration",
                agentId: entry.agentId,
                workspacePath: entry.workspace?.path ?? null,
                launchProfileId: entry.launchProfile?.id ?? null,
              },
              entry.createdAt,
            );
            for (const [messageIndex, message] of snapshot.messages.entries()) {
              if (message.role !== "user" || typeof message.text !== "string") continue;
              appendSessionEvent(
                events,
                "model",
                {
                  type: "model-input",
                  source: "legacy-migration",
                  messageId: message.id,
                  text: message.text,
                  providerInstanceId: null,
                },
                entry.createdAt + messageIndex + 1,
              );
            }
            migratedIds.push(entry.id);
          }
          const eventHighWaterMark = Math.max(snapshot.eventHighWaterMark, events[events.length - 1]?.seq ?? 0);
          const messages = projectAuthoritativeMessages(snapshot.messages, events);
          const droppedStagedMessages = messages.length !== snapshot.messages.length;
          const latestContext = [...events].reverse().find((event) => event.data.type === "session-context");
          const contextData = latestContext?.data.type === "session-context" ? latestContext.data : null;
          const workspace = contextData
            ? contextData.workspacePath === null
              ? null
              : entry.workspace?.path === contextData.workspacePath
                ? entry.workspace
                : workspaceFromPath(contextData.workspacePath)
            : (entry.workspace ?? null);
          const launchProfile = contextData
            ? contextData.launchProfileId === null
              ? null
              : entry.launchProfile?.id === contextData.launchProfileId
                ? entry.launchProfile
                : {
                    id: contextData.launchProfileId,
                    provider: "legacy",
                    model: null,
                    active: true,
                  }
            : (entry.launchProfile ?? null);
          restored[entry.id] = {
            id: entry.id,
            agentId: entry.agentId,
            agentName: entry.agentName,
            title: droppedStagedMessages && messages.length === 0
              ? `Phiên với ${entry.agentName}`
              : entry.title,
            createdAt: entry.createdAt,
            updatedAt: entry.updatedAt,
            workspace,
            launchProfile,
            controls: projectControls(entry.controls ?? [], events),
            commands: entry.commands ?? [],
            pendingControlId: null,
            lastActivityAt: entry.updatedAt,
            status: needsMigration ? "connecting" : "exited",
            messages,
            events,
            eventHighWaterMark,
            runtime: null,
            pendingPermission: null,
            resolvingPermissionId: null,
            cancelPending: false,
            closePending: false,
            deletePending: false,
            statusDetail: needsMigration
              ? "Đang nâng cấp log phiên trước khi có thể khởi động lại agent…"
              : droppedStagedMessages
                ? "Đã bỏ qua prompt chưa xác nhận gửi sau lần thoát trước."
                : "Phiên đã lưu — nhắn tiếp để khởi động lại agent.",
          };
        }
        set((state) => {
          state.sessions = { ...restored, ...state.sessions };
          state.hydrated = true;
          state.hydrating = false;
          state.hydrationError = null;
        });
      } catch (error) {
        // No parser/projection bug may strand the shell in its loading state.
        set((state) => {
          state.hydrated = false;
          state.hydrating = false;
          state.hydrationError = error instanceof Error ? error.message : String(error);
        });
        return;
      }
      for (const sessionId of migratedIds) {
        const session = get().sessions[sessionId];
        if (!session) continue;
        try {
          // A migrated boundary log is not usable until the upgraded snapshot
          // is durable. Restored sessions must not respawn through this gate.
          await persistSessionStrict(session);
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current || current.runtime || current.status !== "connecting") return;
            current.status = "exited";
            current.statusDetail = "Phiên đã lưu — nhắn tiếp để khởi động lại agent.";
          });
        } catch (error) {
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current || current.runtime) return;
            current.status = "error";
            current.statusDetail = `Không thể lưu bản nâng cấp log phiên: ${error instanceof Error ? error.message : String(error)}`;
          });
        }
      }
    },

    createSession: async (agent, workspace, launchProfile = null) => {
      const activeModeExit = modeExitOperation;
      if (activeModeExit) await activeModeExit;
      if (!workspace || !isAbsoluteWorkspacePath(workspace.path)) {
        throw new Error("Hãy chọn một thư mục dự án tuyệt đối trước khi bắt đầu.");
      }
      const sessionId = uuidv4();
      const now = Date.now();
      const events: NekoSessionEvent[] = [];
      appendSessionEvent(
        events,
        "model",
        {
          type: "session-context",
          source: "created",
          agentId: agent.id,
          workspacePath: workspace.path,
          launchProfileId: launchProfile?.id ?? null,
        },
        now,
      );
      set((state) => {
        state.sessions[sessionId] = {
          id: sessionId,
          agentId: agent.id,
          agentName: agent.name,
          title: `Phiên với ${agent.name}`,
          createdAt: now,
          updatedAt: now,
          workspace,
          launchProfile,
          controls: [],
          commands: [],
          pendingControlId: null,
          lastActivityAt: now,
          status: "connecting",
          messages: [],
          events,
          eventHighWaterMark: events[events.length - 1]?.seq ?? 0,
          runtime: null,
          pendingPermission: null,
          resolvingPermissionId: null,
          cancelPending: false,
          closePending: false,
          deletePending: false,
        };
        state.activeSessionId = sessionId;
      });
      try {
        // The workspace/profile can affect the provider before the first
        // prompt, so its event must be durable before driver.start().
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
        if (get().sessions[sessionId]?.status !== "connecting") return sessionId;
        const factory: DriverFactory =
          (get() as unknown as { _driverFactory?: DriverFactory })._driverFactory ?? defaultDriverFactory;
        const pendingEvents: DriverEvent[] = [];
        let preparingRuntime = true;
        const replacement = await runtimes.replace(sessionId, agent.id, (instanceId, ownDriver) =>
          factory(
            agent,
            sessionId,
            {
              workspace,
              ...(launchProfile?.id ? { profileId: launchProfile.id } : {}),
            },
            (event) => {
              if (runtimes.isCurrent(sessionId, instanceId)) get().handleEvent(event);
              else if (preparingRuntime) pendingEvents.push(event);
            },
            ownDriver,
          ),
        );
        preparingRuntime = false;
        set((state) => {
          const session = state.sessions[sessionId];
          if (!session) return;
          session.runtime = replacement.current;
          appendOwnedSessionEvent(session, "runtime", {
            type: "runtime-attached",
            provider: replacement.current,
          });
          if (session.status === "connecting") session.status = "idle";
          if (replacement.cleanupError) {
            session.statusDetail = "Runtime mới đã chạy nhưng runtime cũ không đóng sạch.";
          }
        });
        for (const event of pendingEvents) {
          if (runtimes.isCurrent(sessionId, replacement.current.instanceId)) {
            get().handleEvent(event);
          }
        }
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        set((state) => {
          const session = state.sessions[sessionId];
          if (session?.status === "connecting") {
            session.status = "error";
            session.statusDetail = reason;
            appendOwnedSessionEvent(session, "runtime", {
              type: "runtime-attach-failed",
              providerId: agent.id,
              reason,
            });
          }
        });
      }
      await persistSessionNowOrReport(sessionId, "trạng thái khởi động runtime");
      return sessionId;
    },

    attachWorkspace: async (sessionId, workspace) => {
      if (!workspace || !isAbsoluteWorkspacePath(workspace.path)) return;
      const activeModeExit = modeExitOperation;
      if (activeModeExit) await activeModeExit;
      const current = get().sessions[sessionId];
      if (!current || current.workspace || current.closePending || current.deletePending) return;
      const releaseOperation = acquireHold(runtimeOperations, sessionId);
      try {
        set((state) => {
          const session = state.sessions[sessionId];
          if (session && !session.workspace) session.status = "connecting";
        });
        const provider = runtimes.get(sessionId);
        const disposeError = await runtimes.detach(sessionId).then(
          () => null,
          (error) => error,
        );
        set((state) => {
          const session = state.sessions[sessionId];
          if (!session || session.workspace) return;
          session.workspace = workspace;
          session.runtime = null;
          if (provider) {
            appendOwnedSessionEvent(session, "runtime", {
              type: "runtime-detached",
              providerId: provider.providerId,
              instanceId: provider.instanceId,
              kind: provider.kind,
              reason: "workspace-change",
            });
          }
          appendOwnedSessionEvent(session, "model", {
            type: "session-context",
            source: "workspace-attached",
            agentId: session.agentId,
            workspacePath: workspace.path,
            launchProfileId: session.launchProfile?.id ?? null,
          });
          session.status = "exited";
          session.statusDetail = "Đã gắn dự án. Lượt tiếp theo sẽ khởi động một runtime mới trong thư mục này.";
          if (disposeError) {
            session.statusDetail = "Đã gắn dự án nhưng runtime cũ không đóng sạch.";
          }
          session.updatedAt = Date.now();
          session.lastActivityAt = session.updatedAt;
        });
        const updated = get().sessions[sessionId];
        if (updated) {
          try {
            await persistSessionBeforeDispatch(updated);
          } catch (error) {
            set((state) => {
              const session = state.sessions[sessionId];
              if (session) {
                session.status = "error";
                session.statusDetail = `Không thể lưu ngữ cảnh dự án: ${error instanceof Error ? error.message : String(error)}`;
              }
            });
          }
        }
      } finally {
        releaseOperation();
      }
    },

    sendPrompt: async (text) => {
      const activeModeExit = modeExitOperation;
      if (activeModeExit) await activeModeExit;
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      // "exited" accepts a new prompt: a restored (or crashed) session
      // respawns a FRESH agent process (spec US3-2 / edge case restart).
      if (
        !session ||
        (session.status !== "idle" && session.status !== "exited") ||
        session.pendingControlId ||
        session.pendingPermission ||
        session.resolvingPermissionId ||
        session.closePending ||
        session.deletePending
      ) {
        return;
      }
      if (!session.workspace) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) {
            current.statusDetail = "Hãy gắn một thư mục dự án trước khi nhắn tiếp.";
          }
        });
        return;
      }

      const releaseOperation = acquireHold(runtimeOperations, sessionId);
      try {
        let provider = runtimes.get(sessionId);
        if (!provider) {
          set((state) => {
            const current = state.sessions[sessionId];
            if (current) current.status = "connecting";
          });
          const agentStore = useNekoAgentStore.getState();
          if (agentStore.agents.length === 0) await agentStore.detect();
          const agent = useNekoAgentStore.getState().agents.find((a) => a.id === session.agentId);
          if (!agent?.found) {
            set((state) => {
              const s = state.sessions[sessionId];
              if (s?.status === "connecting") {
                s.status = "error";
                s.statusDetail = `Không tìm thấy agent "${session.agentName}" trên máy này.`;
              }
            });
            return;
          }
          try {
            const factory: DriverFactory =
              (get() as unknown as { _driverFactory?: DriverFactory })._driverFactory ?? defaultDriverFactory;
            if (get().sessions[sessionId]?.status !== "connecting") return;
            const pendingEvents: DriverEvent[] = [];
            let preparingRuntime = true;
            const replacement = await runtimes.replace(sessionId, agent.id, (instanceId, ownDriver) =>
              factory(
                agent,
                sessionId,
                {
                  workspace: session.workspace!,
                  ...(session.launchProfile?.id ? { profileId: session.launchProfile.id } : {}),
                },
                (event) => {
                  if (runtimes.isCurrent(sessionId, instanceId)) get().handleEvent(event);
                  else if (preparingRuntime) pendingEvents.push(event);
                },
                ownDriver,
              ),
            );
            preparingRuntime = false;
            provider = replacement.current;
            set((state) => {
              const s = state.sessions[sessionId];
              if (s) {
                s.runtime = replacement.current;
                appendOwnedSessionEvent(s, "runtime", {
                  type: "runtime-attached",
                  provider: replacement.current,
                });
                s.status = "idle";
                s.statusDetail = undefined;
              }
            });
            for (const event of pendingEvents) {
              if (runtimes.isCurrent(sessionId, replacement.current.instanceId)) {
                get().handleEvent(event);
              }
            }
          } catch (err) {
            const reason = err instanceof Error ? err.message : String(err);
            set((state) => {
              const s = state.sessions[sessionId];
              if (s?.status === "connecting") {
                s.status = "error";
                s.statusDetail = reason;
                appendOwnedSessionEvent(s, "runtime", {
                  type: "runtime-attach-failed",
                  providerId: s.agentId,
                  reason,
                });
              }
            });
            await persistSessionNowOrReport(sessionId, "lỗi khởi động runtime");
            return;
          }
        }

        if (!provider) return;
        const providerInstanceId = provider.instanceId;
        const messageId = uuidv4();
        const previousTitle = get().sessions[sessionId]?.title;
        let inputEventId: string | null = null;
        set((state) => {
          const s = state.sessions[sessionId];
          if (!s) return;
          s.messages.push({ id: messageId, role: "user", text });
          inputEventId = appendOwnedSessionEvent(s, "model", {
            type: "model-input",
            source: "live",
            messageId,
            text,
            providerInstanceId,
            delivery: "staged",
          }).eventId!;
          // Acquire the turn synchronously. No second composer submission may
          // pass while the first prompt waits for its durability barrier.
          s.status = "dispatching";
          s.lastActivityAt = Date.now();
          s.updatedAt = s.lastActivityAt;
          if (s.messages.length === 1) {
            s.title = text.length > 48 ? `${text.slice(0, 48)}…` : text;
          }
        });
        const updated = get().sessions[sessionId];
        if (!updated) return;
        const releaseDispatchBarrier = acquireHold(dispatchBarriers, sessionId);
        try {
          // Hard barrier: the provider cannot observe this prompt before the
          // exact model input is durable in the append-only log.
          await persistSessionBeforeDispatch(updated);
        } catch (error) {
          set((state) => {
            const current = state.sessions[sessionId];
            if (current) {
              current.messages = current.messages.filter((message) => message.id !== messageId);
              removeEventById(current.events as NekoSessionEvent[], inputEventId);
              if (current.messages.length === 0 && previousTitle) {
                current.title = previousTitle;
              }
              if (current.status === "dispatching") current.status = "idle";
              current.statusDetail = `Không thể lưu prompt nên chưa gửi cho agent: ${error instanceof Error ? error.message : String(error)}`;
            }
          });
          return;
        } finally {
          releaseDispatchBarrier();
        }
        // turn-started from the driver flips status + opens the assistant
        // message; prompt() resolves only when the whole turn ends.
        let promptStarted = false;
        try {
          const driver = runtimes.requireInstance(sessionId, providerInstanceId, "prompt");
          const invocation = driver.prompt(text);
          promptStarted = true;
          set((state) => {
            const current = state.sessions[sessionId];
            if (current && inputEventId) {
              appendOwnedSessionEvent(current, "model", {
                type: "dispatch-invoked",
                targetEventId: inputEventId,
                action: "prompt",
                providerInstanceId,
              });
            }
          });
          const persistInvocation = persistSessionNowOrReport(sessionId, "xác nhận dispatch prompt", {
            strict: true,
          });
          let invocationPersisted = false;
          let invocationFailed = false;
          let invocationError: unknown;
          try {
            await invocation;
          } catch (error) {
            invocationFailed = true;
            invocationError = error;
          } finally {
            invocationPersisted = await persistInvocation;
          }
          if (!invocationPersisted) {
            await revokeRuntimeAfterDurabilityFailure(sessionId, provider);
            return;
          }
          if (invocationFailed) throw invocationError;
          set((state) => {
            const current = state.sessions[sessionId];
            // Some drivers only resolve prompt() and do not emit lifecycle
            // events. Release the local dispatch lock in that valid case.
            if (current?.status === "dispatching") current.status = "idle";
          });
        } catch (error) {
          let rolledBackUndispatchedInput = false;
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current) return;
            if (!promptStarted) {
              current.messages = current.messages.filter((message) => message.id !== messageId);
              removeEventById(current.events as NekoSessionEvent[], inputEventId);
              if (current.messages.length === 0 && previousTitle) {
                current.title = previousTitle;
              }
              rolledBackUndispatchedInput = true;
            }
            if (current?.status === "dispatching") {
              current.status = promptStarted ? "error" : "idle";
              current.statusDetail = error instanceof Error ? error.message : String(error);
            }
          });
          if (rolledBackUndispatchedInput) {
            await persistSessionNowOrReport(sessionId, "rollback prompt chưa gửi", {
              fatal: true,
              strict: true,
            });
          }
        }
      } finally {
        releaseOperation();
      }
    },

    cancelTurn: async () => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const provider = runtimes.get(sessionId);
      const session = get().sessions[sessionId];
      if (
        !provider ||
        !session ||
        session.cancelPending ||
        session.resolvingPermissionId ||
        session.closePending ||
        session.deletePending
      )
        return;
      const releaseOperation = acquireHold(runtimeOperations, sessionId);
      try {
        let commandEventId: string | null = null;
        set((state) => {
          const session = state.sessions[sessionId];
          if (session) {
            session.cancelPending = true;
            commandEventId = appendOwnedSessionEvent(session, "model", {
              type: "runtime-command",
              action: "cancel",
              providerInstanceId: provider.instanceId,
              delivery: "staged",
            }).eventId!;
          }
        });
        const session = get().sessions[sessionId];
        if (!session) return;
        const releaseDispatchBarrier = acquireHold(dispatchBarriers, sessionId);
        try {
          await persistSessionBeforeDispatch(session);
        } catch (error) {
          set((state) => {
            const current = state.sessions[sessionId];
            if (current) {
              removeEventById(current.events as NekoSessionEvent[], commandEventId);
              current.cancelPending = false;
              current.statusDetail = error instanceof Error ? error.message : String(error);
            }
          });
          return;
        } finally {
          releaseDispatchBarrier();
        }
        let cancelStarted = false;
        try {
          const driver = runtimes.requireInstance(sessionId, provider.instanceId, "cancel");
          const invocation = driver.cancel();
          cancelStarted = true;
          set((state) => {
            const current = state.sessions[sessionId];
            if (current && commandEventId) {
              appendOwnedSessionEvent(current, "model", {
                type: "dispatch-invoked",
                targetEventId: commandEventId,
                action: "cancel",
                providerInstanceId: provider.instanceId,
              });
            }
          });
          const persistInvocation = persistSessionNowOrReport(sessionId, "xác nhận dispatch yêu cầu dừng", {
            strict: true,
          });
          let invocationPersisted = false;
          let invocationFailed = false;
          let invocationError: unknown;
          try {
            await invocation;
          } catch (error) {
            invocationFailed = true;
            invocationError = error;
          } finally {
            invocationPersisted = await persistInvocation;
          }
          if (!invocationPersisted) {
            await revokeRuntimeAfterDurabilityFailure(sessionId, provider);
            return;
          }
          if (invocationFailed) throw invocationError;
        } catch (error) {
          let rolledBackUndispatchedCancel = false;
          set((state) => {
            const current = state.sessions[sessionId];
            if (current) {
              if (!cancelStarted) {
                removeEventById(current.events as NekoSessionEvent[], commandEventId);
                rolledBackUndispatchedCancel = true;
              }
              if (current.status !== "stopping" && current.status !== "exited") {
                current.statusDetail = error instanceof Error ? error.message : String(error);
              }
            }
          });
          if (rolledBackUndispatchedCancel) {
            await persistSessionNowOrReport(sessionId, "rollback yêu cầu dừng chưa gửi", {
              fatal: true,
              strict: true,
            });
          }
        }
      } finally {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) current.cancelPending = false;
        });
        releaseOperation();
      }
    },

    resolvePermission: async (optionId) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      const request = session?.pendingPermission;
      if (
        !request ||
        session?.resolvingPermissionId ||
        session.cancelPending ||
        session.closePending ||
        session.deletePending
      )
        return;
      const provider = runtimes.get(sessionId);
      if (!provider) return;
      const releaseOperation = acquireHold(runtimeOperations, sessionId);
      let decisionEventId: string | null = null;
      let decisionPersisted = false;
      let resolutionStarted = false;
      set((state) => {
        const s = state.sessions[sessionId];
        if (s?.pendingPermission?.requestId === request.requestId) {
          // Acquire this approval synchronously so a double click cannot
          // append a conflicting decision while persistence is in flight.
          s.resolvingPermissionId = request.requestId;
          decisionEventId = appendOwnedSessionEvent(s, "model", {
            type: "permission-decision",
            requestId: request.requestId,
            optionId,
            providerInstanceId: provider.instanceId,
            delivery: "staged",
          }).eventId!;
        }
      });
      const releaseDispatchBarrier = acquireHold(dispatchBarriers, sessionId);
      try {
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
        decisionPersisted = true;
        releaseDispatchBarrier();
        // Driver fails closed on null/unknown options (FR-006).
        const driver = runtimes.requireInstance(sessionId, provider.instanceId, "permission-resolution");
        const invocation = driver.resolvePermission({ requestId: request.requestId, optionId });
        resolutionStarted = true;
        set((state) => {
          const current = state.sessions[sessionId];
          if (current && decisionEventId) {
            appendOwnedSessionEvent(current, "model", {
              type: "dispatch-invoked",
              targetEventId: decisionEventId,
              action: "permission",
              providerInstanceId: provider.instanceId,
            });
          }
        });
        const persistInvocation = persistSessionNowOrReport(sessionId, "xác nhận dispatch quyết định", {
          strict: true,
        });
        let invocationPersisted = false;
        let invocationFailed = false;
        let invocationError: unknown;
        try {
          await invocation;
        } catch (error) {
          invocationFailed = true;
          invocationError = error;
        } finally {
          invocationPersisted = await persistInvocation;
        }
        set((state) => {
          const s = state.sessions[sessionId];
          if (s?.pendingPermission?.requestId === request.requestId) {
            s.pendingPermission = null;
          }
          if (s?.resolvingPermissionId === request.requestId) {
            s.resolvingPermissionId = null;
          }
        });
        if (!invocationPersisted) {
          await revokeRuntimeAfterDurabilityFailure(sessionId, provider);
          return;
        }
        if (invocationFailed) throw invocationError;
      } catch (error) {
        let rolledBackUndispatchedDecision = false;
        set((state) => {
          const s = state.sessions[sessionId];
          if (s) {
            if (!decisionPersisted || !resolutionStarted) {
              removeEventById(s.events as NekoSessionEvent[], decisionEventId);
              rolledBackUndispatchedDecision = decisionPersisted;
            }
            if (s.resolvingPermissionId === request.requestId) {
              s.resolvingPermissionId = null;
            }
            s.statusDetail = error instanceof Error ? error.message : String(error);
          }
        });
        if (rolledBackUndispatchedDecision) {
          await persistSessionNowOrReport(sessionId, "rollback quyết định chưa gửi", {
            fatal: true,
            strict: true,
          });
        }
      } finally {
        releaseDispatchBarrier();
        releaseOperation();
      }
    },

    setConfigOption: async (optionId, value) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      const option = session?.controls.find((candidate) => candidate.id === optionId);
      if (
        !session ||
        !option ||
        session.status !== "idle" ||
        session.pendingPermission ||
        session.pendingControlId ||
        session.closePending ||
        session.deletePending
      ) {
        return;
      }
      const provider = runtimes.get(sessionId);
      if (!provider) return;
      try {
        runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
      } catch (error) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) current.statusDetail = error instanceof Error ? error.message : String(error);
        });
        return;
      }
      const releaseOperation = acquireHold(runtimeOperations, sessionId);
      try {
        const previousValue = option.currentValue;
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) {
            current.pendingControlId = optionId;
            current.statusDetail = undefined;
            appendOwnedSessionEvent(current, "model", {
              type: "control-change",
              phase: "requested",
              optionId,
              previousValue,
              nextValue: value,
            });
          }
        });
        let driver: Driver;
        let configDispatched = false;
        const releaseControlLock = () => {
          set((state) => {
            const current = state.sessions[sessionId];
            if (current?.pendingControlId === optionId) current.pendingControlId = null;
          });
        };
        try {
          await persistSessionBeforeDispatch(get().sessions[sessionId]);
          driver = runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
          configDispatched = true;
          await driver.setConfigOption(optionId, value);
          // Do not commit a response from a provider that was replaced while
          // its asynchronous configuration call was running.
          runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
        } catch (error) {
          const reason = error instanceof Error ? error.message : String(error);
          let rollbackError: unknown;
          if (configDispatched) {
            try {
              // A rejected request is ambiguous: the provider may have applied
              // the value before its response was lost. Compensate only through
              // the exact provider instance that received the request.
              const rollbackDriver = runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
              await rollbackDriver.setConfigOption(optionId, previousValue);
              runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
            } catch (compensationError) {
              rollbackError = compensationError;
            }
          }
          const rollbackReason = rollbackError instanceof Error ? rollbackError.message : String(rollbackError ?? "");
          const revocation = rollbackError
            ? await detachInstanceForRecovery(sessionId, provider)
            : null;
          set((state) => {
            const current = state.sessions[sessionId];
            if (current) {
              const ownsControlLock = current.pendingControlId === optionId;
              const control = current.controls.find((candidate) => candidate.id === optionId);
              if (!rollbackError && ownsControlLock && control) {
                control.currentValue = previousValue;
              }
              if (revocation) {
                if (current.runtime?.instanceId === revocation.provider.instanceId) {
                  current.runtime = null;
                }
                appendOwnedSessionEvent(current, "runtime", {
                  type: "runtime-detached",
                  providerId: revocation.provider.providerId,
                  instanceId: revocation.provider.instanceId,
                  kind: revocation.provider.kind,
                  reason: "config-uncertain",
                });
              }
              if (ownsControlLock) {
                const lifecycleAlreadyClosed = current.status === "stopping" || current.status === "exited";
                if (rollbackError && revocation) {
                  current.status = revocation.error ? "error" : "exited";
                } else if (rollbackError && !lifecycleAlreadyClosed) {
                  current.status = "error";
                }
                if (!(rollbackError && !revocation && lifecycleAlreadyClosed)) {
                  current.statusDetail = rollbackError
                    ? revocation
                      ? revocation.error
                        ? `Cấu hình không xác định; runtime đã bị thu hồi nhưng cleanup báo lỗi: ${revocation.error instanceof Error ? revocation.error.message : String(revocation.error)}`
                        : `Cấu hình không xác định sau lỗi "${rollbackReason}"; runtime đã được thu hồi. Nhắn tiếp để khởi động một runtime mới.`
                      : `Không thể xác nhận hoặc hoàn tác cấu hình: ${rollbackReason}`
                    : configDispatched
                      ? `Provider báo lỗi; đã hoàn tác cấu hình: ${reason}`
                      : reason;
                }
              }
              appendOwnedSessionEvent(current, "model", {
                type: "control-change",
                phase: rollbackError ? "rollback-failed" : "rolled-back",
                optionId,
                previousValue,
                nextValue: value,
                reason: rollbackError ? `${reason}; compensation: ${rollbackReason}` : reason,
              });
            }
          });
          const terminalPersisted = await persistSessionNowOrReport(sessionId, "trạng thái hoàn tác cấu hình", {
            fatal: true,
            strict: true,
          });
          if (!terminalPersisted) {
            await revokeRuntimeAfterDurabilityFailure(sessionId, provider);
          }
          releaseControlLock();
          return;
        }

        set((state) => {
          const current = state.sessions[sessionId];
          if (!current) return;
          const control = current.controls.find((candidate) => candidate.id === optionId);
          if (control) control.currentValue = value;
          appendOwnedSessionEvent(current, "model", {
            type: "control-change",
            phase: "committed",
            optionId,
            previousValue,
            nextValue: value,
          });
        });
        try {
          await persistSessionBeforeDispatch(get().sessions[sessionId]);
          releaseControlLock();
        } catch (commitError) {
          let rollbackError: unknown;
          try {
            const rollbackDriver = runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
            await rollbackDriver.setConfigOption(optionId, previousValue);
            runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
          } catch (error) {
            rollbackError = error;
          }
          const reason = commitError instanceof Error ? commitError.message : String(commitError);
          const rollbackReason = rollbackError instanceof Error ? rollbackError.message : String(rollbackError ?? "");
          const revocation = rollbackError
            ? await detachInstanceForRecovery(sessionId, provider)
            : null;
          set((state) => {
            const current = state.sessions[sessionId];
            if (!current) return;
            const ownsControlLock = current.pendingControlId === optionId;
            const control = current.controls.find((candidate) => candidate.id === optionId);
            if (!rollbackError && ownsControlLock && control) {
              control.currentValue = previousValue;
            }
            if (revocation) {
              if (current.runtime?.instanceId === revocation.provider.instanceId) {
                current.runtime = null;
              }
              appendOwnedSessionEvent(current, "runtime", {
                type: "runtime-detached",
                providerId: revocation.provider.providerId,
                instanceId: revocation.provider.instanceId,
                kind: revocation.provider.kind,
                reason: "config-uncertain",
              });
            }
            if (ownsControlLock) {
              const lifecycleAlreadyClosed = current.status === "stopping" || current.status === "exited";
              if (rollbackError && revocation) {
                current.status = revocation.error ? "error" : "exited";
              } else if (rollbackError && !lifecycleAlreadyClosed) {
                current.status = "error";
              }
              if (!(rollbackError && !revocation && lifecycleAlreadyClosed)) {
                current.statusDetail = rollbackError
                  ? revocation
                    ? revocation.error
                      ? `Cấu hình không xác định; runtime đã bị thu hồi nhưng cleanup báo lỗi: ${revocation.error instanceof Error ? revocation.error.message : String(revocation.error)}`
                      : `Cấu hình không xác định sau lỗi "${rollbackReason}"; runtime đã được thu hồi. Nhắn tiếp để khởi động một runtime mới.`
                    : `Không thể xác nhận hoặc hoàn tác cấu hình: ${rollbackReason}`
                  : `Không thể lưu cấu hình; đã hoàn tác: ${reason}`;
              }
            }
            appendOwnedSessionEvent(current, "model", {
              type: "control-change",
              phase: rollbackError ? "rollback-failed" : "rolled-back",
              optionId,
              previousValue,
              nextValue: value,
              reason: rollbackError ? `${reason}; compensation: ${rollbackReason}` : reason,
            });
          });
          const terminalPersisted = await persistSessionNowOrReport(sessionId, "trạng thái hoàn tác cấu hình", {
            fatal: true,
            strict: true,
          });
          if (!terminalPersisted) {
            await revokeRuntimeAfterDurabilityFailure(sessionId, provider);
          }
          releaseControlLock();
        }
      } finally {
        releaseOperation();
      }
    },

    closeSession: (sessionId) => {
      const current = get().sessions[sessionId];
      if (!current || current.deletePending) return Promise.resolve();
      if (current.closePending) {
        return closeOperations.get(sessionId) ?? Promise.resolve();
      }
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) {
          session.closePending = true;
          session.status = "stopping";
        }
      });
      const operation = (async () => {
        await waitForHolds(dispatchBarriers, sessionId);
        const provider = runtimes.get(sessionId) ?? get().sessions[sessionId]?.runtime ?? null;
        const disposeError = await runtimes.detach(sessionId).then(
          () => null,
          (error) => error,
        );
        await waitForHolds(runtimeOperations, sessionId);
        set((state) => {
          const session = state.sessions[sessionId];
          if (session) {
            session.runtime = null;
            if (provider) {
              appendOwnedSessionEvent(session, "runtime", {
                type: "runtime-detached",
                providerId: provider.providerId,
                instanceId: provider.instanceId,
                kind: provider.kind,
                reason: "close",
              });
            }
            session.status = "exited";
            session.pendingPermission = null;
            session.resolvingPermissionId = null;
            session.cancelPending = false;
            session.statusDetail = "Đã kết thúc phiên — nhắn tiếp để khởi động lại agent.";
            session.updatedAt = Date.now();
            if (disposeError) {
              session.statusDetail = "Phiên đã đóng nhưng runtime báo lỗi khi thu hồi tài nguyên.";
            }
          }
        });
        await persistSessionNowOrReport(sessionId, "trạng thái đóng phiên");
      })();
      let tracked!: Promise<void>;
      tracked = operation.finally(() => {
        if (closeOperations.get(sessionId) === tracked) {
          set((state) => {
            const session = state.sessions[sessionId];
            if (session) session.closePending = false;
          });
          closeOperations.delete(sessionId);
        }
      });
      closeOperations.set(sessionId, tracked);
      return tracked;
    },

    deleteSession: async (sessionId) => {
      const current = get().sessions[sessionId];
      // Acquire the lifecycle lock before awaiting a close or runtime teardown.
      if (!current || current.deletePending) return;
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) {
          session.deletePending = true;
          session.status = "stopping";
        }
      });
      await closeOperations.get(sessionId)?.catch(() => {});
      await waitForHolds(dispatchBarriers, sessionId);
      await runtimes.detach(sessionId).catch(() => {});
      await waitForHolds(runtimeOperations, sessionId);
      try {
        await deletePersistedSession(sessionId);
      } catch (error) {
        set((state) => {
          const session = state.sessions[sessionId];
          if (!session) return;
          session.runtime = null;
          session.deletePending = false;
          session.status = "error";
          session.statusDetail = `Không thể xóa phiên khỏi bộ nhớ bền: ${error instanceof Error ? error.message : String(error)}`;
        });
        return;
      }
      set((state) => {
        delete state.sessions[sessionId];
        if (state.activeSessionId === sessionId) {
          state.activeSessionId = null;
        }
      });
    },

    setActiveSession: (sessionId) => {
      set((state) => {
        state.activeSessionId = sessionId;
      });
    },

    handleEvent: (event) => {
      const exitingProvider = event.type === "process-exited" ? runtimes.get(event.sessionId) : null;
      set((state) => {
        const session = state.sessions[event.sessionId];
        if (!session) return;
        session.lastActivityAt = Date.now();
        session.updatedAt = session.lastActivityAt;

        switch (event.type) {
          case "session-controls": {
            session.controls = event.controls.map((option) => ({
              ...option,
              choices: option.choices?.map((choice) => ({ ...choice })),
            }));
            return;
          }
          case "available-commands": {
            session.commands = event.commands.map((command) => ({
              ...command,
            }));
            return;
          }
          case "session-info": {
            if (typeof event.title === "string" && event.title.trim()) {
              session.title = event.title.trim().slice(0, 120);
            }
            if (typeof event.updatedAt === "string") {
              const parsed = Date.parse(event.updatedAt);
              if (Number.isFinite(parsed)) {
                session.updatedAt = Math.max(session.updatedAt, parsed);
                session.lastActivityAt = Math.max(session.lastActivityAt, parsed);
              }
            }
            return;
          }
          case "turn-started": {
            session.status = "streaming";
            session.messages.push({
              id: uuidv4(),
              role: "assistant",
              blocks: [],
            });
            return;
          }
          case "reasoning-delta": {
            const message = openAssistant(session);
            if (!message) return;
            const last = lastBlock(message);
            if (last?.type === "thinking" && last.stepState !== "completed") {
              (last as ThinkingBlockData).content += event.text;
            } else {
              message.blocks!.push({
                type: "thinking",
                id: uuidv4(),
                content: event.text,
                toolCalls: [],
                startTime: Date.now(),
              } satisfies ThinkingBlockData);
            }
            return;
          }
          case "answer-delta": {
            const message = openAssistant(session);
            if (!message) return;
            const last = lastBlock(message);
            if (last?.type === "answer") {
              (last as AnswerBlockData).content += event.text;
            } else {
              message.blocks!.push({
                type: "answer",
                id: uuidv4(),
                content: event.text,
              } satisfies AnswerBlockData);
            }
            return;
          }
          case "activity": {
            const message = openAssistant(session);
            if (!message) return;
            const existing = message.blocks!.find(
              (block): block is ToolExecutionBlockData =>
                block.type === "tool_execution" && block.id === event.activity.id,
            );
            const next = toToolBlock(event.activity);
            if (existing) {
              existing.tool = next.tool;
              existing.status = next.status;
            } else {
              message.blocks!.push(next);
            }
            return;
          }
          case "permission-request": {
            session.pendingPermission = event.request;
            session.resolvingPermissionId = null;
            return;
          }
          case "turn-finished": {
            session.status = "idle";
            session.pendingPermission = null;
            session.resolvingPermissionId = null;
            session.cancelPending = false;
            const message = openAssistant(session);
            const last = message ? lastBlock(message) : undefined;
            if (last?.type === "thinking") {
              (last as ThinkingBlockData).endTime = Date.now();
            }
            return;
          }
          case "error": {
            const message = openAssistant(session);
            if (message) {
              message.blocks!.push({
                type: "answer",
                id: uuidv4(),
                content: `⚠️ ${event.message}`,
              } satisfies AnswerBlockData);
            } else {
              session.statusDetail = event.message;
            }
            if (event.fatal) {
              session.status = "error";
              session.statusDetail = event.message;
            }
            return;
          }
          case "process-exited": {
            session.runtime = null;
            if (exitingProvider) {
              appendOwnedSessionEvent(session, "runtime", {
                type: "runtime-detached",
                providerId: exitingProvider.providerId,
                instanceId: exitingProvider.instanceId,
                kind: exitingProvider.kind,
                reason: "process-exit",
              });
            }
            session.status = "exited";
            session.pendingPermission = null;
            session.resolvingPermissionId = null;
            session.cancelPending = false;
            session.statusDetail =
              event.code === 0 || event.code === null ? "Agent đã thoát." : `Agent thoát với mã lỗi ${event.code}.`;
            return;
          }
        }
      });
      // Provider exit is a boundary fact, not ordinary streaming output. Make
      // its detach record immediate so a crash cannot restore a phantom runtime.
      const session = get().sessions[event.sessionId];
      if (session) {
        if (event.type === "process-exited") {
          void persistSessionNowOrReport(event.sessionId, "trạng thái provider đã thoát", {
            strict: true,
          });
        } else {
          persistSessionDebounced(session);
        }
      }
      if (event.type === "process-exited") {
        void runtimes.detach(event.sessionId).catch(() => {});
      }
    },
  })),
);

async function revokeRuntimeAfterDurabilityFailure(
  sessionId: string,
  provider: RuntimeProviderSnapshot,
): Promise<void> {
  const revocation = await detachInstanceForRecovery(sessionId, provider);
  let terminalDetail: string | null = null;
  if (revocation) {
    useNekoSessionStore.setState((state) => {
      const current = state.sessions[sessionId];
      if (!current) return;
      if (current.runtime?.instanceId === revocation.provider.instanceId) {
        current.runtime = null;
      }
      appendOwnedSessionEvent(current, "runtime", {
        type: "runtime-detached",
        providerId: revocation.provider.providerId,
        instanceId: revocation.provider.instanceId,
        kind: revocation.provider.kind,
        reason: "durability-failure",
      });
      if (current.status !== "stopping") {
        current.status = revocation.error ? "error" : "exited";
        terminalDetail = revocation.error
          ? `Không thể lưu kết quả giao dịch; runtime đã bị thu hồi nhưng cleanup báo lỗi: ${revocation.error instanceof Error ? revocation.error.message : String(revocation.error)}`
          : "Không thể lưu kết quả giao dịch; runtime đã được thu hồi. Nhắn tiếp để thử lại khi bộ nhớ bền đã sẵn sàng.";
        current.statusDetail = terminalDetail;
      }
    });
  }
  // The original boundary write may have failed transiently. Retry once with
  // the terminal revocation included; if storage is still unavailable, the
  // earlier durable staged record remains non-authoritative on hydration.
  const terminalPersisted = await persistSessionNowOrReport(sessionId, "trạng thái thu hồi sau lỗi độ bền", {
    fatal: true,
    strict: true,
  });
  if (!terminalPersisted && terminalDetail) {
    useNekoSessionStore.setState((state) => {
      const current = state.sessions[sessionId];
      if (current) {
        current.statusDetail = `${terminalDetail} Bản ghi kết thúc vẫn chưa thể lưu bền.`;
      }
    });
  }
}

async function detachInstanceForRecovery(
  sessionId: string,
  provider: RuntimeProviderSnapshot,
): Promise<RuntimeDisposalResult | null> {
  try {
    return await runtimes.detachInstance(sessionId, provider.instanceId);
  } catch (error) {
    // The provider may already be synchronously revoked while its joined
    // cleanup is still failing. Preserve the captured identity so config
    // recovery can finish its state transition and strict terminal persist.
    return { provider, error };
  }
}

async function persistSessionNowOrReport(
  sessionId: string,
  context: string,
  options: { fatal?: boolean; strict?: boolean } = {},
): Promise<boolean> {
  const session = useNekoSessionStore.getState().sessions[sessionId];
  if (!session) return false;
  try {
    await (options.strict ? persistSessionStrict(session) : persistSessionNow(session));
    return true;
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    useNekoSessionStore.setState((state) => {
      const current = state.sessions[sessionId];
      if (!current) return;
      if (options.fatal && current.status !== "stopping" && current.status !== "exited") {
        current.status = "error";
      }
      current.statusDetail = `Không thể lưu ${context}: ${reason}`;
    });
    return false;
  }
}

// ---------------------------------------------------------------------------
// Idle reap (T601, FR-009 — waku's lesson, reimplemented)
// ---------------------------------------------------------------------------

const IDLE_REAP_MS = 30 * 60 * 1000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;
let reaperTimer: ReturnType<typeof setInterval> | null = null;

/**
 * Dispose runtimes of sessions idle past the threshold. Never touches a
 * streaming turn or an unanswered permission request (the sweep may run
 * while the user reads an approval — reaping there would fail their turn).
 */
export async function sweepIdleSessions(now: number = Date.now()): Promise<void> {
  const { sessions } = useNekoSessionStore.getState();
  for (const session of Object.values(sessions)) {
    if (session.status !== "idle") continue;
    if (session.pendingPermission) continue;
    if (session.pendingControlId) continue;
    if (now - session.lastActivityAt < IDLE_REAP_MS) continue;
    const provider = runtimes.get(session.id);
    if (!provider) continue;
    useNekoSessionStore.setState((state) => {
      const current = state.sessions[session.id];
      if (current?.status === "idle") current.status = "connecting";
    });
    const disposeError = await runtimes.detach(session.id).then(
      () => null,
      (error) => error,
    );
    useNekoSessionStore.setState((state) => {
      const s = state.sessions[session.id];
      if (s && s.status === "connecting") {
        s.runtime = null;
        appendOwnedSessionEvent(
          s,
          "runtime",
          {
            type: "runtime-detached",
            providerId: provider.providerId,
            instanceId: provider.instanceId,
            kind: provider.kind,
            reason: "idle",
          },
          now,
        );
        s.status = "exited";
        s.statusDetail = "Agent tạm nghỉ sau 30 phút yên lặng — nhắn tiếp để khởi động lại.";
        if (disposeError) {
          s.statusDetail = "Runtime hết hạn nhưng báo lỗi khi thu hồi tài nguyên.";
        }
        s.updatedAt = now;
        s.lastActivityAt = now;
      }
    });
    await persistSessionNowOrReport(session.id, "trạng thái runtime hết hạn");
  }
}

/** Start the periodic sweep and return its explicit owner/disposer. */
export function startIdleReaper(): () => void {
  stopIdleReaper();
  reaperTimer = setInterval(() => void sweepIdleSessions(), SWEEP_INTERVAL_MS);
  return stopIdleReaper;
}

export function stopIdleReaper(): void {
  if (!reaperTimer) return;
  clearInterval(reaperTimer);
  reaperTimer = null;
}

/** Mode-exit owner: stop every live runtime and persist detach facts. */
export async function disposeAllNekoRuntimes(): Promise<void> {
  if (modeExitOperation) return modeExitOperation;

  const state = useNekoSessionStore.getState();
  const sessionIds = new Set([
    ...runtimes.ownedSessionIds(),
    ...dispatchBarriers.keys(),
    ...runtimeOperations.keys(),
    ...closeOperations.keys(),
    ...Object.values(state.sessions)
      .filter((session) => session.runtime !== null || session.status === "connecting")
      .map((session) => session.id),
  ]);
  const priorLifecycleOperations = [...sessionIds]
    .map((sessionId) => closeOperations.get(sessionId))
    .filter((operation): operation is Promise<void> => Boolean(operation));

  useNekoSessionStore.setState((draft) => {
    for (const sessionId of sessionIds) {
      const session = draft.sessions[sessionId];
      if (!session || session.deletePending) continue;
      session.closePending = true;
      session.status = "stopping";
    }
  });

  const operation = (async () => {
    await Promise.allSettled(priorLifecycleOperations);
    await Promise.all([...sessionIds].map((sessionId) => waitForHolds(dispatchBarriers, sessionId)));
    const results = await runtimes.disposeAll();
    await Promise.all([...sessionIds].map((sessionId) => waitForHolds(runtimeOperations, sessionId)));

    const resultsBySession = new Map(results.map((result) => [result.sessionId, result] as const));
    const sessionIdsToPersist: string[] = [];
    useNekoSessionStore.setState((draft) => {
      for (const sessionId of sessionIds) {
        const session = draft.sessions[sessionId];
        if (!session || session.deletePending) continue;
        const result = resultsBySession.get(sessionId);
        const provider = result?.provider ?? session.runtime;
        session.runtime = null;
        session.status = "exited";
        session.pendingPermission = null;
        session.resolvingPermissionId = null;
        session.cancelPending = false;
        session.updatedAt = Date.now();
        session.statusDetail = result?.error
          ? "Đã rời Neko Chill nhưng runtime báo lỗi khi thu hồi tài nguyên."
          : "Runtime đã dừng khi rời Neko Chill.";
        if (provider) {
          appendOwnedSessionEvent(session, "runtime", {
            type: "runtime-detached",
            providerId: provider.providerId,
            instanceId: provider.instanceId,
            kind: provider.kind,
            reason: "mode-exit",
          });
        }
        sessionIdsToPersist.push(sessionId);
      }
    });
    await Promise.all(
      sessionIdsToPersist.map(async (sessionId) => {
        await persistSessionNowOrReport(sessionId, "trạng thái rời Neko Chill");
      }),
    );
  })();

  let tracked!: Promise<void>;
  tracked = operation.finally(() => {
    useNekoSessionStore.setState((draft) => {
      for (const sessionId of sessionIds) {
        const session = draft.sessions[sessionId];
        if (session && closeOperations.get(sessionId) === tracked) {
          session.closePending = false;
        }
      }
    });
    for (const sessionId of sessionIds) {
      if (closeOperations.get(sessionId) === tracked) closeOperations.delete(sessionId);
    }
    if (modeExitOperation === tracked) modeExitOperation = null;
  });
  for (const sessionId of sessionIds) closeOperations.set(sessionId, tracked);
  modeExitOperation = tracked;
  return tracked;
}

/** Test hook: swap the driver factory (kept off the public interface). */
export function _setDriverFactoryForTests(factory: DriverFactory | undefined): void {
  useNekoSessionStore.setState({ _driverFactory: factory } as never);
}

/** Test hook: drop live runtimes, simulating an app restart. */
export function _clearLiveDriversForTests(): void {
  runtimes.clearForTests();
  closeOperations.clear();
  dispatchBarriers.clear();
  runtimeOperations.clear();
  modeExitOperation = null;
  stopIdleReaper();
}
