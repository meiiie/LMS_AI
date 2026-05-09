/**
 * Tests for v7.0 multi-target parsers + dispatch queue.
 * Generic — does NOT hardcode any specific UI element. Tests prove
 * the CONTRACT: any sentence with intent + label match dispatches.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  parseAllPointTags,
  parsePointTag,
} from "../pointy-host/inline-tag-parser";
import {
  detectAllEmbodiedPoints,
  detectEmbodiedPoint,
} from "../pointy-host/embodied-parser";
import {
  enqueuePoint,
  enqueuePoints,
  cancelDispatchQueue,
  clearDispatchQueue,
  dispatchQueueState,
} from "../pointy-host/dispatch-queue";
import { pointAtDetailed } from "../pointy-host/api";

// Mock pointAtDetailed so we can verify queue dispatches without real DOM.
vi.mock("../pointy-host/api", () => ({
  clear: vi.fn(),
  pointAtDetailed: vi.fn().mockReturnValue({ success: true }),
}));

describe("parseAllPointTags — multi-tag extraction", () => {
  it("returns empty when no tags", () => {
    expect(parseAllPointTags("Plain prose").tags).toEqual([]);
  });

  it("extracts single tag", () => {
    const r = parseAllPointTags("Đây nè. [POINT:btn-a]");
    expect(r.tags).toEqual([{ selector: "btn-a", caption: "" }]);
  });

  it("extracts multiple tags in order", () => {
    const r = parseAllPointTags(
      "Click [POINT:btn-x:start]. Rồi [POINT:btn-y:middle]. Cuối [POINT:btn-z:end].",
    );
    expect(r.tags).toEqual([
      { selector: "btn-x", caption: "start" },
      { selector: "btn-y", caption: "middle" },
      { selector: "btn-z", caption: "end" },
    ]);
  });

  it("filters [POINT:none] entries", () => {
    const r = parseAllPointTags(
      "Đây nè [POINT:btn-a]. Còn cái này [POINT:none]. Và [POINT:btn-b].",
    );
    expect(r.tags.map((t) => t.selector)).toEqual(["btn-a", "btn-b"]);
  });

  it("strips all tags from displayed text", () => {
    const r = parseAllPointTags(
      "Trước [POINT:btn-a]. Sau đó [POINT:btn-b].",
    );
    expect(r.stripped).toBe("Trước . Sau đó .");
  });

  it("backward compat: single-tag parsePointTag still anchored to end", () => {
    const r = parsePointTag("Mid sentence [POINT:btn-a] not at end.");
    expect(r.tag).toBeNull();
  });
});

describe("detectAllEmbodiedPoints — multi-match parametric", () => {
  const TARGETS = [
    { id: "send-btn", label: "Gửi tin nhắn", role: "button" },
    { id: "settings-link", label: "Cài đặt", role: "link" },
    { id: "model-picker", label: "Chọn model", role: "menu" },
    { id: "attach-btn", label: "Đính kèm", role: "button" },
  ];

  it("returns empty when no targets match", () => {
    const r = detectAllEmbodiedPoints("Trời đẹp quá.", TARGETS);
    expect(r).toEqual([]);
  });

  it("single match works (back-compat with detectEmbodiedPoint)", () => {
    const text = "Nút gửi tin nhắn ở góc dưới phải nè cậu.";
    const single = detectEmbodiedPoint(text, TARGETS);
    const multi = detectAllEmbodiedPoints(text, TARGETS);
    expect(multi.length).toBe(1);
    expect(multi[0].target.id).toBe(single?.target.id);
  });

  it("extracts multi-step sequence in sentence order", () => {
    const text =
      "Đầu tiên click vào Cài đặt. Rồi mở Chọn model. Cuối cùng nhấn vào Gửi tin nhắn.";
    const matches = detectAllEmbodiedPoints(text, TARGETS);
    expect(matches.map((m) => m.target.id)).toEqual([
      "settings-link",
      "model-picker",
      "send-btn",
    ]);
  });

  it("dedupes same target — only first sentence wins", () => {
    const text = "Nút gửi nằm ở góc phải. Nút gửi cũng có thể click bằng Enter.";
    const matches = detectAllEmbodiedPoints(text, TARGETS);
    // Both sentences mention send button, but only first one matches.
    expect(matches.length).toBe(1);
    expect(matches[0].target.id).toBe("send-btn");
  });

  it("respects maxMatches cap", () => {
    const text =
      "Cài đặt ở đây. Chọn model nằm ở đó. Đính kèm là cái này. Gửi tin nhắn ở góc phải.";
    const matches = detectAllEmbodiedPoints(text, TARGETS, { maxMatches: 2 });
    expect(matches.length).toBe(2);
  });

  it("custom threshold works (lower = more permissive)", () => {
    const text = "Cài đặt — chỗ thay đổi options.";
    const strict = detectAllEmbodiedPoints(text, TARGETS, { threshold: 0.7 });
    const loose = detectAllEmbodiedPoints(text, TARGETS, { threshold: 0.4 });
    expect(loose.length).toBeGreaterThanOrEqual(strict.length);
  });
});

describe("dispatch-queue — sequence semantics", () => {
  beforeEach(() => {
    clearDispatchQueue();
    vi.clearAllMocks();
  });

  it("emits structured dispatch telemetry for accepted actions", () => {
    const events: Array<{ status: string; selector: string; source: string }> = [];
    const listener = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      events.push({
        status: detail.status,
        selector: detail.selector,
        source: detail.source,
      });
    };
    window.addEventListener("wiii:pointy:dispatch", listener);
    try {
      enqueuePoint({ selector: "btn-a", durationMs: 1000, source: "manual" });
      expect(events).toEqual([
        { status: "queued", selector: "btn-a", source: "manual" },
        { status: "started", selector: "btn-a", source: "manual" },
        { status: "accepted", selector: "btn-a", source: "manual" },
      ]);
    } finally {
      window.removeEventListener("wiii:pointy:dispatch", listener);
    }
  });

  it("emits failed telemetry and legacy failure event when selector resolution fails", () => {
    vi.mocked(pointAtDetailed).mockReturnValueOnce({
      success: false,
      reason: "selector_not_found",
    });
    const statuses: string[] = [];
    const failures: string[] = [];
    const telemetryListener = (event: Event) => {
      statuses.push((event as CustomEvent).detail.status);
    };
    const failureListener = (event: Event) => {
      failures.push((event as CustomEvent).detail.reason);
    };
    window.addEventListener("wiii:pointy:dispatch", telemetryListener);
    window.addEventListener("wiii:pointy:dispatch-failed", failureListener);
    try {
      enqueuePoint({ selector: "missing-btn", durationMs: 1000 });
      expect(statuses).toEqual(["queued", "started", "failed"]);
      expect(failures).toEqual(["selector_not_found"]);
    } finally {
      window.removeEventListener("wiii:pointy:dispatch", telemetryListener);
      window.removeEventListener("wiii:pointy:dispatch-failed", failureListener);
    }
  });

  it("enqueuePoint returns true on first, false on duplicate signature", () => {
    const r1 = enqueuePoint({ selector: "btn-a", durationMs: 1000 });
    const r2 = enqueuePoint({ selector: "btn-a", durationMs: 1000 });
    expect(r1).toBe(true);
    expect(r2).toBe(false);
  });

  it("different captions count as different signatures", () => {
    const r1 = enqueuePoint({ selector: "btn-a", caption: "first", durationMs: 1000 });
    const r2 = enqueuePoint({ selector: "btn-a", caption: "second", durationMs: 1000 });
    expect(r1).toBe(true);
    expect(r2).toBe(true);
  });

  it("enqueuePoints returns count newly queued", () => {
    const queued = enqueuePoints([
      { selector: "btn-a", durationMs: 1000 },
      { selector: "btn-b", durationMs: 1000 },
      { selector: "btn-a", durationMs: 1000 }, // dup of first
    ]);
    expect(queued).toBe(2);
  });

  it("clearDispatchQueue resets dedup history", () => {
    enqueuePoint({ selector: "btn-a", durationMs: 1000 });
    expect(enqueuePoint({ selector: "btn-a", durationMs: 1000 })).toBe(false);
    clearDispatchQueue();
    expect(enqueuePoint({ selector: "btn-a", durationMs: 1000 })).toBe(true);
  });

  it("cancelDispatchQueue aborts active and pending multi-step guidance", () => {
    const events: Array<{ status: string; selector: string; reason?: string }> = [];
    const listener = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      events.push({
        status: detail.status,
        selector: detail.selector,
        reason: detail.reason,
      });
    };
    window.addEventListener("wiii:pointy:dispatch", listener);
    try {
      enqueuePoints([
        { selector: "btn-a", durationMs: 1000 },
        { selector: "btn-b", durationMs: 1000 },
      ]);
      cancelDispatchQueue("user_dismissed");
      expect(dispatchQueueState()).toEqual({ depth: 0, active: null, seen: 0 });
      expect(events).toContainEqual({
        status: "cancelled",
        selector: "btn-a",
        reason: "user_dismissed",
      });
      expect(events).toContainEqual({
        status: "cancelled",
        selector: "btn-b",
        reason: "user_dismissed",
      });
    } finally {
      window.removeEventListener("wiii:pointy:dispatch", listener);
    }
  });

  it("dispatchQueueState reflects depth + active", () => {
    enqueuePoints([
      { selector: "btn-a", durationMs: 100 },
      { selector: "btn-b", durationMs: 100 },
      { selector: "btn-c", durationMs: 100 },
    ]);
    const s = dispatchQueueState();
    expect(s.seen).toBe(3);
    // First item dispatches synchronously, so active is set + queue depth = 2.
    expect(s.active).toContain("btn-a");
    expect(s.depth).toBe(2);
  });
});
