/**
 * Neko Chill mode shell (T303/T304, #886).
 *
 * No-login local-agent surface. Mounts INSTEAD of the cloud app (ModeGate),
 * so no auth/org/backend init can run while the mode is active (FR-002).
 * Empty state = agent picker; with a session = streaming chat surface.
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

export default function NekoChillApp() {
  const { setMode } = useModeStore();
  const detect = useNekoAgentStore((s) => s.detect);
  const activeSessionId = useNekoSessionStore((s) => s.activeSessionId);
  const session = useNekoSessionStore((s) =>
    s.activeSessionId ? s.sessions[s.activeSessionId] : null,
  );
  const { sendPrompt, cancelTurn, resolvePermission, closeSession } =
    useNekoSessionStore();

  useEffect(() => {
    void detect();
  }, [detect]);

  return (
    <div className="flex flex-col h-screen bg-surface text-text-primary">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div>
          <h1 className="text-lg font-semibold">Neko Chill</h1>
          <p className="text-sm text-text-tertiary">
            {session
              ? `${session.agentName} · ${
                  session.status === "streaming"
                    ? "đang làm việc"
                    : session.status === "connecting"
                      ? "đang kết nối"
                      : session.status === "idle"
                        ? "sẵn sàng"
                        : "đã dừng"
                }`
              : "Agent chạy ngay trên máy bạn — không cần tài khoản."}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {session ? (
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

      {session && activeSessionId ? (
        <>
          <NekoTranscript
            session={session}
            onResolvePermission={(optionId) => void resolvePermission(optionId)}
          />
          <NekoComposer
            disabled={session.status !== "idle"}
            streaming={session.status === "streaming"}
            onSend={(text) => void sendPrompt(text)}
            onCancel={() => void cancelTurn()}
          />
        </>
      ) : (
        <AgentPicker />
      )}
    </div>
  );
}
