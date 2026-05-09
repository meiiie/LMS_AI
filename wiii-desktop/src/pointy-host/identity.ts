/**
 * Cursor identity for Wiii Pointy v2 (multi-cursor architecture).
 *
 * Every cursor on screen has a stable identity (id + name + color +
 * avatar) — exactly the model Figma / Canva / Liveblocks ship for
 * multi-user cursors. Wiii's first identity is the AI itself; future
 * identities will include Sub-Souls (Living Agent peers via Soul
 * Bridge) and, if Wiii ever supports human collaboration, real users.
 *
 * Brand orange ``#F97316`` is reserved for Wiii itself. Other cursors
 * pick from a 12-colour palette via stable hash of their session id, so
 * the same peer always gets the same colour across reconnects. This is
 * the same scheme Figma uses to keep cursor colours visually distinct
 * without needing server-side colour assignment.
 *
 * Reference: ``research-multiplayer-cursors-sota-2026-05-06.md``
 */

export type CursorRole = "ai" | "ai-peer" | "user";

export type AwarenessState =
  | "idle"      // present but not moving
  | "moving"    // pursuing a new target
  | "pointing"  // settled on a designated target with caption
  | "thinking"  // AI computing next move; gentle bob, no spotlight
  | "clicking"  // brief scale animation + ripple
  | "gone"      // faded out, awaiting removal
  | "dock"      // v3.0 Battleship: docked at corner, breathing, "ready for orders"
  | "returning"; // v3.0: motion từ target → dock (sau khi action complete)

export interface CursorIdentity {
  /** Stable id; same id = same cursor across reconnects. */
  id: string;
  /** Display name shown on the badge ("Wiii", "Bro", "Alex"). */
  name: string;
  /** Single character or short emoji on the avatar circle. */
  avatar: string;
  /** Hex colour for cursor body + name pill background. */
  color: string;
  /** Role drives icon variant + reserved colour rules. */
  role: CursorRole;
}

/** Wiii's own AI cursor — the canonical identity. */
export const WIII_IDENTITY: CursorIdentity = {
  id: "wiii",
  name: "Wiii",
  avatar: "W",
  color: "#F97316",
  role: "ai",
};

/**
 * 12-colour palette for non-Wiii cursors. First entry (Wiii orange) is
 * reserved and never assigned via ``identityFor()``. Order is the
 * Figma-style "perceptually distinct" sequence so adjacent cursors
 * never collide visually.
 */
export const CURSOR_PALETTE: readonly string[] = [
  "#F97316", // Wiii orange — RESERVED for the AI itself
  "#85CDCA", // Wiii teal
  "#FFD166", // Wiii yellow
  "#EF4444", // red
  "#A78BFA", // purple
  "#34D399", // emerald
  "#60A5FA", // blue
  "#FB7185", // rose
  "#FACC15", // amber
  "#22C55E", // green
  "#06B6D4", // cyan
  "#F472B6", // pink
] as const;

/**
 * djb2 string hash — fast, stable, no crypto needed for colour assignment.
 */
function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * Pick a stable colour for a non-Wiii session id. Same id always gets
 * the same colour (modulo palette length). Skips the Wiii orange entry
 * so AI's identity stays unique.
 */
export function colorForSessionId(id: string): string {
  if (id === WIII_IDENTITY.id) return WIII_IDENTITY.color;
  const usable = CURSOR_PALETTE.length - 1; // skip reserved Wiii orange at index 0
  const idx = (hashString(id) % usable) + 1;
  return CURSOR_PALETTE[idx];
}

/**
 * Build a cursor identity from a session id + display name. Useful when
 * Soul Bridge or another transport hands us "peer X just joined" and we
 * need to materialise a cursor identity on the spot.
 */
export function identityFor(
  id: string,
  name: string,
  options: { avatar?: string; role?: CursorRole } = {},
): CursorIdentity {
  if (id === WIII_IDENTITY.id) return WIII_IDENTITY;
  const avatar = options.avatar ?? deriveAvatar(name);
  return {
    id,
    name,
    avatar,
    color: colorForSessionId(id),
    role: options.role ?? "ai-peer",
  };
}

/** First grapheme of the name, uppercased. Falls back to "?". */
function deriveAvatar(name: string): string {
  const trimmed = (name || "").trim();
  if (!trimmed) return "?";
  // Use Intl.Segmenter when available so "✨ Bro" → "✨", not "?".
  // Cast through unknown because TS lib.es2020 lacks Intl.Segmenter; it's
  // present in every modern browser and Node 16+.
  try {
    const intlAny = Intl as unknown as {
      Segmenter?: new (
        locales?: string,
        options?: { granularity: "grapheme" | "word" | "sentence" },
      ) => { segment: (input: string) => Iterable<{ segment: string }> };
    };
    if (typeof Intl !== "undefined" && intlAny.Segmenter) {
      const seg = new intlAny.Segmenter(undefined, { granularity: "grapheme" });
      for (const part of seg.segment(trimmed)) {
        return part.segment.toUpperCase();
      }
    }
  } catch {
    // fall through
  }
  return trimmed.charAt(0).toUpperCase();
}
