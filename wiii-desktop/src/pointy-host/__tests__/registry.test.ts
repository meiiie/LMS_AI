/**
 * Tests for CursorRegistry — multi-cursor lifecycle, state transitions,
 * and DOM contract. Uses jsdom default environment.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { CursorRegistry } from "../registry";
import { WIII_IDENTITY, identityFor } from "../identity";

describe("CursorRegistry", () => {
  let registry: CursorRegistry;

  beforeEach(() => {
    document.body.innerHTML = "";
    // driveRaf:false so tests can advance manually
    registry = new CursorRegistry({ driveRaf: false });
  });

  afterEach(() => {
    registry.dispose();
  });

  it("creates a cursor element on first upsert", () => {
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(0);
    registry.upsert(WIII_IDENTITY, { x: 100, y: 50 });
    const els = document.querySelectorAll("[data-pointy-cursor]");
    expect(els).toHaveLength(1);
    expect(els[0].getAttribute("data-pointy-cursor")).toBe("wiii");
  });

  it("creates one element per cursor identity", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const peer = identityFor("peer-1", "Bro");
    registry.upsert(peer, { x: 200, y: 200 });
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(2);
    expect(registry.ids().sort()).toEqual(["peer-1", "wiii"]);
  });

  it("subsequent upsert does not create a new element", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.upsert(WIII_IDENTITY, { x: 500, y: 500 });
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(1);
  });

  it("setState updates data-pointy-state attribute", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.setState("wiii", "thinking");
    const el = document.querySelector('[data-pointy-cursor="wiii"]');
    expect(el?.getAttribute("data-pointy-state")).toBe("thinking");
    registry.setState("wiii", "pointing");
    expect(el?.getAttribute("data-pointy-state")).toBe("pointing");
  });

  it("setLabel updates the separate name pill div (v2.1 — label tách khỏi SVG)", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.setLabel("wiii", "Đang trỏ");
    const pillNode = document.querySelector(
      '[data-pointy-pill="wiii"]',
    ) as HTMLElement | null;
    expect(pillNode).not.toBeNull();
    expect(pillNode!.textContent).toBe("Đang trỏ");
    expect(pillNode!.getAttribute("aria-label")).toBe("Đang trỏ");
  });

  it("name pill is a separate div sibling, not inside the cursor SVG", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const cursor = document.querySelector('[data-pointy-cursor="wiii"]');
    const pill = document.querySelector('[data-pointy-pill="wiii"]');
    expect(cursor).not.toBeNull();
    expect(pill).not.toBeNull();
    // Pill must NOT be a descendant of the cursor SVG.
    expect(cursor?.contains(pill as Node)).toBe(false);
    expect(pill?.tagName.toLowerCase()).toBe("div");
  });

  it("cursor SVG is 28x28 viewBox (v2.2 — bumped from 24, vẫn gọn vs v2's 124x62)", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(cursor?.getAttribute("viewBox")).toBe("0 0 28 28");
    expect(cursor?.getAttribute("width")).toBe("28");
    expect(cursor?.getAttribute("height")).toBe("28");
  });

  it("cursor path is color-tinted (fill = identity color, NOT pure black)", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const path = document.querySelector(
      '[data-pointy-cursor="wiii"] path',
    );
    // Wiii orange = #F97316
    expect(path?.getAttribute("fill")).toBe("#F97316");
    expect(path?.getAttribute("stroke")).toBe("white");
    // v2.2: stroke-width 1.5 → 1.7 (giữ tỷ lệ visual khi viewBox lớn hơn).
    expect(path?.getAttribute("stroke-width")).toBe("1.7");
  });

  it("transform position is rounded to integer pixels (kill jitter)", () => {
    registry.upsert(WIII_IDENTITY, { x: 100, y: 100 });
    // Force a tick with sub-pixel target
    registry.upsert(WIII_IDENTITY, { x: 123.456789, y: 987.654321 });
    for (let i = 0; i < 200; i++) registry.tick(1 / 60);
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const transform = cursor!.style.transform;
    // v2.2: transform string giờ có thêm rotate + scale, nhưng
    // translate3d phần đầu vẫn phải là integer pixel.
    const match = /translate3d\(([\d.]+)px, ([\d.]+)px/.exec(transform);
    expect(match).not.toBeNull();
    if (match) {
      const x = parseFloat(match[1]);
      const y = parseFloat(match[2]);
      // Must be whole numbers, no fractional parts.
      expect(x).toBe(Math.floor(x));
      expect(y).toBe(Math.floor(y));
    }
  });

  it("transform composes translate3d + rotate + scale in one string (v2.2)", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.upsert(WIII_IDENTITY, { x: 500, y: 0 });
    // Tick a few frames so velocity is non-zero — rotation + scale should kick in.
    for (let i = 0; i < 5; i++) registry.tick(1 / 60);
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const transform = cursor!.style.transform;
    expect(transform).toMatch(/translate3d\(/);
    expect(transform).toMatch(/rotate\(/);
    expect(transform).toMatch(/scale\(/);
    // Order must be translate → rotate → scale (rotate around translated origin).
    expect(transform.indexOf("translate3d")).toBeLessThan(transform.indexOf("rotate"));
    expect(transform.indexOf("rotate")).toBeLessThan(transform.indexOf("scale"));
  });

  it("rotation stays within ±6° clamp regardless of velocity direction", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    // Aggressive horizontal motion — velocity direction is +X (atan2 = 0).
    registry.upsert(WIII_IDENTITY, { x: 5000, y: 0 });
    for (let i = 0; i < 3; i++) registry.tick(1 / 60);
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const transform = cursor!.style.transform;
    const m = /rotate\((-?[\d.]+)deg\)/.exec(transform);
    expect(m).not.toBeNull();
    const rotation = parseFloat(m![1]);
    expect(rotation).toBeGreaterThanOrEqual(-6);
    expect(rotation).toBeLessThanOrEqual(6);
  });

  it("scale stays within [1.0, 1.10] velocity-mapped range", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.upsert(WIII_IDENTITY, { x: 9999, y: 0 });
    for (let i = 0; i < 3; i++) registry.tick(1 / 60);
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const transform = cursor!.style.transform;
    const m = /scale\(([\d.]+)\)/.exec(transform);
    expect(m).not.toBeNull();
    const scale = parseFloat(m![1]);
    expect(scale).toBeGreaterThanOrEqual(1.0);
    expect(scale).toBeLessThanOrEqual(1.10);
  });

  it("v3.0: dock state sets opacity 0.75 (breathing animation drives the rest)", () => {
    registry.upsert(WIII_IDENTITY, { x: 1000, y: 700 });
    registry.setState("wiii", "dock");
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(cursor?.style.opacity).toBe("0.75");
    expect(cursor?.getAttribute("data-pointy-state")).toBe("dock");
    // Pill mirror state attribute cho CSS animation hook.
    const pill = document.querySelector(
      '[data-pointy-pill="wiii"]',
    ) as HTMLElement | null;
    expect(pill?.getAttribute("data-pointy-state")).toBe("dock");
  });

  it("v3.0: docked cursor is NOT auto-removed by maybeFade (persistent)", () => {
    registry.upsert(WIII_IDENTITY, { x: 1000, y: 700 });
    registry.setState("wiii", "dock");
    // Force ageMs > removeAfterMs by manipulating lastUpdateAt directly.
    const internal = (registry as unknown as {
      cursors: Map<string, { lastUpdateAt: number }>;
    }).cursors.get("wiii");
    if (internal) internal.lastUpdateAt = 0; // ancient timestamp
    // Trigger maybeFade by ticking.
    registry.tick(1 / 60);
    // Cursor should STILL exist (dock state persistent).
    expect(registry.ids()).toContain("wiii");
    expect(document.querySelector('[data-pointy-cursor="wiii"]')).not.toBeNull();
  });

  it("v3.0: global styles injected on first registry construction", () => {
    // Construct registry → ensureGlobalStyles called.
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const styleEl = document.head.querySelector(
      'style[data-pointy-global-styles]',
    );
    expect(styleEl).not.toBeNull();
    expect(styleEl?.textContent).toContain("pointy-dock-breathe");
    expect(styleEl?.textContent).toContain("pointy-error-shake");
  });

  it("rotation returns to 0 + scale to 1.0 when cursor settles (no jitter at rest)", () => {
    registry.upsert(WIII_IDENTITY, { x: 200, y: 200 });
    // Run many ticks until interp settles.
    for (let i = 0; i < 600; i++) registry.tick(1 / 60);
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const transform = cursor!.style.transform;
    const rot = parseFloat((/rotate\((-?[\d.]+)deg\)/.exec(transform) ?? ["", "0"])[1]);
    const sc = parseFloat((/scale\(([\d.]+)\)/.exec(transform) ?? ["", "1"])[1]);
    // At rest: rotation 0°, scale 1.000.
    expect(Math.abs(rot)).toBeLessThan(0.01);
    expect(sc).toBeCloseTo(1.0, 3);
  });

  it("does NOT inject CSS keyframes (pointy-bob / pointy-live-pulse) — would jitter against JS transform", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const cursor = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    const innerHTML = cursor?.innerHTML || "";
    expect(innerHTML).not.toContain("pointy-bob");
    expect(innerHTML).not.toContain("pointy-live-pulse");
    expect(innerHTML).not.toContain("@keyframes");
    // No green pulse ring either.
    expect(innerHTML).not.toContain("pointy-live-ring");
    expect(cursor?.querySelector(".pointy-live-ring")).toBeNull();
  });

  it("remove fades the cursor and detaches it after timeout", async () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.remove("wiii");
    // Immediately set to opacity 0 + state 'gone'
    const el = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as HTMLElement | null;
    expect(el?.style.opacity).toBe("0");
    // Wait past the 500ms detach timeout.
    await new Promise((r) => setTimeout(r, 550));
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(0);
    expect(registry.ids()).toEqual([]);
  });

  it("dispose tears down all cursors immediately", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.upsert(identityFor("peer", "Bro"), { x: 100, y: 100 });
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(2);
    registry.dispose();
    expect(document.querySelectorAll("[data-pointy-cursor]")).toHaveLength(0);
    expect(registry.ids()).toEqual([]);
  });

  it("upsert with new target redirects mid-flight via tick", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    registry.upsert(WIII_IDENTITY, { x: 500, y: 500 });
    // Manual ticks should drive the spring toward (500, 500).
    for (let i = 0; i < 200; i++) {
      registry.tick(1 / 60);
    }
    const el = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(el).not.toBeNull();
    const transform = el!.style.transform;
    // translate3d(<near 500>px, <near 500>px, 0)
    expect(transform).toContain("translate3d(");
    const match = /translate3d\(([\d.]+)px, ([\d.]+)px/.exec(transform);
    expect(match).not.toBeNull();
    if (match) {
      expect(parseFloat(match[1])).toBeGreaterThan(490);
      expect(parseFloat(match[2])).toBeGreaterThan(490);
    }
  });

  it("emits unique data-pointy-role per identity role", () => {
    registry.upsert(WIII_IDENTITY, { x: 0, y: 0 });
    const peer = identityFor("peer", "Bro");
    registry.upsert(peer, { x: 0, y: 0 });
    const aiCursor = document.querySelector('[data-pointy-cursor="wiii"]');
    const peerCursor = document.querySelector('[data-pointy-cursor="peer"]');
    expect(aiCursor?.getAttribute("data-pointy-role")).toBe("ai");
    expect(peerCursor?.getAttribute("data-pointy-role")).toBe("ai-peer");
  });

  it("uses pointer-events: none so the cursor never blocks clicks", () => {
    registry.upsert(WIII_IDENTITY, { x: 100, y: 100 });
    const el = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(el!.style.pointerEvents).toBe("none");
  });

  it("renders translate3d for GPU acceleration", () => {
    registry.upsert(WIII_IDENTITY, { x: 250, y: 175 });
    const el = document.querySelector(
      '[data-pointy-cursor="wiii"]',
    ) as SVGSVGElement | null;
    expect(el!.style.transform).toContain("translate3d(");
  });
});
