import { describe, expect, it } from "vitest";
import { normalizeAssistantMarkdown } from "@/lib/assistant-markdown";

describe("normalizeAssistantMarkdown", () => {
  it("repairs collapsed tables and section separators before rendering", () => {
    const input =
      "So sánh nhanh: | Tiêu chí | Annex I | Annex VI | |------|------|------| | Ô nhiễm | Dầu ra biển | Khí thải | --- Mẹo nhớ: đọc theo từng cột.";

    const normalized = normalizeAssistantMarkdown(input);

    expect(normalized).toContain("So sánh nhanh:\n\n| Tiêu chí | Annex I | Annex VI |");
    expect(normalized).toContain("\n|------|------|------|");
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
});
