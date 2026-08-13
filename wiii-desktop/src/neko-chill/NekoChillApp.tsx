/** Neko Chill desktop-agent shell: projects -> sessions -> active runtime. */
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, PanelRight, Power } from "lucide-react";
import { TitleBar } from "@/components/layout/TitleBar";
import { useModeStore } from "./stores/mode-store";
import { useNekoAgentStore } from "./stores/neko-agent-store";
import {
  startIdleReaper,
  useNekoSessionStore,
  type NekoSessionStatus,
} from "./stores/neko-session-store";
import { NekoTranscript } from "./components/NekoTranscript";
import { NekoComposer } from "./components/NekoComposer";
import { NewSessionView } from "./components/NewSessionView";
import { SessionInspector } from "./components/SessionInspector";
import { SessionSidebar } from "./components/SessionSidebar";
import { chooseWorkspaceFolder } from "./workspace";
import "./theme.css";

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
        className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-semibold text-[var(--nk-text)] transition-colors hover:bg-[var(--nk-overlay)]"
        onClick={() => setOpen((value) => !value)}
      >
        Neko Chill
        <ChevronDown aria-hidden="true" className="h-3 w-3 text-[var(--nk-text-3)]" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Chọn chế độ"
          className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] p-1 shadow-lg"
          data-testid="mode-switcher-menu"
        >
          <button
            type="button"
            role="menuitemradio"
            aria-checked="false"
            className="w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--nk-overlay)]"
            onClick={() => void setMode("wiii")}
          >
            <span className="block text-[13px] font-medium text-[var(--nk-text)]">Wiii</span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Trợ lý học tập và nghiên cứu · tài khoản cloud
            </span>
          </button>
          <button
            type="button"
            role="menuitemradio"
            aria-checked="true"
            className="w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--nk-overlay)]"
            onClick={() => setOpen(false)}
          >
            <span className="flex items-center justify-between text-[13px] font-medium text-[var(--nk-text)]">
              Neko Chill
              <Check aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-2)]" />
            </span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Agent cục bộ · không cần tài khoản
            </span>
          </button>
        </div>
      ) : null}
    </div>
  );
}

function statusLabel(status: NekoSessionStatus): string {
  switch (status) {
    case "streaming": return "đang làm việc";
    case "connecting": return "đang kết nối";
    case "idle": return "sẵn sàng";
    case "exited": return "runtime đã dừng";
    default: return "lỗi";
  }
}

function statusColor(status: NekoSessionStatus): string {
  if (status === "streaming") return "bg-[var(--nk-accent)] animate-pulse";
  if (status === "idle") return "bg-[var(--nk-success)]";
  if (status === "error") return "bg-[var(--nk-danger)]";
  return "bg-[var(--nk-ghost)]";
}

export default function NekoChillApp() {
  const detect = useNekoAgentStore((state) => state.detect);
  const hydrate = useNekoSessionStore((state) => state.hydrate);
  const activeSessionId = useNekoSessionStore((state) => state.activeSessionId);
  const session = useNekoSessionStore((state) =>
    state.activeSessionId ? state.sessions[state.activeSessionId] : null,
  );
  const {
    attachWorkspace,
    cancelTurn,
    closeSession,
    resolvePermission,
    sendPrompt,
    setActiveSession,
    setConfigOption,
  } = useNekoSessionStore();
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [focusSearchToken, setFocusSearchToken] = useState(0);

  useEffect(() => {
    void detect();
    void hydrate();
    startIdleReaper();
  }, [detect, hydrate]);

  useEffect(() => {
    if (activeSessionId) setInspectorOpen(true);
  }, [activeSessionId]);

  const handleProjectCommand = async () => {
    if (!session) return;
    if (session.workspace) {
      setInspectorOpen(true);
      return;
    }
    const workspace = await chooseWorkspaceFolder();
    if (workspace) await attachWorkspace(session.id, workspace);
  };

  const handleClientCommand = (command: "new" | "project" | "search" | "info") => {
    if (command === "new") setActiveSession(null);
    else if (command === "project") void handleProjectCommand();
    else if (command === "search") setFocusSearchToken((value) => value + 1);
    else setInspectorOpen(true);
  };

  return (
    <div className="nk-root flex h-screen flex-col bg-[var(--nk-canvas)] text-[var(--nk-text)]">
      <TitleBar minimal />
      <div className="flex min-h-0 flex-1">
        <SessionSidebar modeSwitcher={<ModeSwitcher />} focusSearchToken={focusSearchToken} />
        {session ? (
          <div className="relative flex min-w-0 flex-1">
            <div className="flex min-w-0 flex-1 flex-col">
              <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--nk-border)] px-4">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor(session.status)}`} />
                  <div className="min-w-0">
                    <h1 className="truncate text-[13px] font-medium text-[var(--nk-text)]">
                      {session.title}
                    </h1>
                    <p className="truncate text-[10.5px] text-[var(--nk-text-3)]">
                      {session.workspace?.name ?? "Chưa gắn dự án"} · {session.agentName} · {statusLabel(session.status)}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    className={`rounded-md p-1.5 text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] ${inspectorOpen ? "bg-[var(--nk-overlay)]" : ""}`}
                    aria-label={inspectorOpen ? "Ẩn thông tin phiên" : "Hiện thông tin phiên"}
                    aria-pressed={inspectorOpen}
                    onClick={() => setInspectorOpen((value) => !value)}
                  >
                    <PanelRight aria-hidden="true" className="h-3.5 w-3.5" />
                  </button>
                  {session.status !== "exited" && session.status !== "error" ? (
                    <button
                      type="button"
                      className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)]"
                      onClick={() => void closeSession(session.id)}
                    >
                      <Power aria-hidden="true" className="h-3 w-3" />
                      Kết thúc
                    </button>
                  ) : null}
                </div>
              </header>
              <NekoTranscript
                session={session}
                onResolvePermission={(optionId) => void resolvePermission(optionId)}
              />
              <NekoComposer
                session={session}
                disabled={session.status === "connecting" || session.status === "error"}
                streaming={session.status === "streaming"}
                onSend={(text) => void sendPrompt(text)}
                onCancel={() => void cancelTurn()}
                onSetConfigOption={(optionId, value) => void setConfigOption(optionId, value)}
                onClientCommand={handleClientCommand}
              />
            </div>
            {inspectorOpen ? (
              <>
                <button
                  type="button"
                  className="absolute inset-0 z-20 bg-black/10 xl:hidden"
                  aria-label="Đóng thông tin phiên"
                  onClick={() => setInspectorOpen(false)}
                />
                <SessionInspector
                  session={session}
                  onClose={() => setInspectorOpen(false)}
                  onSetConfigOption={(optionId, value) => void setConfigOption(optionId, value)}
                />
              </>
            ) : null}
          </div>
        ) : (
          <NewSessionView />
        )}
      </div>
    </div>
  );
}
