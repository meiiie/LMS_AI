/**
 * Wiii Pointy — spotlight overlay with tooltip.
 *
 * Dims the page (radial-gradient hole around the target) and shows a small
 * Vietnamese-first tooltip near the element. Pure DOM, no Driver.js dep.
 */

const OVERLAY_ID = "wiii-pointy-overlay";
const TARGET_RING_ID = "wiii-pointy-target-ring";
const TOOLTIP_ID = "wiii-pointy-tooltip";
const DISMISS_BUTTON_ID = "wiii-pointy-dismiss";
const BRAND_ORANGE = "#F97316";
const BRAND_CREAM = "#FAF5EE";
const PADDING = 8;

let overlayEl: HTMLDivElement | null = null;
let targetRingEl: HTMLDivElement | null = null;
let tooltipEl: HTMLDivElement | null = null;
let activeTimer: ReturnType<typeof setTimeout> | null = null;
let activeFollowFrame: number | null = null;
let activeDismissHandler: (() => void) | null = null;
let keydownInstalled = false;

function createOverlay(): HTMLDivElement {
  const el = document.createElement("div");
  el.id = OVERLAY_ID;
  el.setAttribute("data-wiii-pointy", "overlay");
  el.setAttribute("aria-hidden", "true");
  Object.assign(el.style, {
    position: "fixed",
    inset: "0",
    zIndex: "2147483645",
    pointerEvents: "none",
    background: "transparent",
    transition: "background 250ms ease-out",
  });
  return el;
}

function createTargetRing(): HTMLDivElement {
  const el = document.createElement("div");
  el.id = TARGET_RING_ID;
  el.setAttribute("data-wiii-pointy", "target-ring");
  el.setAttribute("aria-hidden", "true");
  Object.assign(el.style, {
    position: "fixed",
    zIndex: "2147483646",
    pointerEvents: "none",
    border: `3px solid ${BRAND_ORANGE}`,
    borderRadius: "14px",
    boxShadow: "0 0 0 7px rgba(249,115,22,0.18), 0 0 28px rgba(249,115,22,0.46)",
    opacity: "0",
    transform: "scale(0.96)",
    transition: "opacity 180ms ease-out, transform 180ms ease-out",
  });
  return el;
}

function createTooltip(): HTMLDivElement {
  const el = document.createElement("div");
  el.id = TOOLTIP_ID;
  el.setAttribute("data-wiii-pointy", "tooltip");
  el.setAttribute("role", "group");
  el.setAttribute("aria-live", "polite");
  el.setAttribute("aria-label", "Hướng dẫn Pointy");
  el.setAttribute("aria-hidden", "true");
  Object.assign(el.style, {
    position: "fixed",
    zIndex: "2147483647",
    pointerEvents: "auto",
    background: BRAND_CREAM,
    color: "#1F2937",
    border: `2px solid ${BRAND_ORANGE}`,
    borderRadius: "12px",
    padding: "8px 12px",
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontSize: "14px",
    fontWeight: "500",
    lineHeight: "1.45",
    maxWidth: "min(360px, calc(100vw - 24px))",
    boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
    opacity: "0",
    transform: "translateY(4px)",
    transition: "opacity 180ms ease-out, transform 180ms ease-out",
  });
  return el;
}

function ensureKeyboardDismiss(): void {
  if (keydownInstalled || typeof document === "undefined") return;
  document.addEventListener("keydown", handleKeydownDismiss);
  keydownInstalled = true;
}

function handleKeydownDismiss(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  if (!tooltipEl || tooltipEl.getAttribute("aria-hidden") === "true") return;
  event.preventDefault();
  dismissActiveSpotlight();
}

function dismissActiveSpotlight(): void {
  const onDismiss = activeDismissHandler;
  hideSpotlight();
  onDismiss?.();
}

function renderTooltipContent(
  tooltip: HTMLDivElement,
  message: string,
  dismissLabel: string,
): void {
  tooltip.replaceChildren();

  const wrap = document.createElement("div");
  Object.assign(wrap.style, {
    display: "grid",
    gap: "8px",
  });

  const text = document.createElement("span");
  text.textContent = message;
  Object.assign(text.style, {
    minWidth: "0",
    lineHeight: "1.45",
  });

  const actions = document.createElement("div");
  Object.assign(actions.style, {
    display: "flex",
    justifyContent: "flex-end",
    paddingTop: "2px",
  });

  const button = document.createElement("button");
  button.id = DISMISS_BUTTON_ID;
  button.type = "button";
  button.textContent = dismissLabel;
  button.setAttribute("aria-label", `${dismissLabel} hướng dẫn Pointy`);
  Object.assign(button.style, {
    flex: "0 0 auto",
    minHeight: "28px",
    minWidth: "58px",
    border: "1px solid rgba(249,115,22,0.42)",
    borderRadius: "999px",
    background: "rgba(249,115,22,0.1)",
    color: BRAND_ORANGE,
    cursor: "pointer",
    font: "inherit",
    fontSize: "12px",
    fontWeight: "700",
    padding: "3px 9px",
  });
  button.addEventListener("click", dismissActiveSpotlight);

  actions.appendChild(button);
  wrap.append(text, actions);
  tooltip.appendChild(wrap);
}

function ensureElements(): { overlay: HTMLDivElement; targetRing: HTMLDivElement; tooltip: HTMLDivElement } {
  if (!overlayEl || !overlayEl.isConnected) {
    overlayEl = createOverlay();
    document.body.appendChild(overlayEl);
  }
  if (!targetRingEl || !targetRingEl.isConnected) {
    targetRingEl = createTargetRing();
    document.body.appendChild(targetRingEl);
  }
  if (!tooltipEl || !tooltipEl.isConnected) {
    tooltipEl = createTooltip();
    document.body.appendChild(tooltipEl);
  }
  return { overlay: overlayEl, targetRing: targetRingEl, tooltip: tooltipEl };
}

function positionSpotlight(target: Element): void {
  if (!overlayEl || !targetRingEl || !tooltipEl) return;
  if (!target.isConnected) return;
  const rect = target.getBoundingClientRect();

  // Radial dim with a hole punched around the target.
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const r = Math.max(rect.width, rect.height) / 2 + PADDING;
  overlayEl.style.background = `radial-gradient(circle at ${cx}px ${cy}px, transparent 0px, transparent ${r}px, rgba(15,23,42,0.45) ${r + 24}px)`;

  const ringPad = Math.max(6, Math.min(14, Math.max(rect.width, rect.height) * 0.08));
  Object.assign(targetRingEl.style, {
    left: `${Math.max(4, rect.left - ringPad)}px`,
    top: `${Math.max(4, rect.top - ringPad)}px`,
    width: `${rect.width + ringPad * 2}px`,
    height: `${rect.height + ringPad * 2}px`,
    borderRadius: `${Math.min(18, Math.max(10, ringPad + 8))}px`,
    opacity: "1",
    transform: "scale(1)",
  });

  if (tooltipEl.getAttribute("aria-hidden") === "false") {
    const tRect = tooltipEl.getBoundingClientRect();
    const viewport = {
      width: window.innerWidth || document.documentElement.clientWidth,
      height: window.innerHeight || document.documentElement.clientHeight,
    };
    const { left, top } = computeTooltipPosition(rect, tRect, viewport);
    tooltipEl.style.left = `${left}px`;
    tooltipEl.style.top = `${top}px`;
  }
}

function startFollowingTarget(target: Element): void {
  stopFollowingTarget();
  const tick = () => {
    if (!target.isConnected || !targetRingEl || targetRingEl.style.opacity === "0") {
      activeFollowFrame = null;
      return;
    }
    positionSpotlight(target);
    activeFollowFrame = requestAnimationFrame(tick);
  };
  activeFollowFrame = requestAnimationFrame(tick);
}

function stopFollowingTarget(): void {
  if (activeFollowFrame !== null) {
    cancelAnimationFrame(activeFollowFrame);
    activeFollowFrame = null;
  }
}

/** Position tooltip below the target by default; flip above if it would overflow. */
export function computeTooltipPosition(
  targetRect: DOMRect,
  tooltipRect: { width: number; height: number },
  viewport: { width: number; height: number },
): { left: number; top: number } {
  const desiredLeft = Math.max(
    8,
    Math.min(
      targetRect.left + targetRect.width / 2 - tooltipRect.width / 2,
      viewport.width - tooltipRect.width - 8,
    ),
  );
  const wantsBelow = targetRect.bottom + tooltipRect.height + 12 <= viewport.height;
  const top = wantsBelow
    ? targetRect.bottom + 12
    : Math.max(8, targetRect.top - tooltipRect.height - 12);
  return { left: desiredLeft, top };
}

export interface SpotlightOptions {
  message?: string;
  duration_ms?: number;
  onClose?: () => void;
  onDismiss?: () => void;
  dismissLabel?: string;
}

export function showSpotlight(target: Element, opts: SpotlightOptions = {}): void {
  const { tooltip } = ensureElements();
  ensureKeyboardDismiss();

  if (opts.message) {
    activeDismissHandler = opts.onDismiss ?? null;
    renderTooltipContent(tooltip, opts.message, opts.dismissLabel ?? "Bỏ qua");
    tooltip.setAttribute("aria-hidden", "false");
    tooltip.style.opacity = "0";
    tooltip.style.transform = "translateY(4px)";
    positionSpotlight(target);
    requestAnimationFrame(() => {
      tooltip.style.opacity = "1";
      tooltip.style.transform = "translateY(0)";
    });
  } else {
    activeDismissHandler = null;
    tooltip.replaceChildren();
    tooltip.setAttribute("aria-hidden", "true");
    tooltip.style.opacity = "0";
    positionSpotlight(target);
  }
  startFollowingTarget(target);

  if (activeTimer) {
    clearTimeout(activeTimer);
    activeTimer = null;
  }
  const ms = Math.max(1500, Math.min(opts.duration_ms ?? 7000, 20000));
  activeTimer = setTimeout(() => {
    hideSpotlight();
    opts.onClose?.();
  }, ms);
}

export function hideSpotlight(): void {
  stopFollowingTarget();
  if (activeTimer) {
    clearTimeout(activeTimer);
    activeTimer = null;
  }
  if (overlayEl) overlayEl.style.background = "transparent";
  if (targetRingEl) {
    targetRingEl.style.opacity = "0";
    targetRingEl.style.transform = "scale(0.98)";
  }
  if (tooltipEl) {
    tooltipEl.replaceChildren();
    tooltipEl.setAttribute("aria-hidden", "true");
    tooltipEl.style.opacity = "0";
    tooltipEl.style.transform = "translateY(4px)";
  }
  activeDismissHandler = null;
}

export function destroySpotlight(): void {
  stopFollowingTarget();
  if (activeTimer) {
    clearTimeout(activeTimer);
    activeTimer = null;
  }
  for (const el of [overlayEl, targetRingEl, tooltipEl]) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }
  overlayEl = null;
  targetRingEl = null;
  tooltipEl = null;
  activeDismissHandler = null;
}

export const _testing = {
  OVERLAY_ID,
  TARGET_RING_ID,
  TOOLTIP_ID,
  DISMISS_BUTTON_ID,
  getOverlay: () => overlayEl,
  getTargetRing: () => targetRingEl,
  getTooltip: () => tooltipEl,
};
