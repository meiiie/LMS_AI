import { getClient } from "./client";

export interface DocumentContextExtractedImage {
  id: string;
  label?: string | null;
  timestamp_seconds?: number | null;
  media_type: string;
  data: string;
  detail?: "auto" | "low" | "high";
}

export interface DocumentContextSectionSnippet {
  title: string;
  markdown: string;
  char_start: number;
  char_end: number;
  source_pages?: number[];
  page_start?: number | null;
  page_end?: number | null;
}

export interface DocumentContextParseResponse {
  file_name: string;
  mime_type?: string | null;
  media_kind?: "document" | "video";
  size_bytes: number;
  parser: string;
  title?: string | null;
  page_count?: number | null;
  section_titles: string[];
  section_snippets?: DocumentContextSectionSnippet[];
  markdown: string;
  char_count: number;
  truncated: boolean;
  extracted_images?: DocumentContextExtractedImage[];
  extracted_image_count?: number;
}

export async function parseDocumentContext(
  file: File,
): Promise<DocumentContextParseResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return getClient().postFormData<DocumentContextParseResponse>(
    "/api/v1/document-context/parse",
    formData,
  );
}
