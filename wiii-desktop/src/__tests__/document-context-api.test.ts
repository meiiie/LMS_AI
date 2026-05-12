import { beforeEach, describe, expect, it, vi } from "vitest";

const postFormData = vi.fn();

vi.mock("@/api/client", () => ({
  getClient: () => ({ postFormData }),
}));

import {
  getDocumentContextParseTimeoutMs,
  parseDocumentContext,
} from "@/api/document-context";

function makeFile(name: string, sizeBytes: number, type = ""): File {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

describe("document context API", () => {
  beforeEach(() => {
    postFormData.mockReset();
    postFormData.mockResolvedValue({ file_name: "ok.docx" });
  });

  it("uses a longer parse timeout for large documents", async () => {
    const file = makeFile(
      "maritime-research.docx",
      Math.ceil(13.52 * 1024 * 1024),
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    );

    await parseDocumentContext(file);

    expect(getDocumentContextParseTimeoutMs(file)).toBe(330_000);
    expect(postFormData).toHaveBeenCalledWith(
      "/api/v1/document-context/parse",
      expect.any(FormData),
      330_000,
    );
  });

  it("keeps small document parsing above the default API timeout", () => {
    const file = makeFile("brief.pdf", 300 * 1024, "application/pdf");

    expect(getDocumentContextParseTimeoutMs(file)).toBe(135_000);
  });

  it("allocates more time for video context extraction", () => {
    const file = makeFile("training.mp4", 20 * 1024 * 1024, "video/mp4");

    expect(getDocumentContextParseTimeoutMs(file)).toBe(840_000);
  });
});
