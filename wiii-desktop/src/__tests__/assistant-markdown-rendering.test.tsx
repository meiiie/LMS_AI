import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("MarkdownRenderer assistant cleanup", () => {
  it("renders dense assistant table and quotes as structured markdown", async () => {
    const { MarkdownRenderer } = await import("@/components/common/MarkdownRenderer");
    const content = [
      "--- 🔍 So sánh nhanh: | Tiêu chí | Annex I | Annex VI |---------|----------|---------| | Ô nhiễm | Dầu ra biển | Khí thải ra không khí | Ghi chép | Oil Record Book | FONAR, EIAPP | --- 💡 Mẹo nhớ: đọc theo từng cột.",
      "Cậu chỉ cần nói: > “Mình thấy nút Khóa học” hoặc > “Mình không thấy gì cả”",
    ].join("\n\n");

    render(<MarkdownRenderer content={content} />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Tiêu chí")).toBeTruthy();
    expect(within(table).getByText("Annex I")).toBeTruthy();
    expect(within(table).getByText("Khí thải ra không khí")).toBeTruthy();
    expect(screen.getByText("💡 Mẹo nhớ: đọc theo từng cột.")).toBeTruthy();
    expect(screen.getByText("“Mình thấy nút Khóa học”")).toBeTruthy();
    expect(screen.getByText("“Mình không thấy gì cả”")).toBeTruthy();
  });
});
