import { getClient } from "./client";

const ONE_MIB = 1024 * 1024;
const DOCUMENT_PARSE_BASE_TIMEOUT_MS = 120_000;
const DOCUMENT_PARSE_PER_MIB_TIMEOUT_MS = 15_000;
const DOCUMENT_PARSE_MAX_TIMEOUT_MS = 360_000;
const VIDEO_PARSE_BASE_TIMEOUT_MS = 240_000;
const VIDEO_PARSE_PER_MIB_TIMEOUT_MS = 30_000;
const VIDEO_PARSE_MAX_TIMEOUT_MS = 900_000;
const VIDEO_EXTENSIONS = new Set(["mp4", "m4v", "mov", "webm", "mkv"]);

export interface DocumentContextExtractedImage {
  id: string;
  label?: string | null;
  timestamp_seconds?: number | null;
  media_type: string;
  data: string;
  detail?: "auto" | "low" | "high";
}

export type DocumentContextProvenanceLevel =
  | "text_only"
  | "structured_text"
  | "page_marker"
  | "page_layout";

export interface DocumentContextEmbeddedAsset {
  id: string;
  kind: "image" | "figure" | "picture" | "table";
  label?: string | null;
  page?: number | null;
  text?: string | null;
  bbox?: Record<string, number> | null;
  has_data?: boolean;
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
  parser_chain?: string[];
  parser_warning?: string | null;
  provenance_level?: DocumentContextProvenanceLevel;
  title?: string | null;
  page_count?: number | null;
  section_titles: string[];
  section_snippets?: DocumentContextSectionSnippet[];
  markdown: string;
  char_count: number;
  truncated: boolean;
  extracted_images?: DocumentContextExtractedImage[];
  extracted_image_count?: number;
  embedded_assets?: DocumentContextEmbeddedAsset[];
  embedded_asset_count?: number;
  figure_count?: number;
  table_count?: number;
}

function clampTimeout(value: number, max: number): number {
  return Math.min(max, Math.max(DOCUMENT_PARSE_BASE_TIMEOUT_MS, value));
}

function isVideoFile(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  return file.type.startsWith("video/") || VIDEO_EXTENSIONS.has(extension);
}

export function getDocumentContextParseTimeoutMs(file: File): number {
  const sizeMiB = Math.max(1, Math.ceil((file.size || 0) / ONE_MIB));
  if (isVideoFile(file)) {
    return clampTimeout(
      VIDEO_PARSE_BASE_TIMEOUT_MS + sizeMiB * VIDEO_PARSE_PER_MIB_TIMEOUT_MS,
      VIDEO_PARSE_MAX_TIMEOUT_MS,
    );
  }
  return clampTimeout(
    DOCUMENT_PARSE_BASE_TIMEOUT_MS + sizeMiB * DOCUMENT_PARSE_PER_MIB_TIMEOUT_MS,
    DOCUMENT_PARSE_MAX_TIMEOUT_MS,
  );
}

export async function parseDocumentContext(
  file: File,
  options?: { parserMode?: "auto" | "fast" | "precision" },
): Promise<DocumentContextParseResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (options?.parserMode) {
    formData.append("parser_mode", options.parserMode);
  }
  return getClient().postFormData<DocumentContextParseResponse>(
    "/api/v1/document-context/parse",
    formData,
    getDocumentContextParseTimeoutMs(file),
  );
}
