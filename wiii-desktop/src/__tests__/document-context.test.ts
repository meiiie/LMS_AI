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

  it("strips markdown from display attachments", () => {
    const display = toDisplayDocumentAttachment(makeDoc());

    expect(display.file_name).toBe("brief.docx");
    expect("markdown" in display).toBe(false);
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

  it("formats attachment sizes compactly", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
