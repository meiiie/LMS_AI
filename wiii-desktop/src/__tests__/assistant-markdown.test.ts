import { describe, expect, it } from "vitest";
import { normalizeAssistantMarkdown } from "@/lib/assistant-markdown";

describe("normalizeAssistantMarkdown", () => {
  it("repairs collapsed tables and section separators before rendering", () => {
    const input =
      "So sánh nhanh: | Tiêu chí | Annex I | Annex VI | |------|------|------| | Ô nhiễm | Dầu ra biển | Khí thải | --- Mẹo nhớ: đọc theo từng cột.";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("So sánh nhanh:\n\n| Tiêu chí | Annex I | Annex VI |");
    expect(normalized).toContain("\n| ------ | ------ | ------ |");
    expect(normalized).toContain("\n| Ô nhiễm | Dầu ra biển | Khí thải |");
    expect(normalized).toContain("\n\n---\n\nMẹo nhớ:");
  });

  it("keeps fenced code blocks byte-stable", () => {
    const input = [
      "Trước code --- có separator",
      "```md",
      "| Không | sửa |",
      "|---|---|",
      "A --- B",
      "```",
      "Sau code --- có separator",
    ].join("\n");

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("```md\n| Không | sửa |\n|---|---|\nA --- B\n```");
    expect(normalized).toContain("Trước code\n\n---\n\ncó separator");
    expect(normalized).toContain("Sau code\n\n---\n\ncó separator");
  });

  it("only promotes inline bullets after punctuation boundaries", () => {
    const input = "Các bước: - Mở lớp - Chọn bài - Áp dụng nhưng câu A - B vẫn là văn xuôi.";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("Các bước:\n- Mở lớp\n- Chọn bài\n- Áp dụng");
    expect(normalized).toContain("câu A - B vẫn là văn xuôi");
  });
  it("rebuilds dense product-style tables whose rows were collapsed into one line", () => {
    const input =
      "--- 🔍 So sánh nhanh: | Tiêu chí | Annex I | Annex VI |---------|----------|---------| | Ô nhiễm | Dầu ra biển | Khí thải ra không khí | Chất gây hại | Dầu, hydrocarbon | SOx, NOx, PM, CO₂ | Ghi chép | Oil Record Book | FONAR, EIAPP | --- 💡 Mẹo nhớ: đọc theo từng cột.";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("---\n\n🔍 So sánh nhanh:");
    expect(normalized).toContain("| Tiêu chí | Annex I | Annex VI |");
    expect(normalized).toContain("| --------- | ---------- | --------- |");
    expect(normalized).toContain("| Ô nhiễm | Dầu ra biển | Khí thải ra không khí |");
    expect(normalized).toContain("| Ghi chép | Oil Record Book | FONAR, EIAPP |");
    expect(normalized).toContain("\n\n---\n\n💡 Mẹo nhớ:");
  });

  it("promotes inline blockquotes after Vietnamese quote prompts", () => {
    const input =
      "Cậu chỉ cần nói: > “Mình thấy nút Khóa học” hoặc > “Mình không thấy gì cả”";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("Cậu chỉ cần nói:\n> “Mình thấy nút Khóa học”");
    expect(normalized).toContain("hoặc\n\n> “Mình không thấy gì cả”");
  });

  it("repairs collapsed Vietnamese maritime tables after prose prefixes", () => {
    const input =
      "Ví dụ đời thường: Giống như bạn không được đốt than trong nhà. --- 🔍 So sánh nhanh: | Tiêu chí | Annex I | Annex VI |---------|----------|---------| | Ô nhiễm | Dầu ra biển | Khí thải ra không khí | Chất gây hại | Dầu, hydrocarbon | SOx, NOx, PM, CO₂ | Giới hạn chính | Không xả dầu | Hàm lượng lưu huỳnh ≤0.50% | --- 💡 Mẹo nhớ: đọc theo từng cột.";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("Ví dụ đời thường: Giống như bạn không được đốt than trong nhà.");
    expect(normalized).toContain("\n\n---\n\n🔍 So sánh nhanh:");
    expect(normalized).toContain("| Tiêu chí | Annex I | Annex VI |");
    expect(normalized).toContain("| Ô nhiễm | Dầu ra biển | Khí thải ra không khí |");
    expect(normalized).toContain("| Giới hạn chính | Không xả dầu | Hàm lượng lưu huỳnh ≤0.50% |");
    expect(normalized).toContain("\n\n---\n\n💡 Mẹo nhớ:");
  });
});
