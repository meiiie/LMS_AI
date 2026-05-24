import type { HostContext } from "@/stores/host-context-store";

export const POINTY_FAST_PATH_SOURCE = "pointy_fast_path";

const LOCATE_TERMS = [
  "o dau",
  "where",
  "chi cho",
  "chi vao",
  "chi lai",
  "chi den",
  "chi toi",
  "chi giup",
  "tro vao",
  "tro toi",
  "tro den",
  "highlight",
  "nut",
  "button",
];

const CLICK_TERMS = [
  "mo",
  "bam",
  "click",
  "nhan vao",
  "vao khoa hoc",
  "vao trang",
  "vao muc",
  "vao tab",
  "di toi",
  "chuyen toi",
  "open",
];

const UNSAFE_CLICK_TERMS = [
  "submit",
  "nop bai",
  "quiz",
  "checkout",
  "payment",
  "thanh toan",
  "enroll",
  "dang ky",
  "logout",
  "dang xuat",
  "delete",
  "xoa",
  "mark complete",
  "hoan thanh",
];

const VISUAL_DELIVERY_TERMS = [
  "mo phong",
  "simulate",
  "simulation",
  "simulator",
  "canvas",
  "code studio",
  "tao visual",
  "tao hinh",
  "ve bieu do",
  "draw chart",
  "create chart",
  "mermaid",
  "html app",
];

const EXPLICIT_POINTY_OPERATOR_TERMS = [
  "pointy",
  "chi cho",
  "chi vao",
  "chi lai",
  "chi giup",
  "chi den",
  "chi toi",
  "tro toi",
  "tro vao",
  "tro den",
  "highlight",
  "show me where",
  "point to",
  "o dau",
  "where",
  "nut",
  "button",
  "bam",
  "click",
];

interface PointyTargetAlias {
  ids: string[];
  terms: string[];
}

interface ScoredPointyTarget {
  target: PointyFastPathTarget;
  score: number;
}

const TARGET_ALIASES: PointyTargetAlias[] = [
  {
    ids: ["chat-send-button", "send-message", "send-button", "gui-tin-nhan"],
    terms: ["gui tin nhan", "nut gui tin nhan", "nut gui", "send message", "send button"],
  },
  {
    ids: ["browse-courses", "browse-courses-link", "browse-courses-button"],
    terms: ["kham pha khoa hoc", "kham pha", "browse courses", "browse"],
  },
  {
    ids: ["continue-learn", "continue-lesson", "continue-course"],
    terms: ["tiep tuc hoc", "tiep tuc", "continue learning", "continue"],
  },
  {
    ids: ["my-courses", "my-courses-link"],
    terms: ["khoa hoc cua toi", "khoa hoc dang hoc", "my courses"],
  },
  {
    ids: ["profile-link", "profile-card"],
    terms: ["ho so", "profile"],
  },
];

export interface PointyFastPathTarget {
  id: string;
  selector: string;
  label?: string;
  click_safe?: boolean;
  click_kind?: string;
}

export interface PointyFastPathAction {
  action: "ui.highlight" | "ui.click";
  requestId: string;
  params: {
    selector: string;
    message?: string;
    duration_ms?: number;
    source: typeof POINTY_FAST_PATH_SOURCE;
  };
  target: PointyFastPathTarget;
  reason: "locate" | "click" | "unsafe_click_demoted";
}

export function normalizePointyText(value: string): string {
  return value
    .replace(/đ/g, "d")
    .replace(/Đ/g, "d")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "d")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function hasTerm(prompt: string, term: string): boolean {
  const normalizedTerm = normalizePointyText(term);
  if (!normalizedTerm) return false;
  return new RegExp(`(?:^|\\s)${escapeRegExp(normalizedTerm)}(?:\\s|$)`).test(prompt);
}

function hasAnyTerm(prompt: string, terms: string[]): boolean {
  return terms.some((term) => hasTerm(prompt, term));
}

const POINTY_EXPLICIT_DISPATCH_TERMS = [
  "wiii pointy",
  "chi vao",
  "chi lai",
  "chi cho",
  "chi giup",
  "tro vao",
  "tro toi",
  "tro den",
  "highlight",
  "point to",
  "where is",
  "o dau",
  "vi tri nut",
  "nut gui tin nhan",
  "nut gui",
  "nut dinh kem",
];

export function looksExplicitPointyTurn(prompt: string, forceSkills?: string[]): boolean {
  const forced = (forceSkills || []).some((skill) => (
    normalizePointyText(skill) === "wiii pointy"
    || normalizePointyText(skill) === "pointy"
  ));
  if (forced) return true;
  const normalizedPrompt = normalizePointyText(prompt);
  if (!normalizedPrompt) return false;
  return hasAnyTerm(normalizedPrompt, POINTY_EXPLICIT_DISPATCH_TERMS);
}

function coerceTarget(value: unknown): PointyFastPathTarget | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const id = typeof raw.id === "string" ? raw.id.trim() : "";
  const selector = typeof raw.selector === "string" ? raw.selector.trim() : "";
  if (!id || !selector) return null;
  return {
    id,
    selector,
    label: typeof raw.label === "string" ? raw.label.trim() : undefined,
    click_safe: raw.click_safe === true,
    click_kind: typeof raw.click_kind === "string" ? raw.click_kind.trim() : undefined,
  };
}

export function getPointyTargetsFromContext(ctx: HostContext | null): PointyFastPathTarget[] {
  const targets = ctx?.page?.metadata?.available_targets;
  if (!Array.isArray(targets)) return [];
  return targets.map(coerceTarget).filter((target): target is PointyFastPathTarget => Boolean(target));
}

function aliasScore(prompt: string, target: PointyFastPathTarget): number {
  const idText = normalizePointyText(target.id);
  for (const alias of TARGET_ALIASES) {
    const aliasMatchesPrompt = alias.terms.some((term) => hasTerm(prompt, term));
    if (!aliasMatchesPrompt) continue;
    if (alias.ids.some((id) => idText.includes(normalizePointyText(id)))) {
      return 40;
    }
  }
  return 0;
}

function targetScore(prompt: string, target: PointyFastPathTarget): number {
  const idText = normalizePointyText(target.id);
  const selectorText = normalizePointyText(target.selector);
  const labelText = normalizePointyText(target.label || "");
  const labelWords = labelText.split(" ").filter((word) => word.length >= 3);
  let score = aliasScore(prompt, target);

  if (labelText && hasTerm(prompt, labelText)) score += 35;
  if (idText && hasTerm(prompt, idText)) score += 24;
  if (selectorText && hasTerm(prompt, selectorText)) score += 12;
  if (labelWords.length > 0) {
    const matchedWords = labelWords.filter((word) => hasTerm(prompt, word)).length;
    score += matchedWords * 6;
    if (matchedWords === labelWords.length) score += 12;
  }

  if (target.click_safe) score += 2;
  return score;
}

function selectTarget(prompt: string, targets: PointyFastPathTarget[]): PointyFastPathTarget | null {
  let best: ScoredPointyTarget | null = null;
  for (const target of targets) {
    const score = targetScore(prompt, target);
    if (score <= 0) continue;
    if (!best || score > best.score) {
      best = { target, score };
    }
  }
  return best && best.score >= 12 ? best.target : null;
}

function withKnownWiiiTargets(
  prompt: string,
  ctx: HostContext | null,
  targets: PointyFastPathTarget[],
): PointyFastPathTarget[] {
  const hostType = normalizePointyText(ctx?.host_type || "");
  if (hostType !== "wiii desktop" && hostType !== "wiii web") return targets;
  const wantsSendButton =
    prompt.includes("gui tin nhan") ||
    prompt.includes("nut gui tin nhan") ||
    prompt.includes("nut gui") ||
    prompt.includes("send message") ||
    prompt.includes("send button");
  if (!wantsSendButton) return targets;
  if (targets.some((target) => target.id === "chat-send-button")) return targets;
  return [
    ...targets,
    {
      id: "chat-send-button",
      selector: "[data-wiii-id=\"chat-send-button\"]",
      label: "Gửi tin nhắn",
      click_safe: false,
      click_kind: "chat_send",
    },
  ];
}

function isUnsafeClickTarget(prompt: string, target: PointyFastPathTarget): boolean {
  const combined = normalizePointyText(
    `${prompt} ${target.id} ${target.label || ""} ${target.click_kind || ""}`,
  );
  return hasAnyTerm(combined, UNSAFE_CLICK_TERMS);
}

function makeRequestId(): string {
  const random = globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2, 12);
  return `pointy-fast-${random}`;
}

export function buildPointyFastPathAction(
  prompt: string,
  ctx: HostContext | null,
): PointyFastPathAction | null {
  const lastSource = ctx?.host_action_feedback?.last_action_result?.params?.source;
  if (lastSource === POINTY_FAST_PATH_SOURCE) return null;

  const normalizedPrompt = normalizePointyText(prompt);
  if (!normalizedPrompt) return null;
  if (
    hasAnyTerm(normalizedPrompt, VISUAL_DELIVERY_TERMS)
    && !hasAnyTerm(normalizedPrompt, EXPLICIT_POINTY_OPERATOR_TERMS)
  ) {
    return null;
  }
  const wantsLocate = hasAnyTerm(normalizedPrompt, LOCATE_TERMS);
  const wantsClick = hasAnyTerm(normalizedPrompt, CLICK_TERMS);
  if (!wantsLocate && !wantsClick) return null;

  const target = selectTarget(
    normalizedPrompt,
    withKnownWiiiTargets(normalizedPrompt, ctx, getPointyTargetsFromContext(ctx)),
  );
  if (!target) return null;

  const label = target.label || target.id;
  if (wantsClick && target.click_safe && !isUnsafeClickTarget(normalizedPrompt, target)) {
    return {
      action: "ui.click",
      requestId: makeRequestId(),
      params: {
        selector: target.id,
        message: `Wiii đang mở ${label} cho bạn.`,
        source: POINTY_FAST_PATH_SOURCE,
      },
      target,
      reason: "click",
    };
  }

  return {
    action: "ui.highlight",
    requestId: makeRequestId(),
    params: {
      selector: target.id,
      message: `Đây là ${label}. Wiii trỏ vào để bạn thấy ngay.`,
      duration_ms: wantsClick ? 5600 : 5200,
      source: POINTY_FAST_PATH_SOURCE,
    },
    target,
    reason: wantsClick ? "unsafe_click_demoted" : "locate",
  };
}
