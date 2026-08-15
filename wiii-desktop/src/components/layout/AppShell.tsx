/**
 * AppShell — root layout: TitleBar + Sidebar + main + StatusBar.
 * Sprint 106: Disconnected banner above main content.
 * Sprint 107: SourcesPanel side panel.
 * Sprint 192: View routing — chat, system-admin, org-admin, settings.
 * Sprint 233: Resizable split-panel layout — artifacts/preview push chat left.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { AnimatePresence, motion } from "motion/react";
import { WifiOff, RefreshCw, Menu, Laptop } from "lucide-react";
import { TitleBar } from "./TitleBar";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { ToastContainer } from "@/components/common/Toast";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useSettingsStore } from "@/stores/settings-store";
import { slideDown } from "@/lib/animations";

const ChatView = lazy(async () => {
  const mod = await import("@/components/chat/ChatView");
  return { default: mod.ChatView };
});

const ContextPanel = lazy(async () => {
  const mod = await import("./ContextPanel");
  return { default: mod.ContextPanel };
});

const CharacterPanel = lazy(async () => {
  const mod = await import("./CharacterPanel");
  return { default: mod.CharacterPanel };
});

const SourcesPanel = lazy(async () => {
  const mod = await import("./SourcesPanel");
  return { default: mod.SourcesPanel };
});

const PreviewPanel = lazy(async () => {
  const mod = await import("./PreviewPanel");
  return { default: mod.PreviewPanel };
});

const ArtifactPanel = lazy(async () => {
  const mod = await import("./ArtifactPanel");
  return { default: mod.ArtifactPanel };
});

const SystemAdminView = lazy(async () => {
  const mod = await import("@/components/admin/SystemAdminView");
  return { default: mod.SystemAdminView };
});

const OrgAdminView = lazy(async () => {
  const mod = await import("@/components/org-admin/OrgAdminView");
  return { default: mod.OrgAdminView };
});

const SettingsView = lazy(async () => {
  const mod = await import("@/components/settings/SettingsView");
  return { default: mod.SettingsView };
});

const SoulBridgePanel = lazy(async () => {
  const mod = await import("@/components/soul-bridge/SoulBridgePanel");
  return { default: mod.SoulBridgePanel };
});

const WiiiConnectPage = lazy(async () => {
  const mod = await import("@/components/connect/WiiiConnectPage");
  return { default: mod.WiiiConnectPage };
});

const CodeStudioPanel = lazy(async () => {
  const mod = await import("./CodeStudioPanel");
  return { default: mod.CodeStudioPanel };
});

function ViewFallback({ label }: { label: string }) {
  return (
    <div className="flex flex-1 items-center justify-center bg-surface px-6 text-sm text-text-tertiary">
      {label}
    </div>
  );
}

/** Detect mobile viewport for full-screen overlay fallback */
function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return;
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }, [breakpoint]);
  return isMobile;
}

export function AppShell({ onOpenLocal }: { onOpenLocal?: () => void }) {
  const { sidebarOpen, activeView, setSidebarOpen, toggleSidebar } =
    useUIStore();
  const hasRightPanel = useUIStore((s) => s.hasRightPanel());
  const rightPane = useUIStore((s) => s.rightPane);
  const closeWorkspacePane = useUIStore((s) => s.closeWorkspacePane);
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const [workspaceConversationId, setWorkspaceConversationId] = useState<string | null>(
    activeConversationId,
  );
  const { status, isChecking, errorMessage, checkHealth } = useConnectionStore();
  const serverUrl = useSettingsStore((state) => state.settings.server_url);
  const isMobile = useIsMobile();

  const showDisconnected = status === "disconnected";

  // Sprint 192b: Hide main sidebar entirely when not in chat view (Claude.ai pattern)
  const isInChat = activeView === "chat";

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia("(max-width: 767px)");
    const closeForMobile = (matches: boolean) => {
      if (matches) {
        setSidebarOpen(false);
      }
    };

    closeForMobile(mediaQuery.matches);

    const handleChange = (event: MediaQueryListEvent) => {
      closeForMobile(event.matches);
    };

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", handleChange);
      return () => mediaQuery.removeEventListener("change", handleChange);
    }

    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, [setSidebarOpen]);

  // A selected preview/artifact belongs to one conversation. Never carry a
  // stale resource id into another thread.
  useEffect(() => {
    if (workspaceConversationId !== activeConversationId) {
      closeWorkspacePane();
      setWorkspaceConversationId(activeConversationId);
    }
  }, [activeConversationId, closeWorkspacePane, workspaceConversationId]);

  return (
    <div className="flex flex-col h-screen">
      <TitleBar
        trailing={onOpenLocal ? (
          <button
            type="button"
            onClick={onOpenLocal}
            className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs text-text-tertiary transition-colors hover:bg-surface-tertiary hover:text-text"
            aria-label="Mở không gian cục bộ"
            title="Không gian cục bộ"
          >
            <Laptop aria-hidden="true" size={14} />
            <span className="hidden xl:inline">Cục bộ</span>
          </button>
        ) : undefined}
      />
      <div className="flex flex-1 overflow-hidden">
        <div
          className={`shrink-0 sidebar-slide ${!isInChat ? "sidebar-hidden" : sidebarOpen ? "sidebar-open" : "sidebar-closed"}`}
        >
          <Sidebar />
        </div>
        {/* Sprint 231: Mobile backdrop overlay when sidebar is open */}
        <div
          className={`sidebar-backdrop ${!sidebarOpen || !isInChat ? "hidden" : ""}`}
          onClick={toggleSidebar}
          aria-hidden="true"
        />
        {/* Sprint 231: Mobile menu button (only visible <768px when sidebar closed) */}
        {isInChat && !sidebarOpen && (
          <button
            className="mobile-menu-btn hidden"
            onClick={toggleSidebar}
            aria-label="Menu"
          >
            <Menu size={18} />
          </button>
        )}
        <main className="flex-1 flex flex-col overflow-hidden transition-all duration-200">
          {/* Disconnected banner */}
          <AnimatePresence>
            {showDisconnected && (
              <motion.div
                variants={slideDown}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="flex items-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-800 text-sm"
                role="alert"
                aria-live="assertive"
              >
                <WifiOff size={14} className="shrink-0 text-red-500" />
                <span className="flex-1 text-red-700 dark:text-red-300">
                  Mình mất liên lạc với server rồi.
                  <span className="ml-1 text-red-600/80 dark:text-red-300/80">
                    {serverUrl || "Chưa chọn địa chỉ server"}
                    {errorMessage ? ` · ${errorMessage}` : ""}
                  </span>
                </span>
                <button
                  onClick={checkHealth}
                  disabled={isChecking}
                  aria-busy={isChecking}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors"
                >
                  <RefreshCw size={12} className={isChecking ? "animate-spin" : ""} />
                  {isChecking ? "Đang thử…" : "Thử lại nhé"}
                </button>
              </motion.div>
            )}
          </AnimatePresence>
          {/* Sprint 192: View routing */}
          {/* Sprint 211: SourcesPanel push-aside — chat compresses when panel opens (Claude.ai/ChatGPT pattern) */}
          {/* Sprint 233: Resizable split-panel — artifact/code-studio/preview push chat to the left */}
          {activeView === "chat" ? (
            <Group
              orientation="horizontal"
              id="wiii-main-layout"
              className="flex-1 min-h-0"
            >
              {/* Left: Chat + SourcesPanel */}
              <Panel
                id="chat-panel"
                defaultSize={hasRightPanel ? 45 : 100}
                minSize={25}
              >
                <div className="h-full flex overflow-hidden">
                  <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                    <Suspense
                      fallback={
                        <ViewFallback label="Wiii đang mở cuộc trò chuyện..." />
                      }
                    >
                      <ChatView />
                    </Suspense>
                  </div>
                  <Suspense fallback={null}>
                    <SourcesPanel />
                  </Suspense>
                </div>
              </Panel>

              {/* Right: Artifact / CodeStudio / Preview (resizable) */}
              {hasRightPanel && !isMobile && (
                <>
                  <Separator className="wiii-resize-handle" />
                  <Panel id="right-panel" defaultSize={55} minSize={30}>
                    <div className="h-full flex flex-col overflow-hidden">
                      <Suspense fallback={null}>
                        {rightPane.kind === "artifact" && <ArtifactPanel inline />}
                        {rightPane.kind === "code-studio" && <CodeStudioPanel inline />}
                        {rightPane.kind === "preview" && <PreviewPanel inline />}
                      </Suspense>
                    </div>
                  </Panel>
                </>
              )}
            </Group>
          ) : (
            <Suspense
              fallback={<ViewFallback label="Wiii đang mở không gian này..." />}
            >
              {activeView === "system-admin" && <SystemAdminView />}
              {activeView === "org-admin" && <OrgAdminView />}
              {activeView === "settings" && <SettingsView />}
              {activeView === "soul-bridge" && <SoulBridgePanel />}
              {activeView === "wiii-connect" && <WiiiConnectPage />}
            </Suspense>
          )}
        </main>
      </div>
      {/* Side panels — chat-only overlays for context/character + mobile fallback */}
      {activeView === "chat" && (
        <Suspense fallback={null}>
          <ContextPanel />
          <CharacterPanel />
          {/* Mobile fallback: panels render as fixed overlays on small screens */}
          {isMobile && (
            <>
              {rightPane.kind === "preview" && <PreviewPanel />}
              {rightPane.kind === "artifact" && <ArtifactPanel />}
              {rightPane.kind === "code-studio" && <CodeStudioPanel />}
            </>
          )}
        </Suspense>
      )}
      <StatusBar />
      <ToastContainer />
    </div>
  );
}
