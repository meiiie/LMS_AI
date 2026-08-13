/**
 * Neko Chill mode shell (T303/T502, #886).
 *
 * No-login local-agent surface. Mounts INSTEAD of the cloud app (ModeGate),
 * so no auth/org/backend init can run while the mode is active (FR-002).
 * Left: persisted session list (FR-008). Right: agent picker (no active
 * session) or the streaming chat surface.
 */
import { useEffect } from "react";
import { useModeStore } from "./stores/mode-store";
import { useNekoAgentStore, type DetectedAgent } from "./stores/neko-agent-store";
import { useNekoSessionStore } from "./stores/neko-session-store";
import { NekoTranscript } from "./components/NekoTranscript";
import { NekoComposer } from "./components/NekoComposer";

function AgentPicker() {
  const { agents, isLoading } = useNekoAgentStore();
  const createSession = useNekoSessionStore((s) => s.createSession);

  return (
    <main className="flex-1 overflow-y-auto px-6 py-6">
      <h2 className="text-sm font-medium text-text-tertiary uppercase tracking-wide mb-3">
        Chọn agent để bắt đầu
      </h2>
      {isLoading ? (
        <p className="text-sm text-text-tertiary">Đang dò tìm agent…</p>
      ) : (
        <ul className="space-y-2" data-testid="agent-list">
          {agents.map((agent: DetectedAgent) => (
            <li
              key={agent.id}
              className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
            >
              <div>
                <span className="font-medium">{agent.name}</span>
                {agent.found && agent.version ? (
                  <span className="ml-2 text-xs text-text-tertiary">{agent.version}</span>
                ) : null}
                {!agent.found ? (
                  <span className="ml-2 text-xs text-text-tertiary">Chưa cài</span>
                ) : null}
              </div>
              <button
                type="button"
                className="text-sm rounded-md border border-border px-3 py-1.5 font-medium disabled:opacity-40 hover:bg-surface-hover transition-colors"
                disabled={!agent.found}
                onClick={() => void createSession(agent)}
                data-testid={`start-${agent.id}`}
              >
                Bắt đầu phiên
              </button>
            </li>
          ))}
          {agents.length === 0 ? (
            <li className="text-sm text-text-tertiary">
              Chưa phát hiện agent ACP nào. Cài{" "}
              <span className="font-medium">neko-core</span> (neko.holilihu.online) hoặc{" "}
              <span className="font-medium">Gemini CLI</span> rồi mở lại chế độ này.
            </li>
          ) : null}
        </ul>
      )}
    </main>
  );
}

function SessionSidebar() {
  const sessions = useNekoSessionStore((s) => s.sessions);
  const activeSessionId = useNekoSessionStore((s) => s.activeSessionId);
  const { setActiveSession, deleteSession } = useNekoSessionStore();
  const ordered = Object.values(sessions).sort((a, b) => b.createdAt - a.createdAt);

  return (
    <aside className="w-64 shrink-0 border-r border-border flex flex-col" data-testid="session-sidebar">
      <div className="px-4 py-3 border-b border-border">
        <button
          type="button"
          className="w-full text-sm rounded-md border border-border px-3 py-2 font-medium hover:bg-surface-hover transition-colors"
          onClick={() => setActiveSession(null)}
          data-testid="new-session"
        >
          + Phiên mới
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {ordered.length === 0 ? (
          <p className="px-4 py-2 text-sm text-text-tertiary">Chưa có phiên nào.</p>
        ) : (
          ordered.map((session) => (
            <div
              key={session.id}
              className={`group flex items-center gap-2 px-4 py-2 cursor-pointer text-sm ${
                session.id === activeSessionId
                  ? "bg-surface-secondary"
                  : "hover:bg-surface-hover"
              }`}
              onClick={() => setActiveSession(session.id)}
            >
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium">{session.title}</p>
                <p className="text-xs text-text-tertiary">
                  {session.agentName} · {new Date(session.createdAt).toLocaleDateString("vi-VN")}
                </p>
              </div>
              <button
                type="button"
                className="opacity-0 group-hover:opacity-100 text-xs text-text-tertiary hover:text-red-500 transition-opacity"
                title="Xoá phiên"
                onClick={(event) => {
                  event.stopPropagation();
                  void deleteSession(session.id);
                }}
              >
                ✕
              </button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

export default function NekoChillApp() {
  const { setMode } = useModeStore();
  const detect = useNekoAgentStore((s) => s.detect);
  const hydrate = useNekoSessionStore((s) => s.hydrate);
  const session = useNekoSessionStore((s) =>
    s.activeSessionId ? s.sessions[s.activeSessionId] : null,
  );
  const { sendPrompt, cancelTurn, resolvePermission, closeSession } =
    useNekoSessionStore();

  useEffect(() => {
    void detect();
    void hydrate();
  }, [detect, hydrate]);

  const statusLabel = session
    ? session.status === "streaming"
      ? "đang làm việc"
      : session.status === "connecting"
        ? "đang kết nối"
        : session.status === "idle"
          ? "sẵn sàng"
          : session.status === "exited"
            ? "đã dừng"
            : "lỗi"
    : null;

  return (
    <div className="flex flex-col h-screen bg-surface text-text-primary">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div>
          <h1 className="text-lg font-semibold">Neko Chill</h1>
          <p className="text-sm text-text-tertiary">
            {session
              ? `${session.agentName} · ${statusLabel}`
              : "Agent chạy ngay trên máy bạn — không cần tài khoản."}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {session && session.status !== "exited" && session.status !== "error" ? (
            <button
              type="button"
              className="text-sm text-text-tertiary hover:text-text-primary transition-colors"
              onClick={() => void closeSession(session.id)}
            >
              Kết thúc phiên
            </button>
          ) : null}
          <button
            type="button"
            className="text-sm text-text-tertiary hover:text-text-primary transition-colors"
            onClick={() => void setMode("wiii")}
          >
            ← Về chế độ Wiii
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <SessionSidebar />
        {session ? (
          <div className="flex flex-col flex-1 min-w-0">
            <NekoTranscript
              session={session}
              onResolvePermission={(optionId) => void resolvePermission(optionId)}
            />
            <NekoComposer
              disabled={session.status === "connecting" || session.status === "error"}
              streaming={session.status === "streaming"}
              onSend={(text) => void sendPrompt(text)}
              onCancel={() => void cancelTurn()}
            />
          </div>
        ) : (
          <AgentPicker />
        )}
      </div>
    </div>
  );
}
