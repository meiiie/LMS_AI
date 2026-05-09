/**
 * Tests for UserCursorTracker — real OS cursor tracking.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { UserCursorTracker } from "../user-cursor";

describe("UserCursorTracker", () => {
  let tracker: UserCursorTracker | null = null;

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    tracker?.dispose();
    tracker = null;
  });

  it("starts with null position before any mouse event", () => {
    tracker = new UserCursorTracker();
    const snap = tracker.snapshot();
    expect(snap.position).toBeNull();
    expect(snap.hoveredId).toBeNull();
  });

  it("records position after mousemove", () => {
    tracker = new UserCursorTracker();
    const event = new MouseEvent("mousemove", {
      clientX: 320,
      clientY: 240,
    });
    window.dispatchEvent(event);
    const snap = tracker.snapshot();
    expect(snap.position).toEqual({ x: 320, y: 240 });
  });

  it("detects hovered element with id", () => {
    document.body.innerHTML = `
      <div id="page">
        <button id="send-btn" style="position:fixed;left:0;top:0;width:100px;height:50px">
          Send
        </button>
      </div>
    `;
    tracker = new UserCursorTracker();
    // Mock elementFromPoint to return our button (jsdom doesn't compute layout).
    const btn = document.getElementById("send-btn") as HTMLElement;
    const original = document.elementFromPoint;
    document.elementFromPoint = () => btn;
    try {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 50, clientY: 25 }));
      const snap = tracker.snapshot();
      expect(snap.hoveredId).toBe("send-btn");
      expect(snap.hoveredSelector).toBe("#send-btn");
    } finally {
      document.elementFromPoint = original;
    }
  });

  it("prefers data-wiii-id over CSS id when both present", () => {
    document.body.innerHTML = `<button id="css-id" data-wiii-id="wiii-handle">B</button>`;
    tracker = new UserCursorTracker();
    const btn = document.querySelector("button") as HTMLElement;
    const original = document.elementFromPoint;
    document.elementFromPoint = () => btn;
    try {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 10, clientY: 10 }));
      const snap = tracker.snapshot();
      expect(snap.hoveredId).toBe("wiii-handle");
      expect(snap.hoveredSelector).toBe("wiii-handle");
    } finally {
      document.elementFromPoint = original;
    }
  });

  it("walks up DOM to find pointable ancestor", () => {
    document.body.innerHTML = `
      <button id="parent-btn">
        <span id="inner-text">Click me</span>
      </button>
    `;
    tracker = new UserCursorTracker();
    const span = document.getElementById("inner-text") as HTMLElement;
    const original = document.elementFromPoint;
    document.elementFromPoint = () => span;
    try {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 5, clientY: 5 }));
      const snap = tracker.snapshot();
      // Should resolve to the button parent.
      expect(snap.hoveredId).toBe("parent-btn");
    } finally {
      document.elementFromPoint = original;
    }
  });

  it("flags recentlyClicked after mousedown", () => {
    tracker = new UserCursorTracker();
    expect(tracker.snapshot().recentlyClicked).toBe(false);
    window.dispatchEvent(new MouseEvent("mousedown", { clientX: 0, clientY: 0 }));
    expect(tracker.snapshot().recentlyClicked).toBe(true);
  });

  it("subscribe receives initial snapshot synchronously", () => {
    tracker = new UserCursorTracker();
    const snapshots: number[] = [];
    const unsub = tracker.subscribe((s) => {
      snapshots.push(s.position?.x ?? -1);
    });
    expect(snapshots).toEqual([-1]); // initial: position null
    unsub();
  });

  it("snapshot() reflects first movement (bypasses throttle)", () => {
    tracker = new UserCursorTracker();
    expect(tracker.snapshot().position).toBeNull();
    window.dispatchEvent(new MouseEvent("mousemove", { clientX: 100, clientY: 50 }));
    const snap = tracker.snapshot();
    expect(snap.position).toEqual({ x: 100, y: 50 });
    expect(snap.lastMoveAt).toBeGreaterThan(0);
  });

  it("describeForLLM returns useful text when tracking", () => {
    tracker = new UserCursorTracker();
    expect(tracker.describeForLLM()).toContain("not tracked yet");
    window.dispatchEvent(new MouseEvent("mousemove", { clientX: 50, clientY: 25 }));
    const desc = tracker.describeForLLM();
    expect(desc).toContain("pos=(50, 25)");
    expect(desc).toContain("idle=");
  });

  it("describeForLLM mentions hovered element", () => {
    document.body.innerHTML = `<button id="b" aria-label="Gửi">Click</button>`;
    tracker = new UserCursorTracker();
    const btn = document.querySelector("button") as HTMLElement;
    const original = document.elementFromPoint;
    document.elementFromPoint = () => btn;
    try {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: 10, clientY: 10 }));
      const desc = tracker.describeForLLM();
      expect(desc).toContain('id="b"');
      expect(desc).toContain('label="Gửi"');
    } finally {
      document.elementFromPoint = original;
    }
  });

  it("dispose cleans up listeners", () => {
    tracker = new UserCursorTracker();
    const fn = tracker;
    tracker.dispose();
    // After dispose, subscribers should not fire on subsequent moves.
    let calls = 0;
    fn.subscribe(() => {
      calls++;
    });
    const initialCalls = calls; // 1 from initial push
    window.dispatchEvent(new MouseEvent("mousemove", { clientX: 0, clientY: 0 }));
    expect(calls).toBe(initialCalls); // no further updates
    tracker = null;
  });
});
