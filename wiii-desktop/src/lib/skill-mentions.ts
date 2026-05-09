/**
 * SkillMention parser + catalog (Wiii Pointy v2.8).
 *
 * Triển khai pattern `@plugin-name` mention chuẩn SOTA 2026 (Cursor,
 * GitHub Copilot, Claude Code, Cline). User gõ `@wiii-pointy` trong
 * chat input để FORCE invoke skill, bỏ qua keyword intent guessing.
 *
 * Mention rules:
 *
 * - Trigger char: `@` ở word boundary (đầu input hoặc sau whitespace)
 * - Skill id: lowercase letter start, alphanumeric + hyphen
 * - Multiple mentions OK trong cùng message
 * - Escape: `\@` để literal `@` (rare, không enforce v1)
 *
 * Catalog hard-coded sync với SKILLs trong library/. Alternative aliases
 * map shortcuts → canonical id.
 *
 * Tham khảo: ``research-at-mention-plugin-pattern-2026-05-06.md``
 */

/** Mention regex: `(start of input) | whitespace` then `@<id>`. */
const MENTION_REGEX = /(^|\s)@([a-z][a-z0-9-]*)/g;

export interface SkillMention {
  /** Canonical skill id (sau khi resolve alias). */
  skillId: string;
  /** Raw text user typed including `@`. */
  raw: string;
  /** Position trong original text (start of `@`). */
  startIndex: number;
  /** Position end (exclusive). */
  endIndex: number;
  /** True nếu đây là alias resolve sang canonical id khác. */
  wasAlias: boolean;
}

export interface ParsedMessage {
  /** Original text với mentions giữ nguyên. */
  text: string;
  /** Cleaned text (mentions removed, double-spaces collapsed). */
  cleanedText: string;
  /** All mentions found. */
  mentions: SkillMention[];
  /** List unique canonical skill ids cho backend force_skills. */
  forceSkills: string[];
}

/**
 * Catalog of available skills + alias mappings. Source of truth là
 * library/<skill-name>/SKILL.md, nhưng frontend hard-code để autocomplete
 * không phải fetch network. Khi thêm SKILL mới, update đây.
 */
export interface SkillCatalogEntry {
  id: string;          // canonical skill id (matches SKILL.md `name`)
  label: string;       // friendly display name
  description: string; // 1-line tooltip
  aliases: string[];   // shortcut mentions
}

export const SKILL_CATALOG: readonly SkillCatalogEntry[] = [
  {
    id: "wiii-pointy",
    label: "Wiii Pointy",
    description: "Cursor pointing — chỉ vào element trên màn hình",
    aliases: ["pointy", "point", "cursor"],
  },
  {
    id: "web-search",
    label: "Web Search",
    description: "Tìm kiếm web realtime (SearXNG + bilingual news)",
    aliases: ["search", "web"],
  },
  {
    id: "visual-code-gen",
    label: "Code Studio",
    description: "Tạo simulation, widget, mini app, dashboard",
    aliases: ["code", "studio", "visual"],
  },
] as const;

/** Build alias → canonical map (lazy-init). */
let _aliasMap: Map<string, string> | null = null;
function aliasMap(): Map<string, string> {
  if (_aliasMap) return _aliasMap;
  const m = new Map<string, string>();
  for (const entry of SKILL_CATALOG) {
    m.set(entry.id, entry.id); // identity
    for (const alias of entry.aliases) {
      m.set(alias, entry.id);
    }
  }
  _aliasMap = m;
  return m;
}

/**
 * Parse all `@plugin-name` mentions trong text. Returns structured
 * representation: cleaned text + mentions + force_skills array sẵn cho
 * backend.
 */
export function parseSkillMentions(text: string): ParsedMessage {
  if (!text) {
    return { text: "", cleanedText: "", mentions: [], forceSkills: [] };
  }
  const map = aliasMap();
  const mentions: SkillMention[] = [];
  let cleaned = "";
  let lastIndex = 0;

  // Manual iteration via exec to capture indices.
  MENTION_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MENTION_REGEX.exec(text)) !== null) {
    const leadingChar = match[1]; // "" or whitespace
    const typedId = match[2];
    const canonical = map.get(typedId);
    if (!canonical) {
      // Unknown mention — leave as-is in cleanedText.
      continue;
    }
    const atStart = match.index + leadingChar.length;
    const atEnd = match.index + match[0].length;
    mentions.push({
      skillId: canonical,
      raw: `@${typedId}`,
      startIndex: atStart,
      endIndex: atEnd,
      wasAlias: canonical !== typedId,
    });
    // Append text up to mention start.
    cleaned += text.slice(lastIndex, atStart);
    lastIndex = atEnd;
    // Skip the `@id` from cleaned text. Keep leading whitespace if any.
  }
  cleaned += text.slice(lastIndex);
  // Collapse double-spaces from removed mentions.
  cleaned = cleaned.replace(/\s{2,}/g, " ").trim();

  // Unique force skills, preserving first-mention order.
  const seen = new Set<string>();
  const forceSkills: string[] = [];
  for (const m of mentions) {
    if (!seen.has(m.skillId)) {
      seen.add(m.skillId);
      forceSkills.push(m.skillId);
    }
  }

  return {
    text,
    cleanedText: cleaned,
    mentions,
    forceSkills,
  };
}

/**
 * Suggestion result cho autocomplete dropdown. Filter catalog by typed
 * fragment after `@`.
 */
export interface MentionSuggestion {
  entry: SkillCatalogEntry;
  /** Score for ranking (higher = better match). */
  score: number;
  /** Matched portion bold-highlighted. */
  matchType: "id" | "alias" | "label";
}

/**
 * Filter catalog by user's typed fragment after `@`. Empty fragment
 * returns all. Ranked by: exact id > id starts-with > alias > label.
 */
export function suggestMentions(fragment: string): MentionSuggestion[] {
  const q = fragment.trim().toLowerCase();
  const results: MentionSuggestion[] = [];
  for (const entry of SKILL_CATALOG) {
    let bestScore = 0;
    let matchType: MentionSuggestion["matchType"] = "id";
    if (!q) {
      bestScore = 1; // include all
    } else if (entry.id === q) {
      bestScore = 100;
      matchType = "id";
    } else if (entry.id.startsWith(q)) {
      bestScore = 80;
      matchType = "id";
    } else if (entry.aliases.some((a) => a === q)) {
      bestScore = 70;
      matchType = "alias";
    } else if (entry.aliases.some((a) => a.startsWith(q))) {
      bestScore = 50;
      matchType = "alias";
    } else if (entry.label.toLowerCase().includes(q)) {
      bestScore = 30;
      matchType = "label";
    } else if (entry.id.includes(q)) {
      bestScore = 20;
      matchType = "id";
    }
    if (bestScore > 0) {
      results.push({ entry, score: bestScore, matchType });
    }
  }
  results.sort((a, b) => b.score - a.score);
  return results;
}

/**
 * Helper cho ChatInput: detect xem cursor có đang trong "mention typing"
 * mode không (just typed `@` and hasn't broken to whitespace). Returns
 * the fragment after `@` (e.g., "poi" khi user typed "@poi" nhưng chưa
 * select).
 */
export interface MentionTypingState {
  /** True if cursor đang trong @ mention typing. */
  active: boolean;
  /** Fragment after `@` (could be empty if just typed `@`). */
  fragment: string;
  /** Position of `@` in text. */
  atIndex: number;
}

export function detectMentionTyping(
  text: string,
  caretIndex: number,
): MentionTypingState {
  // Walk backwards from caret tìm `@` không bị whitespace chen.
  let i = caretIndex - 1;
  while (i >= 0) {
    const ch = text[i];
    if (ch === "@") {
      // Check `@` ở word boundary (start of text or after whitespace).
      if (i === 0 || /\s/.test(text[i - 1])) {
        const fragment = text.slice(i + 1, caretIndex);
        // Only valid mention chars (letters, digits, hyphen) trong fragment.
        if (/^[a-z0-9-]*$/i.test(fragment)) {
          return { active: true, fragment: fragment.toLowerCase(), atIndex: i };
        }
      }
      return { active: false, fragment: "", atIndex: -1 };
    }
    if (/\s/.test(ch)) {
      // Whitespace breaks mention typing.
      return { active: false, fragment: "", atIndex: -1 };
    }
    i--;
  }
  return { active: false, fragment: "", atIndex: -1 };
}
