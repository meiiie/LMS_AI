import React, { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type {
  ArtifactBlockData,
  ContentBlock,
  PreviewBlockData,
  ScreenshotBlockData,
  SubagentGroupBlockData,
  ThinkingBlockData,
  ThinkingLevel,
  ThinkingPhase,
  ToolExecutionBlockData,
  VisualBlockData,
} from "@/api/types";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import {
  ReasoningInterval,
  ThinkingInspectorDrawer,
  type ReasoningIntervalItem,
  type ReasoningIntervalViewModel,
} from "./ReasoningInterval";
import { ScreenshotBlock } from "./ScreenshotBlock";
import { SubagentGroup } from "./SubagentGroup";
import { PreviewGroup } from "./PreviewGroup";
import { ArtifactCard } from "./ArtifactCard";
import { VisualBlock } from "./VisualBlock";
import { ToolExecutionStrip } from "./ToolExecutionStrip";

function BlockErrorFallback({
  blockType,
  error,
  onRetry,
}: {
  blockType: string;
  error?: Error | null;
  onRetry?: () => void;
}) {
  return (
    <div
      className="rounded-lg border border-orange-300/50 bg-orange-50/40 dark:bg-orange-950/20 px-3 py-2 text-xs text-text-secondary flex items-center gap-2 flex-wrap"
      role="alert"
    >
      <AlertTriangle size={14} className="shrink-0 text-orange-500" aria-hidden="true" />
      <span className="flex-1 min-w-0">
        Không hiển thị được {blockType === "answer" ? "câu trả lời" : `khối ${blockType}`}
        {error?.message ? <> — <code className="text-[10px] opacity-70">{error.message.slice(0, 80)}</code></> : null}
      </span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 text-[11px] font-medium text-[var(--accent)] hover:underline focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:ring-offset-1 rounded"
        >
          Thử lại
        </button>
      )}
    </div>
  );
}

class BlockErrorBoundary extends React.Component<
  { children: React.ReactNode; blockType: string },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { hasError: true, error }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Phase 35 — log to console with structured context for debugging.
    // Previously silent → Vietnamese diacritic crashes (KaTeX) disappeared
    // entirely with no signal to user OR developer.
    console.warn(
      `[BlockErrorBoundary] ${this.props.blockType} crashed:`,
      error.message,
      info.componentStack?.split("\n").slice(0, 3).join("\n"),
    );
  }
  render() {
    if (this.state.hasError) {
      return (
        <BlockErrorFallback
          blockType={this.props.blockType}
          error={this.state.error}
          onRetry={() => this.setState({ hasError: false, error: null })}
        />
      );
    }
    return this.props.children;
  }
}

type ArticleFigureComposition = {
  visualId: string;
  narrativeAnchor: string;
  bridgeLabel: string;
  claim: string;
  chromeMode: string;
  pedagogicalRole: string;
};

type ArticleCompositionSegment =
  | {
    kind: "prose";
    id: string;
    content: string;
    surfaceRole: "lead" | "body" | "tail";
  }
  | {
    kind: "figure";
    id: string;
    figure: ArticleFigureComposition;
  }

type ArticleComposition = {
  answerIds: string[];
  entryId: string;
  figureIds: string[];
  answerIsLast: boolean;
  segments: ArticleCompositionSegment[];
};

type RenderItem =
  | { kind: "interval"; id: string; interval: ReasoningIntervalViewModel }
  | { kind: "block"; id: string; block: ContentBlock };

function roundDurationSeconds(rawSeconds: number | undefined): number | undefined {
  if (typeof rawSeconds !== "number" || !Number.isFinite(rawSeconds) || rawSeconds <= 0) {
    return undefined;
  }
  return Math.max(0.1, Math.round(rawSeconds * 10) / 10);
}

function durationSecondsFromBounds(
  startTime?: number,
  endTime?: number,
): number | undefined {
  if (typeof startTime !== "number" || typeof endTime !== "number" || endTime <= startTime) {
    return undefined;
  }
  return roundDurationSeconds((endTime - startTime) / 1000);
}

function sumRoundedDurations(values: Array<number | undefined>): number | undefined {
  const total = values.reduce<number>((sum, value) => (
    typeof value === "number" && Number.isFinite(value) && value > 0 ? sum + value : sum
  ), 0);
  return roundDurationSeconds(total);
}

const EDITORIAL_BRIDGE_LABELS: Record<string, string> = {
  comparison: "Minh họa so sánh",
  process: "Minh họa theo bước",
  matrix: "Minh họa ma trận",
  architecture: "Minh họa hệ thống",
  concept: "Sơ đồ ý chính",
  infographic: "Minh họa tổng hợp",
  chart: "Biểu đồ trung tâm",
  timeline: "Dòng thời gian",
  map_lite: "Bản đồ tâm điểm",
};

const VISUAL_MARKER_RE = /\{visual_(\d+)\}|\[visuals rendered above\]/gi;
const VISUAL_INLINE_LABEL_RE = /\[(?:visual|figure)\s*:\s*[^\]]+\]/gi;

function splitEditorialAnswer(content: string): string[] {
  const paragraphSegments = content
    .split(/\n\s*\n+/)
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (paragraphSegments.length >= 2) return paragraphSegments;

  const singleParagraph = paragraphSegments[0] || content.trim();
  if (!singleParagraph) return [];

  const sentenceSegments = singleParagraph
    .split(/(?<=[.!?])\s+(?=[A-Z0-9À-ỹ])/u)
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (sentenceSegments.length >= 3) return sentenceSegments;

  return paragraphSegments;
}

function collectAnswerNarrative(blocks: ContentBlock[]): Array<Extract<ContentBlock, { type: "answer" }>> {
  return blocks
    .filter((block): block is Extract<ContentBlock, { type: "answer" }> => block.type === "answer")
    .filter((answer) => Boolean(answer.content));
}

function isDisposedVisualBlock(block: ContentBlock): block is VisualBlockData {
  return block.type === "visual" && block.status === "disposed";
}

function normalizeEditorialSnippet(value: string | undefined): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function stripEditorialVisualMarkers(value: string): string {
  return value
    .replace(VISUAL_MARKER_RE, " ")
    .replace(VISUAL_INLINE_LABEL_RE, " ")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function pushChunkIntoEditorialSlot(target: string[], chunk: string) {
  const cleaned = stripEditorialVisualMarkers(chunk);
  if (!cleaned) return;

  cleaned
    .split(/\n\s*\n+/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .forEach((segment) => target.push(segment));
}

function buildProseSlotsFromMarkers(
  content: string,
  figureCount: number,
): string[][] | null {
  if (!content || figureCount <= 0) return null;

  const slots = Array.from({ length: figureCount + 1 }, () => [] as string[]);
  const markerRegex = new RegExp(VISUAL_MARKER_RE.source, "gi");
  let currentSlot = 0;
  let cursor = 0;
  let sawMarker = false;

  for (const match of content.matchAll(markerRegex)) {
    const matchIndex = match.index;
    if (typeof matchIndex !== "number") continue;

    sawMarker = true;
    pushChunkIntoEditorialSlot(slots[currentSlot] || [], content.slice(cursor, matchIndex));

    const figureOrdinal = Number(match[1]);
    if (Number.isFinite(figureOrdinal) && figureOrdinal > 0) {
      currentSlot = Math.min(figureOrdinal, figureCount);
    }

    cursor = matchIndex + match[0].length;
  }

  if (!sawMarker) return null;

  pushChunkIntoEditorialSlot(slots[currentSlot] || [], content.slice(cursor));
  return slots;
}

function buildSyntheticEditorialNarrative(figures: VisualBlockData[]): string[] {
  if (figures.length === 0) return [];

  const firstFigure = figures[0]?.visual;
  const lastFigure = figures[figures.length - 1]?.visual;
  const total = figures.length;
  const snippets: string[] = [];
  const seen = new Set<string>();

  const pushUnique = (value: string) => {
    const cleaned = normalizeEditorialSnippet(value);
    if (!cleaned) return;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    snippets.push(cleaned);
  };

  pushUnique(
    `Minh se di qua ${total} figure nho de tach tung y, bat dau tu ${firstFigure?.title || "khung nhin mo dau"}.`,
  );

  if (figures.length > 1) {
    const middleFigure = figures[Math.min(1, figures.length - 1)]?.visual;
    pushUnique(middleFigure?.claim || middleFigure?.summary || "");
  }

  pushUnique(
    `Tu nhom figure nay, diem chot la ${lastFigure?.summary || lastFigure?.claim || lastFigure?.title || "y chinh can nam"}.`,
  );

  if (snippets.length < 2) {
    pushUnique(firstFigure?.summary || firstFigure?.claim || firstFigure?.title || "");
  }

  return snippets.slice(0, 3);
}

function buildArticleComposition(blocks: ContentBlock[]): ArticleComposition | null {
  const answers = collectAnswerNarrative(blocks);
  const visuals = blocks.filter(
    (block): block is VisualBlockData => block.type === "visual" && block.status !== "disposed",
  );

  if (visuals.length === 0) {
    return null;
  }

  const candidateVisuals = visuals.filter((visual) => visual.visual.shell_variant !== "immersive");
  if (candidateVisuals.length === 0) return null;

  const visualsByGroup = new Map<string, VisualBlockData[]>();
  for (const visual of candidateVisuals) {
    const groupId = visual.visual.figure_group_id || visual.visual.visual_session_id || visual.id;
    const existing = visualsByGroup.get(groupId) || [];
    existing.push(visual);
    visualsByGroup.set(groupId, existing);
  }

  const orderedCandidates = candidateVisuals
    .slice()
    .sort((left, right) => (
      blocks.findIndex((block) => block.id === left.id) - blocks.findIndex((block) => block.id === right.id)
    ));

  const groupedCandidates = Array.from(visualsByGroup.values())
    .filter((group) => group.length > 1)
    .sort((left, right) => right.length - left.length)[0];

  const selectedFigures = (groupedCandidates || (orderedCandidates.length > 1 ? orderedCandidates : orderedCandidates.slice(0, 1)))
    ?.slice()
    .sort((left, right) => (
      (left.visual.figure_index || 1) - (right.visual.figure_index || 1)
    ));
  if (!selectedFigures || selectedFigures.length === 0) return null;

  const answerContent = answers
    .map((answer) => answer.content)
    .filter(Boolean)
    .join("\n\n");
  const proseSlotsFromMarkers = answerContent
    ? buildProseSlotsFromMarkers(answerContent, selectedFigures.length)
    : null;
  const proseSegments = answerContent
    ? splitEditorialAnswer(stripEditorialVisualMarkers(answerContent))
    : buildSyntheticEditorialNarrative(selectedFigures);
  const hasMarkerProse = proseSlotsFromMarkers?.some((slot) => slot.length > 0) || false;
  if (proseSegments.length === 0 && !hasMarkerProse) return null;

  const proseBaseId = answers[0]?.id || selectedFigures[0]?.id || "editorial";

  const proseSlots = hasMarkerProse
    ? proseSlotsFromMarkers!
    : (() => {
      const slots = Array.from(
        { length: selectedFigures.length + 1 },
        () => [] as string[],
      );
      proseSegments.forEach((segment, index) => {
        const slotIndex = Math.min(index, selectedFigures.length);
        slots[slotIndex]?.push(segment);
      });
      return slots;
    })();

  const segments: ArticleCompositionSegment[] = [];
  const leadContent = proseSlots[0]?.join("\n\n").trim();
  if (leadContent) {
    segments.push({
      kind: "prose",
      id: `${proseBaseId}-lead`,
      content: leadContent,
      surfaceRole: "lead",
    });
  }

  selectedFigures.forEach((visual, index) => {
    segments.push({
      kind: "figure",
      id: visual.id,
      figure: {
        visualId: visual.id,
        narrativeAnchor: visual.visual.narrative_anchor || "after-lead",
        bridgeLabel: EDITORIAL_BRIDGE_LABELS[visual.visual.type] || "Minh họa trung tâm",
        claim: visual.visual.claim || "",
        chromeMode: visual.visual.chrome_mode || "editorial",
        pedagogicalRole: visual.visual.pedagogical_role || "mechanism",
      },
    });

    const proseAfterFigure = proseSlots[index + 1]?.join("\n\n").trim();
    if (!proseAfterFigure) return;
    const isTail = index === selectedFigures.length - 1;
    segments.push({
      kind: "prose",
      id: `${proseBaseId}-prose-${index + 1}`,
      content: proseAfterFigure,
      surfaceRole: isTail ? "tail" : "body",
    });
  });

  if (segments.filter((segment) => segment.kind === "figure").length === 0) return null;

  const entryId = answers[0]?.id || selectedFigures[0]?.id;
  if (!entryId) return null;

  const lastAnswerId = answers[answers.length - 1]?.id;
  const lastAnswerIndex = lastAnswerId
    ? blocks.findIndex((block) => block.id === lastAnswerId)
    : -1;

  return {
    answerIds: answers.map((answer) => answer.id),
    entryId,
    figureIds: selectedFigures.map((visual) => visual.id),
    answerIsLast: lastAnswerIndex === -1
      ? false
      : !blocks.slice(lastAnswerIndex + 1).some((candidate) => candidate.type === "answer"),
    segments,
  };
}

function reorderForDisplay(blocks: ContentBlock[]): ContentBlock[] {
  const answers = blocks.filter((block) => block.type === "answer");
  if (answers.length === 0) return blocks;

  const firstAnswerIndex = blocks.findIndex((block) => block.type === "answer");
  if (firstAnswerIndex === -1) return blocks;

  const pinnedArtifacts = blocks.filter(
    (block, index) => (block.type === "artifact" || block.type === "visual") && index < firstAnswerIndex,
  );
  if (pinnedArtifacts.length === 0) return blocks;

  const withoutPinnedArtifacts = blocks.filter(
    (block, index) => !((block.type === "artifact" || block.type === "visual") && index < firstAnswerIndex),
  );

  const lastAnswerIndex = withoutPinnedArtifacts.reduce((acc, block, index) => (
    block.type === "answer" ? index : acc
  ), -1);

  if (lastAnswerIndex === -1) return withoutPinnedArtifacts;

  return [
    ...withoutPinnedArtifacts.slice(0, lastAnswerIndex + 1),
    ...pinnedArtifacts,
    ...withoutPinnedArtifacts.slice(lastAnswerIndex + 1),
  ];
}

function mapBlockToIntervalItem(block: ContentBlock): ReasoningIntervalItem | null {
  switch (block.type) {
    case "thinking":
      return { kind: "thinking", id: block.id, block };
    case "action_text":
      return { kind: "action", id: block.id, block };
    case "tool_execution":
      return { kind: "tool", id: block.id, block };
    case "preview":
      return { kind: "preview", id: block.id, block };
    case "artifact":
      return { kind: "artifact", id: block.id, block };
    case "screenshot":
      return { kind: "screenshot", id: block.id, block };
    default:
      return null;
  }
}

function normalizeInlineText(value: string | undefined) {
  return (value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function extractComparableIntervalText(item: ReasoningIntervalItem) {
  if (item.kind === "thinking") return normalizeInlineText(item.block.content);
  if (item.kind === "action") return normalizeInlineText(item.block.content);
  if (item.kind === "status") return normalizeInlineText(item.content);
  return "";
}

function dedupeIntervalItems(items: ReasoningIntervalItem[]) {
  const deduped: ReasoningIntervalItem[] = [];

  for (const item of items) {
    const previous = deduped[deduped.length - 1];
    const currentComparableText = extractComparableIntervalText(item);
    const previousComparableText = previous ? extractComparableIntervalText(previous) : "";

    if (previous && currentComparableText !== "" && currentComparableText === previousComparableText) {
      const comparableKinds = ["thinking", "action", "status"];
      if (comparableKinds.includes(item.kind) && comparableKinds.includes(previous.kind)) {
        continue;
      }
    }

    if (
      item.kind === "tool"
      && previous?.kind === "tool"
      && item.block.tool.name === previous.block.tool.name
      && item.block.status === previous.block.status
    ) {
      const previousResult = normalizeInlineText(previous.block.tool.result);
      const currentResult = normalizeInlineText(item.block.tool.result);
      if (previousResult === currentResult) {
        continue;
      }
    }

    deduped.push(item);
  }

  return deduped;
}

function isDetailedOnlyBlock(block: ContentBlock) {
  return block.type === "preview" || block.type === "artifact" || block.type === "screenshot";
}

function isInspectorTraceBlock(block: ContentBlock) {
  return block.type === "thinking" || block.type === "action_text" || block.type === "tool_execution";
}

function shouldHideTechnicalTraceBlock(
  _block: ContentBlock,
  _thinkingLevel: ThinkingLevel,
  _showReasoningRail: boolean,
) {
  return false;
}

function isIntervalCandidate(
  block: ContentBlock,
  _thinkingLevel: ThinkingLevel,
): boolean {
  return block.type === "thinking";
}

function isIntervalTraceCompanionBlock(block: ContentBlock): boolean {
  return block.type === "tool_execution" || block.type === "action_text";
}

function getIntervalStepId(block: ContentBlock) {
  return block.stepId;
}

function getBlockNode(block?: ContentBlock) {
  if (!block) return undefined;
  return "node" in block ? block.node : undefined;
}

function matchesIntervalTraceBlock(
  interval: ReasoningIntervalViewModel,
  block: ContentBlock,
) {
  if (interval.rawBlocks.some((candidate) => candidate.id === block.id)) {
    return true;
  }
  if (interval.stepId && block.stepId === interval.stepId) {
    return true;
  }
  const blockNode = getBlockNode(block);
  if (interval.node && blockNode && interval.node === blockNode) {
    return true;
  }
  return false;
}

function isCompatibleIntervalBlock(
  currentBlocks: ContentBlock[],
  nextBlock: ContentBlock,
) {
  if (currentBlocks.length === 0) return true;
  const lastBlock = currentBlocks[currentBlocks.length - 1];
  if (!lastBlock) return true;

  const lastStepId = getIntervalStepId(lastBlock);
  const nextStepId = getIntervalStepId(nextBlock);
  if (lastStepId && nextStepId && lastStepId !== nextStepId) return false;

  const currentHasDetailedOnly = currentBlocks.some(isDetailedOnlyBlock);
  if (currentHasDetailedOnly && nextStepId && !lastStepId) return false;

  return true;
}

function findMatchingPhases(
  rawBlocks: ContentBlock[],
  livePhases: ThinkingPhase[],
) {
  if (livePhases.length === 0) return [];

  const stepIds = new Set(
    rawBlocks
      .map((block) => block.stepId)
      .filter((value): value is string => Boolean(value)),
  );

  const nodes = new Set(
    rawBlocks
      .map((block) => ("node" in block ? block.node : undefined))
      .filter((value): value is string => Boolean(value)),
  );

  if (stepIds.size > 0) {
    return livePhases.filter((phase) => phase.stepId && stepIds.has(phase.stepId));
  }

  if (nodes.size === 1) {
    return livePhases.filter((phase) => (
      phase.status === "active"
      && phase.node
      && nodes.has(phase.node)
    ));
  }

  return [];
}

function enrichIntervalWithPhases(
  interval: ReasoningIntervalViewModel,
  livePhases: ThinkingPhase[],
  thinkingLevel: ThinkingLevel,
) {
  if (thinkingLevel !== "detailed") return interval;
  const matchedPhases = findMatchingPhases(interval.rawBlocks, livePhases);
  if (matchedPhases.length === 0) return interval;

  const latestPhase = matchedPhases[matchedPhases.length - 1];
  const label = interval.label || latestPhase.label;
  const summary = interval.summary || latestPhase.summary;
  const phase = interval.phase || latestPhase.phase;
  const node = interval.node || latestPhase.node;
  const stepId = interval.stepId || latestPhase.stepId;
  const isLive = matchedPhases.some((candidate) => candidate.status === "active") || interval.isLive;
  const completedEnds = matchedPhases
    .map((candidate) => candidate.endTime)
    .filter((value): value is number => typeof value === "number");
  const lastEnd = completedEnds.length > 0 ? Math.max(...completedEnds) : undefined;
  const durationSeconds = interval.durationSeconds
    || durationSecondsFromBounds(latestPhase.startTime, lastEnd);

  return {
    ...interval,
    label,
    summary,
    phase,
    node,
    stepId,
    isLive,
    durationSeconds,
    items: interval.items,
  };
}

function buildReasoningInterval(
  rawBlocks: ContentBlock[],
  livePhases: ThinkingPhase[],
  thinkingLevel: ThinkingLevel,
): ReasoningIntervalViewModel {
  const thinkingBlocks = rawBlocks.filter((block): block is ThinkingBlockData => block.type === "thinking");
  const firstThinking = thinkingBlocks[0];
  const firstBlock = rawBlocks[0];
  const label = firstThinking?.label || firstThinking?.summary || firstThinking?.phase || "Đang suy luận";
  const stepId = firstThinking?.stepId || firstBlock?.stepId;
  const node = firstThinking?.node || getBlockNode(firstBlock);
  const phase = firstThinking?.phase;
  const summary = firstThinking?.summary;
  const startTime = thinkingBlocks
    .map((block) => block.startTime)
    .filter((value): value is number => typeof value === "number")
    .sort((a, b) => a - b)[0];
  const endTime = thinkingBlocks
    .map((block) => block.endTime)
    .filter((value): value is number => typeof value === "number")
    .sort((a, b) => b - a)[0];

  const baseInterval: ReasoningIntervalViewModel = {
    id: stepId || rawBlocks.map((block) => block.id).join("-"),
    stepId,
    node,
    label,
    summary,
    phase,
    isLive: rawBlocks.some((block) => block.stepState === "live")
      || thinkingBlocks.some((block) => !block.endTime),
    durationSeconds: durationSecondsFromBounds(startTime, endTime),
    items: dedupeIntervalItems(
      rawBlocks
        .map((block) => mapBlockToIntervalItem(block))
        .filter((item): item is ReasoningIntervalItem => Boolean(item)),
    ),
    rawBlocks,
  };

  return enrichIntervalWithPhases(baseInterval, livePhases, thinkingLevel);
}

function buildRenderItems(
  blocks: ContentBlock[],
  thinkingLevel: ThinkingLevel,
  livePhases: ThinkingPhase[],
): RenderItem[] {
  const items: RenderItem[] = [];

  for (let index = 0; index < blocks.length; ) {
    const current = blocks[index];
    if (!current) {
      index += 1;
      continue;
    }

    if (current.type === "thinking" && current.groupId) {
      index += 1;
      continue;
    }

    if (isIntervalCandidate(current, thinkingLevel)) {
      const intervalBlocks: ContentBlock[] = [current];
      index += 1;
      while (index < blocks.length) {
        const candidate = blocks[index];
        if (!candidate) break;
        if (!isIntervalCandidate(candidate, thinkingLevel) && !isIntervalTraceCompanionBlock(candidate)) {
          break;
        }
        if (!isCompatibleIntervalBlock(intervalBlocks, candidate)) break;
        intervalBlocks.push(candidate);
        index += 1;
      }
      const interval = buildReasoningInterval(intervalBlocks, livePhases, thinkingLevel);
      items.push({ kind: "interval", id: interval.id, interval });
      continue;
    }

    items.push({ kind: "block", id: current.id, block: current });
    index += 1;
  }

  return items;
}

export function shouldRenderReasoningRail(
  _blocks: ContentBlock[],
  showThinking: boolean,
  thinkingLevel: ThinkingLevel = "balanced",
): boolean {
  return showThinking && thinkingLevel !== "minimal";
}

interface InterleavedBlockSequenceProps {
  blocks: ContentBlock[];
  showThinking: boolean;
  thinkingLevel?: ThinkingLevel;
  isStreaming?: boolean;
  livePhases?: ThinkingPhase[];
  onSuggestedQuestion?: (q: string) => void;
}

function AnswerSurface({
  content,
  showCursor = false,
  className = "",
  surfaceRole = "standalone",
}: {
  content: string;
  showCursor?: boolean;
  className?: string;
  surfaceRole?: "standalone" | "lead" | "body" | "tail";
}) {
  if (!content) return null;

  return (
    <div
      className={`assistant-response assistant-response--editorial ${className}`.trim()}
      data-editorial-role={surfaceRole}
      data-testid="answer-block"
    >
      <MarkdownRenderer content={content} />
      {showCursor && (
        <span className="inline-block w-[2px] h-[1em] bg-[var(--accent-orange)] ml-0.5 align-middle animate-pulse rounded-sm" />
      )}
    </div>
  );
}

function renderEditorialFlow(
  composition: ArticleComposition,
  blocks: ContentBlock[],
  isStreaming: boolean,
  onSuggestedQuestion?: (q: string) => void,
) {
  const visualBlocks = new Map(
    blocks
      .filter(
        (candidate): candidate is VisualBlockData => candidate.type === "visual" && candidate.status !== "disposed",
      )
      .map((candidate) => [candidate.id, candidate]),
  );
  const lastProseIndex = composition.segments.reduce((acc, segment, index) => (
    segment.kind === "prose" ? index : acc
  ), -1);

  return (
    <div
      key={`editorial-flow-${composition.entryId}`}
      className="editorial-visual-flow"
      data-testid="editorial-visual-flow"
      data-figure-count={composition.figureIds.length}
    >
      {composition.segments.map((segment, index) => {
        if (segment.kind === "prose") {
          const proseClassName = segment.surfaceRole === "lead"
            ? "editorial-visual-flow__lead-copy"
            : segment.surfaceRole === "tail"
              ? "editorial-visual-flow__tail-copy"
              : "editorial-visual-flow__body-copy";
          return (
            <div
              key={segment.id}
              className={`editorial-visual-flow__prose editorial-visual-flow__prose--${segment.surfaceRole}`}
            >
              <AnswerSurface
                content={segment.content}
                className={proseClassName}
                showCursor={isStreaming && composition.answerIsLast && index === lastProseIndex}
                surfaceRole={segment.surfaceRole}
              />
            </div>
          );
        }

        const visualBlock = visualBlocks.get(segment.figure.visualId);
        if (!visualBlock) return null;

        return (
          <div
            key={segment.id}
            className="editorial-visual-flow__figure"
            data-anchor={segment.figure.narrativeAnchor}
            data-chrome-mode={segment.figure.chromeMode}
            data-pedagogical-role={segment.figure.pedagogicalRole}
          >
            <div
              className="editorial-visual-flow__bridge"
              data-anchor={segment.figure.narrativeAnchor}
            >
              <span className="editorial-visual-flow__bridge-chip">{segment.figure.bridgeLabel}</span>
              {segment.figure.claim ? (
                <span className="editorial-visual-flow__bridge-claim">{segment.figure.claim}</span>
              ) : null}
              <span className="editorial-visual-flow__bridge-line" aria-hidden="true" />
            </div>
            <div className="editorial-visual-flow__stage">
              <VisualBlock block={visualBlock} embedded onSuggestedQuestion={onSuggestedQuestion} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function InterleavedBlockSequence({
  blocks,
  showThinking,
  thinkingLevel = "balanced",
  isStreaming = false,
  livePhases = [],
  onSuggestedQuestion,
}: InterleavedBlockSequenceProps) {
  const [inspectorIntervalId, setInspectorIntervalId] = useState<string | null>(null);
  const showReasoningRail = shouldRenderReasoningRail(blocks, showThinking, thinkingLevel);
  const groupedBlockIds = new Set<string>();

  for (const block of blocks) {
    if (block.type === "thinking" && block.groupId) {
      groupedBlockIds.add(block.id);
    }
  }

  const visibleBlocks = useMemo(() => reorderForDisplay(
    blocks.filter((block) => {
      if (isDisposedVisualBlock(block)) return false;
      if (shouldHideTechnicalTraceBlock(block, thinkingLevel, showReasoningRail)) return false;
      if (!showReasoningRail) {
        return !["thinking", "action_text"].includes(block.type);
      }
      return true;
    }),
  ), [blocks, showReasoningRail, thinkingLevel]);

  const editorialComposition = useMemo(
    () => buildArticleComposition(visibleBlocks),
    [visibleBlocks],
  );

  const renderItems = useMemo(
    () => buildRenderItems(
      visibleBlocks.filter((block) => !(block.type === "thinking" && groupedBlockIds.has(block.id))),
      thinkingLevel,
      showReasoningRail ? livePhases : [],
    ),
    [groupedBlockIds, livePhases, showReasoningRail, thinkingLevel, visibleBlocks],
  );

  const activeInspector = renderItems.find((item) => (
    item.kind === "interval" && item.interval.id === inspectorIntervalId
  ));
  const traceBlocks = useMemo(
    () => blocks.filter((block) => !isDisposedVisualBlock(block) && isInspectorTraceBlock(block)),
    [blocks],
  );
  const inspectorBlocks = useMemo(
    () => traceBlocks,
    [traceBlocks],
  );
  const activeInspectorBlocks = useMemo(
    () => activeInspector?.kind === "interval"
      ? traceBlocks.filter((block) => matchesIntervalTraceBlock(activeInspector.interval, block))
      : inspectorBlocks,
    [activeInspector, inspectorBlocks, traceBlocks],
  );
  const hasHiddenTrace = inspectorBlocks.some((block) => block.type !== "thinking");
  const inspectorTitle = activeInspector?.kind === "interval"
    ? (activeInspector.interval.summary || activeInspector.interval.label || "Trace")
    : inspectorBlocks.length > 0
      ? "Trace chi tiet"
      : "Trace";

  return (
    <>
      {renderItems.map((item, index) => {
        if (item.kind === "interval") {
          // Phase2: Merge consecutive intervals into ONE visual timeline.
          // Skip if this interval is part of a merged group (rendered by first in group).
          const prevItem = renderItems[index - 1];
          if (prevItem?.kind === "interval") {
            return null; // Already rendered as part of merged group
          }

          // Collect all consecutive intervals
          const mergedIntervals = [item.interval];
          let nextIdx = index + 1;
          while (nextIdx < renderItems.length && renderItems[nextIdx].kind === "interval") {
            mergedIntervals.push((renderItems[nextIdx] as typeof item).interval);
            nextIdx++;
          }

          if (mergedIntervals.length === 1) {
            // Fix: Use stable key (index-based) to prevent React remount
            return (
              <ReasoningInterval
                key={`ri-${index}`}
                interval={item.interval}
                thinkingLevel={thinkingLevel}
                isResponseComplete={!isStreaming}
                onOpenInspector={() => setInspectorIntervalId(item.interval.id)}
              />
            );
          }

          // Merge multiple intervals into ONE unified interval
          const mergedInterval: ReasoningIntervalViewModel = {
            ...mergedIntervals[0],
            id: `merged-${index}`,
            isLive: mergedIntervals.some((iv) => iv.isLive),
            items: mergedIntervals.flatMap((iv) => iv.items),
            rawBlocks: mergedIntervals.flatMap((iv) => iv.rawBlocks),
            durationSeconds: sumRoundedDurations(
              mergedIntervals.map((iv) => iv.durationSeconds),
            ),
          };

          // Fix: Stable key based on render position, not generated ID
          return (
            <ReasoningInterval
              key={`ri-${index}`}
              interval={mergedInterval}
              thinkingLevel={thinkingLevel}
              isResponseComplete={!isStreaming}
              onOpenInspector={() => setInspectorIntervalId(mergedIntervals[0].id)}
            />
          );
        }

        const block = item.block;

        if (block.type === "subagent_group") {
          const childBlocks = visibleBlocks.filter(
            (candidate) => candidate.type === "thinking" && candidate.groupId === block.id,
          ) as ThinkingBlockData[];
          return (
            <BlockErrorBoundary key={block.id} blockType="subagent_group">
              <SubagentGroup
                group={block as SubagentGroupBlockData}
                childBlocks={childBlocks}
                isStreaming={isStreaming}
                thinkingLevel={thinkingLevel}
              />
            </BlockErrorBoundary>
          );
        }

        if (block.type === "screenshot") {
          return (
            <BlockErrorBoundary key={block.id} blockType="screenshot">
              <ScreenshotBlock block={block as ScreenshotBlockData} />
            </BlockErrorBoundary>
          );
        }

        if (block.type === "preview") {
          // Preview/search results render at BOTTOM (after answer), not inline.
          // Answer first, sources second — user reads answer then verifies sources.
          return null;
        }

        if (block.type === "tool_execution") {
          return (
            <BlockErrorBoundary key={block.id} blockType="tool_execution">
              <ToolExecutionStrip block={block as ToolExecutionBlockData} />
            </BlockErrorBoundary>
          );
        }

        if (block.type === "artifact") {
          return (
            <BlockErrorBoundary key={block.id} blockType="artifact">
              <ArtifactCard artifact={(block as ArtifactBlockData).artifact} />
            </BlockErrorBoundary>
          );
        }

        if (block.type === "visual") {
          if (editorialComposition?.entryId === block.id) {
            return (
              <BlockErrorBoundary key={block.id} blockType="visual">
                {renderEditorialFlow(editorialComposition, visibleBlocks, isStreaming, onSuggestedQuestion)}
              </BlockErrorBoundary>
            );
          }
          if (editorialComposition?.figureIds.includes(block.id)) return null;
          return (
            <BlockErrorBoundary key={block.id} blockType="visual">
              <VisualBlock block={block as VisualBlockData} onSuggestedQuestion={onSuggestedQuestion} />
            </BlockErrorBoundary>
          );
        }

        if (block.type === "answer") {
          const answerContent = block.content;
          if (!answerContent) return null;

          if (editorialComposition?.entryId === block.id) {
            return (
              <BlockErrorBoundary key={block.id} blockType="answer">
                {renderEditorialFlow(editorialComposition, visibleBlocks, isStreaming, onSuggestedQuestion)}
              </BlockErrorBoundary>
            );
          }
          if (editorialComposition?.answerIds.includes(block.id)) return null;

          const isLastAnswer = !visibleBlocks.slice(index + 1).some((candidate) => candidate.type === "answer");

          return (
            <BlockErrorBoundary key={block.id} blockType="answer">
              <AnswerSurface
                content={answerContent}
                showCursor={isStreaming && isLastAnswer}
              />
            </BlockErrorBoundary>
          );
        }

        return null;
      })}

      {/* Preview/search results — rendered AFTER answer (answer first, sources second) */}
      {renderItems.flatMap((item) => {
        if (item.kind !== "block") return [];
        const block = item.block;
        if (block.type !== "preview") return [];
        return [(
          <BlockErrorBoundary key={`bottom-${block.id}`} blockType="preview">
            <PreviewGroup block={block as PreviewBlockData} />
          </BlockErrorBoundary>
        )];
      })}

      {showReasoningRail && thinkingLevel === "detailed" && hasHiddenTrace ? (
        <div className="reasoning-trace-launcher">
          <button
            type="button"
            className="reasoning-trace-launcher__button"
            onClick={() => setInspectorIntervalId("__message__")}
            data-testid="reasoning-inspector-toggle"
          >
            Xem trace chi tiet
          </button>
        </div>
      ) : null}

      <ThinkingInspectorDrawer
        isOpen={Boolean(activeInspector) || inspectorIntervalId === "__message__"}
        title={inspectorTitle}
        blocks={activeInspector?.kind === "interval" ? activeInspectorBlocks : inspectorBlocks}
        onClose={() => setInspectorIntervalId(null)}
      />
    </>
  );
}
