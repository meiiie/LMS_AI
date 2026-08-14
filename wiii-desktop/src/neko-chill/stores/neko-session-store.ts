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
import type {
  AnswerBlockData,
  ContentBlock,
  ThinkingBlockData,
  ToolExecutionBlockData,
} from "@/api/types";
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
import { isAbsoluteWorkspacePath, type WorkspaceRef } from "../workspace";
import {
  deletePersistedSession,
  loadSessionIndex,
  loadSessionSnapshot,
  persistSessionDebounced,
  persistSessionBeforeDispatch,
  persistSessionNow,
} from "../persistence";
import { appendSessionEvent, type NekoSessionEvent } from "../session-events";
import {
  RuntimeRegistry,
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

export type NekoSessionStatus =
  | "connecting"
  | "stopping"
  | "dispatching"
  | "idle"
  | "streaming"
  | "exited"
  | "error";

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
  /** Current provider identity; null for a restored or stopped session. */
  runtime: RuntimeProviderSnapshot | null;
  /** Set while the agent waits on an approval (FR-006); UI must resolve it. */
  pendingPermission: PermissionRequest | null;
  /** Prevents two UI decisions from racing across the durability barrier. */
  resolvingPermissionId: string | null;
  /** Honest error text for the banner when status is error/exited. */
  statusDetail?: string;
}

/** Live runtimes stay outside Zustand but are owned by RuntimeRegistry. */
const runtimes = new RuntimeRegistry();

/** Injected so tests can fake the driver without Tauri (vi.mock factory). */
type DriverFactory = (
  agent: DetectedAgent,
  sessionId: string,
  launch: { workspace: WorkspaceRef; profileId?: string },
  onEvent: (event: DriverEvent) => void,
) => Promise<Driver>;

async function defaultDriverFactory(
  agent: DetectedAgent,
  sessionId: string,
  launch: { workspace: WorkspaceRef; profileId?: string },
  onEvent: (event: DriverEvent) => void,
): Promise<Driver> {
  const { createDriverForAgent } = await import("../drivers/factory");
  return createDriverForAgent(agent, sessionId, launch, onEvent);
}

interface NekoSessionState {
  sessions: Record<string, NekoSession>;
  activeSessionId: string | null;
  hydrated: boolean;
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
    status:
      activity.status === "pending" || activity.status === "in_progress"
        ? "pending"
        : "completed",
  };
}

/** Rebuild effective session-control values from the durable transition log. */
function projectControls(
  controls: DriverConfigOption[],
  events: NekoSessionEvent[],
): DriverConfigOption[] {
  const projected = controls.map((option) => ({
    ...option,
    choices: option.choices?.map((choice) => ({ ...choice })),
  }));
  for (const event of events) {
    const transition = event.data;
    if (transition.type !== "control-change") continue;
    const value = transition.phase === "committed"
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

export const useNekoSessionStore = create<NekoSessionState>()(
  immer((set, get) => ({
    sessions: {},
    activeSessionId: null,
    hydrated: false,

    hydrate: async () => {
      if (get().hydrated) return;
      const index = await loadSessionIndex();
      const restored: Record<string, NekoSession> = {};
      const migratedIds: string[] = [];
      for (const entry of index) {
        // Live sessions in state win over their persisted snapshot.
        if (get().sessions[entry.id]) continue;
        const snapshot = await loadSessionSnapshot(entry.id);
        const events = [...snapshot.events];
        if (snapshot.needsEventMigration || events.length === 0) {
          appendSessionEvent(events, "model", {
            type: "session-context",
            source: "legacy-migration",
            agentId: entry.agentId,
            workspacePath: entry.workspace?.path ?? null,
            launchProfileId: entry.launchProfile?.id ?? null,
          }, entry.createdAt);
          for (const [messageIndex, message] of snapshot.messages.entries()) {
            if (message.role !== "user" || typeof message.text !== "string") continue;
            appendSessionEvent(events, "model", {
              type: "model-input",
              source: "legacy-migration",
              messageId: message.id,
              text: message.text,
              providerInstanceId: null,
            }, entry.createdAt + messageIndex + 1);
          }
          migratedIds.push(entry.id);
        }
        restored[entry.id] = {
          id: entry.id,
          agentId: entry.agentId,
          agentName: entry.agentName,
          title: entry.title,
          createdAt: entry.createdAt,
          updatedAt: entry.updatedAt,
          workspace: entry.workspace ?? null,
          launchProfile: entry.launchProfile ?? null,
          controls: projectControls(entry.controls ?? [], events),
          commands: entry.commands ?? [],
          pendingControlId: null,
          lastActivityAt: entry.updatedAt,
          status: "exited",
          messages: snapshot.messages,
          events,
          runtime: null,
          pendingPermission: null,
          resolvingPermissionId: null,
          statusDetail: "Phiên đã lưu — nhắn tiếp để khởi động lại agent.",
        };
      }
      set((state) => {
        state.sessions = { ...restored, ...state.sessions };
        state.hydrated = true;
      });
      for (const sessionId of migratedIds) {
        await persistSessionNowOrReport(sessionId, "bản nâng cấp log phiên");
      }
    },

    createSession: async (agent, workspace, launchProfile = null) => {
      if (!workspace || !isAbsoluteWorkspacePath(workspace.path)) {
        throw new Error("Hãy chọn một thư mục dự án tuyệt đối trước khi bắt đầu.");
      }
      const sessionId = uuidv4();
      const now = Date.now();
      const events: NekoSessionEvent[] = [];
      appendSessionEvent(events, "model", {
        type: "session-context",
        source: "created",
        agentId: agent.id,
        workspacePath: workspace.path,
        launchProfileId: launchProfile?.id ?? null,
      }, now);
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
          runtime: null,
          pendingPermission: null,
          resolvingPermissionId: null,
        };
        state.activeSessionId = sessionId;
      });
      try {
        // The workspace/profile can affect the provider before the first
        // prompt, so its event must be durable before driver.start().
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
        if (get().sessions[sessionId]?.status !== "connecting") return sessionId;
        const factory: DriverFactory =
          (get() as unknown as { _driverFactory?: DriverFactory })._driverFactory ??
          defaultDriverFactory;
        const pendingEvents: DriverEvent[] = [];
        let preparingRuntime = true;
        const replacement = await runtimes.replace(
          sessionId,
          agent.id,
          (instanceId) => factory(
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
          ),
        );
        preparingRuntime = false;
        set((state) => {
          const session = state.sessions[sessionId];
          if (!session) return;
          session.runtime = replacement.current;
          appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
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
            appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
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
      const current = get().sessions[sessionId];
      if (!current || current.workspace) return;
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
          appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
            type: "runtime-detached",
            providerId: provider.providerId,
            instanceId: provider.instanceId,
            kind: provider.kind,
            reason: "workspace-change",
          });
        }
        appendSessionEvent(session.events as NekoSessionEvent[], "model", {
          type: "session-context",
          source: "workspace-attached",
          agentId: session.agentId,
          workspacePath: workspace.path,
          launchProfileId: session.launchProfile?.id ?? null,
        });
        session.status = "exited";
        session.statusDetail =
          "Đã gắn dự án. Lượt tiếp theo sẽ khởi động một runtime mới trong thư mục này.";
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
    },

    sendPrompt: async (text) => {
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
        session.resolvingPermissionId
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

      let provider = runtimes.get(sessionId);
      if (!provider) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) current.status = "connecting";
        });
        const agentStore = useNekoAgentStore.getState();
        if (agentStore.agents.length === 0) await agentStore.detect();
        const agent = useNekoAgentStore
          .getState()
          .agents.find((a) => a.id === session.agentId);
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
            (get() as unknown as { _driverFactory?: DriverFactory })._driverFactory ??
            defaultDriverFactory;
          if (get().sessions[sessionId]?.status !== "connecting") return;
          const pendingEvents: DriverEvent[] = [];
          let preparingRuntime = true;
          const replacement = await runtimes.replace(
            sessionId,
            agent.id,
            (instanceId) => factory(
              agent,
              sessionId,
              {
                workspace: session.workspace!,
                ...(session.launchProfile?.id
                  ? { profileId: session.launchProfile.id }
                  : {}),
              },
              (event) => {
                if (runtimes.isCurrent(sessionId, instanceId)) get().handleEvent(event);
                else if (preparingRuntime) pendingEvents.push(event);
              },
            ),
          );
          preparingRuntime = false;
          provider = replacement.current;
          set((state) => {
            const s = state.sessions[sessionId];
            if (s) {
              s.runtime = replacement.current;
              appendSessionEvent(s.events as NekoSessionEvent[], "runtime", {
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
            if (s) {
              s.status = "error";
              s.statusDetail = reason;
              appendSessionEvent(s.events as NekoSessionEvent[], "runtime", {
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
      set((state) => {
        const s = state.sessions[sessionId];
        if (!s) return;
        s.messages.push({ id: messageId, role: "user", text });
        appendSessionEvent(s.events as NekoSessionEvent[], "model", {
          type: "model-input",
          source: "live",
          messageId,
          text,
          providerInstanceId,
        });
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
      try {
        // Hard barrier: the provider cannot observe this prompt before the
        // exact model input is durable in the append-only log.
        await persistSessionBeforeDispatch(updated);
      } catch (error) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) {
            if (current.status === "dispatching") current.status = "idle";
            current.statusDetail = `Không thể lưu prompt nên chưa gửi cho agent: ${error instanceof Error ? error.message : String(error)}`;
          }
        });
        return;
      }
      // turn-started from the driver flips status + opens the assistant
      // message; prompt() resolves only when the whole turn ends.
      try {
        await runtimes
          .requireInstance(sessionId, providerInstanceId, "prompt")
          .prompt(text);
        set((state) => {
          const current = state.sessions[sessionId];
          // Some drivers only resolve prompt() and do not emit lifecycle
          // events. Release the local dispatch lock in that valid case.
          if (current?.status === "dispatching") current.status = "idle";
        });
      } catch (error) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current?.status === "dispatching") {
            current.status = "error";
            current.statusDetail = error instanceof Error ? error.message : String(error);
          }
        });
      }
    },

    cancelTurn: async () => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const provider = runtimes.get(sessionId);
      if (!provider) return;
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) {
          appendSessionEvent(session.events as NekoSessionEvent[], "model", {
            type: "runtime-command",
            action: "cancel",
            providerInstanceId: provider.instanceId,
          });
        }
      });
      const session = get().sessions[sessionId];
      if (!session) return;
      try {
        await persistSessionBeforeDispatch(session);
        await runtimes
          .requireInstance(sessionId, provider.instanceId, "cancel")
          .cancel();
      } catch (error) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) current.statusDetail = error instanceof Error ? error.message : String(error);
        });
      }
    },

    resolvePermission: async (optionId) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      const request = session?.pendingPermission;
      if (!request || session?.resolvingPermissionId) return;
      const provider = runtimes.get(sessionId);
      if (!provider) return;
      set((state) => {
        const s = state.sessions[sessionId];
        if (s?.pendingPermission?.requestId === request.requestId) {
          // Acquire this approval synchronously so a double click cannot
          // append a conflicting decision while persistence is in flight.
          s.resolvingPermissionId = request.requestId;
          appendSessionEvent(s.events as NekoSessionEvent[], "model", {
            type: "permission-decision",
            requestId: request.requestId,
            optionId,
            providerInstanceId: provider.instanceId,
          });
        }
      });
      try {
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
        // Driver fails closed on null/unknown options (FR-006).
        await runtimes
          .requireInstance(
            sessionId,
            provider.instanceId,
            "permission-resolution",
          )
          .resolvePermission({ requestId: request.requestId, optionId });
        set((state) => {
          const s = state.sessions[sessionId];
          if (s?.pendingPermission?.requestId === request.requestId) {
            s.pendingPermission = null;
          }
          if (s?.resolvingPermissionId === request.requestId) {
            s.resolvingPermissionId = null;
          }
        });
      } catch (error) {
        set((state) => {
          const s = state.sessions[sessionId];
          if (s) {
            if (s.resolvingPermissionId === request.requestId) {
              s.resolvingPermissionId = null;
            }
            s.statusDetail = error instanceof Error ? error.message : String(error);
          }
        });
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
        session.pendingControlId
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
      const previousValue = option.currentValue;
      set((state) => {
        const current = state.sessions[sessionId];
        if (current) {
          current.pendingControlId = optionId;
          current.statusDetail = undefined;
          appendSessionEvent(current.events as NekoSessionEvent[], "model", {
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
      try {
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
        driver = runtimes.requireInstance(
          sessionId,
          provider.instanceId,
          "session-config",
        );
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
            const rollbackDriver = runtimes.requireInstance(
              sessionId,
              provider.instanceId,
              "session-config",
            );
            await rollbackDriver.setConfigOption(optionId, previousValue);
            runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
          } catch (compensationError) {
            rollbackError = compensationError;
          }
        }
        const rollbackReason = rollbackError instanceof Error
          ? rollbackError.message
          : String(rollbackError ?? "");
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) {
            const control = current.controls.find((candidate) => candidate.id === optionId);
            if (!rollbackError && control) control.currentValue = previousValue;
            current.status = rollbackError ? "error" : current.status;
            current.statusDetail = rollbackError
              ? `Không thể xác nhận hoặc hoàn tác cấu hình: ${rollbackReason}`
              : configDispatched
                ? `Provider báo lỗi; đã hoàn tác cấu hình: ${reason}`
                : reason;
            current.pendingControlId = null;
            appendSessionEvent(current.events as NekoSessionEvent[], "model", {
              type: "control-change",
              phase: rollbackError ? "rollback-failed" : "rolled-back",
              optionId,
              previousValue,
              nextValue: value,
              reason: rollbackError ? `${reason}; compensation: ${rollbackReason}` : reason,
            });
          }
        });
        await persistSessionNowOrReport(sessionId, "trạng thái hoàn tác cấu hình", true);
        return;
      }

      set((state) => {
        const current = state.sessions[sessionId];
        if (!current) return;
        const control = current.controls.find((candidate) => candidate.id === optionId);
        if (control) control.currentValue = value;
        current.pendingControlId = null;
        appendSessionEvent(current.events as NekoSessionEvent[], "model", {
          type: "control-change",
          phase: "committed",
          optionId,
          previousValue,
          nextValue: value,
        });
      });
      try {
        await persistSessionBeforeDispatch(get().sessions[sessionId]);
      } catch (commitError) {
        let rollbackError: unknown;
        try {
          const rollbackDriver = runtimes.requireInstance(
            sessionId,
            provider.instanceId,
            "session-config",
          );
          await rollbackDriver.setConfigOption(optionId, previousValue);
          runtimes.requireInstance(sessionId, provider.instanceId, "session-config");
        } catch (error) {
          rollbackError = error;
        }
        const reason = commitError instanceof Error ? commitError.message : String(commitError);
        set((state) => {
          const current = state.sessions[sessionId];
          if (!current) return;
          const control = current.controls.find((candidate) => candidate.id === optionId);
          if (!rollbackError && control) control.currentValue = previousValue;
          current.status = rollbackError ? "error" : current.status;
          current.statusDetail = rollbackError
            ? `Không thể xác nhận hoặc hoàn tác cấu hình: ${rollbackError instanceof Error ? rollbackError.message : String(rollbackError)}`
            : `Không thể lưu cấu hình; đã hoàn tác: ${reason}`;
          appendSessionEvent(current.events as NekoSessionEvent[], "model", {
            type: "control-change",
            phase: rollbackError ? "rollback-failed" : "rolled-back",
            optionId,
            previousValue,
            nextValue: value,
            reason,
          });
        });
        await persistSessionNowOrReport(sessionId, "trạng thái hoàn tác cấu hình", true);
      }
    },

    closeSession: async (sessionId) => {
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) session.status = "stopping";
      });
      const provider = runtimes.get(sessionId);
      const disposeError = await runtimes.detach(sessionId).then(
        () => null,
        (error) => error,
      );
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) {
          session.runtime = null;
          if (provider) {
            appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
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
          session.pendingControlId = null;
          session.statusDetail = "Đã kết thúc phiên — nhắn tiếp để khởi động lại agent.";
          session.updatedAt = Date.now();
          if (disposeError) {
            session.statusDetail = "Phiên đã đóng nhưng runtime báo lỗi khi thu hồi tài nguyên.";
          }
        }
      });
      await persistSessionNowOrReport(sessionId, "trạng thái đóng phiên");
    },

    deleteSession: async (sessionId) => {
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) session.status = "stopping";
      });
      await runtimes.detach(sessionId).catch(() => {});
      await deletePersistedSession(sessionId);
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
      const exitingProvider = event.type === "process-exited"
        ? runtimes.get(event.sessionId)
        : null;
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
            session.pendingControlId = null;
            return;
          }
          case "available-commands": {
            session.commands = event.commands.map((command) => ({ ...command }));
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
            session.messages.push({ id: uuidv4(), role: "assistant", blocks: [] });
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
            session.pendingControlId = null;
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
              appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
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
            session.pendingControlId = null;
            session.statusDetail =
              event.code === 0 || event.code === null
                ? "Agent đã thoát."
                : `Agent thoát với mã lỗi ${event.code}.`;
            return;
          }
        }
      });
      // Trailing debounced persist after every transcript-affecting event.
      const session = get().sessions[event.sessionId];
      if (session) persistSessionDebounced(session);
      if (event.type === "process-exited") {
        void runtimes.detach(event.sessionId).catch(() => {});
      }
    },
  })),
);

async function persistSessionNowOrReport(
  sessionId: string,
  context: string,
  fatal = false,
): Promise<void> {
  const session = useNekoSessionStore.getState().sessions[sessionId];
  if (!session) return;
  try {
    await persistSessionNow(session);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    useNekoSessionStore.setState((state) => {
      const current = state.sessions[sessionId];
      if (!current) return;
      if (fatal) current.status = "error";
      current.statusDetail = `Không thể lưu ${context}: ${reason}`;
    });
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
        appendSessionEvent(s.events as NekoSessionEvent[], "runtime", {
          type: "runtime-detached",
          providerId: provider.providerId,
          instanceId: provider.instanceId,
          kind: provider.kind,
          reason: "idle",
        }, now);
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
  const results = await runtimes.disposeAll();
  useNekoSessionStore.setState((state) => {
    for (const result of results) {
      const session = state.sessions[result.provider.sessionId];
      if (!session) continue;
      const currentProvider = runtimes.get(result.provider.sessionId);
      const hasNewRuntime = Boolean(
        currentProvider && currentProvider.instanceId !== result.provider.instanceId,
      );
      if (!hasNewRuntime) {
        session.runtime = null;
        session.status = "exited";
        session.pendingPermission = null;
        session.resolvingPermissionId = null;
        session.pendingControlId = null;
        session.updatedAt = Date.now();
        session.statusDetail = result.error
          ? "Đã rời Neko Chill nhưng runtime báo lỗi khi thu hồi tài nguyên."
          : "Runtime đã dừng khi rời Neko Chill.";
      }
      appendSessionEvent(session.events as NekoSessionEvent[], "runtime", {
        type: "runtime-detached",
        providerId: result.provider.providerId,
        instanceId: result.provider.instanceId,
        kind: result.provider.kind,
        reason: "mode-exit",
      });
    }
  });
  await Promise.all(results.map(async ({ provider }) => {
    await persistSessionNowOrReport(provider.sessionId, "trạng thái rời Neko Chill");
  }));
}

/** Test hook: swap the driver factory (kept off the public interface). */
export function _setDriverFactoryForTests(factory: DriverFactory | undefined): void {
  useNekoSessionStore.setState({ _driverFactory: factory } as never);
}

/** Test hook: drop live runtimes, simulating an app restart. */
export function _clearLiveDriversForTests(): void {
  runtimes.clearForTests();
  stopIdleReaper();
}
