import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ChevronDown,
  Check,
  Copy,
  Clock,
  CheckCircle,
  Search,
  Globe,
  BookOpen,
  Wrench,
} from "lucide-react";
import type { ToolCallInfo } from "@/api/types";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";

import type { ThinkingLevel, ThinkingSummaryMode } from "@/api/types";
import { TOOL_LABELS, PHASE_LABELS } from "@/lib/reasoning-labels";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
  autoExpand?: boolean;
  savedDuration?: number;
  toolCalls?: ToolCallInfo[];
  label?: string;
  summary?: string;
  summaryMode?: ThinkingSummaryMode;
  phase?: string;
  thinkingLevel?: ThinkingLevel;
  continuation?: boolean;
}

const PREVIEW_SKIP_PATTERNS = [
  /^toi can:?$/i,
  /^minh can:?$/i,
  /^ke hoach:?$/i,
  /^ly do chot(?: la)?:?$/i,
  /^ghi chu:?$/i,
  /^buoc \d+[:.]?$/i,
  /^\d+[.)]$/,
];

const PREVIEW_PREFIX_PATTERNS = [
  /^toi can:?\s*/i,
  /^minh can:?\s*/i,
  /^ly do chot(?: la)?:?\s*/i,
  /^ke hoach:?\s*/i,
  /^ghi chu:?\s*/i,
];

const PREVIEW_TOOL_REPLACEMENTS: Array<[RegExp, string]> = [
  [/tool_knowledge_search/gi, "nguồn kiến thức liên quan"],
  [/tool_maritime_search/gi, "nguồn hàng hải liên quan"],
  [/tool_web_search/gi, "nguồn web phù hợp"],
  [/tool_search_news/gi, "nguồn tin cần đối chiếu"],
  [/tool_search_legal/gi, "nguồn pháp lý liên quan"],
  [/tool_search_maritime/gi, "nguồn hàng hải cần tra"],
  [/tool_current_datetime/gi, "mốc thời gian hiện tại"],
  [/tool_calculator/gi, "phép tính cần thiết"],
  [/tool_[a-z0-9_]+/gi, "một công cụ phù hợp"],
];

// Sprint 234: Increased from 160→280 to match backend adaptive thinking (no hardcoded summary limit)
function clampPreviewText(value: string, maxLength = 280): string {
  if (value.length <= maxLength) return value;
  const sliced = value.slice(0, maxLength);
  const lastSpace = sliced.lastIndexOf(" ");
  return `${(lastSpace > 120 ? sliced.slice(0, lastSpace) : sliced).trim()}...`;
}

function sanitizePreviewLine(line: string): string {
  let normalized = line
    .replace(/^[\s>*-]+/, "")
    .replace(/^\d+[.)]\s*/, "")
    .replace(/`+/g, "")
    .replace(/([.!?])(?=\S)/g, "$1 ")
    .replace(/\s+/g, " ")
    .trim();

  for (const pattern of PREVIEW_PREFIX_PATTERNS) {
    normalized = normalized.replace(pattern, "");
  }

  for (const [pattern, replacement] of PREVIEW_TOOL_REPLACEMENTS) {
    normalized = normalized.replace(pattern, replacement);
  }

  normalized = normalized
    .replace(/\b(?:json|yaml|markdown|cot|chain of thought)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();

  return normalized;
}

function buildPreviewText(content: string, fallback?: string): string {
  const cleanedLines = content
    .split(/\n+/)
    .map((line) => sanitizePreviewLine(line))
    .filter((line) => line.length > 0)
    .filter(
      (line) => !PREVIEW_SKIP_PATTERNS.some((pattern) => pattern.test(line)),
    );

  const segments = cleanedLines
    .flatMap((line) =>
      line
        .split(/(?<=[.!?])\s+/)
        .map((segment) => segment.trim())
        .filter((segment) => segment.length >= 20),
    )
    .filter((segment, index, all) => all.indexOf(segment) === index);

  if (segments.length > 0) {
    return clampPreviewText(segments[0]);
  }

  if (cleanedLines.length > 0) {
    return clampPreviewText(cleanedLines[0]);
  }

  if (!fallback) return "";
  return clampPreviewText(sanitizePreviewLine(fallback), 280);
}

function chooseCollapsedPreview(options: {
  header: string;
  summary?: string;
  derived?: string;
}) {
  const header = sanitizePreviewLine(options.header || "");
  const candidates = [options.summary, options.derived]
    .map((value) => sanitizePreviewLine(value || ""))
    .filter(
      (value, index, all) => value.length > 0 && all.indexOf(value) === index,
    )
    .filter((value) => !textsOverlap(value, header));

  if (candidates.length === 0) return "";

  const scored = candidates
    .map((value) => {
      const wordCount = value.split(/\s+/).filter(Boolean).length;
      const sentencePenalty = Math.max(0, wordCount - 18) * 3;
      return {
        value,
        score: value.length + sentencePenalty,
      };
    })
    .sort((a, b) => a.score - b.score);

  return scored[0]?.value || "";
}

function getPhaseHeader(phase?: string) {
  return phase ? PHASE_LABELS[phase] : undefined;
}

function normalizeForDisplay(value?: string) {
  return (value || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function textsOverlap(a?: string, b?: string) {
  const normalizedA = normalizeForDisplay(a);
  const normalizedB = normalizeForDisplay(b);
  if (!normalizedA || !normalizedB) return false;
  return (
    normalizedA === normalizedB ||
    normalizedA.includes(normalizedB) ||
    normalizedB.includes(normalizedA)
  );
}

function stripLeadingDuplicateParagraph(
  content: string,
  candidates: Array<string | undefined>,
): string {
  const normalizedCandidates = candidates
    .map((value) => sanitizePreviewLine(value || ""))
    .filter((value) => value.length > 0);

  if (normalizedCandidates.length === 0) return content;

  const paragraphs = content.split(/\n\s*\n/);
  if (paragraphs.length === 0) return content;

  const firstParagraph = sanitizePreviewLine(paragraphs[0] || "");
  const overlaps = normalizedCandidates.some((candidate) =>
    textsOverlap(firstParagraph, candidate),
  );
  if (!overlaps) return content;

  const remaining = paragraphs.slice(1).join("\n\n").trim();
  return remaining || content;
}

export function ThinkingBlock({
  content,
  isStreaming = false,
  autoExpand = false,
  savedDuration,
  toolCalls,
  label: customLabel,
  summary,
  summaryMode = "header_only",
  phase,
  thinkingLevel = "balanced",
  continuation = false,
}: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(
    thinkingLevel === "detailed" || autoExpand,
  );
  const [duration, setDuration] = useState(savedDuration || 0);
  const [copied, setCopied] = useState(false);
  const startTimeRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // D1: Track if block was ever completed — used to detect re-activation
  const wasCompletedRef = useRef(false);

  const handleCopy = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!content) return;
      try {
        await navigator.clipboard.writeText(content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Fallback for non-secure contexts
      }
    },
    [content],
  );

  useEffect(() => {
    if (autoExpand) {
      setExpanded(true);
    }
  }, [autoExpand]);

  useEffect(() => {
    if (isStreaming && !startTimeRef.current) {
      startTimeRef.current = Date.now();
      if (thinkingLevel === "detailed" || autoExpand) {
        setExpanded(true);
      }
      timerRef.current = setInterval(() => {
        if (startTimeRef.current) {
          setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
        }
      }, 1000);
    }

    if (!isStreaming && startTimeRef.current) {
      if (timerRef.current) clearInterval(timerRef.current);
      setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
      startTimeRef.current = null;
      wasCompletedRef.current = true;
      if (thinkingLevel !== "detailed") {
        const contentLen = content?.length ?? 0;
        const collapseDelay = Math.min(Math.max(1200, contentLen * 3), 4500);
        const collapseTimer = setTimeout(
          () => setExpanded(false),
          collapseDelay,
        );
        // Cancel collapse if block re-activates (becomes streaming again)
        return () => clearTimeout(collapseTimer);
      }
    }

    // D1: Re-expand only on RE-ACTIVATION (block was completed, then becomes live again)
    // Don't change initial expand behavior for balanced/minimal levels
    if (isStreaming && wasCompletedRef.current) {
      wasCompletedRef.current = false;
      setExpanded(true);
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isStreaming, thinkingLevel, content, autoExpand]);

  const hasContent = !!(content || (toolCalls && toolCalls.length > 0));
  const isComplete = !isStreaming;
  const phaseHeader = getPhaseHeader(phase);
  const defaultTitle = isStreaming ? "Tự Vấn" : "Tự Vấn";
  const summaryText = summary?.trim() || "";
  const titleSeed = customLabel?.trim() || "";
  const contentForDisplay = content
    ? stripLeadingDuplicateParagraph(content, [
        summaryText,
        titleSeed,
        phaseHeader,
      ])
    : "";
  const previewContent =
    !expanded && contentForDisplay ? buildPreviewText(contentForDisplay) : "";
  const expandedHeaderText = phaseHeader || titleSeed || defaultTitle;
  const collapsedHeaderText =
    titleSeed || phaseHeader || summaryText || defaultTitle;
  const headerText = expanded ? expandedHeaderText : collapsedHeaderText;
  const durationText = duration > 0 ? `${duration}s` : "";
  const collapsedPreview = chooseCollapsedPreview({
    header: collapsedHeaderText,
    summary: summaryMode === "body_fallback" ? summaryText : undefined,
    derived: previewContent.trim(),
  });
  const showPreviewLine = Boolean(
    collapsedPreview && !textsOverlap(collapsedPreview, collapsedHeaderText),
  );

  if (continuation) {
    return (
      <div
        className={`thinking-block thinking-block--continuation ${isStreaming ? "thinking-block--streaming" : "thinking-block--complete"}`}
      >
        <div className="thinking-block__continuation-shell">
          <div className="thinking-block__continuation-meta">
            {durationText && (
              <span className="thinking-block__duration">{durationText}</span>
            )}
            {isStreaming && <span className="thinking-block__live-dot" />}
          </div>
          <div className="thinking-block__content-shell thinking-block__content-shell--continuation">
            {contentForDisplay && (
              <div className="text-xs text-text-secondary leading-relaxed thinking-markdown">
                <MarkdownRenderer content={contentForDisplay} />
                {isStreaming && (!toolCalls || toolCalls.length === 0) && (
                  <span className="inline-block w-1.5 h-3.5 bg-text-tertiary opacity-40 ml-0.5 animate-pulse rounded-sm" />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`thinking-block group/thinking ${isStreaming ? "thinking-block--streaming" : "thinking-block--complete"}`}
    >
      <div className="flex items-start gap-2">
        {hasContent ? (
          <button
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            className="thinking-block__toggle"
          >
            <span className="thinking-block__status" aria-hidden="true">
              {isComplete ? (
                <motion.span
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: "spring", stiffness: 400, damping: 15 }}
                >
                  <CheckCircle
                    size={14}
                    className="text-[var(--accent-green)] shrink-0"
                  />
                </motion.span>
              ) : (
                <span className="relative shrink-0 flex items-center justify-center w-[16px] h-[16px]">
                  <span className="absolute inset-0 rounded-full border border-[var(--accent-orange)] animate-ping opacity-30" />
                  <Clock
                    size={12}
                    className="relative text-[var(--accent-orange)]"
                  />
                </span>
              )}
            </span>

            <span className="thinking-block__header-body">
              <span className="thinking-block__title-row">
                {phaseHeader && (
                  <span className="thinking-block__phase">{phaseHeader}</span>
                )}
                <span className="thinking-block__title">{headerText}</span>
                {durationText && (
                  <span className="thinking-block__duration">
                    {durationText}
                  </span>
                )}
                {isStreaming && <span className="thinking-block__live-dot" />}
              </span>
              {!expanded && showPreviewLine && (
                <span className="thinking-block__preview-line">
                  {collapsedPreview}
                  {isStreaming && (
                    <span
                      className="thinking-block__preview-caret"
                      aria-hidden="true"
                    />
                  )}
                </span>
              )}
            </span>

            <ChevronDown
              size={14}
              className={`thinking-block__chevron ${expanded ? "thinking-block__chevron--open" : ""}`}
            />
          </button>
        ) : (
          <span className="thinking-block__toggle">
            <span className="thinking-block__status" aria-hidden="true">
              {isStreaming ? (
                <Clock
                  size={14}
                  className="text-[var(--accent-orange)] animate-pulse"
                />
              ) : (
                <CheckCircle size={14} className="text-[var(--accent-green)]" />
              )}
            </span>
            <span className="thinking-block__header-body">
              <span className="thinking-block__title-row">
                <span className="thinking-block__title">{headerText}</span>
              </span>
              {!expanded && showPreviewLine && (
                <span className="thinking-block__preview-line">
                  {collapsedPreview}
                  {isStreaming && (
                    <span
                      className="thinking-block__preview-caret"
                      aria-hidden="true"
                    />
                  )}
                </span>
              )}
            </span>
          </span>
        )}

        {content && !isStreaming && (
          <button
            onClick={handleCopy}
            className="thinking-block__copy"
            title="Sao chép suy nghĩ"
            aria-label="Sao chép nội dung suy nghĩ"
          >
            {copied ? (
              <Check size={12} className="text-[var(--accent-green)]" />
            ) : (
              <Copy size={12} />
            )}
          </button>
        )}
      </div>

      {hasContent && (
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="overflow-hidden"
            >
              <div className="thinking-block__content-shell">
                {content && (
                  <div className="text-xs text-text-secondary leading-relaxed thinking-markdown">
                    <MarkdownRenderer content={contentForDisplay} />
                    {isStreaming && (!toolCalls || toolCalls.length === 0) && (
                      <span className="inline-block w-1.5 h-3.5 bg-text-tertiary opacity-40 ml-0.5 animate-pulse rounded-sm" />
                    )}
                  </div>
                )}

                {toolCalls && toolCalls.length > 0 && (
                  <div className="mt-2 space-y-1.5">
                    {toolCalls.map((tc, i) => (
                      <InlineToolCard
                        key={tc.id || i}
                        toolCall={tc}
                        isLast={i === toolCalls.length - 1}
                        isStreaming={isStreaming}
                      />
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  );
}

function ToolIcon({ name, spinning }: { name: string; spinning?: boolean }) {
  const cls = `shrink-0 ${spinning ? "animate-spin" : ""}`;
  const color = "var(--accent-orange)";

  if (name === "tool_knowledge_search" || name === "tool_maritime_search") {
    return <BookOpen size={14} className={cls} style={{ color }} />;
  }
  if (
    name === "tool_web_search" ||
    name === "tool_search_news" ||
    name === "tool_search_legal" ||
    name === "tool_search_maritime"
  ) {
    return <Globe size={14} className={cls} style={{ color }} />;
  }
  if (name === "tool_think") {
    return <Search size={14} className={cls} style={{ color }} />;
  }
  return <Wrench size={14} className={cls} style={{ color }} />;
}

interface ParsedToolResult {
  title?: string;
  domain?: string;
  score?: number;
  snippet: string;
}

function parseToolResult(name: string, result: string): ParsedToolResult {
  if (name === "tool_knowledge_search" || name === "tool_maritime_search") {
    try {
      const parsed = JSON.parse(result);
      if (parsed.title || parsed.document_title) {
        return {
          title: parsed.title || parsed.document_title,
          domain: parsed.domain_id || parsed.domain,
          score: parsed.score || parsed.relevance_score,
          snippet: parsed.content || parsed.snippet || truncateResult(result),
        };
      }
    } catch {
      // Not JSON
    }
    const titleMatch = result.match(
      /(?:Title|Tieu de|Document):\s*(.+?)(?:\n|$)/i,
    );
    if (titleMatch) {
      return {
        title: titleMatch[1].trim(),
        snippet: truncateResult(result.replace(titleMatch[0], "").trim()),
      };
    }
  }
  return { snippet: truncateResult(result) };
}

export function InlineToolCard({
  toolCall,
  isLast,
  isStreaming,
}: {
  toolCall: ToolCallInfo;
  isLast: boolean;
  isStreaming: boolean;
}) {
  const [resultExpanded, setResultExpanded] = useState(false);
  const hasResult = !!toolCall.result;
  const isPending = isLast && isStreaming && !hasResult;

  const argsPreview = toolCall.args
    ? Object.entries(toolCall.args)
        .slice(0, 2)
        .map(
          ([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`,
        )
        .join(", ")
    : "";

  const parsed = hasResult
    ? parseToolResult(toolCall.name, toolCall.result!)
    : null;
  const isRichResult = parsed && parsed.title;
  const toolLabel = TOOL_LABELS[toolCall.name] || toolCall.name;

  return (
    <div>
      <div className="th-tool-card">
        <ToolIcon name={toolCall.name} spinning={isPending} />
        <span className="th-tool-fn">{toolLabel}</span>

        {argsPreview && <span className="th-tool-args">{argsPreview}</span>}

        <span className="ml-auto shrink-0">
          {isPending ? (
            <span className="flex gap-0.5">
              <span
                className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
                style={{ animationDelay: "0s" }}
              />
              <span
                className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
                style={{ animationDelay: "0.2s" }}
              />
              <span
                className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
                style={{ animationDelay: "0.4s" }}
              />
            </span>
          ) : hasResult ? (
            <motion.span
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="flex items-center gap-1 text-[var(--accent-green)]"
            >
              <Check size={12} />
            </motion.span>
          ) : null}
        </span>
      </div>

      {isPending && <div className="th-shimmer-bar" />}

      {hasResult && isRichResult && (
        <button
          onClick={() => setResultExpanded(!resultExpanded)}
          className="th-tool-result-rich"
        >
          <div className="flex items-start gap-2">
            <BookOpen
              size={12}
              className="mt-0.5 shrink-0 text-[var(--accent-orange)]"
            />
            <div className="min-w-0 text-left">
              <div className="text-[11px] font-medium text-text-primary truncate">
                {parsed.title}
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                {parsed.domain && (
                  <span className="th-tool-domain-tag">{parsed.domain}</span>
                )}
                {parsed.score != null && (
                  <span className="text-[9px] text-text-tertiary tabular-nums">
                    {(parsed.score * 100).toFixed(0)}% relevance
                  </span>
                )}
              </div>
              {resultExpanded && (
                <div className="mt-1.5 text-[10px] text-text-secondary leading-relaxed">
                  {parsed.snippet}
                </div>
              )}
            </div>
            <ChevronDown
              size={10}
              className={`shrink-0 mt-1 text-text-tertiary transition-transform ${resultExpanded ? "rotate-0" : "-rotate-90"}`}
            />
          </div>
        </button>
      )}

      {hasResult && !isRichResult && (
        <div className="th-tool-result">
          {parsed?.snippet || truncateResult(toolCall.result!)}
        </div>
      )}

      {hasResult && isLast && isStreaming && (
        <div className="flex items-center gap-1.5 ml-[26px] mt-1 text-text-tertiary">
          <span className="flex gap-0.5">
            <span
              className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
              style={{ animationDelay: "0s" }}
            />
            <span
              className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
              style={{ animationDelay: "0.2s" }}
            />
            <span
              className="w-1 h-1 rounded-full bg-[var(--accent-orange)] animate-pulse-dot"
              style={{ animationDelay: "0.4s" }}
            />
          </span>
          <span className="text-[10px]">
            Wiii đang đối chiếu kết quả vừa lấy về...
          </span>
        </div>
      )}
    </div>
  );
}

function truncateResult(result: string): string {
  if (result.length <= 300) return result;
  const cut = result.slice(0, 300);
  const sp = cut.lastIndexOf(" ");
  return (sp > 200 ? cut.slice(0, sp) : cut) + "...";
}
