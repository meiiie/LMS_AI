/**
 * ExamMode — opt-in proctoring helper (Wiii Pointy v2.7).
 *
 * Foundation cho LMS Maritime Education exam integration. Hiện tại
 * dùng được ngay trên Wiii's own web (opt-in flag), tương lai sẽ
 * tích hợp với LMS quiz/assignment qua webhook.
 *
 * **Scope rõ ràng**:
 *
 * - ExamMode KHÔNG thay thế dedicated proctoring software (Respondus,
 *   ProctorU, Honorlock). Browser sandbox limit nghiêm ngặt:
 *   * Không thể biết user đang xem URL nào ở tab khác
 *   * Không thể biết app native nào user mở (Cmd+Tab)
 *   * Không thể prevent screenshot điện thoại
 * - ExamMode CÓ thể: track tab focus, copy/paste, fullscreen,
 *   right-click, time-on-page, audit log → gửi LMS qua webhook.
 * - Vai trò: warning + audit + AI-driven hints, không enforcement.
 *
 * **Use cases**:
 *
 * 1. Wiii's own web (now): "focus mode" cho deep work — pause AI
 *    notifications, hide non-essential chrome, track distraction.
 * 2. LMS exam (future): proctor maritime law exams. Threshold-based
 *    flag (e.g., > 3 tab switches = warning), audit log gửi LMS.
 *
 * Tham khảo: ``research-browser-tracking-limits-2026-05-06.md``
 */

import {
  UserAttentionTracker,
  type AttentionEventType,
  type UserAttentionState,
} from "./user-attention";

/** Cấu hình cho 1 phiên ExamMode. */
export interface ExamModeConfig {
  /** ID phiên (e.g., quiz id). Audit log gắn với id này. */
  sessionId: string;
  /** Tên hiển thị (e.g., "Bài thi COLREG kỳ 1"). */
  sessionName?: string;
  /** Có request fullscreen không? Default false (Wiii's web không cần). */
  lockFullscreen?: boolean;
  /**
   * Threshold counts. Khi vượt ngưỡng, ExamMode emit "flag" event.
   * Caller (LMS hook) quyết định xử lý: warning user, fail exam, log...
   */
  thresholds?: {
    /** Max tab switches (visibilitychange to hidden). Default 5. */
    maxTabSwitches?: number;
    /** Max window blurs. Default 10 (less suspicious — popups, notifications). */
    maxBlurs?: number;
    /** Max copy/cut events. Default 3 (low — exam answers shouldn't be copied). */
    maxCopies?: number;
    /** Max paste events. Default 0 (zero — pastes immediately suspicious). */
    maxPastes?: number;
    /** Max ms total away. Default 60000 (1 minute total away time). */
    maxTotalAwayMs?: number;
  };
}

/** Một entry trong audit log. */
export interface ExamAuditEntry {
  sessionId: string;
  type: AttentionEventType | "flag" | "start" | "stop" | "fullscreen_exit";
  at: number; // performance.now timestamp
  /** ISO timestamp cho LMS persistence. */
  iso: string;
  /** Optional reason / label. */
  reason?: string;
  /** Snapshot tổng counts tại thời điểm này. */
  counters?: {
    blurCount: number;
    hideCount: number;
    copyCount: number;
    pasteCount: number;
    contextMenuCount: number;
    totalAwayMs: number;
  };
}

export type FlagReason =
  | "too_many_tab_switches"
  | "too_many_blurs"
  | "too_many_copies"
  | "paste_detected"
  | "too_much_away_time"
  | "fullscreen_exited";

export interface FlagEvent {
  reason: FlagReason;
  threshold: number;
  observed: number;
  at: number;
}

const DEFAULT_THRESHOLDS = {
  maxTabSwitches: 5,
  maxBlurs: 10,
  maxCopies: 3,
  maxPastes: 0,
  maxTotalAwayMs: 60_000,
};

type FlagListener = (flag: FlagEvent) => void;

/**
 * ExamMode wraps một UserAttentionTracker với threshold checks +
 * audit log. Stateful — gọi `start()` để bắt đầu phiên, `stop()` để
 * kết thúc. Trả về audit log để caller persist (e.g., POST lên LMS).
 */
export class ExamMode {
  private config: ExamModeConfig;
  private thresholds: Required<NonNullable<ExamModeConfig["thresholds"]>>;
  private tracker: UserAttentionTracker;
  private auditLog: ExamAuditEntry[] = [];
  private flaggedReasons: Set<FlagReason> = new Set();
  private flagListeners: Set<FlagListener> = new Set();
  private unsubAttention: (() => void) | null = null;
  private startedAt: number = 0;
  private stopped: boolean = false;
  private fullscreenChangeHandler: (() => void) | null = null;

  constructor(config: ExamModeConfig, tracker: UserAttentionTracker) {
    this.config = config;
    this.thresholds = { ...DEFAULT_THRESHOLDS, ...(config.thresholds ?? {}) };
    this.tracker = tracker;
  }

  /** Bắt đầu phiên exam — request fullscreen (nếu config), wire listeners. */
  async start(): Promise<void> {
    if (this.startedAt > 0) return;
    this.startedAt = performance.now();
    this.recordEntry({
      sessionId: this.config.sessionId,
      type: "start",
      at: this.startedAt,
      iso: new Date().toISOString(),
      reason: this.config.sessionName,
    });

    this.unsubAttention = this.tracker.subscribe((state) =>
      this.handleAttentionUpdate(state),
    );

    if (this.config.lockFullscreen && typeof document !== "undefined") {
      try {
        const el = document.documentElement;
        if (el.requestFullscreen) {
          await el.requestFullscreen();
        }
        // Detect exit fullscreen → flag.
        this.fullscreenChangeHandler = () => this.handleFullscreenChange();
        document.addEventListener(
          "fullscreenchange",
          this.fullscreenChangeHandler,
        );
      } catch (err) {
        console.warn("[EXAM_MODE] fullscreen request failed:", err);
      }
    }
  }

  /** Kết thúc phiên — release fullscreen, unsub. Returns final audit log. */
  async stop(): Promise<ExamAuditEntry[]> {
    if (this.stopped) return [...this.auditLog];
    this.stopped = true;
    this.unsubAttention?.();
    this.unsubAttention = null;

    if (this.fullscreenChangeHandler && typeof document !== "undefined") {
      document.removeEventListener(
        "fullscreenchange",
        this.fullscreenChangeHandler,
      );
      this.fullscreenChangeHandler = null;
    }

    if (
      this.config.lockFullscreen &&
      typeof document !== "undefined" &&
      document.fullscreenElement &&
      document.exitFullscreen
    ) {
      try {
        await document.exitFullscreen();
      } catch (err) {
        console.warn("[EXAM_MODE] exit fullscreen failed:", err);
      }
    }

    this.recordEntry({
      sessionId: this.config.sessionId,
      type: "stop",
      at: performance.now(),
      iso: new Date().toISOString(),
    });

    return [...this.auditLog];
  }

  /** Subscribe để nhận flag events khi threshold vượt. */
  onFlag(listener: FlagListener): () => void {
    this.flagListeners.add(listener);
    return () => {
      this.flagListeners.delete(listener);
    };
  }

  /** Read-only audit log snapshot. */
  getAuditLog(): ExamAuditEntry[] {
    return [...this.auditLog];
  }

  /** Returns Set of flag reasons that fired this session. */
  getFlaggedReasons(): FlagReason[] {
    return [...this.flaggedReasons];
  }

  // ────────────────────────────────────────────────────────────────────
  // Private
  // ────────────────────────────────────────────────────────────────────

  /**
   * Track timestamp của event cuối cùng đã ghi vào audit để dedup —
   * phòng trường hợp subscribe push state nhiều lần với cùng recentEvents
   * mà không có event mới.
   */
  private lastRecordedEventAt: number = 0;

  private handleAttentionUpdate(state: UserAttentionState): void {
    if (this.stopped) return;
    const lastEvent = state.recentEvents[state.recentEvents.length - 1];
    if (lastEvent && lastEvent.at > this.startedAt && lastEvent.at > this.lastRecordedEventAt) {
      this.lastRecordedEventAt = lastEvent.at;
      this.recordEntry({
        sessionId: this.config.sessionId,
        type: lastEvent.type,
        at: lastEvent.at,
        iso: new Date().toISOString(),
        counters: this.snapshotCounters(state),
      });
    }

    // Check thresholds.
    this.checkThreshold(
      "too_many_tab_switches",
      state.hideCount,
      this.thresholds.maxTabSwitches,
    );
    this.checkThreshold(
      "too_many_blurs",
      state.blurCount,
      this.thresholds.maxBlurs,
    );
    this.checkThreshold(
      "too_many_copies",
      state.copyCount,
      this.thresholds.maxCopies,
    );
    this.checkThreshold(
      "paste_detected",
      state.pasteCount,
      this.thresholds.maxPastes,
    );
    this.checkThreshold(
      "too_much_away_time",
      state.totalAwayMs,
      this.thresholds.maxTotalAwayMs,
    );
  }

  private checkThreshold(
    reason: FlagReason,
    observed: number,
    threshold: number,
  ): void {
    if (observed > threshold && !this.flaggedReasons.has(reason)) {
      this.flaggedReasons.add(reason);
      const flag: FlagEvent = {
        reason,
        threshold,
        observed,
        at: performance.now(),
      };
      this.recordEntry({
        sessionId: this.config.sessionId,
        type: "flag",
        at: flag.at,
        iso: new Date().toISOString(),
        reason,
        counters: undefined,
      });
      for (const listener of this.flagListeners) {
        try {
          listener(flag);
        } catch (err) {
          console.warn("[EXAM_MODE] flag listener threw:", err);
        }
      }
    }
  }

  private handleFullscreenChange(): void {
    if (typeof document === "undefined") return;
    // User exited fullscreen during exam — flag.
    if (!document.fullscreenElement && !this.flaggedReasons.has("fullscreen_exited")) {
      this.flaggedReasons.add("fullscreen_exited");
      const flag: FlagEvent = {
        reason: "fullscreen_exited",
        threshold: 0,
        observed: 1,
        at: performance.now(),
      };
      this.recordEntry({
        sessionId: this.config.sessionId,
        type: "fullscreen_exit",
        at: flag.at,
        iso: new Date().toISOString(),
      });
      for (const listener of this.flagListeners) {
        try {
          listener(flag);
        } catch (err) {
          console.warn("[EXAM_MODE] flag listener threw:", err);
        }
      }
    }
  }

  private snapshotCounters(
    state: UserAttentionState,
  ): NonNullable<ExamAuditEntry["counters"]> {
    return {
      blurCount: state.blurCount,
      hideCount: state.hideCount,
      copyCount: state.copyCount,
      pasteCount: state.pasteCount,
      contextMenuCount: state.contextMenuCount,
      totalAwayMs: Math.round(state.totalAwayMs),
    };
  }

  private recordEntry(entry: ExamAuditEntry): void {
    this.auditLog.push(entry);
  }
}
