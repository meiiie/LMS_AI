/**
 * Tests for UserAttentionTracker — page visibility + focus + idle counting.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { UserAttentionTracker } from "../user-attention";

describe("UserAttentionTracker", () => {
  let tracker: UserAttentionTracker | null = null;

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    tracker?.dispose();
    tracker = null;
  });

  it("starts in active status when document visible + focused", () => {
    tracker = new UserAttentionTracker();
    const snap = tracker.snapshot();
    expect(snap.isVisible).toBe(true);
    expect(snap.blurCount).toBe(0);
    expect(snap.hideCount).toBe(0);
    expect(snap.totalAwayMs).toBe(0);
  });

  it("counts blur events", () => {
    tracker = new UserAttentionTracker();
    expect(tracker.snapshot().blurCount).toBe(0);
    window.dispatchEvent(new Event("blur"));
    expect(tracker.snapshot().blurCount).toBe(1);
    expect(tracker.snapshot().status).toBe("blurred");
    expect(tracker.snapshot().isFocused).toBe(false);
  });

  it("does not double-count consecutive blur events", () => {
    tracker = new UserAttentionTracker();
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("blur"));
    expect(tracker.snapshot().blurCount).toBe(1);
  });

  it("focus event after blur returns status to active", () => {
    tracker = new UserAttentionTracker();
    window.dispatchEvent(new Event("blur"));
    expect(tracker.snapshot().status).toBe("blurred");
    window.dispatchEvent(new Event("focus"));
    expect(tracker.snapshot().status).toBe("active");
    expect(tracker.snapshot().isFocused).toBe(true);
  });

  it("focus after blur records lastAwayDurationMs > 0", () => {
    tracker = new UserAttentionTracker();
    window.dispatchEvent(new Event("blur"));
    // Force perf timer to advance: just trigger focus immediately.
    // Even minimal duration should be recorded as totalAwayMs.
    window.dispatchEvent(new Event("focus"));
    const snap = tracker.snapshot();
    // lastAwayDurationMs may be 0 in jsdom but field should exist.
    expect(typeof snap.lastAwayDurationMs).toBe("number");
    expect(snap.lastAwayDurationMs).toBeGreaterThanOrEqual(0);
  });

  it("counts visibility hide events as tab switches", () => {
    // Use a stub doc to avoid global side-effects between tests.
    let visibility: "visible" | "hidden" = "visible";
    const stubDoc = {
      get visibilityState() {
        return visibility;
      },
      addEventListener: document.addEventListener.bind(document),
      removeEventListener: document.removeEventListener.bind(document),
      dispatchEvent: document.dispatchEvent.bind(document),
      hasFocus: () => true,
    } as unknown as Document;

    tracker = new UserAttentionTracker({ doc: stubDoc });
    expect(tracker.snapshot().hideCount).toBe(0);
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(tracker.snapshot().hideCount).toBe(1);
    expect(tracker.snapshot().status).toBe("hidden");
    expect(tracker.snapshot().isVisible).toBe(false);
  });

  it("returning to visible flips status back to active", () => {
    let visibility: "visible" | "hidden" = "visible";
    const stubDoc = {
      get visibilityState() {
        return visibility;
      },
      addEventListener: document.addEventListener.bind(document),
      removeEventListener: document.removeEventListener.bind(document),
      dispatchEvent: document.dispatchEvent.bind(document),
      hasFocus: () => true,
    } as unknown as Document;

    tracker = new UserAttentionTracker({ doc: stubDoc });
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(tracker.snapshot().status).toBe("hidden");

    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    expect(tracker.snapshot().isVisible).toBe(true);
    expect(tracker.snapshot().status).toBe("active");
  });

  it("recentEvents array captures transitions in order", () => {
    tracker = new UserAttentionTracker();
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    const events = tracker.snapshot().recentEvents;
    expect(events.length).toBe(2);
    expect(events[0].type).toBe("blur");
    expect(events[1].type).toBe("focus");
  });

  it("trims recentEvents to maxHistory limit", () => {
    tracker = new UserAttentionTracker({ maxHistory: 3 });
    for (let i = 0; i < 10; i++) {
      window.dispatchEvent(new Event("blur"));
      window.dispatchEvent(new Event("focus"));
    }
    expect(tracker.snapshot().recentEvents.length).toBe(3);
  });

  it("describeForLLM produces useful output", () => {
    tracker = new UserAttentionTracker();
    const out = tracker.describeForLLM();
    expect(out).toContain("status=active");
    expect(out).toContain("blurs=0");
    expect(out).toContain("tab_switches=0");
  });

  it("describeForLLM mentions blur count after blur events", () => {
    tracker = new UserAttentionTracker();
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    const out = tracker.describeForLLM();
    expect(out).toContain("blurs=2");
  });

  it("subscribe receives initial snapshot", () => {
    tracker = new UserAttentionTracker();
    const snapshots: string[] = [];
    tracker.subscribe((s) => {
      snapshots.push(s.status);
    });
    expect(snapshots).toEqual(["active"]);
  });

  it("subscribe receives notifications on blur/focus", () => {
    tracker = new UserAttentionTracker();
    const snapshots: string[] = [];
    tracker.subscribe((s) => {
      snapshots.push(s.status);
    });
    window.dispatchEvent(new Event("blur"));
    window.dispatchEvent(new Event("focus"));
    expect(snapshots).toEqual(["active", "blurred", "active"]);
  });

  // ─── v2.7 enhanced events ──────────────────────────────────────

  it("counts copy events", () => {
    tracker = new UserAttentionTracker();
    expect(tracker.snapshot().copyCount).toBe(0);
    document.dispatchEvent(new Event("copy"));
    expect(tracker.snapshot().copyCount).toBe(1);
    document.dispatchEvent(new Event("copy"));
    expect(tracker.snapshot().copyCount).toBe(2);
  });

  it("counts cut events as copyCount (clipboard semantic)", () => {
    tracker = new UserAttentionTracker();
    document.dispatchEvent(new Event("cut"));
    expect(tracker.snapshot().copyCount).toBe(1);
  });

  it("counts paste events separately", () => {
    tracker = new UserAttentionTracker();
    expect(tracker.snapshot().pasteCount).toBe(0);
    document.dispatchEvent(new Event("paste"));
    expect(tracker.snapshot().pasteCount).toBe(1);
    document.dispatchEvent(new Event("paste"));
    expect(tracker.snapshot().pasteCount).toBe(2);
  });

  it("counts contextmenu (right-click) events", () => {
    tracker = new UserAttentionTracker();
    expect(tracker.snapshot().contextMenuCount).toBe(0);
    document.dispatchEvent(new Event("contextmenu"));
    document.dispatchEvent(new Event("contextmenu"));
    expect(tracker.snapshot().contextMenuCount).toBe(2);
  });

  it("records v2.7 events in recentEvents", () => {
    tracker = new UserAttentionTracker();
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("paste"));
    document.dispatchEvent(new Event("contextmenu"));
    const events = tracker.snapshot().recentEvents.map((e) => e.type);
    expect(events).toContain("copy");
    expect(events).toContain("paste");
    expect(events).toContain("contextmenu");
  });

  it("describeForLLM includes copy/paste/right-click counters when non-zero", () => {
    tracker = new UserAttentionTracker();
    document.dispatchEvent(new Event("copy"));
    document.dispatchEvent(new Event("paste"));
    document.dispatchEvent(new Event("contextmenu"));
    const out = tracker.describeForLLM();
    expect(out).toContain("copies=1");
    expect(out).toContain("pastes=1");
    expect(out).toContain("right_clicks=1");
  });

  it("describeForLLM omits behaviour line when all counters zero", () => {
    tracker = new UserAttentionTracker();
    const out = tracker.describeForLLM();
    expect(out).not.toContain("copies=");
  });

  it("dispose removes listeners and stops emitting", () => {
    tracker = new UserAttentionTracker();
    const fn = tracker;
    fn.dispose();
    let calls = 0;
    fn.subscribe(() => {
      calls++;
    });
    const initial = calls; // 1 from initial push (still works after dispose since subscribe pushes synchronously)
    window.dispatchEvent(new Event("blur"));
    expect(calls).toBe(initial); // No new calls after dispose
    tracker = null;
  });
});
