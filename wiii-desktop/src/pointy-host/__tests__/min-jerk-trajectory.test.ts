/**
 * Tests for MinJerkTrajectory + helpers — pin down math correctness.
 *
 * Flash-Hogan 1985 + Fitts 1954 mathematical properties:
 *   s(0) = 0, s(1) = 1
 *   s'(0) = 0, s'(1) = 0
 *   peak velocity at u=0.5 = 1.875·D/T
 *   Bezier B(0) = P₀, B(1) = P₂
 *   Fitts T = a + b·log₂(D/W + 1)
 */

import { describe, it, expect } from "vitest";
import {
  MinJerkTrajectory,
  bezierAt,
  bezierControlPoint,
  bezierTangentAt,
  fittsDuration,
  minJerkS,
  minJerkSDerivative,
} from "../min-jerk-trajectory";

const FRAME_60 = 1 / 60;

describe("min-jerk timing function (Flash-Hogan 1985)", () => {
  it("boundary conditions: s(0) = 0, s(1) = 1", () => {
    expect(minJerkS(0)).toBe(0);
    expect(minJerkS(1)).toBe(1);
  });

  it("monotonically increasing on [0, 1]", () => {
    let prev = -1;
    for (let i = 0; i <= 100; i++) {
      const u = i / 100;
      const s = minJerkS(u);
      expect(s).toBeGreaterThanOrEqual(prev);
      prev = s;
    }
  });

  it("clamps to [0, 1] outside the unit interval", () => {
    expect(minJerkS(-0.5)).toBe(0);
    expect(minJerkS(2)).toBe(1);
  });

  it("derivative s'(0) = 0 and s'(1) = 0 (smooth start/stop)", () => {
    expect(minJerkSDerivative(0)).toBe(0);
    expect(minJerkSDerivative(1)).toBe(0);
  });

  it("peak velocity at u=0.5 is exactly 1.875 (Flash-Hogan)", () => {
    // s'(0.5) = 30·0.25 - 60·0.125 + 30·0.0625 = 7.5 - 7.5 + 1.875 = 1.875
    expect(minJerkSDerivative(0.5)).toBeCloseTo(1.875, 6);
  });

  it("symmetric: s'(u) = s'(1-u)", () => {
    for (const u of [0.1, 0.2, 0.3, 0.4]) {
      expect(minJerkSDerivative(u)).toBeCloseTo(
        minJerkSDerivative(1 - u),
        6,
      );
    }
  });

  it("s(0.5) = 0.5 (50% time = 50% distance — symmetry)", () => {
    expect(minJerkS(0.5)).toBeCloseTo(0.5, 6);
  });
});

describe("Fitts's Law duration", () => {
  it("clamps to MIN duration even with zero distance", () => {
    expect(fittsDuration(0)).toBeCloseTo(0.18, 3);
  });

  it("clamps to MAX duration for very large distances", () => {
    expect(fittsDuration(100_000)).toBeCloseTo(0.80, 3);
  });

  it("D=30, W=30 → log₂(2) = 1 → T = 100 + 80·1 = 180ms (≥ min clamp 180)", () => {
    expect(fittsDuration(30, 30)).toBeCloseTo(0.18, 2);
  });

  it("D=300 gives medium duration ~376ms", () => {
    // T = 100 + 80·log₂(11) ≈ 100 + 80·3.46 ≈ 377
    const t = fittsDuration(300, 30);
    expect(t * 1000).toBeGreaterThan(350);
    expect(t * 1000).toBeLessThan(400);
  });

  it("longer distance produces longer duration (monotonic)", () => {
    expect(fittsDuration(50)).toBeLessThanOrEqual(fittsDuration(200));
    expect(fittsDuration(200)).toBeLessThanOrEqual(fittsDuration(800));
  });

  it("smaller target width → longer duration (precision needed)", () => {
    const wideTarget = fittsDuration(300, 100);
    const narrowTarget = fittsDuration(300, 10);
    expect(narrowTarget).toBeGreaterThan(wideTarget);
  });
});

describe("Quadratic Bezier", () => {
  const p0 = { x: 0, y: 0 };
  const p1 = { x: 50, y: 100 };
  const p2 = { x: 100, y: 0 };

  it("B(0) = P₀ (boundary)", () => {
    const b = bezierAt(0, p0, p1, p2);
    expect(b.x).toBeCloseTo(p0.x, 6);
    expect(b.y).toBeCloseTo(p0.y, 6);
  });

  it("B(1) = P₂ (boundary)", () => {
    const b = bezierAt(1, p0, p1, p2);
    expect(b.x).toBeCloseTo(p2.x, 6);
    expect(b.y).toBeCloseTo(p2.y, 6);
  });

  it("B(0.5) is the de Casteljau midpoint", () => {
    // For quadratic Bezier: B(0.5) = (P₀ + 2·P₁ + P₂) / 4
    // With p0={0,0}, p1={50,100}, p2={100,0}:
    //   x = (0 + 100 + 100) / 4 = 50
    //   y = (0 + 200 + 0) / 4 = 50
    const b = bezierAt(0.5, p0, p1, p2);
    expect(b.x).toBeCloseTo(50, 6);
    expect(b.y).toBeCloseTo(50, 6);
  });

  it("tangent at t=0 points from P₀ toward P₁", () => {
    const tan = bezierTangentAt(0, p0, p1, p2);
    // B'(0) = 2·(P₁ - P₀) = (100, 200)
    expect(tan.x).toBeCloseTo(100, 6);
    expect(tan.y).toBeCloseTo(200, 6);
  });

  it("tangent at t=1 points from P₁ toward P₂", () => {
    const tan = bezierTangentAt(1, p0, p1, p2);
    // B'(1) = 2·(P₂ - P₁) = (100, -200)
    expect(tan.x).toBeCloseTo(100, 6);
    expect(tan.y).toBeCloseTo(-200, 6);
  });
});

describe("Bezier control point computation (perpendicular sag)", () => {
  it("midpoint with zero sag = exact midpoint", () => {
    const cp = bezierControlPoint({ x: 0, y: 0 }, { x: 100, y: 0 }, 0);
    expect(cp.x).toBe(50);
    expect(cp.y).toBe(0);
  });

  it("perpendicular offset for horizontal motion (CCW perpendicular)", () => {
    // Motion is +X, perpendicular CCW is +Y... wait, no.
    // The implementation computes: px = -dy/d, py = dx/d.
    // For motion (100, 0): dx=100, dy=0 → px = 0, py = 1 → offset is +Y.
    const cp = bezierControlPoint({ x: 0, y: 0 }, { x: 100, y: 0 }, 0.1);
    expect(cp.x).toBeCloseTo(50, 4);
    expect(cp.y).toBeCloseTo(10, 4); // 100 * 0.1 = 10
  });

  it("perpendicular offset for vertical motion", () => {
    // Motion (0, 100): dx=0, dy=100 → px = -1, py = 0 → offset is -X.
    const cp = bezierControlPoint({ x: 0, y: 0 }, { x: 0, y: 100 }, 0.1);
    expect(cp.x).toBeCloseTo(-10, 4);
    expect(cp.y).toBeCloseTo(50, 4);
  });

  it("zero distance → returns midpoint without crashing", () => {
    const cp = bezierControlPoint({ x: 5, y: 5 }, { x: 5, y: 5 }, 0.1);
    expect(Number.isFinite(cp.x)).toBe(true);
    expect(Number.isFinite(cp.y)).toBe(true);
  });
});

describe("MinJerkTrajectory integration", () => {
  it("starts at origin and progresses toward end", () => {
    const traj = new MinJerkTrajectory({ x: 0, y: 0 }, { x: 200, y: 0 });
    expect(traj.isDone()).toBe(false);
    const p0 = traj.position();
    expect(p0.x).toBe(0);
    expect(p0.y).toBe(0);

    // Halfway through duration, position should have advanced past 0
    // and not yet reached end.
    const halfDuration = traj.totalDuration() / 2;
    let elapsed = 0;
    while (elapsed < halfDuration) {
      traj.tick(FRAME_60);
      elapsed += FRAME_60;
    }
    const mid = traj.position();
    expect(mid.x).toBeGreaterThan(0);
    expect(mid.x).toBeLessThan(200);
  });

  it("converges to exact end position when complete", () => {
    const traj = new MinJerkTrajectory({ x: 10, y: 20 }, { x: 510, y: 220 });
    while (!traj.isDone()) {
      traj.tick(FRAME_60);
    }
    const final = traj.position();
    expect(final.x).toBeCloseTo(510, 1);
    expect(final.y).toBeCloseTo(220, 1);
  });

  it("velocity at start and end is approximately zero (Flash-Hogan)", () => {
    const traj = new MinJerkTrajectory({ x: 0, y: 0 }, { x: 500, y: 0 });
    // First tick after start
    const r1 = traj.tick(FRAME_60);
    // Velocity should be small at the very start (s'(0)=0).
    // After 1 frame at 60Hz, u_lin ≈ 1/60/T ≈ small → s'(small) is small.
    expect(Math.abs(r1.velocity.x)).toBeLessThan(50);

    // Run to completion
    while (!traj.isDone()) traj.tick(FRAME_60);
    const final = traj.position();
    const vel = traj.velocity();
    expect(final.x).toBeCloseTo(500, 1);
    expect(vel.x).toBeCloseTo(0, 1);
    expect(vel.y).toBeCloseTo(0, 1);
  });

  it("velocity peaks roughly at midpoint of trajectory", () => {
    const traj = new MinJerkTrajectory({ x: 0, y: 0 }, { x: 600, y: 0 });
    const T = traj.totalDuration();
    let maxSpeed = 0;
    let timeAtMax = 0;
    let elapsed = 0;
    while (!traj.isDone()) {
      const r = traj.tick(FRAME_60);
      const speed = Math.hypot(r.velocity.x, r.velocity.y);
      if (speed > maxSpeed) {
        maxSpeed = speed;
        timeAtMax = elapsed;
      }
      elapsed += FRAME_60;
    }
    const u_at_peak = timeAtMax / T;
    // Peak should be near u=0.5 (within 15% tolerance for frame quantization).
    expect(u_at_peak).toBeGreaterThan(0.35);
    expect(u_at_peak).toBeLessThan(0.65);
  });

  it("peak velocity ≈ 1.875·D/T (Flash-Hogan analytical result)", () => {
    const D = 600; // distance
    const traj = new MinJerkTrajectory({ x: 0, y: 0 }, { x: D, y: 0 });
    const T = traj.totalDuration();
    let maxSpeed = 0;
    while (!traj.isDone()) {
      const r = traj.tick(FRAME_60);
      maxSpeed = Math.max(maxSpeed, Math.hypot(r.velocity.x, r.velocity.y));
    }
    const expected = (1.875 * D) / T;
    // Bezier path is slightly curved, so peak speed along the curve is
    // a bit higher than peak straight-line speed. Allow 15% upward
    // deviation, no downward.
    expect(maxSpeed).toBeGreaterThanOrEqual(expected * 0.95);
    expect(maxSpeed).toBeLessThanOrEqual(expected * 1.20);
  });

  it("degenerate trajectory (start = end) marks done immediately", () => {
    const traj = new MinJerkTrajectory({ x: 5, y: 5 }, { x: 5, y: 5 });
    expect(traj.isDone()).toBe(true);
    const r = traj.tick(FRAME_60);
    expect(r.done).toBe(true);
    expect(r.position.x).toBe(5);
  });

  it("custom duration override respects floor (180ms minimum)", () => {
    const traj = new MinJerkTrajectory(
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { duration: 0.05 }, // 50ms — should clamp to 180ms
    );
    expect(traj.totalDuration()).toBeGreaterThanOrEqual(0.18);
  });

  it("path follows curve (not straight line)", () => {
    // For a horizontal motion 0→200 with sag=0.08, the midpoint of
    // the trajectory should be Y-offset by ~16px (200·0.08·0.5 of
    // Bezier midpoint formula). Definitely NOT y=0.
    const traj = new MinJerkTrajectory(
      { x: 0, y: 0 },
      { x: 200, y: 0 },
      { sag: 0.08 },
    );
    const T = traj.totalDuration();
    let elapsed = 0;
    while (elapsed < T / 2) {
      traj.tick(FRAME_60);
      elapsed += FRAME_60;
    }
    const mid = traj.position();
    // Y should be non-zero at trajectory midpoint due to Bezier curve.
    expect(Math.abs(mid.y)).toBeGreaterThan(2);
  });
});
