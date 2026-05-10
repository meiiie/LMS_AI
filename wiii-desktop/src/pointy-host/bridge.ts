/**
 * Wiii Pointy — PostMessage bridge between the host page and the Wiii iframe.
 *
 * Listens for `wiii:action-request` messages whose `action` starts with `ui.`
 * and dispatches them to cursor/spotlight/tour handlers. Replies via
 * `wiii:action-response`. Cross-origin safe: only accepts requests from the
 * configured iframeOrigin and only replies to that same origin.
 */
import { hideCursor, moveCursorToPoint, moveCursorToRect } from "./cursor";
import { hideSpotlight, showSpotlight } from "./spotlight";
import { runTour } from "./tour";
import { resolveSyntheticId as _resolveSyntheticId } from "./auto-discovery";
import { refreshDomBeforePointyAction } from "./dom-refresh";
import { validatePointyTarget } from "./target-validation";
import type {
  ClickParams,
  CursorMoveParams,
  HighlightParams,
  NavigateParams,
  PointyConfig,
  PointyRequest,
  PointyResponse,
  PointyResult,
  ScrollToParams,
  ShowTourParams,
  TourStep,
} from "./types";

function defaultLog(level: "info" | "warn" | "error", msg: string, ctx?: unknown): void {
  const tag = "[wiii-pointy]";
  if (level === "error") console.error(tag, msg, ctx ?? "");
  else if (level === "warn") console.warn(tag, msg, ctx ?? "");
  else console.info(tag, msg, ctx ?? "");
}

function isPointyRequest(data: unknown): data is PointyRequest {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    d.type === "wiii:action-request" &&
    typeof d.id === "string" &&
    typeof d.action === "string" &&
    typeof d.params === "object" &&
    d.params !== null
  );
}

function ok(data?: Record<string, unknown>): PointyResult {
  return { success: true, ...(data ? { data } : {}) };
}
function fail(error: string): PointyResult {
  return { success: false, error };
}

/** Resolve a selector with light hardening: trim, reject empty, allow data-wiii-id. */
export function resolveSelector(selector: unknown): Element | null {
  if (typeof selector !== "string") return null;
  const trimmed = selector.trim();
  if (!trimmed) return null;
  if (typeof document === "undefined") return null;
  refreshDomBeforePointyAction("resolveSelector");

  // v8.0 (2026-05-06) — synthetic auto-discovery ID. Format:
  // `auto:<tag>:<slug>` or `auto:<tag>:<slug>-<idx>`. Look up the
  // bidirectional registry maintained by PageScanner.
  if (trimmed.startsWith("auto:")) {
    // Lazy import to avoid circular dep — auto-discovery imports nothing
    // from bridge but bridge would import auto-discovery → fine, no cycle.
    // Use synchronous dynamic require pattern via require would break
    // ESM. Instead: import statically at module top.
    const el = _resolveSyntheticId(trimmed);
    if (el) return el;
    // Synthetic ID not in registry (scanner hasn't seen it OR element
    // GC'd). Fall through to other resolution paths so user can still
    // dispatch via raw CSS selector if known.
  }

  if (/^[a-zA-Z0-9_-]+$/.test(trimmed)) {
    try {
      const escaped = trimmed.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      const semantic = pickBestElement(
        Array.from(document.querySelectorAll(`[data-wiii-id="${escaped}"]`)),
      );
      if (semantic) return semantic;
    } catch {
      return null;
    }
  }
  try {
    const direct = pickBestElement(Array.from(document.querySelectorAll(trimmed)));
    if (direct) return direct;
  } catch {
    return null;
  }
  return null;
}

function pickBestElement(elements: Element[]): Element | null {
  if (elements.length === 0) return null;
  let best: Element | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;
  for (const el of elements) {
    const score = elementPointyScore(el);
    if (score > bestScore) {
      best = el;
      bestScore = score;
    }
  }
  return best ?? elements[0] ?? null;
}

function elementPointyScore(el: Element): number {
  if (!(el instanceof HTMLElement)) return 0;
  if (!el.isConnected) return -1000;
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true") {
    return -900;
  }

  let styleScore = 0;
  if (typeof window !== "undefined" && window.getComputedStyle) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return -800;
    const opacity = parseFloat(style.opacity || "1");
    if (Number.isFinite(opacity)) styleScore += Math.max(0, Math.min(opacity, 1));
  }

  const rect = el.getBoundingClientRect();
  const area = Math.max(0, rect.width) * Math.max(0, rect.height);
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const visibleX = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
  const visibleY = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
  const visibleArea = visibleX * visibleY;
  const ratio = area > 0 ? visibleArea / area : 0;
  const enabledBonus =
    el.getAttribute("aria-disabled") === "true" ||
    (el instanceof HTMLButtonElement && el.disabled) ||
    (el instanceof HTMLInputElement && el.disabled)
      ? 0
      : 0.1;
  const nativeInteractiveBonus =
    el instanceof HTMLButtonElement ||
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement ||
    (el instanceof HTMLAnchorElement && Boolean(el.href))
      ? 0.25
      : 0;

  return ratio * 1000 + Math.min(area, 50_000) / 50_000 + styleScore + enabledBonus + nativeInteractiveBonus;
}

export async function handleHighlight(params: HighlightParams): Promise<PointyResult> {
  const target = resolveSelector(params.selector);
  if (!target) return fail(`selector_not_found:${params.selector}`);
  const rect = target instanceof HTMLElement
    ? scrollIntoViewIfNeeded(target, target.getBoundingClientRect())
    : target.getBoundingClientRect();
  const validation = validatePointyTarget(target, rect);
  if (!validation.ok) {
    return fail(`target_not_visible:${params.selector}:${validation.reason ?? "unknown"}`);
  }
  moveCursorToRect(rect, { duration_ms: 600 });
  showSpotlight(target, {
    message: params.message,
    duration_ms: params.duration_ms,
  });
  return ok({ summary: `Đã trỏ vào element: ${describeTarget(target)}` });
}

export async function handleCursorMove(params: CursorMoveParams): Promise<PointyResult> {
  if (params.selector) {
    const target = resolveSelector(params.selector);
    if (!target) return fail(`selector_not_found:${params.selector}`);
    const rect = target.getBoundingClientRect();
    const validation = validatePointyTarget(target, rect);
    if (!validation.ok) {
      return fail(`target_not_visible:${params.selector}:${validation.reason ?? "unknown"}`);
    }
    moveCursorToRect(rect, {
      duration_ms: params.duration_ms ?? 360,
      label: params.label,
    });
    return ok({ summary: `Đã di chuyển con trỏ tới element: ${describeTarget(target)}` });
  }

  if (
    typeof params.x !== "number" ||
    typeof params.y !== "number" ||
    !Number.isFinite(params.x) ||
    !Number.isFinite(params.y)
  ) {
    return fail("missing_cursor_target");
  }

  const normalized = params.coordinate_space === "normalized";
  const x =
    normalized && typeof window !== "undefined"
      ? params.x * window.innerWidth
      : params.x;
  const y =
    normalized && typeof window !== "undefined"
      ? params.y * window.innerHeight
      : params.y;
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return fail("missing_cursor_target");
  }
  moveCursorToPoint(
    { x, y },
    {
      duration_ms: params.duration_ms ?? 360,
      label: params.label,
    },
  );
  return ok({ summary: "Đã di chuyển con trỏ." });
}

export async function handleScrollTo(params: ScrollToParams): Promise<PointyResult> {
  const target = resolveSelector(params.selector);
  if (!target) return fail(`selector_not_found:${params.selector}`);
  const validation = validatePointyTarget(target);
  if (!validation.ok) {
    return fail(`target_not_visible:${params.selector}:${validation.reason ?? "unknown"}`);
  }
  if ("scrollIntoView" in target && typeof (target as HTMLElement).scrollIntoView === "function") {
    (target as HTMLElement).scrollIntoView({
      behavior: "smooth",
      block: params.block ?? "center",
    });
  }
  return ok({ summary: `Đã cuộn tới element: ${describeTarget(target)}` });
}

export async function handleNavigate(
  params: NavigateParams,
  config: PointyConfig,
): Promise<PointyResult> {
  const route = (params.route ?? "").trim();
  const url = (params.url ?? "").trim();
  if (!route && !url) return fail("missing_target");
  if (route) {
    if (config.onNavigate) {
      try {
        await config.onNavigate(route);
        return ok({ summary: `Đã chuyển sang route: ${route}` });
      } catch (e) {
        return fail(`navigate_failed:${(e as Error).message}`);
      }
    }
    if (typeof window !== "undefined") {
      window.location.assign(route);
      return ok({ summary: `Đã chuyển sang: ${route}` });
    }
    return fail("no_navigator_available");
  }
  if (!isSafeUrl(url)) return fail("unsafe_url");
  if (typeof window !== "undefined") {
    window.location.assign(url);
    return ok({ summary: `Đã chuyển sang URL: ${url}` });
  }
  return fail("no_navigator_available");
}

export async function handleShowTour(params: ShowTourParams): Promise<PointyResult> {
  if (!Array.isArray(params.steps) || params.steps.length === 0) {
    return fail("empty_tour");
  }
  const steps: TourStep[] = params.steps.filter(
    (s): s is TourStep => !!s && typeof s.selector === "string" && typeof s.message === "string",
  );
  if (steps.length === 0) return fail("invalid_tour_steps");
  const result = await runTour(steps, {
    startAt: params.start_at,
    resolveSelector: (selector) => resolveSelector(selector),
  });
  return ok({
    summary: `Tour ${result.completed_steps}/${result.total_steps} bước.`,
    completed_steps: result.completed_steps,
    total_steps: result.total_steps,
    missing_selectors: result.missing_selectors,
    cancelled: result.cancelled,
  });
}

export async function handleClick(params: ClickParams): Promise<PointyResult> {
  const target = resolveSelector(params.selector);
  if (!target) return fail(`selector_not_found:${params.selector}`);
  if (!(target instanceof HTMLElement) || target.getAttribute("data-wiii-click-safe") !== "true") {
    return fail(`unsafe_click_target:${params.selector}`);
  }
  if (
    target.hasAttribute("disabled")
    || target.getAttribute("aria-disabled") === "true"
    || (target instanceof HTMLButtonElement && target.disabled)
  ) {
    return fail(`disabled_click_target:${params.selector}`);
  }
  const rect = scrollIntoViewIfNeeded(target, target.getBoundingClientRect());
  const validation = validatePointyTarget(target, rect);
  if (!validation.ok) {
    return fail(`target_not_visible:${params.selector}:${validation.reason ?? "unknown"}`);
  }
  moveCursorToRect(rect, { duration_ms: 260 });
  showSpotlight(target, {
    message: params.message || "Wiii dang mo muc nay cho ban.",
    duration_ms: 900,
  });
  target.click();
  return ok({
    summary: `Da bam element: ${describeTarget(target)}`,
    clicked: true,
    click_kind: target.getAttribute("data-wiii-click-kind") || "safe",
  });
}

export function describeTarget(el: Element): string {
  const labels: string[] = [];
  const id = el.getAttribute("data-wiii-id") || el.id;
  if (id) labels.push(`#${id}`);
  const aria = el.getAttribute("aria-label");
  if (aria) labels.push(`"${aria}"`);
  if (!labels.length) {
    const text = (el.textContent || "").trim();
    if (text) labels.push(`"${text.slice(0, 40)}"`);
  }
  if (!labels.length) labels.push(el.tagName.toLowerCase());
  return labels.join(" ");
}

function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url, typeof window !== "undefined" ? window.location.href : undefined);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    const host = parsed.hostname.toLowerCase();
    if (host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0") return false;
    if (host.endsWith(".local") || host.endsWith(".internal")) return false;
    return true;
  } catch {
    return false;
  }
}

function scrollIntoViewIfNeeded(target: HTMLElement, rect: DOMRect): DOMRect {
  if (typeof target.scrollIntoView !== "function") return rect;
  if (isMostlyVisible(rect)) return rect;
  target.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });
  return target.getBoundingClientRect();
}

function isMostlyVisible(rect: DOMRect): boolean {
  const area = Math.max(0, rect.width) * Math.max(0, rect.height);
  if (area <= 0) return true;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const visibleX = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
  const visibleY = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
  return (visibleX * visibleY) / area >= 0.9;
}

export interface BridgeHandle {
  dispose: () => void;
}

export function createBridge(config: PointyConfig): BridgeHandle {
  const log = config.log ?? defaultLog;
  const targetOrigin = config.iframeOrigin;

  const handler = (event: MessageEvent): void => {
    if (event.origin !== targetOrigin) return;
    if (!isPointyRequest(event.data)) return;

    const req = event.data;
    void dispatch(req, config)
      .then((result) => sendResponse(event, req.id, result, targetOrigin, log))
      .catch((err) => {
        log("error", "dispatch_threw", err);
        sendResponse(event, req.id, fail((err as Error).message ?? "unknown_error"), targetOrigin, log);
      });
  };

  if (typeof window !== "undefined") {
    window.addEventListener("message", handler);
  }

  return {
    dispose: () => {
      if (typeof window !== "undefined") {
        window.removeEventListener("message", handler);
      }
      hideSpotlight();
      hideCursor();
    },
  };
}

async function dispatch(req: PointyRequest, config: PointyConfig): Promise<PointyResult> {
  switch (req.action) {
    case "ui.cursor_move":
      return handleCursorMove(req.params as unknown as CursorMoveParams);
    case "ui.highlight":
      return handleHighlight(req.params as unknown as HighlightParams);
    case "ui.scroll_to":
      return handleScrollTo(req.params as unknown as ScrollToParams);
    case "ui.navigate":
      return handleNavigate(req.params as unknown as NavigateParams, config);
    case "ui.show_tour":
      return handleShowTour(req.params as unknown as ShowTourParams);
    case "ui.click":
      return handleClick(req.params as unknown as ClickParams);
    default:
      return fail(`unsupported_action:${req.action}`);
  }
}

function sendResponse(
  event: MessageEvent,
  id: string,
  result: PointyResult,
  targetOrigin: string,
  log: NonNullable<PointyConfig["log"]>,
): void {
  const reply: PointyResponse = {
    type: "wiii:action-response",
    id,
    result,
  };
  const target = (event.source as Window) ?? null;
  if (!target) {
    log("warn", "no_event_source");
    return;
  }
  try {
    target.postMessage(reply, targetOrigin);
  } catch (e) {
    log("error", "postMessage_failed", e);
  }
}

export const _testing = {
  isPointyRequest,
  isSafeUrl,
  ok,
  fail,
};
