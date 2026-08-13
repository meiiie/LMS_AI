import { useState, useEffect } from "react";
import { Minus, Square, X, PanelLeftClose, PanelLeft } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { APP_NAME } from "@/lib/constants";

/**
 * Check if running inside Tauri webview.
 * Outside Tauri (plain browser), window.__TAURI_INTERNALS__ is undefined.
 */
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

interface TitleBarProps {
  /** Hide cloud-shell controls (sidebar toggle) on standalone surfaces
   *  (login, Neko Chill) — window controls + drag region only. */
  minimal?: boolean;
}

export function TitleBar({ minimal = false }: TitleBarProps) {
  const { sidebarOpen, toggleSidebar } = useUIStore();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [appWindow, setAppWindow] = useState<any>(null);
  const [tauri, setTauri] = useState(false);

  useEffect(() => {
    const isTauriEnv = isTauri();
    setTauri(isTauriEnv);
    if (isTauriEnv) {
      import("@tauri-apps/api/window")
        .then((mod) => setAppWindow(mod.getCurrentWindow()))
        .catch(() => {});
    }
  }, []);

  // Sprint 231: Hide TitleBar on web — only show on Tauri desktop (needs window controls + drag)
  // Sidebar toggle moves to inline button in chat area via ChatView
  if (!tauri) return null;

  return (
    <div
      className="flex items-center h-11 bg-surface border-b border-border select-none"
      data-tauri-drag-region
    >
      {/* Left: Toggle sidebar + App name */}
      <div className="flex items-center gap-2 px-3">
        {!minimal ? (
          <button
            onClick={toggleSidebar}
            className="p-1 rounded hover:bg-surface-tertiary transition-colors"
            title={sidebarOpen ? "Ẩn sidebar" : "Hiện sidebar"}
          >
            {sidebarOpen ? (
              <PanelLeftClose size={16} className="text-text-secondary" />
            ) : (
              <PanelLeft size={16} className="text-text-secondary" />
            )}
          </button>
        ) : null}
        <span
          className="text-sm font-semibold text-text-secondary"
          data-tauri-drag-region
        >
          {APP_NAME}
        </span>
      </div>

      {/* Center: Drag region */}
      <div className="flex-1" data-tauri-drag-region />

      {/* Right: Window controls (only in Tauri) */}
      {appWindow && (
        <div className="flex items-center">
          <button
            onClick={() => appWindow.minimize()}
            className="flex items-center justify-center w-11 h-11 hover:bg-surface-tertiary transition-colors"
            aria-label="Thu nhỏ"
          >
            <Minus size={14} className="text-text-secondary" />
          </button>
          <button
            onClick={() => appWindow.toggleMaximize()}
            className="flex items-center justify-center w-11 h-11 hover:bg-surface-tertiary transition-colors"
            aria-label="Phóng to"
          >
            <Square size={12} className="text-text-secondary" />
          </button>
          <button
            onClick={() => appWindow.close()}
            className="flex items-center justify-center w-11 h-11 hover:bg-red-500 hover:text-white transition-colors"
            aria-label="Đóng"
          >
            <X size={14} className="text-text-secondary hover:text-white" />
          </button>
        </div>
      )}
    </div>
  );
}
