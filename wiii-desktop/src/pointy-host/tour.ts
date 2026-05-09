/**
 * Wiii Pointy — multi-step tour sequencer.
 *
 * Walks through TourStep[] one at a time, scrolling, moving the cursor,
 * and showing the spotlight + tooltip for each step in turn. A new tour
 * cancels any tour in progress so the AI can interrupt itself cleanly.
 */
import type { TourStep } from "./types";
import { hideCursor, moveCursorToRect } from "./cursor";
import { hideSpotlight, showSpotlight } from "./spotlight";
import { refreshDomBeforePointyAction } from "./dom-refresh";

let activeTour: { cancelled: boolean } | null = null;

export interface RunTourOptions {
  resolveSelector?: (selector: string) => Element | null;
  /** Step index to start from (0-based). */
  startAt?: number;
}

const DEFAULT_RESOLVE = (sel: string) =>
  typeof document !== "undefined" ? document.querySelector(sel) : null;

export interface TourResult {
  completed_steps: number;
  total_steps: number;
  cancelled: boolean;
  missing_selectors: string[];
}

export async function runTour(
  steps: TourStep[],
  opts: RunTourOptions = {},
): Promise<TourResult> {
  if (activeTour) activeTour.cancelled = true;
  const handle = { cancelled: false };
  activeTour = handle;

  const resolve = opts.resolveSelector ?? DEFAULT_RESOLVE;
  const startAt = Math.max(0, Math.min(opts.startAt ?? 0, steps.length));
  const result: TourResult = {
    completed_steps: 0,
    total_steps: steps.length,
    cancelled: false,
    missing_selectors: [],
  };

  for (let i = startAt; i < steps.length; i++) {
    if (handle.cancelled) break;
    const step = steps[i];
    refreshDomBeforePointyAction("tourStep");
    const target = resolve(step.selector);
    if (!target) {
      result.missing_selectors.push(step.selector);
      continue;
    }

    const rect = target instanceof HTMLElement
      ? scrollIntoViewIfNeeded(target, target.getBoundingClientRect())
      : target.getBoundingClientRect();
    moveCursorToRect(rect, { duration_ms: 500 });

    showSpotlight(target, {
      message: step.message,
      duration_ms: step.duration_ms ?? 2400,
      onDismiss: () => cancelActiveTour(),
    });

    await interruptibleWait(step.duration_ms ?? 2400, handle);
    if (handle.cancelled) break;
    result.completed_steps += 1;
  }

  result.cancelled = handle.cancelled;

  if (activeTour === handle) {
    hideSpotlight();
    hideCursor();
    activeTour = null;
  }
  return result;
}

export function cancelActiveTour(): void {
  if (activeTour) activeTour.cancelled = true;
  hideSpotlight();
  hideCursor();
}

function interruptibleWait(ms: number, handle: { cancelled: boolean }): Promise<void> {
  return new Promise((resolve) => {
    const end = Date.now() + Math.max(0, ms);
    const tick = () => {
      if (handle.cancelled) {
        resolve();
        return;
      }
      const remaining = end - Date.now();
      if (remaining <= 0) {
        resolve();
        return;
      }
      setTimeout(tick, Math.min(20, remaining));
    };
    tick();
  });
}

function scrollIntoViewIfNeeded(target: HTMLElement, rect: DOMRect): DOMRect {
  if (typeof target.scrollIntoView !== "function") return rect;
  if (isMostlyVisible(rect)) return rect;
  target.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });
  return target.getBoundingClientRect();
}

function isMostlyVisible(rect: DOMRect): boolean {
  const area = Math.max(0, rect.width) * Math.max(0, rect.height);
  if (area <= 0) return true;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const visibleX = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
  const visibleY = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
  return (visibleX * visibleY) / area >= 0.9;
}

export const _testing = {
  hasActiveTour: () => activeTour !== null,
  resetState: () => {
    if (activeTour) activeTour.cancelled = true;
    activeTour = null;
  },
};
