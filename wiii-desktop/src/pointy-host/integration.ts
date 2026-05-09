/**
 * Pointy host — integration với HostContextStore (Wiii Pointy v2.4).
 *
 * Bridge module wire ``PageScanner`` + ``CursorAwareness`` vào
 * Zustand ``host-context-store`` (Sprint 222 infrastructure). Frontend
 * chỉ cần gọi ``mountPointyAwareness()`` ở đầu app lifecycle; sau đó
 * mọi chat request tự động bao gồm:
 *
 *   host_context.page.metadata.available_targets = PointyTarget[]
 *   host_context.page.metadata.cursor_state = CursorStateSnapshot
 *
 * Backend đã có `_inject_host_context` đọc store → inject vào agent
 * prompt. Backend tool ``tool_pointy_inventory`` đọc cùng metadata.
 *
 * Tham khảo: ``research-cursor-awareness-2026-05-06.md``
 */

import { useHostContextStore, type HostContext } from "@/stores/host-context-store";
import { CursorAwareness } from "./awareness";
import { PageScanner } from "./scanner";
import { UserCursorTracker } from "./user-cursor";
import { UserAttentionTracker } from "./user-attention";
import { getDefaultRegistry } from "./api";
import { WIII_IDENTITY } from "./identity";
import { computeDockPosition, subscribeDockPosition } from "./dock-position";
import { detectHostEnvironment } from "./host-detector";
import { clearPointyDomRefreshHook, setPointyDomRefreshHook } from "./dom-refresh";

let mounted = false;
let scanner: PageScanner | null = null;
let awareness: CursorAwareness | null = null;
let userCursor: UserCursorTracker | null = null;
let userAttention: UserAttentionTracker | null = null;
let unsubScanner: (() => void) | null = null;
let unsubAwareness: (() => void) | null = null;
let unsubUserCursor: (() => void) | null = null;
let unsubUserAttention: (() => void) | null = null;
let unsubDockResize: (() => void) | null = null;

export interface MountOptions {
  /** Throttle DOM rescan trên MutationObserver. Default 250ms. */
  scannerThrottleMs?: number;
  /** Max targets gửi lên backend (LLM prompt budget). Default 60. */
  maxTargets?: number;
}

/**
 * Mount awareness layer lên store. Idempotent — gọi nhiều lần chỉ
 * mount 1 lần. Trả về unmount function.
 */
export function mountPointyAwareness(options: MountOptions = {}): () => void {
  if (mounted) {
    return unmountPointyAwareness;
  }
  mounted = true;

  // 1. Mount scanner — quét DOM, observe mutations.
  scanner = new PageScanner({
    observe: true,
    throttleMs: options.scannerThrottleMs ?? 250,
    maxTargets: options.maxTargets ?? 60,
  });

  // 2. Mount awareness — track Wiii's overlay cursor state.
  const registry = getDefaultRegistry();
  awareness = new CursorAwareness(registry);
  setPointyDomRefreshHook(refreshPointyContext);

  // 2b. v3.0 Battleship: spawn Wiii cursor at dock position immediately.
  // Cursor is ALWAYS visible (breathing pulse via CSS keyframe targeting
  // [data-pointy-state="dock"]). When AI invokes pointy_show, cursor
  // flies out to target via min-jerk trajectory; when action completes,
  // returns to dock via auto-return setTimeout (see api.ts pointAt).
  // This eliminates the silent-fail UX problem where cursor was
  // invisible until first pointy_show, hiding hallucination errors.
  const dockPos = computeDockPosition();
  registry.upsert(WIII_IDENTITY, dockPos);
  registry.setState(WIII_IDENTITY.id, "dock");

  // 2d. F9 (2026-05-06) — expose manual test entrypoint on `window`.
  // Lets user verify cursor motion + selector resolution in DevTools
  // independently from any backend/SSE/parser pipeline. Usage in console:
  //   window.__wiiiPointTest__("chat-send-button")
  //   window.__wiiiPointTest__()  // probes inventory + dispatches first
  if (typeof window !== "undefined") {
    void import("./api").then((pointyApi) => {
      (window as unknown as { __wiiiPointTest__?: (sel?: string) => string }).__wiiiPointTest__ =
        (sel?: string) => {
          // v5.0 F10 (2026-05-06): force fresh scan + DOM-direct fallback.
          // Cached scanner targets become stale across React renders
          // (button disabled/enabled, ChatView mount/unmount).
          let targets = scanner?.scanNow() || [];
          if (targets.length === 0 && typeof document !== "undefined") {
            const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
            targets = Array.from(els)
              .map((el) => ({
                id: el.getAttribute("data-wiii-id") || "",
                selector: el.getAttribute("data-wiii-id") || "",
                label: el.getAttribute("aria-label") || el.textContent?.trim().slice(0, 40) || "",
                role: "button" as const,
                click_safe: false,
                visible: true,
                in_viewport_ratio: 1,
                bounds: { x: 0, y: 0, w: 0, h: 0 },
              }))
              .filter((t) => t.id);
          }
          const pickedSel = sel || targets[0]?.id || "";
          if (!pickedSel) {
            console.warn("[POINTY-TEST] no targets available");
            return "no targets";
          }
          const ok = pointyApi.pointAt(pickedSel, {
            caption: `manual test: ${pickedSel}`,
            duration_ms: 6000,
          });
          console.warn(`[POINTY-TEST] pointAt selector=${pickedSel} ok=${ok}`);
          console.warn(`[POINTY-TEST] available_targets count=${targets.length} ids=${targets.slice(0, 5).map((t) => t.id).join(",")}`);
          return `dispatched ${pickedSel} ok=${ok}`;
        };
      // v7.0 F12 — synthetic onDone using multi-match queue path.
      // Returns concatenated dispatch summary so E2E can assert all
      // targets were queued + first one fired ok=true.
      (window as unknown as {
        __wiiiEmbodiedTest__?: (text: string) => Promise<string>;
      }).__wiiiEmbodiedTest__ = async (text: string) => {
        const [tagMod, embodiedMod] = await Promise.all([
          import("./inline-tag-parser"),
          import("./embodied-parser"),
        ]);
        let targets = scanner?.scanNow() || [];
        if (targets.length === 0 && typeof document !== "undefined") {
          const els = document.querySelectorAll<HTMLElement>("[data-wiii-id]");
          targets = Array.from(els)
            .map((el) => ({
              id: el.getAttribute("data-wiii-id") || "",
              selector: el.getAttribute("data-wiii-id") || "",
              label: el.getAttribute("aria-label") || el.textContent?.trim().slice(0, 40) || "",
              role: "button" as const,
              click_safe: false,
              visible: true,
              in_viewport_ratio: 1,
              bounds: { x: 0, y: 0, w: 0, h: 0 },
            }))
            .filter((t) => t.id);
        }
        // Path 1: extract all tags.
        const tags = tagMod.parseAllPointTags(text).tags;
        if (tags.length > 0) {
          // Fire first immediately + queue rest. Test asserts on first.
          const first = tags[0];
          const ok = pointyApi.pointAt(first.selector, {
            caption: first.caption || undefined,
          });
          return `tag selector=${first.selector} count=${tags.length} ok=${ok}`;
        }
        // Path 2: multi-embodied.
        const matches = embodiedMod.detectAllEmbodiedPoints(text, targets);
        if (matches.length > 0) {
          const first = matches[0];
          const ok = pointyApi.pointAt(first.target.id, {
            caption: first.target.label || undefined,
          });
          // F13 debug: include first 3 matches in report so test failures
          // surface scoring information without re-running.
          const detail = matches
            .slice(0, 3)
            .map((m) => `${m.target.id}@${m.score.toFixed(2)}`)
            .join(",");
          const targetIds = targets
            .slice(0, 8)
            .map((t) => t.id)
            .join(",");
          return `embodied selector=${first.target.id} score=${first.score.toFixed(2)} count=${matches.length} ok=${ok} detail=[${detail}] targets=[${targetIds}]`;
        }
        return `no-match targets=${targets.length}`;
      };
      // F14 — expose production scanner inventory for E2E tests +
      // DevTools introspection. Returns the EXACT same target list
      // that embodied/tag dispatch sees.
      (window as unknown as {
        __wiiiInventory__?: () => Array<{ id: string; label?: string; role?: string }>;
      }).__wiiiInventory__ = () => {
        const targets = scanner?.scanNow() || [];
        return targets.map((t) => ({ id: t.id, label: t.label, role: t.role }));
      };
      console.warn("[POINTY-TEST] Ready. Run window.__wiiiPointTest__() in DevTools.");
    });
  }

  // 2c. Subscribe viewport resize → reposition dock cursor. Throttled
  // via rAF inside subscribeDockPosition — safe at 60Hz scrub.
  unsubDockResize = subscribeDockPosition((pos) => {
    // Only reposition if cursor is currently in dock/idle state — don't
    // teleport mid-flight. ``moving``/``returning`` states own their
    // own trajectory and would be jarringly disrupted.
    const snapshot = awareness?.cursorSnapshot(WIII_IDENTITY.id);
    const state = snapshot?.awarenessState;
    if (state === "dock" || state === "idle" || state === undefined) {
      registry.upsert(WIII_IDENTITY, pos);
      // Re-assert dock state in case upsert reset it.
      if (state === "dock" || state === undefined) {
        registry.setState(WIII_IDENTITY.id, "dock");
      }
    }
  });

  // 3. Mount user cursor tracker — track REAL OS mouse pointer.
  // v2.5: AI biết cả 2 cursors — Wiii's (overlay) và user's (real).
  userCursor = new UserCursorTracker({ throttleMs: 50 });

  // 4. Mount user attention tracker — track tab visibility, blur/focus,
  // idle. v2.6: AI biết user "đi đâu rồi" — switch tab, blur window.
  userAttention = new UserAttentionTracker();

  // 5. Subscribe → publish vào store.
  unsubScanner = scanner.subscribe(() => publishToStore());
  unsubAwareness = awareness.subscribe(() => publishToStore());
  unsubUserCursor = userCursor.subscribe(() => publishToStore());
  unsubUserAttention = userAttention.subscribe(() => publishToStore());

  // Initial publish (synchronous after subscribe sometimes misses).
  publishToStore();

  return unmountPointyAwareness;
}

/** Tear down awareness — gọi khi app unmount. */
export function unmountPointyAwareness(): void {
  if (!mounted) return;
  mounted = false;
  unsubScanner?.();
  unsubAwareness?.();
  unsubUserCursor?.();
  unsubUserAttention?.();
  unsubDockResize?.();
  unsubScanner = null;
  unsubAwareness = null;
  unsubUserCursor = null;
  unsubUserAttention = null;
  unsubDockResize = null;
  clearPointyDomRefreshHook(refreshPointyContext);
  scanner?.dispose();
  awareness?.dispose();
  userCursor?.dispose();
  userAttention?.dispose();
  scanner = null;
  awareness = null;
  userCursor = null;
  userAttention = null;
}

/** Force a one-shot scan + publish. Useful sau navigation. */
export function refreshPointyContext(): void {
  if (scanner) scanner.scanNow();
  publishToStore();
}

/** Publish cursor state + available_targets vào HostContextStore. */
function publishToStore(): void {
  if (!scanner || !awareness) return;

  const targets = scanner.getTargets();
  // Only include the Wiii cursor for now — peers (Soul Bridge) sẽ là
  // separate metadata key trong tương lai.
  const wiiiCursor = awareness.cursorSnapshot(WIII_IDENTITY.id);
  // User's real OS cursor — separate from Wiii overlay cursor. v2.5.
  const userCursorState = userCursor?.snapshot() ?? null;
  // User's attention/presence (tab visibility, focus, idle). v2.6.
  const attentionState = userAttention?.snapshot() ?? null;

  const store = useHostContextStore.getState();
  const current: HostContext | null = store.currentContext;

  // v3.0 F1 — detect actual runtime environment dynamically. KHÔNG
  // hardcode "wiii-desktop" because Wiii có thể chạy ở 3 surfaces:
  //   - localhost:1420 (dev) → host_type "wiii-desktop"
  //   - wiii.holilihu.online (prod web) → host_type "wiii-web"
  //   - LMS iframe embed → host_type "lms"
  // The detector uses iframe parent check + hostname rules. Backend
  // `_inject_host_context` reads `host_type` and writes a system-prompt
  // line so AI knows the surface and KHÔNG hallucinate "trang LMS".
  // Existing LMS-pushed context (Sprint 222) overrides this when LMS
  // sends its own host-context PostMessage.
  const env = detectHostEnvironment();
  const baseContext: HostContext = current ?? {
    host_type: env.host_type,
    host_name: env.host_name,
    page: {
      type: env.page_type,
      title: env.page_title,
      url: env.page_url,
      metadata: {
        // Surface raw env signals so backend can build accurate prompt.
        is_standalone: env.is_standalone,
        is_embedded: env.is_embedded,
        hostname: env.hostname,
      },
    },
  };

  const existingMetadata = baseContext.page.metadata ?? {};
  const newMetadata: Record<string, unknown> = {
    ...existingMetadata,
    available_targets: targets.map((t) => ({
      id: t.id,
      selector: t.selector,
      label: t.label,
      role: t.role,
      click_safe: t.click_safe,
      click_kind: t.click_kind,
      visible: t.visible,
      // Bounds intentionally omitted from store → less noise in
      // backend prompt. Caller có thể compute lại nếu cần.
    })),
    cursor_state: wiiiCursor
      ? {
          identity_id: wiiiCursor.identity.id,
          identity_name: wiiiCursor.identity.name,
          position: {
            x: Math.round(wiiiCursor.position.x),
            y: Math.round(wiiiCursor.position.y),
          },
          isMoving: wiiiCursor.isMoving,
          awarenessState: wiiiCursor.awarenessState,
          motionStrategy: wiiiCursor.motionStrategy,
          currentSelector: wiiiCursor.currentSelector,
          currentCaption: wiiiCursor.currentCaption,
        }
      : null,
    // Wiii Pointy v2.5 — user's real OS cursor. AI có thể tham khảo
    // user đang nhìn đâu, hover gì, vừa click chưa.
    user_cursor_state: userCursorState
      ? {
          position: userCursorState.position,
          hovered_id: userCursorState.hoveredId,
          hovered_label: userCursorState.hoveredLabel,
          idle_ms: userCursorState.idleMs,
          recently_clicked: userCursorState.recentlyClicked,
        }
      : null,
    // Wiii Pointy v2.6 — user attention (tab visibility, focus, idle).
    // v2.7 thêm behavior counters (copy/paste/right-click) + last
    // selected text. AI có thể detect copy-then-question pattern.
    user_attention: attentionState
      ? {
          status: attentionState.status,
          is_visible: attentionState.isVisible,
          is_focused: attentionState.isFocused,
          blur_count: attentionState.blurCount,
          tab_switch_count: attentionState.hideCount,
          total_away_ms: Math.round(attentionState.totalAwayMs),
          last_away_duration_ms: Math.round(attentionState.lastAwayDurationMs),
          // v2.7 behavior fields
          copy_count: attentionState.copyCount,
          paste_count: attentionState.pasteCount,
          context_menu_count: attentionState.contextMenuCount,
          last_selected_text: attentionState.lastSelectedText,
          recent_events: attentionState.recentEvents.slice(-5).map((e) => ({
            type: e.type,
            duration_from_previous_ms: Math.round(e.durationFromPreviousMs),
          })),
        }
      : null,
  };

  store.updateContext({
    ...baseContext,
    page: {
      ...baseContext.page,
      metadata: newMetadata,
    },
  });
}

/**
 * Notify awareness module rằng cursor đã được điểm vào selector mới.
 * Caller (api.ts pointAt) gọi để awareness reflect activity, không
 * thông qua DOM scan riêng.
 */
export function recordPointyActivity(
  cursorId: string,
  activity: { selector?: string | null; caption?: string | null },
): void {
  if (!awareness) return;
  awareness.recordActivity(cursorId, activity);
}

/** Direct accessors cho debugging / advanced use cases. */
export function getPointyAwareness(): CursorAwareness | null {
  return awareness;
}

export function getPointyScanner(): PageScanner | null {
  return scanner;
}
