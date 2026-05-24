/**
 * CodeStudioPanel — side panel for streaming code + live preview.
 *
 * Modeled on ArtifactPanel.tsx (same layout pattern).
 * Shows Code tab (streaming code display) and Preview tab (InlineVisualFrame).
 * Version bar for navigating between iterations.
 */
import { memo, useCallback, useState, useEffect, useRef, useMemo } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X, Copy, Check, Code2, Eye, Loader2, Download } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import type { CodeStudioSession } from "@/stores/code-studio-store";
import { InlineVisualFrame } from "@/components/common/InlineVisualFrame";

type StudioTab = "code" | "preview";

export const CodeStudioPanel = memo(function CodeStudioPanel({
  inline,
}: {
  inline?: boolean;
}) {
  const codeStudioPanelOpen = useUIStore((s) => s.codeStudioPanelOpen);
  const closeCodeStudio = useUIStore((s) => s.closeCodeStudio);
  const session = useCodeStudioStore((s) =>
    s.activeSessionId ? s.sessions[s.activeSessionId] : null,
  );

  if (!codeStudioPanelOpen || !session) return null;

  // Sprint 233: Inline mode — render directly inside resizable split panel
  if (inline) {
    return (
      <div className="h-full flex flex-col code-studio-panel">
        <CodeStudioContent session={session} onClose={closeCodeStudio} />
      </div>
    );
  }

  // Mobile / overlay fallback — original fixed positioning
  return (
    <AnimatePresence>
      <motion.div
        key="code-studio-panel"
        initial={{ x: "100%", opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: "100%", opacity: 0 }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className="fixed inset-x-0 top-[var(--titlebar-height,32px)] bottom-[var(--statusbar-height,24px)] w-full max-w-full min-w-0 border-l border-border z-40 flex flex-col shadow-xl code-studio-panel sm:left-auto sm:right-0 sm:w-[52vw] sm:max-w-[860px] sm:min-w-[420px]"
      >
        <CodeStudioContent session={session} onClose={closeCodeStudio} />
      </motion.div>
    </AnimatePresence>
  );
});

const CodeStudioContent = memo(function CodeStudioContent({
  session,
  onClose,
}: {
  session: CodeStudioSession;
  onClose: () => void;
}) {
  const explicitRequestedView = (
    session.metadata as Record<string, unknown> | undefined
  )?.requestedView as StudioTab | undefined;
  const preferredTab = explicitRequestedView === "preview" ? "preview" : "code";
  const setRequestedView = useCodeStudioStore((s) => s.setRequestedView);
  const [activeTab, setActiveTab] = useState<StudioTab>(preferredTab);
  const switchVersion = useCodeStudioStore((s) => s.switchVersion);
  const isStreaming = session.status === "streaming";
  const showPreviewBadge =
    session.status === "complete" && activeTab === "code";

  useEffect(() => {
    setActiveTab(preferredTab);
  }, [preferredTab, session.sessionId, session.activeVersion, session.status]);

  useEffect(() => {
    if (session.status !== "complete" || !session.code) return;
    if (explicitRequestedView === "code" || activeTab === "preview") return;
    setActiveTab("preview");
    setRequestedView(session.sessionId, "preview");
  }, [
    activeTab,
    explicitRequestedView,
    session.code,
    session.sessionId,
    session.status,
    setRequestedView,
  ]);

  const handleSelectTab = useCallback(
    (tab: StudioTab) => {
      setActiveTab(tab);
      setRequestedView(session.sessionId, tab);
    },
    [session.sessionId, setRequestedView],
  );

  const planItems = useMemo(() => {
    const code = session.code.toLowerCase();
    return [
      {
        label: "Thiết kế giao diện",
        done: code.includes("<style") || code.includes("css"),
      },
      {
        label: "Canvas / SVG",
        done: code.includes("<canvas") || code.includes("<svg"),
      },
      {
        label: "Logic xử lý",
        done: code.includes("<script") || code.includes("function"),
      },
      {
        label: "Điều khiển tương tác",
        done: code.includes('type="range"') || code.includes("<button"),
      },
      {
        label: "Kết nối Wiii Bridge",
        done:
          code.includes("wiiivisualbridge") || code.includes("reportresult"),
      },
    ];
  }, [session.code]);

  return (
    <>
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border shrink-0 code-studio-panel__header">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
          <Code2 size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-text truncate">
            {session.title}
          </div>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-text-tertiary">
            <span className="uppercase tracking-[0.08em]">
              {session.language}
            </span>
            {isStreaming && (
              <span className="flex items-center gap-1 text-[var(--accent)]">
                <Loader2 size={10} className="animate-spin" />
                Đang tạo...
              </span>
            )}
            {!isStreaming && (
              <span className="text-[var(--green)]">Đã xong</span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-tertiary hover:text-text transition-colors"
          aria-label="Đóng Code Studio"
        >
          <X size={16} />
        </button>
      </div>

      {/* Plan checklist during streaming */}
      {isStreaming && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 px-4 py-2 border-b border-border/50 text-[10px]">
          {planItems.map((item) => (
            <span
              key={item.label}
              className={
                item.done ? "text-[var(--green)]" : "text-text-tertiary/50"
              }
            >
              {item.done ? "\u2713" : "\u25CB"} {item.label}
            </span>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-border shrink-0">
        <TabButton
          icon={Code2}
          label="Mã"
          active={activeTab === "code"}
          onClick={() => handleSelectTab("code")}
        />
        <TabButton
          icon={Eye}
          label="Xem trước"
          active={activeTab === "preview"}
          onClick={() => handleSelectTab("preview")}
          disabled={isStreaming}
          badge={showPreviewBadge}
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto min-h-0">
        {activeTab === "code" && <CodeTab session={session} />}
        {activeTab === "preview" && <PreviewTab session={session} />}
      </div>

      {/* Version bar */}
      {session.versions.length > 1 && (
        <div className="flex items-center gap-2 px-4 py-2 border-t border-border shrink-0 overflow-x-auto">
          {session.versions.map((v) => (
            <button
              key={v.version}
              onClick={() => switchVersion(session.sessionId, v.version)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                v.version === session.activeVersion
                  ? "bg-[var(--accent)] text-white"
                  : "bg-surface-tertiary text-text-secondary hover:bg-border"
              }`}
            >
              v{v.version}
            </button>
          ))}
        </div>
      )}
    </>
  );
});

function TabButton({
  icon: Icon,
  label,
  active,
  onClick,
  disabled,
  badge,
}: {
  icon: typeof Code2;
  label: string;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  badge?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors ${
        active
          ? "text-[var(--accent)]"
          : disabled
            ? "text-text-tertiary/40 cursor-not-allowed"
            : "text-text-tertiary hover:text-text-secondary"
      }`}
    >
      <Icon size={14} />
      {label}
      {badge && (
        <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-[var(--accent)] animate-pulse" />
      )}
    </button>
  );
}

function CodeTab({ session }: { session: CodeStudioSession }) {
  const [copied, setCopied] = useState(false);
  const codeEndRef = useRef<HTMLDivElement>(null);
  const isStreaming = session.status === "streaming";

  // Auto-scroll to bottom during streaming (debounced via RAF)
  useEffect(() => {
    if (!isStreaming) return;
    const rafId = requestAnimationFrame(() => {
      codeEndRef.current?.scrollIntoView({ behavior: "smooth" });
    });
    return () => cancelAnimationFrame(rafId);
  }, [session.chunkCount, isStreaming]);

  const handleCopy = useCallback(async () => {
    try {
      const s = useCodeStudioStore.getState().sessions[session.sessionId];
      if (s) await navigator.clipboard.writeText(s.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard errors.
    }
  }, [session.sessionId]);

  const handleDownload = useCallback(() => {
    const s = useCodeStudioStore.getState().sessions[session.sessionId];
    if (!s) return;
    const blob = new Blob([s.code], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${s.title.replace(/\s+/g, "_").toLowerCase()}.html`;
    a.click();
    URL.revokeObjectURL(url);
  }, [session.sessionId]);

  const lineCount = session.code.split("\n").length;

  return (
    <div className="relative h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/50 shrink-0">
        <span className="text-[10px] text-text-tertiary">
          {lineCount} dòng · {session.code.length} byte
          {isStreaming && session.totalBytes > 0 && (
            <>
              {" "}
              · {Math.round((session.code.length / session.totalBytes) * 100)}%
            </>
          )}
        </span>
        <div className="flex gap-1">
          <button
            onClick={handleCopy}
            disabled={isStreaming}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-surface-tertiary hover:bg-border text-text-secondary transition-colors disabled:opacity-40"
            title="Sao chép"
          >
            {copied ? (
              <Check size={12} className="text-green-500" />
            ) : (
              <Copy size={12} />
            )}
            {copied ? "Đã chép" : "Sao chép"}
          </button>
          <button
            onClick={handleDownload}
            disabled={isStreaming}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-surface-tertiary hover:bg-border text-text-secondary transition-colors disabled:opacity-40"
            title="Tải xuống"
          >
            <Download size={12} />
          </button>
        </div>
      </div>

      {/* Code display */}
      <div className="flex-1 overflow-auto p-4 font-mono text-[13px] leading-relaxed code-studio-panel__code">
        <pre className="whitespace-pre-wrap break-words text-text-secondary">
          <code>{session.code}</code>
          {isStreaming && (
            <span className="code-studio-cursor" aria-hidden="true" />
          )}
        </pre>
        <div ref={codeEndRef} />
      </div>
    </div>
  );
}

function PreviewTab({ session }: { session: CodeStudioSession }) {
  if (session.status === "streaming") {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-tertiary py-16">
        <Loader2 size={32} className="mb-3 animate-spin opacity-50" />
        <p className="text-sm">
          Đang tạo mã, bản xem trước sẽ hiện sau khi hoàn thành.
        </p>
      </div>
    );
  }

  if (!session.code) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-tertiary py-16">
        <Eye size={32} className="mb-3 opacity-50" />
        <p className="text-sm">Không có mã để xem trước.</p>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 code-studio-panel__preview">
      <InlineVisualFrame
        html={session.code}
        title={session.title}
        sessionId={session.sessionId}
        className="w-full h-full"
        frameKind="app"
        sizingMode="viewport"
        shellVariant="immersive"
        hostShellMode="force"
        showTweaksToggle
      />
    </div>
  );
}
