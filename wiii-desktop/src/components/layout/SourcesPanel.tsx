/**
 * SourcesPanel — push-aside side panel showing full source content.
 * Sprint 107: Wired to useUIStore sourcesPanelOpen/selectedSourceIndex.
 * Sprint 211: Professional UX redesign — type badges, thumbnails, image zoom,
 *             skeleton loading, refined bboxes, clear typography hierarchy.
 *             Push-aside layout: chat compresses when panel opens (Claude.ai pattern).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X, FileText, ExternalLink, ImageIcon, ZoomIn } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { SourceInfo } from "@/api/types";

/** Panel width constant — used for animation and inner content sizing. */
const PANEL_WIDTH = 400;

/** Infer source type from available fields for color-coded badges. */
function inferSourceType(source: SourceInfo): {
  label: string;
  color: string;
  bg: string;
} {
  if (source.image_url) {
    return {
      label: "PDF",
      color: "var(--accent-teal, #0d9488)",
      bg: "var(--accent-teal, #0d9488)",
    };
  }
  if (source.document_id) {
    return {
      label: "TÀI LIỆU",
      color: "var(--accent)",
      bg: "var(--accent)",
    };
  }
  if (source.url || source.source_type === "web") {
    return {
      label: "WEB",
      color: "var(--accent-blue, #2563eb)",
      bg: "var(--accent-blue, #2563eb)",
    };
  }
  return {
    label: "VĂN BẢN",
    color: "var(--accent-green, #16a34a)",
    bg: "var(--accent-green, #16a34a)",
  };
}

export function SourcesPanel() {
  const { sourcesPanelOpen, selectedSourceIndex, toggleSourcesPanel, selectSource } =
    useUIStore();
  const panelRef = useRef<HTMLDivElement>(null);

  // Get sources from the last assistant message that has them
  const sources = useChatStore((s) => {
    const conv = s.activeConversation();
    if (!conv) return [];
    // Walk backwards to find the latest message with sources
    for (let i = conv.messages.length - 1; i >= 0; i--) {
      const msg = conv.messages[i];
      if (msg.role === "assistant" && msg.sources && msg.sources.length > 0) {
        return msg.sources;
      }
    }
    return [];
  });

  // Close on Escape (only when zoom is NOT open — zoom handler has priority via capture phase)
  useEffect(() => {
    if (!sourcesPanelOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") toggleSourcesPanel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [sourcesPanelOpen, toggleSourcesPanel]);

  const selected =
    selectedSourceIndex !== null && sources[selectedSourceIndex]
      ? sources[selectedSourceIndex]
      : null;

  return (
    <AnimatePresence>
      {sourcesPanelOpen && (
        <motion.div
          ref={panelRef}
          initial={{ width: 0 }}
          animate={{ width: PANEL_WIDTH, transition: { duration: 0.3, ease: [0.25, 0.1, 0.25, 1] } }}
          exit={{ width: 0, transition: { duration: 0.25, ease: [0.25, 0.1, 0.25, 1] } }}
          className="shrink-0 overflow-hidden"
          role="complementary"
          aria-label="Nguồn tham khảo"
        >
          {/* Fixed-width inner container — prevents content reflow during width animation */}
          <div className="h-full flex flex-col bg-surface border-l border-border" style={{ width: PANEL_WIDTH }}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
              <div className="flex items-center gap-2">
                <FileText size={18} className="text-[var(--accent)]" />
                <span className="font-semibold text-[15px] text-text">
                  Nguồn tham khảo
                </span>
                <span className="text-[11px] font-medium text-text-tertiary bg-surface-tertiary px-1.5 py-0.5 rounded-full">
                  {sources.length}
                </span>
              </div>
              <button
                onClick={toggleSourcesPanel}
                className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-secondary transition-colors"
                aria-label="Đóng panel nguồn"
              >
                <X size={16} />
              </button>
            </div>

            {/* Source list */}
            <div className="flex-1 overflow-y-auto scroll-container">
              {sources.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-text-tertiary text-sm">
                  <FileText size={36} className="mb-2 opacity-30" />
                  <p>Mình chưa tìm được nguồn cho câu hỏi này.</p>
                </div>
              ) : (
                <div className="p-2 space-y-1">
                  {sources.map((source, i) => (
                    <SourceItem
                      key={i}
                      index={i}
                      source={source}
                      isSelected={selectedSourceIndex === i}
                      onSelect={() =>
                        selectSource(selectedSourceIndex === i ? null : i)
                      }
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Selected source detail */}
            <AnimatePresence>
              {selected && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1, transition: { duration: 0.2 } }}
                  exit={{ height: 0, opacity: 0, transition: { duration: 0.15 } }}
                  className="border-t border-border overflow-hidden"
                >
                  <div className="p-4 max-h-[45vh] overflow-y-auto scroll-container">
                    {/* Page image with bounding box overlay */}
                    {selected.image_url && (
                      <PageImageWithBboxes
                        imageUrl={selected.image_url}
                        boundingBoxes={selected.bounding_boxes}
                      />
                    )}
                    <div className="rounded-lg border border-border-secondary bg-surface-secondary/50 p-3">
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">
                        Nội dung trích dẫn
                      </div>
                      <div className="text-sm text-text">
                        <MarkdownRenderer content={selected.content} />
                      </div>
                      {selected.url && (
                        <a
                          href={selected.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-[var(--accent)] hover:underline"
                        >
                          Mở nguồn web
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Renders the page image with bounding box overlays (normalized 0-1 coords). */
function PageImageWithBboxes({
  imageUrl,
  boundingBoxes,
}: {
  imageUrl: string;
  boundingBoxes?: SourceInfo["bounding_boxes"];
}) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [zoomed, setZoomed] = useState(false);

  // Close zoom on Escape (capture phase — fires before panel's Escape handler)
  useEffect(() => {
    if (!zoomed) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setZoomed(false);
      }
    };
    window.addEventListener("keydown", handleKey, true);
    return () => window.removeEventListener("keydown", handleKey, true);
  }, [zoomed]);

  const handleZoomToggle = useCallback(() => {
    if (loaded) setZoomed((z) => !z);
  }, [loaded]);

  if (error) return null;

  const bboxElements = (isZoomed: boolean) =>
    boundingBoxes && boundingBoxes.length > 0
      ? boundingBoxes.map((box, i) => (
          <div
            key={i}
            className={`absolute rounded-sm pointer-events-none ${
              isZoomed
                ? "border-2 border-[var(--accent)] bg-[var(--accent)]/8"
                : "border border-[var(--accent)] bg-[var(--accent)]/5"
            }`}
            style={{
              left: `${box.x0 * 100}%`,
              top: `${box.y0 * 100}%`,
              width: `${(box.x1 - box.x0) * 100}%`,
              height: `${(box.y1 - box.y0) * 100}%`,
            }}
          />
        ))
      : null;

  return (
    <>
      <div className="mb-3 rounded-lg overflow-hidden border border-border bg-surface-tertiary group">
        <div
          className="relative cursor-pointer"
          onClick={handleZoomToggle}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleZoomToggle(); }}
          aria-label="Nhấn để phóng to ảnh trang tài liệu"
        >
          {/* Skeleton placeholder */}
          {!loaded && !error && (
            <div className="aspect-[3/4] skeleton-pulse flex items-center justify-center">
              <ImageIcon size={32} className="text-text-tertiary opacity-40" />
            </div>
          )}
          <img
            src={imageUrl}
            alt="Trang tài liệu"
            className={`w-full h-auto transition-opacity duration-300 ${
              loaded ? "opacity-100" : "opacity-0 absolute inset-0"
            }`}
            onLoad={() => setLoaded(true)}
            onError={() => setError(true)}
            loading="lazy"
          />
          {/* Bounding box overlays (inline) */}
          {loaded && <div className="absolute inset-0">{bboxElements(false)}</div>}
          {/* Zoom hint */}
          {loaded && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors">
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-black/60 text-white text-xs opacity-0 group-hover:opacity-100 transition-opacity">
                <ZoomIn size={14} />
                Nhấn để phóng to
              </div>
            </div>
          )}
        </div>
        <div className="px-2 py-1.5 text-[11px] text-text-tertiary text-center border-t border-border/50">
          Ảnh trang tài liệu gốc
        </div>
      </div>

      {/* Fullscreen zoom overlay — stays fixed (global modal, independent of panel layout) */}
      <AnimatePresence>
        {zoomed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: 0.2 } }}
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8"
            onClick={() => setZoomed(false)}
          >
            <button
              className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
              onClick={(e) => { e.stopPropagation(); setZoomed(false); }}
              aria-label="Đóng phóng to"
            >
              <X size={20} />
            </button>
            <div
              className="relative max-w-[90vw] max-h-[90vh]"
              onClick={(e) => e.stopPropagation()}
            >
              <img
                src={imageUrl}
                alt="Trang tài liệu (phóng to)"
                className="max-w-full max-h-[90vh] object-contain rounded-lg"
              />
              {/* Bounding box overlays (zoomed — thicker borders) */}
              <div className="absolute inset-0">{bboxElements(true)}</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function SourceItem({
  index,
  source,
  isSelected,
  onSelect,
}: {
  index: number;
  source: SourceInfo;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const sourceType = inferSourceType(source);

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
        isSelected
          ? "bg-[var(--accent)]/10 border border-[var(--accent)]/30"
          : "hover:bg-surface-secondary hover:border-border-secondary border border-transparent"
      }`}
    >
      <div className="flex items-start gap-2.5">
        {/* Number badge */}
        <span
          className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold shrink-0 mt-0.5 ${
            isSelected
              ? "bg-[var(--accent)] text-white"
              : "bg-[var(--accent)]/12 text-[var(--accent)]"
          }`}
        >
          {index + 1}
        </span>

        {/* Mini thumbnail */}
        {source.image_url && (
          <div className="w-10 h-10 rounded overflow-hidden shrink-0 bg-surface-tertiary border border-border/50">
            <img
              src={source.image_url}
              alt=""
              className="w-full h-full object-cover"
              loading="lazy"
            />
          </div>
        )}

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-0.5">
          {/* Type badge + page */}
          <div className="flex items-center gap-1.5">
            <span
              className="text-[9px] font-semibold uppercase tracking-wider px-1 py-px rounded"
              style={{
                color: sourceType.color,
                backgroundColor: `color-mix(in srgb, ${sourceType.bg} 12%, transparent)`,
              }}
            >
              {sourceType.label}
            </span>
            {source.page_number && (
              <span className="text-[10px] text-text-tertiary">
                · tr. {source.page_number}
              </span>
            )}
          </div>

          {/* Title */}
          <div className="text-[13px] font-semibold text-text line-clamp-2">
            {source.title}
          </div>

          {/* Snippet */}
          {source.content && !isSelected && (
            <div className="text-xs text-text-secondary line-clamp-2">
              {source.content.slice(0, 120)}
              {source.content.length > 120 ? "..." : ""}
            </div>
          )}
        </div>

        {source.document_id && (
          <ExternalLink size={12} className="shrink-0 text-text-tertiary mt-1" />
        )}
      </div>
    </button>
  );
}
