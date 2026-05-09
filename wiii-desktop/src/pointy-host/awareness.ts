/**
 * CursorAwareness — cursor self-introspection (Wiii Pointy v2.4).
 *
 * Trả lời câu hỏi của user: "Wiii Pointy biết cursor mình đang ở đâu
 * làm gì và tính làm gì?".
 *
 * Mỗi cursor trong CursorRegistry có internal state (position, motion,
 * awareness state). Module này expose state đó qua API + subscription
 * pattern để:
 *
 *   - UI components đọc realtime (hiển thị status bar, debugging)
 *   - Backend AI biết qua host_context (Sprint 222 reuse)
 *   - Tools as ``tool_pointy_inventory`` báo cáo current state
 *
 * Tham khảo: ``research-cursor-awareness-2026-05-06.md``
 */

import type { CursorRegistry } from "./registry";
import type { AwarenessState, CursorIdentity } from "./identity";
import type { Vec2 } from "./interpolator";
import type { MotionStrategy } from "./motion-engine";

/**
 * Snapshot trạng thái của 1 cursor tại một thời điểm. Plain object,
 * không reference internal mutable state — an toàn để serialize qua
 * SSE / PostMessage / chat request.
 */
export interface CursorStateSnapshot {
  /** Identity + visual identity. */
  identity: CursorIdentity;

  /** Vị trí hiện tại (viewport coords). */
  position: Vec2;
  /** Vận tốc hiện tại (px/giây). */
  velocity: Vec2;
  /** Speed scalar (px/giây) — tiện cho UI threshold. */
  speed: number;

  /** Cursor đang còn di chuyển hay đã settle? */
  isMoving: boolean;

  /**
   * Selector của target gần nhất cursor được trỏ vào (qua pointAt).
   * null nếu cursor chưa từng được điểm hoặc đã clear.
   */
  currentSelector: string | null;
  /** Caption đang hiển thị trên pill (= label hiện tại). */
  currentCaption: string | null;

  /** Strategy motion engine đang dùng. */
  motionStrategy: MotionStrategy;
  /** Awareness state chính thức (idle/moving/pointing/...). */
  awarenessState: AwarenessState;

  /** Timestamp last update (ms từ performance.now epoch). */
  lastUpdateAt: number;
}

/**
 * State chung của toàn bộ pointy host — trạng thái mọi cursor đang
 * sống cộng thông tin context.
 */
export interface PointyAwarenessSnapshot {
  /** Tất cả cursors đang được render. */
  cursors: CursorStateSnapshot[];
  /** Số cursor active (== cursors.length, tiện cho UI). */
  cursorCount: number;
  /** Có cursor nào đang ở trạng thái "pointing" không? */
  anyPointing: boolean;
  /** Timestamp khi snapshot lấy (ms epoch). */
  takenAt: number;
}

type Subscriber = (snapshot: PointyAwarenessSnapshot) => void;

/**
 * Awareness wrapper around CursorRegistry. Caller giữ cùng registry
 * instance dùng để render → awareness mirror state.
 */
export class CursorAwareness {
  private registry: CursorRegistry;
  /**
   * Side-table track per-cursor activity metadata mà CursorRegistry
   * không lưu (nó chỉ care về render). Map id → { selector, caption }.
   */
  private activity: Map<
    string,
    { selector: string | null; caption: string | null }
  > = new Map();
  private subscribers: Set<Subscriber> = new Set();
  private rafHandle = 0;
  private disposed = false;

  constructor(registry: CursorRegistry) {
    this.registry = registry;
  }

  /**
   * Cập nhật metadata activity khi caller pointAt / moveTo / clear.
   * Gọi từ pointy-host/api.ts để awareness phản ánh chính xác intent.
   */
  recordActivity(
    cursorId: string,
    activity: { selector?: string | null; caption?: string | null },
  ): void {
    const current = this.activity.get(cursorId) ?? {
      selector: null,
      caption: null,
    };
    if (activity.selector !== undefined) current.selector = activity.selector;
    if (activity.caption !== undefined) current.caption = activity.caption;
    this.activity.set(cursorId, current);
  }

  /** Lấy snapshot ngay tại thời điểm này (sync, không subscribe). */
  snapshot(): PointyAwarenessSnapshot {
    const cursors: CursorStateSnapshot[] = [];
    for (const id of this.registry.ids()) {
      const cursorSnap = this.cursorSnapshot(id);
      if (cursorSnap) cursors.push(cursorSnap);
    }
    return {
      cursors,
      cursorCount: cursors.length,
      anyPointing: cursors.some((c) => c.awarenessState === "pointing"),
      takenAt: performance.now(),
    };
  }

  /** Snapshot của 1 cursor cụ thể. null nếu cursor không tồn tại. */
  cursorSnapshot(id: string): CursorStateSnapshot | null {
    const internal = (
      this.registry as unknown as {
        cursors: Map<string, InternalCursorEntry>;
      }
    ).cursors.get(id);
    if (!internal) return null;

    const pos = internal.motion.position();
    const vel = internal.motion.velocity();
    const activity = this.activity.get(id) ?? {
      selector: null,
      caption: null,
    };

    return {
      identity: { ...internal.identity },
      position: { ...pos },
      velocity: { ...vel },
      speed: Math.hypot(vel.x, vel.y),
      isMoving: !internal.motion.isSettled(),
      currentSelector: activity.selector,
      currentCaption: activity.caption ?? internal.label ?? null,
      motionStrategy: internal.motion.currentStrategy(),
      awarenessState: internal.state,
      lastUpdateAt: internal.lastUpdateAt,
    };
  }

  /**
   * Subscribe để nhận snapshot mới mỗi rAF tick. Trả về unsubscribe
   * function. Subscribers tự động driving rAF loop khi cần.
   */
  subscribe(callback: Subscriber): () => void {
    this.subscribers.add(callback);
    if (this.rafHandle === 0 && !this.disposed) {
      this.startRaf();
    }
    return () => {
      this.subscribers.delete(callback);
      if (this.subscribers.size === 0) {
        this.stopRaf();
      }
    };
  }

  /**
   * Trả về snapshot dạng compact cho LLM consume. Format text-friendly,
   * không nhiều dấu ngoặc, dễ parse + dễ đọc cho debugger.
   */
  describeForLLM(): string {
    const snap = this.snapshot();
    if (snap.cursorCount === 0) return "No cursors active.";
    const lines: string[] = [];
    lines.push(`Cursors active: ${snap.cursorCount}`);
    for (const c of snap.cursors) {
      const pos = `(${Math.round(c.position.x)}, ${Math.round(c.position.y)})`;
      const moving = c.isMoving ? "moving" : "settled";
      const target = c.currentSelector
        ? ` last_target=${JSON.stringify(c.currentSelector)}`
        : "";
      const caption = c.currentCaption
        ? ` caption=${JSON.stringify(c.currentCaption)}`
        : "";
      lines.push(
        `- ${c.identity.name} (id=${c.identity.id}) pos=${pos} state=${c.awarenessState} ${moving} strategy=${c.motionStrategy}${target}${caption}`,
      );
    }
    return lines.join("\n");
  }

  /** Unsubscribe all + stop rAF. Idempotent. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.subscribers.clear();
    this.stopRaf();
    this.activity.clear();
  }

  // ────────────────────────────────────────────────────────────────────
  // Private: rAF loop emits snapshots to subscribers.
  // ────────────────────────────────────────────────────────────────────

  private startRaf(): void {
    if (typeof requestAnimationFrame === "undefined") return;
    const tick = (): void => {
      if (this.disposed || this.subscribers.size === 0) {
        this.rafHandle = 0;
        return;
      }
      const snap = this.snapshot();
      // Skip emit nếu state không đổi (cursor settled, no motion).
      // Compare via JSON shallow trên position + state — đủ chính xác.
      const sig = signatureOf(snap);
      if (sig !== this.lastSig) {
        this.lastSig = sig;
        for (const cb of this.subscribers) {
          try {
            cb(snap);
          } catch (err) {
            console.warn("[POINTY_AWARENESS] subscriber threw:", err);
          }
        }
      }
      this.rafHandle = requestAnimationFrame(tick);
    };
    this.rafHandle = requestAnimationFrame(tick);
  }

  private stopRaf(): void {
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    this.rafHandle = 0;
  }

  private lastSig: string = "";
}

interface InternalCursorEntry {
  identity: CursorIdentity;
  motion: {
    position: () => Vec2;
    velocity: () => Vec2;
    isSettled: () => boolean;
    currentStrategy: () => MotionStrategy;
  };
  state: AwarenessState;
  label: string;
  lastUpdateAt: number;
}

function signatureOf(snap: PointyAwarenessSnapshot): string {
  // Bốn chữ số sau vị trí integer pixel + state đủ phát hiện change.
  const parts: string[] = [];
  for (const c of snap.cursors) {
    parts.push(
      `${c.identity.id}|${Math.round(c.position.x)}|${Math.round(c.position.y)}|${c.awarenessState}|${c.motionStrategy}|${c.currentSelector ?? ""}`,
    );
  }
  return parts.join(",");
}
