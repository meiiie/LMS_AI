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
  loadSessionTranscript,
  persistSessionDebounced,
  persistSessionNow,
} from "../persistence";

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
  /** Set while the agent waits on an approval (FR-006); UI must resolve it. */
  pendingPermission: PermissionRequest | null;
  /** Honest error text for the banner when status is error/exited. */
  statusDetail?: string;
}

/** Live drivers, keyed by session id — deliberately outside zustand. */
const drivers = new Map<string, Driver>();

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

export const useNekoSessionStore = create<NekoSessionState>()(
  immer((set, get) => ({
    sessions: {},
    activeSessionId: null,
    hydrated: false,

    hydrate: async () => {
      if (get().hydrated) return;
      const index = await loadSessionIndex();
      const restored: Record<string, NekoSession> = {};
      for (const entry of index) {
        // Live sessions in state win over their persisted snapshot.
        if (get().sessions[entry.id]) continue;
        restored[entry.id] = {
          id: entry.id,
          agentId: entry.agentId,
          agentName: entry.agentName,
          title: entry.title,
          createdAt: entry.createdAt,
          updatedAt: entry.updatedAt,
          workspace: entry.workspace ?? null,
          launchProfile: entry.launchProfile ?? null,
          controls: entry.controls ?? [],
          commands: entry.commands ?? [],
          pendingControlId: null,
          lastActivityAt: entry.updatedAt,
          status: "exited",
          messages: await loadSessionTranscript(entry.id),
          pendingPermission: null,
          statusDetail: "Phiên đã lưu — nhắn tiếp để khởi động lại agent.",
        };
      }
      set((state) => {
        state.sessions = { ...restored, ...state.sessions };
        state.hydrated = true;
      });
    },

    createSession: async (agent, workspace, launchProfile = null) => {
      if (!workspace || !isAbsoluteWorkspacePath(workspace.path)) {
        throw new Error("Hãy chọn một thư mục dự án tuyệt đối trước khi bắt đầu.");
      }
      const sessionId = uuidv4();
      const now = Date.now();
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
          pendingPermission: null,
        };
        state.activeSessionId = sessionId;
      });
      try {
        const factory: DriverFactory =
          (get() as unknown as { _driverFactory?: DriverFactory })._driverFactory ??
          defaultDriverFactory;
        const driver = await factory(
          agent,
          sessionId,
          {
            workspace,
            ...(launchProfile?.id ? { profileId: launchProfile.id } : {}),
          },
          (event) => get().handleEvent(event),
        );
        drivers.set(sessionId, driver);
        set((state) => {
          const session = state.sessions[sessionId];
          if (session && session.status === "connecting") session.status = "idle";
        });
      } catch (err) {
        set((state) => {
          const session = state.sessions[sessionId];
          if (session) {
            session.status = "error";
            session.statusDetail =
              err instanceof Error ? err.message : String(err);
          }
        });
      }
      const created = get().sessions[sessionId];
      if (created) await persistSessionNow(created);
      return sessionId;
    },

    attachWorkspace: async (sessionId, workspace) => {
      if (!workspace || !isAbsoluteWorkspacePath(workspace.path)) return;
      const current = get().sessions[sessionId];
      if (!current || current.workspace) return;
      const driver = drivers.get(sessionId);
      drivers.delete(sessionId);
      await driver?.dispose().catch(() => {});
      set((state) => {
        const session = state.sessions[sessionId];
        if (!session || session.workspace) return;
        session.workspace = workspace;
        session.status = "exited";
        session.statusDetail =
          "Đã gắn dự án. Lượt tiếp theo sẽ khởi động một runtime mới trong thư mục này.";
        session.updatedAt = Date.now();
        session.lastActivityAt = session.updatedAt;
      });
      const updated = get().sessions[sessionId];
      if (updated) await persistSessionNow(updated);
    },

    sendPrompt: async (text) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      // "exited" accepts a new prompt: a restored (or crashed) session
      // respawns a FRESH agent process (spec US3-2 / edge case restart).
      if (!session || (session.status !== "idle" && session.status !== "exited")) {
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

      let driver = drivers.get(sessionId);
      if (!driver) {
        const agentStore = useNekoAgentStore.getState();
        if (agentStore.agents.length === 0) await agentStore.detect();
        const agent = useNekoAgentStore
          .getState()
          .agents.find((a) => a.id === session.agentId);
        if (!agent?.found) {
          set((state) => {
            const s = state.sessions[sessionId];
            if (s) {
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
          driver = await factory(
            agent,
            sessionId,
            {
              workspace: session.workspace,
              ...(session.launchProfile?.id
                ? { profileId: session.launchProfile.id }
                : {}),
            },
            (event) => get().handleEvent(event),
          );
          drivers.set(sessionId, driver);
          set((state) => {
            const s = state.sessions[sessionId];
            if (s) {
              s.status = "idle";
              s.statusDetail = undefined;
            }
          });
        } catch (err) {
          set((state) => {
            const s = state.sessions[sessionId];
            if (s) {
              s.status = "error";
              s.statusDetail = err instanceof Error ? err.message : String(err);
            }
          });
          return;
        }
      }

      set((state) => {
        const s = state.sessions[sessionId];
        if (!s) return;
        s.messages.push({ id: uuidv4(), role: "user", text });
        s.lastActivityAt = Date.now();
        s.updatedAt = s.lastActivityAt;
        if (s.messages.length === 1) {
          s.title = text.length > 48 ? `${text.slice(0, 48)}…` : text;
        }
      });
      const updated = get().sessions[sessionId];
      if (updated) persistSessionDebounced(updated);
      // turn-started from the driver flips status + opens the assistant
      // message; prompt() resolves only when the whole turn ends.
      await driver.prompt(text);
    },

    cancelTurn: async () => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      await drivers.get(sessionId)?.cancel();
    },

    resolvePermission: async (optionId) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      const request = session?.pendingPermission;
      if (!request) return;
      set((state) => {
        const s = state.sessions[sessionId];
        if (s) s.pendingPermission = null;
      });
      // Driver fails closed on null/unknown options (FR-006).
      await drivers.get(sessionId)?.resolvePermission({
        requestId: request.requestId,
        optionId,
      });
    },

    setConfigOption: async (optionId, value) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const session = get().sessions[sessionId];
      const driver = drivers.get(sessionId);
      if (
        !session ||
        !driver ||
        session.status !== "idle" ||
        session.pendingPermission ||
        session.pendingControlId
      ) {
        return;
      }
      set((state) => {
        const current = state.sessions[sessionId];
        if (current) {
          current.pendingControlId = optionId;
          current.statusDetail = undefined;
        }
      });
      try {
        await driver.setConfigOption(optionId, value);
      } catch (error) {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current) {
            current.statusDetail =
              error instanceof Error ? error.message : String(error);
          }
        });
      } finally {
        set((state) => {
          const current = state.sessions[sessionId];
          if (current?.pendingControlId === optionId) {
            current.pendingControlId = null;
          }
        });
      }
      const updated = get().sessions[sessionId];
      if (updated) persistSessionDebounced(updated);
    },

    closeSession: async (sessionId) => {
      const driver = drivers.get(sessionId);
      drivers.delete(sessionId);
      await driver?.dispose().catch(() => {});
      set((state) => {
        const session = state.sessions[sessionId];
        if (session) {
          session.status = "exited";
          session.pendingPermission = null;
          session.pendingControlId = null;
          session.statusDetail = "Đã kết thúc phiên — nhắn tiếp để khởi động lại agent.";
          session.updatedAt = Date.now();
        }
      });
      const session = get().sessions[sessionId];
      if (session) await persistSessionNow(session);
    },

    deleteSession: async (sessionId) => {
      const driver = drivers.get(sessionId);
      drivers.delete(sessionId);
      await driver?.dispose().catch(() => {});
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
            return;
          }
          case "turn-finished": {
            session.status = "idle";
            session.pendingPermission = null;
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
            drivers.delete(event.sessionId);
            session.status = "exited";
            session.pendingPermission = null;
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
    },
  })),
);

// ---------------------------------------------------------------------------
// Idle reap (T601, FR-009 — waku's lesson, reimplemented)
// ---------------------------------------------------------------------------

const IDLE_REAP_MS = 30 * 60 * 1000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;
let reaperTimer: ReturnType<typeof setInterval> | null = null;

/**
 * Dispose drivers of sessions idle past the threshold. Never touches a
 * streaming turn or an unanswered permission request (the sweep may run
 * while the user reads an approval — reaping there would fail their turn).
 */
export async function sweepIdleSessions(now: number = Date.now()): Promise<void> {
  const { sessions } = useNekoSessionStore.getState();
  for (const session of Object.values(sessions)) {
    if (session.status !== "idle") continue;
    if (session.pendingPermission) continue;
    if (now - session.lastActivityAt < IDLE_REAP_MS) continue;
    const driver = drivers.get(session.id);
    if (!driver) continue;
    drivers.delete(session.id);
    await driver.dispose().catch(() => {});
    useNekoSessionStore.setState((state) => {
      const s = state.sessions[session.id];
      if (s && s.status === "idle") {
        s.status = "exited";
        s.statusDetail = "Agent tạm nghỉ sau 30 phút yên lặng — nhắn tiếp để khởi động lại.";
        s.updatedAt = now;
        s.lastActivityAt = now;
      }
    });
    const updated = useNekoSessionStore.getState().sessions[session.id];
    if (updated) await persistSessionNow(updated);
  }
}

/** Start the periodic sweep (idempotent; called on mode entry). */
export function startIdleReaper(): void {
  if (reaperTimer) return;
  reaperTimer = setInterval(() => void sweepIdleSessions(), SWEEP_INTERVAL_MS);
}

/** Test hook: swap the driver factory (kept off the public interface). */
export function _setDriverFactoryForTests(factory: DriverFactory | undefined): void {
  useNekoSessionStore.setState({ _driverFactory: factory } as never);
}

/** Test hook: drop live drivers, simulating an app restart. */
export function _clearLiveDriversForTests(): void {
  drivers.clear();
}
