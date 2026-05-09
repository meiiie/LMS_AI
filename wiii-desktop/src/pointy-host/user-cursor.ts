/**
 * UserCursorTracker — track REAL OS cursor của user (Wiii Pointy v2.5).
 *
 * Trả lời câu hỏi của user: "Wiii Pointy có biết được cursor của
 * chính người dùng đang ở đâu không?".
 *
 * Trước v2.5, Wiii chỉ biết AI's overlay cursor (SVG W badge cam).
 * Real OS mouse pointer hoàn toàn separate — browser quản lý, app
 * không có visibility. v2.5 thêm `mousemove` listener để track real
 * cursor: vị trí, hover element, idle duration, gần đây có click không.
 *
 * Lợi ích:
 *
 * 1. **AI biết user đang nhìn đâu** → context cho conversation. AI
 *    có thể nói "bạn đang trỏ vào X, có phải hỏi về nó không?".
 * 2. **Anti-collision**: Wiii cursor có thể avoid che user cursor.
 * 3. **Multi-cursor demo realistic**: Wiii cursor moves NEAR user
 *    cursor cho cảm giác collaborative.
 * 4. **Click anticipation**: nếu user dừng cursor lâu trên element,
 *    AI có thể proactively offer help ("Bạn cần biết về X?").
 *
 * Performance: throttled 50ms (≈20Hz, đủ smooth, không CPU spike).
 * Privacy: data ở trong app — không gửi ra ngoài trừ qua chat
 * request có user consent (cùng channel với HostContext).
 *
 * Tham khảo: ``research-agentic-loop-sota-2026-05-06.md``
 */

export interface UserCursorState {
  /** Vị trí current (viewport coords). null nếu chưa có mousemove event. */
  position: { x: number; y: number } | null;
  /** Element user đang hover (closest pointable). null nếu không có. */
  hoveredId: string | null;
  /** Selector của hovered element. */
  hoveredSelector: string | null;
  /** Label của hovered element (aria-label / text). */
  hoveredLabel: string | null;
  /** ms từ lần move gần nhất. Idle > 1000ms = user đang đọc gì đó. */
  idleMs: number;
  /** Có recent click trong 2s gần đây không? */
  recentlyClicked: boolean;
  /** Timestamp last move (ms epoch). */
  lastMoveAt: number;
}

export interface UserCursorTrackerOptions {
  /** Window object (default: global window). Override cho test. */
  win?: Window;
  /** Throttle ms cho mousemove. Default 50ms (≈20Hz). */
  throttleMs?: number;
  /** Idle threshold (ms) trên đó coi là "user đang dừng". */
  idleThresholdMs?: number;
}

const DEFAULT_THROTTLE = 50;
const DEFAULT_IDLE = 1000;
const RECENT_CLICK_WINDOW = 2000;

type Listener = (state: UserCursorState) => void;

export class UserCursorTracker {
  private win: Window;
  private throttleMs: number;
  private idleThresholdMs: number;

  private state: UserCursorState = {
    position: null,
    hoveredId: null,
    hoveredSelector: null,
    hoveredLabel: null,
    idleMs: 0,
    recentlyClicked: false,
    lastMoveAt: 0,
  };

  private subscribers: Set<Listener> = new Set();
  private lastEmittedSig: string = "";
  private lastMoveTime: number = 0;
  private pendingMoveX: number = 0;
  private pendingMoveY: number = 0;
  private pendingMove: boolean = false;
  private rafHandle: number = 0;
  private lastClickAt: number = 0;
  private idleTimer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;

  // Bound handlers (so we can removeEventListener cleanly).
  private onMouseMove: (e: MouseEvent) => void;
  private onMouseDown: () => void;

  constructor(options: UserCursorTrackerOptions = {}) {
    this.win = options.win ?? (typeof window !== "undefined" ? window : (null as never));
    this.throttleMs = options.throttleMs ?? DEFAULT_THROTTLE;
    this.idleThresholdMs = options.idleThresholdMs ?? DEFAULT_IDLE;

    this.onMouseMove = (e: MouseEvent) => this.handleMove(e);
    this.onMouseDown = () => this.handleClick();

    if (this.win) {
      this.win.addEventListener("mousemove", this.onMouseMove, { passive: true });
      this.win.addEventListener("mousedown", this.onMouseDown, { passive: true });
      // Periodic update of idleMs (mousemove throttled, idle counter
      // needs separate tick).
      this.idleTimer = setInterval(() => this.updateIdle(), 250);
    }
  }

  /** Sync snapshot of current state. */
  snapshot(): UserCursorState {
    return { ...this.state };
  }

  /** Subscribe to state changes. */
  subscribe(callback: Listener): () => void {
    this.subscribers.add(callback);
    callback(this.snapshot()); // initial push
    return () => {
      this.subscribers.delete(callback);
    };
  }

  /** Format compact text cho LLM consume. */
  describeForLLM(): string {
    const s = this.state;
    if (!s.position) return "User cursor: not tracked yet (no mouse movement detected).";
    const lines: string[] = [];
    lines.push(`User cursor: pos=(${s.position.x}, ${s.position.y}) idle=${s.idleMs}ms`);
    if (s.hoveredId) {
      const labelPart = s.hoveredLabel ? ` label="${s.hoveredLabel}"` : "";
      lines.push(`Hovering: id="${s.hoveredId}"${labelPart}`);
    }
    if (s.recentlyClicked) {
      lines.push("User clicked something within the last 2 seconds.");
    }
    return lines.join("\n");
  }

  /** Tear down listeners. Idempotent. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.win) {
      this.win.removeEventListener("mousemove", this.onMouseMove);
      this.win.removeEventListener("mousedown", this.onMouseDown);
    }
    if (this.idleTimer) clearInterval(this.idleTimer);
    this.idleTimer = null;
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    this.rafHandle = 0;
    this.subscribers.clear();
  }

  // ────────────────────────────────────────────────────────────────────
  // Private
  // ────────────────────────────────────────────────────────────────────

  private handleMove(e: MouseEvent): void {
    // Throttle: collapse rapid moves into one rAF frame.
    this.pendingMoveX = e.clientX;
    this.pendingMoveY = e.clientY;
    this.pendingMove = true;
    const now = performance.now();
    if (now - this.lastMoveTime < this.throttleMs) {
      // Too soon — defer to rAF if not already scheduled.
      if (!this.rafHandle) {
        this.rafHandle = requestAnimationFrame(() => {
          this.rafHandle = 0;
          this.flushMove();
        });
      }
      return;
    }
    this.lastMoveTime = now;
    this.flushMove();
  }

  private flushMove(): void {
    if (!this.pendingMove) return;
    this.pendingMove = false;
    const x = this.pendingMoveX;
    const y = this.pendingMoveY;
    const now = performance.now();
    this.state.position = { x, y };
    this.state.lastMoveAt = now;
    this.state.idleMs = 0;

    // Find element under cursor + extract pointable metadata.
    const hovered = this.findHoveredElement(x, y);
    this.state.hoveredId = hovered?.id ?? null;
    this.state.hoveredSelector = hovered?.selector ?? null;
    this.state.hoveredLabel = hovered?.label ?? null;

    this.emitIfChanged();
  }

  private handleClick(): void {
    this.lastClickAt = performance.now();
    this.state.recentlyClicked = true;
    this.emitIfChanged();
  }

  private updateIdle(): void {
    const now = performance.now();
    if (this.state.position) {
      this.state.idleMs = now - this.state.lastMoveAt;
    }
    // Decay recentlyClicked flag.
    const wasClicked = this.state.recentlyClicked;
    if (wasClicked && now - this.lastClickAt > RECENT_CLICK_WINDOW) {
      this.state.recentlyClicked = false;
    }
    if (this.state.idleMs >= this.idleThresholdMs || (wasClicked && !this.state.recentlyClicked)) {
      this.emitIfChanged();
    }
  }

  private findHoveredElement(
    x: number,
    y: number,
  ): { id: string; selector: string; label: string } | null {
    if (typeof document === "undefined" || typeof document.elementFromPoint !== "function") return null;
    const el = document.elementFromPoint(x, y);
    if (!el || !(el instanceof HTMLElement)) return null;
    // Walk up to find pointable ancestor (data-wiii-id or button/a/input).
    let current: HTMLElement | null = el;
    while (current && current !== document.body) {
      const wiiiId = current.getAttribute("data-wiii-id");
      const cssId = current.id;
      const tag = current.tagName.toLowerCase();
      const role = current.getAttribute("role");
      const isInteractiveTag =
        tag === "button" || tag === "a" || tag === "input" ||
        tag === "select" || tag === "textarea";
      const isInteractiveRole =
        role === "button" || role === "link" || role === "menuitem" || role === "tab";
      // data-wiii-id always wins. CSS id chỉ được tính pointable nếu
      // element thật sự interactive (tag hoặc ARIA role) — một
      // <span id="x"> bên trong <button> KHÔNG phải pointable, button
      // cha mới là.
      const isPointable =
        Boolean(wiiiId) ||
        (Boolean(cssId) && (isInteractiveTag || isInteractiveRole)) ||
        isInteractiveTag ||
        isInteractiveRole;
      if (isPointable) {
        const id = wiiiId || cssId || "";
        if (!id) {
          current = current.parentElement;
          continue;
        }
        const selector = wiiiId || (cssId ? `#${cssId}` : "");
        const label = inferLabel(current);
        return { id, selector, label };
      }
      current = current.parentElement;
    }
    return null;
  }

  private emitIfChanged(): void {
    const sig = this.signature();
    if (sig === this.lastEmittedSig) return;
    this.lastEmittedSig = sig;
    const snap = this.snapshot();
    for (const cb of this.subscribers) {
      try {
        cb(snap);
      } catch (err) {
        console.warn("[USER_CURSOR] subscriber threw:", err);
      }
    }
  }

  private signature(): string {
    const s = this.state;
    const px = s.position?.x ?? "?";
    const py = s.position?.y ?? "?";
    return [
      px, py,
      s.hoveredId ?? "",
      s.recentlyClicked ? "1" : "0",
      // Round idleMs to 250ms buckets so we don't emit every 4ms.
      Math.floor(s.idleMs / 250),
    ].join("|");
  }
}

function inferLabel(el: HTMLElement): string {
  const aria = el.getAttribute("aria-label");
  if (aria && aria.trim()) return aria.trim().slice(0, 60);
  const title = el.getAttribute("title");
  if (title && title.trim()) return title.trim().slice(0, 60);
  const text = (el.textContent || "").trim().replace(/\s+/g, " ");
  if (text) return text.slice(0, 60);
  return el.tagName.toLowerCase();
}
