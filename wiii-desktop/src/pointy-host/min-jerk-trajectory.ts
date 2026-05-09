/**
 * Minimum-jerk trajectory + quadratic Bezier path (Wiii Pointy v2.3).
 *
 * Mô hình toán học chuẩn cho cursor "directed move" (AI điểm target):
 *
 * 1. **Flash & Hogan 1985** — minimum-jerk velocity profile (bell-shaped,
 *    peak ở giữa đường đi). Đây là cách cánh tay người THỰC SỰ di
 *    chuyển khi reach một mục tiêu cụ thể (motor control research).
 *
 * 2. **Fitts's Law (1954)** — duration scale theo log₂(D/W + 1).
 *    Distance gấp 10 chỉ cần ~3.3× thời gian, không tuyến tính.
 *
 * 3. **Quadratic Bezier curve** — đường cung nhẹ qua control point lệch
 *    perpendicular 8% distance. Cánh tay người không đi thẳng tuyệt đối.
 *
 * Khác với spring (Hooke's law) — spring có velocity profile EXPONENTIAL
 * DECAY (peak ngay lúc bắt đầu). Min-jerk có velocity profile BELL (peak
 * ở giữa). Min-jerk = chuẩn vàng cho "deliberate reach" motion.
 *
 * Tham khảo: ``research-cursor-motion-math-2026-05-06.md``
 */

export interface Vec2 {
  x: number;
  y: number;
}

export interface MinJerkOptions {
  /**
   * Duration override (giây). Nếu omit → tính bằng Fitts's Law từ
   * distance + targetWidth.
   */
  duration?: number;
  /**
   * Width của target (px) cho Fitts's Law. Mặc định 30px (typical
   * button). Nhỏ hơn → di chuyển chậm hơn (cần precision cao).
   */
  targetWidth?: number;
  /**
   * Sag của Bezier control point (% distance). 0 = đường thẳng, 0.08 =
   * arc nhẹ tự nhiên (Steve Ruiz perfect-cursors default), >0.15 =
   * vòng cung quá lớn giả tạo. Mặc định 0.08.
   */
  sag?: number;
  /**
   * Initial velocity (px/giây) tại điểm start. Khi switch từ spring
   * sang min-jerk, dùng velocity hiện tại để tránh jerky transition.
   * Mặc định {0, 0}.
   *
   * Note: min-jerk classic giả định v(0)=0, v(T)=0. Truyền initial
   * velocity ≠ 0 sẽ vi phạm boundary condition; trajectory vẫn đi tới
   * end nhưng đầu đường đi không hoàn toàn smooth. Dùng cẩn thận.
   */
  initialVelocity?: Vec2;
}

// Fitts's Law parameters cho UI cursor (calibrated cho Liveblocks-feel).
// T = a + b · log₂(D/W + 1)
const FITTS_INTERCEPT_MS = 100; // a — overhead phản ứng
const FITTS_SLOPE_MS = 80;       // b — slope/efficiency
const FITTS_DEFAULT_W_PX = 30;   // typical button width

const DEFAULT_SAG = 0.08;
const MIN_DURATION_S = 0.18; // 180ms — clamp minimum (close target)
const MAX_DURATION_S = 0.80; // 800ms — clamp maximum (very long)

/**
 * Compute movement duration via Fitts's Law.
 *
 * @param distancePx khoảng cách euclidean từ start tới end
 * @param targetWidthPx chiều rộng của target (cho precision scaling)
 * @returns duration (giây), clamped trong [0.18, 0.80]
 */
export function fittsDuration(
  distancePx: number,
  targetWidthPx: number = FITTS_DEFAULT_W_PX,
): number {
  const D = Math.max(0, distancePx);
  const W = Math.max(8, targetWidthPx); // floor 8px để log₂ không nổ
  const indexOfDifficulty = Math.log2(D / W + 1);
  const ms = FITTS_INTERCEPT_MS + FITTS_SLOPE_MS * indexOfDifficulty;
  const seconds = ms / 1000;
  return Math.max(MIN_DURATION_S, Math.min(seconds, MAX_DURATION_S));
}

/**
 * Min-jerk timing function (Flash-Hogan 1985 5th-order polynomial).
 *
 * Maps linear time u ∈ [0, 1] to position fraction s ∈ [0, 1] với
 * bell-shaped velocity profile. Boundary conditions:
 *   s(0) = 0, s(1) = 1
 *   s'(0) = 0, s'(1) = 0  (smooth start/stop)
 *   s''(0) = 0, s''(1) = 0 (no jerk at endpoints)
 */
export function minJerkS(u: number): number {
  if (u <= 0) return 0;
  if (u >= 1) return 1;
  const u2 = u * u;
  const u3 = u2 * u;
  const u4 = u3 * u;
  const u5 = u4 * u;
  return 10 * u3 - 15 * u4 + 6 * u5;
}

/**
 * Đạo hàm bậc 1 của min-jerk timing — dùng để tính velocity.
 *   s'(u) = 30u² - 60u³ + 30u⁴
 *
 * Peak at u=0.5: s'(0.5) = 1.875.
 * Velocity at time t = (B'(u) · s'(u)) / T  (chain rule)
 */
export function minJerkSDerivative(u: number): number {
  if (u <= 0 || u >= 1) return 0;
  const u2 = u * u;
  const u3 = u2 * u;
  const u4 = u3 * u;
  return 30 * u2 - 60 * u3 + 30 * u4;
}

/**
 * Compute Bezier control point — midpoint offset perpendicular to
 * motion direction. Tạo arc nhẹ thay vì đường thẳng.
 *
 * Direction nhất quán: perpendicular = (-dy/d, dx/d) (rotated 90° CCW)
 * → cursor luôn cong về một phía nhất định, không "rung" qua lại.
 */
export function bezierControlPoint(
  start: Vec2,
  end: Vec2,
  sag: number = DEFAULT_SAG,
): Vec2 {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 0.001) {
    return { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
  }
  const mx = (start.x + end.x) / 2;
  const my = (start.y + end.y) / 2;
  // Unit perpendicular (rotated 90° CCW from motion direction).
  const px = -dy / distance;
  const py = dx / distance;
  const offset = distance * sag;
  return { x: mx + px * offset, y: my + py * offset };
}

/**
 * Quadratic Bezier evaluation at parameter t ∈ [0, 1].
 *   B(t) = (1-t)² · P₀ + 2(1-t)t · P₁ + t² · P₂
 */
export function bezierAt(t: number, p0: Vec2, p1: Vec2, p2: Vec2): Vec2 {
  const u = 1 - t;
  const u2 = u * u;
  const t2 = t * t;
  const ut2 = 2 * u * t;
  return {
    x: u2 * p0.x + ut2 * p1.x + t2 * p2.x,
    y: u2 * p0.y + ut2 * p1.y + t2 * p2.y,
  };
}

/**
 * Bezier tangent vector at parameter t (đạo hàm B'(t) theo t).
 *   B'(t) = 2(1-t)(P₁ - P₀) + 2t(P₂ - P₁)
 *
 * Magnitude của tangent = velocity per unit-t. Combined với min-jerk
 * timing s'(u), velocity tại thời điểm thực t_real:
 *   v(t_real) = B'(s(u_lin)) · s'(u_lin) / T
 */
export function bezierTangentAt(
  t: number,
  p0: Vec2,
  p1: Vec2,
  p2: Vec2,
): Vec2 {
  const u = 1 - t;
  return {
    x: 2 * u * (p1.x - p0.x) + 2 * t * (p2.x - p1.x),
    y: 2 * u * (p1.y - p0.y) + 2 * t * (p2.y - p1.y),
  };
}

/**
 * MinJerkTrajectory — parametric trajectory từ start tới end qua quỹ
 * đạo cung Bezier với timing min-jerk. Dùng cho "directed moves" (AI
 * điểm target cụ thể).
 *
 * Khác với SpringInterpolator (state-based, cập nhật target bất kỳ
 * lúc nào): trajectory này có duration cố định, không thể "redirect
 * mid-flight" mượt. Caller phải tạo trajectory MỚI khi target đổi.
 *
 * Usage:
 *   const traj = new MinJerkTrajectory(currentPos, targetPos, opts);
 *   while (!traj.isDone()) {
 *     const { position, velocity } = traj.tick(dt);
 *     renderCursor(position);
 *   }
 */
export class MinJerkTrajectory {
  private readonly start: Vec2;
  private readonly end: Vec2;
  private readonly control: Vec2;
  private readonly duration: number; // giây
  private elapsed: number = 0;
  private done: boolean = false;
  // Cached current state — tránh recompute trong velocity()/position()
  // calls liên tiếp trong cùng frame.
  private currentPos: Vec2;
  private currentVel: Vec2 = { x: 0, y: 0 };

  constructor(start: Vec2, end: Vec2, options: MinJerkOptions = {}) {
    this.start = { ...start };
    this.end = { ...end };
    this.currentPos = { ...start };

    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const distance = Math.hypot(dx, dy);

    this.duration =
      options.duration !== undefined
        ? Math.max(MIN_DURATION_S, options.duration)
        : fittsDuration(distance, options.targetWidth);

    const sag = options.sag !== undefined ? options.sag : DEFAULT_SAG;
    this.control = bezierControlPoint(this.start, this.end, sag);

    // Trajectory degenerate (start ≈ end) → mark done immediately.
    if (distance < 0.5) {
      this.done = true;
    }
  }

  /**
   * Advance trajectory by dt seconds. Returns position + velocity at
   * the new time. Idempotent once done.
   */
  tick(dt: number): { position: Vec2; velocity: Vec2; done: boolean } {
    if (this.done) {
      return {
        position: { ...this.currentPos },
        velocity: { x: 0, y: 0 },
        done: true,
      };
    }

    this.elapsed += dt;
    const u_linear = this.elapsed / this.duration;

    if (u_linear >= 1) {
      // Snap to end at completion. Min-jerk s'(1)=0 đảm bảo velocity ≈ 0.
      this.currentPos = { ...this.end };
      this.currentVel = { x: 0, y: 0 };
      this.done = true;
      return {
        position: { ...this.currentPos },
        velocity: { x: 0, y: 0 },
        done: true,
      };
    }

    // Step 1: linear time u_lin → min-jerk parameter u_mj
    const u_mj = minJerkS(u_linear);

    // Step 2: position via Bezier at u_mj
    this.currentPos = bezierAt(u_mj, this.start, this.control, this.end);

    // Step 3: velocity via chain rule
    //   v(t) = B'(s(u_lin)) · s'(u_lin) / T
    const tangent = bezierTangentAt(
      u_mj,
      this.start,
      this.control,
      this.end,
    );
    const sPrime = minJerkSDerivative(u_linear);
    const scale = sPrime / this.duration;
    this.currentVel = {
      x: tangent.x * scale,
      y: tangent.y * scale,
    };

    return {
      position: { ...this.currentPos },
      velocity: { ...this.currentVel },
      done: false,
    };
  }

  /** Current position (last computed by tick). */
  position(): Vec2 {
    return { ...this.currentPos };
  }

  /** Current velocity (last computed by tick). */
  velocity(): Vec2 {
    return { ...this.currentVel };
  }

  /** True after trajectory has reached end. */
  isDone(): boolean {
    return this.done;
  }

  /** Total duration of trajectory (seconds). */
  totalDuration(): number {
    return this.duration;
  }

  /** Progress fraction t/T ∈ [0, 1]. */
  progress(): number {
    if (this.done) return 1;
    return Math.min(1, this.elapsed / this.duration);
  }
}
