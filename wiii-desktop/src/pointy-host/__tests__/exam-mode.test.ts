/**
 * Tests for ExamMode foundation — proctoring helper với threshold flags.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { ExamMode } from "../exam-mode";
import { UserAttentionTracker } from "../user-attention";

describe("ExamMode", () => {
  let tracker: UserAttentionTracker | null = null;
  let exam: ExamMode | null = null;

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(async () => {
    if (exam) {
      await exam.stop();
      exam = null;
    }
    tracker?.dispose();
    tracker = null;
  });

  it("starts with empty audit log", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "test-session" }, tracker);
    expect(exam.getAuditLog()).toHaveLength(0);
  });

  it("logs start entry on start()", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "quiz-1", sessionName: "Test Quiz" }, tracker);
    await exam.start();
    const log = exam.getAuditLog();
    expect(log).toHaveLength(1);
    expect(log[0].type).toBe("start");
    expect(log[0].sessionId).toBe("quiz-1");
    expect(log[0].reason).toBe("Test Quiz");
  });

  it("logs stop entry on stop()", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "quiz-1" }, tracker);
    await exam.start();
    const finalLog = await exam.stop();
    const stopEntry = finalLog[finalLog.length - 1];
    expect(stopEntry.type).toBe("stop");
  });

  it("captures attention events into audit log during exam", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    await exam.start();
    // Simulate user actions.
    document.dispatchEvent(new Event("copy"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    const log = exam.getAuditLog();
    const types = log.map((e) => e.type);
    expect(types).toContain("copy");
    expect(types).toContain("blur");
    expect(types).toContain("focus");
  });

  it("includes counters snapshot in audit entries", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    await exam.start();
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("copy"));
    const log = exam.getAuditLog();
    const copies = log.filter((e) => e.type === "copy");
    expect(copies.length).toBeGreaterThan(0);
    const lastCopy = copies[copies.length - 1];
    expect(lastCopy.counters?.copyCount).toBe(2);
  });

  it("flags too_many_tab_switches when threshold exceeded", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode(
      { sessionId: "q1", thresholds: { maxTabSwitches: 1 } },
      tracker,
    );
    const flags: string[] = [];
    exam.onFlag((f) => flags.push(f.reason));
    await exam.start();
    // Simulate 2 tab switches.
    let visibility: "visible" | "hidden" = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(flags).toContain("too_many_tab_switches");
    expect(exam.getFlaggedReasons()).toContain("too_many_tab_switches");
  });

  it("flags paste_detected on first paste (default threshold 0)", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    const flags: string[] = [];
    exam.onFlag((f) => flags.push(f.reason));
    await exam.start();
    document.dispatchEvent(new Event("paste"));
    expect(flags).toContain("paste_detected");
  });

  it("does NOT flag same reason multiple times", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode(
      { sessionId: "q1", thresholds: { maxCopies: 1 } },
      tracker,
    );
    const flags: string[] = [];
    exam.onFlag((f) => flags.push(f.reason));
    await exam.start();
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("copy"));
    const copyFlags = flags.filter((r) => r === "too_many_copies");
    expect(copyFlags.length).toBe(1); // only once
  });

  it("getFlaggedReasons returns all reasons fired", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode(
      {
        sessionId: "q1",
        thresholds: { maxCopies: 1, maxBlurs: 1 },
      },
      tracker,
    );
    await exam.start();
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("copy"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("blur"));
    const reasons = exam.getFlaggedReasons();
    expect(reasons).toContain("too_many_copies");
    expect(reasons).toContain("too_many_blurs");
  });

  it("stop() returns final audit log including stop entry", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    await exam.start();
    document.dispatchEvent(new Event("copy"));
    const finalLog = await exam.stop();
    expect(finalLog[0].type).toBe("start");
    expect(finalLog[finalLog.length - 1].type).toBe("stop");
    expect(finalLog.some((e) => e.type === "copy")).toBe(true);
  });

  it("idempotent: double stop returns same log", async () => {
    tracker = new UserAttentionTracker();
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    await exam.start();
    const first = await exam.stop();
    const second = await exam.stop();
    expect(second.length).toBe(first.length);
  });

  it("does not log copy/paste events fired before start()", async () => {
    tracker = new UserAttentionTracker();
    // Fire events BEFORE creating exam — these should NOT count.
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("paste"));
    exam = new ExamMode({ sessionId: "q1" }, tracker);
    await exam.start();
    const log = exam.getAuditLog();
    // Should not contain pre-start copy or paste in audit log.
    const types = log.map((e) => e.type);
    expect(types).not.toContain("copy");
    expect(types).not.toContain("paste");
    expect(types).toContain("start");
  });
});
