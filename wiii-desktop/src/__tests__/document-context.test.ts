import { describe, expect, it } from "vitest";
import {
  buildChatDocumentContext,
  formatBytes,
  toImageInputsFromExtractedFrames,
  toDisplayDocumentAttachment,
  type ParsedDocumentForContext,
} from "@/lib/document-context";

function makeDoc(overrides: Partial<ParsedDocumentForContext> = {}): ParsedDocumentForContext {
  return {
    id: "doc-1",
    file_name: "brief.docx",
    mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 2048,
    parser: "markitdown",
    char_count: 32,
    truncated: false,
    media_kind: "document",
    markdown: "# Brief\n\nRule 5: keep a lookout.",
    ...overrides,
  };
}

describe("document context helpers", () => {
  it("builds a bounded per-turn document context", () => {
    const context = buildChatDocumentContext([
      makeDoc({ markdown: "A".repeat(1000), char_count: 1000 }),
    ], 120);

    expect(context?.source).toBe("desktop_upload");
    expect(context?.attachments).toHaveLength(1);
    expect(context?.attachments[0].markdown.length).toBeLessThanOrEqual(120);
    expect(context?.attachments[0].truncated).toBe(true);
  });

  it("keeps teacher sections from long LMS manuals before trimming", () => {
    const markdown = [
      "![Logo](data:image/png;base64...)",
      "# HoLiLiHu LMS",
      "Mo dau ".repeat(300),
      "# 3. Huong Dan Cho Hoc Vien",
      "Noi dung hoc vien ".repeat(260),
      "# 4. Huong Dan Cho Giang Vien",
      "Giang vien tao khoa hoc, soan chuong va bai, them video tuong tac, tao cau hoi va gui duyet. ".repeat(45),
      "# 6. Huong Dan Cho Quan Ly",
      "Noi dung quan ly ".repeat(120),
    ].join("\n\n");

    const context = buildChatDocumentContext([
      makeDoc({ markdown, char_count: markdown.length, truncated: true }),
    ], 3_200);
    const bounded = context?.attachments[0].markdown || "";

    expect(bounded.length).toBeLessThanOrEqual(3_200);
    expect(bounded).toContain("Huong Dan Cho Giang Vien");
    expect(bounded).toContain("tao khoa hoc");
    expect(bounded).not.toContain("data:image");
  });

  it("retrieves important sections from backend snippets beyond the truncated markdown", () => {
    const truncatedMarkdown = [
      "# HoLiLiHu LMS",
      "Phan dau tai lieu ".repeat(900),
      "# 2. Noi dung nen",
      "Doan dem khong lien quan ".repeat(900),
    ].join("\n\n");

    const context = buildChatDocumentContext([
      makeDoc({
        markdown: truncatedMarkdown,
        char_count: truncatedMarkdown.length + 18_000,
        truncated: true,
        section_snippets: [
          {
            title: "2. Noi dung nen",
            markdown: "# 2. Noi dung nen\n\nDoan dem khong lien quan.",
            char_start: 10_000,
            char_end: 13_000,
            source_pages: [2],
          },
          {
            title: "9. Hướng Dẫn Cho Giảng Viên",
            markdown:
              "# 9. Hướng Dẫn Cho Giảng Viên\n\nGiảng viên tạo khóa học, soạn chương và bài, thêm video tương tác, tạo câu hỏi và gửi duyệt.",
            char_start: 45_000,
            char_end: 48_000,
            source_pages: [9, 10],
          },
        ],
      }),
    ], 2_800);
    const bounded = context?.attachments[0].markdown || "";

    expect(bounded.length).toBeLessThanOrEqual(2_800);
    expect(bounded).toContain("Hướng Dẫn Cho Giảng Viên");
    expect(bounded).toContain("Nguồn section: 9. Hướng Dẫn Cho Giảng Viên (trang 9-10)");
    expect(bounded).toContain("thêm video tương tác");
  });

  it("prioritizes teacher authoring sections over incidental admin teacher mentions", () => {
    const snippets = [
      ["3.7. Hoc video tuong tac", "Hoc vien tra loi khi video tam dung."],
      ["4. Huong Dan Cho Giang Vien", "Tong quan quy trinh tao va van hanh khoa hoc."],
      ["4.2. Tao khoa hoc moi", "Nhap thong tin khoa hoc, muc tieu va mo ta cho hoc vien."],
      ["4.4. Soan cau truc chuong va bai", "Sap xep chuong, bai, tai lieu va thu tu hoc."],
      ["4.5. Them bai video va video tuong tac", "Them video, diem dung, cau hoi va phan hoi."],
      ["4.6. Tao cau hoi trong ngan hang", "Tao cau hoi, dap an, giai thich va gan vao quiz."],
      ["4.9. Doc phan tich giang vien", "Theo doi hieu qua khoa va noi dung hoc vien dang vuong."],
      ["6.2. Quan ly giang vien", "Admin tim va ho tro tai khoan giang vien."],
      ["9.2. Checklist giang vien truoc khi gui duyet", "Kiem tra thong tin, video, cau hoi va trang thai gui duyet."],
    ].map(([title, body], index) => ({
      title,
      markdown: `# ${title}\n\n${body}`,
      char_start: 10_000 + index * 1000,
      char_end: 10_800 + index * 1000,
      source_pages: [index + 1],
    }));

    const context = buildChatDocumentContext([
      makeDoc({
        markdown: "# Manual\n\n" + "Mo dau tai lieu ".repeat(900),
        char_count: 80_000,
        truncated: true,
        section_snippets: snippets,
      }),
    ], 5_200);
    const bounded = context?.attachments[0].markdown || "";

    expect(bounded).toContain("Nguồn section: 4.2. Tao khoa hoc moi");
    expect(bounded).toContain("Nguồn section: 4.4. Soan cau truc chuong va bai");
    expect(bounded).toContain("Nguồn section: 4.5. Them bai video va video tuong tac");
    expect(bounded).toContain("Nguồn section: 4.6. Tao cau hoi trong ngan hang");
    expect(bounded).not.toContain("Hoc vien tra loi khi video tam dung");
    expect(bounded).not.toContain("Admin tim va ho tro tai khoan giang vien");
    expect(bounded).not.toContain("Theo doi hieu qua khoa va noi dung hoc vien dang vuong");
  });

  it("strips markdown from display attachments", () => {
    const display = toDisplayDocumentAttachment(makeDoc());

    expect(display.file_name).toBe("brief.docx");
    expect("markdown" in display).toBe(false);
  });

  it("keeps outline source lines for long non-priority documents", () => {
    const sectionSnippets = Array.from({ length: 35 }, (_, index) => {
      const sectionNumber = index + 1;
      return {
        title: `Section ${sectionNumber}: Operational topic ${sectionNumber}`,
        markdown: `# Section ${sectionNumber}: Operational topic ${sectionNumber}\n\nNeutral operational content ${sectionNumber}.`,
        char_start: sectionNumber * 1000,
        char_end: sectionNumber * 1000 + 800,
        source_pages: [sectionNumber],
      };
    });

    const context = buildChatDocumentContext([
      makeDoc({
        file_name: "long-neutral-report.docx",
        markdown: "# Long neutral report\n\n" + "Opening context ".repeat(1200),
        char_count: 90_000,
        truncated: true,
        section_snippets: sectionSnippets,
      }),
    ], 9_000);
    const bounded = context?.attachments[0].markdown || "";

    expect(bounded.length).toBeLessThanOrEqual(9_000);
    expect(bounded).toContain("Nguồn section: Section 1: Operational topic 1 (trang 1)");
    expect(bounded).toContain("Nguồn section: Section 35: Operational topic 35 (trang 35)");
    expect(bounded).not.toContain("còn 1 mục khác");
  });

  it("preserves video frame metadata without putting frame bytes in document context", () => {
    const doc = makeDoc({
      file_name: "lesson.mp4",
      media_kind: "video",
      parser: "video_context",
      extracted_image_count: 1,
      extracted_images: [
        {
          id: "video-frame-1",
          label: "Khung hình 1 @ 0:01",
          media_type: "image/jpeg",
          data: "ZmFrZS1qcGVn",
          detail: "low",
        },
      ],
      markdown: "# Video upload\n\nSampled keyframes attached.",
    });

    const context = buildChatDocumentContext([doc], 1000);
    const display = toDisplayDocumentAttachment(doc);
    const frames = toImageInputsFromExtractedFrames([doc], 5);

    expect(context?.attachments[0].media_kind).toBe("video");
    expect("extracted_images" in context!.attachments[0]).toBe(false);
    expect(display.extracted_image_count).toBe(1);
    expect(frames).toHaveLength(1);
    expect(frames[0].media_type).toBe("image/jpeg");
  });

  it("carries parser provenance and embedded asset counts into bounded context", () => {
    const markdown = [
      "# Maritime report",
      "Opening ".repeat(900),
      "# Findings",
      "Operational findings ".repeat(200),
    ].join("\n\n");

    const context = buildChatDocumentContext([
      makeDoc({
        file_name: "asset-report.docx",
        parser: "docling",
        parser_chain: ["markitdown", "docling"],
        provenance_level: "page_layout",
        embedded_asset_count: 3,
        figure_count: 2,
        table_count: 1,
        markdown,
        char_count: markdown.length,
        truncated: true,
      }),
    ], 2_400);
    const bounded = context?.attachments[0].markdown || "";

    expect(context?.attachments[0].provenance_level).toBe("page_layout");
    expect(context?.attachments[0].embedded_asset_count).toBe(3);
    expect(bounded).toContain("Parser provenance");
    expect(bounded).toContain("parser_chain: markitdown -> docling");
    expect(bounded).toContain("Embedded asset signals");
  });

  it("formats attachment sizes compactly", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
