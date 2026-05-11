export type PreviewSourceReference = {
  kind?: string;
  title?: string;
  chapter_title?: string;
  chapter_index?: number;
  lesson_index?: number;
  source_pages: Array<number | string>;
  excerpt?: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function optionalString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normalizePageValue(value: unknown): number | string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  return null;
}

function normalizePages(record: Record<string, unknown>): Array<number | string> {
  const raw =
    record.source_pages ??
    record.sourcePages ??
    record.pages ??
    record.page_numbers ??
    record.pageNumbers;
  const values = Array.isArray(raw) ? raw : [raw];
  return values
    .map(normalizePageValue)
    .filter((page): page is number | string => page != null);
}

export function normalizeSourceReferences(
  value: unknown,
): PreviewSourceReference[] {
  if (!Array.isArray(value)) return [];

  return value
    .map(asRecord)
    .filter((record): record is Record<string, unknown> => record != null)
    .map((record): PreviewSourceReference | null => {
      const sourcePages = normalizePages(record);
      if (sourcePages.length === 0) return null;
      const ref: PreviewSourceReference = { source_pages: sourcePages };
      const kind = optionalString(record.kind);
      const title = optionalString(record.title);
      const chapterTitle = optionalString(record.chapter_title ?? record.chapterTitle);
      const chapterIndex = optionalNumber(record.chapter_index ?? record.chapterIndex);
      const lessonIndex = optionalNumber(record.lesson_index ?? record.lessonIndex);
      const excerpt = optionalString(record.excerpt);
      if (kind) ref.kind = kind;
      if (title) ref.title = title;
      if (chapterTitle) ref.chapter_title = chapterTitle;
      if (typeof chapterIndex === "number") ref.chapter_index = chapterIndex;
      if (typeof lessonIndex === "number") ref.lesson_index = lessonIndex;
      if (excerpt) ref.excerpt = excerpt;
      return ref;
    })
    .filter((ref): ref is PreviewSourceReference => ref != null);
}

export function formatSourcePages(pages: Array<number | string>): string {
  return pages.map((page) => String(page)).join(", ");
}

export function sourceReferenceLabel(ref: PreviewSourceReference): string {
  if (ref.title) return ref.title;
  if (ref.chapter_title) return ref.chapter_title;
  if (typeof ref.chapter_index === "number" && typeof ref.lesson_index === "number") {
    return `Chương ${ref.chapter_index + 1}, bài ${ref.lesson_index + 1}`;
  }
  if (typeof ref.chapter_index === "number") {
    return `Chương ${ref.chapter_index + 1}`;
  }
  return ref.kind || "Nguồn";
}
