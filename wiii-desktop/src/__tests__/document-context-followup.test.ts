import { describe, expect, it } from "vitest";

import { looksDocumentContextFollowupIntent } from "@/lib/document-followup-intent";

describe("document context follow-up intent", () => {
  it("keeps the latest uploaded document for short Vietnamese preview follow-ups", () => {
    expect(looksDocumentContextFollowupIntent("preview đi")).toBe(true);
    expect(looksDocumentContextFollowupIntent("xem trước bản nháp giúp mình")).toBe(true);
  });

  it("detects teacher authoring wording for document-to-course creation", () => {
    expect(looksDocumentContextFollowupIntent("Tạo bài giảng đi.")).toBe(true);
    expect(looksDocumentContextFollowupIntent("soạn giáo án từ file này")).toBe(true);
    expect(looksDocumentContextFollowupIntent("chia thành chương và bài")).toBe(true);
  });

  it("does not attach stale documents to unrelated chat", () => {
    expect(looksDocumentContextFollowupIntent("hôm nay thời tiết sao")).toBe(false);
    expect(looksDocumentContextFollowupIntent("cảm ơn Wiii nhé")).toBe(false);
  });
});
