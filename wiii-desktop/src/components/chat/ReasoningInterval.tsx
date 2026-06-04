import { useEffect, useMemo, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  ChevronRight,
  Clock3,
  FileSearch,
  Globe2,
  Image as ImageIcon,
  TerminalSquare,
  Wrench,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type {
  ActionTextBlockData,
  ArtifactBlockData,
  ContentBlock,
  PreviewBlockData,
  ScreenshotBlockData,
  ThinkingBlockData,
  ThinkingLevel,
  ToolExecutionBlockData,
  VisualBlockData,
} from "@/api/types";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { NODE_LABELS } from "@/lib/reasoning-labels";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import {
  ToolExecutionStrip,
  summarizeToolExecutionBlock,
} from "./ToolExecutionStrip";
import { ThinkingBlock } from "./ThinkingBlock";
import { ScreenshotBlock } from "./ScreenshotBlock";
import { PreviewGroup } from "./PreviewGroup";
import { ArtifactCard } from "./ArtifactCard";
import { VisualBlock } from "./VisualBlock";

export type ReasoningIntervalItem =
  | { kind: "thinking"; id: string; block: ThinkingBlockData }
  | { kind: "action"; id: string; block: ActionTextBlockData }
  | { kind: "tool"; id: string; block: ToolExecutionBlockData }
  | { kind: "status"; id: string; content: string }
  | { kind: "preview"; id: string; block: PreviewBlockData }
  | { kind: "artifact"; id: string; block: ArtifactBlockData }
  | { kind: "screenshot"; id: string; block: ScreenshotBlockData };

export interface ReasoningIntervalViewModel {
  id: string;
  stepId?: string;
  node?: string;
  label: string;
  summary?: string;
  phase?: string;
  isLive: boolean;
  durationSeconds?: number;
  items: ReasoningIntervalItem[];
  rawBlocks: ContentBlock[];
}

function formatIntervalDuration(seconds?: number): string {
  if (
    typeof seconds !== "number" ||
    !Number.isFinite(seconds) ||
    seconds <= 0
  ) {
    return "";
  }
  const rounded = Math.round(seconds * 10) / 10;
  const display = Number.isInteger(rounded)
    ? String(rounded)
    : rounded.toFixed(1);
  return `Nhịp ${display}s`;
}

function normalizeNode(node?: string) {
  return (node || "").toLowerCase().replace(/\s+/g, "_");
}

function getNodeLabel(node?: string) {
  return NODE_LABELS[normalizeNode(node)] || node || "Đang suy luận";
}

const WIII_FALLBACK_LABEL_LIVE = "Wiii đang xử lý";
const WIII_FALLBACK_LABEL_DONE = "Wiii đã xử lý xong";

/**
 * Header labels stay operational. Persona text and internal phase labels belong
 * in the expanded body or the final answer, not in the timeline chrome.
 */
function getIntervalHeaderLabel(interval: ReasoningIntervalViewModel) {
  if (interval.isLive) return WIII_FALLBACK_LABEL_LIVE;
  return WIII_FALLBACK_LABEL_DONE;
}

/** Full summary for the expanded body preview. */
function getIntervalSummary(interval: ReasoningIntervalViewModel) {
  return interval.summary?.trim() || interval.label?.trim() || "";
}

function buildPreviewLine(block: PreviewBlockData) {
  const first = block.items[0];
  if (!first) return "Đã đối chiếu một preview";
  return `${first.title}${first.snippet ? ` — ${first.snippet}` : ""}`;
}

function buildArtifactLine(block: ArtifactBlockData) {
  const artifact = block.artifact;
  if (!artifact) return "Đã tạo một artifact";
  return `${artifact.title}${artifact.artifact_type ? ` • ${artifact.artifact_type}` : ""}`;
}

function summarizeAction(block: ActionTextBlockData) {
  return {
    label: getNodeLabel(block.node),
    text: block.content,
  };
}

function resolveOperationIcon(
  kind: ReasoningIntervalItem["kind"],
  toolName?: string,
) {
  if (kind === "status") return Clock3;
  if (kind === "action") return ChevronRight;
  if (kind === "preview") return Globe2;
  if (kind === "artifact") return FileSearch;
  if (kind === "screenshot") return ImageIcon;
  if (kind === "tool" && toolName) {
    const { Icon } = summarizeToolExecutionBlock({
      type: "tool_execution",
      id: "__summary__",
      tool: { id: "__summary__", name: toolName },
      status: "pending",
    } as ToolExecutionBlockData);
    return Icon;
  }
  if (toolName?.includes("search")) return Globe2;
  if (toolName?.includes("python") || toolName?.includes("code"))
    return TerminalSquare;
  if (toolName?.includes("generate") || toolName?.includes("file"))
    return FileSearch;
  if (toolName?.includes("knowledge")) return BookOpen;
  return Wrench;
}

function _normalizeInlineText(value: string | undefined) {
  return (value || "").replace(/\s+/g, " ").trim().toLowerCase();
}
void _normalizeInlineText;

function renderThinkingMarkdown(block: ThinkingBlockData, withCursor = false) {
  const content = block.content?.trim() || "";
  if (!content) return null;
  return (
    <div className="reasoning-interval__thinking">
      <MarkdownRenderer content={content} />
      {withCursor && (
        <span className="reasoning-interval__cursor" aria-hidden="true" />
      )}
    </div>
  );
}

function buildCollapsedPreviewText(items: ReasoningIntervalItem[]) {
  for (const item of items) {
    if (item.kind !== "thinking") continue;
    const raw = item.block.content?.trim() || "";
    if (!raw) continue;
    const normalized = raw.replace(/\s+/g, " ").trim();
    if (!normalized) continue;
    if (normalized.length <= 180) return normalized;
    return `${normalized.slice(0, 179).trimEnd()}…`;
  }
  return "";
}

function OperationRow({
  icon: Icon,
  label,
  body,
  tone = "default",
}: {
  icon:
    | ComponentType<{ size?: string | number; className?: string }>
    | LucideIcon;
  label: string;
  body: string;
  tone?: "default" | "success" | "pending";
}) {
  return (
    <div className={`reasoning-op-row reasoning-op-row--${tone}`}>
      <div className="reasoning-op-row__icon" aria-hidden="true">
        <Icon size={12} />
      </div>
      <div className="reasoning-op-row__body">
        <div className="reasoning-op-row__label">{label}</div>
        <div className="reasoning-op-row__text">{body}</div>
      </div>
    </div>
  );
}

function renderOperationItem(
  item: ReasoningIntervalItem,
  thinkingLevel: ThinkingLevel,
) {
  if (item.kind === "status") {
    return (
      <OperationRow
        key={item.id}
        icon={resolveOperationIcon(item.kind)}
        label="Tiến trình"
        body={item.content}
        tone="pending"
      />
    );
  }

  if (item.kind === "action") {
    const action = summarizeAction(item.block);
    return (
      <OperationRow
        key={item.id}
        icon={resolveOperationIcon(item.kind)}
        label={action.label}
        body={action.text}
      />
    );
  }

  if (item.kind === "tool") {
    if (item.block.tool.name === "tool_create_visual_code") {
      return <ToolExecutionStrip key={item.id} block={item.block} />;
    }
    const summary = summarizeToolExecutionBlock(item.block);
    const body =
      [summary.argsLine, summary.resultLine].filter(Boolean).join(" • ") ||
      "Đang thực hiện một thao tác";
    return (
      <OperationRow
        key={item.id}
        icon={summary.Icon}
        label={summary.label}
        body={body}
        tone={summary.isPending ? "pending" : "success"}
      />
    );
  }

  if (thinkingLevel !== "detailed") return null;

  if (item.kind === "preview") {
    return (
      <OperationRow
        key={item.id}
        icon={resolveOperationIcon(item.kind)}
        label="Preview"
        body={buildPreviewLine(item.block)}
      />
    );
  }

  if (item.kind === "artifact") {
    return (
      <OperationRow
        key={item.id}
        icon={resolveOperationIcon(item.kind)}
        label="Artifact"
        body={buildArtifactLine(item.block)}
        tone="success"
      />
    );
  }

  if (item.kind === "screenshot") {
    return (
      <OperationRow
        key={item.id}
        icon={resolveOperationIcon(item.kind)}
        label="Ảnh kiểm chứng"
        body={item.block.label || item.block.url || "Đã cập nhật một ảnh chụp"}
      />
    );
  }

  return null;
}

/** Tool interval: clickable header + collapsible thinking body (mockup pattern) */
function ToolIntervalSection({
  children,
  thinkingAfter,
  defaultExpanded = false,
}: {
  children: ReactNode;
  thinkingAfter?: ReactNode;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  useEffect(() => {
    if (defaultExpanded) {
      setExpanded(true);
    }
  }, [defaultExpanded]);
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Don't trigger parent thinking block toggle
    setExpanded(!expanded);
  };
  return (
    <div className="reasoning-interval__tool-interval">
      <div
        role="button"
        tabIndex={0}
        className="reasoning-interval__tool-header"
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleClick(e as unknown as React.MouseEvent);
          }
        }}
        aria-expanded={expanded}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`reasoning-interval__tool-chevron ${expanded ? "reasoning-interval__tool-chevron--open" : ""}`}
        >
          <path d="M7.16 14.13C6.96 14.31 6.94 14.63 7.13 14.84 7.31 15.04 7.63 15.06 7.84 14.87L12.84 10.37C13.06 10.18 13.06 9.82 12.84 9.63L7.84 5.13C7.63 4.94 7.31 4.96 7.13 5.17 6.94 5.37 6.96 5.69 7.16 5.87L11.75 10 7.16 14.13Z" />
        </svg>
        {children}
      </div>
      {expanded && thinkingAfter && (
        <div className="reasoning-interval__tool-body">{thinkingAfter}</div>
      )}
    </div>
  );
}

function selectVisibleItems(
  items: ReasoningIntervalItem[],
  thinkingLevel: ThinkingLevel,
  isLive: boolean,
  keepExpandedTail = false,
) {
  const thinkingItems = items.filter(
    (item): item is Extract<ReasoningIntervalItem, { kind: "thinking" }> =>
      item.kind === "thinking",
  );

  if (thinkingLevel === "minimal") {
    return [];
  }

  if (thinkingLevel === "detailed") {
    return items;
  }

  if (thinkingLevel === "balanced") {
    if (thinkingItems.length <= 2) {
      return items;
    }

    const firstThinking = thinkingItems[0];
    const lastThinking = thinkingItems[thinkingItems.length - 1];
    if (!firstThinking || !lastThinking) {
      return items;
    }

    let visibleThinkingIds = new Set<string>();
    if (isLive) {
      const latestWindow = thinkingItems.slice(-2);
      visibleThinkingIds = new Set(
        [
          firstThinking,
          ...latestWindow.filter((item) => item.id != firstThinking.id),
        ].map((item) => item.id),
      );
      return items.filter(
        (item) => item.kind !== "thinking" || visibleThinkingIds.has(item.id),
      );
    }

    if (keepExpandedTail) {
      const latestWindow = thinkingItems.slice(-2);
      visibleThinkingIds = new Set(
        [
          firstThinking,
          ...latestWindow.filter((item) => item.id !== firstThinking.id),
        ].map((item) => item.id),
      );
      return items.filter(
        (item) => item.kind !== "thinking" || visibleThinkingIds.has(item.id),
      );
    }

    if (lastThinking.id === firstThinking.id) {
      visibleThinkingIds = new Set([firstThinking.id]);
      return items.filter(
        (item) => item.kind !== "thinking" || visibleThinkingIds.has(item.id),
      );
    }

    visibleThinkingIds = new Set([firstThinking.id, lastThinking.id]);
    return items.filter(
      (item) => item.kind !== "thinking" || visibleThinkingIds.has(item.id),
    );
  }

  return items;
}

export function ReasoningInterval({
  interval,
  thinkingLevel,
  isResponseComplete = false,
  onOpenInspector: _onOpenInspector,
}: {
  interval: ReasoningIntervalViewModel;
  thinkingLevel: ThinkingLevel;
  isResponseComplete?: boolean;
  onOpenInspector: () => void;
}) {
  // Use isResponseComplete as robust "done" signal (not dependent on isLive flag)
  const isDone = isResponseComplete || !interval.isLive;
  // Header: "đang suy nghĩ" (streaming) → "đã suy nghĩ xong" (done)
  const effectiveInterval = { ...interval, isLive: !isDone };
  const headerLabel = getIntervalHeaderLabel(effectiveInterval);
  void getIntervalSummary;
  const durationText = formatIntervalDuration(interval.durationSeconds);
  const keepLongTurnExpanded =
    thinkingLevel === "balanced" &&
    isDone &&
    typeof interval.durationSeconds === "number" &&
    interval.durationSeconds >= 12;

  // Code Studio delegation: when a tool_create_visual_code call targets a
  // session that Code Studio already owns, skip the inline tool render — the
  // Code Studio panel is responsible for showing that content. Mirrors
  // VisualBlock's delegation check so the tool trace and the visual don't
  // both duplicate into the reasoning timeline.
  const codeStudioSessions = useCodeStudioStore((s) => s.sessions);

  // Phase2: Auto-expand while streaming, auto-collapse when done (Claude pattern)
  const [userToggled, setUserToggled] = useState(false);
  const [userExpanded, setUserExpanded] = useState(false);
  const allItems = interval.items;
  const visibleItems = useMemo(
    () =>
      selectVisibleItems(
        allItems,
        thinkingLevel,
        !isDone,
        keepLongTurnExpanded,
      ),
    [allItems, isDone, keepLongTurnExpanded, thinkingLevel],
  );
  const collapsedPreview = useMemo(
    () =>
      buildCollapsedPreviewText(
        visibleItems.length > 0 ? visibleItems : allItems,
      ) || "",
    [allItems, visibleItems],
  );

  // Streaming → auto expanded. Done → auto collapsed. User click → manual override.
  const showBody = userToggled
    ? userExpanded
    : !isDone || thinkingLevel === "detailed" || keepLongTurnExpanded;

  const handleToggle = () => {
    setUserToggled(true);
    setUserExpanded(!showBody);
  };

  // Items render inline — thinking collapsible, operations always visible

  return (
    <section
      className={`reasoning-interval reasoning-interval--${isDone ? "complete" : "live"}`}
      data-testid="reasoning-interval"
      data-step-id={interval.stepId || ""}
    >
      <div className="reasoning-interval__main">
        {/* ONE header — Wiii persona label + chevron toggle */}
        <button
          className="reasoning-interval__header-btn"
          onClick={handleToggle}
          aria-expanded={showBody}
        >
          {/* Icon: animated sparkle when streaming, static check when done */}
          {!isDone ? (
            <span className="reasoning-interval__live-dot" />
          ) : (
            <svg
              className="reasoning-interval__header-icon"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
          )}
          <span className="reasoning-interval__header-label" aria-live="polite">
            {headerLabel}
          </span>
          {durationText && (
            <span className="reasoning-interval__header-duration">
              {durationText}
            </span>
          )}
          <svg
            width="12"
            height="12"
            viewBox="0 0 20 20"
            fill="currentColor"
            className={`reasoning-interval__chevron ${showBody ? "reasoning-interval__chevron--open" : ""}`}
          >
            <path d="M14.128 7.16482C14.3126 6.95983 14.6298 6.94336 14.835 7.12771C15.0402 7.31242 15.0567 7.62952 14.8721 7.83477L10.372 12.835C10.1755 13.0551 9.82445 13.0551 9.62788 12.835L5.12778 7.83477C4.94317 7.62952 4.95963 7.31242 5.16489 7.12771C5.37015 6.94336 5.68741 6.95983 5.87193 7.16482L9.99995 11.7519L14.128 7.16482Z" />
          </svg>
        </button>
        {!showBody && collapsedPreview ? (
          <div className="reasoning-interval__collapsed-preview">
            <MarkdownRenderer content={collapsedPreview} />
          </div>
        ) : null}

        {/* Thinking body: timeline line via ::before, contained here */}
        <div
          className={`reasoning-interval__thinking-body ${showBody ? "reasoning-interval__thinking-body--expanded" : "reasoning-interval__thinking-body--collapsed"}`}
          hidden={!showBody}
          aria-hidden={!showBody}
        >
          {(() => {
            // Group items: thinking shown inline, operations get their following thinking as expandable body
            const elements: React.ReactElement[] = [];
            for (let idx = 0; idx < visibleItems.length; idx++) {
              const item = visibleItems[idx];

              if (item.kind === "thinking") {
                const isLast =
                  idx === visibleItems.length - 1 ||
                  visibleItems
                    .slice(idx + 1)
                    .every((i) => i.kind !== "thinking");
                const showCursor = !isDone && isLast;
                elements.push(
                  <div key={item.id} className="reasoning-interval__segment">
                    {renderThinkingMarkdown(item.block, showCursor)}
                  </div>,
                );
                continue;
              }

              // Delegate to Code Studio panel when it owns the target session.
              if (
                item.kind === "tool" &&
                item.block.tool.name === "tool_create_visual_code"
              ) {
                const vsid = (
                  item.block.tool.args as Record<string, unknown> | undefined
                )?.visual_session_id;
                if (typeof vsid === "string" && codeStudioSessions[vsid]) {
                  continue;
                }
              }

              // Operation: collect the NEXT thinking item as its expandable body
              const operation = renderOperationItem(item, thinkingLevel);
              if (!operation) continue;

              let thinkingAfterNode: ReactNode = null;
              if (
                idx + 1 < visibleItems.length &&
                visibleItems[idx + 1].kind === "thinking"
              ) {
                const nextThinking = visibleItems[idx + 1];
                thinkingAfterNode = renderThinkingMarkdown(
                  (nextThinking as { block: ThinkingBlockData }).block,
                  false,
                );
                idx++; // Skip the thinking item — it's rendered inside the tool section
              }

              elements.push(
                <ToolIntervalSection
                  key={item.id}
                  thinkingAfter={thinkingAfterNode}
                  defaultExpanded={
                    Boolean(thinkingAfterNode) &&
                    (thinkingLevel === "detailed" ||
                      (thinkingLevel === "balanced" && showBody))
                  }
                >
                  {operation}
                </ToolIntervalSection>,
              );
            }
            return elements;
          })()}

          {/* Terminal label — shown when thinking is complete */}
          {isDone && (
            <div className="reasoning-interval__terminal">
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span>Wiii đã xem xong ≽^•⩊•^≼</span>
              {durationText && (
                <span className="reasoning-interval__header-duration">
                  {durationText}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function renderInspectorBlock(block: ContentBlock) {
  if (block.type === "thinking") {
    return (
      <ThinkingBlock
        key={block.id}
        content={block.content}
        toolCalls={block.toolCalls}
        savedDuration={
          block.startTime && block.endTime
            ? Math.round((block.endTime - block.startTime) / 1000)
            : undefined
        }
        label={block.label}
        summary={block.summary}
        summaryMode={block.summaryMode}
        phase={block.phase}
        thinkingLevel="detailed"
        autoExpand
      />
    );
  }

  if (block.type === "tool_execution") {
    return <ToolExecutionStrip key={block.id} block={block} />;
  }

  if (block.type === "action_text") {
    const action = summarizeAction(block);
    return (
      <OperationRow
        key={block.id}
        icon={ChevronRight}
        label={action.label}
        body={action.text}
      />
    );
  }

  if (block.type === "screenshot") {
    return <ScreenshotBlock key={block.id} block={block} />;
  }

  if (block.type === "preview") {
    return <PreviewGroup key={block.id} block={block} />;
  }

  if (block.type === "artifact") {
    return <ArtifactCard key={block.id} artifact={block.artifact} />;
  }

  if (block.type === "visual") {
    return (
      <VisualBlock key={block.id} block={block as VisualBlockData} embedded />
    );
  }

  if (block.type === "answer") {
    return (
      <div key={block.id} className="reasoning-inspector__answer">
        <MarkdownRenderer content={block.content} />
      </div>
    );
  }

  return null;
}

export function ThinkingInspectorDrawer({
  isOpen,
  title,
  blocks,
  onClose,
}: {
  isOpen: boolean;
  title: string;
  blocks: ContentBlock[];
  onClose: () => void;
}) {
  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.button
            type="button"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="reasoning-inspector__backdrop"
            onClick={onClose}
            aria-label="Đóng trace"
          />
          <motion.aside
            initial={{ opacity: 0, x: 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 28 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="reasoning-inspector"
            data-testid="reasoning-inspector-drawer"
          >
            <header className="reasoning-inspector__header">
              <div>
                <div className="reasoning-inspector__eyebrow">Debug trace</div>
                <h3 className="reasoning-inspector__title">{title}</h3>
              </div>
              <button
                type="button"
                className="reasoning-inspector__close"
                onClick={onClose}
                aria-label="Đóng trace"
              >
                <X size={16} />
              </button>
            </header>
            <div className="reasoning-inspector__body">
              {blocks.map((block) => renderInspectorBlock(block))}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}
