/**
 * Shared mention tokenization + skill visual map (Wiii Pointy v3.0).
 *
 * Used by:
 *   - MentionMirror (overlay highlight behind textarea, invisible text)
 *   - MessageMentions (visible chips in user message bubble after send)
 *
 * Tokenizer splits raw text into ordered ``Segment[]`` so consumers can
 * render plain runs and mention runs differently. Visual map ties each
 * canonical skill id to a lucide icon + Tailwind color tokens.
 */

import { MousePointer2, Search, Sparkles, Puzzle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { SKILL_CATALOG } from "@/lib/skill-mentions";

const MENTION_RE = /(^|\s)@([a-z][a-z0-9-]*)/g;

const VALID_MENTION_IDS = new Set<string>(
  SKILL_CATALOG.flatMap((entry) => [entry.id, ...entry.aliases]),
);
const ALIAS_TO_CANONICAL = new Map<string, string>(
  SKILL_CATALOG.flatMap((entry) =>
    [
      [entry.id, entry.id] as [string, string],
      ...entry.aliases.map((a) => [a, entry.id] as [string, string]),
    ],
  ),
);

export interface SkillVisual {
  Icon: LucideIcon;
  /** Tailwind classes — chip background + border. */
  chipBg: string;
  /** Tailwind classes — chip text + icon stroke color. */
  chipFg: string;
  /** Tailwind classes — pure background highlight (no border) for inline mirror. */
  highlightBg: string;
}

export const SKILL_VISUAL_BY_ID: Record<string, SkillVisual> = {
  "wiii-pointy": {
    Icon: MousePointer2,
    chipBg:
      "bg-orange-100 dark:bg-orange-500/20 border border-orange-300/60 dark:border-orange-500/30",
    chipFg: "text-orange-700 dark:text-orange-300",
    highlightBg: "bg-orange-200/70 dark:bg-orange-500/30 rounded-[3px]",
  },
  "web-search": {
    Icon: Search,
    chipBg:
      "bg-sky-100 dark:bg-sky-500/20 border border-sky-300/60 dark:border-sky-500/30",
    chipFg: "text-sky-700 dark:text-sky-300",
    highlightBg: "bg-sky-200/70 dark:bg-sky-500/30 rounded-[3px]",
  },
  "visual-code-gen": {
    Icon: Sparkles,
    chipBg:
      "bg-violet-100 dark:bg-violet-500/20 border border-violet-300/60 dark:border-violet-500/30",
    chipFg: "text-violet-700 dark:text-violet-300",
    highlightBg: "bg-violet-200/70 dark:bg-violet-500/30 rounded-[3px]",
  },
};
export const FALLBACK_VISUAL: SkillVisual = {
  Icon: Puzzle,
  chipBg: "bg-surface-tertiary border border-[var(--border)]",
  chipFg: "text-text-secondary",
  highlightBg: "bg-surface-tertiary rounded-[3px]",
};

export interface MentionSegment {
  type: "text" | "mention";
  content: string;
  /** Canonical id (only for mention segments — alias resolved). */
  canonicalId?: string;
  /** Raw typed form including alias (e.g., "@pointy" even when canonical
   *  is "wiii-pointy"). Used for accurate text reconstruction. */
  rawId?: string;
  /** Friendly label from SKILL_CATALOG. */
  label?: string;
}

/** Split text into ordered plain/mention segments. Unknown ids are
 * kept as plain text (no chip rendered). */
export function tokenizeMentions(text: string): MentionSegment[] {
  if (!text) return [];
  const segs: MentionSegment[] = [];
  let lastIndex = 0;
  MENTION_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = MENTION_RE.exec(text)) !== null) {
    const leading = m[1];
    const typedId = m[2];
    if (!VALID_MENTION_IDS.has(typedId)) continue;
    const atStart = m.index + leading.length;
    if (atStart > lastIndex) {
      segs.push({ type: "text", content: text.slice(lastIndex, atStart) });
    }
    const canonical = ALIAS_TO_CANONICAL.get(typedId) ?? typedId;
    const entry = SKILL_CATALOG.find((e) => e.id === canonical);
    segs.push({
      type: "mention",
      content: `@${typedId}`,
      canonicalId: canonical,
      rawId: typedId,
      label: entry?.label ?? canonical,
    });
    lastIndex = atStart + m[0].length - leading.length;
  }
  if (lastIndex < text.length) {
    segs.push({ type: "text", content: text.slice(lastIndex) });
  }
  return segs;
}

/** True when text contains at least one valid mention. */
export function hasMention(text: string): boolean {
  return tokenizeMentions(text).some((s) => s.type === "mention");
}
