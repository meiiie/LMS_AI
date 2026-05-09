/**
 * Tests for Wiii Pointy v5.0 embodied response parser.
 * Body schema fallback: cursor follows AI's natural language about
 * UI elements (no explicit tag required).
 */

import { describe, it, expect } from "vitest";
import { detectEmbodiedPoint } from "../pointy-host/embodied-parser";

const TARGETS = [
  { id: "chat-send-button", label: "Gửi tin nhắn", role: "button" },
  { id: "settings-link", label: "Cài đặt", role: "link" },
  { id: "model-picker", label: "Chọn model", role: "menu" },
  { id: "attach-file-button", label: "Đính kèm file", role: "button" },
];

describe("detectEmbodiedPoint", () => {
  it("returns null when no targets available", () => {
    expect(detectEmbodiedPoint("Nút gửi ở đâu", [])).toBeNull();
  });

  it("returns null when response empty", () => {
    expect(detectEmbodiedPoint("", TARGETS)).toBeNull();
  });

  it("returns null when response talks about non-UI topic", () => {
    const r = detectEmbodiedPoint(
      "Hôm nay trời đẹp quá nhỉ, chúng ta đi chơi đi.",
      TARGETS,
    );
    expect(r).toBeNull();
  });

  it("matches send button when AI mentions label + intent phrase", () => {
    const r = detectEmbodiedPoint(
      "Nút gửi tin nhắn ở góc dưới bên phải nè cậu.",
      TARGETS,
    );
    expect(r?.target.id).toBe("chat-send-button");
    expect(r?.score).toBeGreaterThanOrEqual(0.6);
  });

  it("matches when AI says 'trỏ vào nút gửi tin nhắn'", () => {
    const r = detectEmbodiedPoint(
      "Mình đang trỏ vào nút gửi tin nhắn cho cậu thấy nè.",
      TARGETS,
    );
    expect(r?.target.id).toBe("chat-send-button");
  });

  it("matches when AI says 'Đây nè' + label", () => {
    const r = detectEmbodiedPoint(
      "Đây rồi! Cài đặt nằm ở thanh bên trái nha.",
      TARGETS,
    );
    expect(r?.target.id).toBe("settings-link");
  });

  it("matches highest-scoring target when multiple labels mentioned", () => {
    // Both "gửi tin nhắn" and "đính kèm" appear, but only "gửi tin nhắn"
    // co-occurs with intent phrase "ở góc".
    const r = detectEmbodiedPoint(
      "Nút gửi tin nhắn ở góc phải, còn đính kèm file thì để sau.",
      TARGETS,
    );
    expect(r?.target.id).toBe("chat-send-button");
  });

  it("ignores diacritics — 'nut gui tin nhan' matches", () => {
    const r = detectEmbodiedPoint(
      "Nut gui tin nhan o goc duoi ben phai.",
      TARGETS,
    );
    expect(r?.target.id).toBe("chat-send-button");
  });

  it("falls below threshold when intent phrase missing", () => {
    // Just mentioning "tin nhắn" without intent phrase → too weak.
    const r = detectEmbodiedPoint(
      "Tin nhắn của cậu rất hay.",
      TARGETS,
    );
    expect(r).toBeNull();
  });

  it("matches when AI uses verbatim id (read inventory)", () => {
    const r = detectEmbodiedPoint(
      "Click vào chat-send-button để gửi.",
      TARGETS,
    );
    expect(r?.target.id).toBe("chat-send-button");
  });

  it("captures sentence containing the match (for debug)", () => {
    const r = detectEmbodiedPoint(
      "Hôm nay là thứ ba. Nút gửi tin nhắn ở góc phải nha cậu.",
      TARGETS,
    );
    expect(r?.sentence).toContain("Nút gửi tin nhắn");
  });

  it("threshold customizable", () => {
    // v8.1 (2026-05-06): partial label match without intent phrase
    // scores 0.3 (was 0.5). Test now uses sentence WITH intent phrase
    // to verify threshold knob still works.
    const r = detectEmbodiedPoint(
      "Gửi tin nhắn nằm ở góc phải.",
      TARGETS,
      { threshold: 0.4 },
    );
    expect(r).not.toBeNull();
    expect(r?.target.id).toBe("chat-send-button");
  });

  it("does not match explanation about a button without pointing intent", () => {
    const r = detectEmbodiedPoint(
      "Tin nhắn của cậu cần một nút để confirm trước khi gửi đi, đó là lý do có nút gửi.",
      TARGETS,
    );
    expect(r).toBeNull();
  });

  it("does not let the intent word 'trỏ' match 'trò chuyện'", () => {
    const r = detectEmbodiedPoint(
      "Trỏ vào sao trên trời cũng đẹp đó cậu.",
      [
        {
          id: "new-chat-button",
          label: "Tạo cuộc trò chuyện mới",
          role: "button",
        },
      ],
    );
    expect(r).toBeNull();
  });

  it("v8.3 synonyms — 'kẹp giấy' matches attach button via synonym", () => {
    const targetsWithSynonyms = [
      {
        id: "attach-file-button",
        label: "Đính kèm file",
        role: "button",
        synonyms: ["kẹp giấy", "paperclip", "đính kèm ảnh", "upload"],
      },
      {
        id: "chat-textarea",
        label: "Khung soạn tin nhắn",
        role: "textarea",
      },
    ];
    const r = detectEmbodiedPoint(
      "Cậu click vào nút kẹp giấy 📎 ở góc dưới khung chat để đính kèm ảnh.",
      targetsWithSynonyms,
    );
    expect(r?.target.id).toBe("attach-file-button");
  });

  it("v8.3 synonyms — synonym full-match scores like full label", () => {
    const targets = [
      {
        id: "send-btn",
        label: "Gửi tin nhắn",
        role: "button",
        synonyms: ["mũi tên", "máy bay giấy", "send"],
      },
    ];
    const r = detectEmbodiedPoint(
      "Mũi tên ở góc phải nha cậu.",
      targets,
    );
    // Synonym "mũi tên" full-matched — should score same level as full label.
    expect(r).not.toBeNull();
    expect(r?.score).toBeGreaterThanOrEqual(0.7);
  });

  it("v8.3 synonyms — multi-word synonym matches as unit (not split words)", () => {
    const targets = [
      {
        id: "send-btn",
        label: "Send",
        role: "button",
        synonyms: ["máy bay giấy"],
      },
    ];
    // "giấy" alone (1 word from synonym) shouldn't false-match without
    // intent. But full "máy bay giấy" + intent should.
    const r1 = detectEmbodiedPoint("Tờ giấy của tôi rất đẹp.", targets);
    expect(r1).toBeNull();
    const r2 = detectEmbodiedPoint(
      "Click vào máy bay giấy ở góc phải.",
      targets,
    );
    expect(r2?.target.id).toBe("send-btn");
  });

  it("English intent phrases also work", () => {
    const r = detectEmbodiedPoint(
      "Click on the send button in the bottom-right corner.",
      [{ id: "chat-send-button", label: "send button", role: "button" }],
    );
    expect(r?.target.id).toBe("chat-send-button");
  });
});
