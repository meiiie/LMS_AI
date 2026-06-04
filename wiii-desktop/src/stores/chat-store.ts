/**
 * Chat store — conversations, messages, streaming state.
 * Conversations are persisted via tauri-plugin-store (or localStorage fallback).
 *
 * Sprint 62: Added streamingBlocks for interleaved thinking/answer rendering.
 * Old flat fields (streamingContent, streamingThinking, streamingToolCalls)
 * are kept for backward compatibility with tests and simple consumers.
 *
 * Sprint 154: Added immer middleware to eliminate spread operators in streaming mutations.
 * Direct draft mutations reduce GC pressure during high-frequency token streaming.
 */
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { v4 as uuidv4 } from "uuid";
import { loadStore, saveStore } from "@/lib/storage";
import { stripWiiiInternalMarkupFromStream } from "@/lib/internal-markup";
import type {
  Conversation,
  Message,
  SourceInfo,
  ChatResponseMetadata,
  ToolCallInfo,
  ContentBlock,
  DisplayPresentationMeta,
  StreamingStep,
  ThinkingPhase,
  ThinkingSummaryMode,
  ThinkingBlockData,
  ScreenshotBlockData,
  SubagentGroupBlockData,
  SubagentWorker,
  AggregationSummary,
  PreviewItemData,
  PreviewBlockData,
  ArtifactData,
  ArtifactBlockData,
  ChatLifecycleTelemetryEvent,
  ToolExecutionBlockData,
  ChatDocumentAttachment,
  ImageInput,
  SSEChatLifecycleEvent,
  VisualPayload,
  VisualBlockData,
  VisualSessionState,
  WidgetFeedbackItem,
  WiiiConnectRuntimeConnection,
  WiiiConnectRuntimePathCapability,
  WiiiConnectRuntimeSnapshot,
} from "@/api/types";

const BASE_STORE_NAME = "conversations.json";
const BASE_STORE_KEY = "conversations";
const MAX_CHAT_LIFECYCLE_EVENTS = 48;
const MAX_CHAT_LIFECYCLE_RECORD_KEYS = 16;
const MAX_CHAT_LIFECYCLE_ARRAY_ITEMS = 16;
const MAX_CHAT_LIFECYCLE_STRING_CHARS = 240;

/**
 * Sprint 218: Per-user conversation storage.
 * Each user gets their own store file: conversations_{userId}.json
 * This prevents User A from seeing User B's chat history after OAuth switch.
 */
let _currentUserId: string | null = null;

function getStoreName(): string {
  if (_currentUserId) return `conversations_${_currentUserId}.json`;
  return BASE_STORE_NAME;
}

function getStoreKey(): string {
  if (_currentUserId) return `conversations_${_currentUserId}`;
  return BASE_STORE_KEY;
}

function normalizeNarrativeText(value: string | undefined): string {
  return (value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function normalizeThinkingSnapshot(value: string | undefined): string {
  return (value || "").replace(/\s+/g, " ").trim();
}

function sourceDedupKey(source: SourceInfo): string {
  const url = String(source.url || "").trim().toLowerCase();
  if (url) return `url:${url}`;
  return [
    "text",
    String(source.title || "").trim().toLowerCase(),
    String(source.content || "").slice(0, 160).trim().toLowerCase(),
  ].join(":");
}

function mergeSourceInfos(
  existing: SourceInfo[],
  incoming: SourceInfo[],
): SourceInfo[] {
  const merged: SourceInfo[] = [];
  const seen = new Set<string>();
  for (const source of [...existing, ...incoming]) {
    const key = sourceDedupKey(source);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(source);
  }
  return merged;
}

function attachSourcesToLastAssistantDraft(
  state: ChatState,
  sources: SourceInfo[],
  conversationId: string | null,
): boolean {
  if (sources.length === 0 || !conversationId) return false;
  const recentlyCompleted =
    typeof state.streamCompletedAt === "number" &&
    Date.now() - state.streamCompletedAt < 60_000;
  if (!recentlyCompleted) return false;

  const conversation = state.conversations.find(
    (item) => item.id === conversationId,
  );
  if (!conversation) return false;

  for (let i = conversation.messages.length - 1; i >= 0; i -= 1) {
    const message = conversation.messages[i];
    if (message.role !== "assistant") continue;
    message.sources = mergeSourceInfos(message.sources || [], sources);
    return true;
  }
  return false;
}

function getLastNarrativeLine(value: string | undefined): string {
  const segments = (value || "")
    .split("\n")
    .map((segment) => segment.trim())
    .filter(Boolean);
  return segments.length > 0 ? segments[segments.length - 1] || "" : "";
}

function getNarrativeSegments(value: string | undefined): string[] {
  return (value || "")
    .split("\n")
    .map((segment) => segment.trim())
    .filter(Boolean);
}

function hasNarrativeSegment(
  value: string | undefined,
  candidate: string,
): boolean {
  const normalizedCandidate = normalizeNarrativeText(candidate);
  if (!normalizedCandidate) return false;
  return getNarrativeSegments(value).some(
    (segment) => normalizeNarrativeText(segment) === normalizedCandidate,
  );
}

function isReplayProneNarrativeChunk(value: string | undefined): boolean {
  const trimmed = (value || "").trim();
  if (!trimmed) return false;
  return trimmed.length >= 24 || /\s/u.test(trimmed) || /[.!?…]/u.test(trimmed);
}

function shouldSkipRepeatedNarrative(
  existingText: string | undefined,
  candidate: string,
): boolean {
  if (!isReplayProneNarrativeChunk(candidate)) return false;
  return hasNarrativeSegment(existingText, candidate);
}

function buildThinkingDedupContext(
  openBlock: ThinkingBlockData | undefined,
  previousBlock: ThinkingBlockData | undefined,
  streamingThinking: string,
): string {
  return [
    openBlock?.content,
    openBlock?.summary,
    previousBlock?.content,
    previousBlock?.summary,
    streamingThinking,
  ]
    .filter((value): value is string => Boolean(value && value.trim()))
    .join("\n");
}

function sanitizeThinkingLabel(label: string | undefined): string | undefined {
  const trimmed = (label || "").trim();
  if (!trimmed) return undefined;
  if (/^🔧/u.test(trimmed)) return undefined;
  if (/^chuyển sang\b/i.test(trimmed)) return undefined;
  if (/^tìm thấy\s+\d+/i.test(trimmed)) return undefined;
  if (/\btool_[a-z0-9_]+\b/i.test(trimmed)) return undefined;
  return trimmed;
}

interface ChatState {
  // Data
  conversations: Conversation[];
  activeConversationId: string | null;

  // Sidebar search + pin (Sprint 80)
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  pinConversation: (id: string) => void;
  unpinConversation: (id: string) => void;

  // Streaming state — flat fields (backward compat)
  isStreaming: boolean;
  streamingContent: string;
  streamingThinking: string;
  streamingSources: SourceInfo[];
  streamingStep: string;
  streamingToolCalls: ToolCallInfo[];

  // Streaming state — block-based (interleaved support)
  streamingBlocks: ContentBlock[];

  // Streaming state — timer + pipeline steps (Sprint 63)
  streamingStartTime: number | null;
  streamingSteps: StreamingStep[];
  streamingLifecycleEvents: ChatLifecycleTelemetryEvent[];
  lastCompletedLifecycleEvents: ChatLifecycleTelemetryEvent[];

  // Sprint 80b: Domain notice for off-domain content
  streamingDomainNotice: string;

  // Sprint 141: Unified thinking phases for ThinkingFlow
  streamingPhases: ThinkingPhase[];

  // Sprint 166: Preview cards state
  streamingPreviews: PreviewItemData[];

  // Sprint 167: Artifact state
  streamingArtifacts: ArtifactData[];
  pendingStreamMetadata: ChatResponseMetadata | null;
  visualSessions: Record<string, VisualSessionState>;

  // Sprint 164: Active subagent group tracking
  _activeSubagentGroupId: string | null;

  // Sprint 145: Transient avatar state fields
  streamError: string;
  streamCompletedAt: number | null;
  lastCompletedConversationId: string | null;

  // Computed
  activeConversation: () => Conversation | undefined;

  // Persistence
  isLoaded: boolean;
  loadConversations: () => Promise<void>;

  // Actions
  createConversation: (
    domainId?: string,
    organizationId?: string,
    sessionId?: string,
  ) => string;
  deleteConversation: (id: string) => void;
  setActiveConversation: (id: string | null) => void;
  renameConversation: (id: string, title: string) => void;
  addUserMessage: (
    content: string,
    images?: ImageInput[],
    documents?: ChatDocumentAttachment[],
  ) => string | null;
  startStreaming: () => void;
  appendStreamingContent: (chunk: string) => void;
  setStreamingThinking: (thinking: string) => void;
  setStreamingThinkingLabel: (label: string) => void;
  setStreamingStep: (step: string) => void;
  setStreamingSources: (sources: SourceInfo[]) => void;
  addStreamingStep: (label: string, node?: string) => void;
  addChatLifecycleEvent: (event: SSEChatLifecycleEvent) => void;
  appendThinkingDelta: (
    delta: string,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  openThinkingBlock: (
    label: string,
    summary?: string,
    node?: string,
    phase?: string,
    meta?: DisplayPresentationMeta,
    summaryMode?: ThinkingSummaryMode,
  ) => void;
  closeThinkingBlock: (durationMs?: number) => void;
  appendToolCall: (tc: ToolCallInfo, meta?: DisplayPresentationMeta) => void;
  updateToolCallResult: (
    id: string,
    result: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  setStreamingDomainNotice: (notice: string) => void;
  /** Sprint 147: Append bold action text between thinking blocks */
  appendActionText: (
    text: string,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  /** Sprint 153: Append browser screenshot block. */
  appendScreenshot: (
    data: { url: string; image: string; label: string; node?: string },
    meta?: DisplayPresentationMeta,
  ) => void;
  /** Sprint 164: Open a subagent parallel dispatch group */
  openSubagentGroup: (label: string, agentNames: string[]) => void;
  /** Sprint 164: Close the active subagent group */
  closeSubagentGroup: () => void;
  /** Sprint 164: Attach aggregation decision to the most recent subagent group */
  setAggregationSummary: (summary: AggregationSummary) => void;
  /** Sprint 164: Mark a specific worker as completed within the active group */
  markWorkerCompleted: (workerNode: string) => void;
  /** Sprint 164: Append a status message to a specific worker */
  appendWorkerStatus: (workerNode: string, message: string) => void;
  /** Sprint 166: Add a preview item to the streaming state */
  addPreviewItem: (
    item: PreviewItemData,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  /** Sprint 167: Add an artifact to the streaming state */
  addArtifact: (
    artifact: ArtifactData,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  /** Sprint 230: Add a structured inline visual to the streaming state */
  addVisual: (
    visual: VisualPayload,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  openVisualSession: (
    visual: VisualPayload,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  patchVisualSession: (
    visual: VisualPayload,
    node?: string,
    meta?: DisplayPresentationMeta,
  ) => void;
  commitVisualSession: (sessionId: string) => void;
  disposeVisualSession: (sessionId: string, reason?: string) => void;
  updateVisualSessionInteraction: (
    sessionId: string,
    patch: Partial<
      Pick<VisualSessionState, "focusedAnnotationId" | "focusedNodeId">
    > & {
      controlValues?: Record<string, string | number | boolean>;
      interactionDelta?: number;
    },
  ) => void;
  getActiveVisualContext: () => Record<string, unknown> | undefined;
  recordWidgetFeedback: (
    feedback: Omit<WidgetFeedbackItem, "timestamp"> & { timestamp?: string },
  ) => void;
  getActiveWidgetFeedbackContext: () => Record<string, unknown> | undefined;
  // Sprint 141: ThinkingFlow phase actions
  addOrUpdatePhase: (
    label: string,
    node?: string,
    stepId?: string,
    phase?: string,
    summary?: string,
    summaryMode?: ThinkingSummaryMode,
  ) => void;
  appendPhaseThinking: (
    content: string,
    node?: string,
    stepId?: string,
  ) => void;
  appendPhaseThinkingDelta: (
    delta: string,
    node?: string,
    stepId?: string,
  ) => void;
  closeActivePhase: (durationMs?: number) => void;
  appendPhaseStatus: (message: string, node?: string, stepId?: string) => void;
  appendPhaseToolCall: (tc: ToolCallInfo, stepId?: string) => void;
  updatePhaseToolCallResult: (id: string, result: string) => void;
  setPendingStreamMetadata: (metadata: ChatResponseMetadata) => void;
  finalizeStream: (metadata?: ChatResponseMetadata) => void;
  setStreamError: (error: string, metadata?: Record<string, unknown>) => void;
  setMessageFeedback: (
    messageId: string,
    feedback: "up" | "down" | null,
  ) => void;
  clearStreaming: () => void;
  /** Sprint 218: Clear conversations on logout (prevent cross-user leakage) */
  clearForLogout: () => void;
  /** Sprint 218: Switch to a different user's conversation store */
  switchUser: (userId: string | null) => Promise<void>;
  /** Sprint 225: Sync conversation list from server (additive merge) */
  syncFromServer: () => Promise<void>;
  /** Sprint 225: Lazy-load messages from server for a conversation */
  loadServerMessages: (conversationId: string) => Promise<void>;
}

// Debounced persist — avoids excessive writes during streaming
let _persistTimer: ReturnType<typeof setTimeout> | null = null;

// Sprint 225: Prevent concurrent syncFromServer calls
let _syncInProgress = false;
let _pendingAnswerInternalMarkup = "";

function persistConversations(conversations: Conversation[]) {
  if (_persistTimer) clearTimeout(_persistTimer);
  const storeName = getStoreName();
  const storeKey = getStoreKey();
  _persistTimer = setTimeout(() => {
    saveStore(storeName, storeKey, conversations).catch((err) =>
      console.warn("[chat-store] Failed to persist:", err),
    );
  }, 2000);
}

function persistConversationsImmediate(conversations: Conversation[]) {
  if (_persistTimer) clearTimeout(_persistTimer);
  saveStore(getStoreName(), getStoreKey(), conversations).catch((err) =>
    console.warn("[chat-store] Failed to persist:", err),
  );
}

/** Close the last open thinking block in-place (immer-compatible). */
function closeLastThinkingBlockDraft(blocks: ContentBlock[]): void {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (block.type === "thinking" && !block.endTime) {
      block.endTime = Date.now();
      block.stepState = "completed";
      break;
    }
  }
}

function extractSuggestedQuestions(
  metadata?: ChatResponseMetadata,
): string[] | undefined {
  const rawSQ =
    metadata?.suggested_questions ??
    (metadata?.data as Record<string, unknown> | undefined)
      ?.suggested_questions;
  return Array.isArray(rawSQ) ? (rawSQ as string[]) : undefined;
}

function buildDegradedAssistantContent(
  state: Pick<
    ChatState,
    | "streamingContent"
    | "streamingBlocks"
    | "streamingArtifacts"
    | "streamingPreviews"
  >,
): string {
  if (state.streamingContent.trim()) return state.streamingContent;
  if (state.streamingBlocks.some((block) => block.type === "visual")) {
    return "Wiii đã tạo xong visual inline, nhưng phần text tổng hợp bị ngắt trước khi gửi trọn vẹn.";
  }
  if (
    state.streamingArtifacts.length > 0 ||
    state.streamingPreviews.length > 0
  ) {
    return "Wiii đã hoàn tất phần tạo nội dung và giữ lại các tệp/kết quả cho bạn, nhưng câu trả lời cuối đã bị ngắt trước khi gửi trọn vẹn.";
  }
  if (state.streamingBlocks.length > 0) {
    return "Wiii đã đi hết phần suy luận, nhưng phản hồi cuối bị ngắt trước khi hiển thị trọn vẹn. Bạn có thể xem lại dòng suy luận hoặc gửi lại để mình chốt lại gọn hơn.";
  }
  return "Luồng phản hồi đã kết thúc sớm trước khi Wiii kịp gửi câu trả lời cuối.";
}

function mergeStreamMetadataIntoMessage(
  message: Message,
  metadata: ChatResponseMetadata,
): void {
  const existingLifecycle = Array.isArray(message.metadata?.chat_lifecycle)
    ? (message.metadata.chat_lifecycle as ChatLifecycleTelemetryEvent[])
    : [];
  const mergedMetadata = metadata.chat_lifecycle
    ? metadata
    : (mergeChatLifecycleMetadata(metadata, existingLifecycle) as
        | ChatResponseMetadata
        | undefined);
  message.reasoning_trace = metadata.reasoning_trace;
  message.metadata = mergedMetadata || metadata;
  message.suggested_questions = extractSuggestedQuestions(
    mergedMetadata || metadata,
  );
  const metadataThinking = normalizeThinkingSnapshot(
    metadata.thinking_lifecycle?.final_text ||
      metadata.thinking_content ||
      metadata.thinking ||
      "",
  );
  if (metadataThinking) {
    const currentThinking = normalizeThinkingSnapshot(message.thinking);
    if (!currentThinking || metadataThinking.length > currentThinking.length) {
      message.thinking = metadataThinking;
    }
  }
}

function pickPreferredFinalThinking(
  streamingThinking: string,
  metadata?: ChatResponseMetadata,
): string {
  const liveThinking = normalizeThinkingSnapshot(streamingThinking);
  const lifecycleThinking = normalizeThinkingSnapshot(
    metadata?.thinking_lifecycle?.final_text || "",
  );
  const metadataThinking = normalizeThinkingSnapshot(
    metadata?.thinking_content || metadata?.thinking || "",
  );

  if (lifecycleThinking) {
    if (!liveThinking) return lifecycleThinking;
    if (lifecycleThinking === liveThinking) return liveThinking;
    if (lifecycleThinking.length >= liveThinking.length)
      return lifecycleThinking;
  }
  if (!metadataThinking) return liveThinking || lifecycleThinking;
  if (!liveThinking) return metadataThinking;
  if (metadataThinking === liveThinking) return liveThinking;
  if (metadataThinking.length > liveThinking.length) return metadataThinking;
  return liveThinking;
}

function reconcileFinalThinkingBlocks(
  blocks: ContentBlock[],
  preferredThinking: string,
): ContentBlock[] {
  const cleanThinking = normalizeThinkingSnapshot(preferredThinking);
  if (!cleanThinking) return blocks;

  const nextBlocks = blocks.map((block) => ({ ...block })) as ContentBlock[];
  const lastThinking = findLastThinkingBlock(nextBlocks);
  if (lastThinking) {
    const currentContent = normalizeThinkingSnapshot(lastThinking.content);
    if (!currentContent || cleanThinking.length > currentContent.length) {
      lastThinking.content = cleanThinking;
      if (!lastThinking.endTime) {
        lastThinking.endTime = Date.now();
      }
      lastThinking.stepState = "completed";
    }
    return nextBlocks;
  }

  nextBlocks.unshift({
    type: "thinking",
    id: uuidv4(),
    content: cleanThinking,
    toolCalls: [],
    startTime: Date.now(),
    endTime: Date.now(),
    stepState: "completed",
    displayRole: "thinking",
    presentation: "compact",
  } as ThinkingBlockData);
  return nextBlocks;
}

function getMetadataRequestId(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const requestId = (value as Record<string, unknown>).request_id;
  return typeof requestId === "string" ? requestId.trim() : "";
}

function applyDisplayMeta<T extends DisplayPresentationMeta>(
  target: T,
  meta?: DisplayPresentationMeta,
): T {
  if (!meta) return target;
  if (meta.displayRole) target.displayRole = meta.displayRole;
  if (meta.sequenceId != null) target.sequenceId = meta.sequenceId;
  if (meta.stepId) target.stepId = meta.stepId;
  if (meta.stepState) target.stepState = meta.stepState;
  if (meta.presentation) target.presentation = meta.presentation;
  return target;
}

function findLastOpenThinkingBlock(
  blocks: ContentBlock[],
  stepId?: string,
  node?: string,
) {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (block.type !== "thinking" || block.endTime) continue;
    if (stepId && block.stepId === stepId) return block;
    if (!stepId && node && block.node === node) return block;
    if (!stepId && !node) return block;
  }
  return undefined;
}

function findLastThinkingBlock(
  blocks: ContentBlock[],
  stepId?: string,
  node?: string,
) {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (block.type !== "thinking") continue;
    if (stepId && block.stepId === stepId) return block;
    if (!stepId && node && block.node === node) return block;
    if (!stepId && !node) return block;
  }
  return undefined;
}

function mergeToolCallInfoDraft(
  target: ToolCallInfo,
  incoming: ToolCallInfo,
): ToolCallInfo {
  target.name = incoming.name || target.name;
  if (incoming.args) {
    target.args = {
      ...(target.args || {}),
      ...incoming.args,
    };
  }
  if (incoming.result !== undefined) {
    target.result = incoming.result;
  }
  if (incoming.node) {
    target.node = incoming.node;
  }
  return target;
}

function upsertToolCallInfoDraft(
  toolCalls: ToolCallInfo[],
  incoming: ToolCallInfo,
): ToolCallInfo {
  const existing = toolCalls.find((tc) => tc.id === incoming.id);
  if (existing) return mergeToolCallInfoDraft(existing, incoming);
  const next = {
    ...incoming,
    args: incoming.args ? { ...incoming.args } : undefined,
  };
  toolCalls.push(next);
  return next;
}

function findToolExecutionBlockDraft(
  blocks: ContentBlock[],
  toolCallId: string,
): ToolExecutionBlockData | undefined {
  return blocks.find(
    (block): block is ToolExecutionBlockData =>
      block.type === "tool_execution" && block.tool.id === toolCallId,
  );
}

function findActiveThinkingPhaseIndex(
  phases: ThinkingPhase[],
  stepId?: string,
  node?: string,
) {
  let fallbackIndex = -1;
  for (let i = phases.length - 1; i >= 0; i--) {
    const phase = phases[i];
    if (phase.status !== "active") continue;
    if (stepId && phase.stepId === stepId) return i;
    if (!stepId && node && phase.node === node) return i;
    if (fallbackIndex === -1) fallbackIndex = i;
  }
  return fallbackIndex;
}

function getVisualSessionId(
  visual: Pick<VisualPayload, "visual_session_id" | "id">,
): string {
  return visual.visual_session_id || visual.id;
}

const VISUAL_TOOL_EXECUTION_NAMES = new Set([
  "tool_generate_visual",
  "tool_generate_rich_visual",
  "tool_create_visual_code",
]);

function getDefaultVisualControlValues(
  visual: VisualPayload,
): Record<string, string | number | boolean> {
  const values: Record<string, string | number | boolean> = {};
  for (const control of visual.controls || []) {
    if (typeof control.value !== "undefined") {
      values[control.id] = control.value;
      continue;
    }
    if (control.type === "toggle") {
      values[control.id] = false;
      continue;
    }
    if (control.type === "range") {
      values[control.id] = typeof control.min === "number" ? control.min : 0;
      continue;
    }
    if (control.options && control.options.length > 0) {
      values[control.id] = control.options[0].value;
    }
  }
  return values;
}

function summarizeVisualSessionState(session: VisualSessionState): string {
  const controls = Object.entries(session.controlValues || {})
    .slice(0, 3)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
  const focus = [session.focusedAnnotationId, session.focusedNodeId]
    .filter(Boolean)
    .join(" / ");
  return [controls, focus].filter(Boolean).join(" | ");
}

function summarizeWidgetFeedback(feedback: WidgetFeedbackItem): string {
  if (feedback.summary) return feedback.summary;
  if (
    typeof feedback.score === "number" &&
    typeof feedback.total_count === "number"
  ) {
    return `${feedback.score}/${feedback.total_count}`;
  }
  if (
    typeof feedback.correct_count === "number" &&
    typeof feedback.total_count === "number"
  ) {
    return `${feedback.correct_count}/${feedback.total_count} dung`;
  }
  return feedback.widget_kind.replaceAll("_", " ");
}

function clampChatLifecycleString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return trimmed.length > MAX_CHAT_LIFECYCLE_STRING_CHARS
    ? `${trimmed.slice(0, MAX_CHAT_LIFECYCLE_STRING_CHARS - 3)}...`
    : trimmed;
}

function sanitizeChatLifecycleStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const output = value
    .map((item) => clampChatLifecycleString(item))
    .filter((item): item is string => Boolean(item))
    .slice(0, MAX_CHAT_LIFECYCLE_ARRAY_ITEMS);
  return output.length > 0 ? output : undefined;
}

function sanitizeChatLifecycleRecord(
  value: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object") return undefined;
  const output: Record<string, unknown> = {};
  for (const [key, rawValue] of Object.entries(value).slice(
    0,
    MAX_CHAT_LIFECYCLE_RECORD_KEYS,
  )) {
    if (typeof rawValue === "string") {
      const normalized = clampChatLifecycleString(rawValue);
      if (normalized) output[key] = normalized;
      continue;
    }
    if (
      typeof rawValue === "number" ||
      typeof rawValue === "boolean" ||
      rawValue === null
    ) {
      output[key] = rawValue;
      continue;
    }
    const strings = sanitizeChatLifecycleStringArray(rawValue);
    if (strings) output[key] = strings;
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

const WIII_CONNECT_CONNECTION_KEYS = new Set([
  "id",
  "provider_kind",
  "slug",
  "label",
  "status",
  "active",
  "agent_ready",
  "scopes",
  "capabilities",
  "required_for_paths",
  "source",
  "last_checked_at",
  "reason",
  "warnings",
  "host_type",
  "connector_id",
  "resource_count",
  "surface_count",
  "tool_count",
  "mutating_tool_count",
  "attachment_count",
  "document_count",
  "source_ref_count",
  "target_count",
  "fail_closed_tool",
  "default_city",
]);

const WIII_CONNECT_PATH_KEYS = new Set([
  "path",
  "allowed_connection_slugs",
  "required_connection_slugs",
  "allowed_tool_groups",
  "forbidden_tool_groups",
  "mutation_policy",
  "delegation_policy",
]);

function sanitizeWiiiConnectScopes(value: unknown): Record<string, boolean> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const output: Record<string, boolean> = {};
  for (const key of ["read", "preview", "write", "apply", "admin"]) {
    const rawValue = (value as Record<string, unknown>)[key];
    if (typeof rawValue === "boolean") output[key] = rawValue;
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

function sanitizeWiiiConnectRecord(
  value: unknown,
  allowedKeys: Set<string>,
): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const source = value as Record<string, unknown>;
  const output: Record<string, unknown> = {};
  for (const key of allowedKeys) {
    const rawValue = source[key];
    if (rawValue === undefined) continue;
    if (key === "scopes") {
      const scopes = sanitizeWiiiConnectScopes(rawValue);
      if (scopes) output[key] = scopes;
      continue;
    }
    if (typeof rawValue === "string") {
      const normalized = clampChatLifecycleString(rawValue);
      if (normalized) output[key] = normalized;
      continue;
    }
    if (
      typeof rawValue === "number" ||
      typeof rawValue === "boolean" ||
      rawValue === null
    ) {
      output[key] = rawValue;
      continue;
    }
    const strings = sanitizeChatLifecycleStringArray(rawValue);
    if (strings) output[key] = strings;
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

function sanitizeWiiiConnectSnapshot(
  value: unknown,
): WiiiConnectRuntimeSnapshot | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const source = value as Record<string, unknown>;
  const version = clampChatLifecycleString(source.version);
  if (!version) return undefined;
  const snapshot: WiiiConnectRuntimeSnapshot = { version };
  const generatedAt = clampChatLifecycleString(source.generated_at);
  if (generatedAt) snapshot.generated_at = generatedAt;
  const surface = clampChatLifecycleString(source.surface);
  if (surface) snapshot.surface = surface;

  if (Array.isArray(source.connections)) {
    const connections = source.connections
      .map((item) => sanitizeWiiiConnectRecord(item, WIII_CONNECT_CONNECTION_KEYS))
      .filter((item): item is WiiiConnectRuntimeConnection => {
        return Boolean(
          item &&
          typeof item.slug === "string" &&
          typeof item.label === "string" &&
          typeof item.status === "string",
        );
      })
      .slice(0, MAX_CHAT_LIFECYCLE_ARRAY_ITEMS);
    if (connections.length > 0) snapshot.connections = connections;
  }

  if (Array.isArray(source.path_capabilities)) {
    const pathCapabilities = source.path_capabilities
      .map((item) => sanitizeWiiiConnectRecord(item, WIII_CONNECT_PATH_KEYS))
      .filter((item): item is WiiiConnectRuntimePathCapability => {
        return Boolean(item && typeof item.path === "string");
      })
      .slice(0, MAX_CHAT_LIFECYCLE_ARRAY_ITEMS);
    if (pathCapabilities.length > 0) {
      snapshot.path_capabilities = pathCapabilities;
    }
  }

  const warnings = sanitizeChatLifecycleStringArray(source.warnings);
  if (warnings) snapshot.warnings = warnings;
  return snapshot;
}

function sanitizeChatLifecycleCapabilities(
  capabilities: SSEChatLifecycleEvent["capabilities"],
): SSEChatLifecycleEvent["capabilities"] | undefined {
  if (!capabilities) return undefined;
  const output: NonNullable<SSEChatLifecycleEvent["capabilities"]> = {};
  const hostSurface = clampChatLifecycleString(capabilities.host_surface);
  if (hostSurface) output.host_surface = hostSurface;
  const hostCapabilities = sanitizeChatLifecycleStringArray(
    capabilities.host_capabilities,
  );
  if (hostCapabilities) output.host_capabilities = hostCapabilities;
  const observedTools = sanitizeChatLifecycleStringArray(
    capabilities.observed_tools,
  );
  if (observedTools) output.observed_tools = observedTools;
  const suppressedTools = sanitizeChatLifecycleStringArray(
    capabilities.suppressed_tools,
  );
  if (suppressedTools) output.suppressed_tools = suppressedTools;
  if (typeof capabilities.preview_required === "boolean") {
    output.preview_required = capabilities.preview_required;
  }
  if (typeof capabilities.preview_emitted === "boolean") {
    output.preview_emitted = capabilities.preview_emitted;
  }
  if (typeof capabilities.approval_token_present === "boolean") {
    output.approval_token_present = capabilities.approval_token_present;
  }
  if (typeof capabilities.apply_attempted === "boolean") {
    output.apply_attempted = capabilities.apply_attempted;
  }
  const wiiiConnect = sanitizeWiiiConnectSnapshot(capabilities.wiii_connect);
  if (wiiiConnect) output.wiii_connect = wiiiConnect;
  return Object.keys(output).length > 0 ? output : undefined;
}

function normalizeChatLifecycleEvent(
  event: SSEChatLifecycleEvent,
): ChatLifecycleTelemetryEvent {
  const normalized: ChatLifecycleTelemetryEvent = {
    schema_version:
      clampChatLifecycleString(event.schema_version) || "unknown",
    event_name: clampChatLifecycleString(event.event_name) || "unknown",
    phase: clampChatLifecycleString(event.phase) || "unknown",
    status: clampChatLifecycleString(event.status) || "unknown",
    message: clampChatLifecycleString(event.message) || "",
    received_at_ms: Date.now(),
  };
  const requestId = clampChatLifecycleString(event.request_id);
  if (requestId) normalized.request_id = requestId;
  const sessionId = clampChatLifecycleString(event.session_id);
  if (sessionId) normalized.session_id = sessionId;
  const lane = clampChatLifecycleString(event.lane);
  if (lane) normalized.lane = lane;
  const reason = clampChatLifecycleString(event.reason);
  if (reason) normalized.reason = reason;
  const node = clampChatLifecycleString(event.node);
  if (node) normalized.node = node;
  const step = clampChatLifecycleString(event.step);
  if (step) normalized.step = step;
  const capabilities = sanitizeChatLifecycleCapabilities(event.capabilities);
  if (capabilities) normalized.capabilities = capabilities;
  const metadata = sanitizeChatLifecycleRecord(event.metadata);
  if (metadata) normalized.metadata = metadata;
  const details = sanitizeChatLifecycleRecord(event.details);
  if (details) normalized.details = details;
  if (event.display_role) normalized.display_role = event.display_role;
  if (typeof event.sequence_id === "number") {
    normalized.sequence_id = event.sequence_id;
  }
  if (event.step_id) normalized.step_id = event.step_id;
  if (event.step_state) normalized.step_state = event.step_state;
  if (event.presentation) normalized.presentation = event.presentation;
  return normalized;
}

function cloneChatLifecycleEvents(
  events: ChatLifecycleTelemetryEvent[],
): ChatLifecycleTelemetryEvent[] {
  return events.map((event) => ({
    ...event,
    capabilities: event.capabilities
      ? {
          ...event.capabilities,
          host_capabilities: event.capabilities.host_capabilities
            ? [...event.capabilities.host_capabilities]
            : undefined,
          observed_tools: event.capabilities.observed_tools
            ? [...event.capabilities.observed_tools]
            : undefined,
          suppressed_tools: event.capabilities.suppressed_tools
            ? [...event.capabilities.suppressed_tools]
            : undefined,
          wiii_connect: event.capabilities.wiii_connect
            ? {
                ...event.capabilities.wiii_connect,
                connections: event.capabilities.wiii_connect.connections
                  ? event.capabilities.wiii_connect.connections.map((connection) => ({
                      ...connection,
                      capabilities: connection.capabilities ? [...connection.capabilities] : undefined,
                      required_for_paths: connection.required_for_paths
                        ? [...connection.required_for_paths]
                        : undefined,
                      warnings: connection.warnings ? [...connection.warnings] : undefined,
                      scopes: connection.scopes ? { ...connection.scopes } : undefined,
                    }))
                  : undefined,
                path_capabilities: event.capabilities.wiii_connect.path_capabilities
                  ? event.capabilities.wiii_connect.path_capabilities.map((path) => ({
                      ...path,
                      allowed_connection_slugs: path.allowed_connection_slugs
                        ? [...path.allowed_connection_slugs]
                        : undefined,
                      required_connection_slugs: path.required_connection_slugs
                        ? [...path.required_connection_slugs]
                        : undefined,
                      allowed_tool_groups: path.allowed_tool_groups
                        ? [...path.allowed_tool_groups]
                        : undefined,
                      forbidden_tool_groups: path.forbidden_tool_groups
                        ? [...path.forbidden_tool_groups]
                        : undefined,
                    }))
                  : undefined,
                warnings: event.capabilities.wiii_connect.warnings
                  ? [...event.capabilities.wiii_connect.warnings]
                  : undefined,
              }
            : undefined,
        }
      : undefined,
    metadata: event.metadata ? { ...event.metadata } : undefined,
    details: event.details ? { ...event.details } : undefined,
  }));
}

function mergeChatLifecycleMetadata(
  metadata: Record<string, unknown> | undefined,
  lifecycleEvents: ChatLifecycleTelemetryEvent[],
): Record<string, unknown> | undefined {
  if (lifecycleEvents.length === 0) return metadata;
  const existingEvents = Array.isArray(metadata?.chat_lifecycle)
    ? (metadata?.chat_lifecycle as ChatLifecycleTelemetryEvent[])
    : [];
  return {
    ...(metadata || {}),
    chat_lifecycle: cloneChatLifecycleEvents([
      ...existingEvents,
      ...lifecycleEvents,
    ]).slice(-MAX_CHAT_LIFECYCLE_EVENTS),
  };
}

function matchesVisualBlockSession(
  block: VisualBlockData,
  sessionId: string,
  visualId?: string,
): boolean {
  return Boolean(
    (block.sessionId || block.visual.visual_session_id) === sessionId ||
    block.id === sessionId ||
    (visualId && block.visual.id === visualId),
  );
}

function upsertVisualBlockDraft(
  state: Pick<ChatState, "streamingBlocks">,
  visual: VisualPayload,
  node?: string,
  meta?: DisplayPresentationMeta,
  status: VisualSessionState["status"] = "open",
): void {
  const sessionId = getVisualSessionId(visual);
  const existingIdx = state.streamingBlocks.findIndex(
    (block) =>
      block.type === "visual" &&
      ((block as VisualBlockData).sessionId === sessionId ||
        (block as VisualBlockData).visual.visual_session_id === sessionId ||
        (block as VisualBlockData).id === sessionId ||
        (block as VisualBlockData).visual.id === visual.id),
  );

  if (existingIdx >= 0) {
    const existing = state.streamingBlocks[existingIdx] as VisualBlockData;
    existing.id = sessionId;
    existing.sessionId = sessionId;
    existing.visual = visual;
    existing.node = node ?? existing.node;
    existing.status = status;
    applyDisplayMeta(existing, meta);
    return;
  }

  state.streamingBlocks.push(
    applyDisplayMeta(
      {
        type: "visual",
        id: sessionId,
        sessionId,
        visual,
        node,
        status,
        displayRole: "artifact",
        presentation: "compact",
      } as VisualBlockData,
      meta,
    ),
  );
}

function attachVisualSessionIdToToolExecutionDraft(
  state: Pick<ChatState, "streamingBlocks" | "streamingToolCalls">,
  sessionId: string,
  sourceTool?: string,
  node?: string,
): void {
  const matchingToolName =
    sourceTool && VISUAL_TOOL_EXECUTION_NAMES.has(sourceTool)
      ? sourceTool
      : undefined;

  for (let i = state.streamingBlocks.length - 1; i >= 0; i--) {
    const block = state.streamingBlocks[i];
    if (block.type !== "tool_execution") continue;
    const toolBlock = block as ToolExecutionBlockData;
    if (!VISUAL_TOOL_EXECUTION_NAMES.has(toolBlock.tool.name)) continue;
    if (matchingToolName && toolBlock.tool.name !== matchingToolName) continue;
    if (node && toolBlock.node && toolBlock.node !== node) continue;

    const args = toolBlock.tool.args || {};
    if (typeof args.visual_session_id === "string" && args.visual_session_id)
      return;
    toolBlock.tool.args = {
      ...args,
      visual_session_id: sessionId,
    };

    const flatToolCall = state.streamingToolCalls.find(
      (tc) => tc.id === toolBlock.tool.id,
    );
    if (flatToolCall) {
      flatToolCall.args = {
        ...(flatToolCall.args || {}),
        visual_session_id: sessionId,
      };
    }
    return;
  }
}

function upsertPersistedVisualBlockDraft(
  state: Pick<ChatState, "conversations" | "activeConversationId">,
  visual: VisualPayload,
  node?: string,
  meta?: DisplayPresentationMeta,
  status: VisualSessionState["status"] = "open",
): boolean {
  const conversation = state.conversations.find(
    (item) => item.id === state.activeConversationId,
  );
  if (!conversation) return false;

  const sessionId = getVisualSessionId(visual);
  let updated = false;

  for (const message of conversation.messages) {
    if (!message.blocks) continue;
    for (const block of message.blocks) {
      if (block.type !== "visual") continue;
      const visualBlock = block as VisualBlockData;
      if (!matchesVisualBlockSession(visualBlock, sessionId, visual.id))
        continue;
      visualBlock.id = sessionId;
      visualBlock.sessionId = sessionId;
      visualBlock.visual = visual;
      visualBlock.node = node ?? visualBlock.node;
      visualBlock.status = status;
      applyDisplayMeta(visualBlock, meta);
      updated = true;
    }
  }

  return updated;
}

function markVisualSessionStatusDraft(
  state: Pick<
    ChatState,
    | "visualSessions"
    | "streamingBlocks"
    | "conversations"
    | "activeConversationId"
  >,
  sessionId: string,
  status: VisualSessionState["status"],
): void {
  const session = state.visualSessions[sessionId];
  if (session) {
    session.status = status;
    session.lastUpdatedAt = Date.now();
  }
  for (const block of state.streamingBlocks) {
    if (
      block.type === "visual" &&
      matchesVisualBlockSession(block as VisualBlockData, sessionId)
    ) {
      (block as VisualBlockData).status = status;
    }
  }

  const conversation = state.conversations.find(
    (item) => item.id === state.activeConversationId,
  );
  if (!conversation) return;
  for (const message of conversation.messages) {
    if (!message.blocks) continue;
    for (const block of message.blocks) {
      if (
        block.type === "visual" &&
        matchesVisualBlockSession(block as VisualBlockData, sessionId)
      ) {
        (block as VisualBlockData).status = status;
      }
    }
  }
}

function disposeLiveVisualSessionsDraft(
  state: Pick<
    ChatState,
    | "visualSessions"
    | "streamingBlocks"
    | "conversations"
    | "activeConversationId"
  >,
): void {
  for (const session of Object.values(state.visualSessions)) {
    if (session.status === "open") {
      markVisualSessionStatusDraft(state, session.sessionId, "disposed");
    }
  }
}

function upsertConversationWidgetFeedbackDraft(
  state: Pick<ChatState, "conversations" | "activeConversationId">,
  feedback: WidgetFeedbackItem,
): void {
  const conversation = state.conversations.find(
    (item) => item.id === state.activeConversationId,
  );
  if (!conversation) return;

  const items = conversation.widget_feedback || [];
  const existingIndex = items.findIndex(
    (item) => item.widget_id === feedback.widget_id,
  );
  if (existingIndex >= 0) {
    items[existingIndex] = {
      ...items[existingIndex],
      ...feedback,
    };
  } else {
    items.unshift(feedback);
  }

  conversation.widget_feedback = items
    .slice()
    .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
    .slice(0, 12);
}

function resetStreamingDraft(state: ChatState): void {
  _pendingAnswerInternalMarkup = "";
  state.isStreaming = false;
  state.streamingContent = "";
  state.streamingThinking = "";
  state.streamingSources = [];
  state.streamingStep = "";
  state.streamingToolCalls = [];
  state.streamingBlocks = [];
  state.streamingStartTime = null;
  state.streamingSteps = [];
  state.streamingLifecycleEvents = [];
  state.streamingDomainNotice = "";
  state.streamingPhases = [];
  state.streamingPreviews = [];
  state.streamingArtifacts = [];
  state.pendingStreamMetadata = null;
  state._activeSubagentGroupId = null;
}

export const useChatStore = create<ChatState>()(
  immer((set, get) => ({
    conversations: [],
    activeConversationId: null,
    searchQuery: "",
    isLoaded: false,
    isStreaming: false,
    streamingContent: "",
    streamingThinking: "",
    streamingSources: [],
    streamingStep: "",
    streamingToolCalls: [],
    streamingBlocks: [],
    streamingStartTime: null,
    streamingSteps: [],
    streamingLifecycleEvents: [],
    lastCompletedLifecycleEvents: [],
    streamingDomainNotice: "",
    streamingPhases: [],
    streamingPreviews: [],
    streamingArtifacts: [],
    pendingStreamMetadata: null,
    visualSessions: {},
    _activeSubagentGroupId: null,
    streamError: "",
    streamCompletedAt: null,
    lastCompletedConversationId: null,

    loadConversations: async () => {
      try {
        // Sprint 218: Resolve current user_id for per-user storage
        // Sprint 223-fix: Also read from embed config as fallback (JWT user_id)
        try {
          const { resolveCurrentChatUserId } =
            await import("@/stores/chat-store-runtime");
          _currentUserId = resolveCurrentChatUserId();
        } catch {
          _currentUserId = null;
        }

        // Fallback: read user_id from embed config (set by EmbedApp after JWT decode)
        if (!_currentUserId) {
          const embedConfig = (window as any)?.__WIII_EMBED_CONFIG__;
          if (embedConfig?.user_id) {
            _currentUserId = embedConfig.user_id;
          }
        }

        const saved = await loadStore<Conversation[]>(
          getStoreName(),
          getStoreKey(),
          [],
        );
        if (saved.length > 0) {
          set((state) => {
            state.conversations = saved;
            state.activeConversationId = saved[0]?.id || null;
            state.isLoaded = true;
          });
        } else {
          set((state) => {
            state.isLoaded = true;
          });
        }

        // Sprint 225: Background server sync (non-blocking)
        get()
          .syncFromServer()
          .catch((err) =>
            console.debug("[chat-store] Server sync skipped:", err),
          );
      } catch (err) {
        console.warn("[chat-store] Failed to load conversations:", err);
        set((state) => {
          state.isLoaded = true;
        });
      }
    },

    activeConversation: () => {
      const { conversations, activeConversationId } = get();
      return conversations.find((c) => c.id === activeConversationId);
    },

    createConversation: (domainId, organizationId, sessionId) => {
      const id = uuidv4();
      const now = new Date().toISOString();
      const conversation: Conversation = {
        id,
        title: "Cuộc trò chuyện mới",
        domain_id: domainId,
        organization_id: organizationId || undefined,
        created_at: now,
        updated_at: now,
        messages: [],
        // Sprint 220c: Pre-set session_id for embed session resumption
        session_id: sessionId || undefined,
      };

      set((state) => {
        state.conversations.unshift(conversation);
        state.activeConversationId = id;
      });

      persistConversationsImmediate(get().conversations);
      return id;
    },

    deleteConversation: (id) => {
      // Sprint 225: Capture thread_id before removing from state
      const conv = get().conversations.find((c) => c.id === id);
      const threadId = conv?.thread_id;

      set((state) => {
        const idx = state.conversations.findIndex((c) => c.id === id);
        if (idx >= 0) state.conversations.splice(idx, 1);
        if (state.activeConversationId === id) {
          state.activeConversationId = state.conversations[0]?.id || null;
        }
      });
      persistConversationsImmediate(get().conversations);

      // Sprint 225: Fire-and-forget server delete
      if (threadId) {
        import("@/api/threads").then(({ deleteServerThread }) =>
          deleteServerThread(threadId).catch(() => {}),
        );
      }
    },

    setActiveConversation: (id) => {
      set((state) => {
        state.activeConversationId = id;
      });
      // Sprint 225: Lazy-load server messages for stub conversations
      if (id) {
        get().loadServerMessages(id);
      }
    },

    renameConversation: (id, title) => {
      // Sprint 225: Capture thread_id for server propagation
      const conv = get().conversations.find((c) => c.id === id);
      const threadId = conv?.thread_id;

      set((state) => {
        const found = state.conversations.find((c) => c.id === id);
        if (found) {
          found.title = title;
          found.updated_at = new Date().toISOString();
          found.user_renamed = true; // Sprint 225: prevent server overwrite
        }
      });
      persistConversationsImmediate(get().conversations);

      // Sprint 225: Fire-and-forget server rename
      if (threadId) {
        import("@/api/threads").then(({ renameServerThread }) =>
          renameServerThread(threadId, title).catch(() => {}),
        );
      }
    },

    setSearchQuery: (query) => {
      set((state) => {
        state.searchQuery = query;
      });
    },

    pinConversation: (id) => {
      set((state) => {
        const conv = state.conversations.find((c) => c.id === id);
        if (conv) conv.pinned = true;
      });
      persistConversationsImmediate(get().conversations);
    },

    unpinConversation: (id) => {
      set((state) => {
        const conv = state.conversations.find((c) => c.id === id);
        if (conv) conv.pinned = false;
      });
      persistConversationsImmediate(get().conversations);
    },

    addUserMessage: (content, images, documents) => {
      const { activeConversationId, conversations } = get();
      if (!activeConversationId) return null;

      const messageId = uuidv4();
      const message: Message = {
        id: messageId,
        role: "user",
        content,
        timestamp: new Date().toISOString(),
        // Sprint 179: Attach images to user message for display
        ...(images && images.length > 0 ? { images } : {}),
        ...(documents && documents.length > 0 ? { documents } : {}),
      };

      const conversation = conversations.find(
        (c) => c.id === activeConversationId,
      );
      const isFirstMessage = conversation?.messages.length === 0;

      set((state) => {
        const conv = state.conversations.find(
          (c) => c.id === activeConversationId,
        );
        if (conv) {
          conv.messages.push(message);
          conv.updated_at = new Date().toISOString();
          if (isFirstMessage) {
            conv.title =
              content.slice(0, 50) + (content.length > 50 ? "..." : "");
          }
        }
      });

      persistConversations(get().conversations);
      return messageId;
    },

    startStreaming: () => {
      set((state) => {
        disposeLiveVisualSessionsDraft(state);
        resetStreamingDraft(state);
        state.isStreaming = true;
        state.streamingStartTime = Date.now();
        state.streamError = "";
        state.streamCompletedAt = null;
        state.lastCompletedConversationId = null;
        state.lastCompletedLifecycleEvents = [];
      });
    },

    appendStreamingContent: (chunk) => {
      set((state) => {
        const internalMarkup = stripWiiiInternalMarkupFromStream(
          chunk,
          _pendingAnswerInternalMarkup,
        );
        _pendingAnswerInternalMarkup = internalMarkup.pending;
        // Strip visual reference markers that LLM puts in answer text
        const clean = internalMarkup.content
          .replace(/\{visual-[a-f0-9]+\}/gi, "")
          .replace(/<!-- WiiiVisualBridge:visual-[a-f0-9]+ -->/gi, "")
          .replace(/\[Biểu đồ[^\]]*\]/gi, "")
          .replace(/\[Chart[^\]]*\]/gi, "")
          .replace(/\[Visual[^\]]*\]/gi, "")
          .replace(/\(Visuals?[^)]*hiển thị[^)]*\)/gi, "")
          .replace(/\(Visual[^)]*displayed[^)]*\)/gi, "")
          // v4.0 F7 (2026-05-06): Wiii Pointy inline tag — Clicky pattern.
          // LLM appends [POINT:bare-id] / [POINT:bare-id:caption] / [POINT:none]
          // at end of response. Strip from display; useSSEStream onDone
          // parses fullAnswerTextRef (unstripped) to dispatch cursor.
          .replace(/\[POINT:[^\]]+\]/g, "");
        if (!clean) return; // Skip if chunk was only a visual marker

        // Flat field — backward compat
        state.streamingContent += clean;

        // Block-based: append to last answer block, or create new one
        const lastBlock =
          state.streamingBlocks[state.streamingBlocks.length - 1];
        if (lastBlock?.type === "answer") {
          lastBlock.content += clean;
        } else {
          closeLastThinkingBlockDraft(state.streamingBlocks);
          state.streamingBlocks.push({
            type: "answer",
            id: uuidv4(),
            content: clean,
            displayRole: "answer",
            presentation: "compact",
          });
        }
      });
    },

    setStreamingThinking: (thinking) => {
      set((state) => {
        const normalizedThinking = normalizeNarrativeText(thinking);
        if (!normalizedThinking) return;

        const lastNarrativeLine = normalizeNarrativeText(
          getLastNarrativeLine(state.streamingThinking),
        );
        const lastBlock =
          state.streamingBlocks[state.streamingBlocks.length - 1];
        const lastBlockLine =
          lastBlock?.type === "thinking"
            ? normalizeNarrativeText(getLastNarrativeLine(lastBlock.content))
            : "";
        if (
          normalizedThinking === lastNarrativeLine &&
          normalizedThinking === lastBlockLine
        ) {
          return;
        }
        if (hasNarrativeSegment(state.streamingThinking, thinking)) {
          return;
        }
        if (
          lastBlock?.type === "thinking" &&
          hasNarrativeSegment(lastBlock.content, thinking)
        ) {
          return;
        }

        // Flat field — backward compat
        state.streamingThinking = state.streamingThinking
          ? state.streamingThinking + "\n" + thinking
          : thinking;

        // Block-based: append to last thinking block, or create new one
        if (lastBlock?.type === "thinking") {
          lastBlock.content = lastBlock.content
            ? lastBlock.content + "\n" + thinking
            : thinking;
        } else {
          state.streamingBlocks.push({
            type: "thinking",
            id: uuidv4(),
            label: sanitizeThinkingLabel(state.streamingStep),
            content: thinking,
            toolCalls: [],
            startTime: Date.now(),
          });
        }
      });
    },

    // Phase2: Update the latest thinking block's label with Wiii persona label
    setStreamingThinkingLabel: (label) => {
      set((state) => {
        const safeLabel = sanitizeThinkingLabel(label);
        if (!safeLabel) return;
        for (let i = state.streamingBlocks.length - 1; i >= 0; i--) {
          const block = state.streamingBlocks[i];
          if (block.type === "thinking") {
            (block as { label?: string }).label = safeLabel;
            break;
          }
        }
      });
    },

    setStreamingStep: (step) => {
      set((state) => {
        state.streamingStep = step;
        const lastBlock =
          state.streamingBlocks[state.streamingBlocks.length - 1];
        const safeLabel = sanitizeThinkingLabel(step);
        if (lastBlock?.type === "thinking" && !lastBlock.label && safeLabel) {
          lastBlock.label = safeLabel;
        }
      });
    },

    setStreamingSources: (sources) => {
      let attachedToFinalMessage = false;
      set((state) => {
        if (state.isStreaming) {
          state.streamingSources =
            sources.length === 0
              ? []
              : mergeSourceInfos(state.streamingSources, sources);
          return;
        }
        if (sources.length > 0) {
          attachedToFinalMessage = attachSourcesToLastAssistantDraft(
            state,
            sources,
            state.lastCompletedConversationId,
          );
        }
      });
      if (attachedToFinalMessage) {
        persistConversationsImmediate(get().conversations);
      }
    },

    addStreamingStep: (label, node) => {
      set((state) => {
        state.streamingSteps.push({ label, node, timestamp: Date.now() });
      });
    },

    addChatLifecycleEvent: (event) => {
      const normalized = normalizeChatLifecycleEvent(event);
      set((state) => {
        state.streamingLifecycleEvents.push(normalized);
        const overflow =
          state.streamingLifecycleEvents.length - MAX_CHAT_LIFECYCLE_EVENTS;
        if (overflow > 0) {
          state.streamingLifecycleEvents.splice(0, overflow);
        }
      });
    },

    appendThinkingDelta: (delta, node, meta) => {
      set((state) => {
        if (!delta || !delta.trim()) {
          return;
        }
        const openBlock = findLastOpenThinkingBlock(
          state.streamingBlocks,
          meta?.stepId,
          node,
        );
        const previousBlock =
          openBlock ||
          findLastThinkingBlock(state.streamingBlocks, meta?.stepId, node);
        const existingNarrative = buildThinkingDedupContext(
          openBlock,
          previousBlock,
          state.streamingThinking,
        );
        if (shouldSkipRepeatedNarrative(existingNarrative, delta)) {
          return;
        }

        // Flat field - backward compat
        state.streamingThinking += delta;

        // Block-based: append to matching open thinking block, or create new one
        if (openBlock) {
          openBlock.content += delta;
          if (node && !openBlock.node) {
            openBlock.node = node;
          }
          applyDisplayMeta(openBlock, meta);
        } else {
          if (
            previousBlock &&
            meta?.stepId &&
            previousBlock.stepId === meta.stepId
          ) {
            previousBlock.content += delta;
            if (node && !previousBlock.node) {
              previousBlock.node = node;
            }
            applyDisplayMeta(previousBlock, meta);
            return;
          }
          const groupId = state._activeSubagentGroupId;
          state.streamingBlocks.push(
            applyDisplayMeta(
              {
                type: "thinking",
                id: uuidv4(),
                label:
                  sanitizeThinkingLabel(previousBlock?.label) ||
                  sanitizeThinkingLabel(state.streamingStep),
                summary: previousBlock?.summary,
                summaryMode: previousBlock?.summaryMode,
                phase: previousBlock?.phase,
                node,
                content: delta,
                toolCalls: [],
                startTime: Date.now(),
                ...(groupId ? { groupId, workerNode: node } : {}),
                displayRole: "thinking",
                presentation: "expanded",
              },
              meta,
            ),
          );
        }
      });
    },

    openThinkingBlock: (label, summary, node, phase, meta, summaryMode) => {
      set((state) => {
        // Close any open thinking block first
        const lastBlock = findLastOpenThinkingBlock(state.streamingBlocks);
        if (lastBlock) {
          lastBlock.endTime = Date.now();
          lastBlock.stepState = "completed";
        }
        // Open new thinking block - tag with group + workerNode if inside parallel dispatch
        const groupId = state._activeSubagentGroupId;
        state.streamingBlocks.push(
          applyDisplayMeta(
            {
              type: "thinking",
              id: uuidv4(),
              label,
              summary,
              summaryMode,
              node,
              phase,
              content: "",
              toolCalls: [],
              startTime: Date.now(),
              ...(groupId ? { groupId, workerNode: node } : {}),
              displayRole: "thinking",
              stepState: "live",
              presentation: "expanded",
            },
            meta,
          ),
        );
      });
    },

    setStreamingDomainNotice: (notice) => {
      set((state) => {
        state.streamingDomainNotice = notice;
      });
    },

    appendActionText: (text, node, meta) => {
      set((state) => {
        closeLastThinkingBlockDraft(state.streamingBlocks);
        const lastBlock =
          state.streamingBlocks[state.streamingBlocks.length - 1];
        if (
          lastBlock?.type === "action_text" &&
          normalizeNarrativeText(lastBlock.content) ===
            normalizeNarrativeText(text) &&
          (lastBlock.node || "") === (node || "")
        ) {
          return;
        }
        state.streamingBlocks.push(
          applyDisplayMeta(
            {
              type: "action_text",
              id: uuidv4(),
              content: text,
              node,
              displayRole: "action",
              presentation: "compact",
            },
            meta,
          ),
        );
      });
    },

    appendScreenshot: (data, meta) => {
      set((state) => {
        closeLastThinkingBlockDraft(state.streamingBlocks);
        const block: ScreenshotBlockData = applyDisplayMeta(
          {
            type: "screenshot",
            id: `screenshot-${Date.now()}`,
            ...data,
            displayRole: "artifact",
            presentation: "compact",
          },
          meta,
        );
        state.streamingBlocks.push(block);
      });
    },

    // ---- Sprint 164: Subagent group actions ----

    openSubagentGroup: (label, agentNames) => {
      set((state) => {
        // Close any open thinking block first
        closeLastThinkingBlockDraft(state.streamingBlocks);

        const groupId = uuidv4();
        const workers: SubagentWorker[] = agentNames.map((name) => ({
          agentName: name,
          label: name,
          status: "active" as const,
          startTime: Date.now(),
          statusMessages: [],
        }));

        const block: SubagentGroupBlockData = {
          type: "subagent_group",
          id: groupId,
          label,
          workers,
          startTime: Date.now(),
        };

        state.streamingBlocks.push(block);
        state._activeSubagentGroupId = groupId;
      });
    },

    closeSubagentGroup: () => {
      set((state) => {
        const groupId = state._activeSubagentGroupId;
        if (!groupId) return;

        // Close any open thinking block
        closeLastThinkingBlockDraft(state.streamingBlocks);

        // Find the group block and set endTime + mark workers completed
        for (const block of state.streamingBlocks) {
          if (block.type === "subagent_group" && block.id === groupId) {
            block.endTime = Date.now();
            for (const w of block.workers) {
              if (w.status === "active") {
                w.status = "completed";
                w.endTime = Date.now();
              }
            }
            break;
          }
        }

        state._activeSubagentGroupId = null;
      });
    },

    setAggregationSummary: (summary) => {
      set((state) => {
        // Find the most recent subagent_group block
        for (let i = state.streamingBlocks.length - 1; i >= 0; i--) {
          const block = state.streamingBlocks[i];
          if (block.type === "subagent_group") {
            block.aggregation = summary;
            break;
          }
        }
      });
    },

    markWorkerCompleted: (workerNode) => {
      set((state) => {
        const groupId = state._activeSubagentGroupId;
        if (!groupId) return;

        for (const block of state.streamingBlocks) {
          if (block.type === "subagent_group" && block.id === groupId) {
            const worker = block.workers.find(
              (w) => w.agentName === workerNode,
            );
            if (worker && worker.status === "active") {
              worker.status = "completed";
              worker.endTime = Date.now();
            }
            break;
          }
        }
      });
    },

    appendWorkerStatus: (workerNode, message) => {
      set((state) => {
        const groupId = state._activeSubagentGroupId;
        if (!groupId) return;

        for (const block of state.streamingBlocks) {
          if (block.type === "subagent_group" && block.id === groupId) {
            const worker = block.workers.find(
              (w) => w.agentName === workerNode,
            );
            if (worker) {
              worker.statusMessages.push(message);
            }
            break;
          }
        }
      });
    },

    // ---- Sprint 166: Preview card actions ----

    addPreviewItem: (item, node, meta) => {
      set((state) => {
        // Dedup by preview_id
        if (
          state.streamingPreviews.some((p) => p.preview_id === item.preview_id)
        )
          return;
        state.streamingPreviews.push(item);

        // Find or create preview block in streamingBlocks
        const lastBlock =
          state.streamingBlocks[state.streamingBlocks.length - 1];
        if (
          lastBlock?.type === "preview" &&
          (lastBlock as PreviewBlockData).node === node
        ) {
          // Append to existing group
          (lastBlock as PreviewBlockData).items.push(item);
          applyDisplayMeta(lastBlock as PreviewBlockData, meta);
        } else {
          // New preview block
          closeLastThinkingBlockDraft(state.streamingBlocks);
          state.streamingBlocks.push(
            applyDisplayMeta(
              {
                type: "preview",
                id: uuidv4(),
                items: [item],
                node,
                displayRole: "tool",
                presentation: "compact",
              } as PreviewBlockData,
              meta,
            ),
          );
        }
      });
    },

    // ---- Sprint 167: Artifact actions ----

    addArtifact: (artifact, node, meta) => {
      set((state) => {
        // L-4: Content size limit (1MB)
        const MAX_ARTIFACT_SIZE = 1_000_000;
        if (artifact.content.length > MAX_ARTIFACT_SIZE) {
          console.warn(
            `[chat-store] Artifact ${artifact.artifact_id} exceeds 1MB, truncating`,
          );
          artifact = {
            ...artifact,
            content:
              artifact.content.slice(0, MAX_ARTIFACT_SIZE) +
              "\n// ... truncated",
          };
        }

        // M-1: Upsert — update existing artifact instead of dropping
        const existingIdx = state.streamingArtifacts.findIndex(
          (a) => a.artifact_id === artifact.artifact_id,
        );
        if (existingIdx >= 0) {
          state.streamingArtifacts[existingIdx] = artifact;
          // Update block too
          const blockIdx = state.streamingBlocks.findIndex(
            (b) =>
              b.type === "artifact" &&
              (b as ArtifactBlockData).id === artifact.artifact_id,
          );
          if (blockIdx >= 0) {
            (state.streamingBlocks[blockIdx] as ArtifactBlockData).artifact =
              artifact;
            applyDisplayMeta(
              state.streamingBlocks[blockIdx] as ArtifactBlockData,
              meta,
            );
          }
          return;
        }

        // New artifact
        state.streamingArtifacts.push(artifact);

        // Artifacts can arrive mid-step (e.g. think -> tool -> artifact -> think).
        // Do not force-close the active thinking block here, otherwise later
        // post-tool reflections get split into a duplicate block.
        state.streamingBlocks.push(
          applyDisplayMeta(
            {
              type: "artifact",
              id: artifact.artifact_id,
              artifact,
              node,
              displayRole: "artifact",
              presentation: "compact",
            } as ArtifactBlockData,
            meta,
          ),
        );
      });
    },

    addVisual: (visual, node, meta) => {
      get().openVisualSession(visual, node, meta);
    },

    openVisualSession: (visual, node, meta) => {
      set((state) => {
        const sessionId = getVisualSessionId(visual);
        const existing = state.visualSessions[sessionId];
        attachVisualSessionIdToToolExecutionDraft(
          state,
          sessionId,
          typeof visual.metadata?.source_tool === "string"
            ? visual.metadata.source_tool
            : undefined,
          node,
        );
        state.visualSessions[sessionId] = {
          sessionId,
          latestVisual: visual,
          status: "open",
          revisionCount: (existing?.revisionCount || 0) + 1,
          node: node ?? existing?.node,
          controlValues: existing?.controlValues
            ? {
                ...getDefaultVisualControlValues(visual),
                ...existing.controlValues,
              }
            : getDefaultVisualControlValues(visual),
          focusedAnnotationId: existing?.focusedAnnotationId,
          focusedNodeId: existing?.focusedNodeId,
          interactionCount: existing?.interactionCount || 0,
          lastUpdatedAt: Date.now(),
        };
        upsertVisualBlockDraft(state, visual, node, meta, "open");
      });
    },

    patchVisualSession: (visual, node, meta) => {
      set((state) => {
        const sessionId = getVisualSessionId(visual);
        const existing = state.visualSessions[sessionId];
        attachVisualSessionIdToToolExecutionDraft(
          state,
          sessionId,
          typeof visual.metadata?.source_tool === "string"
            ? visual.metadata.source_tool
            : undefined,
          node,
        );
        state.visualSessions[sessionId] = {
          sessionId,
          latestVisual: visual,
          status: "open",
          revisionCount: (existing?.revisionCount || 0) + 1,
          node: node ?? existing?.node,
          controlValues: existing?.controlValues
            ? {
                ...getDefaultVisualControlValues(visual),
                ...existing.controlValues,
              }
            : getDefaultVisualControlValues(visual),
          focusedAnnotationId: existing?.focusedAnnotationId,
          focusedNodeId: existing?.focusedNodeId,
          interactionCount: existing?.interactionCount || 0,
          lastUpdatedAt: Date.now(),
        };
        const patchedPersistedBlock = upsertPersistedVisualBlockDraft(
          state,
          visual,
          node,
          meta,
          "open",
        );
        if (!patchedPersistedBlock) {
          upsertVisualBlockDraft(state, visual, node, meta, "open");
        }
      });
    },

    commitVisualSession: (sessionId) => {
      set((state) => {
        if (!sessionId) return;
        markVisualSessionStatusDraft(state, sessionId, "committed");
      });
    },

    disposeVisualSession: (sessionId, _reason) => {
      set((state) => {
        if (!sessionId) return;
        markVisualSessionStatusDraft(state, sessionId, "disposed");
      });
    },

    updateVisualSessionInteraction: (sessionId, patch) => {
      set((state) => {
        const session = state.visualSessions[sessionId];
        if (!session) return;
        if (patch.controlValues) {
          session.controlValues = {
            ...session.controlValues,
            ...patch.controlValues,
          };
        }
        if (typeof patch.focusedAnnotationId !== "undefined") {
          session.focusedAnnotationId = patch.focusedAnnotationId;
        }
        if (typeof patch.focusedNodeId !== "undefined") {
          session.focusedNodeId = patch.focusedNodeId;
        }
        session.interactionCount += patch.interactionDelta || 0;
        session.lastUpdatedAt = Date.now();
      });
    },

    getActiveVisualContext: () => {
      const {
        activeConversationId,
        conversations,
        streamingBlocks,
        visualSessions,
      } = get();
      const conversation = conversations.find(
        (item) => item.id === activeConversationId,
      );
      const persistedVisualBlocks = (conversation?.messages || [])
        .flatMap((message) => message.blocks || [])
        .filter((block): block is VisualBlockData => block.type === "visual");
      const liveVisualBlocks = streamingBlocks.filter(
        (block): block is VisualBlockData => block.type === "visual",
      );
      const orderedBlocks = [...persistedVisualBlocks, ...liveVisualBlocks];
      const lastVisualBlock =
        orderedBlocks.length > 0
          ? orderedBlocks[orderedBlocks.length - 1]
          : undefined;

      const sessionSummaries = Object.values(visualSessions)
        .filter((session) => session.status !== "disposed")
        .sort((a, b) => b.lastUpdatedAt - a.lastUpdatedAt)
        .map((session) => ({
          visual_session_id: session.sessionId,
          type: session.latestVisual.type,
          title: session.latestVisual.title,
          renderer_kind: session.latestVisual.renderer_kind,
          shell_variant: session.latestVisual.shell_variant,
          patch_strategy: session.latestVisual.patch_strategy,
          state_summary: summarizeVisualSessionState(session),
          status: session.status,
        }));
      if (sessionSummaries.length === 0 && lastVisualBlock?.visual) {
        sessionSummaries.push({
          visual_session_id:
            lastVisualBlock.visual.visual_session_id || lastVisualBlock.id,
          type: lastVisualBlock.visual.type,
          title: lastVisualBlock.visual.title,
          renderer_kind: lastVisualBlock.visual.renderer_kind,
          shell_variant: lastVisualBlock.visual.shell_variant,
          patch_strategy: lastVisualBlock.visual.patch_strategy,
          state_summary: "",
          status: lastVisualBlock.status || "committed",
        });
      }

      if (!lastVisualBlock && sessionSummaries.length === 0) {
        return undefined;
      }

      return {
        last_visual_session_id:
          lastVisualBlock?.visual.visual_session_id ||
          lastVisualBlock?.sessionId,
        last_visual_type: lastVisualBlock?.visual.type,
        last_visual_title: lastVisualBlock?.visual.title,
        visual_state_summary: sessionSummaries[0]?.state_summary,
        active_inline_visuals: sessionSummaries,
      };
    },

    recordWidgetFeedback: (feedback) => {
      const normalizedFeedback: WidgetFeedbackItem = {
        ...feedback,
        timestamp: feedback.timestamp || new Date().toISOString(),
      };

      set((state) => {
        upsertConversationWidgetFeedbackDraft(state, normalizedFeedback);
      });

      persistConversations(get().conversations);
    },

    getActiveWidgetFeedbackContext: () => {
      const { activeConversationId, conversations } = get();
      const conversation = conversations.find(
        (item) => item.id === activeConversationId,
      );
      const feedbackItems = [...(conversation?.widget_feedback || [])]
        .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
        .slice(0, 5);

      if (feedbackItems.length === 0) {
        return undefined;
      }

      const latest = feedbackItems[0];
      return {
        last_widget_kind: latest.widget_kind,
        last_widget_summary: summarizeWidgetFeedback(latest),
        recent_widget_feedback: feedbackItems.map((item) => ({
          widget_id: item.widget_id,
          widget_kind: item.widget_kind,
          summary: summarizeWidgetFeedback(item),
          status: item.status,
          title: item.title,
          visual_session_id: item.visual_session_id,
          score: item.score,
          correct_count: item.correct_count,
          total_count: item.total_count,
          source: item.source,
          payload: item.payload || item.data,
          session_id: item.session_id,
          message_id: item.message_id,
          version: item.version,
          timestamp: item.timestamp,
        })),
      };
    },

    // ---- Sprint 141: ThinkingFlow phase actions ----

    addOrUpdatePhase: (label, node, stepId, phase, summary, summaryMode) => {
      set((state) => {
        for (const p of state.streamingPhases) {
          if (p.status === "active") {
            p.status = "completed";
            p.endTime = Date.now();
          }
        }
        state.streamingPhases.push({
          id: uuidv4(),
          label,
          node,
          stepId,
          phase,
          summary,
          summaryMode,
          status: "active",
          startTime: Date.now(),
          thinkingContent: "",
          toolCalls: [],
          statusMessages: [],
        });
      });
    },

    appendPhaseThinking: (content, node, stepId) => {
      set((state) => {
        const idx = findActiveThinkingPhaseIndex(
          state.streamingPhases,
          stepId,
          node,
        );
        if (idx >= 0) {
          const phase = state.streamingPhases[idx];
          phase.thinkingContent = phase.thinkingContent
            ? phase.thinkingContent + "\n" + content
            : content;
        }
      });
    },

    appendPhaseThinkingDelta: (delta, node, stepId) => {
      set((state) => {
        const idx = findActiveThinkingPhaseIndex(
          state.streamingPhases,
          stepId,
          node,
        );
        if (idx >= 0) {
          state.streamingPhases[idx].thinkingContent += delta;
        }
      });
    },

    closeActivePhase: (durationMs) => {
      set((state) => {
        for (const p of state.streamingPhases) {
          if (p.status === "active") {
            p.status = "completed";
            p.endTime =
              durationMs != null ? p.startTime + durationMs : Date.now();
          }
        }
      });
    },

    appendPhaseStatus: (message, node, stepId) => {
      set((state) => {
        const idx = findActiveThinkingPhaseIndex(
          state.streamingPhases,
          stepId,
          node,
        );
        if (idx >= 0) {
          state.streamingPhases[idx].statusMessages.push(message);
        } else {
          state.streamingPhases.push({
            id: uuidv4(),
            label: message,
            node,
            stepId,
            status: "active",
            startTime: Date.now(),
            thinkingContent: "",
            toolCalls: [],
            statusMessages: [],
          });
        }
      });
    },

    appendPhaseToolCall: (tc, stepId) => {
      set((state) => {
        const idx = findActiveThinkingPhaseIndex(
          state.streamingPhases,
          stepId,
          tc.node,
        );
        if (idx >= 0) {
          upsertToolCallInfoDraft(state.streamingPhases[idx].toolCalls, tc);
        }
      });
    },

    updatePhaseToolCallResult: (id, result) => {
      set((state) => {
        for (const phase of state.streamingPhases) {
          const tc = phase.toolCalls.find((t) => t.id === id);
          if (tc) {
            tc.result = result;
            break;
          }
        }
      });
    },

    closeThinkingBlock: (durationMs) => {
      set((state) => {
        const openBlock = findLastOpenThinkingBlock(state.streamingBlocks);
        if (openBlock) {
          openBlock.endTime =
            durationMs != null && openBlock.startTime
              ? openBlock.startTime + durationMs
              : Date.now();
          openBlock.stepState = "completed";
        }
      });
    },

    appendToolCall: (tc, meta) => {
      set((state) => {
        // Flat field - backward compat. Treat tool_call as idempotent because
        // some provider streams can replay the same native call chunk by id.
        const normalizedToolCall = upsertToolCallInfoDraft(
          state.streamingToolCalls,
          tc,
        );

        // Keep tool call mirrored on current thinking block for backward compat
        let mirroredOnThinkingBlock = false;
        for (const block of state.streamingBlocks) {
          if (block.type !== "thinking") continue;
          const existing = block.toolCalls.find(
            (toolCall) => toolCall.id === normalizedToolCall.id,
          );
          if (existing) {
            mergeToolCallInfoDraft(existing, normalizedToolCall);
            mirroredOnThinkingBlock = true;
          }
        }

        const openBlock = findLastOpenThinkingBlock(
          state.streamingBlocks,
          meta?.stepId,
          normalizedToolCall.node,
        );
        if (openBlock && !mirroredOnThinkingBlock) {
          upsertToolCallInfoDraft(openBlock.toolCalls, normalizedToolCall);
        }

        const existingToolBlock = findToolExecutionBlockDraft(
          state.streamingBlocks,
          normalizedToolCall.id,
        );
        if (existingToolBlock) {
          mergeToolCallInfoDraft(existingToolBlock.tool, normalizedToolCall);
          existingToolBlock.node =
            normalizedToolCall.node || existingToolBlock.node;
          existingToolBlock.status = existingToolBlock.tool.result
            ? "completed"
            : "pending";
          applyDisplayMeta(existingToolBlock, meta);
          return;
        }

        state.streamingBlocks.push(
          applyDisplayMeta(
            {
              type: "tool_execution",
              id: normalizedToolCall.id,
              tool: {
                ...normalizedToolCall,
                args: normalizedToolCall.args
                  ? { ...normalizedToolCall.args }
                  : undefined,
              },
              node: normalizedToolCall.node,
              status: normalizedToolCall.result ? "completed" : "pending",
            } as ToolExecutionBlockData,
            {
              displayRole: "tool",
              presentation: meta?.presentation || "technical",
              ...meta,
            },
          ),
        );
      });
    },

    updateToolCallResult: (id, result, meta) => {
      set((state) => {
        // Flat field - backward compat
        const flatTc = state.streamingToolCalls.find((tc) => tc.id === id);
        if (flatTc) flatTc.result = result;

        // Backward compat: find tool call in thinking blocks and update
        for (const block of state.streamingBlocks) {
          if (block.type === "thinking") {
            const tc = block.toolCalls.find((t) => t.id === id);
            if (tc) {
              tc.result = result;
            }
          }
          if (block.type === "tool_execution" && block.tool.id === id) {
            block.tool.result = result;
            block.status = "completed";
            applyDisplayMeta(block, meta);
          }
        }
      });
    },

    setPendingStreamMetadata: (metadata) => {
      if (!metadata) return;
      const wasStreaming = get().isStreaming;
      const incomingRequestId = getMetadataRequestId(metadata);

      set((state) => {
        if (state.isStreaming) {
          state.pendingStreamMetadata = metadata;
          return;
        }

        if (
          !state.streamCompletedAt ||
          Date.now() - state.streamCompletedAt > 15_000
        ) {
          return;
        }

        const conv = state.conversations.find(
          (c) => c.id === state.activeConversationId,
        );
        const message = conv?.messages[conv.messages.length - 1];
        if (!conv || !message || message.role !== "assistant") return;

        const messageRequestId = getMetadataRequestId(message.metadata);
        if (incomingRequestId) {
          if (!messageRequestId || messageRequestId !== incomingRequestId) {
            return;
          }
        }

        mergeStreamMetadataIntoMessage(message, metadata);

        if (metadata.session_id && !conv.session_id) {
          conv.session_id = metadata.session_id;
        }

        const backendThreadId =
          typeof metadata?.thread_id === "string"
            ? metadata.thread_id
            : undefined;
        if (backendThreadId && !conv.thread_id) {
          conv.thread_id = backendThreadId;
        }
      });

      if (!wasStreaming) {
        persistConversationsImmediate(get().conversations);
      }
    },

    finalizeStream: (metadata) => {
      const {
        isStreaming,
        activeConversationId,
        streamingContent,
        streamingThinking,
        streamingSources,
        streamingToolCalls,
        streamingBlocks,
        streamingDomainNotice,
        streamingPreviews,
        streamingArtifacts,
        streamingLifecycleEvents,
        pendingStreamMetadata,
        visualSessions,
      } = get();

      // Sprint 153b: Guard against double finalization.
      if (!isStreaming || !activeConversationId) return;

      const lifecycleSnapshot = cloneChatLifecycleEvents(
        streamingLifecycleEvents,
      );
      const effectiveMetadata = mergeChatLifecycleMetadata(
        (metadata ?? pendingStreamMetadata ?? undefined) as
          | Record<string, unknown>
          | undefined,
        lifecycleSnapshot,
      ) as ChatResponseMetadata | undefined;
      const suggestedQuestions = extractSuggestedQuestions(effectiveMetadata);

      // Close any remaining open thinking blocks (immutable copy for message)
      const committedVisualSessionIds = Object.values(visualSessions)
        .filter((session) => session.status === "open")
        .map((session) => session.sessionId);

      const closedBlocks: ContentBlock[] = streamingBlocks.map((block) => {
        if (block.type === "thinking" && !block.endTime) {
          return {
            ...block,
            endTime: Date.now(),
            stepState: "completed" as const,
          };
        }
        if (block.type === "visual") {
          const visualBlock = block as VisualBlockData;
          const sessionId =
            visualBlock.sessionId || visualBlock.visual.visual_session_id;
          if (sessionId && committedVisualSessionIds.includes(sessionId)) {
            return { ...visualBlock, status: "committed" as const };
          }
        }
        return block;
      });

      // Sprint 154: Keep full screenshot images (no stripping).
      // Storage cost is minimal and full images look more professional.

      const preferredThinking = pickPreferredFinalThinking(
        streamingThinking,
        effectiveMetadata,
      );
      const reconciledBlocks = reconcileFinalThinkingBlocks(
        closedBlocks,
        preferredThinking,
      );

      const message: Message = {
        id: uuidv4(),
        role: "assistant",
        content: buildDegradedAssistantContent({
          streamingContent,
          streamingBlocks: reconciledBlocks,
          streamingArtifacts,
          streamingPreviews,
        }),
        timestamp: new Date().toISOString(),
        sources: streamingSources.length > 0 ? streamingSources : undefined,
        thinking: preferredThinking || undefined,
        reasoning_trace: effectiveMetadata?.reasoning_trace,
        suggested_questions: suggestedQuestions,
        tool_calls:
          streamingToolCalls.length > 0 ? [...streamingToolCalls] : undefined,
        blocks: reconciledBlocks.length > 0 ? reconciledBlocks : undefined,
        domain_notice: streamingDomainNotice || undefined,
        previews:
          streamingPreviews.length > 0 ? [...streamingPreviews] : undefined,
        artifacts:
          streamingArtifacts.length > 0 ? [...streamingArtifacts] : undefined,
        metadata: effectiveMetadata,
      };

      const backendSessionId = effectiveMetadata?.session_id;
      // Sprint 225: Save thread_id for cross-platform sync
      const backendThreadId =
        typeof effectiveMetadata?.thread_id === "string"
          ? effectiveMetadata.thread_id
          : undefined;

      set((state) => {
        for (const sessionId of committedVisualSessionIds) {
          markVisualSessionStatusDraft(state, sessionId, "committed");
        }
        resetStreamingDraft(state);
        state.streamError = "";
        state.streamCompletedAt = Date.now();
        state.lastCompletedConversationId = activeConversationId;
        state.lastCompletedLifecycleEvents = lifecycleSnapshot;

        const conv = state.conversations.find(
          (c) => c.id === activeConversationId,
        );
        if (conv) {
          conv.messages.push(message);
          conv.updated_at = new Date().toISOString();
          if (backendSessionId && !conv.session_id) {
            conv.session_id = backendSessionId;
          }
          // Sprint 225: Store thread_id for server sync
          if (backendThreadId && !conv.thread_id) {
            conv.thread_id = backendThreadId;
          }
        }
      });

      persistConversationsImmediate(get().conversations);
    },

    setStreamError: (error, metadata) => {
      const { activeConversationId, streamingLifecycleEvents } = get();
      if (!activeConversationId) return;
      const lifecycleSnapshot = cloneChatLifecycleEvents(
        streamingLifecycleEvents,
      );
      const errorMetadata = mergeChatLifecycleMetadata(
        metadata,
        lifecycleSnapshot,
      );

      const message: Message = {
        id: uuidv4(),
        role: "assistant",
        content: `Lỗi: ${error}`,
        timestamp: new Date().toISOString(),
        metadata: errorMetadata,
      };

      set((state) => {
        disposeLiveVisualSessionsDraft(state);
        resetStreamingDraft(state);
        state.streamError = error;
        state.streamCompletedAt = null;
        state.lastCompletedConversationId = null;
        state.lastCompletedLifecycleEvents = lifecycleSnapshot;

        const conv = state.conversations.find(
          (c) => c.id === activeConversationId,
        );
        if (conv) {
          conv.messages.push(message);
          conv.updated_at = new Date().toISOString();
        }
      });

      persistConversationsImmediate(get().conversations);
    },

    setMessageFeedback: (messageId, feedback) => {
      set((state) => {
        for (const conv of state.conversations) {
          const msg = conv.messages.find((m) => m.id === messageId);
          if (msg) {
            msg.feedback = feedback;
            break;
          }
        }
      });
      persistConversations(get().conversations);
    },

    clearStreaming: () => {
      set((state) => {
        disposeLiveVisualSessionsDraft(state);
        resetStreamingDraft(state);
        state.streamError = "";
        state.streamCompletedAt = null;
        state.lastCompletedConversationId = null;
        state.lastCompletedLifecycleEvents = [];
      });
    },

    // Sprint 225: Sync conversation list from server (additive merge)
    syncFromServer: async () => {
      if (_syncInProgress) return;
      _syncInProgress = true;
      try {
        const { shouldUseServerThreadApis } =
          await import("@/stores/chat-store-runtime");
        if (!shouldUseServerThreadApis()) return;

        const { fetchThreads } = await import("@/api/threads");
        const resp = await fetchThreads(200, 0);
        if (!resp.threads || resp.threads.length === 0) return;

        set((state) => {
          // Build lookup of existing local conversations by thread_id
          const byThreadId = new Map<string, Conversation>();
          for (const c of state.conversations) {
            if (c.thread_id) byThreadId.set(c.thread_id, c);
          }

          for (const t of resp.threads) {
            const existing = byThreadId.get(t.thread_id);
            if (existing) {
              // Update metadata from server (server is source of truth for list)
              // Update title unless user explicitly renamed it (user_renamed flag)
              if (t.title && !existing.user_renamed) {
                existing.title = t.title;
              }
              existing.message_count = t.message_count;
            } else {
              // New conversation from another platform — add stub
              // Extract session_id from thread_id format:
              // "user_{uid}__session_{sid}" or "org_{oid}__user_{uid}__session_{sid}"
              let sessionId: string | undefined;
              const sesMatch = t.thread_id.match(/__session_(.+)$/);
              if (sesMatch) sessionId = sesMatch[1];

              const stub: Conversation = {
                id: t.thread_id, // Use thread_id as local id for dedup
                title: t.title || "Cuộc trò chuyện mới",
                domain_id: t.domain_id || undefined,
                created_at: t.created_at || new Date().toISOString(),
                updated_at: t.updated_at || new Date().toISOString(),
                messages: [], // Lazy-loaded on demand
                session_id: sessionId,
                thread_id: t.thread_id,
                message_count: t.message_count,
              };
              state.conversations.push(stub);
            }
          }

          // Sort by updated_at descending
          state.conversations.sort((a, b) =>
            (b.updated_at || "").localeCompare(a.updated_at || ""),
          );
        });

        persistConversations(get().conversations);
      } catch (err) {
        // Graceful degradation — server unreachable, keep local conversations
        console.debug("[chat-store] syncFromServer failed:", err);
      } finally {
        _syncInProgress = false;
      }
    },

    // Sprint 225: Lazy-load messages from server for a conversation with no local messages
    loadServerMessages: async (conversationId: string) => {
      const conv = get().conversations.find((c) => c.id === conversationId);
      if (!conv || conv.messages.length > 0 || !conv.thread_id) return;

      try {
        const { shouldUseServerThreadApis } =
          await import("@/stores/chat-store-runtime");
        if (!shouldUseServerThreadApis()) return;

        const { fetchThreadMessages } = await import("@/api/threads");
        const msgs = await fetchThreadMessages(conv.thread_id, 500);
        if (!msgs || msgs.length === 0) return;

        set((state) => {
          const target = state.conversations.find(
            (c) => c.id === conversationId,
          );
          if (target && target.messages.length === 0) {
            target.messages = msgs.map((m) => ({
              id: m.id,
              role: m.role as "user" | "assistant",
              content: m.content,
              timestamp: m.created_at || new Date().toISOString(),
            }));
          }
        });

        persistConversations(get().conversations);
      } catch (err) {
        console.debug("[chat-store] loadServerMessages failed:", err);
      }
    },

    // Sprint 218: Clear in-memory state on logout (prevent cross-user leakage)
    clearForLogout: () => {
      if (_persistTimer) clearTimeout(_persistTimer);
      _currentUserId = null;
      set((state) => {
        state.conversations = [];
        state.activeConversationId = null;
        state.isLoaded = true;
        state.visualSessions = {};
        resetStreamingDraft(state);
        state.lastCompletedConversationId = null;
        state.lastCompletedLifecycleEvents = [];
      });
    },

    // Sprint 218: Switch user and reload their conversations
    switchUser: async (userId: string | null) => {
      if (_persistTimer) clearTimeout(_persistTimer);
      _currentUserId = userId;
      try {
        const saved = await loadStore<Conversation[]>(
          getStoreName(),
          getStoreKey(),
          [],
        );
        set((state) => {
          state.conversations = saved;
          state.activeConversationId = saved.length > 0 ? saved[0].id : null;
          state.isLoaded = true;
          state.visualSessions = {};
          resetStreamingDraft(state);
          state.lastCompletedConversationId = null;
          state.lastCompletedLifecycleEvents = [];
        });
      } catch (err) {
        console.warn(
          "[chat-store] Failed to load conversations for user:",
          err,
        );
        set((state) => {
          state.conversations = [];
          state.activeConversationId = null;
          state.isLoaded = true;
          state.visualSessions = {};
          resetStreamingDraft(state);
          state.lastCompletedConversationId = null;
          state.lastCompletedLifecycleEvents = [];
        });
      }
    },
  })),
);
