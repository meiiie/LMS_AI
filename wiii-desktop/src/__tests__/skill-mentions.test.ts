/**
 * Tests cho parseSkillMentions + suggestMentions + detectMentionTyping.
 */

import { describe, it, expect } from "vitest";
import {
  parseSkillMentions,
  suggestMentions,
  detectMentionTyping,
  SKILL_CATALOG,
} from "../lib/skill-mentions";

describe("parseSkillMentions", () => {
  it("returns empty for empty input", () => {
    const r = parseSkillMentions("");
    expect(r.mentions).toEqual([]);
    expect(r.forceSkills).toEqual([]);
    expect(r.cleanedText).toBe("");
  });

  it("parses canonical skill id at start", () => {
    const r = parseSkillMentions("@wiii-pointy nút gửi ở đâu");
    expect(r.mentions).toHaveLength(1);
    expect(r.mentions[0].skillId).toBe("wiii-pointy");
    expect(r.forceSkills).toEqual(["wiii-pointy"]);
    expect(r.cleanedText).toBe("nút gửi ở đâu");
  });

  it("resolves alias to canonical id", () => {
    const r = parseSkillMentions("@pointy chỉ giúp tôi");
    expect(r.forceSkills).toEqual(["wiii-pointy"]);
    expect(r.mentions[0].wasAlias).toBe(true);
  });

  it("ignores @ NOT at word boundary (e.g., email)", () => {
    const r = parseSkillMentions("liên hệ user@wiii-pointy.com");
    // The @ here is in middle of word "user@wiii..." → no leading space/start
    expect(r.forceSkills).toEqual([]);
  });

  it("parses multiple mentions", () => {
    const r = parseSkillMentions("@search @pointy tìm rồi chỉ tôi");
    expect(r.forceSkills).toEqual(["web-search", "wiii-pointy"]);
    expect(r.cleanedText).toBe("tìm rồi chỉ tôi");
  });

  it("dedupes same skill mentioned twice", () => {
    const r = parseSkillMentions("@pointy chỉ vào X @wiii-pointy thêm Y");
    expect(r.forceSkills).toEqual(["wiii-pointy"]); // unique
    expect(r.mentions).toHaveLength(2); // both raw mentions captured
  });

  it("ignores unknown mentions", () => {
    const r = parseSkillMentions("@unknown-plugin gì đó");
    expect(r.forceSkills).toEqual([]);
    // Cleaned text keeps the unknown mention as-is.
    expect(r.cleanedText).toContain("@unknown-plugin");
  });

  it("preserves text around mentions", () => {
    const r = parseSkillMentions("Trong app, @pointy nút gửi ở đâu vậy");
    expect(r.cleanedText).toBe("Trong app, nút gửi ở đâu vậy");
  });
});

describe("suggestMentions", () => {
  it("empty fragment returns all skills", () => {
    const s = suggestMentions("");
    expect(s).toHaveLength(SKILL_CATALOG.length);
  });

  it("filters by id starts-with", () => {
    const s = suggestMentions("wiii");
    expect(s.length).toBeGreaterThanOrEqual(1);
    expect(s[0].entry.id).toBe("wiii-pointy");
  });

  it("matches aliases", () => {
    const s = suggestMentions("point");
    expect(s[0].entry.id).toBe("wiii-pointy");
    expect(s[0].matchType).toBe("alias");
  });

  it("ranks exact match highest", () => {
    const s = suggestMentions("web-search");
    expect(s[0].entry.id).toBe("web-search");
    expect(s[0].score).toBeGreaterThan(50);
  });

  it("returns empty when no match", () => {
    const s = suggestMentions("zzznonexistent");
    expect(s).toEqual([]);
  });
});

describe("detectMentionTyping", () => {
  it("active when caret right after @", () => {
    const r = detectMentionTyping("hi @", 4);
    expect(r.active).toBe(true);
    expect(r.fragment).toBe("");
    expect(r.atIndex).toBe(3);
  });

  it("active when typing fragment after @", () => {
    const r = detectMentionTyping("hi @poi", 7);
    expect(r.active).toBe(true);
    expect(r.fragment).toBe("poi");
  });

  it("inactive when whitespace breaks the mention", () => {
    const r = detectMentionTyping("hi @poi some other text", 23);
    expect(r.active).toBe(false);
  });

  it("inactive when @ inside word (e.g., email)", () => {
    const r = detectMentionTyping("user@example.com", 5);
    expect(r.active).toBe(false);
  });

  it("active when @ at start of input", () => {
    const r = detectMentionTyping("@wiii", 5);
    expect(r.active).toBe(true);
    expect(r.fragment).toBe("wiii");
    expect(r.atIndex).toBe(0);
  });

  it("inactive when caret before @", () => {
    const r = detectMentionTyping("text @poi", 4);
    expect(r.active).toBe(false);
  });
});
