/**
 * CursorRegistry — multi-cursor host (Wiii Pointy v2.1, redesigned art).
 *
 * One ``CursorRegistry`` per page renders any number of cursors, each
 * with its own SVG element, ``SpringInterpolator``, ``CursorIdentity``,
 * and awareness state. A single ``requestAnimationFrame`` loop drives
 * every cursor so motion stays in sync with display refresh — exactly
 * the architecture Liveblocks / Figma use to keep dozens of cursors
 * smooth on the same canvas.
 *
 * v2.1 (2026-05-06) thay đổi hình thức + diệt jitter:
 *
 * - Cursor art mới (``cursor-art.ts``): 24×24px, color-tinted, không
 *   pulse ring, không avatar circle inside SVG.
 * - Name pill TÁCH RA `<div>` riêng — không nằm trong SVG nữa, tránh
 *   font bị blur theo drop-shadow filter của cursor.
 * - **Diệt jitter**: ``Math.round`` cả x lẫn y trước khi set transform
 *   (sub-pixel positions gây shimmer). Loại bỏ CSS keyframe animation
 *   ``pointy-bob`` và ``pointy-live-pulse`` vì chúng dùng ``translate``
 *   / ``transform: scale()`` xung đột với JS-driven transform → root
 *   cause của rung lắc.
 * - Spring damping default ``0.85 → 0.92`` — giảm overshoot.
 *
 * Public API kept minimal so callers can adopt incrementally:
 *
 *   const registry = new CursorRegistry();
 *   registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });   // create or move
 *   registry.setState(WIII_IDENTITY.id, "thinking");  // awareness state
 *   registry.setLabel(WIII_IDENTITY.id, "Wiii");      // dynamic label
 *   registry.remove(WIII_IDENTITY.id);                // fade + cleanup
 *   registry.dispose();                                // tear down all
 *
 * Old ``cursor.ts`` (single-cursor SVG + Web Animations API) remains
 * for the LMS embed bridge until the bridge is migrated. New code
 * should use this registry directly.
 *
 * Tham khảo: ``research-cursor-art-sota-2026-05-06.md``,
 * ``research-multiplayer-cursors-sota-2026-05-06.md``.
 */

import { type Vec2 } from "./interpolator";
import { MotionEngine, type SetTargetOptions } from "./motion-engine";
import type {
  AwarenessState,
  CursorIdentity,
} from "./identity";
import {
  CURSOR_VIEWBOX_H,
  CURSOR_VIEWBOX_W,
  cursorSvgInner,
  cursorSvgStyle,
  namePillStyle,
  pillLabel,
  PILL_OFFSET_X,
  PILL_OFFSET_Y,
} from "./cursor-art";

// Z-index above app content but below browser-native modals/overlays.
const CURSOR_Z_INDEX = 2147483640;

// v3.0 Battleship: dock state breathing pulse via CSS keyframe.
// Animate ONLY opacity (NOT transform/translate) để KHÔNG conflict với
// JS-driven transform mỗi frame trong applyTransform. Opacity là separate
// CSS property, browser composite riêng, an toàn với JS transform.
const POINTY_GLOBAL_STYLES = `
@keyframes pointy-dock-breathe {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 0.95; }
}
@keyframes pointy-dock-pill-breathe {
  0%, 100% { opacity: 0.65; }
  50% { opacity: 1.0; }
}
@keyframes pointy-error-shake {
  0%, 100% { filter: drop-shadow(0 2px 6px rgba(0,0,0,0.20)); }
  25% { filter: drop-shadow(-3px 2px 6px rgba(220,38,38,0.45)); }
  75% { filter: drop-shadow(3px 2px 6px rgba(220,38,38,0.45)); }
}
[data-pointy-cursor][data-pointy-state="dock"] {
  animation: pointy-dock-breathe 3s ease-in-out infinite;
}
[data-pointy-pill][data-pointy-state="dock"] {
  animation: pointy-dock-pill-breathe 3s ease-in-out infinite;
}
[data-pointy-cursor][data-pointy-state="error"] {
  animation: pointy-error-shake 280ms ease-in-out 2;
}
`.trim();

let _stylesInjected = false;
function ensureGlobalStyles(): void {
  if (_stylesInjected || typeof document === "undefined") return;
  _stylesInjected = true;
  const style = document.createElement("style");
  style.setAttribute("data-pointy-global-styles", "v3.0");
  style.textContent = POINTY_GLOBAL_STYLES;
  document.head.appendChild(style);
}

interface CursorEntry {
  identity: CursorIdentity;
  /**
   * MotionEngine wraps SpringInterpolator + MinJerkTrajectory. Quyết
   * định strategy ('spring' tracking vs 'trajectory' directed) dựa
   * trên distance + caller intent.
   */
  motion: MotionEngine;
  state: AwarenessState;
  label: string;
  el: SVGSVGElement;
  /** Name pill `<div>` — DOM riêng, không nằm trong cursor SVG. */
  pillEl: HTMLDivElement;
  lastUpdateAt: number;
  // Idle fade timing
  idleFadeAt: number; // performance.now() + ms
}

export interface CursorRegistryOptions {
  /** ``document.body`` by default; override for tests / iframe contexts. */
  parent?: HTMLElement;
  /** Disable rAF loop (tests). When false, callers tick manually. */
  driveRaf?: boolean;
  /** ms of inactivity before a cursor begins to fade to idle opacity. */
  idleAfterMs?: number;
  /** ms of inactivity before a cursor fades out completely. */
  removeAfterMs?: number;
  /** Honour ``prefers-reduced-motion``. Default: true. */
  honourReducedMotion?: boolean;
}

const DEFAULT_OPTIONS: Required<Omit<CursorRegistryOptions, "parent">> = {
  driveRaf: true,
  idleAfterMs: 2000,
  removeAfterMs: 30_000,
  honourReducedMotion: true,
};

export class CursorRegistry {
  private cursors: Map<string, CursorEntry> = new Map();
  private parent: HTMLElement;
  private opts: Required<Omit<CursorRegistryOptions, "parent">>;
  private rafHandle = 0;
  private lastFrameAt = 0;
  private prefersReducedMotion = false;
  private disposed = false;

  constructor(options: CursorRegistryOptions = {}) {
    this.parent =
      options.parent ??
      (typeof document !== "undefined" ? document.body : (null as never));
    this.opts = { ...DEFAULT_OPTIONS, ...options };
    if (this.opts.honourReducedMotion && typeof window !== "undefined" && window.matchMedia) {
      this.prefersReducedMotion = window.matchMedia(
        "(prefers-reduced-motion:reduce)",
      ).matches;
    }
    // v3.0 Battleship: inject global CSS keyframes (dock breathing,
    // error shake) ONCE per page. Idempotent.
    ensureGlobalStyles();
    if (this.opts.driveRaf && typeof requestAnimationFrame !== "undefined") {
      this.startRaf();
    }
  }

  /**
   * Create or update a cursor's target position. If the cursor doesn't
   * exist yet, it appears at the new position with full opacity.
   *
   * @param target Vị trí đích (viewport coords)
   * @param label Optional name pill text (override identity.name)
   * @param options.directed Bắt buộc dùng MinJerkTrajectory (Bezier +
   *   Fitts). Caller (api.ts pointAt) set true cho AI-pointing để có
   *   "deliberate reach" feel. Khi không set: distance ≥ 50px tự
   *   động dùng trajectory; <50px dùng spring tracking.
   * @param options.targetWidth Width của target element (px) cho Fitts
   *   duration scaling. Mặc định 30. Width nhỏ hơn → di chuyển chậm hơn.
   */
  upsert(
    identity: CursorIdentity,
    target: Vec2,
    label?: string,
    options: SetTargetOptions = {},
  ): void {
    if (this.disposed) return;
    const now = performance.now();
    let entry = this.cursors.get(identity.id);
    if (!entry) {
      const el = this.createCursorElement(identity);
      this.parent.appendChild(el);
      const pillEl = this.createNamePillElement(identity, label ?? identity.name);
      this.parent.appendChild(pillEl);
      const motion = new MotionEngine(target, {
        prefersReducedMotion: this.prefersReducedMotion,
      });
      entry = {
        identity,
        motion,
        state: "moving",
        label: label ?? identity.name,
        el,
        pillEl,
        lastUpdateAt: now,
        idleFadeAt: now + this.opts.idleAfterMs,
      };
      this.cursors.set(identity.id, entry);
      this.applyTransform(entry);
      this.applyState(entry);
      return;
    }

    if (label !== undefined && label !== entry.label) {
      entry.label = label;
      this.applyLabel(entry);
    }

    if (this.prefersReducedMotion) {
      // Snap directly — no animation when user prefers reduced motion.
      entry.motion.reset(target.x, target.y);
    } else {
      entry.motion.setTarget(target.x, target.y, options);
      this.setState(entry.identity.id, "moving");
    }
    entry.lastUpdateAt = now;
    entry.idleFadeAt = now + this.opts.idleAfterMs;
  }

  /**
   * Switch a cursor to a new awareness state (idle/moving/pointing/...).
   *
   * State chỉ ảnh hưởng visual treatment (opacity, pill style) — motion
   * strategy được điều khiển qua ``upsert(..., {directed: true})``.
   * Tách biệt 2 concerns này giúp code đơn giản hơn.
   */
  setState(id: string, state: AwarenessState): void {
    const entry = this.cursors.get(id);
    if (!entry || entry.state === state) return;
    entry.state = state;
    this.applyState(entry);
  }

  /** Replace the displayed label for a cursor. */
  setLabel(id: string, label: string): void {
    const entry = this.cursors.get(id);
    if (!entry) return;
    entry.label = label;
    this.applyLabel(entry);
  }

  /** Begin removing a cursor — fades out then detaches from DOM. */
  remove(id: string): void {
    const entry = this.cursors.get(id);
    if (!entry) return;
    entry.state = "gone";
    entry.el.style.opacity = "0";
    entry.pillEl.style.opacity = "0";
    setTimeout(() => {
      if (entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
      if (entry.pillEl.parentNode) entry.pillEl.parentNode.removeChild(entry.pillEl);
      this.cursors.delete(id);
    }, 500);
  }

  /** Manual tick for tests / non-rAF drivers. */
  tick(dt: number): void {
    if (this.disposed) return;
    const now = performance.now();
    for (const entry of this.cursors.values()) {
      entry.motion.tick(dt);
      this.applyTransform(entry);
      this.maybeFade(entry, now);
    }
  }

  /** All cursor ids currently rendered. */
  ids(): string[] {
    return [...this.cursors.keys()];
  }

  /** Remove all cursors and stop the rAF loop. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    this.rafHandle = 0;
    for (const entry of this.cursors.values()) {
      if (entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
      if (entry.pillEl.parentNode) entry.pillEl.parentNode.removeChild(entry.pillEl);
    }
    this.cursors.clear();
  }

  // ────────────────────────────────────────────────────────────────────
  // Private — DOM construction + render loop
  // ────────────────────────────────────────────────────────────────────

  private startRaf(): void {
    this.lastFrameAt = performance.now();
    const frame = (now: number): void => {
      if (this.disposed) return;
      const dt = Math.max(0, (now - this.lastFrameAt) / 1000);
      this.lastFrameAt = now;
      for (const entry of this.cursors.values()) {
        entry.motion.tick(dt);
        this.applyTransform(entry);
        this.maybeFade(entry, now);
      }
      this.rafHandle = requestAnimationFrame(frame);
    };
    this.rafHandle = requestAnimationFrame(frame);
  }

  private createCursorElement(identity: CursorIdentity): SVGSVGElement {
    const svg = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "svg",
    );
    svg.setAttribute("data-pointy-cursor", identity.id);
    svg.setAttribute("data-pointy-state", "moving");
    svg.setAttribute("data-pointy-role", identity.role);
    svg.setAttribute("width", String(CURSOR_VIEWBOX_W));
    svg.setAttribute("height", String(CURSOR_VIEWBOX_H));
    svg.setAttribute("viewBox", `0 0 ${CURSOR_VIEWBOX_W} ${CURSOR_VIEWBOX_H}`);
    svg.setAttribute("aria-hidden", "true"); // a11y — pill carries the name

    Object.assign(svg.style, cursorSvgStyle(), {
      zIndex: String(CURSOR_Z_INDEX),
    });

    // KHÔNG inject CSS keyframes như v2 — chúng dùng `translate` /
    // `transform: scale()` xung đột với JS-driven transform mỗi frame
    // và là gốc rễ của jitter rung lắc. Mọi phản hồi state đều qua
    // attribute thay đổi opacity inline.
    svg.innerHTML = cursorSvgInner(identity);
    return svg;
  }

  private createNamePillElement(
    identity: CursorIdentity,
    label: string,
  ): HTMLDivElement {
    const div = document.createElement("div");
    div.setAttribute("data-pointy-pill", identity.id);
    div.setAttribute("data-pointy-state", "moving");
    div.setAttribute("role", "status");
    div.setAttribute("aria-label", label || identity.name);
    div.textContent = pillLabel(label, identity);

    const pillStyle = namePillStyle(identity);
    Object.assign(div.style, {
      position: "fixed",
      left: "0",
      top: "0",
      zIndex: String(CURSOR_Z_INDEX),
      pointerEvents: "none",
      background: pillStyle.background,
      color: pillStyle.color,
      border: `1px solid ${pillStyle.borderColor}`,
      padding: "3px 9px",
      borderRadius: "999px",
      fontSize: "11px",
      fontWeight: "600",
      fontFamily:
        '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
      letterSpacing: "0.01em",
      lineHeight: "1.2",
      whiteSpace: "nowrap",
      boxShadow: "0 2px 6px rgba(0,0,0,0.18)",
      willChange: "transform, opacity",
      transition: "opacity 200ms ease-out",
      opacity: "1",
    });
    return div;
  }

  /**
   * Áp transform lên cursor + name pill (Wiii Pointy v2.2 — motion alive).
   *
   * Compose 3 thành phần trong CÙNG `transform` string:
   *   translate3d(x, y, 0) rotate(angle) scale(scale)
   *
   * Thứ tự quan trọng — translate trước, rotate/scale sau (rotate sau
   * sẽ xoay quanh điểm đã translate tới). Browser compose đúng thứ tự
   * khai báo, không xung đột vì cùng property.
   *
   * Round x,y về integer pixel diệt sub-pixel shimmer (Liveblocks
   * pattern). Rotation + scale dựa trên velocity vector, không phải
   * position — atan2(vy, vx) cho hướng, hypot(vx, vy) cho speed.
   *
   * Tham khảo: research-cursor-motion-sota-2026-05-06.md
   */
  private applyTransform(entry: CursorEntry): void {
    const pos = entry.motion.position();
    const vel = entry.motion.velocity(); // px/second

    // 1. Position — round integer pixel cho cursor + pill.
    const x = Math.round(pos.x);
    const y = Math.round(pos.y);

    // 2. Velocity-based rotation (Figma "lean into motion" signature).
    // atan2 returns full ±180° range; cursor mặc định "trỏ lên" trong
    // viewBox, tip ở (6, 3) — heading = -90° (up-left). Subtract để
    // align với velocity direction. Clamp ±6° để không quá aggressive.
    const speed = Math.hypot(vel.x, vel.y); // px/second
    let rotation = 0;
    // Threshold 30 px/s — dưới ngưỡng đó coi như cursor đã settle, không
    // áp rotation (tránh shimmer góc khi vận tốc rất nhỏ).
    if (speed > 30 && entry.state !== "gone") {
      const targetDeg = Math.atan2(vel.y, vel.x) * (180 / Math.PI);
      const aligned = clampAngle(targetDeg - 90);
      rotation = clamp(aligned, -6, 6);
    }

    // 3. Velocity-based scale — "weight" feel.
    //   speed in px/s. Mapping [0, 1500] → scale [1.0, 1.10].
    //   1500 px/s ≈ peak velocity của trajectory với D=800 và T=0.5s
    //   theo Flash-Hogan công thức (v_peak = 1.875·D/T = 3000 px/s
    //   cho extremes; 1500 cho moderate moves).
    const scale = 1 + Math.min(speed / 1500, 0.10);

    // 4. Compose into single transform string.
    entry.el.style.transform =
      `translate3d(${x}px, ${y}px, 0) rotate(${rotation.toFixed(2)}deg) scale(${scale.toFixed(3)})`;

    // Pill bám theo cursor với offset cố định, KHÔNG xoay/scale (text
    // dễ đọc nhất khi flat horizontal).
    entry.pillEl.style.transform =
      `translate3d(${x + PILL_OFFSET_X}px, ${y + PILL_OFFSET_Y}px, 0)`;
  }

  /**
   * Phản hồi state qua opacity + nhẹ scale của cursor (KHÔNG động vào
   * `translate` để tránh xung đột với applyTransform). Pill cũng nhận
   * cùng state attribute để CSS có thể style nếu cần.
   */
  private applyState(entry: CursorEntry): void {
    entry.el.setAttribute("data-pointy-state", entry.state);
    entry.pillEl.setAttribute("data-pointy-state", entry.state);

    // State-driven visual qua opacity (không phải position) nên không
    // xung đột với transform JS đang ghi mỗi frame.
    switch (entry.state) {
      case "idle":
        entry.el.style.opacity = "0.5";
        entry.pillEl.style.opacity = "0.5";
        break;
      case "thinking":
        entry.el.style.opacity = "0.85";
        entry.pillEl.style.opacity = "0.7";
        break;
      case "gone":
        entry.el.style.opacity = "0";
        entry.pillEl.style.opacity = "0";
        break;
      case "dock":
        // v3.0 Battleship: cursor docked at corner, breathing pulse via
        // CSS animation (data-pointy-state="dock" hook). Lower opacity
        // (0.7) to indicate "standby"; full opacity when active again.
        entry.el.style.opacity = "0.75";
        entry.pillEl.style.opacity = "0.85";
        break;
      case "returning":
        // v3.0: cursor flying back to dock — full opacity, motion engine
        // handles trajectory. Visual same as moving.
        entry.el.style.opacity = "1";
        entry.pillEl.style.opacity = "0.9";
        break;
      default: // moving / pointing / clicking
        entry.el.style.opacity = "1";
        entry.pillEl.style.opacity = "1";
    }
  }

  private applyLabel(entry: CursorEntry): void {
    const text = pillLabel(entry.label, entry.identity);
    entry.pillEl.textContent = text;
    entry.pillEl.setAttribute("aria-label", text);
  }

  private maybeFade(entry: CursorEntry, now: number): void {
    if (entry.state === "gone") return;
    // v3.0 Battleship: docked cursors are persistent — never auto-remove,
    // never auto-idle. They live at dock position breathing-pulse cho
    // tới khi caller explicit dispose hoặc state đổi sang moving.
    if (entry.state === "dock") return;
    const ageMs = now - entry.lastUpdateAt;
    if (ageMs > this.opts.removeAfterMs) {
      this.remove(entry.identity.id);
      return;
    }
    if (ageMs > this.opts.idleAfterMs && entry.state === "moving") {
      this.setState(entry.identity.id, "idle");
    }
  }
}

/** Clamp số trong [min, max]. */
function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

/**
 * Normalize góc về (-180, 180] để clamp ±6° không bị wrap qua ±180°.
 * Ví dụ: targetDeg=170, aligned (no normalize) = 170-90=80 → clamp 6.
 * Nhưng nếu targetDeg=-170, aligned=-260 → cần wrap về +100 trước clamp.
 */
function clampAngle(deg: number): number {
  let d = deg % 360;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return d;
}
