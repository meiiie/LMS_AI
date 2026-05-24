/**
 * CodeStudioCard — inline code streaming widget in chat (Claude Artifacts pattern).
 *
 * Three phases:
 *   1. Planning — streaming, no code yet → shimmer bars
 *   2. Streaming — has code → live code editor + plan checklist
 *   3. Complete — collapsed card with "Xem code" / "Xem preview" buttons
 */
import { memo, useRef, useEffect, useMemo, useCallback } from "react";
import { CheckCircle2, Code2, Eye, Loader2 } from "lucide-react";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";

interface CodeStudioCardProps {
  sessionId: string;
}

export const CodeStudioCard = memo(function CodeStudioCard({
  sessionId,
}: CodeStudioCardProps) {
  const session = useCodeStudioStore((s) => s.sessions[sessionId]);
  const setActiveSession = useCodeStudioStore((s) => s.setActiveSession);
  const openCodeStudio = useUIStore((s) => s.openCodeStudio);
  const codeEndRef = useRef<HTMLDivElement>(null);

  const isStreaming = session?.status === "streaming";
  const hasCode = Boolean(session?.code);
  const lineCount = session?.code?.split("\n").length ?? 0;

  const planItems = useMemo(() => {
    if (!session?.code) return [];
    const code = session.code.toLowerCase();
    return [
      { label: "Giao di\u1EC7n", done: code.includes("<style") },
      { label: "Canvas", done: code.includes("<canvas") || code.includes("<svg") },
      { label: "Logic", done: code.includes("<script") || code.includes("function") },
      { label: "\u0110i\u1EC1u khi\u1EC3n", done: code.includes('type="range"') || code.includes("<button") },
      { label: "K\u1EBFt n\u1ED1i", done: code.includes("wiiivisualbridge") || code.includes("reportresult") },
    ];
  }, [session?.code]);

  useEffect(() => {
    if (!isStreaming || !hasCode) return;
    const rafId = requestAnimationFrame(() => {
      codeEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
    return () => cancelAnimationFrame(rafId);
  }, [isStreaming, hasCode, session?.code?.length]);

  const handleOpen = useCallback(() => {
    setActiveSession(sessionId);
    openCodeStudio();
  }, [sessionId, setActiveSession, openCodeStudio]);

  const handlePreview = useCallback(() => {
    setActiveSession(sessionId);
    useCodeStudioStore.getState().setRequestedView(sessionId, "preview");
    openCodeStudio();
  }, [sessionId, setActiveSession, openCodeStudio]);

  // Single return — avoids early returns that can cause React reconciler issues
  // with "Rendered fewer hooks than expected" when phase transitions change the tree.
  return (
    <article
      className="code-studio-card rounded-xl border border-border/60 overflow-hidden"
      data-status={session?.status ?? "missing"}
    >
      {!session ? null : isStreaming && !hasCode ? (
        /* Phase 1: Planning (streaming, no code yet) */
        <>
          <div className="flex items-center gap-3 px-3 py-2.5">
            <div className="w-7 h-7 rounded-lg bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
              <Code2 size={14} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-text truncate">{session.title}</div>
              <div className="text-[10px] text-[var(--accent)]">{"\u0110ang l\u00EAn k\u1EBF ho\u1EA1ch..."}</div>
            </div>
            <Loader2 size={16} className="animate-spin text-[var(--accent)]" />
          </div>
          <div className="px-3 pb-3 space-y-2">
            <div className="h-2 rounded bg-surface-tertiary/60 animate-pulse" style={{ width: "70%" }} />
            <div className="h-2 rounded bg-surface-tertiary/40 animate-pulse" style={{ width: "45%" }} />
          </div>
        </>
      ) : isStreaming && hasCode ? (
        /* Phase 2: Streaming (has code) */
        <>
          <div className="flex items-center gap-3 px-3 py-2.5">
            <Code2 size={14} className="text-[var(--accent)] shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-text truncate">{session.title}</div>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--accent)]">
              <Loader2 size={12} className="animate-spin" />
              {lineCount} {`d\u00F2ng`}
            </div>
          </div>
          {planItems.length > 0 && (
            <div className="flex flex-wrap gap-x-2.5 gap-y-0.5 px-3 py-1.5 border-t border-border/30 text-[9px]">
              {planItems.map((item) => (
                <span
                  key={item.label}
                  className={item.done ? "text-[var(--green)]" : "text-text-tertiary/40"}
                >
                  {item.done ? "\u2713" : "\u25CB"} {item.label}
                </span>
              ))}
            </div>
          )}
          <div className="max-h-[320px] overflow-auto bg-[#0f172a] text-[#e2e8f0] border-t border-border/30">
            <pre className="p-3 text-[11px] leading-relaxed font-mono whitespace-pre-wrap break-words m-0">
              <code>{session.code}</code>
              <span className="inline-block w-[2px] h-[14px] bg-[var(--accent)] animate-pulse ml-0.5 align-middle" />
              <div ref={codeEndRef} />
            </pre>
          </div>
        </>
      ) : (
        /* Phase 3: Complete */
        <>
          <div className="flex items-center gap-3 px-3 py-2.5">
            <div className="w-7 h-7 rounded-lg bg-[var(--green)]/10 text-[var(--green)] flex items-center justify-center shrink-0">
              <CheckCircle2 size={14} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-text truncate">{session?.title}</div>
              <div className="text-[10px] text-text-tertiary">
                {`\u0110\u00E3 ho\u00E0n th\u00E0nh \u00B7 ${lineCount} d\u00F2ng \u00B7 ${session?.language}`}
              </div>
            </div>
            <div className="flex gap-1.5 shrink-0">
              <button
                onClick={handleOpen}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-surface-tertiary hover:bg-border text-text-secondary transition-colors"
              >
                <Code2 size={11} /> Xem mã
              </button>
              {session?.visualSessionId && (
                <button
                  onClick={handlePreview}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium bg-[var(--accent)]/10 hover:bg-[var(--accent)]/20 text-[var(--accent)] transition-colors"
                >
                  <Eye size={11} /> Xem trước
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </article>
  );
});
