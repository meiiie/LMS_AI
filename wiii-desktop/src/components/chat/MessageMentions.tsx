/**
 * Message-bubble mention renderer (Wiii Pointy v3.0 — Phase 2 persist).
 *
 * Khi user đã send message với `@plugin-name` mention, bubble trong
 * chat history hiển thị chip có icon + colored background — KHÔNG strip
 * mention thành plain text. Đây là pattern ChatGPT plugins, Cursor
 * `@codebase`, Claude Code `@file`: mention persist visible across
 * conversation history để user thấy ngay "tôi đã invoke skill nào".
 *
 * Khác với MentionMirror (overlay invisible-text behind textarea), đây
 * là VISIBLE rendering với full chip styling: icon + label + colored
 * pill background. Layout matters less because this is post-send static
 * content, không cần align với textarea.
 */

import { tokenizeMentions, SKILL_VISUAL_BY_ID, FALLBACK_VISUAL } from "./mention-segments";

interface MessageMentionsProps {
  text: string;
  /** Inherit text styles from parent paragraph. */
  className?: string;
}

/**
 * Render text with `@mention` segments as inline pill chips. Plain text
 * runs render verbatim, mentions render as `<span>` chip với:
 *
 *   - Lucide skill icon (12-13px)
 *   - Skill label (e.g., "Wiii Pointy") — friendly display name
 *   - Colored pill background + 1px border per skill palette
 *   - Tooltip showing the canonical id on hover
 *
 * Trade-off: chip displays the skill **label**, not the raw `@id` user
 * typed. This matches ChatGPT plugin behaviour (typing `@browser` in
 * input → chip says "Browser" not "@browser"). Easier reading, drops
 * one signal (typed alias vs canonical), acceptable.
 */
export function MessageMentions({ text, className }: MessageMentionsProps) {
  const segments = tokenizeMentions(text);
  if (segments.length === 0) {
    return <>{text}</>;
  }
  return (
    <span className={className}>
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          return <span key={i}>{seg.content}</span>;
        }
        const visual = seg.canonicalId
          ? SKILL_VISUAL_BY_ID[seg.canonicalId] ?? FALLBACK_VISUAL
          : FALLBACK_VISUAL;
        const Icon = visual.Icon;
        return (
          <span
            key={i}
            data-mention-id={seg.canonicalId}
            title={`@${seg.rawId} → ${seg.label}`}
            className={`inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 rounded-md text-[0.92em] font-medium align-baseline ${visual.chipBg} ${visual.chipFg}`}
          >
            <Icon size={13} strokeWidth={2.25} className="shrink-0" />
            <span>{seg.label}</span>
          </span>
        );
      })}
    </span>
  );
}
