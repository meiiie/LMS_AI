/**
 * Dispatch queue (Wiii Pointy v7.0 — 2026-05-06).
 *
 * Cursor visits multiple targets sequentially within a single AI
 * response — "Đầu tiên click X, rồi Y, cuối cùng Z" → queue X→Y→Z.
 * Each visit holds for `holdMs` then advances. Smooth redirect mid-
 * flight if a new (higher-priority) target arrives.
 *
 * SOTA reference (2026):
 * - Anthropic Computer Use 2026 — interleaved actions in single response
 * - Project Astra (DeepMind) — multi-object grounding within utterance
 * - Real human pointing — sequential references during speech
 *
 * Idempotency:
 * - Each dispatched item tracks a stable signature (selector + caption)
 *   so re-dispatching the same step is a no-op.
 * - `clear()` aborts the queue (e.g., new stream start, error).
 *
 * Architecture: NOT React state — module-scope singleton tied to the
 * pointy-host singleton registry. Persists across stream boundaries.
 */

import { clear as clearPointy, pointAtDetailed } from "./api";

export interface QueuedPoint {
  selector: string;
  caption?: string;
  durationMs: number;
  /** Source that produced this point action, used only for telemetry. */
  source?: "tag" | "embodied" | "manual" | "legacy";
}

interface QueueItem extends QueuedPoint {
  signature: string;
}

export type PointyDispatchStatus =
  | "queued"
  | "started"
  | "accepted"
  | "failed"
  | "cancelled"
  | "skipped_duplicate";

export interface PointyDispatchEventDetail {
  action: "ui.highlight";
  selector: string;
  caption?: string;
  source: NonNullable<QueuedPoint["source"]>;
  signature: string;
  status: PointyDispatchStatus;
  reason?: string;
  timestamp: number;
}

const DEFAULT_HOLD_MS = 2400;
const REDIRECT_GRACE_MS = 200; // brief settle before advancing

let _queue: QueueItem[] = [];
let _activeTimer: ReturnType<typeof setTimeout> | null = null;
let _activeSignature: string | null = null;
let _activeItem: QueueItem | null = null;
const _seenSignatures = new Set<string>();
// v8.2 F15 (2026-05-06) — tag-priority flag. When AI emits explicit
// `[POINT:...]` tag, that's a deterministic signal — overrides any
// in-flight embodied dispatch (which is best-guess).
let _tagFiredThisStream: boolean = false;

function buildSignature(p: QueuedPoint): string {
  return `${p.selector}::${p.caption || ""}`;
}

function dispatchPointyTelemetry(
  item: Pick<QueueItem, "selector" | "caption" | "signature" | "source">,
  status: PointyDispatchStatus,
  reason?: string,
): void {
  if (typeof window === "undefined") return;
  try {
    const detail: PointyDispatchEventDetail = {
      action: "ui.highlight",
      selector: item.selector,
      caption: item.caption,
      source: item.source ?? "manual",
      signature: item.signature,
      status,
      reason,
      timestamp: Date.now(),
    };
    window.dispatchEvent(
      new CustomEvent("wiii:pointy:dispatch", { detail }),
    );
  } catch {
    // CustomEvent may be unavailable in stripped-down test environments.
  }
}

function processNext(): void {
  if (_activeTimer) return;
  const next = _queue.shift();
  if (!next) {
    _activeSignature = null;
    _activeItem = null;
    return;
  }
  _activeSignature = next.signature;
  _activeItem = next;
  dispatchPointyTelemetry(next, "started");
  // Fire pointAt (motion engine handles smooth redirect from current pos).
  const result = pointAtDetailed(next.selector, {
    caption: next.caption,
    duration_ms: next.durationMs + REDIRECT_GRACE_MS,
    onDismiss: () => cancelDispatchQueue("user_dismissed"),
  });
  if (!result.success) {
    const reason = result.reason ?? "pointy_action_failed";
    dispatchPointyTelemetry(next, "failed", reason);
    // v8.2 F15 (2026-05-06) — emit dispatch-failure feedback. Anthropic
    // Computer Use 2026 pattern: tool_result with `is_error: true` so
    // the agent sees what went wrong. Frontend dispatches CustomEvent
    // on window so DevTools tools / debug UIs can subscribe; SSE-side
    // failure plumbing is opt-in via Wiii's runtime feedback bus.
    console.warn(
      `[POINTY-DISPATCH] failed selector=${next.selector} reason=${reason}`,
    );
    if (typeof window !== "undefined") {
      try {
        window.dispatchEvent(
          new CustomEvent("wiii:pointy:dispatch-failed", {
            detail: {
              selector: next.selector,
              caption: next.caption,
              reason,
              timestamp: Date.now(),
            },
          }),
        );
      } catch {
        // CustomEvent unavailable in some test envs.
      }
    }
    // Selector resolved nothing — skip to next instead of stalling queue.
    _activeSignature = null;
    _activeItem = null;
    processNext();
    return;
  }
  dispatchPointyTelemetry(next, "accepted");
  // Hold this target then advance.
  _activeTimer = setTimeout(() => {
    _activeTimer = null;
    _activeSignature = null;
    _activeItem = null;
    processNext();
  }, next.durationMs);
}

/**
 * Enqueue a point. Idempotent: same signature won't re-dispatch within
 * the same stream session (use `clear()` between streams to allow
 * re-points).
 */
export function enqueuePoint(p: QueuedPoint): boolean {
  const signature = buildSignature(p);
  if (_seenSignatures.has(signature)) {
    dispatchPointyTelemetry(
      {
        ...p,
        signature,
        source: p.source ?? "manual",
      },
      "skipped_duplicate",
      "duplicate_signature",
    );
    return false;
  }
  _seenSignatures.add(signature);
  const item: QueueItem = {
    ...p,
    signature,
    source: p.source ?? "manual",
    durationMs: p.durationMs ?? DEFAULT_HOLD_MS,
  };
  _queue.push(item);
  dispatchPointyTelemetry(item, "queued");
  if (!_activeTimer && !_activeSignature) {
    processNext();
  }
  return true;
}

/**
 * Enqueue multiple points (e.g., from `parseAllPointTags` output) in
 * order. Returns count actually queued (after dedup).
 */
export function enqueuePoints(points: QueuedPoint[]): number {
  let count = 0;
  for (const p of points) {
    if (enqueuePoint(p)) count++;
  }
  return count;
}

/**
 * v8.2 F15 — TAG-PRIORITY enqueue. AI explicitly emitted `[POINT:...]`
 * tag (deterministic signal). Override any in-flight embodied dispatch:
 *
 * 1. Cancel current active timer (cursor mid-flight to wrong target).
 * 2. Drop pending queue items that came from embodied (best-guess).
 * 3. Set _tagFiredThisStream = true so subsequent embodied calls skip.
 * 4. Enqueue + dispatch tag points immediately.
 *
 * This is the "AI knows best" pattern — when AI commits to a specific
 * id via tag syntax, frontend trusts it over heuristic matching.
 */
export function enqueueTagPoints(points: QueuedPoint[]): number {
  if (points.length === 0) return 0;
  // Cancel in-flight embodied dispatch.
  if (_activeTimer) {
    clearTimeout(_activeTimer);
    _activeTimer = null;
  }
  _activeSignature = null;
  _activeItem = null;
  _queue = [];
  // Reset dedup so tags can re-dispatch even if embodied attempted same id.
  // We re-add the tag's signatures below via enqueuePoint.
  _tagFiredThisStream = true;
  let count = 0;
  for (const p of points) {
    if (enqueuePoint({ ...p, source: p.source ?? "tag" })) count++;
  }
  return count;
}

/**
 * v8.2 F15 — embodied enqueue. Skipped entirely when tag has already
 * fired in this stream (tag is deterministic, embodied is heuristic).
 */
export function enqueueEmbodiedPoints(points: QueuedPoint[]): number {
  if (_tagFiredThisStream) return 0;
  return enqueuePoints(
    points.map((p) => ({ ...p, source: p.source ?? "embodied" })),
  );
}

/**
 * Reset queue + dedup history. Call at stream start so a new turn can
 * re-point at previously-visited elements.
 */
export function clearDispatchQueue(): void {
  _queue = [];
  _seenSignatures.clear();
  if (_activeTimer) {
    clearTimeout(_activeTimer);
    _activeTimer = null;
  }
  _activeSignature = null;
  _activeItem = null;
  _tagFiredThisStream = false;
}

/** User-facing cancel: abort current multi-step guidance and send Wiii home. */
export function cancelDispatchQueue(reason: string = "user_cancelled"): void {
  const active = _activeItem;
  const pending = _queue;
  if (_activeTimer) {
    clearTimeout(_activeTimer);
    _activeTimer = null;
  }
  _queue = [];
  _seenSignatures.clear();
  _activeSignature = null;
  _activeItem = null;
  _tagFiredThisStream = false;

  if (active) {
    dispatchPointyTelemetry(active, "cancelled", reason);
  }
  for (const item of pending) {
    dispatchPointyTelemetry(item, "cancelled", reason);
  }
  clearPointy();
}

/** Diagnostic: current queue depth + active target. */
export function dispatchQueueState(): {
  depth: number;
  active: string | null;
  seen: number;
} {
  return {
    depth: _queue.length,
    active: _activeSignature,
    seen: _seenSignatures.size,
  };
}
