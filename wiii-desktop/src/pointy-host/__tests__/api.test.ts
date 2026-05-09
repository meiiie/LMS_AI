/**
 * Tests for the public Pointy API — pin down the SSE-handler /
 * SoulBridge contract: selector resolution, identity defaults, peer
 * cursors, clear behaviour, fail-soft on missing selectors.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  pointAt,
  moveTo,
  showPeer,
  spawnPeer,
  setCursorState,
  clear,
  clearAll,
  getDefaultRegistry,
  disposeDefaultRegistry,
} from "../api";
import { WIII_IDENTITY, identityFor } from "../identity";

describe("pointy-host/api", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });
  afterEach(() => {
    disposeDefaultRegistry();
  });

  it("getDefaultRegistry returns the same instance across calls", () => {
    const a = getDefaultRegistry();
    const b = getDefaultRegistry();
    expect(a).toBe(b);
  });

  it("disposeDefaultRegistry clears the singleton", () => {
    const a = getDefaultRegistry();
    disposeDefaultRegistry();
    const b = getDefaultRegistry();
    expect(a).not.toBe(b);
  });

  it("pointAt returns false on unresolved selector", () => {
    const ok = pointAt("#nonexistent-element", { caption: "test" });
    expect(ok).toBe(false);
  });

  it("pointAt returns true and creates Wiii cursor on a real element", () => {
    const btn = document.createElement("button");
    btn.id = "test-btn";
    btn.style.position = "fixed";
    btn.style.left = "200px";
    btn.style.top = "100px";
    btn.style.width = "100px";
    btn.style.height = "40px";
    document.body.appendChild(btn);

    const ok = pointAt("#test-btn", { caption: "Test" });
    expect(ok).toBe(true);
    const cursorEl = document.querySelector('[data-pointy-cursor="wiii"]');
    expect(cursorEl).not.toBeNull();
  });

  it("pointAt emits a target event for optional voice/telemetry bridges", () => {
    const btn = document.createElement("button");
    btn.id = "voice-target";
    document.body.appendChild(btn);
    const seen = vi.fn();
    window.addEventListener("wiii:pointy:target", seen);

    const ok = pointAt("#voice-target", { caption: "Day la nut gui." });

    expect(ok).toBe(true);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0]?.[0]?.detail).toMatchObject({
      selector: "#voice-target",
      caption: "Day la nut gui.",
      target: {
        tagName: "BUTTON",
      },
    });
    window.removeEventListener("wiii:pointy:target", seen);
  });

  it("pointAt rejects hidden targets and emits invalid-target telemetry", () => {
    document.body.innerHTML = `<button id="ghost" style="display:none">Ghost</button>`;
    const seen = vi.fn();
    window.addEventListener("wiii:pointy:target-invalid", seen);

    const ok = pointAt("#ghost", { caption: "hidden" });

    expect(ok).toBe(false);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0]?.[0]?.detail).toMatchObject({
      selector: "#ghost",
      reason: "target_display_none",
      target: {
        tagName: "BUTTON",
      },
    });
    window.removeEventListener("wiii:pointy:target-invalid", seen);
  });

  it("pointAt resolves data-wiii-id selectors via fallback chain", () => {
    const btn = document.createElement("button");
    btn.setAttribute("data-wiii-id", "send-button");
    document.body.appendChild(btn);

    const ok = pointAt("send-button");
    expect(ok).toBe(true);
  });

  it("moveTo upserts cursor at coordinates without spotlight", () => {
    moveTo(300, 200, { label: "Wiii test" });
    const cursorEl = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(cursorEl).not.toBeNull();
    expect(cursorEl!.style.transform).toContain("translate3d(");
  });

  it("showPeer creates a non-Wiii cursor", () => {
    const peer = identityFor("peer-x", "Bro");
    showPeer(peer, { x: 100, y: 100 });
    const cursorEl = document.querySelector('[data-pointy-cursor="peer-x"]');
    expect(cursorEl).not.toBeNull();
    // Wiii cursor must NOT exist yet (we only added a peer).
    expect(document.querySelector('[data-pointy-cursor="wiii"]')).toBeNull();
  });

  it("showPeer refuses to spoof Wiii's reserved identity", () => {
    const fake = { ...WIII_IDENTITY }; // shallow clone, same id
    showPeer(fake, { x: 0, y: 0 });
    // Refused — no Wiii cursor created via showPeer.
    expect(document.querySelector('[data-pointy-cursor="wiii"]')).toBeNull();
  });

  it("spawnPeer builds identity + shows cursor in one call", () => {
    const ident = spawnPeer("alex", "Alex", { x: 50, y: 50 });
    expect(ident.id).toBe("alex");
    expect(ident.name).toBe("Alex");
    expect(ident.role).toBe("ai-peer");
    expect(document.querySelector('[data-pointy-cursor="alex"]')).not.toBeNull();
  });

  it("setCursorState updates data-pointy-state on the right cursor", () => {
    moveTo(0, 0);
    setCursorState(WIII_IDENTITY.id, "thinking");
    const el = document.querySelector('[data-pointy-cursor="wiii"]');
    expect(el?.getAttribute("data-pointy-state")).toBe("thinking");
  });

  it("clear sends Wiii to 'returning' (then dock), peers to 'idle', hides spotlight, keeps cursors visible", () => {
    moveTo(100, 100);
    spawnPeer("peer", "Bro", { x: 200, y: 200 });
    clear();
    // v3.0 Battleship: Wiii goes "returning" immediately (then dock after
    // ~1000ms timer); peer goes idle (peer lifecycle managed by transport).
    const wiiiEl = document.querySelector('[data-pointy-cursor="wiii"]');
    const peerEl = document.querySelector('[data-pointy-cursor="peer"]');
    expect(wiiiEl?.getAttribute("data-pointy-state")).toBe("returning");
    expect(peerEl?.getAttribute("data-pointy-state")).toBe("idle");
    // Both cursors still in DOM.
    expect(wiiiEl).not.toBeNull();
    expect(peerEl).not.toBeNull();
  });

  it("clearAll disposes registry and removes all cursors", () => {
    moveTo(100, 100);
    spawnPeer("peer", "Bro", { x: 200, y: 200 });
    clearAll();
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(0);
  });

  describe("v3.0 Battleship — dock auto-return", () => {
    it("pointAt successful → Wiii eventually returns to dock", async () => {
      vi.useFakeTimers();
      try {
        document.body.innerHTML = `<button data-wiii-id="send-btn">Send</button>`;
        const ok = pointAt("send-btn", { caption: "test", duration_ms: 1500 });
        expect(ok).toBe(true);
        const wiiiEl = document.querySelector('[data-pointy-cursor="wiii"]');
        // Initially: cursor should be 'moving' or 'pointing' (timer to
        // setState(pointing) at +200ms).
        expect(["moving", "pointing", "idle"]).toContain(
          wiiiEl?.getAttribute("data-pointy-state"),
        );
        // Fast-forward past duration_ms (1500) + DOCK_RETURN_HOLD_MS (800)
        // = 2300ms → "returning" should be set.
        vi.advanceTimersByTime(2400);
        expect(wiiiEl?.getAttribute("data-pointy-state")).toBe("returning");
        // Fast-forward another 1100ms → "dock" should land.
        vi.advanceTimersByTime(1100);
        expect(wiiiEl?.getAttribute("data-pointy-state")).toBe("dock");
      } finally {
        vi.useRealTimers();
      }
    });

    it("rapid sequential pointAt cancels stale dock-return timer", async () => {
      vi.useFakeTimers();
      try {
        document.body.innerHTML = `
          <button data-wiii-id="btn-a">A</button>
          <button data-wiii-id="btn-b">B</button>
        `;
        pointAt("btn-a", { duration_ms: 2000 });
        // 500ms in, redirect to btn-b — old timer should be cancelled.
        vi.advanceTimersByTime(500);
        pointAt("btn-b", { duration_ms: 2000 });
        // After enough time for OLD timer (2000+800=2800) but not NEW
        // timer (started at 500 → fires at 500+2800=3300), state should
        // still be moving/pointing, NOT returning yet.
        vi.advanceTimersByTime(2400); // total 2900 — past old 2800
        const state = document
          .querySelector('[data-pointy-cursor="wiii"]')
          ?.getAttribute("data-pointy-state");
        expect(["moving", "pointing"]).toContain(state);
        // Past the new timer.
        vi.advanceTimersByTime(500); // total 3400 — past new 3300
        expect(
          document
            .querySelector('[data-pointy-cursor="wiii"]')
            ?.getAttribute("data-pointy-state"),
        ).toBe("returning");
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
