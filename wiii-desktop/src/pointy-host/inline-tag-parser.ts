/**
 * Inline `[POINT:...]` tag parser (Wiii Pointy v4.0 — Clicky pattern).
 *
 * SOTA reference: farzaa/clicky (MIT, github April 2026).
 * Clicky's insight: Claude reliably outputs structured text tags inline
 * in its response. Parsing a tag from response text is far more robust
 * than building a 6-layer SSE pipeline (tool_call → dispatch → SSE →
 * presenter → handler → registry) where any layer breaks → cursor
 * doesn't move.
 *
 * Wiii v4.0 adopts the same pattern, adapted for our DOM-id-based
 * selector contract:
 *
 *   AI response: "Nút gửi ở góc dưới bên phải. [POINT:chat-send-button]"
 *                       ↓ frontend parse on stream complete
 *   parsePointTag("Nút gửi... [POINT:chat-send-button]")
 *                       ↓
 *   { stripped: "Nút gửi...", tag: { selector: "chat-send-button", caption: "" } }
 *                       ↓
 *   pointy.pointAt("chat-send-button", { caption: "" })
 *
 * Tag grammar (regex `[POINT:<exact-id>(:<caption>)?]` or `[POINT:none]`):
 *
 *   exact-id := [a-zA-Z][a-zA-Z0-9_-]* | auto:<tag>:<slug>
 *   caption  := any chars except `]`      (optional, trimmed)
 *
 * Tag MUST be at very end of response text (per WiiiDesktopHostAdapter
 * prompt). The parser is anchored to `\s*$` so internal `[POINT:...]`
 * mentions in code blocks / quotes don't accidentally trigger.
 */

const POINT_SELECTOR_PATTERN = String.raw`(?:auto:[a-z0-9_-]+:[a-z0-9_-]+(?:-\d+)?|[a-zA-Z][a-zA-Z0-9_-]*)`;

const POINT_TAG_REGEX = new RegExp(
  String.raw`\[POINT:(?:none|(${POINT_SELECTOR_PATTERN})(?::([^\]]*))?)\]\s*$`,
);

/** Global regex (no `$` anchor) — matches ALL `[POINT:...]` occurrences
 * anywhere in response, in order. Used for v7.0 multi-target queue. */
const POINT_TAG_GLOBAL = new RegExp(
  String.raw`\[POINT:(?:none|(${POINT_SELECTOR_PATTERN})(?::([^\]]*))?)\]`,
  "g",
);

export interface PointTag {
  /** Exact inventory id, including synthetic `auto:...` ids. */
  selector: string;
  /** Optional friendly caption shown next to cursor. */
  caption: string;
}

export interface PointTagParseResult {
  /** Original text with tag stripped + trailing whitespace trimmed. */
  stripped: string;
  /** Parsed tag, or null if no tag / `[POINT:none]`. */
  tag: PointTag | null;
}

/**
 * Extract `[POINT:...]` tag from end of LLM response text. Returns the
 * stripped text + parsed tag (or null when LLM said `[POINT:none]` or
 * no tag was emitted).
 *
 * Idempotent: calling on already-stripped text returns same text + null.
 */
export function parsePointTag(text: string): PointTagParseResult {
  if (!text) return { stripped: text, tag: null };
  const match = POINT_TAG_REGEX.exec(text);
  if (!match) return { stripped: text, tag: null };
  const selector = match[1]; // undefined when [POINT:none]
  const caption = (match[2] || "").trim();
  // Strip the tag + collapse trailing whitespace.
  const stripped = text.slice(0, match.index).replace(/[\s\n]+$/, "");
  if (!selector) {
    // [POINT:none] — strip but no dispatch.
    return { stripped, tag: null };
  }
  return { stripped, tag: { selector, caption } };
}

/**
 * True when text contains a `[POINT:...]` tag at end. Used by the
 * streaming-content stripper to decide whether to defer flushing.
 */
export function hasPointTag(text: string): boolean {
  return POINT_TAG_REGEX.test(text);
}

/**
 * v7.0 (2026-05-06) — Extract ALL `[POINT:...]` tags in order of
 * appearance. Supports multi-target sequence dispatch ("Click X then Y
 * then Z"). Anchored to global regex; not just end-of-text.
 *
 * Returns ordered array; consumers iterate to queue dispatches.
 * `[POINT:none]` entries are filtered (no-op signal). Returns also
 * the "stripped" text with all tags removed for display.
 */
export function parseAllPointTags(text: string): {
  tags: PointTag[];
  stripped: string;
} {
  if (!text) return { tags: [], stripped: text };
  const tags: PointTag[] = [];
  POINT_TAG_GLOBAL.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = POINT_TAG_GLOBAL.exec(text)) !== null) {
    const selector = match[1];
    if (!selector) continue; // [POINT:none]
    const caption = (match[2] || "").trim();
    tags.push({ selector, caption });
  }
  const stripped = text.replace(POINT_TAG_GLOBAL, "").replace(/\s+\n/g, "\n").trim();
  return { tags, stripped };
}
