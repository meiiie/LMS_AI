/**
 * MotionEngine — chiến lược motion switcher (Wiii Pointy v2.3).
 *
 * Wraps SpringInterpolator + MinJerkTrajectory để chọn đúng mô hình
 * motion cho từng tình huống:
 *
 * - **Tracking mode** (small continuous updates) → SpringInterpolator.
 *   Phù hợp cho: Soul Bridge presence streaming, mouse-follow, các
 *   cập nhật vị trí liên tục từ network. Spring không có "duration"
 *   nên redirect mid-flight smooth.
 *
 * - **Directed mode** (deliberate AI move tới target cụ thể) →
 *   MinJerkTrajectory + Bezier. Phù hợp cho: ``tool_pointy_show``
 *   (AI đang điểm 1 nút cụ thể), multi-step tour. Min-jerk có bell
 *   velocity profile + Fitts-scaled duration + arc path.
 *
 * **Switching logic** (trong setTarget):
 *
 *   if explicit { directed: true } → directed
 *   else if distance >= 50px → directed (auto-detect deliberate jump)
 *   else → tracking (small continuous update)
 *
 * **Continuity**: khi MinJerkTrajectory hoàn tất (t >= T), engine
 * transfer position + velocity sang spring (velocity ≈ 0 do min-jerk
 * boundary condition s'(1)=0). Spring sẽ handle micro-adjustments
 * sau đó cho tới khi target đổi.
 *
 * Tham khảo: ``research-cursor-motion-math-2026-05-06.md``
 */

import { SpringInterpolator, SPRING_PRESETS, type Vec2 } from "./interpolator";
import { MinJerkTrajectory, type MinJerkOptions } from "./min-jerk-trajectory";

export interface MotionEngineOptions {
  /** Distance threshold (px) trên đó setTarget không-flag tự động dùng directed. */
  autoDirectedThresholdPx?: number;
  /**
   * Honour ``prefers-reduced-motion``: snap thẳng tới target, không
   * spring/trajectory animation.
   */
  prefersReducedMotion?: boolean;
}

export interface SetTargetOptions {
  /**
   * Bắt buộc dùng directed mode (min-jerk + Bezier) bất kể distance.
   * Caller (api.ts pointAt) set true cho AI-pointing để có "deliberate
   * reach" feel.
   */
  directed?: boolean;
  /** Width of target (cho Fitts duration scaling). Default 30px. */
  targetWidth?: number;
}

const DEFAULT_AUTO_DIRECTED_THRESHOLD = 50; // px

export type MotionStrategy = "spring" | "trajectory" | "snap";

export class MotionEngine {
  private spring: SpringInterpolator;
  private trajectory: MinJerkTrajectory | null = null;
  private strategy: MotionStrategy = "spring";
  private opts: Required<MotionEngineOptions>;

  // Cache last position/velocity từ trajectory để spring nhận continuity.
  private currentPos: Vec2;
  private currentVel: Vec2 = { x: 0, y: 0 };

  constructor(initialPos: Vec2 = { x: 0, y: 0 }, options: MotionEngineOptions = {}) {
    this.spring = new SpringInterpolator(SPRING_PRESETS.default);
    this.spring.reset(initialPos.x, initialPos.y);
    this.currentPos = { ...initialPos };
    this.opts = {
      autoDirectedThresholdPx:
        options.autoDirectedThresholdPx ?? DEFAULT_AUTO_DIRECTED_THRESHOLD,
      prefersReducedMotion: options.prefersReducedMotion ?? false,
    };
  }

  /**
   * Snap immediately to a position (zero velocity, no animation). Dùng
   * khi cursor mới spawn — không "fly in" từ origin.
   */
  reset(x: number, y: number): void {
    this.spring.reset(x, y);
    this.trajectory = null;
    this.strategy = "spring";
    this.currentPos = { x, y };
    this.currentVel = { x: 0, y: 0 };
  }

  /**
   * Set new target. Strategy được chọn dựa trên distance + flag.
   */
  setTarget(x: number, y: number, options: SetTargetOptions = {}): void {
    if (this.opts.prefersReducedMotion) {
      // Reduced motion: snap thẳng, không animation.
      this.reset(x, y);
      this.strategy = "snap";
      return;
    }

    const dx = x - this.currentPos.x;
    const dy = y - this.currentPos.y;
    const distance = Math.hypot(dx, dy);

    // Distance < 1px → no-op (avoid spurious trajectory creation).
    if (distance < 0.5) return;

    const wantsDirected =
      options.directed === true ||
      distance >= this.opts.autoDirectedThresholdPx;

    if (wantsDirected) {
      // Tạo MinJerkTrajectory mới từ current position tới target.
      // KHÔNG transfer velocity — min-jerk classical giả định v(0)=0.
      // Trade-off: nếu cursor đang chạy nhanh và đổi target, sẽ có
      // "soft restart" thay vì redirect mượt. Trong thực tế, distance
      // ≥50px thường đến từ AI tool call, cursor đang idle hoặc gần
      // idle, nên trade-off này chấp nhận được.
      const minJerkOpts: MinJerkOptions = {
        targetWidth: options.targetWidth,
      };
      this.trajectory = new MinJerkTrajectory(
        this.currentPos,
        { x, y },
        minJerkOpts,
      );
      this.strategy = "trajectory";
    } else {
      // Small continuous update → tracking spring.
      if (this.strategy !== "spring") {
        // Switching từ trajectory → spring. Reset spring tới current
        // position + velocity để continuity.
        this.spring.reset(this.currentPos.x, this.currentPos.y);
        this.trajectory = null;
        this.strategy = "spring";
      }
      this.spring.setTarget(x, y);
    }
  }

  /**
   * Advance simulation by dt seconds. Returns interpolated position +
   * velocity. Always safe to call (idempotent when settled).
   */
  tick(dt: number): { position: Vec2; velocity: Vec2 } {
    if (this.strategy === "trajectory" && this.trajectory) {
      const result = this.trajectory.tick(dt);
      this.currentPos = result.position;
      this.currentVel = result.velocity;
      if (result.done) {
        // Trajectory hoàn tất → transition về spring cho micro-adjustments.
        // Velocity ≈ 0 do min-jerk s'(1)=0, nên spring start với 0 vel.
        this.spring.reset(result.position.x, result.position.y);
        this.trajectory = null;
        this.strategy = "spring";
      }
      return {
        position: { ...result.position },
        velocity: { ...result.velocity },
      };
    }

    // Spring path
    const pos = this.spring.tick(dt);
    // Velocity = (current - last) / dt — but spring object doesn't
    // expose velocity directly via tick. Get it from internal state.
    const vel = this.spring.velocity();
    this.currentPos = pos;
    // Spring velocity is per-frame at 60Hz reference; convert to per-second
    // by multiplying by 60 (approximate — spring uses normalized step).
    this.currentVel = { x: vel.x * 60, y: vel.y * 60 };
    return {
      position: { ...pos },
      velocity: { ...this.currentVel },
    };
  }

  /** Current position (read-only). */
  position(): Vec2 {
    return { ...this.currentPos };
  }

  /** Current velocity in px/second. */
  velocity(): Vec2 {
    return { ...this.currentVel };
  }

  /** Active motion strategy ("spring", "trajectory", or "snap"). */
  currentStrategy(): MotionStrategy {
    return this.strategy;
  }

  /** True when motion has settled (no more movement expected). */
  isSettled(): boolean {
    if (this.strategy === "trajectory") {
      return this.trajectory ? this.trajectory.isDone() : true;
    }
    return this.spring.isSettled();
  }
}
