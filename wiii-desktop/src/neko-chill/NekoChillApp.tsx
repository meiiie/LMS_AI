/** Neko Chill desktop-agent shell: projects -> sessions -> active runtime. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  LoaderCircle,
  PanelLeft,
  PanelLeftClose,
  Files,
  Info,
  Power,
  RefreshCw,
  Search,
} from "lucide-react";
import { TitleBar } from "@/components/layout/TitleBar";
import { WiiiMark } from "@/components/common/WiiiMark";
import { useNekoAgentStore } from "./stores/neko-agent-store";
import {
  disposeAllNekoRuntimes,
  startIdleReaper,
  useNekoSessionStore,
  type NekoSessionStatus,
} from "./stores/neko-session-store";
import { NEKO_SESSION_STATUS_LABELS } from "./session-status";
import { NekoTranscript } from "./components/NekoTranscript";
import { NekoComposer } from "./components/NekoComposer";
import { NewSessionView } from "./components/NewSessionView";
import { SessionInspector } from "./components/SessionInspector";
import { SessionSidebar } from "./components/SessionSidebar";
import { NekoCommandCenter } from "./components/NekoCommandCenter";
import { NekoWorkspacePane } from "./components/NekoWorkspacePane";
import { useNekoWorkspaceStore } from "./stores/neko-workspace-store";
import {
  type ClientCommandName,
  type WorkbenchActionName,
} from "./command-items";
import type { ComposerInsertRequest } from "./components/NekoComposer";
import { chooseWorkspaceFolder } from "./workspace";
import { useKnowledgeConnectionStore } from "@/workbench/knowledge";
import "./theme.css";

function useCompactWorkspace(breakpoint = 1040) {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, [breakpoint]);
  return compact;
}

function ModeSwitcher({ onOpenManaged }: { onOpenManaged: () => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const knowledgeStatus = useKnowledgeConnectionStore((state) => state.status);
  const knowledgeError = useKnowledgeConnectionStore((state) => state.error);
  const connectKnowledge = useKnowledgeConnectionStore((state) => state.connect);
  const disconnectKnowledge = useKnowledgeConnectionStore((state) => state.disconnect);

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
        aria-label="Chuyển không gian"
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-semibold text-[var(--nk-text)] transition-colors hover:bg-[var(--nk-overlay)]"
        onClick={() => setOpen((value) => !value)}
      >
        <WiiiMark className="shrink-0" size={17} />
        <span>Wiii Workbench</span>
        <ChevronDown aria-hidden="true" className="h-3 w-3 text-[var(--nk-text-3)]" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Chọn không gian"
          className="absolute left-0 top-full z-50 mt-1 w-64 rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] p-1 shadow-lg"
          data-testid="mode-switcher-menu"
        >
          <button
            type="button"
            role="menuitemradio"
            aria-checked="false"
            className="w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--nk-overlay)]"
            onClick={() => {
              setOpen(false);
              onOpenManaged();
            }}
          >
            <span className="block text-[13px] font-medium text-[var(--nk-text)]">Wiii Service</span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Runtime được quản lý · RAG, memory và đồng bộ
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
              Không gian cục bộ
              <Check aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-2)]" />
            </span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              Agent và tệp dự án trên máy · không cần tài khoản Wiii
            </span>
          </button>
          <div className="my-1 border-t border-[var(--nk-border)]" />
          <div className="px-3 pb-1 pt-1">
            <span className="block text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--nk-ghost)]">
              Tri thức tùy chọn
            </span>
          </div>
          <button
            type="button"
            role="menuitem"
            disabled={knowledgeStatus === "connecting"}
            className="w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--nk-overlay)] disabled:opacity-60"
            onClick={() => {
              if (knowledgeStatus === "ready") disconnectKnowledge();
              else void connectKnowledge();
            }}
          >
            <span className="flex items-center justify-between text-[13px] font-medium text-[var(--nk-text)]">
              Wiii Knowledge
              <span className={`h-2 w-2 rounded-full ${
                knowledgeStatus === "ready"
                  ? "bg-[var(--nk-success)]"
                  : knowledgeStatus === "connecting"
                    ? "animate-pulse bg-[var(--nk-accent)]"
                    : knowledgeStatus === "degraded"
                      ? "bg-[var(--nk-danger)]"
                      : "bg-[var(--nk-ghost)]"
              }`} />
            </span>
            <span className="block text-[11.5px] text-[var(--nk-text-3)]">
              {knowledgeStatus === "ready"
                ? "Đang thêm RAG có nguồn vào lượt nhắn · bấm để ngắt"
                : knowledgeStatus === "connecting"
                  ? "Đang kiểm tra Wiii Service…"
                  : knowledgeStatus === "degraded"
                    ? knowledgeError ?? "Kết nối đang gián đoạn"
                    : "Tắt mặc định · agent cục bộ vẫn hoạt động độc lập"}
            </span>
          </button>
          {knowledgeStatus === "degraded" ? (
            <button
              type="button"
              role="menuitem"
              className="mx-2 mb-1 rounded-md px-2 py-1 text-[11px] text-[var(--nk-accent)] hover:bg-[var(--nk-overlay)]"
              onClick={() => {
                setOpen(false);
                onOpenManaged();
              }}
            >
              Mở Wiii Service để đăng nhập hoặc cấu hình
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function statusColor(status: NekoSessionStatus): string {
  if (status === "streaming" || status === "dispatching") return "bg-[var(--nk-accent)] animate-pulse";
  if (status === "idle") return "bg-[var(--nk-success)]";
  if (status === "error") return "bg-[var(--nk-danger)]";
  return "bg-[var(--nk-ghost)]";
}

function SessionRecoveryState({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <main
        className="grid min-h-0 flex-1 place-items-center px-6"
        role="status"
        aria-live="polite"
      >
        <div className="flex items-center gap-3 text-[13px] text-[var(--nk-text-3)]">
          <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" />
          Đang khôi phục lịch sử phiên…
        </div>
      </main>
    );
  }
  return (
    <main className="grid min-h-0 flex-1 place-items-center px-6">
      <section
        className="w-full max-w-md rounded-2xl border border-[var(--nk-border-strong)] bg-[var(--nk-raised)] p-6 shadow-sm"
        role="alert"
        aria-labelledby="neko-history-error-title"
      >
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--nk-danger-soft)] text-[var(--nk-danger)]">
            <AlertTriangle aria-hidden="true" className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h1 id="neko-history-error-title" className="text-[14px] font-semibold text-[var(--nk-text)]">
              Chưa thể mở lịch sử phiên
            </h1>
            <p className="mt-1 text-[12px] leading-5 text-[var(--nk-text-3)]">
              Neko Chill đã khóa việc tạo và mở phiên để không ghi đè dữ liệu đang có.
            </p>
            {error ? (
              <p className="mt-2 break-words rounded-lg bg-[var(--nk-inset)] px-3 py-2 text-[11px] leading-4 text-[var(--nk-text-3)]">
                {error}
              </p>
            ) : null}
            <button
              type="button"
              className="mt-4 inline-flex h-8 items-center gap-2 rounded-lg bg-[var(--nk-inverse)] px-3 text-[12px] font-medium text-[var(--nk-on-inverse)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--nk-focus-soft)]"
              onClick={onRetry}
            >
              <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
              Thử tải lại
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

export default function NekoChillApp({
  onOpenManaged = () => {},
}: { onOpenManaged?: () => void }) {
  const detect = useNekoAgentStore((state) => state.detect);
  const hydrate = useNekoSessionStore((state) => state.hydrate);
  const hydrated = useNekoSessionStore((state) => state.hydrated);
  const hydrating = useNekoSessionStore((state) => state.hydrating);
  const hydrationError = useNekoSessionStore((state) => state.hydrationError);
  const activeSessionId = useNekoSessionStore((state) => state.activeSessionId);
  const session = useNekoSessionStore((state) =>
    state.activeSessionId ? state.sessions[state.activeSessionId] : null,
  );
  const sessionsById = useNekoSessionStore((state) => state.sessions);
  const sessions = useMemo(() => Object.values(sessionsById), [sessionsById]);
  const {
    attachWorkspace,
    cancelTurn,
    closeSession,
    resolvePermission,
    sendPrompt,
    setActiveSession,
    setConfigOption,
  } = useNekoSessionStore();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [commandCenterOpen, setCommandCenterOpen] = useState(false);
  const [insertRequest, setInsertRequest] = useState<ComposerInsertRequest | null>(null);
  const desktopChrome = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  const compactWorkspace = useCompactWorkspace();
  const workspacePane = useNekoWorkspaceStore((state) =>
    activeSessionId ? state.sessions[activeSessionId] : undefined,
  );
  const {
    ensureSession: ensureWorkspaceSession,
    refresh: refreshWorkspace,
    restoreActivities,
    toggle: toggleWorkspace,
    close: closeWorkspace,
  } = useNekoWorkspaceStore();

  useEffect(() => {
    void detect();
    void hydrate();
    const stopIdleReaper = startIdleReaper();
    return () => {
      stopIdleReaper();
      void disposeAllNekoRuntimes();
    };
  }, [detect, hydrate]);

  useEffect(() => {
    setInspectorOpen(false);
  }, [activeSessionId]);

  useEffect(() => {
    if (!session?.workspace) return;
    ensureWorkspaceSession(session.id);
    restoreActivities(
      session.id,
      session.workspace,
      session.events.flatMap((event) =>
        event.data.type === "workspace-activity"
          ? [{
              id: event.data.activityId,
              title: event.data.title,
              kind: "file" as const,
              status: event.data.status,
              operation: event.data.operation ?? undefined,
              locations: event.data.locations,
              toolName: event.data.toolName,
              detail: event.data.detail,
            }]
          : [],
      ),
    );
    void refreshWorkspace(session.id, session.workspace);
  }, [
    ensureWorkspaceSession,
    refreshWorkspace,
    restoreActivities,
    session?.id,
    session?.workspace?.path,
  ]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandCenterOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleProjectCommand = async () => {
    if (!session) return;
    if (session.workspace) {
      if (!useNekoWorkspaceStore.getState().sessions[session.id]?.open) {
        if (compactWorkspace) setSidebarOpen(false);
        toggleWorkspace(session.id);
      }
      void refreshWorkspace(session.id, session.workspace);
      return;
    }
    const workspace = await chooseWorkspaceFolder();
    if (workspace) await attachWorkspace(session.id, workspace);
  };

  const handleClientCommand = (command: ClientCommandName) => {
    if (command === "new") setActiveSession(null);
    else if (command === "project") void handleProjectCommand();
    else if (command === "search") setCommandCenterOpen(true);
    else setInspectorOpen(true);
  };

  const insertIntoComposer = (text: string) => {
    setInsertRequest((current) => ({ text, token: (current?.token ?? 0) + 1 }));
  };

  const handleWorkbenchAction = (action: WorkbenchActionName) => {
    if (action === "new") setActiveSession(null);
    else if (action === "toggle-sidebar") setSidebarOpen((value) => !value);
    else if (action === "project") void handleProjectCommand();
    else setInspectorOpen(true);
  };

  const sidebarToggle = (
    <button
      type="button"
      className="grid h-8 w-8 place-items-center rounded-md text-[var(--nk-text-3)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--nk-focus-soft)]"
      aria-label={sidebarOpen ? "Ẩn cây dự án và phiên" : "Hiện cây dự án và phiên"}
      aria-pressed={!sidebarOpen}
      title={sidebarOpen ? "Ẩn cây dự án và phiên" : "Hiện cây dự án và phiên"}
      onClick={() => setSidebarOpen((value) => !value)}
    >
      {sidebarOpen ? (
        <PanelLeftClose aria-hidden="true" className="h-4 w-4" />
      ) : (
        <PanelLeft aria-hidden="true" className="h-4 w-4" />
      )}
    </button>
  );

  return (
    <div className="nk-root flex h-screen flex-col bg-[var(--nk-canvas)] text-[var(--nk-text)]">
      <TitleBar
        minimal
        leading={<ModeSwitcher onOpenManaged={onOpenManaged} />}
        commandCenter={{
          label: "Tìm phiên hoặc chạy lệnh",
          onClick: () => setCommandCenterOpen(true),
        }}
        trailing={sidebarToggle}
      />
      {!desktopChrome ? (
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--nk-border)] bg-[var(--nk-sidebar)] px-2">
          <ModeSwitcher onOpenManaged={onOpenManaged} />
          <div className="flex-1" />
          <button
            type="button"
            className="flex h-8 min-w-8 items-center gap-2 rounded-lg border border-[var(--nk-border)] bg-[var(--nk-raised)] px-2.5 text-[11.5px] text-[var(--nk-text-3)] hover:text-[var(--nk-text)]"
            aria-label="Tìm phiên hoặc chạy lệnh"
            onClick={() => setCommandCenterOpen(true)}
          >
            <Search aria-hidden="true" className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Tìm hoặc chạy lệnh</span>
            <kbd className="hidden text-[9px] text-[var(--nk-ghost)] md:inline">Ctrl K</kbd>
          </button>
          {sidebarToggle}
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1">
        {!hydrated ? (
          <SessionRecoveryState
            loading={hydrating || !hydrationError}
            error={hydrationError}
            onRetry={() => void hydrate()}
          />
        ) : (
          <>
            {sidebarOpen ? <SessionSidebar /> : null}
            {session ? (
          <div className="relative flex min-w-0 flex-1">
            <Group
              orientation="horizontal"
              id={`neko-workspace-layout-${session.id}`}
              className="min-w-0 flex-1"
            >
              <Panel
                id="neko-chat"
                defaultSize={workspacePane?.open && !compactWorkspace ? 48 : 100}
                minSize={28}
              >
            <div className="flex h-full min-w-0 flex-1 flex-col">
              <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--nk-border)] px-4">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor(session.status)}`} />
                  <div className="min-w-0">
                    <h1 className="truncate text-[13px] font-medium text-[var(--nk-text)]">
                      {session.title}
                    </h1>
                    <p className="truncate text-[10.5px] text-[var(--nk-text-3)]">
                      {session.workspace?.name ?? "Chưa gắn dự án"} · {session.agentName} · {NEKO_SESSION_STATUS_LABELS[session.status]}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    className={`relative rounded-md p-1.5 text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] ${workspacePane?.open ? "bg-[var(--nk-overlay)] text-[var(--nk-text)]" : ""}`}
                    aria-label={workspacePane?.open ? "Ẩn workspace" : "Mở workspace"}
                    aria-pressed={Boolean(workspacePane?.open)}
                    title="Files và Changes"
                    onClick={() => {
                      setInspectorOpen(false);
                      if (!workspacePane?.open && compactWorkspace) setSidebarOpen(false);
                      toggleWorkspace(session.id);
                    }}
                  >
                    <Files aria-hidden="true" className="h-3.5 w-3.5" />
                    {workspacePane?.unseenChanges ? (
                      <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-[var(--nk-accent)]" />
                    ) : null}
                  </button>
                  <button
                    type="button"
                    className={`rounded-md p-1.5 text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] ${inspectorOpen ? "bg-[var(--nk-overlay)] text-[var(--nk-text)]" : ""}`}
                    aria-label={inspectorOpen ? "Ẩn thông tin phiên" : "Mở thông tin phiên"}
                    aria-pressed={inspectorOpen}
                    title="Thông tin phiên"
                    onClick={() => {
                      if (!inspectorOpen) closeWorkspace(session.id);
                      setInspectorOpen((value) => !value);
                    }}
                  >
                    <Info aria-hidden="true" className="h-3.5 w-3.5" />
                  </button>
                  {session.status !== "exited" &&
                  session.status !== "stopping" &&
                  (session.status !== "error" || session.runtime !== null) ? (
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
                onInsertPrompt={insertIntoComposer}
              />
              <NekoComposer
                session={session}
                disabled={session.status === "connecting" || session.status === "error"}
                streaming={session.status === "streaming"}
                onSend={(text) => void sendPrompt(text)}
                onCancel={() => void cancelTurn()}
                onSetConfigOption={(optionId, value) => void setConfigOption(optionId, value)}
                onClientCommand={handleClientCommand}
                insertRequest={insertRequest}
              />
            </div>
              </Panel>
              {workspacePane?.open && !compactWorkspace ? (
                <>
                  <Separator className="wiii-resize-handle" />
                  <Panel id="neko-workspace" defaultSize={52} minSize={36}>
                    <NekoWorkspacePane session={session} />
                  </Panel>
                </>
              ) : null}
            </Group>
            {workspacePane?.open && compactWorkspace ? (
              <div className="absolute inset-0 z-30 bg-[var(--nk-composer)]">
                <NekoWorkspacePane session={session} />
              </div>
            ) : null}
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
                  onInsertCommand={(text) => {
                    insertIntoComposer(text);
                    setInspectorOpen(false);
                  }}
                />
              </>
            ) : null}
          </div>
            ) : (
              <NewSessionView />
            )}
          </>
        )}
      </div>
      {hydrated ? (
        <NekoCommandCenter
          open={commandCenterOpen}
          sessions={sessions}
          activeSession={session}
          sidebarOpen={sidebarOpen}
          onClose={() => setCommandCenterOpen(false)}
          onAction={handleWorkbenchAction}
          onSelectSession={setActiveSession}
          onInsertCommand={insertIntoComposer}
        />
      ) : null}
    </div>
  );
}
