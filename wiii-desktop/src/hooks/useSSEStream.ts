/**
 * SSE streaming hook — connects chat store to SSE parser.
 * Sprint 150: StreamBuffer integration for smooth token rendering.
 */
import { useCallback, useEffect, useRef } from "react";
import { sendMessageStream } from "@/api/chat";
import { ApiHttpError, initClient } from "@/api/client";
import {
  fetchWiiiConnectFacebookPages,
  fetchWiiiConnectProviderConnections,
} from "@/api/wiii-connect";
import {
  submitHostActionAudit,
  submitHostActionResult,
  type HostActionAuditEventType,
  type HostActionAuditRequest,
  type HostActionResultRequest,
} from "@/api/host-actions";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { useContextStore } from "@/stores/context-store";
import { useCharacterStore } from "@/stores/character-store";
import { usePageContextStore } from "@/stores/page-context-store";
import { useHostContextStore, type ActionResult } from "@/stores/host-context-store";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";
import { useToastStore } from "@/stores/toast-store";
import { useModelStore } from "@/stores/model-store";
import { useAuthStore } from "@/stores/auth-store";
import { StreamBuffer } from "@/lib/stream-buffer";
import { stripWiiiInternalMarkup } from "@/lib/internal-markup";
import { normalizeSourceReferences } from "@/lib/source-references";
import {
  POINTY_FAST_PATH_SOURCE,
  buildPointyFastPathAction,
  looksExplicitPointyTurn,
} from "@/lib/pointy-fast-path";
import { pointAt } from "@/pointy-host/api";
import { trackVisualTelemetry } from "@/lib/visual-telemetry";
import { looksDocumentContextFollowupIntent } from "@/lib/document-followup-intent";
import type { SSEEventHandler } from "@/api/sse";
import type {
  AggregationSummary,
  ArtifactType,
  ChatDocumentAttachment,
  ChatDocumentContext,
  ChatResponseMetadata,
  DisplayPresentationMeta,
  ImageInput,
  MoodType,
  PreviewItemData,
  PreviewType,
} from "@/api/types";

const MAX_SSE_RETRIES = 3;
const SSE_BACKOFF_MS = 1000; // 1s, 2s, 4s
// Provider/router cold paths can exceed 30s before the first answer token.
const SSE_IDLE_TIMEOUT_MS = 120_000;
const IDLE_TIMEOUT_ABORT_REASON = "stream_idle_timeout";
const STREAM_RESTART_ABORT_REASON = "stream_restart";
const USER_CANCEL_ABORT_REASON = "user_cancel";
const TRACE_SSE = import.meta.env.DEV;

type HostContextForRequest = NonNullable<
  ReturnType<typeof useHostContextStore.getState>["currentContext"]
>;

// Sprint 147: Track think tool IDs to skip their results
const _thinkToolIds = new Set<string>();

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeIntentText(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/\s+/g, " ")
    .trim();
}

function looksWiiiConnectFacebookContextTurn(text: string): boolean {
  const normalized = normalizeIntentText(text);
  if (!/\b(facebook|fb|meta)\b/.test(normalized)) {
    return false;
  }
  return [
    "ket noi",
    "connect",
    "connected",
    "dang bai",
    "dang len",
    "post",
    "publish",
    "bai viet",
    "facebook",
  ].some((marker) => normalized.includes(marker));
}

async function buildWiiiConnectFacebookContextSnapshot(
  text: string,
): Promise<Record<string, unknown> | null> {
  if (!looksWiiiConnectFacebookContextTurn(text)) {
    return null;
  }

  try {
    const connections = await fetchWiiiConnectProviderConnections("facebook", {
      probeDatabase: true,
    });
    const connectionItems = connections.connections || [];
    const activeConnections = connectionItems.filter(
      (item) => item.active || item.state === "connected",
    );
    const firstConnection = activeConnections[0] || connectionItems[0];
    const connectionRef =
      firstConnection?.connection_ref || firstConnection?.connection_id || "";
    const snapshot: Record<string, unknown> = {
      provider_slug: "facebook",
      provider_label: "Facebook",
      status: activeConnections.length > 0 ? "connected" : "not_connected",
      connection_count: connectionItems.length,
      active_connection_count: activeConnections.length,
    };
    if (firstConnection) {
      snapshot.connection_ref_present = Boolean(connectionRef);
      snapshot.connection_state = firstConnection.state || "";
      snapshot.connection_active = Boolean(firstConnection.active);
      snapshot.blocked_reason = firstConnection.reason || firstConnection.state || "";
    }

    if (connectionRef && activeConnections.length > 0) {
      const pages = await fetchWiiiConnectFacebookPages("facebook", connectionRef);
      snapshot.page_status = pages.status;
      snapshot.blocked_reason = pages.status === "ready" ? "" : pages.reason || "";
      snapshot.page_count = pages.page_count;
      snapshot.page_names = (pages.pages || [])
        .map((page) => page.name)
        .filter((name) => Boolean(name))
        .slice(0, 5);
      if (pages.status === "ready" && pages.page_count > 0) {
        snapshot.available_actions = [
          "wiii_connect.facebook_post.direct_apply",
          "wiii_connect.facebook_post.preview",
          "wiii_connect.facebook_post.apply",
        ];
      }
    }

    return snapshot;
  } catch (error) {
    console.warn(
      "[SSE] Wiii Connect Facebook context snapshot failed:",
      error instanceof Error ? error.message : String(error),
    );
    return {
      provider_slug: "facebook",
      provider_label: "Facebook",
      status: "unavailable",
    };
  }
}

function withWiiiConnectSnapshot(
  context: HostContextForRequest | null,
  snapshot: Record<string, unknown> | null,
): HostContextForRequest | null {
  if (!snapshot) {
    return context;
  }
  if (!context) {
    const hostname =
      typeof window !== "undefined" ? window.location.hostname : "localhost";
    const isEmbedded =
      typeof window !== "undefined" ? window.parent !== window : false;
    return {
      host_type: "wiii-desktop",
      host_name: "Wiii Desktop",
      resource_uri: "wiii://chat/current",
      page: {
        type: "chat",
        title: "Wiii Chat",
        url: typeof window !== "undefined" ? window.location.href : undefined,
        metadata: {
          hostname,
          is_embedded: isEmbedded,
          wiii_connect: snapshot,
        },
      },
      workflow_stage: "conversation",
    };
  }
  return {
    ...context,
    page: {
      ...context.page,
      metadata: {
        ...(context.page.metadata || {}),
        wiii_connect: snapshot,
      },
    },
  };
}

async function waitForPointyLayoutCommit(): Promise<void> {
  if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
    await sleep(0);
    return;
  }
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

function createStreamRequestId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return `chat-stream-${randomUuid}`;
  }
  return `chat-stream-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Sprint 165: Map error types to Wiii-character Vietnamese messages. */
function _getVietnameseErrorMessage(err: unknown): string {
  if (err instanceof ApiHttpError) {
    const rawMessage = err.body?.message;
    if (typeof rawMessage === "string" && rawMessage.trim()) {
      return rawMessage.trim();
    }
  }
  if (err instanceof TypeError && err.message.includes("fetch")) {
    return "Ôi, Wiii mất kết nối với máy chủ rồi. Bạn kiểm tra mạng giúp mình nhé!";
  }
  if (err instanceof DOMException && err.name === "TimeoutError") {
    return "Wiii suy nghĩ hơi lâu quá... Bạn thử hỏi lại mình nhé!";
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return "Đã hủy yêu cầu rồi nha.";
  }
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.includes("500") || msg.includes("Internal")) {
    return "Wiii bị trục trặc bên trong rồi. Mình đang cố khắc phục...";
  }
  if (msg.includes("429") || msg.includes("rate")) {
    return "Bạn ơi, hỏi nhanh quá, Wiii chưa kịp thở. Đợi mình một chút nhé!";
  }
  return "Wiii bị mất kết nối rồi. Bạn thử lại giúp mình nhé!";
}

function _extractStructuredErrorMetadata(err: unknown): Record<string, unknown> | undefined {
  if (err instanceof ApiHttpError && err.body) {
    return err.body;
  }
  return undefined;
}

/**
 * Sprint 164: Extract agent names from parallel dispatch status content.
 * Examples: "Triển khai song song: rag, tutor" → ["rag", "tutor"]
 *           "Dispatching: rag_agent, tutor_agent" → ["rag_agent", "tutor_agent"]
 */
export function _parseParallelTargets(content: string): string[] {
  if (!content) return [];
  // Try colon-separated format: "Label: agent1, agent2"
  const colonIdx = content.indexOf(":");
  const segment = colonIdx >= 0 ? content.slice(colonIdx + 1) : content;
  const names = segment
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && /^[a-z_]+$/i.test(s));
  return names;
}

function _normalizePromptIntent(text: string): string {
  return (text || "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

function _inferCodeStudioRequestedView(prompt: string): "code" | "preview" | undefined {
  const normalized = _normalizePromptIntent(prompt);
  if (!normalized) return undefined;
  if (
    /(^|[\s,])((xem|hien|mo|show|view)\s+code|(xem|hien)\s+ma)\b/.test(normalized)
    || normalized.includes("source code")
  ) {
    return "code";
  }
  if (
    /(^|[\s,])((xem|mo|show|view)\s+(preview|ban xem truoc)|xem demo)\b/.test(normalized)
  ) {
    return "preview";
  }
  return undefined;
}

function _normalizeCompatibilityRole(
  value: unknown,
): "student" | "teacher" | "admin" | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "teacher") return "teacher";
  if (normalized === "student") return "student";
  if (normalized === "admin") return "admin";
  if (normalized === "org_admin" || normalized === "owner") return "teacher";
  return null;
}

export function _resolveCompatibilityRole(
  authMode: "oauth" | "legacy",
  settingsRole: string,
  hostRole?: unknown,
  pageRole?: unknown,
): "student" | "teacher" | "admin" {
  const hostOverlayRole =
    _normalizeCompatibilityRole(hostRole) || _normalizeCompatibilityRole(pageRole);
  if (hostOverlayRole) {
    return hostOverlayRole;
  }
  if (authMode === "legacy") {
    return _normalizeCompatibilityRole(settingsRole) || "student";
  }
  return "student";
}

export function _resolveRequestUserId(
  authMode: "oauth" | "legacy",
  settingsUserId: string,
  authUserId?: string | null,
): string {
  if (authMode === "oauth" && authUserId && authUserId.trim()) {
    return authUserId.trim();
  }
  return settingsUserId;
}

export function _resolveRequestDisplayName(
  authMode: "oauth" | "legacy",
  settingsDisplayName: string,
  settingsUserId: string,
  authName?: string | null,
  authEmail?: string | null,
): string {
  if (authMode === "oauth") {
    const authLabel = authName?.trim() || authEmail?.trim();
    if (authLabel) {
      return authLabel;
    }
  }
  return settingsDisplayName || settingsUserId;
}

function toDisplayMeta(
  data: Partial<{
    display_role: DisplayPresentationMeta["displayRole"];
    sequence_id: number;
    step_id: string;
    step_state: DisplayPresentationMeta["stepState"];
    presentation: DisplayPresentationMeta["presentation"];
  }>,
): DisplayPresentationMeta {
  return {
    displayRole: data.display_role,
    sequenceId: data.sequence_id,
    stepId: data.step_id,
    stepState: data.step_state,
    presentation: data.presentation,
  };
}

function mapHostActionAuditEvent(action: string): HostActionAuditEventType | null {
  switch (action) {
    case "authoring.preview_lesson_patch":
    case "assessment.preview_quiz_commit":
    case "publish.preview_quiz":
      return "preview_created";
    case "authoring.apply_lesson_patch":
    case "assessment.apply_quiz_commit":
      return "apply_confirmed";
    case "publish.apply_quiz":
      return "publish_confirmed";
    default:
      return null;
  }
}

export function buildHostActionPreviewItem(
  action: string,
  requestId: string,
  params: Record<string, unknown>,
  data: Record<string, unknown>,
  hostContext: ReturnType<typeof useHostContextStore.getState>["currentContext"],
): PreviewItemData | null {
  const previewKind = typeof data.preview_kind === "string" ? data.preview_kind : "";
  const previewToken =
    typeof data.preview_token === "string" && data.preview_token.trim()
      ? data.preview_token.trim()
      : previewKind === "facebook_post" && typeof data.preview_evidence_id === "string"
        ? data.preview_evidence_id.trim()
        : "";
  if (!previewToken) return null;
  const approvalToken =
    typeof data.approval_token === "string" ? data.approval_token.trim() : "";

  const summary = typeof data.summary === "string" ? data.summary.trim() : "Preview is ready.";
  const sourceReferences = normalizeSourceReferences(
    data.source_references ?? data.sourceReferences,
  );
  const changedFields = Array.isArray(data.changed_fields)
    ? data.changed_fields.filter((field): field is string => typeof field === "string" && field.trim().length > 0)
    : [];
  const questionCount =
    typeof data.question_count === "number"
      ? data.question_count
      : Array.isArray(params.question_ids)
        ? params.question_ids.length
        : Array.isArray(params.questionIds)
          ? params.questionIds.length
          : undefined;

  const targetLabel =
    (typeof data.lesson_title === "string" && data.lesson_title.trim())
    || (typeof data.quiz_title === "string" && data.quiz_title.trim())
    || (typeof data.page_label === "string" && data.page_label.trim())
    || (typeof params.title === "string" && params.title.trim())
    || (typeof data.lesson_id === "string" && data.lesson_id.trim())
    || (typeof data.quiz_id === "string" && data.quiz_id.trim())
    || (typeof data.page_id === "string" && data.page_id.trim())
    || "Host preview";

  const title =
    previewKind === "lesson_patch"
      ? `Xem trước cập nhật bài học: ${targetLabel}`
      : previewKind === "quiz_commit"
        ? `Xem trước bài kiểm tra: ${targetLabel}`
        : previewKind === "quiz_publish"
          ? `Xem trước phát hành bài kiểm tra: ${targetLabel}`
          : `Xem trước thao tác LMS: ${targetLabel}`;
  const displayTitle =
    previewKind === "facebook_post"
      ? `Xem trước bài đăng Facebook: ${targetLabel}`
      : title;

  return {
    preview_id: `host-action-${requestId}`,
    preview_type: "host_action",
    title: displayTitle,
    snippet: summary,
    metadata: {
      action,
      request_id: requestId,
      summary,
      preview_kind: previewKind || undefined,
      preview_token: previewToken,
      preview_evidence_id:
        typeof data.preview_evidence_id === "string" ? data.preview_evidence_id : undefined,
      approval_token: approvalToken || undefined,
      apply_action: typeof data.apply_action === "string" ? data.apply_action : undefined,
      target_label: targetLabel,
      page_id: typeof data.page_id === "string" ? data.page_id : undefined,
      page_label: typeof data.page_label === "string" ? data.page_label : undefined,
      message: typeof data.message === "string" ? data.message : undefined,
      image_present:
        typeof data.image_present === "boolean" ? data.image_present : undefined,
      facebook_post_body:
        data.facebook_post_body && typeof data.facebook_post_body === "object"
          ? data.facebook_post_body
          : undefined,
      lesson_id: typeof data.lesson_id === "string" ? data.lesson_id : undefined,
      lesson_title: typeof data.lesson_title === "string" ? data.lesson_title : undefined,
      quiz_id: typeof data.quiz_id === "string" ? data.quiz_id : undefined,
      quiz_title: typeof data.quiz_title === "string" ? data.quiz_title : undefined,
      course_id: typeof data.course_id === "string" ? data.course_id : undefined,
      changed_fields: changedFields.length > 0 ? changedFields : undefined,
      changed_count: changedFields.length > 0 ? changedFields.length : undefined,
      question_count: questionCount,
      lesson_before:
        data.lesson_before && typeof data.lesson_before === "object"
          ? data.lesson_before
          : undefined,
      lesson_after:
        data.lesson_after && typeof data.lesson_after === "object"
          ? data.lesson_after
          : undefined,
      block_diff:
        data.block_diff && typeof data.block_diff === "object"
          ? data.block_diff
          : undefined,
      quiz_plan:
        data.quiz_plan && typeof data.quiz_plan === "object"
          ? data.quiz_plan
          : undefined,
      publish_plan:
        data.publish_plan && typeof data.publish_plan === "object"
          ? data.publish_plan
          : undefined,
      source_references:
        sourceReferences.length > 0 ? sourceReferences : undefined,
      requires_confirmation: true,
      workflow_stage: hostContext?.workflow_stage,
      page_type: hostContext?.page?.type,
      next_step: "Xem bản xem trước rồi xác nhận rõ ràng nếu bạn muốn Wiii áp dụng thay đổi này vào LMS.",
    },
  };
}

function buildHostActionAuditRequest(
  action: string,
  requestId: string,
  result: { success: boolean; data?: Record<string, unknown>; error?: string },
  hostContext: ReturnType<typeof useHostContextStore.getState>["currentContext"],
  hostCapabilities: ReturnType<typeof useHostContextStore.getState>["capabilities"],
): HostActionAuditRequest | null {
  if (!result.success) return null;
  const eventType = mapHostActionAuditEvent(action);
  if (!eventType) return null;

  const data = result.data || {};
  const sourceReferences = normalizeSourceReferences(
    data.source_references ?? data.sourceReferences,
  );
  return {
    event_type: eventType,
    action,
    request_id: requestId,
    summary: typeof data.summary === "string" ? data.summary : undefined,
    host_type: hostContext?.host_type,
    host_name: hostCapabilities?.host_name || hostContext?.host_name,
    page_type: hostContext?.page?.type,
    page_title: hostContext?.page?.title,
    user_role: hostContext?.user_role,
    workflow_stage: hostContext?.workflow_stage,
    preview_kind: typeof data.preview_kind === "string" ? data.preview_kind : undefined,
    preview_token: typeof data.preview_token === "string" ? data.preview_token : undefined,
    target_type:
      typeof data.lesson_id === "string"
        ? "lesson"
        : typeof data.quiz_id === "string"
          ? "quiz"
          : undefined,
    target_id:
      typeof data.lesson_id === "string"
        ? data.lesson_id
        : typeof data.quiz_id === "string"
          ? data.quiz_id
          : undefined,
    surface:
      eventType === "preview_created"
        ? "preview_panel"
        : "editor_shell",
    metadata: {
      request_id: requestId,
      course_id: typeof data.course_id === "string" ? data.course_id : undefined,
      lesson_id: typeof data.lesson_id === "string" ? data.lesson_id : undefined,
      lesson_title: typeof data.lesson_title === "string" ? data.lesson_title : undefined,
      quiz_id: typeof data.quiz_id === "string" ? data.quiz_id : undefined,
      quiz_title: typeof data.quiz_title === "string" ? data.quiz_title : undefined,
      changed_fields: Array.isArray(data.changed_fields) ? data.changed_fields : undefined,
      question_count:
        typeof data.question_count === "number" ? data.question_count : undefined,
      lesson_before:
        data.lesson_before && typeof data.lesson_before === "object"
          ? data.lesson_before
          : undefined,
      lesson_after:
        data.lesson_after && typeof data.lesson_after === "object"
          ? data.lesson_after
          : undefined,
      block_diff:
        data.block_diff && typeof data.block_diff === "object"
          ? data.block_diff
          : undefined,
      quiz_plan:
        data.quiz_plan && typeof data.quiz_plan === "object"
          ? data.quiz_plan
          : undefined,
      publish_plan:
        data.publish_plan && typeof data.publish_plan === "object"
          ? data.publish_plan
          : undefined,
      source_references:
        sourceReferences.length > 0 ? sourceReferences : undefined,
    },
  };
}

const HOST_ACTION_RESULT_REDACT_KEYS = new Set([
  "access_token",
  "refresh_token",
  "client_secret",
  "api_key",
  "authorization",
  "approval_token",
  "image_base64",
]);

function sanitizeHostActionResultValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeHostActionResultValue(item));
  }
  if (value && typeof value === "object") {
    const sanitized: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      sanitized[key] = HOST_ACTION_RESULT_REDACT_KEYS.has(key.toLowerCase())
        ? "[redacted]"
        : sanitizeHostActionResultValue(item);
    }
    return sanitized;
  }
  return value;
}

export function buildHostActionResultRequest(
  action: string,
  requestId: string,
  result: ActionResult,
): HostActionResultRequest {
  const rawData = result.data || {};
  const data = sanitizeHostActionResultValue(rawData) as Record<string, unknown>;
  const dataSummary = typeof data.summary === "string" ? data.summary.trim() : "";
  return {
    action,
    request_id: requestId,
    success: result.success,
    summary: dataSummary || (result.success ? "Host action completed." : result.error),
    error: result.error,
    data,
  };
}

export function useSSEStream() {
  const abortRef = useRef<AbortController | null>(null);
  // Sprint 150: Token smoothing buffers
  const answerBufferRef = useRef<StreamBuffer | null>(null);
  // v4.0 F7 (2026-05-06) — Clicky-pattern inline `[POINT:...]` tag.
  // Shadow accumulator captures FULL unstripped answer text (with tag
  // intact) so onDone can parse + dispatch cursor without round-tripping
  // through the broken tool_call → SSE pointy_action pipeline.
  const fullAnswerTextRef = useRef<string>("");
  // v6.0 F11 (2026-05-06) — streaming dispatch state. "Vừa nói vừa làm":
  // cursor flies WHILE AI is still streaming text, not after onDone.
  // Tag regex matches as soon as `]` arrives in stream; embodied parser
  // fires on sentence boundary. Idempotent via dispatchedThisStreamRef.
  const dispatchedThisStreamRef = useRef<boolean>(false);
  const allowEmbodiedDispatchRef = useRef<boolean>(false);
  type PointyTargetMin = { id: string; label?: string; role?: string };
  type PointyModules = {
    parsePointTag: (t: string) => {
      tag: { selector: string; caption: string } | null;
      stripped: string;
    };
    parseAllPointTags: (t: string) => {
      tags: { selector: string; caption: string }[];
      stripped: string;
    };
    detectEmbodiedPoint: (
      text: string,
      targets: PointyTargetMin[],
    ) => { target: PointyTargetMin; score: number; sentence: string } | null;
    detectAllEmbodiedPoints: (
      text: string,
      targets: PointyTargetMin[],
      options?: { threshold?: number; maxMatches?: number },
    ) => { target: PointyTargetMin; score: number; sentence: string }[];
    enqueuePoints: (
      points: { selector: string; caption?: string; durationMs: number }[],
    ) => number;
    enqueueTagPoints: (
      points: { selector: string; caption?: string; durationMs: number }[],
    ) => number;
    enqueueEmbodiedPoints: (
      points: { selector: string; caption?: string; durationMs: number }[],
    ) => number;
    clearDispatchQueue: () => void;
    getTargets: () => PointyTargetMin[];
  };
  const pointyModulesRef = useRef<PointyModules | null>(null);
  // v7.0 F12 — last accumulated text we ran parser on. Streaming dispatch
  // uses this to compute the DELTA (new content since last parse) so we
  // don't re-dispatch tags/sentences already processed.
  const lastParsedLenRef = useRef<number>(0);

  // v6.0 F11 — preload pointy modules ONCE so per-chunk dispatch is
  // synchronous (no async import overhead per stream chunk).
  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      import("@/pointy-host/inline-tag-parser"),
      import("@/pointy-host/embodied-parser"),
      import("@/pointy-host/dispatch-queue"),
      import("@/pointy-host/integration"),
    ]).then(([tagMod, embodiedMod, queueMod, integrationMod]) => {
      if (cancelled) return;
      pointyModulesRef.current = {
        parsePointTag: tagMod.parsePointTag,
        parseAllPointTags: tagMod.parseAllPointTags,
        detectEmbodiedPoint: embodiedMod.detectEmbodiedPoint,
        detectAllEmbodiedPoints: embodiedMod.detectAllEmbodiedPoints,
        enqueuePoints: queueMod.enqueuePoints,
        enqueueTagPoints: queueMod.enqueueTagPoints,
        enqueueEmbodiedPoints: queueMod.enqueueEmbodiedPoints,
        clearDispatchQueue: queueMod.clearDispatchQueue,
        getTargets: () => {
          integrationMod.refreshPointyContext();
          const scanner = integrationMod.getPointyScanner();
          let targets: PointyTargetMin[] = [];
          if (scanner) {
            targets = scanner.getTargets().map((t) => ({
              id: t.id,
              label: t.label,
              role: t.role,
            }));
          }
          if (targets.length === 0 && typeof document !== "undefined") {
            const els = document.querySelectorAll<HTMLElement>(
              "[data-wiii-id]",
            );
            targets = Array.from(els)
              .map((el) => ({
                id: el.getAttribute("data-wiii-id") || "",
                label:
                  el.getAttribute("aria-label") ||
                  el.textContent?.trim().slice(0, 40) ||
                  "",
                role: el.tagName.toLowerCase(),
              }))
              .filter((t) => t.id);
          }
          return targets;
        },
      };
    }).catch((err) => {
      console.warn("[POINTY-STREAM] module preload failed:", err);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * v7.0 F12 (2026-05-06) — multi-target streaming dispatch via queue.
   *
   * "Vừa nói vừa làm" with sequence support: a single AI response can
   * point at multiple elements ("Đầu tiên click X, rồi Y, cuối cùng Z").
   * Each match is enqueued; cursor visits them in sequence with a hold
   * duration. Dispatch queue dedupes by (selector + caption) signature.
   *
   * Two paths feeding the queue:
   *   1. Tag — `parseAllPointTags` extracts every `[POINT:...]` in the
   *      response. Runs every chunk; queue handles dedupe.
   *   2. Embodied — only on sentence boundary, run `detectAllEmbodiedPoints`
   *      to find all matches in order. Queue dedupes targets so we don't
   *      bounce back to same element.
   *
   * Idempotency lives in the queue (signature dedup), NOT in a boolean
   * flag — that's what enables multi-dispatch per stream.
   */
  const tryStreamingDispatch = useCallback((accumulated: string): void => {
    if (dispatchedThisStreamRef.current) return;
    const mods = pointyModulesRef.current;
    if (!mods) return;
    const cleaned = stripWiiiInternalMarkup(accumulated);
    if (!cleaned.trim()) return;

    // Path 1 — explicit `[POINT:...]` tag (deterministic). Uses TAG-priority
    // enqueue: cancels any in-flight embodied dispatch + flips flag so
    // subsequent embodied calls in this stream are skipped. AI explicitly
    // chose this id → trust it over heuristic guess.
    const { tags } = mods.parseAllPointTags(cleaned);
    if (tags.length > 0) {
      const queued = mods.enqueueTagPoints(
        tags.map((t) => ({
          selector: t.selector,
          caption: t.caption || undefined,
          durationMs: 2400,
        })),
      );
      if (queued > 0) {
        console.warn(
          `[POINTY-STREAM] tag-queue queued=${queued} total_tags=${tags.length} (tag-priority — embodied skipped)`,
        );
      }
    }

    // Path 2 — embodied parser, only on sentence boundary AND only if no
    // tag fired yet. enqueueEmbodiedPoints internally checks tag-fired
    // flag and returns 0 if true.
    if (!allowEmbodiedDispatchRef.current) return;

    const lastChar = cleaned.trimEnd().slice(-1);
    if ([".", "!", "?", "\n", "~"].includes(lastChar)) {
      const targets = mods.getTargets();
      if (targets.length > 0) {
        const matches = mods.detectAllEmbodiedPoints(cleaned, targets, {
          threshold: 0.6,
          maxMatches: 5,
        });
        if (matches.length > 0) {
          const queued = mods.enqueueEmbodiedPoints(
            matches.map((m) => ({
              selector: m.target.id,
              caption: m.target.label || undefined,
              durationMs: 2400,
            })),
          );
          if (queued > 0) {
            console.warn(
              `[POINTY-STREAM] embodied-queue queued=${queued} matches=${matches.length} top="${matches[0].target.id}@${matches[0].score.toFixed(2)}"`,
            );
          }
        }
      }
    }
  }, []);
  const thinkingBufferRef = useRef<StreamBuffer | null>(null);
  // Track current thinking node for buffer flush callback
  const thinkingNodeRef = useRef<string | undefined>(undefined);
  const thinkingMetaRef = useRef<DisplayPresentationMeta | undefined>(undefined);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventOrderRef = useRef<string[]>([]);
  // Track whether code_open was emitted this turn — used to suppress
  // duplicate ToolExecutionStrip for tool_create_visual_code.
  const codeOpenActiveRef = useRef(false);
  const recentDocumentContextRef = useRef<ChatDocumentContext | undefined>(undefined);
  const recentDocumentContextConversationRef = useRef<string | undefined>(undefined);

  const clearIdleGuard = useCallback(() => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  }, []);

  const hasStreamingOutput = useCallback(() => {
    const state = useChatStore.getState();
    return Boolean(
      state.streamingContent.trim()
      || state.streamingThinking.trim()
      || state.streamingBlocks.length > 0
      || state.streamingSources.length > 0
      || state.streamingToolCalls.length > 0
      || state.streamingPreviews.length > 0
      || state.streamingArtifacts.length > 0
      || state.streamingDomainNotice.trim()
    );
  }, []);

  const finalizeFromTransport = useCallback((
    reason: "done" | "eof" | "idle_timeout",
    metadata?: ChatResponseMetadata,
  ) => {
    clearIdleGuard();
    answerBufferRef.current?.drain();
    thinkingBufferRef.current?.drain();

    const store = useChatStore.getState();
    if (!store.isStreaming) return;

    const effectiveMetadata = metadata
      ? ({
          ...(store.pendingStreamMetadata || {}),
          ...metadata,
        } as ChatResponseMetadata)
      : undefined;

    if (effectiveMetadata) {
      store.setPendingStreamMetadata(effectiveMetadata);
    }

    if (hasStreamingOutput()) {
      if (TRACE_SSE) {
        console.debug("[SSE] finalize", { reason, eventOrder: [...eventOrderRef.current] });
      }
      store.finalizeStream(effectiveMetadata);
      void useModelStore.getState().fetchProviders({ force: true });
      return;
    }

    // Phase 35 — stream-resume protocol.
    // When stream ends with NO answer received (eof/idle_timeout), the backend
    // may have produced + persisted the answer via the always-run finalize
    // hook (chat_stream_coordinator try/finally). Fetch the latest assistant
    // message from the durable thread log and surface it instead of showing
    // a generic "luồng đã ngắt" error.
    if (reason !== "done") {
      const activeConv = store.activeConversation();
      const threadId = activeConv?.thread_id;
      if (threadId) {
        if (TRACE_SSE) {
          console.debug("[SSE] stream-resume: fetching latest from", threadId);
        }
        void (async () => {
          try {
            const { fetchThreadMessages } = await import("@/api/threads");
            const msgs = await fetchThreadMessages(threadId, 5);
            const lastAssistant = msgs
              ?.slice()
              .reverse()
              .find((m) => m?.role === "assistant");
            const recoveredText = (lastAssistant && typeof lastAssistant === "object"
              && "content" in lastAssistant
              && typeof (lastAssistant as { content?: unknown }).content === "string")
              ? (lastAssistant as { content: string }).content.trim()
              : "";
            if (recoveredText) {
              if (TRACE_SSE) {
                console.debug("[SSE] stream-resume: recovered", recoveredText.length, "chars");
              }
              useChatStore.getState().appendStreamingContent(recoveredText);
              useChatStore.getState().finalizeStream();
              return;
            }
          } catch (err) {
            console.debug("[SSE] stream-resume failed:", err);
          }
          // Recovery fetch failed → fall back to original error message.
          const fallbackMessage =
            reason === "idle_timeout"
              ? "Luồng phản hồi đã im lặng quá lâu trước khi chốt câu trả lời cuối."
              : "Luồng phản hồi kết thúc sớm trước khi Wiii kịp chốt câu trả lời cuối.";
          useChatStore.getState().setStreamError(fallbackMessage);
        })();
        void useModelStore.getState().fetchProviders({ force: true });
        return;
      }
    }

    const fallbackMessage =
      reason === "idle_timeout"
        ? "Luồng phản hồi đã im lặng quá lâu trước khi chốt câu trả lời cuối."
        : "Luồng phản hồi kết thúc sớm trước khi Wiii kịp chốt câu trả lời cuối.";
    store.setStreamError(fallbackMessage);
    void useModelStore.getState().fetchProviders({ force: true });
  }, [clearIdleGuard, hasStreamingOutput]);

  const scheduleIdleGuard = useCallback(() => {
    clearIdleGuard();
    if (!abortRef.current) return;

    idleTimerRef.current = setTimeout(() => {
      if (!abortRef.current || abortRef.current.signal.aborted) return;
      if (!useChatStore.getState().isStreaming) return;

      if (TRACE_SSE) {
        console.debug("[SSE] idle-timeout", { eventOrder: [...eventOrderRef.current] });
      }

      abortRef.current.abort(IDLE_TIMEOUT_ABORT_REASON);
      finalizeFromTransport("idle_timeout");
    }, SSE_IDLE_TIMEOUT_MS);
  }, [clearIdleGuard, finalizeFromTransport]);

  const traceEvent = useCallback((eventType: string, payload?: unknown) => {
    eventOrderRef.current.push(eventType);
    if (TRACE_SSE) {
      console.debug("[SSE]", eventType, payload);
    }
    scheduleIdleGuard();
  }, [scheduleIdleGuard]);

  const sendMessage = useCallback(async (
    content: string,
    images?: ImageInput[],
    forceSkills?: string[],
    documents?: ChatDocumentAttachment[],
    documentContext?: ChatDocumentContext,
  ) => {
    const settings = useSettingsStore.getState().settings;
    const authHeaders = useSettingsStore.getState().getAuthHeaders();
    const domainId = useDomainStore.getState().activeDomainId;
    const chatStore = useChatStore.getState();

    // Sprint 153b: Concurrent stream guard — abort previous stream before starting new one
    if (abortRef.current) {
      abortRef.current.abort(STREAM_RESTART_ABORT_REASON);
      answerBufferRef.current?.discard();
      thinkingBufferRef.current?.discard();
      clearIdleGuard();
    }

    // Ensure we have an active conversation
    let conversationId = chatStore.activeConversationId;
    if (!conversationId) {
      // Sprint 220c: Pass embed session_id for session resumption
      const embedSessionId = (window as any).__WIII_EMBED_CONFIG__?.session_id;
      conversationId = chatStore.createConversation(domainId, undefined, embedSessionId);
    }
    const effectiveDocumentContext =
      documentContext
      || (
        looksDocumentContextFollowupIntent(content)
        && recentDocumentContextConversationRef.current === conversationId
          ? recentDocumentContextRef.current
          : undefined
      );
    if (documentContext?.attachments?.length) {
      recentDocumentContextRef.current = documentContext;
      recentDocumentContextConversationRef.current = conversationId;
    }

    // Add user message (Sprint 179 images + per-turn document chips)
    chatStore.addUserMessage(content, images, documents);
    useHostContextStore.getState().setLocalActionImages(images);

    // Initialize the HTTP client with current settings
    initClient(settings.server_url, authHeaders);
    const wiiiConnectContextSnapshot =
      await buildWiiiConnectFacebookContextSnapshot(content);

      // Start streaming
      chatStore.startStreaming();
      chatStore.setStreamingStep("Wiii đang nghe bạn...");
      useCharacterStore.getState().clearSoulEmotion();

      // Sprint 153b: Clear stale think/progress tool IDs from previous streams
      _thinkToolIds.clear();
    eventOrderRef.current = [];
    thinkingMetaRef.current = undefined;
    codeOpenActiveRef.current = false;

    const canUseHostActionBridge =
      typeof window !== "undefined" && window.parent !== window;
    const explicitPointyTurn = settings.pointy_mode === true
      && looksExplicitPointyTurn(content, forceSkills);
    let pointyFastPathAction: ReturnType<typeof buildPointyFastPathAction> = null;
    if (explicitPointyTurn) {
      await waitForPointyLayoutCommit();
      try {
        const { refreshPointyContext } = await import("@/pointy-host/integration");
        refreshPointyContext();
      } catch (err) {
        console.warn(
          "[SSE] pointy context refresh skipped:",
          err instanceof Error ? err.message : String(err),
        );
      }
      pointyFastPathAction = buildPointyFastPathAction(
        content,
        useHostContextStore.getState().currentContext,
      );
    }
    const allowPointyEmbodiedDispatch = explicitPointyTurn;
    const hostContextState = useHostContextStore.getState();
    const supportsCursorMove =
      hostContextState.capabilities?.tools?.some(
        (tool) => tool.name === "ui.cursor_move",
      ) === true;
    const pointyFastPathPromise = pointyFastPathAction
      ? (async () => {
          if (canUseHostActionBridge && supportsCursorMove) {
            chatStore.setStreamingStep("Wiii đang nhìn vị trí trên trang...");
            await Promise.race([
              hostContextState.requestAction(
                "ui.cursor_move",
                {
                  selector: pointyFastPathAction.target.id,
                  label: "Wiii",
                  duration_ms: 280,
                  source: POINTY_FAST_PATH_SOURCE,
                },
                `${pointyFastPathAction.requestId}-cursor`,
              ),
              sleep(220),
            ]).catch((err) => {
              console.warn(
                "[SSE] pointy cursor pre-move failed:",
                err instanceof Error ? err.message : String(err),
              );
              return null;
            });
          }

          if (canUseHostActionBridge) {
            return hostContextState.requestAction(
              pointyFastPathAction.action,
              pointyFastPathAction.params,
              pointyFastPathAction.requestId,
            );
          }

          if (pointyFastPathAction.action === "ui.highlight") {
            const ok = pointAt(pointyFastPathAction.target.id, {
              caption: pointyFastPathAction.params.message,
              duration_ms: pointyFastPathAction.params.duration_ms,
            });
            return {
              success: ok,
              data: ok ? { summary: pointyFastPathAction.params.message } : undefined,
              error: ok ? undefined : "Pointy target did not resolve in standalone desktop.",
            };
          }

          return {
            success: false,
            error: "Host bridge unavailable for mutating Pointy action.",
          };
        })()
          .then((result) => {
            if (TRACE_SSE) {
              console.debug("[SSE] pointy-fast-path resolved", {
                action: pointyFastPathAction.action,
                target: pointyFastPathAction.target.id,
                success: result.success,
              });
            }
            if (result.success) {
              eventOrderRef.current.push("pointy_fast_path");
              chatStore.setStreamingStep("Wiii đang trỏ trên trang...");
              chatStore.addStreamingStep("Wiii đang trỏ trên trang...", "pointy_fast_path");
            }
            return result;
          })
          .catch((err) => {
            console.warn(
              "[SSE] pointy-fast-path failed:",
              err instanceof Error ? err.message : String(err),
            );
            return null;
          })
      : null;

    // Keep a per-send controller so an aborted previous request cannot
    // accidentally clear/finalize the newly-started stream.
    const streamController = new AbortController();
    abortRef.current = streamController;
    const clearIdleGuardIfCurrent = () => {
      if (abortRef.current === streamController) {
        clearIdleGuard();
      }
    };
    scheduleIdleGuard();

    if (pointyFastPathPromise) {
      await Promise.race([pointyFastPathPromise, sleep(350)]);
    }

    // Sprint 150: Create fresh StreamBuffer instances for this stream
    answerBufferRef.current = new StreamBuffer({
      onFlush: (chars) => useChatStore.getState().appendStreamingContent(chars),
      initialHoldMs: 80,
      minCharsPerFrame: 3,
      maxCharsPerFrame: 28,
      targetBufferDepth: 40,
      easeInFrames: 15,
    });
    // v7.0 F12 — reset streaming dispatch state + queue for new stream.
    fullAnswerTextRef.current = "";
    // If deterministic host/tool Pointy already handled this turn, do not
    // let heuristic embodied parsing point at unrelated message controls.
    dispatchedThisStreamRef.current = pointyFastPathAction !== null;
    allowEmbodiedDispatchRef.current = allowPointyEmbodiedDispatch;
    lastParsedLenRef.current = 0;
    pointyModulesRef.current?.clearDispatchQueue();
    thinkingBufferRef.current = new StreamBuffer({
      onFlush: (chars) => {
        useChatStore.getState().appendThinkingDelta(chars, thinkingNodeRef.current, thinkingMetaRef.current);
        useChatStore.getState().appendPhaseThinkingDelta(
          chars,
          thinkingNodeRef.current,
          thinkingMetaRef.current?.stepId,
        );
      },
      initialHoldMs: 70,
      minCharsPerFrame: 2,
      maxCharsPerFrame: 20,
      targetBufferDepth: 28,
      easeInFrames: 10,
    });

    // D3: Consistent buffer flush helper — drain both buffers before any block boundary
    const flushBothBuffers = () => {
      answerBufferRef.current?.drain();
      thinkingBufferRef.current?.drain();
    };

    const handlers: SSEEventHandler = {
      onThinking: (data) => {
        traceEvent("thinking", { node: data.node });
        // Sprint 140b: Thinking events contain AI reasoning ONLY.
        // Pipeline progress is handled by onStatus (event: status).
        // Full thinking events are complete paragraphs — no buffering needed.
        if (data.content) {
          const store = useChatStore.getState();
          store.setStreamingThinking(data.content);
          store.appendPhaseThinking(data.content, data.node, data.step_id);
        }
      },
      onAnswer: (data) => {
        traceEvent("answer", { length: data.content.length });
        // Sprint 150: Push to buffer instead of direct store update
        answerBufferRef.current?.push(data.content);
        // v4.0 F7 (2026-05-06) — accumulate FULL answer text (with
        // [POINT:...] tag intact) for onDone parser. The display path
        // strips the tag in chat-store.appendStreamingContent.
        fullAnswerTextRef.current += data.content;
        // v7.0 F12 — multi-target streaming dispatch. Queue dedupes
        // already-fired so same target doesn't re-dispatch. Multiple
        // distinct targets in one response → cursor visits in sequence.
        tryStreamingDispatch(fullAnswerTextRef.current);
      },
      onSources: (data) => {
        const sources = Array.isArray(data.sources)
          ? data.sources
          : Array.isArray(data.content)
            ? data.content
            : [];
        traceEvent("sources", { count: sources.length });
        useChatStore.getState().setStreamingSources(sources);
      },
      onMetadata: (data) => {
        traceEvent("metadata", { session_id: data.session_id, model: data.model });
        useChatStore.getState().setPendingStreamMetadata(data as Partial<ChatResponseMetadata> as ChatResponseMetadata);
        // Sprint 120: Update mood from metadata if present
        const moodData = (data as Record<string, unknown>).mood as
          | { positivity: number; energy: number; mood: MoodType }
          | null
          | undefined;
        if (moodData && moodData.mood) {
          const charStore = useCharacterStore.getState();
          charStore.setMood(moodData.mood, moodData.positivity, moodData.energy);
          charStore.setMoodEnabled(true);
        }
      },
      onChatLifecycle: (data) => {
        traceEvent("chat_lifecycle", {
          event_name: data.event_name,
          lane: data.lane,
          status: data.status,
        });
        useChatStore.getState().addChatLifecycleEvent(data);
      },
      onDone: (data) => {
        traceEvent("done");
        // Some backend paths (notably source-backed web synthesis) emit the
        // final answer as a compact chunk right before `done`. Drain before
        // finalizing, otherwise the message can be committed while the answer
        // is still sitting in the animation buffer.
        flushBothBuffers();
        // v5.0 F8 (2026-05-06) — EMBODIED dispatcher. Wiii body schema:
        // cursor IS Wiii's hand, driven by Wiii's thinking. Two paths:
        //
        //   1. FAST: explicit `[POINT:bare-id:caption]` tag (Clicky pattern)
        //   2. FALLBACK: scan response for element label + intent phrase
        //      co-occurrence (Embodied pattern — works WITHOUT tag)
        //
        // Both feed `pointy.pointAt`. The fallback is what makes Wiii feel
        // alive — when Wiii says "Nút gửi ở góc dưới phải nè cậu", body
        // auto-points without the LLM needing to remember the tag syntax.
        //
        // SOTA reference: Anthropic Computer Use 2026 (intent → action),
        // farzaa/clicky (MIT, github April 2026), Project Astra grounding.
        const fullText = fullAnswerTextRef.current;
        fullAnswerTextRef.current = "";
        // v7.0 F12 — final pass on complete text. Queue dedupes — items
        // already fired mid-stream are no-ops. This is the SAFETY NET
        // for cases where streaming dispatch missed (e.g., AI emitted tag
        // in single chunk after answer is mostly done, or sentence didn't
        // hit boundary trigger).
        if (fullText) {
          tryStreamingDispatch(fullText);
        }
        queueMicrotask(() => {
          finalizeFromTransport(
            "done",
            data as Partial<ChatResponseMetadata> as ChatResponseMetadata,
          );
          const activeConv = useChatStore.getState().activeConversation();
          const sid = activeConv?.session_id || activeConv?.id || "";
          if (sid) {
            setTimeout(() => {
              useContextStore.getState().fetchContextInfo(sid);
            }, 500);
          }
        });
      },
      onError: (data) => {
        traceEvent("error", data);
        clearIdleGuard();
        // Sprint 150: Discard buffered tokens on error
        answerBufferRef.current?.discard();
        thinkingBufferRef.current?.discard();
        useChatStore.getState().setStreamError(
          data.message,
          data as unknown as Record<string, unknown>,
        );
        void useModelStore.getState().fetchProviders({ force: true });
      },
      onToolCall: (data) => {
        traceEvent("tool_call", { name: data.content.name, node: data.node });
        const store = useChatStore.getState();
        if (data.content.name === "tool_think") {
          const personaLabel = String(data.content.args?.persona_label || "").trim();
          if (personaLabel) {
            store.setStreamingThinkingLabel(personaLabel);
          }
          const rawThought = String(data.content.args?.thought || "").trim();
          const tc = {
            id: data.content.id,
            name: data.content.name,
            args: data.content.args,
            result: rawThought || undefined,
            node: data.node,
          };
          flushBothBuffers();
          store.appendToolCall(tc, toDisplayMeta(data));
          store.appendPhaseToolCall(tc, data.step_id);
          _thinkToolIds.add(data.content.id);
          return;
        }
        if (data.content.name === "tool_report_progress") {
          const rawMessage = String(data.content.args?.message || data.content.args?.phase_label || "").trim();
          const tc = {
            id: data.content.id,
            name: data.content.name,
            args: data.content.args,
            result: rawMessage || undefined,
            node: data.node,
          };
          flushBothBuffers();
          store.appendToolCall(tc, toDisplayMeta(data));
          store.appendPhaseToolCall(tc, data.step_id);
          _thinkToolIds.add(data.content.id);
          return;
        }
        // Inject CodeStudio session ID so VisualToolStrip can find it
        if (data.content.name === "tool_create_visual_code" && codeOpenActiveRef.current) {
          const activeSessionId = useCodeStudioStore.getState().activeSessionId;
          if (activeSessionId) {
            data.content.args = { ...(data.content.args || {}), _code_studio_session_id: activeSessionId };
          }
        }
        // D3: Flush both buffers before tool card
        flushBothBuffers();
        const tc = {
          id: data.content.id,
          name: data.content.name,
          args: data.content.args,
          node: data.node,
        };
        store.appendToolCall(tc, toDisplayMeta(data));
        store.appendPhaseToolCall(tc, data.step_id);
      },
      onToolResult: (data) => {
        traceEvent("tool_result", { id: data.content.id, node: data.node });
        // Sprint 147: Skip think tool results (just acknowledgments)
        if (_thinkToolIds.has(data.content.id)) {
          _thinkToolIds.delete(data.content.id);
          return;
        }
        const store = useChatStore.getState();
        store.updateToolCallResult(data.content.id, data.content.result, toDisplayMeta(data));
        store.updatePhaseToolCallResult(data.content.id, data.content.result);
      },
      onStatus: (data) => {
        traceEvent("status", { node: data.node, step: data.step });
        const label = data.content || data.step;
        const store = useChatStore.getState();

        // Runtime failover: model_switch notification from backend
        const statusDetails = (data as unknown as Record<string, unknown>).details as Record<string, unknown> | undefined;
        const isEphemeralHeartbeat = statusDetails?.subtype === "heartbeat" || statusDetails?.visibility === "status_only";
        if (statusDetails?.subtype === "model_switch") {
          const from = String(statusDetails.from_provider || "");
          const to = String(statusDetails.to_provider || "");
          useToastStore.getState().addToast(
            "info",
            `${from} đang bận — Wiii tự động chuyển sang ${to}`,
            5000,
          );
        }

        // Sprint 164: Detect parallel dispatch → open subagent group
        if (data.node === "parallel_dispatch") {
          const agentNames = _parseParallelTargets(data.content);
          if (agentNames.length > 0) {
            store.openSubagentGroup(
              label || "Triển khai song song",
              agentNames,
            );
          }
        }

        // Sprint 164: Detect aggregator → close group + extract decision
        if (data.node === "aggregator") {
          store.closeSubagentGroup();
          const details = (data as unknown as Record<string, unknown>).details as Record<string, unknown> | undefined;
          if (details?.aggregation) {
            store.setAggregationSummary(details.aggregation as AggregationSummary);
          }
        }

        // Sprint 164: Forward status to worker lane when inside group
        if (label && data.node && store._activeSubagentGroupId
            && data.node !== "parallel_dispatch" && data.node !== "aggregator") {
          store.appendWorkerStatus(data.node, label);
        }

        if (label) {
          // Phase 32d (#207): UI cleanup. The backend pipeline emits
          // ~13 status events per turn (guardian → supervisor → direct
          // → synthesizer with route + step_start/end variants). Each
          // setStreamingStep call repaints the live timer label, which
          // produces a jerky "internal pipeline" feeling that big
          // orgs (Claude / ChatGPT / Gemini) deliberately avoid — they
          // show ONE generic spinner ("Wiii đang nghĩ...") until the
          // first answer or thinking event lands. We surface only the
          // user-facing labels: explicit ``thinking_*`` events drive
          // ThinkingBlock; routing-internal status_only events stay
          // in the persistent timeline (debug / power users) but do
          // NOT update the live timer.
          if (!isEphemeralHeartbeat) {
            store.setStreamingStep(label);
            store.addStreamingStep(label, data.node);
            store.appendPhaseStatus(label, data.node, data.step_id);
          }
        }
      },
      onThinkingDelta: (data) => {
        traceEvent("thinking_delta", { node: data.node, length: data.content.length });
        // Sprint 150: Push to thinking buffer instead of direct update
        thinkingNodeRef.current = data.node;
        thinkingMetaRef.current = toDisplayMeta(data);
        thinkingBufferRef.current?.push(data.content);
      },
      onThinkingStart: (data) => {
        traceEvent("thinking_start", { node: data.node, phase: data.phase });
        // D3: Flush both buffers before opening new thinking block
        flushBothBuffers();
        thinkingMetaRef.current = undefined;
        const store = useChatStore.getState();
        // Sprint 164: Pass node for workerNode tagging inside subagent groups
        store.openThinkingBlock(
          data.content || data.node || "",
          data.summary,
          data.node,
          data.phase,
          toDisplayMeta({
            ...data,
            step_id: data.step_id || data.block_id,
          }),
          data.summary_mode,
        );
        store.addOrUpdatePhase(
          data.content || data.node || "",
          data.node,
          data.step_id || data.block_id,
          data.phase,
          data.summary,
          data.summary_mode,
        );
      },
      onThinkingEnd: (data) => {
        traceEvent("thinking_end", { node: data.node });
        // D3: Flush both buffers before closing thinking block
        flushBothBuffers();
        const store = useChatStore.getState();
        store.closeThinkingBlock(data.duration_ms);
        store.closeActivePhase(data.duration_ms);
        // Sprint 164: Mark the specific worker as completed in active group
        if (data.node && store._activeSubagentGroupId) {
          store.markWorkerCompleted(data.node);
        }
      },
      onDomainNotice: (data) => {
        traceEvent("domain_notice");
        useChatStore.getState().setStreamingDomainNotice(data.content);
      },
      onEmotion: (data) => {
        traceEvent("emotion", { mood: data.mood });
        // Sprint 135: Soul emotion — LLM-driven avatar expression
        try {
          const charStore = useCharacterStore.getState();
          charStore.setSoulEmotion({
            mood: data.mood,
            face: data.face ?? {},
            intensity: data.intensity,
          });
        } catch (err) {
          console.error("[Soul Emotion] SSE handler error:", err);
        }
      },
      onActionText: (data) => {
        traceEvent("action_text", { node: data.node });
        // D3: Flush both buffers before action text block
        flushBothBuffers();
        // Sprint 147: Bold action text between thinking blocks
        // Sprint 149: Pass node for agent attribution
        useChatStore.getState().appendActionText(data.content, data.node, toDisplayMeta(data));
      },
      onBrowserScreenshot: (data) => {
        traceEvent("browser_screenshot", { url: data.content.url, node: data.node });
        // D3: Flush both buffers before screenshot block
        flushBothBuffers();
        useChatStore.getState().appendScreenshot({
          url: data.content.url,
          image: data.content.image,
          label: data.content.label,
          node: data.node,
        }, toDisplayMeta(data));
      },
      onPreview: (data) => {
        traceEvent("preview", { id: data.content.preview_id, node: data.node });
        // D3: Flush both buffers before preview card
        flushBothBuffers();
        const previewSettings = useSettingsStore.getState().settings;
        if (previewSettings.show_previews === false) return;
        useChatStore.getState().addPreviewItem({
          ...data.content,
          preview_type: data.content.preview_type as PreviewType,
        }, data.node, toDisplayMeta(data));
      },
      onArtifact: (data) => {
        traceEvent("artifact", { id: data.content.artifact_id, node: data.node });
        // D3: Flush both buffers before artifact block
        flushBothBuffers();
        const artifactSettings = useSettingsStore.getState().settings;
        if (artifactSettings.show_artifacts === false) return;
        useChatStore.getState().addArtifact({
          ...data.content,
          artifact_type: data.content.artifact_type as ArtifactType,
        }, data.node, toDisplayMeta(data));
      },
      onVisual: (data) => {
        traceEvent("visual", { id: data.content.id, type: data.content.type, node: data.node });
        flushBothBuffers();
        try {
          useChatStore.getState().openVisualSession(data.content, data.node, toDisplayMeta(data));
          trackVisualTelemetry("visual_opened", {
            visual_id: data.content.id,
            visual_session_id: data.content.visual_session_id,
            visual_type: data.content.type,
            runtime: data.content.runtime,
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : "unknown visual store error";
          trackVisualTelemetry("visual_render_error", {
            visual_id: data.content.id,
            visual_type: data.content.type,
            runtime: data.content.runtime,
            error: `store_insert_failed:${message}`,
          });
          throw error;
        }
      },
      onVisualOpen: (data) => {
        traceEvent("visual_open", { id: data.content.id, session: data.content.visual_session_id, node: data.node });
        flushBothBuffers();
        useChatStore.getState().openVisualSession(data.content, data.node, toDisplayMeta(data));
        trackVisualTelemetry("visual_opened", {
          visual_id: data.content.id,
          visual_session_id: data.content.visual_session_id,
          visual_type: data.content.type,
          runtime: data.content.runtime,
        });
      },
      onVisualPatch: (data) => {
        traceEvent("visual_patch", { id: data.content.id, session: data.content.visual_session_id, node: data.node });
        flushBothBuffers();
        useChatStore.getState().patchVisualSession(data.content, data.node, toDisplayMeta(data));
        trackVisualTelemetry("visual_patched", {
          visual_id: data.content.id,
          visual_session_id: data.content.visual_session_id,
          visual_type: data.content.type,
          runtime: data.content.runtime,
        });
      },
      onVisualCommit: (data) => {
        traceEvent("visual_commit", { session: data.content.visual_session_id, node: data.node });
        useChatStore.getState().commitVisualSession(data.content.visual_session_id);
        trackVisualTelemetry("visual_committed", {
          visual_session_id: data.content.visual_session_id,
          status: data.content.status || "committed",
        });
      },
      onVisualDispose: (data) => {
        traceEvent("visual_dispose", { session: data.content.visual_session_id, node: data.node });
        useChatStore.getState().disposeVisualSession(data.content.visual_session_id, data.content.reason);
        trackVisualTelemetry("visual_disposed", {
          visual_session_id: data.content.visual_session_id,
          status: data.content.status || "disposed",
          reason: data.content.reason || "",
        });
      },
      onPointyAction: (data) => {
        // Wiii Pointy v2: agent-controlled cursor / spotlight via
        // spring-physics CursorRegistry. The backend tool
        // ``tool_pointy_show`` emits this event; we dispatch through
        // the pointy-host public API which uses CursorRegistry under
        // the hood (60Hz spring interpolation, GPU translate3d,
        // multi-cursor identity-aware) instead of the legacy
        // single-cursor + Web Animations keyframes.
        const payload = data.content;
        traceEvent("pointy_action", {
          action: payload?.action,
          selector: payload?.params?.selector,
          mode: payload?.mode,
        });
        // v3.0 F6 (2026-05-06): explicit warn-level log so Vite dev
        // server forwards it to terminal output. console.info is dropped
        // by Vite client console hook; only warn/error are forwarded.
        console.warn("[POINTY-SSE]", JSON.stringify({
          action: payload?.action,
          selector: payload?.params?.selector,
          source: payload?.params?.source,
          node: data.node,
        }));
        if (!payload || !payload.action) {
          console.warn("[POINTY-SSE] dropped — empty payload or no action");
          return;
        }
        if (payload.action === "ui.highlight" || payload.action === "ui.cursor_move") {
          dispatchedThisStreamRef.current = true;
        }

        // Lazy-import to avoid pulling pointy-host into the cold path of
        // chat streams that never invoke pointy.
        void import("@/pointy-host/api").then((pointy) => {
          const params = payload.params || {};
          const selector = (params.selector as string | undefined) ?? "";
          const caption = (params.message as string | undefined) ?? "";
          const duration_ms = (params.duration_ms as number | undefined) ?? 4500;

          switch (payload.action) {
            case "ui.highlight":
              if (selector) {
                const ok = pointy.pointAt(selector, { caption, duration_ms });
                console.warn(`[POINTY-DISPATCH] selector=${selector} ok=${ok}`);
                if (!ok) {
                  console.warn(`[POINTY] selector_not_found: ${selector}`);
                }
              } else {
                console.warn("[POINTY-SSE] highlight action with empty selector");
              }
              break;
            case "ui.cursor_move":
              if (selector) {
                pointy.pointAt(selector, { caption, duration_ms, skipSpotlight: true });
              } else if (
                typeof params.x === "number" &&
                typeof params.y === "number"
              ) {
                pointy.moveTo(params.x as number, params.y as number, {
                  label: caption || undefined,
                });
              }
              break;
            case "ui.clear":
              pointy.clear();
              break;
            default:
              console.warn(`[POINTY] Unknown action: ${payload.action}`);
          }
        }).catch((err) => {
          console.warn("[POINTY] Failed to load pointy api:", err);
        });
      },
      onHostAction: (data) => {
        traceEvent("host_action", { id: data.content?.id, action: data.content?.action });
        // Sprint 222b: AI agent requested a host action
        const { id, action, params } = data.content || {};
        if (id && action) {
          useHostContextStore.getState().requestAction(action, params || {}, id)
            .then((result) => {
              console.log(`[SSE] Host action ${id} resolved:`, result);
              void submitHostActionResult(
                buildHostActionResultRequest(action, id, result),
              ).catch((err) => {
                console.warn(`[SSE] Host action result ${id} failed:`, err instanceof Error ? err.message : String(err));
              });
              const hostStore = useHostContextStore.getState();
              const previewItem = buildHostActionPreviewItem(
                action,
                id,
                (params || {}) as Record<string, unknown>,
                result.data || {},
                hostStore.currentContext,
              );
              if (previewItem) {
                flushBothBuffers();
                useChatStore.getState().addPreviewItem(previewItem, data.node || "host_action", toDisplayMeta(data));
                useUIStore.getState().openPreview(previewItem.preview_id);
              } else if (action === "wiii_connect.facebook_post.direct_apply") {
                const summary =
                  typeof result.data?.summary === "string" && result.data.summary.trim().length > 0
                    ? result.data.summary.trim()
                    : result.success
                      ? "Đã đăng bài lên Facebook."
                      : (result.error || "Facebook chưa đăng.");
                useToastStore.getState().addToast(
                  result.success ? "success" : "error",
                  summary,
                  5000,
                );
              }
              const auditRequest = buildHostActionAuditRequest(
                action,
                id,
                result,
                hostStore.currentContext,
                hostStore.capabilities,
              );
              if (auditRequest) {
                void submitHostActionAudit(auditRequest).catch((err) => {
                  console.warn(`[SSE] Host action audit ${id} failed:`, err instanceof Error ? err.message : String(err));
                });
              }
            })
            .catch((err) => {
              const message = err instanceof Error ? err.message : String(err);
              console.warn(`[SSE] Host action ${id} failed:`, message);
              void submitHostActionResult(
                buildHostActionResultRequest(action, id, {
                  success: false,
                  error: message,
                  data: { summary: message },
                }),
              ).catch((submitError) => {
                console.warn(
                  `[SSE] Host action failed-result ${id} failed:`,
                  submitError instanceof Error ? submitError.message : String(submitError),
                );
              });
            });
        }
      },
      onCodeOpen: (data) => {
          traceEvent("code_open", { session: data.content.session_id, title: data.content.title });
          codeOpenActiveRef.current = true;
          // D3: Flush both buffers before code studio session
          flushBothBuffers();
          useCodeStudioStore.getState().openSession(
          data.content.session_id,
          data.content.title,
          data.content.language,
          data.content.version,
            {
              studioLane: data.content.studio_lane,
              artifactKind: data.content.artifact_kind,
              qualityProfile: data.content.quality_profile,
              rendererContract: data.content.renderer_contract,
              requestedView: data.content.requested_view,
            },
          );
          useCodeStudioStore.getState().setActiveSession(data.content.session_id);
          useUIStore.getState().openCodeStudio();
        },
      onCodeDelta: (data) => {
        traceEvent("code_delta", { session: data.content.session_id, idx: data.content.chunk_index });
        useCodeStudioStore.getState().appendCode(
          data.content.session_id,
          data.content.chunk,
          data.content.chunk_index,
          data.content.total_bytes,
        );
      },
      onCodeComplete: (data) => {
        traceEvent("code_complete", { session: data.content.session_id, version: data.content.version });
        useCodeStudioStore.getState().completeSession(
          data.content.session_id,
          data.content.full_code,
          data.content.language,
          data.content.version,
          data.content.visual_payload,
          data.content.visual_session_id,
        );
      },
      onKeepAlive: () => {
        traceEvent("keepalive");
        if (!hasStreamingOutput()) {
          useChatStore.getState().setStreamingStep("Wiii vẫn đang giữ kết nối và xử lý...");
        }
      },
    };

    // Sprint 121b: Include session_id from active conversation for history continuity
    // Backend uses this to load previous messages in the same session
    const activeConv = useChatStore.getState().activeConversation();
    const sessionId = activeConv?.session_id || activeConv?.id || "";

    // Sprint 156: Include org ID when not personal workspace
    const orgId = useOrgStore.getState().activeOrgId;

    // Sprint 222: Use host-context-store (generic, replaces Sprint 221 page-context-store)
    // Sprint 221 backward compat: also read old page-context-store as fallback
    const pageData = usePageContextStore.getState().getPageContextForRequest();

    // Build user_context: prefer host-context-store, fallback to page-context-store
    const buildUserContext = () => {
      const authState = useAuthStore.getState();
      const authMode = authState.authMode;
      const currentHostCtx = withWiiiConnectSnapshot(
        useHostContextStore.getState().getContextForRequest(),
        wiiiConnectContextSnapshot,
      );
      const visualContext = useChatStore.getState().getActiveVisualContext();
      const widgetFeedback = useChatStore.getState().getActiveWidgetFeedbackContext();
      const codeStudioContext = useCodeStudioStore.getState().getActiveSessionContext();
      const hostCapabilities = useHostContextStore.getState().getCapabilitiesForRequest();
      const hostActionFeedback = useHostContextStore.getState().getActionFeedbackForRequest();
      const displayName = _resolveRequestDisplayName(
        authMode,
        settings.display_name,
        settings.user_id,
        authState.user?.name,
        authState.user?.email,
      );
      const compatibilityRole = _resolveCompatibilityRole(
        authMode,
        settings.user_role,
        currentHostCtx?.user_role,
        pageData?.page_context?.user_role,
      );
      if (currentHostCtx) {
        return {
          display_name: displayName,
          role: compatibilityRole,
          host_context: currentHostCtx,
          host_capabilities: hostCapabilities || undefined,
          host_action_feedback: hostActionFeedback || undefined,
          // Sprint 221 backward compat — keep flat fields for backend
          page_context: {
            page_type: currentHostCtx.page.type,
            page_title: currentHostCtx.page.title,
            ...(currentHostCtx.page.metadata || {}),
            content_snippet: currentHostCtx.content?.snippet,
            action: currentHostCtx.page.metadata?.action as string | undefined,
            user_role: currentHostCtx.user_role,
            workflow_stage: currentHostCtx.workflow_stage,
            selection: currentHostCtx.selection || undefined,
            editable_scope: currentHostCtx.editable_scope || undefined,
            entity_refs: currentHostCtx.entity_refs || undefined,
          },
          student_state: currentHostCtx.user_state || undefined,
          available_actions: currentHostCtx.available_actions || undefined,
          visual_context: visualContext,
          widget_feedback: widgetFeedback,
          code_studio_context: codeStudioContext,
          document_context: effectiveDocumentContext,
        };
      }
      if (pageData) {
        return {
          display_name: displayName,
          role: compatibilityRole,
          ...pageData,
          visual_context: visualContext,
          widget_feedback: widgetFeedback,
          code_studio_context: codeStudioContext,
          document_context: effectiveDocumentContext,
        };
      }
      if (visualContext || widgetFeedback || codeStudioContext || effectiveDocumentContext) {
        return {
          display_name: displayName,
          role: compatibilityRole,
          visual_context: visualContext,
          widget_feedback: widgetFeedback,
          code_studio_context: codeStudioContext,
          document_context: effectiveDocumentContext,
        };
      }
      return undefined;
    };

    const requestedViewHint = _inferCodeStudioRequestedView(content);
    const activeCodeStudioSessionId = useCodeStudioStore.getState().activeSessionId;
    if (requestedViewHint && activeCodeStudioSessionId) {
      useCodeStudioStore.getState().setRequestedView(activeCodeStudioSessionId, requestedViewHint);
      useUIStore.getState().openCodeStudio();
    }

    // Per-request provider selection
    const { provider: selectedProvider, model: selectedModel } =
      useModelStore.getState().consumeSelectionForRequest();
    const authState = useAuthStore.getState();
    const compatibilityRole = _resolveCompatibilityRole(
      authState.authMode,
      settings.user_role,
      useHostContextStore.getState().currentContext?.user_role,
      pageData?.page_context?.user_role,
    );
    const effectiveUserId = _resolveRequestUserId(
      authState.authMode,
      settings.user_id,
      authState.user?.id,
    );

    const request = {
      user_id: effectiveUserId,
      message: content,
      role: compatibilityRole,
      domain_id: domainId,
      session_id: sessionId,
      organization_id: orgId && orgId !== "personal" ? orgId : undefined,
      // Sprint 179: Include images for multimodal vision
      images: images && images.length > 0 ? images : undefined,
      // Sprint 222: Host-aware context (with Sprint 221 backward compat)
      user_context: buildUserContext(),
      // Per-request provider selection
      provider: selectedProvider !== "auto" ? selectedProvider : undefined,
      model: selectedProvider !== "auto" ? selectedModel ?? undefined : undefined,
      // Wiii Pointy v2.8: explicit `@plugin-name` mention force-binds
      // skills regardless of keyword intent gates.
      force_skills: forceSkills && forceSkills.length > 0 ? forceSkills : undefined,
      // F18 Phase B (2026-05-07) — Pointy mode user toggle. When ON,
      // backend tool forcing is only sent for explicit Pointy turns.
      pointy_mode: explicitPointyTurn,
    };

    // Sprint 194b (H5): Facebook cookie now in secure storage, not settings
    try {
      const { loadFacebookCookie } = await import("@/lib/secure-token-storage");
      const fbCookie = await loadFacebookCookie();
      if (fbCookie) {
        authHeaders["X-Facebook-Cookie"] = fbCookie;
        initClient(settings.server_url, authHeaders);
      }
    } catch {
      // Secure storage not available — skip Facebook cookie
    }

    let lastEventId: string | null = null;
    const streamRequestId = createStreamRequestId();
    let retryCount = 0;

    try {
      while (retryCount <= MAX_SSE_RETRIES) {
        try {
          const result = await sendMessageStream(
            request,
            handlers,
            streamController.signal,
            lastEventId,
            streamRequestId,
          );
          lastEventId = result.lastEventId;
          clearIdleGuardIfCurrent();

          if (TRACE_SSE) {
            console.debug("[SSE] stream-end", result);
          }

          if (abortRef.current === streamController && useChatStore.getState().isStreaming) {
            finalizeFromTransport(result.sawDone ? "done" : "eof");
          }

          lastEventId = null;
          break; // Success — exit retry loop
        } catch (err) {
          clearIdleGuardIfCurrent();

          if (streamController.signal.aborted) {
            if (streamController.signal.reason === IDLE_TIMEOUT_ABORT_REASON) {
              break;
            }
            break;
          }
          retryCount++;
          if (retryCount > MAX_SSE_RETRIES) {
            // Sprint 153b: Discard buffered tokens on final failure
            answerBufferRef.current?.discard();
            thinkingBufferRef.current?.discard();
            // Sprint 165: Localized error messages based on error type
            const errorMsg = _getVietnameseErrorMessage(err);
            useChatStore.getState().setStreamError(
              errorMsg,
              _extractStructuredErrorMetadata(err),
            );
            break;
          }
          // Sprint 153b: Discard partially-buffered tokens before retry
          answerBufferRef.current?.discard();
          thinkingBufferRef.current?.discard();
          if (abortRef.current === streamController) {
            scheduleIdleGuard();
          }
          await sleep(SSE_BACKOFF_MS * Math.pow(2, retryCount - 1));
        }
      }
    } finally {
      if (abortRef.current === streamController) {
        abortRef.current = null;
        clearIdleGuard();
        if (useChatStore.getState().isStreaming) {
          const abortReason = streamController.signal.aborted
            ? streamController.signal.reason
            : undefined;
          if (
            abortReason !== USER_CANCEL_ABORT_REASON &&
            abortReason !== STREAM_RESTART_ABORT_REASON
          ) {
            finalizeFromTransport(
              abortReason === IDLE_TIMEOUT_ABORT_REASON ? "idle_timeout" : "eof",
            );
          }
        }
      }
    }
  }, [clearIdleGuard, finalizeFromTransport, scheduleIdleGuard, traceEvent]);

  const cancelStream = useCallback(() => {
    // Sprint 150: Discard buffered tokens on cancel
    answerBufferRef.current?.discard();
    thinkingBufferRef.current?.discard();
    clearIdleGuard();
    abortRef.current?.abort(USER_CANCEL_ABORT_REASON);
    useChatStore.getState().clearStreaming();
  }, [clearIdleGuard]);

  return { sendMessage, cancelStream };
}
