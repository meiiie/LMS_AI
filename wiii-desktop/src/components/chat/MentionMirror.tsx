/**
 * Mention mirror overlay (Wiii Pointy v3.0 — Phase 2 inline highlight).
 *
 * Absolute-positioned div BEHIND the textarea với identical font /
 * padding / wrapping. Plain text in mirror is fully transparent (chỉ
 * reserve spacing); ``@<skill-id>`` mentions render as colored
 * background bleed-through behind textarea text.
 *
 * Background-only (no padding chip with icon) — adding padding hoặc
 * inline icon sẽ shift mention text width vs textarea, breaking
 * pixel-perfect alignment. Slack / Discord / Linear all use this
 * approach for in-textarea mentions.
 */

import { tokenizeMentions, SKILL_VISUAL_BY_ID, FALLBACK_VISUAL } from "./mention-segments";

interface MentionMirrorProps {
  text: string;
  /** Same className as the textarea so font / line-height / padding match. */
  className: string;
}

export function MentionMirror({ text, className }: MentionMirrorProps) {
  const segments = tokenizeMentions(text);
  if (segments.length === 0 || !segments.some((s) => s.type === "mention")) {
    return null;
  }
  return (
    <div
      aria-hidden="true"
      data-wiii-id="mention-mirror"
      className={`absolute inset-0 pointer-events-none whitespace-pre-wrap break-words overflow-hidden text-transparent ${className}`}
    >
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          return <span key={i}>{seg.content}</span>;
        }
        const visual = seg.canonicalId
          ? SKILL_VISUAL_BY_ID[seg.canonicalId] ?? FALLBACK_VISUAL
          : FALLBACK_VISUAL;
        return (
          <span
            key={i}
            data-mention-id={seg.canonicalId}
            className={visual.highlightBg}
          >
            {seg.content}
          </span>
        );
      })}
    </div>
  );
}
