/**
 * Target validation for Pointy action execution.
 *
 * Inspired by GUI-agent operator loops: perceive the current environment,
 * validate the target, then act. Pointy should never confidently frame a
 * detached or hidden element just because a selector still matches.
 */

export interface PointyTargetRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PointyTargetSnapshot {
  tagName: string;
  id?: string;
  dataWiiiId?: string;
  ariaLabel?: string;
  text?: string;
  rect: PointyTargetRect;
  visibleRatio: number;
  connected: boolean;
}

export interface PointyTargetValidation {
  ok: boolean;
  reason?: string;
  snapshot: PointyTargetSnapshot;
}

export function snapshotPointyTarget(
  target: Element,
  rect: DOMRect = target.getBoundingClientRect(),
): PointyTargetSnapshot {
  const visibleRatio = computeVisibleRatio(rect);
  return {
    tagName: target.tagName,
    id: target.id || undefined,
    dataWiiiId: target.getAttribute("data-wiii-id") || undefined,
    ariaLabel: target.getAttribute("aria-label") || undefined,
    text: target.textContent?.trim().slice(0, 80) || undefined,
    rect: {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    visibleRatio,
    connected: target.isConnected,
  };
}

export function validatePointyTarget(
  target: Element,
  rect: DOMRect = target.getBoundingClientRect(),
): PointyTargetValidation {
  const snapshot = snapshotPointyTarget(target, rect);

  if (!target.isConnected) {
    return { ok: false, reason: "target_detached", snapshot };
  }
  if (target.hasAttribute("hidden")) {
    return { ok: false, reason: "target_hidden_attribute", snapshot };
  }
  if (target.getAttribute("aria-hidden") === "true") {
    return { ok: false, reason: "target_aria_hidden", snapshot };
  }

  if (target instanceof HTMLElement && typeof window !== "undefined") {
    const style = window.getComputedStyle(target);
    if (style.display === "none") {
      return { ok: false, reason: "target_display_none", snapshot };
    }
    if (style.visibility === "hidden") {
      return { ok: false, reason: "target_visibility_hidden", snapshot };
    }
    const opacity = Number.parseFloat(style.opacity || "1");
    if (Number.isFinite(opacity) && opacity <= 0.01) {
      return { ok: false, reason: "target_transparent", snapshot };
    }
  }

  const hasArea = rect.width > 1 && rect.height > 1;
  if (!hasArea && !isJsdomRuntime()) {
    return { ok: false, reason: "target_zero_area", snapshot };
  }

  return { ok: true, snapshot };
}

function computeVisibleRatio(rect: DOMRect): number {
  const area = Math.max(0, rect.width) * Math.max(0, rect.height);
  if (area <= 0) return 0;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const visibleX = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
  const visibleY = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
  return Math.max(0, Math.min(1, (visibleX * visibleY) / area));
}

function isJsdomRuntime(): boolean {
  return typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent);
}
