import { describe, expect, it } from "vitest";
import { validateAdeRunTransition } from "@/ade/lifecycle";

describe("ADE run lifecycle", () => {
  it("accepts the explicit plan-to-review path", () => {
    expect(validateAdeRunTransition("queued", "starting")).toBeNull();
    expect(validateAdeRunTransition("starting", "running")).toBeNull();
    expect(validateAdeRunTransition("running", "verifying")).toBeNull();
    expect(validateAdeRunTransition("verifying", "review")).toBeNull();
    expect(validateAdeRunTransition("review", "completed")).toBeNull();
  });

  it("keeps terminal runs terminal so retry creates another run", () => {
    for (const terminal of [
      "completed",
      "failed",
      "cancelled",
      "unknown_outcome",
    ] as const) {
      expect(validateAdeRunTransition(terminal, "running")).toEqual({
        code: "invalid_run_transition",
        from: terminal,
        to: "running",
      });
    }
  });
});
