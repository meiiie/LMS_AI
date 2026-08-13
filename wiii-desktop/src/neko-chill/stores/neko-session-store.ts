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
  DriverEvent,
  PermissionRequest,
} from "../drivers/types";
import type { DetectedAgent } from "./neko-agent-store";

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
  onEvent: (event: DriverEvent) => void,
) => Promise<Driver>;

async function defaultDriverFactory(
  agent: DetectedAgent,
  sessionId: string,
  onEvent: (event: DriverEvent) => void,
): Promise<Driver> {
  const { createDriverForAgent } = await import("../drivers/factory");
  return createDriverForAgent(agent, sessionId, onEvent);
}

interface NekoSessionState {
  sessions: Record<string, NekoSession>;
  activeSessionId: string | null;
  createSession: (agent: DetectedAgent) => Promise<string>;
  sendPrompt: (text: string) => Promise<void>;
  cancelTurn: () => Promise<void>;
  resolvePermission: (optionId: string | null) => Promise<void>;
  closeSession: (sessionId: string) => Promise<void>;
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

    createSession: async (agent) => {
      const sessionId = uuidv4();
      set((state) => {
        state.sessions[sessionId] = {
          id: sessionId,
          agentId: agent.id,
          agentName: agent.name,
          title: `Phiên với ${agent.name}`,
          createdAt: Date.now(),
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
        const driver = await factory(agent, sessionId, (event) =>
          get().handleEvent(event),
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
      return sessionId;
    },

    sendPrompt: async (text) => {
      const sessionId = get().activeSessionId;
      if (!sessionId) return;
      const driver = drivers.get(sessionId);
      const session = get().sessions[sessionId];
      if (!driver || !session || session.status !== "idle") return;

      set((state) => {
        const s = state.sessions[sessionId];
        if (!s) return;
        s.messages.push({ id: uuidv4(), role: "user", text });
        if (s.messages.length === 1) {
          s.title = text.length > 48 ? `${text.slice(0, 48)}…` : text;
        }
      });
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

    closeSession: async (sessionId) => {
      const driver = drivers.get(sessionId);
      drivers.delete(sessionId);
      await driver?.dispose().catch(() => {});
      set((state) => {
        delete state.sessions[sessionId];
        if (state.activeSessionId === sessionId) {
          const remaining = Object.keys(state.sessions);
          state.activeSessionId = remaining[remaining.length - 1] ?? null;
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

        switch (event.type) {
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
            session.statusDetail =
              event.code === 0 || event.code === null
                ? "Agent đã thoát."
                : `Agent thoát với mã lỗi ${event.code}.`;
            return;
          }
        }
      });
    },
  })),
);

/** Test hook: swap the driver factory (kept off the public interface). */
export function _setDriverFactoryForTests(factory: DriverFactory | undefined): void {
  useNekoSessionStore.setState({ _driverFactory: factory } as never);
}
