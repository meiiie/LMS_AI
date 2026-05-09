/**
 * Mention picker — `@`-trigger autocomplete dropdown (Wiii Pointy v3.0).
 *
 * Khi user gõ `@` trong ChatInput, popup hiển thị danh sách skills
 * available (Wiii Pointy, Web Search, Code Studio) — chuẩn UX 2026
 * (ChatGPT plugins, Cursor `@codebase`, GitHub Copilot `@workspace`,
 * Claude Code `@file`, Cline `@docs`).
 *
 * Component thuần presentational: receives suggestions + selected index,
 * fires `onSelect` khi click. ChatInput owns keyboard navigation +
 * detection lifecycle qua ``detectMentionTyping`` + ``suggestMentions``.
 *
 * Layout: anchored above textarea (bottom-full + left-0). Single column
 * vertical list, max-height auto-scroll. Each row: skill icon + label
 * + description (label bold khi match prefix).
 */

import { useEffect, useRef } from "react";
import { MousePointer2, Search, Sparkles, Puzzle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { MentionSuggestion } from "@/lib/skill-mentions";

interface MentionPickerProps {
  suggestions: MentionSuggestion[];
  selectedIndex: number;
  fragment: string;
  onSelect: (suggestion: MentionSuggestion) => void;
  onHover: (index: number) => void;
}

interface SkillVisual {
  Icon: LucideIcon;
  /** Brand-tinted background for icon badge. */
  iconBg: string;
  /** Icon stroke color. */
  iconColor: string;
}

const SKILL_VISUAL_BY_ID: Record<string, SkillVisual> = {
  "wiii-pointy": {
    Icon: MousePointer2,
    iconBg: "bg-orange-100 dark:bg-orange-500/15",
    iconColor: "text-orange-600 dark:text-orange-400",
  },
  "web-search": {
    Icon: Search,
    iconBg: "bg-sky-100 dark:bg-sky-500/15",
    iconColor: "text-sky-600 dark:text-sky-400",
  },
  "visual-code-gen": {
    Icon: Sparkles,
    iconBg: "bg-violet-100 dark:bg-violet-500/15",
    iconColor: "text-violet-600 dark:text-violet-400",
  },
};
const FALLBACK_VISUAL: SkillVisual = {
  Icon: Puzzle,
  iconBg: "bg-surface-tertiary",
  iconColor: "text-text-secondary",
};

export function MentionPicker({
  suggestions,
  selectedIndex,
  fragment,
  onSelect,
  onHover,
}: MentionPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll selected item vào viewport khi keyboard nav.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const item = container.querySelector<HTMLElement>(
      `[data-mention-index="${selectedIndex}"]`,
    );
    // jsdom (test env) doesn't implement scrollIntoView — guard the call.
    if (item && typeof item.scrollIntoView === "function") {
      item.scrollIntoView({ block: "nearest", behavior: "instant" });
    }
  }, [selectedIndex]);

  if (suggestions.length === 0) return null;

  return (
    <div
      ref={containerRef}
      role="listbox"
      aria-label="Plugin suggestions"
      data-wiii-id="mention-picker"
      className="absolute bottom-full left-0 mb-2 w-[420px] max-w-[calc(100vw-2rem)] max-h-[280px] overflow-y-auto bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-lg z-50"
      // KHÔNG steal focus từ textarea — onMouseDown.preventDefault.
      onMouseDown={(e) => e.preventDefault()}
    >
      <div className="px-3 pt-2.5 pb-1 text-[11px] font-medium text-text-tertiary uppercase tracking-wide">
        Plugins
      </div>
      <div className="pb-1.5">
        {suggestions.map((s, i) => {
          const isSelected = i === selectedIndex;
          const visual = SKILL_VISUAL_BY_ID[s.entry.id] ?? FALLBACK_VISUAL;
          const Icon = visual.Icon;
          return (
            <button
              key={s.entry.id}
              type="button"
              role="option"
              aria-selected={isSelected}
              data-mention-index={i}
              onClick={() => onSelect(s)}
              onMouseEnter={() => onHover(i)}
              className={`w-full flex items-start gap-2.5 px-3 py-2 text-left transition-colors ${
                isSelected
                  ? "bg-[var(--accent-light)]"
                  : "hover:bg-surface-tertiary"
              }`}
            >
              <span
                className={`shrink-0 mt-0.5 inline-flex items-center justify-center w-7 h-7 rounded-md ${visual.iconBg}`}
              >
                <Icon size={15} strokeWidth={2} className={visual.iconColor} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span
                    className={`text-[13px] font-medium ${
                      isSelected ? "text-[var(--accent)]" : "text-text"
                    }`}
                  >
                    {highlightFragment(s.entry.label, fragment)}
                  </span>
                  <span className="text-[11px] text-text-tertiary tabular-nums">
                    @{s.entry.id}
                  </span>
                </div>
                <div className="text-[12px] text-text-secondary truncate">
                  {s.entry.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <div className="px-3 py-1.5 border-t border-[var(--border)] text-[10.5px] text-text-tertiary flex items-center gap-3">
        <kbd className="px-1 py-px rounded bg-surface-tertiary">↑↓</kbd>
        <span>chọn</span>
        <kbd className="px-1 py-px rounded bg-surface-tertiary">Enter</kbd>
        <span>chèn</span>
        <kbd className="px-1 py-px rounded bg-surface-tertiary">Esc</kbd>
        <span>đóng</span>
      </div>
    </div>
  );
}

/** Bold-highlight matched fragment trong label (case-insensitive). */
function highlightFragment(text: string, fragment: string): React.ReactNode {
  if (!fragment) return text;
  const lower = text.toLowerCase();
  const q = fragment.toLowerCase();
  const i = lower.indexOf(q);
  if (i === -1) return text;
  return (
    <>
      {text.slice(0, i)}
      <span className="font-semibold underline decoration-2 underline-offset-2">
        {text.slice(i, i + fragment.length)}
      </span>
      {text.slice(i + fragment.length)}
    </>
  );
}
