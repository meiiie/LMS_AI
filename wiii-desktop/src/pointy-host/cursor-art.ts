/**
 * Cursor SVG art (Wiii Pointy v2.1 — SOTA 2026 redesign).
 *
 * Tách khỏi registry để dễ swap art theo identity / theme. Thiết kế
 * theo chuẩn Liveblocks / Figma 2024 / Linear / tldraw 2026:
 *
 * - 24×24px viewBox (gọn, không che nội dung; v2 dùng 124×62 quá to).
 * - Fill = identity.color (color-tinted body — KHÔNG phải đen 100%
 *   như v2; modern multiplayer cursors không bao giờ dùng đen pure).
 * - Stroke trắng 1.5px → giữ contrast trên cả light + dark background.
 * - Bo tròn các đường nối (``stroke-linejoin="round"``).
 * - **Không có** pulse ring, không có badge gắn liền — name pill nằm
 *   ở `<div>` riêng (xem ``namePillMarkup``) để animate độc lập + giữ
 *   font crisp (không bị blur theo drop-shadow filter của cursor).
 *
 * Tip vị trí trong viewBox: ``(CURSOR_TIP_X, CURSOR_TIP_Y) = (5, 3)``.
 * Đây là điểm cursor "trỏ vào" — khi caller muốn cursor land trên
 * element ở (x, y), dịch SVG sao cho tip nằm tại (x, y).
 *
 * Tham khảo: ``research-cursor-art-sota-2026-05-06.md``
 */

import type { CursorIdentity } from "./identity";

// v2.2: bump 24 → 28px theo user feedback. Vẫn dưới Liveblocks
// "comfortable" 32px nhưng đủ visible trên màn 1080p+ retina.
export const CURSOR_VIEWBOX_W = 28;
export const CURSOR_VIEWBOX_H = 28;
/** Vị trí mũi cursor trong viewBox (28×28). */
export const CURSOR_TIP_X = 6;
export const CURSOR_TIP_Y = 3;

/**
 * Sinh innerHTML cho `<svg>` cursor. SVG element được tạo bên ngoài
 * (registry quản lý DOM lifecycle); hàm này chỉ trả về phần markup
 * bên trong.
 */
export function cursorSvgInner(identity: CursorIdentity): string {
  const fill = identity.color;
  // Path scaled 24→28: tip ở (6, 3), mũi tên rộng hơn ~17%, body
  // dài 23.5 (từ y=3 đến y=23). Stroke-width 1.7 (tăng nhẹ vì
  // cursor lớn hơn — giữ tỷ lệ visual với 24px version).
  return `
    <path
      d="M6 3 L6 23.4 L10.97 19.27 L13.84 25.27 L16.39 24.10 L13.53 18.13 L19.89 18.13 Z"
      fill="${fill}"
      stroke="white"
      stroke-width="1.7"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
  `;
}

/**
 * Style cố định cho cursor SVG. Drop shadow nhẹ theo Figma 2024 (v2
 * dùng `drop-shadow(0 12px 26px rgba(15,23,42,0.26))` quá nặng và
 * blur cả label text — giờ shadow rời, chỉ áp lên cursor body).
 */
export function cursorSvgStyle(): Partial<CSSStyleDeclaration> {
  return {
    position: "fixed",
    left: "0",
    top: "0",
    zIndex: "2147483640",
    pointerEvents: "none",
    transformOrigin: `${CURSOR_TIP_X}px ${CURSOR_TIP_Y}px`,
    filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.20))",
    overflow: "visible",
    willChange: "transform, opacity",
    // KHÔNG `transition: opacity ...`: state changes (idle/moving) cần
    // phản hồi tức thì, không lag. Fade-in lúc spawn dùng opacity start
    // = 0 + reset trong tick đầu (xem registry).
  };
}

export interface NamePillStyle {
  /** Background = identity color (giữ contrast với text trắng). */
  background: string;
  /** Text trắng — đối nghịch với background đậm. */
  color: string;
  /** Stroke 1.5px tone-on-tone (background + 6% white) cho viền tinh tế. */
  borderColor: string;
}

export function namePillStyle(identity: CursorIdentity): NamePillStyle {
  return {
    background: identity.color,
    color: "white",
    borderColor: "rgba(255, 255, 255, 0.18)",
  };
}

/**
 * Sinh innerText cho name pill. Cắt 24 ký tự để pill không quá rộng
 * khi name dài (e.g., username Vietnamese + emoji).
 */
export function pillLabel(label: string, identity: CursorIdentity): string {
  const raw = (label || identity.name || "").trim();
  if (!raw) return identity.name || "?";
  return raw.length > 24 ? raw.slice(0, 23) + "…" : raw;
}

/** Offset name pill so với cursor tip (theo viewport coords). */
export const PILL_OFFSET_X = 14;
export const PILL_OFFSET_Y = 18;
