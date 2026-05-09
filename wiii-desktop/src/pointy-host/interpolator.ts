/**
 * Spring-physics cursor interpolator (Wiii Pointy v2).
 *
 * Replaces rigid CSS keyframe animation with semi-implicit Euler spring
 * integration. Each cursor has a current (x, y) position, a velocity
 * vector, and a target. Each frame, a spring force pulls current toward
 * target; velocity carries momentum, so direction changes mid-flight
 * feel natural — exactly the technique Figma / Liveblocks / Canva use.
 *
 * Why spring, not keyframes?
 *
 * - Keyframes precompute the path. Mid-flight redirects require cancel
 *   + restart, producing visible glitches.
 * - Keyframes have fixed duration. Short distances feel sluggish, long
 *   distances feel rushed. Spring naturally scales: a 50px move settles
 *   in ~200ms, a 500px move in ~600ms, with the same physics constants.
 * - Real cursors have momentum. Spring continuity makes the cursor feel
 *   like it has weight — the first SOTA detail every multiplayer
 *   cursor ships.
 *
 * Tuning notes:
 *
 * - ``stiffness 0.18, damping 0.85`` is the default — feels like the
 *   Liveblocks / Figma "snappy but settled" curve.
 * - Lower stiffness (0.08) feels heavy / lazy.
 * - Higher stiffness (0.35) feels twitchy.
 * - Damping above 0.9 over-damps (no overshoot, settles fast).
 * - Damping below 0.75 starts to bounce visibly.
 *
 * Anti-pattern: do NOT call ``tick()`` from ``setInterval``. Always drive
 * from ``requestAnimationFrame`` so the integrator stays in sync with
 * display refresh and pauses cleanly in background tabs.
 *
 * Reference research: ``research-multiplayer-cursors-sota-2026-05-06.md``
 */

export interface SpringConfig {
  /** Force strength pulling current toward target. 0.05 (sluggish) — 0.4 (snappy). */
  stiffness: number;
  /** Velocity friction per frame. 0.7 (bouncy) — 0.95 (critically damped). */
  damping: number;
  /** Below this threshold (px), snap to target and zero velocity to avoid jitter. */
  settleThreshold: number;
}

export const SPRING_PRESETS = {
  /**
   * Default — Liveblocks/Figma signature feel. v2.2 quay lại từ 0.92
   * (over-damped, lờ đờ) về 0.86 + bump stiffness 0.18 → 0.20 cho
   * pursue snappy hơn. Trade-off: overshoot ~6px (vẫn dưới ngưỡng
   * "lúng túng" của 0.85=12px). Đây là điều cursor "thở" — pure
   * critical damping cảm giác chết.
   *
   * Settle threshold 0.4 → 0.1: soft settle thay vì hard snap. rAF
   * vẫn dừng vì spring tự suy yếu qua damping, nhưng cursor approach
   * target asymptotically.
   */
  default: { stiffness: 0.20, damping: 0.86, settleThreshold: 0.1 } as SpringConfig,
  /** Snappy — AI-assistant energy, phản ứng nhanh nhưng vẫn settle nhẹ. */
  snappy: { stiffness: 0.30, damping: 0.84, settleThreshold: 0.1 } as SpringConfig,
  /** Heavy — cursor "trọng lượng", smooth deceleration cho thinking. */
  heavy: { stiffness: 0.10, damping: 0.91, settleThreshold: 0.1 } as SpringConfig,
  /**
   * Critical — CHÍNH XÁC tuyệt đối trên target, không overshoot. Dùng
   * khi cursor đang trong state 'pointing' và phải đậu đúng trên nút
   * được trỏ. Damping 0.95 vs default 0.86 → cảm giác "chuyên nghiệp"
   * thay vì "vui tươi".
   */
  critical: { stiffness: 0.22, damping: 0.95, settleThreshold: 0.1 } as SpringConfig,
} as const;

export interface Vec2 {
  x: number;
  y: number;
}

export class SpringInterpolator {
  private currentX = 0;
  private currentY = 0;
  private velocityX = 0;
  private velocityY = 0;
  private targetX = 0;
  private targetY = 0;
  private settled = true;
  private config: SpringConfig;

  constructor(config: SpringConfig = SPRING_PRESETS.default) {
    this.config = { ...config };
  }

  /** Snap immediately to a position with zero velocity. */
  reset(x: number, y: number): void {
    this.currentX = x;
    this.currentY = y;
    this.targetX = x;
    this.targetY = y;
    this.velocityX = 0;
    this.velocityY = 0;
    this.settled = true;
  }

  /** Set the target the spring should pursue. Cursor will smoothly redirect. */
  setTarget(x: number, y: number): void {
    if (x === this.targetX && y === this.targetY) return;
    this.targetX = x;
    this.targetY = y;
    this.settled = false;
  }

  /** Replace the spring config (e.g., switch to "heavy" for thinking state). */
  setConfig(config: SpringConfig): void {
    this.config = { ...config };
  }

  /**
   * Advance the simulation by ``dt`` seconds. Returns the position to
   * render this frame. Idempotent when settled.
   */
  tick(dt: number): Vec2 {
    if (this.settled) {
      return { x: this.currentX, y: this.currentY };
    }

    // Normalise dt to a 60Hz reference step. Clamp to avoid huge jumps
    // when the tab was backgrounded.
    const dtNorm = Math.min(dt, 1 / 30) * 60;

    const dx = this.targetX - this.currentX;
    const dy = this.targetY - this.currentY;

    // Spring force: F = stiffness * displacement.
    const fx = dx * this.config.stiffness * dtNorm;
    const fy = dy * this.config.stiffness * dtNorm;

    // Apply damping then add force. Use Math.pow so damping behaves
    // consistently across variable frame rates.
    const dampingPerFrame = Math.pow(this.config.damping, dtNorm);
    this.velocityX = this.velocityX * dampingPerFrame + fx;
    this.velocityY = this.velocityY * dampingPerFrame + fy;

    this.currentX += this.velocityX;
    this.currentY += this.velocityY;

    // Settle when close enough — avoids sub-pixel jitter and lets us
    // skip work until the next setTarget() call.
    const distSq = dx * dx + dy * dy;
    const speedSq = this.velocityX * this.velocityX + this.velocityY * this.velocityY;
    const threshold = this.config.settleThreshold;
    if (distSq < threshold * threshold && speedSq < threshold * threshold) {
      this.currentX = this.targetX;
      this.currentY = this.targetY;
      this.velocityX = 0;
      this.velocityY = 0;
      this.settled = true;
    }

    return { x: this.currentX, y: this.currentY };
  }

  /** True when the cursor has reached its target and stopped moving. */
  isSettled(): boolean {
    return this.settled;
  }

  /** Current rendered position. */
  position(): Vec2 {
    return { x: this.currentX, y: this.currentY };
  }

  /** Current velocity vector (px/frame at 60Hz). Useful for motion-blur. */
  velocity(): Vec2 {
    return { x: this.velocityX, y: this.velocityY };
  }

  /** Distance to current target. Useful for caption-fade timing. */
  distanceToTarget(): number {
    const dx = this.targetX - this.currentX;
    const dy = this.targetY - this.currentY;
    return Math.sqrt(dx * dx + dy * dy);
  }
}
