const SOUL_TAG_RE =
  /(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:[\s\S]*?(?:--\s*>|--\s*&gt;)/gi;
const SOUL_TAG_AT_START_RE =
  /^\s*(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:/i;
const SOUL_TAG_OPEN_RE =
  /(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:/i;
const SOUL_TAG_PREFIXES = ["<!--wiii_soul:", "&lt;!--wiii_soul:"];

export interface InternalMarkupStripResult {
  content: string;
  pending: string;
}

function compactSoulPrefix(value: string): string {
  return value.replace(/\s+/g, "").toLowerCase();
}

function stripCompleteSoulTags(value: string): string {
  return value.replace(SOUL_TAG_RE, "");
}

function findIncompleteSoulTagStart(value: string): number {
  const openMatch = value.match(SOUL_TAG_OPEN_RE);
  if (openMatch?.index != null) return openMatch.index;

  const scanStart = Math.max(0, value.length - 32);
  for (let index = scanStart; index < value.length; index += 1) {
    const compactTail = compactSoulPrefix(value.slice(index));
    if (
      compactTail &&
      SOUL_TAG_PREFIXES.some((prefix) => prefix.startsWith(compactTail))
    ) {
      return index;
    }
  }
  return -1;
}

export function stripWiiiInternalMarkup(value: string): string {
  if (!value) return value;
  const startsWithInternalTag = SOUL_TAG_AT_START_RE.test(value);
  let cleaned = stripCompleteSoulTags(value);
  const incompleteStart = findIncompleteSoulTagStart(cleaned);
  if (incompleteStart >= 0) {
    cleaned = cleaned.slice(0, incompleteStart);
  }
  return startsWithInternalTag ? cleaned.trimStart() : cleaned;
}

export function stripWiiiInternalMarkupFromStream(
  chunk: string,
  pending = "",
): InternalMarkupStripResult {
  const combined = `${pending}${chunk || ""}`;
  if (!combined) return { content: "", pending: "" };

  const startsWithInternalTag = SOUL_TAG_AT_START_RE.test(combined);
  let cleaned = stripCompleteSoulTags(combined);
  let nextPending = "";
  const incompleteStart = findIncompleteSoulTagStart(cleaned);
  if (incompleteStart >= 0) {
    nextPending = cleaned.slice(incompleteStart);
    cleaned = cleaned.slice(0, incompleteStart);
  }

  return {
    content: startsWithInternalTag ? cleaned.trimStart() : cleaned,
    pending: nextPending,
  };
}
