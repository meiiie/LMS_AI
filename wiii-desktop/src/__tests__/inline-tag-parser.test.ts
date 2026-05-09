/**
 * Tests for Wiii Pointy v4.0 inline `[POINT:...]` tag parser.
 * Pattern: farzaa/clicky single-source-of-truth (MIT, github April 2026).
 */

import { describe, it, expect } from "vitest";
import {
  parsePointTag,
  parseAllPointTags,
  hasPointTag,
} from "../pointy-host/inline-tag-parser";

describe("parsePointTag", () => {
  it("returns null tag + original text when no tag present", () => {
    const r = parsePointTag("Đây là câu trả lời thường.");
    expect(r.tag).toBeNull();
    expect(r.stripped).toBe("Đây là câu trả lời thường.");
  });

  it("returns null on empty input", () => {
    expect(parsePointTag("").tag).toBeNull();
  });

  it("extracts bare-id with no caption", () => {
    const r = parsePointTag("Nút gửi ở góc dưới phải. [POINT:chat-send-button]");
    expect(r.tag).toEqual({ selector: "chat-send-button", caption: "" });
    expect(r.stripped).toBe("Nút gửi ở góc dưới phải.");
  });

  it("extracts selector + caption", () => {
    const r = parsePointTag(
      "Đây nè cậu. [POINT:chat-send-button:Nhấn để gửi]",
    );
    expect(r.tag).toEqual({
      selector: "chat-send-button",
      caption: "Nhấn để gửi",
    });
    expect(r.stripped).toBe("Đây nè cậu.");
  });

  it("[POINT:none] strips tag but returns null (no dispatch)", () => {
    const r = parsePointTag("Câu hỏi chung không cần trỏ. [POINT:none]");
    expect(r.tag).toBeNull();
    expect(r.stripped).toBe("Câu hỏi chung không cần trỏ.");
  });

  it("ignores [POINT:...] inside response (must be at end)", () => {
    const r = parsePointTag(
      "Tag [POINT:chat-send-button] phải ở cuối, không giữa câu.",
    );
    expect(r.tag).toBeNull();
    expect(r.stripped).toBe(
      "Tag [POINT:chat-send-button] phải ở cuối, không giữa câu.",
    );
  });

  it("strips trailing whitespace + newlines around tag", () => {
    const r = parsePointTag(
      "Đây.\n\n  [POINT:settings-link]   ",
    );
    expect(r.tag?.selector).toBe("settings-link");
    expect(r.stripped).toBe("Đây.");
  });

  it("rejects compound CSS selector (anti-hallucination)", () => {
    // exact-id regex blocks `.class`, `#id`, `[attr]`, `:pseudo`, etc.
    const r = parsePointTag('Test. [POINT:.send-button]');
    expect(r.tag).toBeNull();
  });

  it("rejects selector starting with digit", () => {
    const r = parsePointTag("Test. [POINT:1invalid]");
    expect(r.tag).toBeNull();
  });

  it("accepts underscore + hyphen in selector", () => {
    const r = parsePointTag("Test. [POINT:btn_save-primary-2]");
    expect(r.tag?.selector).toBe("btn_save-primary-2");
  });

  it("accepts scanner synthetic auto ids", () => {
    const r = parsePointTag(
      "Nút gửi ở cạnh khung chat nè. [POINT:auto:button:gui-tin-nhan]",
    );
    expect(r.tag).toEqual({
      selector: "auto:button:gui-tin-nhan",
      caption: "",
    });
    expect(r.stripped).toBe("Nút gửi ở cạnh khung chat nè.");
  });

  it("accepts scanner synthetic auto ids with captions", () => {
    const r = parsePointTag(
      "Mình trỏ vào đây nha. [POINT:auto:button:gui-tin-nhan:Gửi tin nhắn]",
    );
    expect(r.tag).toEqual({
      selector: "auto:button:gui-tin-nhan",
      caption: "Gửi tin nhắn",
    });
  });

  it("idempotent — re-parsing stripped text returns same + null", () => {
    const r1 = parsePointTag("Đây nè. [POINT:btn]");
    const r2 = parsePointTag(r1.stripped);
    expect(r2.tag).toBeNull();
    expect(r2.stripped).toBe(r1.stripped);
  });
});

describe("hasPointTag", () => {
  it("true for valid tag at end", () => {
    expect(hasPointTag("text [POINT:btn]")).toBe(true);
    expect(hasPointTag("text [POINT:none]")).toBe(true);
  });
  it("false for no tag", () => {
    expect(hasPointTag("plain text")).toBe(false);
  });
  it("false for tag in middle", () => {
    expect(hasPointTag("[POINT:btn] in middle of text")).toBe(false);
  });
});

describe("parseAllPointTags auto ids", () => {
  it("extracts multiple exact inventory ids including auto ids", () => {
    const r = parseAllPointTags(
      "Đi theo thứ tự này. [POINT:auto:button:chon-model:Model] rồi [POINT:chat-send-button:Gửi]",
    );
    expect(r.tags).toEqual([
      { selector: "auto:button:chon-model", caption: "Model" },
      { selector: "chat-send-button", caption: "Gửi" },
    ]);
    expect(r.stripped).toBe("Đi theo thứ tự này.  rồi");
  });
});
