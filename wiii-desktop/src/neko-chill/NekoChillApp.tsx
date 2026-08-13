/**
 * Neko Chill mode shell — waku-fidelity layout (#893, task #12).
 *
 * Anatomy studied from references/waku (design parameters only): 252px
 * sidebar, 51px session cards, 32px action rows, 720px content column,
 * coral accent used for pulses only, primary actions = inverse fill.
 * Top-left product switcher follows the Codex Desktop pattern
 * (one app, two engines: Wiii cloud ↔ Neko Chill local).
 */
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus, X } from "lucide-react";
import { TitleBar } from "@/components/layout/TitleBar";
import { useModeStore } from "./stores/mode-store";
import { useNekoAgentStore, type DetectedAgent } from "./stores/neko-agent-store";
import {
  startIdleReaper,
  useNekoSessionStore,
  type NekoSessionStatus,
} from "./stores/neko-session-store";
import { NekoTranscript } from "./components/NekoTranscript";
import { NekoComposer } from "./components/NekoComposer";
import "./theme.css";

/** Codex-style top-left product switcher: one app, two engines. */
function ModeSwitcher() {
  const { setMode } = useModeStore();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="mode-switcher"
        aria-label="Chuyển chế độ"
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-semibold text-[var(--nk-text)] hover:bg-[var(--nk-overlay)] transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        Neko Chill
        <ChevronDown aria-hidden="true" className="h-3 w-3 text-[var(--nk-text-3)]" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Chọn chế độ"
          className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-raised)] p-1 shadow-lg"
          data-testid="mode-switcher-menu"
        >
          <button
            type="button"
            role="menuitemradio"
            aria-checked="false"
            className="w-full rounded-lg px-3 py-2 text-left hover:bg-[var(--nk-overlay)] transition-colors"
            onClick={() => void setMode("wiii")}
          >
            <span className="block text-[13px] font-medium text-[var(--nk-text)]">Wiii</span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Trợ lý học tập & nghiên cứu — tài khoản cloud
            </span>
          </button>
          <button
            type="button"
            role="menuitemradio"
            aria-checked="true"
            className="w-full rounded-lg px-3 py-2 text-left hover:bg-[var(--nk-overlay)] transition-colors"
            onClick={() => setOpen(false)}
          >
            <span className="flex items-center justify-between text-[13px] font-medium text-[var(--nk-text)]">
              Neko Chill
              <Check aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-2)]" />
            </span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Agent chạy trên máy bạn — không cần tài khoản
            </span>
          </button>
        </div>
      ) : null}
    </div>
  );
}

function statusLabel(status: NekoSessionStatus): string {
  switch (status) {
    case "streaming":
      return "đang làm việc";
    case "connecting":
      return "đang kết nối";
    case "idle":
      return "sẵn sàng";
    case "exited":
      return "đã dừng";
    default:
      return "lỗi";
  }
}

function SessionSidebar() {
  const sessions = useNekoSessionStore((s) => s.sessions);
  const activeSessionId = useNekoSessionStore((s) => s.activeSessionId);
  const { setActiveSession, deleteSession } = useNekoSessionStore();
  const ordered = Object.values(sessions).sort((a, b) => b.createdAt - a.createdAt);

  return (
    <aside
      className="w-[252px] shrink-0 flex flex-col border-r border-[var(--nk-border)]"
      data-testid="session-sidebar"
    >
      <div className="px-2 pt-2 pb-1">
        <ModeSwitcher />
      </div>
      <div className="px-2 pb-1.5">
        <button
          type="button"
          className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[12.5px] font-medium text-[var(--nk-text-2)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] transition-colors"
          onClick={() => setActiveSession(null)}
          data-testid="new-session"
        >
          <Plus aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" />
          Phiên mới
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {ordered.length === 0 ? (
          <p className="px-2.5 py-2 text-[12px] text-[var(--nk-text-3)]">Chưa có phiên nào.</p>
        ) : (
          <div className="flex flex-col gap-[1px]">
            {ordered.map((session) => (
              <div
                key={session.id}
                className={`nk-session-row group flex h-[51px] items-center gap-2 rounded-lg px-2.5 transition-colors ${
                  session.id === activeSessionId
                    ? "bg-[var(--nk-item-active)]"
                    : "hover:bg-[var(--nk-overlay)]"
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 cursor-pointer text-left"
                  aria-current={session.id === activeSessionId ? "true" : undefined}
                  aria-label={`Mở phiên ${session.title}`}
                  onClick={() => setActiveSession(session.id)}
                >
                  <span className="block truncate text-[13px] font-medium leading-[18px] text-[var(--nk-text)]">
                    {session.title}
                  </span>
                  <span className="block truncate text-[11px] leading-[15px] text-[var(--nk-text-3)]">
                    {session.agentName} ·{" "}
                    {new Date(session.createdAt).toLocaleDateString("vi-VN")}
                    {session.status === "streaming" ? (
                      <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-[var(--nk-accent)] align-middle animate-pulse" />
                    ) : null}
                  </span>
                </button>
                <button
                  type="button"
                  className="nk-row-action rounded p-1 text-[var(--nk-ghost)] hover:text-[var(--nk-danger)] transition-colors"
                  title="Xoá phiên"
                  aria-label={`Xoá phiên ${session.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteSession(session.id);
                  }}
                >
                  <X aria-hidden="true" className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

function AgentPicker() {
  const { agents, isLoading } = useNekoAgentStore();
  const createSession = useNekoSessionStore((s) => s.createSession);

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[720px] px-6 pt-[12vh]">
        <h1
          className="text-[26px] font-normal text-[var(--nk-text)]"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          Neko Chill
        </h1>
        <p className="mt-1 mb-8 text-[13.5px] text-[var(--nk-text-2)]">
          Agent chạy ngay trên máy bạn — không cần tài khoản.
        </p>
        <p className="mb-2 text-[11.5px] font-medium uppercase tracking-wide text-[var(--nk-text-3)]">
          Chọn agent để bắt đầu
        </p>
        {isLoading ? (
          <p className="text-[13px] text-[var(--nk-text-3)]">Đang dò tìm agent…</p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="agent-list">
            {agents.map((agent: DetectedAgent) => (
              <li
                key={agent.id}
                className="flex h-[54px] items-center justify-between rounded-[10px] border border-[var(--nk-border)] bg-[var(--nk-raised)] px-4 transition-colors hover:border-[var(--nk-border-strong)]"
              >
                <div className="min-w-0">
                  <span className="text-[13.5px] font-medium text-[var(--nk-text)]">
                    {agent.name}
                  </span>
                  <span className="ml-2 text-[11.5px] text-[var(--nk-text-3)]">
                    {agent.found ? agent.version : "Chưa cài"}
                  </span>
                </div>
                <button
                  type="button"
                  className="rounded-lg bg-[var(--nk-inverse)] px-3 py-1.5 text-[12px] font-medium text-[var(--nk-on-inverse)] disabled:opacity-35 transition-opacity"
                  disabled={!agent.found}
                  onClick={() => void createSession(agent)}
                  data-testid={`start-${agent.id}`}
                >
                  Bắt đầu phiên
                </button>
              </li>
            ))}
            {agents.length === 0 ? (
              <li className="text-[13px] text-[var(--nk-text-3)]">
                Chưa phát hiện agent ACP nào. Cài{" "}
                <span className="font-medium text-[var(--nk-text-2)]">neko-core</span>{" "}
                (neko.holilihu.online) hoặc{" "}
                <span className="font-medium text-[var(--nk-text-2)]">Gemini CLI</span> rồi
                mở lại chế độ này.
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </main>
  );
}

export default function NekoChillApp() {
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
    startIdleReaper();
  }, [detect, hydrate]);

  return (
    <div className="nk-root flex h-screen flex-col bg-[var(--nk-canvas)] text-[var(--nk-text)]">
      {/* Frameless window: standalone surfaces carry their own controls. */}
      <TitleBar minimal />
      <div className="flex min-h-0 flex-1">
        <SessionSidebar />
        {session ? (
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex h-10 shrink-0 items-center justify-between px-4">
              <p className="flex items-center gap-2 text-[12.5px] text-[var(--nk-text-2)]">
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    session.status === "streaming"
                      ? "bg-[var(--nk-accent)] animate-pulse"
                      : session.status === "idle"
                        ? "bg-[var(--nk-success)]"
                        : session.status === "error"
                          ? "bg-[var(--nk-danger)]"
                          : "bg-[var(--nk-ghost)]"
                  }`}
                />
                {session.agentName} · {statusLabel(session.status)}
              </p>
              {session.status !== "exited" && session.status !== "error" ? (
                <button
                  type="button"
                  className="text-[12px] text-[var(--nk-text-3)] hover:text-[var(--nk-text)] transition-colors"
                  onClick={() => void closeSession(session.id)}
                >
                  Kết thúc phiên
                </button>
              ) : null}
            </header>
            <NekoTranscript
              session={session}
              onResolvePermission={(optionId) => void resolvePermission(optionId)}
            />
            <NekoComposer
              disabled={session.status === "connecting" || session.status === "error"}
              streaming={session.status === "streaming"}
              agentLabel={session.agentName}
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
