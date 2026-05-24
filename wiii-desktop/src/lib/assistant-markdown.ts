const FENCED_BLOCK_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
const TABLE_SEPARATOR_ROW_RE =
  /\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?/;

function splitCodeSafe(content: string): string[] {
  return content.split(FENCED_BLOCK_RE);
}

function isFencedBlock(segment: string): boolean {
  return /^(```|~~~)/.test(segment.trimStart());
}

function normalizeInlineSeparators(segment: string): string {
  const promoted = segment
    .replace(/([^|\n])\s+(---|\*\*\*|___)\s+(?=\S)/g, "$1\n\n$2\n\n")
    .replace(/[ \t]+([0-9]{1,2}[.)])[ \t]+(?=\S)/g, "\n$1 ")
    .replace(/[ \t]+([-*+])[ \t]+(?=\S)/g, (match, marker, offset, source) => {
      const before = source.slice(Math.max(0, offset - 24), offset);
      if (!/[:.;!?)]\s*$|\n\s*$/.test(before)) return match;
      return `\n${marker} `;
    });

  let next = promoted;
  for (let pass = 0; pass < 4; pass += 1) {
    const previous = next;
    next = next.replace(
      /(\n[ \t]*[-*+][ \t]+[^\n]*?)[ \t]+([-*+])[ \t]+(?=\S)/g,
      (match, prefix: string, marker: string, offset: number, source: string) => {
        const after = source.slice(offset + match.length, offset + match.length + 16);
        if (/^[A-Z]\b/.test(after)) return match;
        return `${prefix}\n${marker} `;
      },
    );
    if (next === previous) break;
  }
  return next;
}

function normalizeCollapsedPipeTableLine(line: string): string {
  if (!TABLE_SEPARATOR_ROW_RE.test(line)) return line;

  const firstPipe = line.indexOf("|");
  if (firstPipe < 0) return line;

  const prefix = line.slice(0, firstPipe).trimEnd();
  const table = line
    .slice(firstPipe)
    .trim()
    .replace(/\|\s+\|(?=\s*\S)/g, "|\n|")
    .replace(/\|\s+(---|\*\*\*|___)\s+(?=\S)/g, "|\n\n$1\n\n")
    .split("\n")
    .map((row) => row.trim())
    .filter(Boolean)
    .join("\n");

  if (!prefix) return table;
  return `${prefix}\n\n${table}`;
}

function normalizeCollapsedPipeTables(segment: string): string {
  return segment
    .split("\n")
    .map(normalizeCollapsedPipeTableLine)
    .join("\n");
}

function normalizeParagraphSpacing(segment: string): string {
  return segment
    .replace(/\n(---|\*\*\*|___)\n/g, "\n\n$1\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n");
}

function normalizeMarkdownSegment(segment: string): string {
  const withTables = normalizeCollapsedPipeTables(segment);
  const withSeparators = normalizeInlineSeparators(withTables);
  return normalizeParagraphSpacing(withSeparators);
}

export function normalizeAssistantMarkdown(content: string): string {
  if (!content) return content;

  return splitCodeSafe(content)
    .map((segment) =>
      isFencedBlock(segment) ? segment : normalizeMarkdownSegment(segment),
    )
    .join("");
}
