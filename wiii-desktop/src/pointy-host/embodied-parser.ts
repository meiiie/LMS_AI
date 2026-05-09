/**
 * Embodied response parser (Wiii Pointy v5.0 — Body Schema).
 *
 * SOTA reference (2026):
 * - Anthropic Computer Use 2026 — agent describes actions in prose,
 *   parser extracts targets
 * - Project Astra (Google DeepMind) — multimodal grounding via name
 *   resolution from response
 * - Predictive coding (Friston 2010) — actions emerge from internal
 *   thoughts, not from explicit commands
 *
 * Architecture insight: Wiii is a SOUL with a body schema. The cursor
 * IS Wiii's hand — extension of identity, not a separate tool. When
 * Wiii's brain (LLM) thinks "the send button is at the bottom-right",
 * the hand naturally moves there. No protocol layer between thought
 * and action.
 *
 * Implementation: scan AI response text for co-occurring (a) intent
 * phrase + (b) element label match. When both signals present in the
 * same sentence, the body auto-points at that element.
 *
 * vs Clicky-style strict `[POINT:bare-id]` tag:
 *   - Tag: deterministic, fast — used when LLM remembers it
 *   - Embodied: works with ANY response style — used as fallback
 *
 * Both share the same `pointy.pointAt` dispatch endpoint.
 */

export interface AvailableTarget {
  id: string;
  label?: string;
  role?: string;
  /** v8.3 (2026-05-06) — synonym keywords for visual/icon descriptions
   * ("kẹp giấy" for paperclip icon, "máy bay giấy" for send arrow).
   * Read from `data-wiii-synonyms` comma-separated attribute. */
  synonyms?: string[];
}

export interface EmbodiedMatch {
  target: AvailableTarget;
  /** Score 0-1 (1 = perfect match). */
  score: number;
  /** Sentence that triggered the match (for caption). */
  sentence: string;
}

/**
 * Vietnamese + English intent phrases that signal "AI is pointing at
 * something on screen". When co-occurring in the same sentence as an
 * element label, treat as embodied dispatch trigger.
 *
 * Curated from observed AI responses (Vietnamese chatbot, NVIDIA
 * DeepSeek + Google Gemini training distribution). Not exhaustive —
 * fall through to no-match when phrase missing (better than false
 * positive cursor jumps).
 */
const INTENT_PHRASES_VI = [
  "trỏ vào",
  "trỏ đến",
  "trỏ tới",
  "đây nè",
  "đây rồi",
  "đây này",
  "là cái này",
  "ở đây",
  "ở góc",
  "nằm ở",
  "nằm ngay",
  "ngay góc",
  "click vào",
  "nhấn vào",
  "bấm vào",
  "chỉ cho cậu",
  "chỉ giúp",
  "đây là",
  "cái này nè",
  "thấy chưa",
  "thấy nè",
  "chỗ này",
  // v7.0 F13 expansion — multi-word intent phrases only (single-verb
  // forms like "nhấn " false-match because diacritic normalize collides:
  // "nhấn" → "nhan" matches "nhắn" in unrelated content). Keep specific
  // phrases.
  // Step markers (signal sequential UI instruction).
  "đầu tiên",
  "sau đó",
  "tiếp theo",
  "cuối cùng",
  "trước hết",
  // Verb + nút/cái (button/thing) — common Vietnamese UI directives.
  "nhấn nút",
  "bấm nút",
  "click nút",
  "click ",
  "click vô",
  "gõ ",
  "gõ vào",
  "nhập ",
  "nhập vào",
  "đổi ",
  "mở ",
  "ấn nút",
  "ấn vào",
  // Position phrases (often co-occur with element label).
  "góc dưới",
  "góc trên",
  "góc trái",
  "góc phải",
  "bên trái",
  "bên phải",
  "phía dưới",
  "phía trên",
  "ngay dưới",
  "ngay trên",
  "ngay đó",
  "ngay cạnh",
];

const INTENT_PHRASES_EN = [
  "point to",
  "pointing at",
  "right here",
  "click on",
  "located at",
  "in the bottom",
  "in the top",
  "in the corner",
  "this is the",
  "see this",
];

const ALL_INTENT_PHRASES = [...INTENT_PHRASES_VI, ...INTENT_PHRASES_EN];

const GENERIC_LABEL_PHRASES = new Set(["tin nhan"]);

/**
 * Normalize Vietnamese text (strip diacritics + lowercase) for fuzzy
 * matching. We compare both raw + normalized to maximize hit rate
 * across user typing variations.
 */
function normalize(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d");
}

/**
 * Split text into sentences. Vietnamese punctuation: `.!?` plus
 * newlines. Quoted strings or abbreviations not handled — accept
 * occasional over/under-split, body schema is forgiving.
 */
function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/**
 * Build searchable candidates for a target — its label normalized,
 * its id with `-` / `_` replaced by spaces, and label keywords.
 *
 * Example for `{id: "chat-send-button", label: "Gửi tin nhắn"}`:
 *   candidates = ["chat send button", "gui tin nhan", "gửi tin nhắn", "gửi", "tin nhắn"]
 */
function targetSearchCandidates(target: AvailableTarget): string[] {
  const cands: Set<string> = new Set();
  const idDeslugged = target.id.replace(/[-_]/g, " ").trim();
  if (target.id.trim()) {
    cands.add(target.id.toLowerCase());
  }
  if (idDeslugged) {
    cands.add(idDeslugged);
    cands.add(normalize(idDeslugged));
  }
  if (target.label) {
    const label = target.label.trim();
    if (label) {
      cands.add(label.toLowerCase());
      cands.add(normalize(label));
      const labelWords = label
        .split(/\s+/)
        .map((word) => word.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ""))
        .filter(Boolean);
      for (let i = 0; i < labelWords.length - 1; i += 1) {
        const phrase = `${labelWords[i]} ${labelWords[i + 1]}`.trim();
        const normalizedPhrase = normalize(phrase);
        if (
          normalizedPhrase.length >= 5 &&
          !GENERIC_LABEL_PHRASES.has(normalizedPhrase)
        ) {
          cands.add(phrase);
          cands.add(normalizedPhrase);
        }
      }
      // Common Vietnamese UI shorthand: users and models often say
      // "nút gửi" for the canonical label "Gửi tin nhắn". Keep it scoped to
      // button-like targets so generic prose still needs an intent phrase.
      const firstLabelWord = labelWords[0] || "";
      const firstLabelWordNorm = normalize(firstLabelWord);
      if (
        firstLabelWordNorm.length >= 3 &&
        (target.role || "").toLowerCase().includes("button")
      ) {
        cands.add(`nút ${firstLabelWord}`);
        cands.add(`nut ${firstLabelWordNorm}`);
      }
      // Also add only strong individual words. Short/common words create
      // bad body-schema jumps: "trỏ vào sao..." used to match "trò chuyện"
      // via normalized "tro", and generic explanations about "gửi" could
      // point at the send button without an actual instruction.
      for (const cleaned of labelWords) {
        const normalized = normalize(cleaned);
        if (normalized.length >= 5) {
          cands.add(cleaned);
          cands.add(normalized);
        }
      }
    }
  }
  // v8.3 — synonyms (visual/icon descriptions). Add as full phrases
  // (not split) so multi-word synonyms like "kẹp giấy", "máy bay giấy"
  // match as a unit, not as individual words ("giấy" alone false-matches).
  if (target.synonyms && target.synonyms.length > 0) {
    for (const syn of target.synonyms) {
      const s = syn.trim();
      if (s.length >= 3) {
        cands.add(s.toLowerCase());
        cands.add(normalize(s));
      }
    }
  }
  return [...cands].filter((c) => c.length >= 3);
}

/**
 * Score a sentence × target pair. Higher = more likely the AI is
 * pointing at this target. Score components (v8.1, 2026-05-06):
 *
 * - +0.5 base if any target candidate appears in sentence (FULL LABEL)
 * - +0.3 base if only PARTIAL/keyword match (e.g., id-deslugged word)
 * - +0.3 if intent phrase ALSO appears in same sentence
 * - +0.2 if best match was the FULL accessible label (not partial keyword)
 * - +0.2 if id appears verbatim (LLM read inventory)
 * - −0.2 if best match is a SHORT (≤4 char) id-deslugged keyword that's
 *   too generic (e.g., "chat" matching chat-textarea via id deslug —
 *   common false positive).
 *
 * Reference: research-at-mention 2026-05-06 + Anthropic Computer Use
 * grounding doc + axe-core target-prominence heuristics.
 */
function scoreSentence(
  sentence: string,
  target: AvailableTarget,
  candidates: string[],
): number {
  const sentLower = sentence.toLowerCase();
  const sentNorm = normalize(sentence);
  const fullLabel = (target.label || "").toLowerCase().trim();
  const fullLabelNorm = normalize(fullLabel);

  // (a) Element name match — track BOTH best and how strong (full vs partial).
  // v8.3 — synonyms full-match also count as "strong" (treated like full label).
  const synonymsNorm = (target.synonyms || []).map((s) =>
    normalize(s.toLowerCase()),
  );
  const synonymsLower = (target.synonyms || []).map((s) => s.toLowerCase());
  let bestCandidate = "";
  let isFullLabelMatch = false;
  let bestCandidateIndex = Number.POSITIVE_INFINITY;
  for (const cand of candidates) {
    if (cand.length < 3) continue;
    const rawIndex = sentLower.indexOf(cand);
    const normIndex = sentNorm.indexOf(cand);
    const matchIndex =
      rawIndex >= 0 ? rawIndex : normIndex >= 0 ? normIndex : -1;
    if (matchIndex >= 0) {
      if (cand.length > bestCandidate.length) {
        bestCandidate = cand;
        bestCandidateIndex = matchIndex;
        const isFullLabel =
          (fullLabel.length > 0 && cand === fullLabel) ||
          (fullLabelNorm.length > 0 && cand === fullLabelNorm);
        const isFullSynonym =
          synonymsLower.includes(cand) || synonymsNorm.includes(cand);
        isFullLabelMatch = isFullLabel || isFullSynonym;
      }
    }
  }
  if (!bestCandidate) return 0;

  // (a) Base: full-label match → 0.5, partial → 0.3 (lower confidence).
  let score = isFullLabelMatch ? 0.5 : 0.3;

  // (b) Intent phrase in same sentence.
  let hasIntentPhrase = false;
  for (const phrase of ALL_INTENT_PHRASES) {
    if (sentLower.includes(phrase) || sentNorm.includes(normalize(phrase))) {
      hasIntentPhrase = true;
      break;
    }
  }
  if (hasIntentPhrase) {
    score += 0.3;
  }

  // (c) Full-label bonus (strong signal LLM matched canonical label).
  if (Number.isFinite(bestCandidateIndex)) {
    score += Math.max(0, 0.05 - Math.min(bestCandidateIndex, 50) * 0.001);
  }

  // (d) ID verbatim — strongest signal (LLM emitted exact ID from inventory).
  if (sentLower.includes(target.id.toLowerCase())) {
    score += 0.2;
  }

  // (e) Penalize generic short keyword match SOURCED from id-deslug
  // (not from label). Common case: "chat" (4 chars) matching chat-textarea
  // via id "chat-textarea" → "chat textarea" → word "chat". When AI talks
  // about "chat" generically, this false-matches. We DON'T penalize when
  // the keyword comes from the LABEL (e.g., "gửi" from "Gửi tin nhắn"
  // is a legitimate semantic shorthand).
  const candidateInLabel =
    fullLabel.includes(bestCandidate) || fullLabelNorm.includes(bestCandidate);
  if (
    !isFullLabelMatch &&
    bestCandidate.length <= 4 &&
    !candidateInLabel
  ) {
    score -= 0.2;
  }

  return Math.max(0, Math.min(score, 1.0));
}

/**
 * Detect whether AI's response signals a body-schema point.
 *
 * Returns the best-scored target if it crosses the threshold (0.6 by
 * default — element name + intent phrase co-occurrence required).
 * Below threshold: returns null (no false-positive cursor jumps).
 */
export function detectEmbodiedPoint(
  responseText: string,
  availableTargets: AvailableTarget[],
  options: { threshold?: number } = {},
): EmbodiedMatch | null {
  const threshold = options.threshold ?? 0.6;
  if (!responseText || availableTargets.length === 0) return null;

  const sentences = splitSentences(responseText);
  if (sentences.length === 0) return null;

  let best: EmbodiedMatch | null = null;
  for (const target of availableTargets) {
    const candidates = targetSearchCandidates(target);
    if (candidates.length === 0) continue;
    for (const sentence of sentences) {
      const score = scoreSentence(sentence, target, candidates);
      if (score >= threshold && (!best || score > best.score)) {
        best = { target, score, sentence };
      }
    }
  }
  return best;
}

/**
 * v7.0 (2026-05-06) — Detect ALL embodied points in response, in
 * sentence-appearance order. Supports multi-target sequence dispatch:
 * "Đầu tiên X, rồi Y, cuối cùng Z" → queue X→Y→Z visits.
 *
 * Deduplication: if same target matches in multiple sentences, only
 * keep the first (highest-position) occurrence to avoid cursor
 * bouncing back to the same place.
 *
 * Returns ordered array. Empty array if no matches above threshold.
 */
export function detectAllEmbodiedPoints(
  responseText: string,
  availableTargets: AvailableTarget[],
  options: { threshold?: number; maxMatches?: number } = {},
): EmbodiedMatch[] {
  const threshold = options.threshold ?? 0.6;
  const maxMatches = options.maxMatches ?? 5;
  if (!responseText || availableTargets.length === 0) return [];

  const sentences = splitSentences(responseText);
  if (sentences.length === 0) return [];

  // Walk sentences in order. For each sentence, pick the best target
  // (if any). Dedupe targets — first appearance wins for that target.
  const seenTargetIds = new Set<string>();
  const matches: EmbodiedMatch[] = [];
  for (const sentence of sentences) {
    let bestForSentence: EmbodiedMatch | null = null;
    for (const target of availableTargets) {
      if (seenTargetIds.has(target.id)) continue;
      const candidates = targetSearchCandidates(target);
      if (candidates.length === 0) continue;
      const score = scoreSentence(sentence, target, candidates);
      if (
        score >= threshold &&
        (!bestForSentence || score > bestForSentence.score)
      ) {
        bestForSentence = { target, score, sentence };
      }
    }
    if (bestForSentence) {
      matches.push(bestForSentence);
      seenTargetIds.add(bestForSentence.target.id);
      if (matches.length >= maxMatches) break;
    }
  }
  return matches;
}
