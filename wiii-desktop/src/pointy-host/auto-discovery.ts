/**
 * Auto-discovery synthetic IDs (Wiii Pointy v8.0 — 2026-05-06).
 *
 * SOTA reference (2026):
 * - Anthropic Computer Use 2026 — accessibility tree + grounding via
 *   computed names, no manual annotation required.
 * - WebMCP standard proposal — browsers expose semantic UI tree to AI.
 * - axe-core accessible-name computation — W3C ARIA Authoring spec.
 *
 * Architecture insight: requiring `data-wiii-id` on every element is
 * brittle. Most apps have hundreds of buttons/links/inputs that the AI
 * should be able to point at. Auto-discovery treats EVERY interactive
 * element as pointable by:
 *
 *   1. Computing the accessible name (aria-label > title > text > placeholder)
 *   2. Slugifying it into a stable ID (auto:button:gui-tin-nhan)
 *   3. Maintaining a bidirectional Map<id, Element> at scan time
 *   4. resolveSelector("auto:button:gui-tin-nhan") looks up the map
 *
 * The synthetic ID is REGENERATED on each scan (DOM may change). The
 * bidirectional Map is the source of truth — element refs are stored
 * via WeakRef so GC can reclaim removed elements.
 *
 * Why synthetic IDs over CSS selectors:
 * - CSS selectors are brittle (Tailwind classes change, indexes shift)
 * - aria-label-based selectors break on i18n
 * - synthetic IDs persist across re-renders as long as the accessible
 *   name is stable (which it should be for any production-quality app)
 */

const SLUG_NORM_RE = /[^\p{L}\p{N}\s]/gu;
const SPACES_RE = /\s+/g;

/** Strip diacritics + lowercase + collapse spaces to hyphens. */
function slugify(s: string): string {
  if (!s) return "";
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .replace(SLUG_NORM_RE, " ")
    .trim()
    .replace(SPACES_RE, "-")
    .slice(0, 60); // keep IDs reasonable length
}

/**
 * Compute the accessible name following axe-core / W3C accname-1.2
 * algorithm (Wiii Pointy v8.1, 2026-05-06).
 *
 * Halt-on-non-empty step order — axe-core canonical sequence:
 *   2B.1 — aria-labelledby (recursive IDREFs, joined by space)
 *   2C   — aria-label
 *   2D   — native text alt (host-language: <label for=>, alt, <legend>, <caption>)
 *   2E   — embedded control value (input value when used in label context)
 *   2F+H — name from subtree contents (button/link text)
 *   2G   — plain text node value
 *   2I   — title attribute (last resort, tooltip)
 *
 * Critical rule per axe-core source: WHITESPACE-ONLY names HALT the
 * algorithm — they don't fall through. This catches `aria-label=" "`
 * silent bugs.
 *
 * Reference: dequelabs/axe-core/blob/develop/lib/commons/text/accessible-text-virtual.js
 */
export function computeAccessibleName(el: Element): string {
  // Step 2B.1 — aria-labelledby (highest priority).
  const labelledby = el.getAttribute("aria-labelledby");
  if (labelledby) {
    const labels = labelledby
      .split(/\s+/)
      .map((id) => document.getElementById(id))
      .filter((n): n is HTMLElement => !!n)
      .map((n) => n.textContent?.trim() || "")
      .filter(Boolean);
    if (labels.length > 0) {
      const joined = labels.join(" ").trim();
      if (joined) return joined;
      // Per axe-core: whitespace-only halts. If labelledby resolved but
      // produced empty (all elements had whitespace-only), HALT here.
      return "";
    }
  }

  // Step 2C — aria-label.
  const ariaLabel = el.getAttribute("aria-label");
  if (ariaLabel !== null) {
    const trimmed = ariaLabel.trim();
    if (trimmed) return trimmed;
    // Whitespace-only aria-label HALTS (per axe-core canonical behavior).
    if (ariaLabel.length > 0) return "";
  }

  // Step 2D — native text alternative (host-language defined).
  // For form controls with associated <label> element via for= or wrapping.
  if (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement
  ) {
    if (el.id) {
      const associated = document.querySelector<HTMLLabelElement>(
        `label[for="${el.id.replace(/"/g, '\\"')}"]`,
      );
      if (associated) {
        const txt = associated.textContent?.trim();
        if (txt) return txt;
      }
    }
    // Wrapping <label>.
    const wrapping = el.closest("label");
    if (wrapping) {
      // Strip the input's own value/text.
      const clone = wrapping.cloneNode(true) as HTMLElement;
      const removed = clone.querySelector(`[id="${el.id}"]`);
      removed?.remove();
      const txt = clone.textContent?.trim();
      if (txt) return txt;
    }
  }
  if (el instanceof HTMLImageElement) {
    if (el.alt?.trim()) return el.alt.trim();
  }
  if (el instanceof HTMLFieldSetElement) {
    const legend = el.querySelector("legend");
    if (legend?.textContent?.trim()) return legend.textContent.trim();
  }
  if (el instanceof HTMLTableElement) {
    const caption = el.querySelector("caption");
    if (caption?.textContent?.trim()) return caption.textContent.trim();
  }

  // Step 2F+2H — name from subtree contents (for buttons, links).
  const tag = el.tagName.toLowerCase();
  if (
    tag === "button" ||
    tag === "a" ||
    tag === "summary" ||
    el.getAttribute("role") === "button" ||
    el.getAttribute("role") === "link"
  ) {
    const txt = el.textContent?.trim();
    if (txt) return txt.slice(0, 80);
  }

  // Step 2D continued — placeholder fallback for inputs (covered after
  // label since label is more authoritative).
  if (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement
  ) {
    if (el.placeholder?.trim()) return el.placeholder.trim();
  }

  // Step 2G — plain text content (for elements not covered by 2F).
  if (el.textContent?.trim()) return el.textContent.trim().slice(0, 80);

  // Step 2I — title (last-resort tooltip).
  const title = el.getAttribute("title");
  if (title?.trim()) return title.trim();

  return "";
}

/** Lowercase tag name with semantic role normalization. */
function tagToken(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute("role")?.toLowerCase();
  if (role && role !== tag) {
    // Use role for semantic clarity (e.g., div with role=button → "button").
    if (["button", "link", "menuitem", "menu", "tab"].includes(role)) {
      return role;
    }
  }
  // Normalize common tags.
  if (tag === "a") return "link";
  if (tag === "input") {
    const type = (el as HTMLInputElement).type?.toLowerCase() || "text";
    return `input-${type}`;
  }
  return tag;
}

/**
 * Build a stable synthetic ID for an element. Same element + same
 * accessible name → same ID across scans.
 *
 * Format: `auto:<tag>:<slug>` or `auto:<tag>:<slug>-<index>` for
 * disambiguation. Caller passes the index when multiple elements share
 * the base id.
 *
 * Returns empty string when element has no accessible name (skip).
 */
export function syntheticIdFor(el: Element, indexAmongDupes: number = 0): string {
  const name = computeAccessibleName(el);
  if (!name) return "";
  const slug = slugify(name);
  if (!slug) return "";
  const tag = tagToken(el);
  const base = `auto:${tag}:${slug}`;
  return indexAmongDupes > 0 ? `${base}-${indexAmongDupes}` : base;
}

/**
 * Synthetic ID registry — maps synthetic IDs back to live DOM elements.
 * Populated at scan time, consulted by `resolveSelector` for "auto:"
 * prefix selectors.
 *
 * Singleton: shared across all PageScanner instances on the same page.
 * WeakRef so removed elements get GC'd; we can't accidentally hold
 * references that prevent React from cleaning up.
 */
const _registry: Map<string, WeakRef<Element>> = new Map();

/**
 * Register an element with its synthetic ID. Overwrites any prior entry
 * (latest scan wins). Called by PageScanner during describeElement().
 */
export function registerSyntheticId(id: string, el: Element): void {
  if (!id) return;
  _registry.set(id, new WeakRef(el));
}

/** Look up the live element for a synthetic ID. Returns null when GC'd
 * or never registered. Caller should fall back to other resolution paths. */
export function resolveSyntheticId(id: string): Element | null {
  const ref = _registry.get(id);
  if (!ref) return null;
  const el = ref.deref();
  if (!el) {
    _registry.delete(id);
    return null;
  }
  // Verify still in DOM (element may have been removed without GC).
  if (!el.isConnected) {
    _registry.delete(id);
    return null;
  }
  return el;
}

/** Drop the entire registry. Called when scanner re-scans from scratch. */
export function clearSyntheticRegistry(): void {
  _registry.clear();
}

/** Diagnostic: registry size. */
export function syntheticRegistrySize(): number {
  return _registry.size;
}
