/**
 * Dock position helper (Wiii Pointy v3.0 — Battleship pattern).
 *
 * Dock = "home position" của Wiii cursor ở góc bottom-right màn hình.
 * Cursor luôn visible ở dock khi idle (breathing pulse), fly out khi
 * AI invoke pointy → settle on target → return về dock.
 *
 * Architecture:
 *
 * - Bottom-right corner: anchor cố định, persistent across viewport changes
 * - Insets từ edges: 80px desktop / 56px mobile để không che native UI
 * - Responsive recompute trên window resize (subscribe pattern)
 *
 * Tham khảo: ``research-cursor-art-sota-2026-05-06.md`` (Battleship pattern
 * section), screenshot test case khi user feedback "cursor không hiện",
 * silent fail mode discussion.
 */

import type { Vec2 } from "./interpolator";

export interface DockConfig {
  /** Inset from right edge (px). Default 80 desktop, 56 mobile. */
  rightInset: number;
  /** Inset from bottom edge (px). Default 80 desktop, 56 mobile. */
  bottomInset: number;
}

const DESKTOP_INSET = 80;
const MOBILE_INSET = 56;
const MOBILE_WIDTH_THRESHOLD = 640;

/**
 * Compute dock position dựa vào current viewport. Responsive: smaller
 * inset trên mobile để không che bottom navigation hoặc kbd.
 */
export function computeDockPosition(
  vw: number = typeof window !== "undefined" ? window.innerWidth : 1024,
  vh: number = typeof window !== "undefined" ? window.innerHeight : 768,
): Vec2 {
  const isMobile = vw < MOBILE_WIDTH_THRESHOLD;
  const inset = isMobile ? MOBILE_INSET : DESKTOP_INSET;
  return {
    x: vw - inset,
    y: vh - inset,
  };
}

/**
 * Subscribe to dock position updates trên window resize. Trả về
 * unsubscribe function. Throttled qua rAF để không thrash trong khi
 * user đang resize window.
 */
export function subscribeDockPosition(
  callback: (pos: Vec2) => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  let rafHandle = 0;
  const handler = () => {
    if (rafHandle) return;
    rafHandle = requestAnimationFrame(() => {
      rafHandle = 0;
      callback(computeDockPosition());
    });
  };
  window.addEventListener("resize", handler, { passive: true });
  // Initial fire.
  callback(computeDockPosition());
  return () => {
    window.removeEventListener("resize", handler);
    if (rafHandle) cancelAnimationFrame(rafHandle);
  };
}

/**
 * Get config dock cho given viewport. Useful nếu callers muốn tuỳ chỉnh
 * inset (e.g., extra padding cho có chat composer ở bottom).
 */
export function getDockConfig(
  vw: number = typeof window !== "undefined" ? window.innerWidth : 1024,
): DockConfig {
  const isMobile = vw < MOBILE_WIDTH_THRESHOLD;
  const inset = isMobile ? MOBILE_INSET : DESKTOP_INSET;
  return {
    rightInset: inset,
    bottomInset: inset,
  };
}
