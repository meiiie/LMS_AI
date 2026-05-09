/**
 * Wiii Pointy — public API for in-app cursor control.
 *
 * Top-level façade callers should use instead of touching the registry,
 * spotlight, or bridge directly. Encapsulates:
 *
 *   - A lazily-created singleton ``CursorRegistry`` (one per page).
 *   - Selector resolution + ``getBoundingClientRect`` math.
 *   - Spotlight + tooltip overlay (existing ``spotlight.ts``).
 *   - Cursor identity defaults — ``WIII_IDENTITY`` for the AI itself,
 *     auto-spawn pattern for sub-soul / peer cursors.
 *
 * Callers (SSE handler, demo page, future Soul Bridge presence) get a
 * small, stable surface:
 *
 *     pointAt("#chat-send-button", { caption: "Đây là nút gửi." });
 *     moveTo(640, 480, { label: "Wiii" });
 *     showPeer({ id: "subsoul-bro", name: "Bro" }, { x, y });
 *     clear();
 *
 * The legacy ``bridge.ts`` (PostMessage, single-cursor + Web Animations
 * keyframes) stays for LMS embed compatibility but new code should not
 * use it — spring physics from ``CursorRegistry`` is the v2 path.
 */

import { CursorRegistry } from "./registry";
import {
  WIII_IDENTITY,
  identityFor,
  type CursorIdentity,
  type AwarenessState,
} from "./identity";
import { resolveSelector } from "./bridge";
import {
  showSpotlight,
  hideSpotlight,
} from "./spotlight";
import { hideCursor as legacyHideCursor } from "./cursor";
import { computeDockPosition } from "./dock-position";
import { validatePointyTarget, type PointyTargetSnapshot } from "./target-validation";

let _defaultRegistry: CursorRegistry | null = null;
// v3.0 Battleship: timer handle cho auto-return-to-dock. Một timer
// per page (chỉ Wiii cursor về dock; peers tự manage). Cleared mỗi
// pointAt mới hoặc clear() — KHÔNG để stale timer override new motion.
let _dockReturnTimer: ReturnType<typeof setTimeout> | null = null;
const DOCK_RETURN_HOLD_MS = 800; // hold "pointing" before returning

/**
 * Lazily create / return the page-wide cursor registry. The first call
 * mounts the rAF loop; subsequent calls reuse the same instance.
 */
export function getDefaultRegistry(): CursorRegistry {
  if (!_defaultRegistry || (_defaultRegistry as unknown as { disposed?: boolean }).disposed) {
    _defaultRegistry = new CursorRegistry();
  }
  return _defaultRegistry;
}

/** Tear down the singleton. Tests / unmount hooks call this. */
export function disposeDefaultRegistry(): void {
  _defaultRegistry?.dispose();
  _defaultRegistry = null;
  hideSpotlight();
  legacyHideCursor();
}

export interface PointAtOptions {
  /** Vietnamese tooltip shown next to the cursor + spotlight. */
  caption?: string;
  /** Spotlight duration in ms. Clamped 1500-8000. Default 4500. */
  duration_ms?: number;
  /** Cursor identity. Defaults to ``WIII_IDENTITY``. */
  identity?: CursorIdentity;
  /** If true, skips the spotlight ring (presence-only cursor move). */
  skipSpotlight?: boolean;
  /** Override the badge label (defaults to identity.name). */
  label?: string;
  /** Called when the user dismisses the active Pointy hint. */
  onDismiss?: () => void;
}

export interface PointAtResult {
  success: boolean;
  reason?: string;
  target?: PointyTargetSnapshot;
}

function emitPointyTargetEvent(
  selector: string,
  options: PointAtOptions,
  durationMs: number,
  snapshot: PointyTargetSnapshot,
): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent("wiii:pointy:target", {
        detail: {
          selector,
          caption: options.caption ?? "",
          duration_ms: durationMs,
          source: options.identity?.id ?? WIII_IDENTITY.id,
          target: snapshot,
        },
      }),
    );
  } catch {
    // Optional voice/telemetry hook. Pointy movement must remain fail-soft.
  }
}

function emitPointyTargetInvalidEvent(
  selector: string,
  options: PointAtOptions,
  reason: string,
  snapshot: PointyTargetSnapshot,
): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent("wiii:pointy:target-invalid", {
        detail: {
          selector,
          caption: options.caption ?? "",
          reason,
          target: snapshot,
          timestamp: Date.now(),
        },
      }),
    );
  } catch {
    // Optional debug/telemetry hook. Pointy must remain fail-soft.
  }
}

/**
 * Point the Wiii cursor at a UI element. Resolves the selector,
 * smoothly moves the spring-physics cursor to its center, and (unless
 * suppressed) shows the spotlight ring + Vietnamese tooltip.
 *
 * Failure modes are silent — no throw, just early return — because the
 * cursor is a UX hint, never a hard dependency. Callers always also
 * provide a prose answer.
 *
 * @returns true on success, false if the selector did not resolve.
 */
export function pointAt(
  selector: string,
  options: PointAtOptions = {},
): boolean {
  return pointAtDetailed(selector, options).success;
}

export function pointAtDetailed(
  selector: string,
  options: PointAtOptions = {},
): PointAtResult {
  const target = resolveSelector(selector);
  if (!target) {
    console.warn(`[POINTY-API] resolveSelector("${selector}") → null`);
    return { success: false, reason: "selector_not_found" };
  }

  let rect = target.getBoundingClientRect();
  if (!options.skipSpotlight && target instanceof HTMLElement) {
    rect = scrollIntoViewIfNeeded(target, rect);
  }
  const validation = validatePointyTarget(target, rect);
  if (!validation.ok) {
    const reason = validation.reason ?? "target_not_actionable";
    emitPointyTargetInvalidEvent(selector, options, reason, validation.snapshot);
    console.warn(`[POINTY-API] target rejected selector=${selector} reason=${reason}`);
    return { success: false, reason, target: validation.snapshot };
  }
  // v3.0 F6 (2026-05-06): log target rect at warn level (visible in
  // Vite stdout). If rect is 0×0 / off-screen, cursor "moves" but
  // visually appears static. Helps catch cases where the element is
  // in DOM but display:none / visibility:hidden / detached.
  console.warn(
    `[POINTY-API] pointAt selector=${selector} rect={top:${rect.top.toFixed(0)},left:${rect.left.toFixed(0)},w:${rect.width.toFixed(0)},h:${rect.height.toFixed(0)}} tag=${target.tagName}`,
  );
  const center = {
    x: rect.left + rect.width / 2 - CURSOR_TIP_X,
    y: rect.top + rect.height / 2 - CURSOR_TIP_Y,
  };

  const identity = options.identity ?? WIII_IDENTITY;
  const reg = getDefaultRegistry();
  // ``directed: true`` → MotionEngine dùng MinJerkTrajectory + Bezier
  // curve + Fitts duration (chuẩn vàng cho "deliberate reach" — Flash-
  // Hogan 1985). targetWidth lấy từ rect để Fitts scale precision đúng.
  reg.upsert(identity, center, options.label, {
    directed: true,
    targetWidth: Math.max(rect.width, rect.height),
  });
  const durationMs = clampDuration(options.duration_ms);
  emitPointyTargetEvent(selector, options, durationMs, validation.snapshot);

  // Record activity vào awareness layer (nếu mounted) → backend qua
  // host context biết "Wiii cursor đang trỏ vào X". Lazy-import
  // tránh cycle: api.ts ↔ integration.ts.
  void import("./integration").then(({ recordPointyActivity }) => {
    recordPointyActivity(identity.id, {
      selector,
      caption: options.caption ?? null,
    });
  }).catch(() => {
    // Awareness chưa mounted — silent skip.
  });

  // Settle into "pointing" state — visual treatment changes (stronger
  // glow). Strategy đã set qua directed flag, không cần tweak ở đây.
  setTimeout(() => reg.setState(identity.id, "pointing"), 200);

  if (!options.skipSpotlight) {
    showSpotlight(target, {
      message: options.caption,
      duration_ms: durationMs,
      onDismiss: options.onDismiss ?? clear,
    });
  }

  // v3.0 Battleship: only Wiii's cursor auto-returns to dock. Peer
  // cursors (Soul Bridge) keep their position — chúng có lifecycle
  // riêng managed by transport layer.
  if (identity.id === WIII_IDENTITY.id) {
    scheduleDockReturn(reg, durationMs);
  }

  return { success: true, target: validation.snapshot };
}

/**
 * Schedule the Wiii cursor to fly back to dock after the spotlight
 * duration completes. Total wait = duration + brief hold (so the
 * "pointing" state is visible to the user before withdrawal).
 *
 * Idempotent: previous pending timer is cancelled, so rapid successive
 * pointAt() calls don't queue stale returns. The cursor follows the
 * latest pointAt destination, then returns from THAT.
 */
function scheduleDockReturn(reg: CursorRegistry, durationMs: number): void {
  if (_dockReturnTimer) {
    clearTimeout(_dockReturnTimer);
    _dockReturnTimer = null;
  }
  const totalMs = durationMs + DOCK_RETURN_HOLD_MS;
  _dockReturnTimer = setTimeout(() => {
    _dockReturnTimer = null;
    // Hide spotlight first so the cursor isn't withdrawing while still
    // ringed. ``hideSpotlight`` is idempotent.
    hideSpotlight();
    // Set state to "returning" → motion engine treats it as a directed
    // reach back to dock. Use the same min-jerk strategy by passing
    // ``directed: true`` to upsert.
    const dockPos = computeDockPosition();
    // upsert internally calls setState("moving") — call setState("returning")
    // AFTER so our explicit state wins. Order matters: motion target must
    // be set first, then visual state overrides.
    reg.upsert(WIII_IDENTITY, dockPos, undefined, {
      directed: true,
      // Generous targetWidth so Fitts duration stays short for return.
      targetWidth: 100,
    });
    reg.setState(WIII_IDENTITY.id, "returning");
    // Once arrival should be complete (~Fitts duration ≤ 800ms for a
    // 100px target across viewport), settle into "dock" state. Use
    // 1000ms upper bound to cover slow viewports + tab-out throttling.
    setTimeout(() => {
      // Defensive: if cursor was redirected via another pointAt during
      // return, don't override its new state.
      const reg2 = _defaultRegistry;
      if (!reg2) return;
      const ids = reg2.ids();
      if (!ids.includes(WIII_IDENTITY.id)) return;
      reg2.setState(WIII_IDENTITY.id, "dock");
    }, 1000);
  }, totalMs);
}

/** Cancel any pending dock return — used when caller wants to keep cursor
 * settled (e.g., long-running tutorial sequence). */
export function cancelDockReturn(): void {
  if (_dockReturnTimer) {
    clearTimeout(_dockReturnTimer);
    _dockReturnTimer = null;
  }
}

/** Force the Wiii cursor back to dock immediately (skip duration wait). */
export function returnToDock(): void {
  cancelDockReturn();
  const reg = _defaultRegistry;
  if (!reg) return;
  hideSpotlight();
  const dockPos = computeDockPosition();
  reg.setState(WIII_IDENTITY.id, "returning");
  reg.upsert(WIII_IDENTITY, dockPos, undefined, {
    directed: true,
    targetWidth: 100,
  });
  setTimeout(() => {
    const reg2 = _defaultRegistry;
    if (!reg2) return;
    if (!reg2.ids().includes(WIII_IDENTITY.id)) return;
    reg2.setState(WIII_IDENTITY.id, "dock");
  }, 1000);
}

export interface MoveToOptions {
  identity?: CursorIdentity;
  label?: string;
  state?: AwarenessState;
}

/**
 * Move a cursor to absolute viewport coordinates without a spotlight.
 * Useful for presence-only motion (e.g., Wiii "thinking" wandering)
 * or for scripted demos.
 */
export function moveTo(
  x: number,
  y: number,
  options: MoveToOptions = {},
): void {
  const identity = options.identity ?? WIII_IDENTITY;
  const reg = getDefaultRegistry();
  reg.upsert(identity, { x, y }, options.label);
  if (options.state) reg.setState(identity.id, options.state);
}

/** Show or update a peer cursor (sub-soul, Soul Bridge participant). */
export function showPeer(
  identity: CursorIdentity,
  position: { x: number; y: number },
  label?: string,
): void {
  if (identity.id === WIII_IDENTITY.id) {
    // Wiii orange is reserved — refuse spoofing the AI's own identity.
    return;
  }
  getDefaultRegistry().upsert(identity, position, label);
}

/** Convenience: build a peer identity + show in one call. */
export function spawnPeer(
  id: string,
  name: string,
  position: { x: number; y: number },
  options: { avatar?: string } = {},
): CursorIdentity {
  const identity = identityFor(id, name, { avatar: options.avatar, role: "ai-peer" });
  showPeer(identity, position);
  return identity;
}

/** Update a cursor's awareness state. */
export function setCursorState(id: string, state: AwarenessState): void {
  getDefaultRegistry().setState(id, state);
}

/**
 * Clear all active overlays — Wiii cursor returns to dock immediately,
 * spotlight hides. Peer cursors go idle (managed by transport layer).
 *
 * v3.0 Battleship: explicit ``clear()`` triggers immediate dock return
 * for Wiii (no waiting for spotlight duration). Cancels any pending
 * auto-return timer so we don't double-fire.
 */
export function clear(): void {
  cancelDockReturn();
  hideSpotlight();
  const reg = _defaultRegistry;
  if (!reg) return;
  for (const id of reg.ids()) {
    if (id === WIII_IDENTITY.id) {
      // Wiii goes home to dock, not idle — keeps Battleship invariant
      // "Wiii cursor is always either at dock or in flight".
      // upsert calls setState("moving") internally — order matters,
      // setState("returning") AFTER so our explicit state wins.
      const dockPos = computeDockPosition();
      reg.upsert(WIII_IDENTITY, dockPos, undefined, {
        directed: true,
        targetWidth: 100,
      });
      reg.setState(WIII_IDENTITY.id, "returning");
      setTimeout(() => {
        const reg2 = _defaultRegistry;
        if (!reg2) return;
        if (!reg2.ids().includes(WIII_IDENTITY.id)) return;
        reg2.setState(WIII_IDENTITY.id, "dock");
      }, 1000);
    } else {
      reg.setState(id, "idle");
    }
  }
}

/** Hard reset — cursor disappears, all peers gone, registry torn down. */
export function clearAll(): void {
  disposeDefaultRegistry();
}

// ────────────────────────────────────────────────────────────────────
// Constants kept in sync with registry.ts SVG geometry.
// ────────────────────────────────────────────────────────────────────

const CURSOR_TIP_X = 5;
const CURSOR_TIP_Y = 4;

function clampDuration(ms: number | undefined): number {
  const v = typeof ms === "number" && Number.isFinite(ms) ? ms : 4500;
  return Math.max(1500, Math.min(v, 8000));
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
