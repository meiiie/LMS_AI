/**
 * Tests for MotionEngine — strategy switching + continuity.
 */

import { describe, it, expect } from "vitest";
import { MotionEngine } from "../motion-engine";

const FRAME_60 = 1 / 60;

describe("MotionEngine strategy selection", () => {
  it("starts in spring (tracking) mode", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    expect(engine.currentStrategy()).toBe("spring");
  });

  it("setTarget with small delta (<50px) uses spring (tracking)", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(30, 0);
    expect(engine.currentStrategy()).toBe("spring");
  });

  it("setTarget with large delta (>=50px) auto-switches to trajectory", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(100, 0);
    expect(engine.currentStrategy()).toBe("trajectory");
  });

  it("explicit directed=true forces trajectory regardless of distance", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(10, 0, { directed: true });
    expect(engine.currentStrategy()).toBe("trajectory");
  });

  it("prefersReducedMotion uses snap (no animation)", () => {
    const engine = new MotionEngine({ x: 0, y: 0 }, { prefersReducedMotion: true });
    engine.setTarget(500, 500);
    expect(engine.currentStrategy()).toBe("snap");
    expect(engine.position()).toEqual({ x: 500, y: 500 });
  });
});

describe("MotionEngine — directed move (trajectory)", () => {
  it("converges to exact target position when directed move completes", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(500, 200, { directed: true });
    while (!engine.isSettled()) engine.tick(FRAME_60);
    const pos = engine.position();
    expect(Math.abs(pos.x - 500)).toBeLessThan(1);
    expect(Math.abs(pos.y - 200)).toBeLessThan(1);
  });

  it("transitions to spring after trajectory completes (continuity)", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(500, 0, { directed: true });
    expect(engine.currentStrategy()).toBe("trajectory");
    while (!engine.isSettled()) engine.tick(FRAME_60);
    // After trajectory done, engine should have switched back to spring.
    expect(engine.currentStrategy()).toBe("spring");
  });

  it("velocity peaks somewhere in the middle of the trajectory (bell shape)", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(800, 0, { directed: true });
    let maxSpeed = 0;
    while (!engine.isSettled()) {
      const r = engine.tick(FRAME_60);
      const speed = Math.hypot(r.velocity.x, r.velocity.y);
      maxSpeed = Math.max(maxSpeed, speed);
    }
    // Peak speed should be substantial (at least 1000px/s for D=800px).
    expect(maxSpeed).toBeGreaterThan(800);
  });

  it("returns to spring tracking when small follow-up update arrives mid-flight", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(500, 0, { directed: true });
    expect(engine.currentStrategy()).toBe("trajectory");
    // Mid-flight, send a tiny tracking update — should switch back.
    for (let i = 0; i < 5; i++) engine.tick(FRAME_60);
    engine.setTarget(engine.position().x + 5, engine.position().y);
    expect(engine.currentStrategy()).toBe("spring");
  });
});

describe("MotionEngine — tracking move (spring)", () => {
  it("uses spring physics for small continuous updates", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(20, 0); // < 50px threshold
    expect(engine.currentStrategy()).toBe("spring");
    // Run for 2s — should converge to target.
    for (let i = 0; i < 120; i++) engine.tick(FRAME_60);
    const pos = engine.position();
    expect(Math.abs(pos.x - 20)).toBeLessThan(1);
  });

  it("redirects mid-tracking when target updates", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(30, 0);
    for (let i = 0; i < 10; i++) engine.tick(FRAME_60);
    const midPos = engine.position();
    // Target redirect — still small (under 50px from current).
    engine.setTarget(midPos.x + 25, midPos.y + 10);
    expect(engine.currentStrategy()).toBe("spring");
    // Should converge to new target eventually.
    for (let i = 0; i < 240; i++) engine.tick(FRAME_60);
    const finalPos = engine.position();
    expect(Math.abs(finalPos.x - (midPos.x + 25))).toBeLessThan(1);
  });
});

describe("MotionEngine — edge cases", () => {
  it("setTarget with same position is a no-op", () => {
    const engine = new MotionEngine({ x: 100, y: 100 });
    engine.setTarget(100, 100);
    expect(engine.currentStrategy()).toBe("spring");
    expect(engine.isSettled()).toBe(true);
  });

  it("reset snaps to position with zero velocity", () => {
    const engine = new MotionEngine({ x: 0, y: 0 });
    engine.setTarget(500, 0, { directed: true });
    for (let i = 0; i < 5; i++) engine.tick(FRAME_60);
    engine.reset(50, 50);
    expect(engine.position()).toEqual({ x: 50, y: 50 });
    expect(engine.velocity()).toEqual({ x: 0, y: 0 });
    expect(engine.currentStrategy()).toBe("spring");
  });

  it("targetWidth option propagates to Fitts duration", () => {
    const engine1 = new MotionEngine({ x: 0, y: 0 });
    engine1.setTarget(300, 0, { directed: true, targetWidth: 100 });
    const engine2 = new MotionEngine({ x: 0, y: 0 });
    engine2.setTarget(300, 0, { directed: true, targetWidth: 10 });

    let frames1 = 0;
    while (!engine1.isSettled()) {
      engine1.tick(FRAME_60);
      frames1++;
    }
    let frames2 = 0;
    while (!engine2.isSettled()) {
      engine2.tick(FRAME_60);
      frames2++;
    }
    // Smaller target (10px) should take more frames than larger (100px).
    expect(frames2).toBeGreaterThan(frames1);
  });
});
