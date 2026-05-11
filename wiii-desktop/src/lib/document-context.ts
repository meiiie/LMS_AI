import type {
  ChatDocumentAttachment,
  ChatDocumentContext,
  ChatDocumentContextAttachment,
  ImageInput,
} from "@/api/types";
import type {
  DocumentContextExtractedImage,
  DocumentContextSectionSnippet,
} from "@/api/document-context";

export const MAX_DOCUMENT_CONTEXT_CHARS = 8_000;
const SECTION_CONTEXT_TITLE_LIMIT = 28;
const PRIORITY_SECTION_LIMIT = 4;
const PRIORITY_SECTION_CHARS = 1_300;

interface MarkdownSection {
  title: string;
  start: number;
  end: number;
  priority: number;
}

interface ContextSection {
  title: string;
  markdown: string;
  start: number;
  priority: number;
  sourcePages: number[];
}

export interface ParsedDocumentForContext extends ChatDocumentContextAttachment {
  id: string;
  extracted_images?: DocumentContextExtractedImage[];
  section_snippets?: DocumentContextSectionSnippet[];
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
    const markdown = buildBoundedDocumentMarkdown(doc, budget);
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

function buildBoundedDocumentMarkdown(
  doc: ParsedDocumentForContext,
  maxChars: number,
): string {
  const markdown = normalizeDocumentMarkdown(doc.markdown);
  if (markdown.length <= maxChars) return markdown.trim();

  const sections = buildContextSections(doc, markdown);
  if (sections.length === 0 || maxChars < 1_200) {
    return markdown.slice(0, maxChars).trim();
  }

  const title = `# Tài liệu upload: ${doc.file_name}`;
  const outline = renderSectionOutline(sections);
  const headBudget = Math.min(1_500, Math.max(700, Math.floor(maxChars * 0.22)));
  const chunks: string[] = [
    title,
    outline,
    "## Trích đoạn đầu tài liệu",
    markdown.slice(0, headBudget).trim(),
  ];

  const prioritySections = sections
    .filter((section) => section.priority > 0)
    .sort((left, right) => right.priority - left.priority || left.start - right.start)
    .slice(0, PRIORITY_SECTION_LIMIT);

  if (prioritySections.length > 0) {
    chunks.push("## Trích đoạn ưu tiên theo vai trò/chủ đề");
    for (const section of prioritySections) {
      chunks.push(
        [
          `### ${section.title}`,
          formatSectionSourceLine(section),
          section.markdown.slice(0, PRIORITY_SECTION_CHARS).trim(),
        ]
          .filter(Boolean)
          .join("\n"),
      );
    }
  }

  const tailBudget = Math.min(900, Math.max(350, Math.floor(maxChars * 0.12)));
  chunks.push("## Trích đoạn cuối tài liệu", markdown.slice(-tailBudget).trim());

  return compactToBudget(chunks.join("\n\n"), maxChars);
}

function normalizeDocumentMarkdown(markdown: string): string {
  return markdown
    .replace(/!\[[^\]]*]\(data:image\/[^)]+\)/gi, "")
    .replace(/data:image\/[^\s)]+/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractMarkdownSections(markdown: string): MarkdownSection[] {
  const headings: Array<{ title: string; start: number }> = [];
  const headingPattern = /^#{1,6}\s+(.+?)\s*$/gm;
  let match: RegExpExecArray | null;
  while ((match = headingPattern.exec(markdown)) !== null) {
    const title = match[1]?.trim();
    if (!title) continue;
    headings.push({ title, start: match.index });
  }

  return headings.map((heading, index) => ({
    title: heading.title,
    start: heading.start,
    end: headings[index + 1]?.start ?? markdown.length,
    priority: scoreSectionTitle(heading.title),
  }));
}

function buildContextSections(
  doc: ParsedDocumentForContext,
  fallbackMarkdown: string,
): ContextSection[] {
  const snippetSections = (doc.section_snippets || [])
    .map((snippet, index) => {
      const markdown = normalizeDocumentMarkdown(snippet.markdown || "");
      const title = snippet.title?.trim() || firstMarkdownHeading(markdown) || `Section ${index + 1}`;
      if (!markdown.trim()) return null;
      const sourcePages = normalizeSourcePages(snippet);
      return {
        title,
        markdown,
        start: Number.isFinite(snippet.char_start) ? snippet.char_start : index,
        priority: scoreSectionTitle(title),
        sourcePages,
      };
    })
    .filter((section): section is ContextSection => section !== null);

  if (snippetSections.length > 0) return snippetSections;

  return extractMarkdownSections(fallbackMarkdown).map((section) => ({
    title: section.title,
    markdown: fallbackMarkdown.slice(section.start, section.end).trim(),
    start: section.start,
    priority: section.priority,
    sourcePages: [],
  }));
}

function firstMarkdownHeading(markdown: string): string {
  const match = /^#{1,6}\s+(.+?)\s*$/m.exec(markdown);
  return match?.[1]?.trim() || "";
}

function normalizeSourcePages(snippet: DocumentContextSectionSnippet): number[] {
  const pages = Array.isArray(snippet.source_pages) ? snippet.source_pages : [];
  const explicit = pages
    .map((page) => Number(page))
    .filter((page) => Number.isFinite(page) && page > 0);
  if (explicit.length > 0) return [...new Set(explicit)];
  const start = Number(snippet.page_start);
  const end = Number(snippet.page_end);
  if (!Number.isFinite(start) || start <= 0) return [];
  if (!Number.isFinite(end) || end <= start) return [start];
  const range: number[] = [];
  for (let page = start; page <= end && range.length < 12; page += 1) {
    range.push(page);
  }
  return range;
}

function formatSectionSourceLine(section: ContextSection): string {
  const pages = section.sourcePages || [];
  if (pages.length === 0) return "";
  const pageText =
    pages.length === 1
      ? `trang ${pages[0]}`
      : `trang ${Math.min(...pages)}-${Math.max(...pages)}`;
  return `Nguồn section: ${section.title} (${pageText})`;
}

function scoreSectionTitle(title: string): number {
  const normalized = stripVietnameseDiacritics(title).toLowerCase();
  if (/\b(giang vien|giao vien|teacher|instructor)\b/.test(normalized)) return 100;
  if (/(tao khoa|soan|chuong va bai|cau hoi|bai tap|xuat ban|phan tich giang vien)/.test(normalized)) {
    return 85;
  }
  if (/\b(hoc vien|student|learner)\b/.test(normalized)) return 65;
  if (/\b(quan ly|org_admin|admin|manager)\b/.test(normalized)) return 55;
  if (/(checklist|quy trinh|video tuong tac|van hanh)/.test(normalized)) return 45;
  return 0;
}

function stripVietnameseDiacritics(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D");
}

function renderSectionOutline(sections: Array<{ title: string }>): string {
  const titles = sections
    .slice(0, SECTION_CONTEXT_TITLE_LIMIT)
    .map((section) => `- ${section.title}`)
    .join("\n");
  return `## Mục lục phát hiện\n${titles}`;
}

function compactToBudget(text: string, maxChars: number): string {
  const compacted = text.replace(/\n{3,}/g, "\n\n").trim();
  if (compacted.length <= maxChars) return compacted;
  const sliced = compacted.slice(0, maxChars).trimEnd();
  const lastBreak = sliced.lastIndexOf("\n## ");
  if (lastBreak > maxChars * 0.7) {
    return sliced.slice(0, lastBreak).trimEnd();
  }
  return sliced;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb >= 10 ? 0 : 1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}
