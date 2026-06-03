/**
 * Host Context Store — generic context from any host application.
 * Sprint 222: "Wiii Universal Context Engine"
 *
 * Replaces Sprint 221's LMS-specific page-context-store with a
 * host-agnostic store supporting LMS, e-commerce, trading, CRM, etc.
 */
import { create } from "zustand";
import {
  applyWiiiConnectFacebookPost,
  fetchWiiiConnectFacebookPages,
  fetchWiiiConnectProviderConnections,
  previewWiiiConnectFacebookPost,
} from "@/api/wiii-connect";
import type { ImageInput } from "@/api/types";

const MAX_SNIPPET_LENGTH = 2000;

// ── Types ──

export interface HostPage {
  type: string;
  title?: string;
  url?: string;
  content_type?: string;
  metadata?: Record<string, unknown>;
}

export interface HostContext {
  host_type: string;
  host_name?: string;
  connector_id?: string;
  host_user_id?: string;
  host_workspace_id?: string;
  host_organization_id?: string;
  resource_uri?: string;
  page: HostPage;
  user_role?: string;
  workflow_stage?: string;
  selection?: Record<string, unknown> | null;
  editable_scope?: Record<string, unknown> | null;
  entity_refs?: Array<Record<string, unknown>> | null;
  user_state?: Record<string, unknown> | null;
  host_action_feedback?: {
    last_action_result?: {
      params?: {
        source?: string;
      } | null;
    } | null;
  } | null;
  content?: { snippet?: string; structured?: unknown } | null;
  available_actions?: Array<{
    action?: string;
    name?: string;
    label: string;
    input_schema?: unknown;
    roles?: string[];
    permission?: string;
    required_permissions?: string[];
    requires_confirmation?: boolean;
    mutates_state?: boolean;
    surface?: string;
    result_schema?: unknown;
  }> | null;
}

export interface HostCapabilities {
  host_type: string;
  host_name?: string;
  connector_id?: string;
  host_workspace_id?: string;
  host_organization_id?: string;
  version?: string;
  resources: string[];
  surfaces?: string[];
  tools: Array<{
    name: string;
    description: string;
    input_schema?: unknown;
    roles?: string[];
    permission?: string;
    required_permissions?: string[];
    requires_confirmation?: boolean;
    mutates_state?: boolean;
    surface?: string;
    result_schema?: unknown;
  }>;
}

interface LegacyPageContext {
  [key: string]: unknown;
  page_type?: string;
  page_title?: string;
  connector_id?: string;
  host_user_id?: string;
  host_workspace_id?: string;
  host_organization_id?: string;
  action?: string;
  user_role?: string;
  workflow_stage?: string;
  selection?: Record<string, unknown> | null;
  editable_scope?: Record<string, unknown> | null;
  entity_refs?: Array<Record<string, unknown>> | null;
  course_id?: string;
  course_name?: string;
  lesson_id?: string;
  lesson_name?: string;
  chapter_name?: string;
  content_snippet?: string;
  content_type?: string;
  quiz_question?: string;
  quiz_options?: string[];
  assignment_description?: string;
  structured?: unknown;
}

// ── Action Support (Sprint 222b Phase 5) ──

export interface ActionResult {
  success: boolean;
  data?: Record<string, unknown>;
  error?: string;
}

export interface HostActionFeedbackItem {
  request_id: string;
  action: string;
  params?: Record<string, unknown>;
  success: boolean;
  summary?: string;
  error?: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

// ── Store ──

interface HostContextState {
  capabilities: HostCapabilities | null;
  currentContext: HostContext | null;
  localActionImages: ImageInput[];
  lastActionResult: HostActionFeedbackItem | null;
  recentActionResults: HostActionFeedbackItem[];
  setCapabilities: (caps: HostCapabilities) => void;
  setLocalActionImages: (images?: ImageInput[] | null) => void;
  updateContext: (ctx: HostContext) => void;
  setLegacyPageContext: (
    ctx: LegacyPageContext,
    studentState?: Record<string, unknown> | null,
    actions?: Array<Record<string, unknown>> | null,
  ) => void;
  clear: () => void;
  getContextForRequest: () => HostContext | null;
  getCapabilitiesForRequest: () => HostCapabilities | null;
  getActionFeedbackForRequest: () => {
    last_action_result?: HostActionFeedbackItem;
    recent_action_results?: HostActionFeedbackItem[];
  } | null;

  // Sprint 222b Phase 5: Bidirectional Actions
  pendingActions: Map<string, {
    action: string;
    params: Record<string, unknown>;
    resolve: (result: ActionResult) => void;
    reject: (error: Error) => void;
    timeout: ReturnType<typeof setTimeout>;
  }>;
  requestAction: (
    action: string,
    params: Record<string, unknown>,
    requestId?: string,
  ) => Promise<ActionResult>;
  resolveAction: (requestId: string, result: ActionResult) => void;
}

function truncateSnippet(ctx: HostContext): HostContext {
  if (ctx.content?.snippet && ctx.content.snippet.length > MAX_SNIPPET_LENGTH) {
    return {
      ...ctx,
      content: {
        ...ctx.content,
        snippet: ctx.content.snippet.slice(0, MAX_SNIPPET_LENGTH),
      },
    };
  }
  return ctx;
}

const REQUEST_SENSITIVE_KEY_MARKERS = [
  "access_token",
  "refresh_token",
  "approval_token",
  "authorization",
  "bearer",
  "api_key",
  "apikey",
  "client_secret",
  "password",
  "secret",
  "cookie",
  "credential",
  "private_key",
  "connection_ref",
  "connection_id",
  "page_id",
  "vault_ref",
  "external_account_ref",
  "provider_payload",
  "raw_provider",
  "image_base64",
  "ak_secret",
];
const REQUEST_SENSITIVE_EXACT_KEYS = new Set(["token"]);
const MAX_REQUEST_ARRAY_ITEMS = 20;
const MAX_REQUEST_DEPTH = 6;

function isSensitiveRequestKey(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  if (!normalized) return false;
  if (REQUEST_SENSITIVE_EXACT_KEYS.has(normalized)) return true;
  return REQUEST_SENSITIVE_KEY_MARKERS.some((marker) => normalized.includes(marker));
}

function sanitizeRequestValue(
  value: unknown,
  key = "",
  depth = 0,
): unknown {
  if (key && isSensitiveRequestKey(key)) return undefined;
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return value.length > MAX_SNIPPET_LENGTH ? value.slice(0, MAX_SNIPPET_LENGTH) : value;
  }
  if (depth >= MAX_REQUEST_DEPTH) return undefined;
  if (Array.isArray(value)) {
    const items = value
      .slice(0, MAX_REQUEST_ARRAY_ITEMS)
      .map((item) => sanitizeRequestValue(item, "", depth + 1))
      .filter((item) => item !== undefined);
    return items.length > 0 ? items : undefined;
  }
  if (!value || typeof value !== "object") return undefined;

  const output = Object.create(null) as Record<string, unknown>;
  for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
    if (
      childKey === "__proto__" ||
      childKey === "prototype" ||
      childKey === "constructor"
    ) {
      continue;
    }
    const sanitized = sanitizeRequestValue(childValue, childKey, depth + 1);
    if (sanitized !== undefined) output[childKey] = sanitized;
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

function sanitizeHostContextForRequest(ctx: HostContext | null): HostContext | null {
  const sanitized = sanitizeRequestValue(ctx) as HostContext | undefined;
  return sanitized?.host_type && sanitized?.page ? sanitized : null;
}

function sanitizeCapabilitiesForRequest(caps: HostCapabilities | null): HostCapabilities | null {
  const sanitized = sanitizeRequestValue(caps) as HostCapabilities | undefined;
  return sanitized?.host_type && Array.isArray(sanitized.resources) && Array.isArray(sanitized.tools)
    ? sanitized
    : null;
}

function sanitizeActionFeedbackForRequest(
  feedback: HostActionFeedbackItem | null | undefined,
): HostActionFeedbackItem | undefined {
  return sanitizeRequestValue(feedback) as HostActionFeedbackItem | undefined;
}

function legacyToHostContext(
  legacy: LegacyPageContext,
  studentState?: Record<string, unknown> | null,
  actions?: Array<Record<string, unknown>> | null,
): HostContext {
  const metadata = Object.create(null) as Record<string, unknown>;
  const blockedMetadataKeys = new Set(["__proto__", "prototype", "constructor"]);
  const metaKeys = [
    "action",
    "workflow_stage",
    "course_id",
    "course_name",
    "lesson_id",
    "lesson_name",
    "chapter_name",
    "content_type",
    "quiz_question",
    "quiz_options",
    "assignment_description",
  ] as const;
  const topLevelKeys = new Set([
    "page_type",
    "page_title",
    "connector_id",
    "host_user_id",
    "host_workspace_id",
    "host_organization_id",
    "user_role",
    "selection",
    "editable_scope",
    "entity_refs",
    "content_snippet",
    "structured",
  ]);
  for (const key of metaKeys) {
    const val = legacy[key as keyof LegacyPageContext];
    if (val !== undefined && val !== null) {
      metadata[key] = val;
    }
  }
  for (const [key, val] of Object.entries(legacy)) {
    if (
      blockedMetadataKeys.has(key) ||
      topLevelKeys.has(key) ||
      Object.prototype.hasOwnProperty.call(metadata, key) ||
      val === undefined ||
      val === null
    ) {
      continue;
    }
    metadata[key] = val;
  }

  return {
    host_type: "lms",
    connector_id: legacy.connector_id,
    host_user_id: legacy.host_user_id,
    host_workspace_id: legacy.host_workspace_id,
    host_organization_id: legacy.host_organization_id,
    page: {
      type: legacy.page_type || "unknown",
      title: legacy.page_title,
      metadata,
    },
    user_role: legacy.user_role || undefined,
    workflow_stage: legacy.workflow_stage || undefined,
    selection: legacy.selection || null,
    editable_scope: legacy.editable_scope || null,
    entity_refs: legacy.entity_refs || null,
    user_state: studentState || null,
    content: (legacy.content_snippet || legacy.structured)
      ? {
          snippet: legacy.content_snippet || undefined,
          structured: legacy.structured || undefined,
        }
      : null,
    available_actions:
      (actions as HostContext["available_actions"]) || null,
  };
}

function stringParam(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  return typeof value === "string" ? value.trim() : "";
}

function latestUserImagePayload(
  params: Record<string, unknown>,
  imageSource: () => ImageInput[],
): {
  image_base64?: string | null;
  image_media_type?: string | null;
  image_filename?: string | null;
} {
  const explicitImage = stringParam(params, "image_base64");
  if (explicitImage) {
    return {
      image_base64: explicitImage,
      image_media_type: stringParam(params, "image_media_type") || "image/jpeg",
      image_filename: stringParam(params, "image_filename") || "wiii-facebook-image",
    };
  }

  const policy = stringParam(params, "image_policy");
  if (policy !== "use_latest_user_image") {
    return {};
  }
  const image = imageSource().find((item) => item?.type === "base64" && item.data);
  if (!image) {
    return {};
  }
  return {
    image_base64: image.data,
    image_media_type: image.media_type || "image/jpeg",
    image_filename: "wiii-chat-image",
  };
}

async function resolveFacebookPostBase(
  params: Record<string, unknown>,
  imageSource: () => ImageInput[],
) {
  const providerSlug = stringParam(params, "provider_slug") || "facebook";
  const connectionList = await fetchWiiiConnectProviderConnections(providerSlug, {
    probeDatabase: true,
  });
  const connection =
    (connectionList.connections || []).find(
      (item) => item.active || item.state === "connected",
    ) || connectionList.connections?.[0];
  const connectionRef =
    stringParam(params, "connection_ref") ||
    connection?.connection_ref ||
    connection?.connection_id ||
    "";
  if (!connectionRef) {
    return {
      error: "facebook_connection_missing",
      providerSlug,
      connectionRef: "",
    };
  }
  if (connection && !(connection.active || connection.state === "connected")) {
    return {
      error: "facebook_connection_not_active",
      providerSlug,
      connectionRef,
      connectionState: connection.state || "unknown",
    };
  }

  const message =
    stringParam(params, "message") ||
    stringParam(params, "caption") ||
    stringParam(params, "text");
  if (!message) {
    return {
      error: "facebook_post_message_missing",
      providerSlug,
      connectionRef,
    };
  }

  const pages = await fetchWiiiConnectFacebookPages(providerSlug, connectionRef);
  const selectedPageId = stringParam(params, "page_id") || pages.pages?.[0]?.page_id || "";
  const page = pages.pages?.find((item) => item.page_id === selectedPageId) || pages.pages?.[0];
  if (!selectedPageId) {
    return {
      error: pages.reason || "facebook_page_missing",
      providerSlug,
      connectionRef,
    };
  }

  return {
    providerSlug,
    connectionRef,
    pageId: selectedPageId,
    pageLabel: page?.name || selectedPageId,
    message,
    imagePayload: latestUserImagePayload(params, imageSource),
  };
}

function facebookPostBodyFromBase(base: {
  connectionRef: string;
  pageId: string;
  message: string;
  imagePayload: ReturnType<typeof latestUserImagePayload>;
}) {
  return {
    connection_ref: base.connectionRef,
    page_id: base.pageId,
    message: base.message,
    ...base.imagePayload,
  };
}

function executeLocalWiiiConnectAction(
  action: string,
  params: Record<string, unknown>,
  imageSource: () => ImageInput[],
): Promise<ActionResult> | null {
  if (action === "wiii_connect.facebook_post.direct_apply") {
    return (async () => {
      const base = await resolveFacebookPostBase(params, imageSource);
      if ("error" in base) {
        return {
          success: false,
          error: base.error,
          data: {
            code: base.error,
            provider_slug: base.providerSlug,
            connection_ref: base.connectionRef,
            summary: `Facebook chưa đăng: ${base.error}`,
          },
        };
      }

      const postBody = facebookPostBodyFromBase(base);
      const preview = await previewWiiiConnectFacebookPost(base.providerSlug, postBody);
      if (
        preview.status !== "ready" ||
        !preview.preview_evidence_id ||
        !preview.approval_token
      ) {
        const reason = preview.reason || "facebook_preview_blocked";
        return {
          success: false,
          error: reason,
          data: {
            ...preview,
            summary: `Facebook chưa đăng: ${reason}`,
          } as unknown as Record<string, unknown>,
        };
      }

      const response = await applyWiiiConnectFacebookPost(base.providerSlug, {
        ...postBody,
        approval_token: preview.approval_token,
        preview_evidence_id: preview.preview_evidence_id,
      });
      const succeeded = response.status === "succeeded";
      const reason = response.reason || (succeeded ? "succeeded" : "facebook_apply_failed");
      return {
        success: succeeded,
        error: succeeded ? undefined : reason,
        data: {
          ...response,
          preview_evidence_id_present: true,
          page_id: base.pageId,
          page_label: base.pageLabel,
          image_present: Boolean(base.imagePayload.image_base64),
          summary: succeeded
            ? `Đã đăng bài lên Facebook: ${base.pageLabel}.`
            : `Facebook chưa đăng: ${reason}`,
        } as unknown as Record<string, unknown>,
      };
    })();
  }

  if (action === "wiii_connect.facebook_post.preview") {
    return (async () => {
      const base = await resolveFacebookPostBase(params, imageSource);
      if ("error" in base) {
        return {
          success: false,
          error: base.error,
          data: {
            code: base.error,
            provider_slug: base.providerSlug,
            connection_ref: base.connectionRef,
          },
        };
      }

      const response = await previewWiiiConnectFacebookPost(
        base.providerSlug,
        facebookPostBodyFromBase(base),
      );
      if (response.status !== "ready") {
        return {
          success: false,
          error: response.reason || "facebook_preview_blocked",
          data: response as unknown as Record<string, unknown>,
        };
      }

      return {
        success: true,
        data: {
          ...response,
          preview_kind: "facebook_post",
          preview_token: response.preview_evidence_id,
          apply_action: "wiii_connect.facebook_post.apply",
          page_id: base.pageId,
          page_label: base.pageLabel,
          message: base.message,
          image_present: Boolean(base.imagePayload.image_base64),
          facebook_post_body: facebookPostBodyFromBase(base),
          summary: `Preview Facebook đã sẵn sàng cho ${base.pageLabel}.`,
        },
      };
    })();
  }

  if (action === "wiii_connect.facebook_post.apply") {
    return (async () => {
      const providerSlug = stringParam(params, "provider_slug") || "facebook";
      const approvalToken = stringParam(params, "approval_token");
      const previewEvidenceId =
        stringParam(params, "preview_evidence_id") || stringParam(params, "preview_token");
      const connectionRef = stringParam(params, "connection_ref");
      const pageId = stringParam(params, "page_id");
      const message = stringParam(params, "message");
      if (!approvalToken || !previewEvidenceId || !connectionRef || !pageId) {
        return {
          success: false,
          error: "facebook_apply_missing_preview_approval",
          data: { code: "facebook_apply_missing_preview_approval" },
        };
      }
      const response = await applyWiiiConnectFacebookPost(providerSlug, {
        connection_ref: connectionRef,
        page_id: pageId,
        message,
        image_base64: stringParam(params, "image_base64") || null,
        image_media_type: stringParam(params, "image_media_type") || null,
        image_filename: stringParam(params, "image_filename") || null,
        approval_token: approvalToken,
        preview_evidence_id: previewEvidenceId,
      });
      return {
        success: response.status === "succeeded",
        error: response.status === "succeeded" ? undefined : response.reason,
        data: {
          ...response,
          summary:
            response.status === "succeeded"
              ? "Đã đăng bài lên Facebook."
              : `Facebook chưa đăng: ${response.reason}`,
        },
      };
    })();
  }

  return null;
}

export const useHostContextStore = create<HostContextState>((set, get) => ({
  capabilities: null,
  currentContext: null,
  localActionImages: [],
  lastActionResult: null,
  recentActionResults: [],

  setCapabilities: (caps) => set({ capabilities: caps }),
  setLocalActionImages: (images) => set({ localActionImages: images ? [...images] : [] }),

  updateContext: (ctx) => set({ currentContext: truncateSnippet(ctx) }),

  setLegacyPageContext: (ctx, studentState, actions) => {
    const hostCtx = legacyToHostContext(ctx, studentState, actions);
    set({ currentContext: truncateSnippet(hostCtx) });
  },

  clear: () => {
    // Clear pending action timeouts
    const pending = get().pendingActions;
    for (const entry of pending.values()) {
      clearTimeout(entry.timeout);
    }
    set({
      capabilities: null,
      currentContext: null,
      lastActionResult: null,
      recentActionResults: [],
      localActionImages: [],
      pendingActions: new Map(),
    });
  },

  getContextForRequest: () => sanitizeHostContextForRequest(get().currentContext),

  getCapabilitiesForRequest: () => sanitizeCapabilitiesForRequest(get().capabilities),

  getActionFeedbackForRequest: () => {
    const last = get().lastActionResult;
    const recent = get().recentActionResults;
    if (!last && recent.length === 0) {
      return null;
    }
    const sanitizedLast = sanitizeActionFeedbackForRequest(last);
    const sanitizedRecent = recent
      .map((item) => sanitizeActionFeedbackForRequest(item))
      .filter((item): item is HostActionFeedbackItem => Boolean(item));
    return {
      last_action_result: sanitizedLast,
      recent_action_results: sanitizedRecent.length > 0 ? sanitizedRecent : undefined,
    };
  },

  pendingActions: new Map(),

  requestAction: (action, params, requestId) => {
    return new Promise<ActionResult>((resolve, reject) => {
      const finalRequestId = requestId || `req-${Math.random().toString(36).slice(2, 14)}`;
      const timeout = setTimeout(() => {
        const pending = get().pendingActions;
        pending.delete(finalRequestId);
        set({ pendingActions: new Map(pending) });
        reject(new Error(`Action timeout: ${action} (${finalRequestId})`));
      }, 30000);

      const pending = get().pendingActions;
      pending.set(finalRequestId, { action, params, resolve, reject, timeout });
      set({ pendingActions: new Map(pending) });

      const localAction = executeLocalWiiiConnectAction(
        action,
        params,
        () => get().localActionImages,
      );
      if (localAction) {
        localAction
          .then((result) => get().resolveAction(finalRequestId, result))
          .catch((error) => {
            const currentPending = get().pendingActions;
            const entry = currentPending.get(finalRequestId);
            if (entry) {
              clearTimeout(entry.timeout);
              currentPending.delete(finalRequestId);
              set({ pendingActions: new Map(currentPending) });
              entry.reject(error instanceof Error ? error : new Error(String(error)));
            }
          });
        return;
      }

      // Send PostMessage to host
      if (window.parent !== window) {
        window.parent.postMessage({
          type: "wiii:action-request",
          id: finalRequestId,
          action,
          params,
        }, "*");
      }
    });
  },

  resolveAction: (requestId, result) => {
    const pending = get().pendingActions;
    const entry = pending.get(requestId);
    if (entry) {
      clearTimeout(entry.timeout);
      pending.delete(requestId);
      const data = result.data || undefined;
      const summary =
        typeof data?.summary === "string" && data.summary.trim().length > 0
          ? data.summary.trim()
          : result.success
            ? `Host action ${entry.action} completed.`
            : (result.error || `Host action ${entry.action} failed.`);
      const feedback: HostActionFeedbackItem = {
        request_id: requestId,
        action: entry.action,
        params: entry.params,
        success: result.success,
        summary,
        error: result.error,
        data,
        timestamp: new Date().toISOString(),
      };
      const recent = [feedback, ...get().recentActionResults].slice(0, 6);
      set({
        pendingActions: new Map(pending),
        lastActionResult: feedback,
        recentActionResults: recent,
      });
      entry.resolve(result);
    }
  },
}));
