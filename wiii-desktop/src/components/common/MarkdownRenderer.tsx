import { lazy, Suspense, useDeferredValue, useMemo } from "react";
import { stripWiiiInternalMarkup } from "@/lib/internal-markup";
import { normalizeAssistantMarkdown } from "@/lib/assistant-markdown";
import { splitWidgetBlocks } from "./widget-segments";

const InlineHtmlWidget = lazy(() => import("./InlineHtmlWidget"));
const RichMarkdownSegment = lazy(async () => {
  const mod = await import("./RichMarkdownSegment");
  return { default: mod.RichMarkdownSegment };
});
const MarkdownLiteSegment = lazy(async () => {
  const mod = await import("./MarkdownLiteSegment");
  return { default: mod.MarkdownLiteSegment };
});
const MathMarkdownSegment = lazy(async () => {
  const mod = await import("./MathMarkdownSegment");
  return { default: mod.MathMarkdownSegment };
});

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function PendingWidgetSegment() {
  return (
    <div
      className="rounded-[24px] border border-[color-mix(in_srgb,var(--border)_78%,white)] bg-[linear-gradient(180deg,rgba(255,255,255,0.84),rgba(248,244,236,0.76))] px-5 py-5 text-sm text-text-secondary shadow-[var(--shadow-sm)]"
      data-testid="pending-inline-widget"
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-text-tertiary">
        Đang dựng widget
      </p>
      <p className="mt-2 leading-6">
        Wiii đang hoàn thiện khung tương tác để chèn ngay trong câu trả lời.
      </p>
    </div>
  );
}

function shouldUseRichMarkdown(content: string): boolean {
  const trimmed = content.trim();
  if (!trimmed) return false;

  return (
    /```|~~~/.test(trimmed) ||
    /(^|\n)\s{0,3}(#{1,6}\s|[-*+]\s|>\s|\d+[.)]\s)/m.test(trimmed) ||
    /!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)/.test(trimmed) ||
    /(^|\n)\|.+\|/m.test(trimmed) ||
    /\bhttps?:\/\/\S+/i.test(trimmed) ||
    /\$\$?/.test(trimmed) ||
    /[*_~`]/.test(trimmed) ||
    /<\/?[A-Za-z][^>]*>/.test(trimmed)
  );
}

// Phase 35 — only trigger math rendering when content contains REAL math
// markup, not currency `$` mentions that happen to bracket text.
// KaTeX's font (Main-Regular) lacks Vietnamese diacritic glyphs (`ệ`, `ạ`,
// `ậ`, `ị`...), so passing prose like "Brent $110.01 USD/thùng" through
// KaTeX crashes with "No character metrics for 'ệ'" → ErrorBoundary →
// answer disappears from the UI.
const VIETNAMESE_DIACRITIC_RE =
  /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]/;

function shouldUseMathMarkdown(content: string): boolean {
  // Block-level $$...$$
  const blockMath = /\$\$[\s\S]+?\$\$/;
  // LaTeX-only delimiters \( ... \) or \[ ... \]
  const latexDelim = /\\\(|\\\[/;
  // Inline $...$ (must be non-currency: math content cannot contain
  // Vietnamese diacritics)
  const inlineMath = /(?:^|[^\\$])\$([^$\n]{1,200})\$/;

  if (blockMath.test(content)) return true;
  if (latexDelim.test(content)) return true;

  const inlineMatch = content.match(inlineMath);
  if (inlineMatch && !VIETNAMESE_DIACRITIC_RE.test(inlineMatch[1])) {
    // ASCII-only math content → safe to render with KaTeX
    return true;
  }
  return false;
}

function shouldUseHtmlMarkdown(content: string): boolean {
  return /<\/?[A-Za-z][^>]*>/.test(content);
}

function PlainTextSegment({ content }: { content: string }) {
  const paragraphs = content
    .split(/\n\s*\n+/)
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) return null;

  return (
    <div className="markdown-plain space-y-4">
      {paragraphs.map((paragraph, index) => (
        <p
          key={`${index}-${paragraph.slice(0, 24)}`}
          className="whitespace-pre-wrap"
        >
          {paragraph}
        </p>
      ))}
    </div>
  );
}

export function MarkdownRenderer({
  content,
  className = "",
}: MarkdownRendererProps) {
  // Phase 35 — defer expensive markdown parsing during fast streaming.
  // React 18 `useDeferredValue` lets us yield to high-priority updates
  // (state changes, paint) when content updates rapidly. The deferred
  // value is rendered with stale content until parsing catches up; this
  // eliminates the perceived "giật" stutter when StreamBuffer flushes
  // 28 chars/frame and ReactMarkdown re-tokenizes the full string.
  // Reference: https://react.dev/reference/react/useDeferredValue
  const deferredContent = useDeferredValue(content);
  const safeContent = useMemo(
    () => normalizeAssistantMarkdown(stripWiiiInternalMarkup(deferredContent)),
    [deferredContent],
  );
  const segments = useMemo(() => splitWidgetBlocks(safeContent), [safeContent]);

  return (
    <div className={`markdown-content selectable ${className}`}>
      {segments.map((seg, i) => {
        if (seg.type === "widget") {
          if (seg.pending) {
            return <PendingWidgetSegment key={`widget-pending-${i}`} />;
          }
          return (
            <Suspense
              key={`widget-${i}`}
              fallback={
                <div className="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg text-sm animate-pulse">
                  Đang tải widget...
                </div>
              }
            >
              <InlineHtmlWidget
                code={seg.content}
                widgetId={`legacy-widget-${i}`}
              />
            </Suspense>
          );
        }

        if (!shouldUseRichMarkdown(seg.content)) {
          return <PlainTextSegment key={`plain-${i}`} content={seg.content} />;
        }

        const SegmentComponent = shouldUseMathMarkdown(seg.content)
          ? MathMarkdownSegment
          : shouldUseHtmlMarkdown(seg.content)
            ? RichMarkdownSegment
            : MarkdownLiteSegment;

        return (
          <Suspense
            key={`md-${i}`}
            fallback={<PlainTextSegment content={seg.content} />}
          >
            <SegmentComponent content={seg.content} />
          </Suspense>
        );
      })}
    </div>
  );
}
