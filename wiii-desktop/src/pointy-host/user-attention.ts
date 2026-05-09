/**
 * UserAttentionTracker — track presence + tab focus (Wiii Pointy v2.6).
 *
 * Trả lời câu hỏi của user: "Wiii có biết user đã rời trang để đi
 * click tab nào ngoài web hay không? đếm số lần user rời web?"
 *
 * Ngoài cursor position (UserCursorTracker v2.5), user có thể:
 *
 * - Switch sang tab khác (Cmd+Tab, click tab brower khác)
 *   → `document.visibilityState === "hidden"`
 * - Click ra ngoài cửa sổ Wiii (e.g., taskbar, another app)
 *   → `window.blur` event
 * - Focus quay lại
 *   → `window.focus` event + `visibilitychange` to "visible"
 *
 * Module này theo dõi cả 3 events, đếm số lần, đo duration của mỗi
 * lần "vắng", publish vào host context. AI có thể:
 *
 * - "Bạn vừa rời tab 3 lần trong 2 phút — câu trả lời của mình có
 *    quá dài không?"
 * - Resume context: "Bạn quay lại rồi à? Mình đang nói tới X..."
 * - Pause animation/streaming khi user không xem (tiết kiệm CPU)
 *
 * Tham khảo:
 * - W3C Page Visibility API: https://www.w3.org/TR/page-visibility/
 * - Anthropic Computer Use 2026 — agents that pause when user away
 *
 * Tham khảo doc: ``research-agentic-loop-sota-2026-05-06.md``
 */

export type AttentionStatus =
  | "active"      // tab visible + window focused
  | "blurred"     // window not focused but tab still visible (e.g., notification popup)
  | "hidden"      // tab not visible (user switched tab)
  | "idle";       // no mouse/keyboard activity in idle threshold

export type AttentionEventType =
  | "blur"        // window lost focus
  | "focus"       // window gained focus
  | "hide"        // tab became hidden (visibilitychange)
  | "show"        // tab became visible
  | "idle"        // user went idle (no input for threshold)
  | "active"      // user came back from idle
  | "copy"        // user copied to clipboard (v2.7)
  | "cut"         // user cut to clipboard (v2.7)
  | "paste"       // user pasted from clipboard (v2.7)
  | "contextmenu" // right-click / context menu opened (v2.7)
  | "beforeunload" // user navigating away or closing tab (v2.7)
  | "selectionchange"; // text selection changed (v2.7, throttled)

export interface AttentionEvent {
  type: AttentionEventType;
  at: number; // performance.now timestamp
  /** ms since last event (duration of previous state). */
  durationFromPreviousMs: number;
}

export interface UserAttentionState {
  /** Current high-level status. */
  status: AttentionStatus;
  /** Tab visibility (W3C Page Visibility API). */
  isVisible: boolean;
  /** Window has focus (window.focus / blur). */
  isFocused: boolean;

  /** Số lần user blur (rời window) trong session này. */
  blurCount: number;
  /** Số lần user hide tab (chuyển tab khác). */
  hideCount: number;
  /** ms tổng cộng user "vắng" (blur + hide gộp). */
  totalAwayMs: number;
  /** ms từ lúc user trở lại (nếu đang active). */
  msSinceReturn: number;
  /** ms vắng của lần "đi" gần nhất (0 nếu đang active). */
  lastAwayDurationMs: number;
  /** Timestamp của event gần nhất. */
  lastEventAt: number;
  /** Lịch sử events ngắn (last 10 events). */
  recentEvents: AttentionEvent[];

  /** v2.7: Số lần copy/cut tổng. AI biết user lưu info nhiều không. */
  copyCount: number;
  /** v2.7: Số lần paste. */
  pasteCount: number;
  /** v2.7: Số lần right-click / context menu. */
  contextMenuCount: number;
  /**
   * v2.7: Last text selection (max 200 chars). Useful: AI biết user
   * đang highlight gì để hỏi (e.g., user paste-into-chat selected
   * text from page). null nếu không có selection.
   */
  lastSelectedText: string | null;
}

export interface UserAttentionOptions {
  /** Window object (default: global). Override cho test. */
  win?: Window;
  /** Document (default: global). Override cho test. */
  doc?: Document;
  /** Idle threshold (ms) — không có mouse/keyboard quá ngưỡng = idle. */
  idleThresholdMs?: number;
  /** Số events giữ trong history. Default 10. */
  maxHistory?: number;
}

const DEFAULT_IDLE_MS = 30_000; // 30s
const DEFAULT_HISTORY = 10;

type Listener = (state: UserAttentionState) => void;

export class UserAttentionTracker {
  private win: Window | null;
  private doc: Document | null;
  private idleThresholdMs: number;
  private maxHistory: number;

  private state: UserAttentionState;
  private subscribers: Set<Listener> = new Set();
  private disposed = false;

  /** Timestamp khi state hiện tại bắt đầu (để compute duration). */
  private currentStateSince: number;
  /** Timestamp activity gần nhất (mouse/keyboard). */
  private lastActivityAt: number;
  /** Timer kiểm tra idle. */
  private idleTimer: ReturnType<typeof setInterval> | null = null;

  /** v2.7: throttle selectionchange — fired on every char of cursor move. */
  private selectionThrottleAt: number = 0;
  private selectionThrottleMs: number = 500;

  // Bound handlers cho cleanup.
  private onVisibilityChange: () => void;
  private onWindowBlur: () => void;
  private onWindowFocus: () => void;
  private onActivity: () => void;
  private onCopy: () => void;
  private onCut: () => void;
  private onPaste: () => void;
  private onContextMenu: () => void;
  private onBeforeUnload: () => void;
  private onSelectionChange: () => void;

  constructor(options: UserAttentionOptions = {}) {
    this.win = options.win ?? (typeof window !== "undefined" ? window : null);
    this.doc = options.doc ?? (typeof document !== "undefined" ? document : null);
    this.idleThresholdMs = options.idleThresholdMs ?? DEFAULT_IDLE_MS;
    this.maxHistory = options.maxHistory ?? DEFAULT_HISTORY;

    const now = performance.now();
    this.currentStateSince = now;
    this.lastActivityAt = now;
    // Default isFocused=true. Browser blur/focus events đều có
    // browser-side debounce (chỉ fire khi state thật sự đổi), nên
    // chúng ta không cần guard `if (!this.state.isFocused) return`
    // — điều đó breaks tests trong jsdom (hasFocus()=false init)
    // và không thêm safety thực tế trên real browser.
    this.state = {
      status: this.computeStatus(true, true),
      isVisible: this.doc?.visibilityState !== "hidden",
      isFocused: true,
      blurCount: 0,
      hideCount: 0,
      totalAwayMs: 0,
      msSinceReturn: 0,
      lastAwayDurationMs: 0,
      lastEventAt: now,
      recentEvents: [],
      copyCount: 0,
      pasteCount: 0,
      contextMenuCount: 0,
      lastSelectedText: null,
    };

    this.onVisibilityChange = () => this.handleVisibilityChange();
    this.onWindowBlur = () => this.handleBlur();
    this.onWindowFocus = () => this.handleFocus();
    this.onActivity = () => this.handleActivity();
    this.onCopy = () => this.handleClipboard("copy");
    this.onCut = () => this.handleClipboard("cut");
    this.onPaste = () => this.handleClipboard("paste");
    this.onContextMenu = () => this.handleContextMenu();
    this.onBeforeUnload = () => this.handleBeforeUnload();
    this.onSelectionChange = () => this.handleSelectionChange();

    if (this.doc) {
      this.doc.addEventListener("visibilitychange", this.onVisibilityChange);
      // v2.7: clipboard + context menu + selection events live on document.
      this.doc.addEventListener("copy", this.onCopy);
      this.doc.addEventListener("cut", this.onCut);
      this.doc.addEventListener("paste", this.onPaste);
      this.doc.addEventListener("contextmenu", this.onContextMenu);
      this.doc.addEventListener("selectionchange", this.onSelectionChange);
    }
    if (this.win) {
      this.win.addEventListener("blur", this.onWindowBlur);
      this.win.addEventListener("focus", this.onWindowFocus);
      // Activity events — chỉ bắt cơ bản, không heavy.
      this.win.addEventListener("mousemove", this.onActivity, { passive: true });
      this.win.addEventListener("keydown", this.onActivity);
      this.win.addEventListener("scroll", this.onActivity, { passive: true });
      this.win.addEventListener("touchstart", this.onActivity, { passive: true });
      // v2.7: pageleave event (user closing tab / navigating away).
      this.win.addEventListener("beforeunload", this.onBeforeUnload);
    }
    // Idle check periodic.
    this.idleTimer = setInterval(() => this.checkIdle(), 1000);
  }

  /** Sync snapshot. */
  snapshot(): UserAttentionState {
    // Recompute msSinceReturn live for accuracy.
    const now = performance.now();
    return {
      ...this.state,
      msSinceReturn:
        this.state.status === "active"
          ? now - this.currentStateSince
          : 0,
    };
  }

  /** Subscribe to state changes. */
  subscribe(callback: Listener): () => void {
    this.subscribers.add(callback);
    callback(this.snapshot());
    return () => {
      this.subscribers.delete(callback);
    };
  }

  /** Format compact text cho LLM. */
  describeForLLM(): string {
    const s = this.snapshot();
    const lines: string[] = [];
    lines.push(`User attention: status=${s.status}`);
    lines.push(
      `  visible=${s.isVisible} focused=${s.isFocused} blurs=${s.blurCount} tab_switches=${s.hideCount}`,
    );
    if (s.totalAwayMs > 0) {
      lines.push(`  total_away=${Math.round(s.totalAwayMs / 1000)}s`);
    }
    if (s.lastAwayDurationMs > 0 && s.status === "active") {
      lines.push(`  last_return: was away ${Math.round(s.lastAwayDurationMs / 1000)}s`);
    }
    // v2.7: behavioural counters.
    if (s.copyCount > 0 || s.pasteCount > 0 || s.contextMenuCount > 0) {
      lines.push(
        `  behaviour: copies=${s.copyCount} pastes=${s.pasteCount} right_clicks=${s.contextMenuCount}`,
      );
    }
    if (s.lastSelectedText) {
      const preview = s.lastSelectedText.length > 60
        ? s.lastSelectedText.slice(0, 57) + "…"
        : s.lastSelectedText;
      lines.push(`  selected_text: ${JSON.stringify(preview)}`);
    }
    if (s.recentEvents.length > 0) {
      const recent = s.recentEvents.slice(-3).map((e) => e.type).join(" → ");
      lines.push(`  recent_events: ${recent}`);
    }
    return lines.join("\n");
  }

  /** Tear down. Idempotent. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.doc) {
      this.doc.removeEventListener("visibilitychange", this.onVisibilityChange);
      this.doc.removeEventListener("copy", this.onCopy);
      this.doc.removeEventListener("cut", this.onCut);
      this.doc.removeEventListener("paste", this.onPaste);
      this.doc.removeEventListener("contextmenu", this.onContextMenu);
      this.doc.removeEventListener("selectionchange", this.onSelectionChange);
    }
    if (this.win) {
      this.win.removeEventListener("blur", this.onWindowBlur);
      this.win.removeEventListener("focus", this.onWindowFocus);
      this.win.removeEventListener("mousemove", this.onActivity);
      this.win.removeEventListener("keydown", this.onActivity);
      this.win.removeEventListener("scroll", this.onActivity);
      this.win.removeEventListener("touchstart", this.onActivity);
      this.win.removeEventListener("beforeunload", this.onBeforeUnload);
    }
    if (this.idleTimer) clearInterval(this.idleTimer);
    this.idleTimer = null;
    this.subscribers.clear();
  }

  // ────────────────────────────────────────────────────────────────────
  // Private handlers
  // ────────────────────────────────────────────────────────────────────

  private handleVisibilityChange(): void {
    const wasVisible = this.state.isVisible;
    const isVisible = this.doc?.visibilityState !== "hidden";
    if (wasVisible === isVisible) return;
    const now = performance.now();
    const duration = now - this.state.lastEventAt;

    if (!isVisible) {
      // User switched away
      this.state.hideCount += 1;
      this.recordEvent({ type: "hide", at: now, durationFromPreviousMs: duration });
      this.transitionTo(now);
    } else {
      // User came back
      this.state.totalAwayMs += duration;
      this.state.lastAwayDurationMs = duration;
      this.recordEvent({ type: "show", at: now, durationFromPreviousMs: duration });
      this.transitionTo(now);
    }

    this.state.isVisible = isVisible;
    this.state.lastEventAt = now;
    this.state.status = this.computeStatus(isVisible, this.state.isFocused);
    this.emit();
  }

  private handleBlur(): void {
    if (!this.state.isFocused) return;
    const now = performance.now();
    const duration = now - this.state.lastEventAt;
    this.state.blurCount += 1;
    this.state.isFocused = false;
    this.state.lastEventAt = now;
    this.state.status = this.computeStatus(this.state.isVisible, false);
    this.recordEvent({ type: "blur", at: now, durationFromPreviousMs: duration });
    this.transitionTo(now);
    this.emit();
  }

  private handleFocus(): void {
    if (this.state.isFocused) return;
    const now = performance.now();
    const duration = now - this.state.lastEventAt;
    if (!this.state.isVisible || this.state.status === "blurred") {
      this.state.totalAwayMs += duration;
      this.state.lastAwayDurationMs = duration;
    }
    this.state.isFocused = true;
    this.state.lastEventAt = now;
    this.state.status = this.computeStatus(this.state.isVisible, true);
    this.recordEvent({ type: "focus", at: now, durationFromPreviousMs: duration });
    this.transitionTo(now);
    this.emit();
  }

  private handleActivity(): void {
    this.lastActivityAt = performance.now();
    if (this.state.status === "idle") {
      // Coming out of idle.
      const now = this.lastActivityAt;
      const duration = now - this.state.lastEventAt;
      this.state.lastAwayDurationMs = duration;
      this.state.lastEventAt = now;
      this.state.status = this.computeStatus(this.state.isVisible, this.state.isFocused);
      this.recordEvent({ type: "active", at: now, durationFromPreviousMs: duration });
      this.transitionTo(now);
      this.emit();
    }
  }

  private checkIdle(): void {
    if (this.state.status === "idle") return; // Đã idle.
    const now = performance.now();
    const idleFor = now - this.lastActivityAt;
    if (idleFor >= this.idleThresholdMs && this.state.status === "active") {
      const duration = now - this.state.lastEventAt;
      this.state.lastEventAt = now;
      this.state.status = "idle";
      this.recordEvent({ type: "idle", at: now, durationFromPreviousMs: duration });
      this.transitionTo(now);
      this.emit();
    }
  }

  /**
   * v2.7: Clipboard event handler. Browser fires copy/cut/paste khi user
   * thực hiện hành động — chúng ta không đọc CONTENT của clipboard
   * (cần permission + privacy concern), chỉ đếm + log timestamp.
   */
  private handleClipboard(kind: "copy" | "cut" | "paste"): void {
    const now = performance.now();
    const duration = now - this.state.lastEventAt;
    if (kind === "copy" || kind === "cut") {
      this.state.copyCount += 1;
    } else {
      this.state.pasteCount += 1;
    }
    this.state.lastEventAt = now;
    this.recordEvent({ type: kind, at: now, durationFromPreviousMs: duration });
    this.emit();
  }

  /**
   * v2.7: Right-click / context menu opened. Heuristic: user có thể
   * đang inspect element hoặc dùng menu copy/save image. Đếm để AI
   * detect "user đang dò xét" pattern.
   */
  private handleContextMenu(): void {
    const now = performance.now();
    const duration = now - this.state.lastEventAt;
    this.state.contextMenuCount += 1;
    this.state.lastEventAt = now;
    this.recordEvent({
      type: "contextmenu",
      at: now,
      durationFromPreviousMs: duration,
    });
    this.emit();
  }

  /**
   * v2.7: User sắp đóng tab / navigate away. Last chance event —
   * không guarantee subscriber nhận được trước page tear down.
   */
  private handleBeforeUnload(): void {
    const now = performance.now();
    const duration = now - this.state.lastEventAt;
    this.recordEvent({
      type: "beforeunload",
      at: now,
      durationFromPreviousMs: duration,
    });
    // Do NOT call this.emit() here — subscribers run after page is
    // already in unload phase, results unpredictable.
  }

  /**
   * v2.7: Selection changed (user highlighted text). Throttled 500ms
   * vì selectionchange fires on every char of cursor drag.
   */
  private handleSelectionChange(): void {
    const now = performance.now();
    if (now - this.selectionThrottleAt < this.selectionThrottleMs) return;
    this.selectionThrottleAt = now;
    let selectedText: string | null = null;
    if (this.win && this.win.getSelection) {
      const sel = this.win.getSelection();
      const text = sel?.toString().trim() ?? "";
      if (text.length > 0) {
        selectedText = text.slice(0, 200);
      }
    }
    // Skip emit nếu selection trống và đã trống từ trước.
    if (selectedText === null && this.state.lastSelectedText === null) return;
    const duration = now - this.state.lastEventAt;
    this.state.lastSelectedText = selectedText;
    this.state.lastEventAt = now;
    this.recordEvent({
      type: "selectionchange",
      at: now,
      durationFromPreviousMs: duration,
    });
    this.emit();
  }

  private computeStatus(isVisible: boolean, isFocused: boolean): AttentionStatus {
    if (!isVisible) return "hidden";
    if (!isFocused) return "blurred";
    return "active";
  }

  private transitionTo(now: number): void {
    this.currentStateSince = now;
  }

  private recordEvent(ev: AttentionEvent): void {
    this.state.recentEvents.push(ev);
    if (this.state.recentEvents.length > this.maxHistory) {
      this.state.recentEvents.shift();
    }
  }

  private emit(): void {
    const snap = this.snapshot();
    for (const cb of this.subscribers) {
      try {
        cb(snap);
      } catch (err) {
        console.warn("[USER_ATTENTION] subscriber threw:", err);
      }
    }
  }
}
