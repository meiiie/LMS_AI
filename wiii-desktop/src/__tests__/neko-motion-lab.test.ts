import { describe, expect, it } from "vitest";
import {
  NEKO_MOTION_PRESETS,
  NEKO_MOTION_STATES,
  nextNekoMotionState,
  resolveNekoPose,
} from "@/neko-motion-lab/neko-motion-model";

describe("Neko Motion Lab state contract", () => {
  it("defines the eight reviewed semantic states", () => {
    expect(NEKO_MOTION_STATES).toEqual([
      "ready",
      "listening",
      "thinking",
      "tool-running",
      "success",
      "attention",
      "idle",
      "recover",
    ]);
    expect(Object.keys(NEKO_MOTION_PRESETS)).toHaveLength(8);
  });

  it("keeps every pose inside the approved motion envelope", () => {
    for (const state of NEKO_MOTION_STATES) {
      const pose = resolveNekoPose(
        state,
        { energy: 1, gazeX: 0, gazeY: 0, tail: 0 },
        false,
      );
      expect(Math.abs(pose.tilt), state).toBeLessThanOrEqual(8);
      expect(Math.abs(pose.lift), state).toBeLessThanOrEqual(9);
      expect(Math.abs(pose.gazeX), state).toBeLessThanOrEqual(1);
      expect(Math.abs(pose.gazeY), state).toBeLessThanOrEqual(1);
      expect(pose.eyeOpen, state).toBeGreaterThanOrEqual(0.12);
      expect(pose.eyeOpen, state).toBeLessThanOrEqual(1);
    }
  });

  it("clamps manual parameters before resolving the renderer pose", () => {
    const pose = resolveNekoPose(
      "thinking",
      { energy: 4, gazeX: 7, gazeY: -9, tail: 12 },
      false,
    );
    expect(pose.gazeX).toBe(1);
    expect(pose.gazeY).toBe(-1);
    expect(pose.tail).toBe(1);
    expect(pose.tilt).toBe(7);
  });

  it("removes nonessential spatial motion in reduced-motion mode", () => {
    const pose = resolveNekoPose(
      "success",
      { energy: 1, gazeX: 0.5, gazeY: 0.5, tail: 1 },
      true,
    );
    expect(pose.tilt).toBe(0);
    expect(pose.lift).toBe(0);
    expect(pose.scale).toBe(1);
    expect(pose.tail).toBe(0);
    expect(pose.eyeOpen).toBe(NEKO_MOTION_PRESETS.success.eyeOpen);
  });

  it("cycles deterministically and returns to ready", () => {
    expect(nextNekoMotionState("ready")).toBe("listening");
    expect(nextNekoMotionState("recover")).toBe("ready");
  });

  it("uses recover rather than a sad error face", () => {
    expect(NEKO_MOTION_STATES).not.toContain("error");
    expect(NEKO_MOTION_PRESETS.recover.meaning).toContain("không bằng mặt buồn");
  });
});
