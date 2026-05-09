import type {
  ChatDocumentAttachment,
  ChatDocumentContext,
  ChatDocumentContextAttachment,
  ImageInput,
} from "@/api/types";
import type { DocumentContextExtractedImage } from "@/api/document-context";

export const MAX_DOCUMENT_CONTEXT_CHARS = 8_000;

export interface ParsedDocumentForContext extends ChatDocumentContextAttachment {
  id: string;
  extracted_images?: DocumentContextExtractedImage[];
}

export function toDisplayDocumentAttachment(
  doc: ParsedDocumentForContext,
): ChatDocumentAttachment {
  return {
    id: doc.id,
    file_name: doc.file_name,
    mime_type: doc.mime_type,
    size_bytes: doc.size_bytes,
    parser: doc.parser,
    char_count: doc.char_count,
    truncated: doc.truncated,
    media_kind: doc.media_kind,
    extracted_image_count: doc.extracted_image_count,
  };
}

export function toImageInputsFromExtractedFrames(
  docs: ParsedDocumentForContext[],
  maxImages: number,
): ImageInput[] {
  if (maxImages <= 0) return [];
  const images: ImageInput[] = [];
  for (const doc of docs) {
    for (const frame of doc.extracted_images || []) {
      if (images.length >= maxImages) return images;
      if (!frame.data?.trim()) continue;
      images.push({
        type: "base64",
        media_type: frame.media_type || "image/jpeg",
        data: frame.data,
        detail: frame.detail || "low",
      });
    }
  }
  return images;
}

export function buildChatDocumentContext(
  docs: ParsedDocumentForContext[],
  maxChars = MAX_DOCUMENT_CONTEXT_CHARS,
): ChatDocumentContext | undefined {
  const readyDocs = docs.filter((doc) => doc.markdown.trim().length > 0);
  if (readyDocs.length === 0 || maxChars <= 0) return undefined;

  const perDocBudget = Math.max(800, Math.floor(maxChars / readyDocs.length));
  let remaining = maxChars;
  const attachments: ChatDocumentContextAttachment[] = [];

  for (const doc of readyDocs) {
    if (remaining <= 0) break;
    const budget = Math.min(perDocBudget, remaining);
    const markdown = doc.markdown.slice(0, budget).trim();
    if (!markdown) continue;
    remaining -= markdown.length;
    attachments.push({
      id: doc.id,
      file_name: doc.file_name,
      mime_type: doc.mime_type,
      size_bytes: doc.size_bytes,
      parser: doc.parser || "markitdown",
      char_count: doc.char_count,
      media_kind: doc.media_kind,
      extracted_image_count: doc.extracted_image_count,
      truncated: Boolean(doc.truncated || doc.markdown.length > markdown.length),
      markdown,
    });
  }

  if (attachments.length === 0) return undefined;
  return {
    source: "desktop_upload",
    attachments,
  };
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb >= 10 ? 0 : 1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}
