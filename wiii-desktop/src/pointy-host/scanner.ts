/**
 * PageScanner — quét DOM tìm pointable elements (Wiii Pointy v2.4).
 *
 * Trả lời câu hỏi của user: "Wiii Pointy nhận biết được màn hình đang
 * có gì?". Module quét DOM, build inventory `PointyTarget[]` mà AI
 * có thể consume — tương tự pattern Anthropic Computer Use 2026
 * (accessibility tree → element registry).
 *
 * Selectors ưu tiên (thứ tự độ ổn định):
 *
 * 1. `[data-wiii-id]` — explicitly registered, frontend team duy trì.
 * 2. Element có `id` attribute.
 * 3. `<button>`, `<a href>`, `<input>` (HTML semantics).
 * 4. `[role="button"]`, `[role="link"]`, `[role="menuitem"]` (ARIA).
 *
 * Filter visibility:
 * - `getBoundingClientRect()` intersect viewport
 * - không có `display: none` / `visibility: hidden` / `opacity: 0`
 * - không có `disabled` / `aria-disabled="true"` / `aria-hidden="true"`
 *
 * Auto-refresh qua `MutationObserver` khi DOM thay đổi (throttled
 * 250ms để tránh CPU spike trên dynamic apps).
 *
 * Tham khảo: ``research-cursor-awareness-2026-05-06.md``
 */

import {
  syntheticIdFor,
  registerSyntheticId,
  resolveSyntheticId,
  clearSyntheticRegistry,
} from "./auto-discovery";

export type PointyTargetRole =
  | "button"
  | "link"
  | "input"
  | "menu"
  | "menuitem"
  | "tab"
  | "region"
  | "other";

export interface PointyTarget {
  /** Stable id — ưu tiên data-wiii-id, fallback CSS id, fallback generated. */
  id: string;
  /** CSS selector hoặc data-wiii-id form mà bridge resolve được. */
  selector: string;
  /** Human-readable label cho LLM tham khảo. */
  label: string;
  /** Vai trò ngữ nghĩa của element. */
  role: PointyTargetRole;
  /** Có data-wiii-click-safe="true"? Bridge chỉ cho phép click khi true. */
  click_safe: boolean;
  /** Optional click_kind metadata. */
  click_kind?: string;
  /** Bounding box (viewport coords). */
  bounds: { x: number; y: number; w: number; h: number };
  /** Element có visible trong viewport không? */
  visible: boolean;
  /** Tỉ lệ phần trong viewport [0..1]. 1 = fully visible. */
  in_viewport_ratio: number;
  /** v8.3 (2026-05-06) — synonym keywords for visual/icon descriptions
   * (e.g., "kẹp giấy" for attach button, "máy bay giấy" for send).
   * Read from `data-wiii-synonyms` comma-separated attribute. Used by
   * embodied parser as additional candidates + by backend prompt to
   * teach AI canonical label synonyms. */
  synonyms?: string[];
}

export interface ScannerOptions {
  /** Root để quét. Mặc định ``document.body``. */
  root?: HTMLElement;
  /** Có theo dõi DOM changes không? Mặc định true. */
  observe?: boolean;
  /** Throttle ms cho re-scan trên DOM mutation. */
  throttleMs?: number;
  /** Maximum số targets trả về (clip để LLM prompt không bloat). */
  maxTargets?: number;
}

const DEFAULT_THROTTLE_MS = 250;
const DEFAULT_MAX_TARGETS = 60;

const POINTY_SELECTORS = [
  "[data-wiii-id]",
  "button:not([disabled])",
  "a[href]",
  "input:not([type='hidden']):not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[role='button']:not([disabled])",
  "[role='link']",
  "[role='menuitem']",
  "[role='tab']",
].join(", ");

export class PageScanner {
  private root: HTMLElement;
  private observe: boolean;
  private throttleMs: number;
  private maxTargets: number;

  private observer: MutationObserver | null = null;
  private rescanTimer: ReturnType<typeof setTimeout> | null = null;
  private cachedTargets: PointyTarget[] = [];
  private subscribers: Set<(targets: PointyTarget[]) => void> = new Set();
  private disposed = false;

  constructor(options: ScannerOptions = {}) {
    this.root =
      options.root ??
      (typeof document !== "undefined" ? document.body : (null as never));
    this.observe = options.observe ?? true;
    this.throttleMs = options.throttleMs ?? DEFAULT_THROTTLE_MS;
    this.maxTargets = options.maxTargets ?? DEFAULT_MAX_TARGETS;

    // Initial scan + start observer.
    this.scan();
    if (this.observe && typeof MutationObserver !== "undefined") {
      this.startObserver();
    }
  }

  /** Trả về targets đã scan gần nhất. Cached, sub-ms. */
  getTargets(): PointyTarget[] {
    return [...this.cachedTargets];
  }

  /** Force scan ngay lập tức (bỏ qua throttle). Trả về fresh targets. */
  scanNow(): PointyTarget[] {
    return this.scan();
  }

  /** Subscribe để nhận target list mỗi lần re-scan. */
  subscribe(callback: (targets: PointyTarget[]) => void): () => void {
    this.subscribers.add(callback);
    // Immediately push current snapshot.
    callback(this.getTargets());
    return () => {
      this.subscribers.delete(callback);
    };
  }

  /** Tear down observer + clear cache. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stopObserver();
    if (this.rescanTimer) clearTimeout(this.rescanTimer);
    this.rescanTimer = null;
    this.subscribers.clear();
    this.cachedTargets = [];
  }

  // ────────────────────────────────────────────────────────────────────
  // Private: scan logic
  // ────────────────────────────────────────────────────────────────────

  private scan(): PointyTarget[] {
    if (this.disposed || !this.root) return this.cachedTargets;

    // v8.0 (2026-05-06) — clear synthetic ID registry at start of each
    // scan. describeElement() will re-register every visible element
    // with its current accessible name. WeakRef-based registry GC's old
    // entries naturally; this just ensures stale IDs from prior scan
    // don't shadow current DOM state.
    clearSyntheticRegistry();

    const elements = Array.from(
      this.root.querySelectorAll<HTMLElement>(POINTY_SELECTORS),
    );
    const targetsById = new Map<string, PointyTarget>();

    for (const el of elements) {
      if (!isUsableElement(el)) continue;
      const target = describeElement(el);
      if (!target) continue;
      const existing = targetsById.get(target.id);
      if (!existing || isBetterTarget(target, existing)) {
        targetsById.set(target.id, target);
      }
    }

    // Sort: visible first, then by id (stable order).
    const targets = Array.from(targetsById.values()).sort((a, b) => {
      if (a.visible !== b.visible) return a.visible ? -1 : 1;
      // Higher in_viewport_ratio first
      if (a.in_viewport_ratio !== b.in_viewport_ratio) {
        return b.in_viewport_ratio - a.in_viewport_ratio;
      }
      const areaA = a.bounds.w * a.bounds.h;
      const areaB = b.bounds.w * b.bounds.h;
      if (areaA !== areaB) return areaB - areaA;
      return a.id.localeCompare(b.id);
    });

    this.cachedTargets = targets.slice(0, this.maxTargets);

    // Notify subscribers.
    for (const cb of this.subscribers) {
      try {
        cb(this.getTargets());
      } catch (err) {
        console.warn("[POINTY_SCANNER] subscriber threw:", err);
      }
    }

    return this.cachedTargets;
  }

  private startObserver(): void {
    this.observer = new MutationObserver(() => this.scheduleRescan());
    this.observer.observe(this.root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "data-wiii-id",
        "data-wiii-role",
        "data-wiii-click-safe",
        "data-wiii-click-kind",
        "id",
        "disabled",
        "aria-hidden",
        "aria-disabled",
        "hidden",
        "role",
      ],
    });
  }

  private stopObserver(): void {
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
  }

  private scheduleRescan(): void {
    if (this.rescanTimer) return; // already scheduled
    this.rescanTimer = setTimeout(() => {
      this.rescanTimer = null;
      this.scan();
    }, this.throttleMs);
  }
}

// ────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────

function isUsableElement(el: HTMLElement): boolean {
  if (!el || !el.isConnected) return false;
  if (el.hasAttribute("hidden")) return false;
  if (el.getAttribute("aria-hidden") === "true") return false;
  // v7.0 F13 (2026-05-06): KEEP disabled buttons in inventory — they're
  // still pointable (cursor can highlight to teach "click here AFTER you
  // type"). Disabled state is reflected separately via `click_safe`
  // flag on the target. Excluding them caused chat-send-button (disabled
  // when input empty) to vanish from inventory → embodied parser only
  // saw chat-textarea (label "Nhập tin nhắn") and matched there instead.
  // if (el.getAttribute("aria-disabled") === "true") return false;
  // if (el instanceof HTMLButtonElement && el.disabled) return false;
  // if (el instanceof HTMLInputElement && el.disabled) return false;
  // Skip elements with computed display:none / visibility:hidden / opacity 0.
  // Lưu ý: trong jsdom, getComputedStyle thường trả về defaults và
  // getBoundingClientRect cho 0×0 (jsdom không tính layout). Vì vậy
  // KHÔNG dùng rect 0×0 làm tín hiệu reject — sẽ false-negative trong
  // tests. Layout-aware filtering áp dụng ở consumer (visible flag).
  if (typeof window !== "undefined" && window.getComputedStyle) {
    const style = window.getComputedStyle(el);
    if (style.display === "none") return false;
    if (style.visibility === "hidden") return false;
    if (parseFloat(style.opacity || "1") === 0) return false;
  }
  return true;
}

function isBetterTarget(candidate: PointyTarget, current: PointyTarget): boolean {
  if (candidate.visible !== current.visible) return candidate.visible;
  if (candidate.in_viewport_ratio !== current.in_viewport_ratio) {
    return candidate.in_viewport_ratio > current.in_viewport_ratio;
  }
  const candidateArea = candidate.bounds.w * candidate.bounds.h;
  const currentArea = current.bounds.w * current.bounds.h;
  if (candidateArea !== currentArea) return candidateArea > currentArea;
  // Later DOM candidates usually represent the currently mounted React surface
  // during short transitions between welcome and chat composers.
  return true;
}

function describeElement(el: HTMLElement): PointyTarget | null {
  const wiiiId = el.getAttribute("data-wiii-id") || "";
  const cssId = el.id || "";

  // Selector resolution priority — v8.0 (2026-05-06):
  //   1. data-wiii-id (frontend-team curated, most stable)
  //   2. CSS id attribute
  //   3. Synthetic auto-discovery ID from accessible name (WebMCP-style)
  // The third path means EVERY interactive element with a label becomes
  // pointable without manual annotation — Wiii reads the DOM as it is.
  let selector: string;
  let id: string;
  if (wiiiId) {
    selector = wiiiId;
    id = wiiiId;
  } else if (cssId) {
    selector = `#${cssId}`;
    id = cssId;
  } else {
    // Try synthetic auto-discovery. Compute accessible name, slugify,
    // assign a unique ID + register in the bidirectional map for
    // resolveSelector to look up.
    const synthId = syntheticIdFor(el, 0);
    if (!synthId) {
      // No identifying name → can't synthesize stable ID. Skip.
      return null;
    }
    // Disambiguate: if the base ID is already registered to a DIFFERENT
    // element, suffix with index until unique.
    let finalId = synthId;
    let dupeIndex = 1;
    while (true) {
      const existing = resolveSyntheticId(finalId);
      if (!existing || existing === el) break;
      finalId = syntheticIdFor(el, dupeIndex);
      dupeIndex += 1;
      if (dupeIndex > 32) {
        // Defensive: too many duplicates with same name → bail.
        return null;
      }
    }
    registerSyntheticId(finalId, el);
    selector = finalId;
    id = finalId;
  }

  const role = inferRole(el);
  const label = inferLabel(el);
  const clickSafe = el.getAttribute("data-wiii-click-safe") === "true";
  const clickKind = el.getAttribute("data-wiii-click-kind") || undefined;
  const rawSynonyms = el.getAttribute("data-wiii-synonyms") || "";
  const synonyms = rawSynonyms
    ? rawSynonyms
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length >= 2)
    : undefined;

  const rect = el.getBoundingClientRect();
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const visibleX = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
  const visibleY = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
  const visibleArea = visibleX * visibleY;
  const totalArea = rect.width * rect.height;
  const in_viewport_ratio = totalArea > 0 ? visibleArea / totalArea : 0;
  const visible = in_viewport_ratio > 0.5; // ≥50% in viewport

  return {
    id,
    selector,
    label,
    role,
    click_safe: clickSafe,
    click_kind: clickKind,
    synonyms,
    bounds: {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      w: Math.round(rect.width),
      h: Math.round(rect.height),
    },
    visible,
    in_viewport_ratio: Math.round(in_viewport_ratio * 100) / 100,
  };
}

function inferRole(el: HTMLElement): PointyTargetRole {
  const wiiiRole = el.getAttribute("data-wiii-role");
  if (
    wiiiRole === "button" ||
    wiiiRole === "link" ||
    wiiiRole === "input" ||
    wiiiRole === "menu" ||
    wiiiRole === "menuitem" ||
    wiiiRole === "tab" ||
    wiiiRole === "region" ||
    wiiiRole === "other"
  ) {
    return wiiiRole;
  }
  const ariaRole = el.getAttribute("role");
  if (ariaRole) {
    if (ariaRole === "button") return "button";
    if (ariaRole === "link") return "link";
    if (ariaRole === "menuitem") return "menuitem";
    if (ariaRole === "menu") return "menu";
    if (ariaRole === "tab") return "tab";
    if (ariaRole === "region" || ariaRole === "main") return "region";
  }
  const tag = el.tagName.toLowerCase();
  if (tag === "button") return "button";
  if (tag === "a") return "link";
  if (tag === "input" || tag === "textarea" || tag === "select") return "input";
  return "other";
}

function inferLabel(el: HTMLElement): string {
  // Priority: aria-label → title → text content → placeholder → tag name.
  const aria = el.getAttribute("aria-label");
  if (aria && aria.trim()) return clipLabel(aria);
  const title = el.getAttribute("title");
  if (title && title.trim()) return clipLabel(title);
  const text = (el.textContent || "").trim();
  if (text) return clipLabel(text);
  if (el instanceof HTMLInputElement) {
    if (el.placeholder) return clipLabel(el.placeholder);
    if (el.value) return clipLabel(el.value);
  }
  return el.tagName.toLowerCase();
}

function clipLabel(s: string, max: number = 60): string {
  const trimmed = s.replace(/\s+/g, " ").trim();
  return trimmed.length > max ? trimmed.slice(0, max - 1) + "…" : trimmed;
}

/**
 * Format targets cho LLM consume. Compact, dễ parse, không bloat prompt.
 *
 * Ưu tiên hiển thị visible elements; nếu không có visible (test env
 * jsdom không có layout, hoặc page chưa render), fallback liệt kê
 * off-screen targets — vẫn hữu ích cho LLM biết SCREEN có gì kể cả
 * khi visibility info thiếu.
 */
export function formatTargetsForLLM(
  targets: PointyTarget[],
  maxLines: number = 30,
): string {
  if (!targets.length) return "No pointable elements detected on screen.";
  const visible = targets.filter((t) => t.visible);
  const offscreen = targets.filter((t) => !t.visible);
  const lines: string[] = [];
  lines.push(
    `Pointable elements (${visible.length} visible, ${offscreen.length} off-screen):`,
  );
  // Use visible if available; otherwise fall back to all targets.
  const display = visible.length > 0 ? visible : targets;
  const top = display.slice(0, maxLines);
  for (const t of top) {
    const safe = t.click_safe ? " click_safe" : "";
    const kind = t.click_kind ? ` kind=${t.click_kind}` : "";
    const labelPart = t.label ? ` label=${JSON.stringify(t.label)}` : "";
    const visTag = t.visible ? "" : " offscreen";
    lines.push(
      `- id="${t.id}" role=${t.role}${labelPart}${safe}${kind}${visTag}`,
    );
  }
  if (display.length > maxLines) {
    lines.push(`… ${display.length - maxLines} more elements omitted.`);
  }
  return lines.join("\n");
}
