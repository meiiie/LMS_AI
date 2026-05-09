/**
 * PreviewGroup — Horizontal scrollable carousel of PreviewCards.
 * Sprint 166: Initial grid layout.
 * Sprint 200: Upgraded to horizontal snap-scroll carousel with nav arrows.
 * Sprint 233: Web search results → Claude-style compact search widget.
 *
 * Product previews → horizontal carousel (220px cards).
 * Web/link previews → compact scrollable search widget.
 * Document/other previews → original 2-col grid.
 * Keyboard: ArrowLeft/Right to navigate, Enter to open panel.
 */
import { useRef, useCallback, useState, useEffect } from "react";
import { ChevronLeft, ChevronRight, Globe } from "lucide-react";
import type { PreviewBlockData } from "@/api/types";
import { useUIStore } from "@/stores/ui-store";
import { PreviewCard } from "./PreviewCard";

interface PreviewGroupProps {
  block: PreviewBlockData;
  onPreviewClick?: (previewId: string) => void;
}

/** Extract domain from URL, fallback to raw string. */
function extractDomain(url?: string): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function PreviewGroup({ block, onPreviewClick }: PreviewGroupProps) {
  const openPreview = useUIStore((s) => s.openPreview);
  const containerRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  // Determine if this is a product carousel (all items are product type)
  const isProductCarousel =
    block.items.length > 0 &&
    block.items.every((item) => item.preview_type === "product");

  // Determine if this is a web search widget (all items are web or link type)
  const isWebSearch =
    block.items.length > 0 &&
    block.items.every(
      (item) => item.preview_type === "web" || item.preview_type === "link",
    );

  // Track scroll state for arrow visibility
  const updateScrollState = useCallback(() => {
    const el = containerRef.current;
    if (!el || !isProductCarousel) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, [isProductCarousel]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !isProductCarousel) return;
    updateScrollState();
    el.addEventListener("scroll", updateScrollState, { passive: true });
    // Also update on resize
    const ro = new ResizeObserver(updateScrollState);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", updateScrollState);
      ro.disconnect();
    };
  }, [isProductCarousel, updateScrollState, block.items.length]);

  const scrollBy = useCallback(
    (direction: "left" | "right") => {
      const el = containerRef.current;
      if (!el) return;
      const scrollAmount = 240; // ~1 card width + gap
      el.scrollBy({
        left: direction === "right" ? scrollAmount : -scrollAmount,
        behavior: "smooth",
      });
    },
    [],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const container = containerRef.current;
      if (!container) return;

      const cards = container.querySelectorAll<HTMLElement>("button");
      const focused = document.activeElement;
      const idx = Array.from(cards).indexOf(focused as HTMLElement);

      if (e.key === "ArrowRight" && idx < cards.length - 1) {
        e.preventDefault();
        cards[idx + 1]?.focus();
      } else if (e.key === "ArrowLeft" && idx > 0) {
        e.preventDefault();
        cards[idx - 1]?.focus();
      }
    },
    [],
  );

  // Phase 35 — filter out polluted preview items: missing URL, missing title,
  // or error-string artifacts ("Unknown tool", "Tool unavailable", "Lỗi: ...").
  // These are produced when LLM hallucinates tool names; they shouldn't
  // appear in the user-facing source list.
  if (block.items) {
    const _BAD_TITLE_PREFIXES = [
      "Unknown tool", "Tool unavailable", "Lỗi:", "Error:",
    ];
    block = {
      ...block,
      items: block.items.filter((item) => {
        if (!item.url || !item.title) return false;
        const title = String(item.title).trim();
        if (_BAD_TITLE_PREFIXES.some((p) => title.startsWith(p))) return false;
        return true;
      }),
    };
  }
  if (!block.items || block.items.length === 0) return null;

  // Web search widget layout — collapsed by default, answer first
  const [widgetExpanded, setWidgetExpanded] = useState(false);

  if (isWebSearch) {
    return (
      <div className="search-widget my-2" role="region" aria-label="Kết quả tìm kiếm">
        {/* Header — clickable toggle */}
        <button
          type="button"
          className="search-widget__header"
          onClick={() => setWidgetExpanded(!widgetExpanded)}
          aria-expanded={widgetExpanded}
        >
          <Globe size={14} className="search-widget__icon" />
          <span className="search-widget__query">
            {block.items.length} nguồn tham khảo
          </span>
          <svg
            width="12" height="12" viewBox="0 0 20 20" fill="currentColor"
            className={`search-widget__chevron ${widgetExpanded ? "search-widget__chevron--open" : ""}`}
          >
            <path d="M7.16 14.13C6.96 14.31 6.94 14.63 7.13 14.84 7.31 15.04 7.63 15.06 7.84 14.87L12.84 10.37C13.06 10.18 13.06 9.82 12.84 9.63L7.84 5.13C7.63 4.94 7.31 4.96 7.13 5.17 6.94 5.37 6.96 5.69 7.16 5.87L11.75 10 7.16 14.13Z" />
          </svg>
        </button>

        {/* Scrollable results list — only when expanded */}
        {widgetExpanded && (
        <div className="search-widget__list" role="list">
          {block.items.map((item) => {
            const domain = extractDomain(item.url);
            const faviconUrl = domain
              ? `https://www.google.com/s2/favicons?domain=${domain}&sz=32`
              : null;

            return (
              <a
                key={item.preview_id}
                className="search-widget__item"
                role="listitem"
                tabIndex={0}
                onClick={() => {
                  if (item.url) {
                    window.open(item.url, "_blank", "noopener,noreferrer");
                  }
                  onPreviewClick?.(item.preview_id);
                  openPreview(item.preview_id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (item.url) {
                      window.open(item.url, "_blank", "noopener,noreferrer");
                    }
                    onPreviewClick?.(item.preview_id);
                    openPreview(item.preview_id);
                  }
                }}
                title={item.title}
              >
                {faviconUrl ? (
                  <img
                    src={faviconUrl}
                    alt=""
                    width={16}
                    height={16}
                    className="search-widget__favicon"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                      // Show fallback globe via next sibling
                      const fallback = e.currentTarget.nextElementSibling as HTMLElement;
                      if (fallback) fallback.style.display = "flex";
                    }}
                  />
                ) : null}
                <span
                  className="search-widget__favicon-fallback"
                  style={{ display: faviconUrl ? "none" : "flex" }}
                >
                  <Globe size={12} />
                </span>
                <span className="search-widget__title">{item.title}</span>
                {domain && (
                  <span className="search-widget__domain">{domain}</span>
                )}
              </a>
            );
          })}
        </div>
        )}
      </div>
    );
  }

  // Product carousel layout
  if (isProductCarousel) {
    return (
      <div className="relative group/carousel my-2">
        {/* Scroll container */}
        <div
          ref={containerRef}
          className="flex gap-3 overflow-x-auto snap-x snap-mandatory scroll-smooth
            pb-2 -mx-1 px-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
          role="region"
          aria-roledescription="carousel"
          aria-label="Kết quả tìm kiếm sản phẩm"
          onKeyDown={handleKeyDown}
        >
          {block.items.map((item, idx) => (
            <div
              key={item.preview_id}
              role="group"
              aria-roledescription="slide"
              aria-label={`Sản phẩm ${idx + 1} trên ${block.items.length}`}
              className="snap-start flex-shrink-0 w-[220px]"
            >
              <PreviewCard
                item={item}
                onClick={() => {
                  onPreviewClick?.(item.preview_id);
                  openPreview(item.preview_id);
                }}
              />
            </div>
          ))}
        </div>

        {/* Left arrow */}
        {canScrollLeft && (
          <button
            onClick={() => scrollBy("left")}
            className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1
              w-8 h-8 rounded-full bg-[var(--surface,#fff)] border border-[var(--border,#e5e5e0)]
              shadow-md flex items-center justify-center
              opacity-0 group-hover/carousel:opacity-100 transition-opacity z-10
              hover:bg-[var(--surface-hover,#fafaf5)]"
            aria-label="Cuộn sang trái"
          >
            <ChevronLeft size={16} className="text-[var(--text-secondary,#6b6b6b)]" />
          </button>
        )}

        {/* Right arrow */}
        {canScrollRight && (
          <button
            onClick={() => scrollBy("right")}
            className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1
              w-8 h-8 rounded-full bg-[var(--surface,#fff)] border border-[var(--border,#e5e5e0)]
              shadow-md flex items-center justify-center
              opacity-0 group-hover/carousel:opacity-100 transition-opacity z-10
              hover:bg-[var(--surface-hover,#fafaf5)]"
            aria-label="Cuộn sang phải"
          >
            <ChevronRight size={16} className="text-[var(--text-secondary,#6b6b6b)]" />
          </button>
        )}
      </div>
    );
  }

  // Default grid layout for document/other previews
  return (
    <div
      ref={containerRef}
      className="grid grid-cols-1 sm:grid-cols-2 gap-2 my-2"
      role="list"
      aria-label="Nội dung xem trước"
      onKeyDown={handleKeyDown}
    >
      {block.items.map((item) => (
        <div key={item.preview_id} role="listitem">
          <PreviewCard
            item={item}
            onClick={() => {
              onPreviewClick?.(item.preview_id);
              openPreview(item.preview_id);
            }}
          />
        </div>
      ))}
    </div>
  );
}
