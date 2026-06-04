import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  applyWiiiConnectFacebookPost,
  fetchWiiiConnectFacebookPages,
  fetchWiiiConnectProviderConnections,
  previewWiiiConnectFacebookPost,
} from "@/api/wiii-connect";
import { useHostContextStore } from "@/stores/host-context-store";

vi.mock("@/api/wiii-connect", () => ({
  applyWiiiConnectFacebookPost: vi.fn(),
  fetchWiiiConnectFacebookPages: vi.fn(),
  fetchWiiiConnectProviderConnections: vi.fn(),
  previewWiiiConnectFacebookPost: vi.fn(),
}));

describe("Host Context Store — Action Support (Sprint 222b)", () => {
  beforeEach(() => {
    useHostContextStore.getState().clear();
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("requestAction creates pending action and returns promise", async () => {
    vi.useRealTimers(); // Need real timers for this test
    const store = useHostContextStore.getState();
    const promise = store.requestAction("create_course", { name: "Test" });

    const pending = useHostContextStore.getState().pendingActions;
    expect(pending.size).toBe(1);

    const [reqId] = Array.from(pending.keys());
    expect(reqId).toMatch(/^req-/);

    store.resolveAction(reqId, { success: true, data: { id: 123 } });
    const result = await promise;
    expect(result.success).toBe(true);
    expect(result.data?.id).toBe(123);
  });

  it("requestAction times out after 30s", async () => {
    const store = useHostContextStore.getState();
    const promise = store.requestAction("slow_action", {});

    vi.advanceTimersByTime(30000);

    await expect(promise).rejects.toThrow(/timeout/i);
    expect(useHostContextStore.getState().pendingActions.size).toBe(0);
  });

  it("resolveAction for unknown ID does not throw", () => {
    const store = useHostContextStore.getState();
    expect(() => store.resolveAction("unknown-id", { success: false })).not.toThrow();
  });

  it("clear removes pending actions", () => {
    vi.useRealTimers();
    const store = useHostContextStore.getState();
    store.requestAction("test", {});
    expect(useHostContextStore.getState().pendingActions.size).toBe(1);
    store.clear();
    expect(useHostContextStore.getState().pendingActions.size).toBe(0);
  });

  it("multiple concurrent actions tracked independently", async () => {
    vi.useRealTimers();
    const store = useHostContextStore.getState();
    const p1 = store.requestAction("action_a", {});
    const p2 = store.requestAction("action_b", {});

    const pending = useHostContextStore.getState().pendingActions;
    expect(pending.size).toBe(2);

    const [id1, id2] = Array.from(pending.keys());
    store.resolveAction(id1, { success: true });
    store.resolveAction(id2, { success: true });

    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1.success).toBe(true);
    expect(r2.success).toBe(true);
  });

  it("requestAction preserves provided request id", async () => {
    vi.useRealTimers();
    const store = useHostContextStore.getState();
    const promise = store.requestAction("navigate", { url: "/lesson/1" }, "req-fixed-123");

    const pending = useHostContextStore.getState().pendingActions;
    expect(pending.has("req-fixed-123")).toBe(true);

    store.resolveAction("req-fixed-123", { success: true, data: { ok: true } });
    const result = await promise;
    expect(result.success).toBe(true);
    expect(result.data?.ok).toBe(true);
  });

  it("resolveAction stores semantic feedback for the next turn", async () => {
    vi.useRealTimers();
    const store = useHostContextStore.getState();
    const promise = store.requestAction(
      "authoring.preview_lesson_patch",
      { lesson_id: "lesson-1" },
      "req-preview-1",
    );

    store.resolveAction("req-preview-1", {
      success: true,
      data: {
        preview_token: "lesson-preview-123",
        summary: "Lesson patch preview ready.",
      },
    });

    await promise;

    const feedback = useHostContextStore.getState().getActionFeedbackForRequest();
    expect(feedback?.last_action_result?.action).toBe("authoring.preview_lesson_patch");
    expect(feedback?.last_action_result?.data?.preview_token).toBe("lesson-preview-123");
    expect(feedback?.recent_action_results?.length).toBe(1);
  });

  it("direct Facebook action previews then applies through Wiii Connect", async () => {
    vi.useRealTimers();
    vi.mocked(fetchWiiiConnectProviderConnections).mockResolvedValueOnce({
      version: "wiii_connect_connection_list.v1",
      provider_slug: "facebook",
      status: "ready",
      connection_count: 1,
      connections: [
        {
          provider_slug: "facebook",
          connection_ref: "conn-facebook-1",
          connection_id: "conn-facebook-1",
          state: "connected",
          active: true,
        },
      ],
    } as any);
    vi.mocked(fetchWiiiConnectFacebookPages).mockResolvedValueOnce({
      version: "wiii_connect_facebook_pages.v1",
      status: "ready",
      reason: "ready",
      provider_slug: "facebook",
      page_count: 1,
      pages: [{ page_id: "page-1", name: "Wiii" }],
    } as any);
    vi.mocked(previewWiiiConnectFacebookPost).mockResolvedValueOnce({
      version: "wiii_connect_facebook_post_preview.v1",
      status: "ready",
      reason: "ready",
      provider_slug: "facebook",
      preview_evidence_id: "fb-preview-1",
      approval_token: "fb-approval-1",
    });
    vi.mocked(applyWiiiConnectFacebookPost).mockResolvedValueOnce({
      version: "wiii_connect_facebook_post_apply.v1",
      status: "succeeded",
      reason: "succeeded",
      provider_slug: "facebook",
    });

    const result = await useHostContextStore.getState().requestAction(
      "wiii_connect.facebook_post.direct_apply",
      { provider_slug: "facebook", message: "Bài đăng thử từ Wiii." },
      "req-facebook-direct-1",
    );

    expect(result.success).toBe(true);
    expect(previewWiiiConnectFacebookPost).toHaveBeenCalledWith("facebook", {
      connection_ref: "conn-facebook-1",
      page_id: "page-1",
      message: "Bài đăng thử từ Wiii.",
    });
    expect(applyWiiiConnectFacebookPost).toHaveBeenCalledWith("facebook", {
      connection_ref: "conn-facebook-1",
      page_id: "page-1",
      message: "Bài đăng thử từ Wiii.",
      approval_token: "fb-approval-1",
      preview_evidence_id: "fb-preview-1",
    });
    expect(result.data?.summary).toBe("Đã đăng bài lên Facebook: Wiii.");
    expect(useHostContextStore.getState().lastActionResult?.action).toBe(
      "wiii_connect.facebook_post.direct_apply",
    );
  });

  it("direct Facebook action fails closed when post message is missing", async () => {
    vi.useRealTimers();
    vi.mocked(fetchWiiiConnectProviderConnections).mockResolvedValueOnce({
      version: "wiii_connect_connection_list.v1",
      provider_slug: "facebook",
      status: "ready",
      connection_count: 1,
      connections: [
        {
          provider_slug: "facebook",
          connection_ref: "conn-facebook-1",
          connection_id: "conn-facebook-1",
          state: "connected",
          active: true,
        },
      ],
    } as any);

    const result = await useHostContextStore.getState().requestAction(
      "wiii_connect.facebook_post.direct_apply",
      { provider_slug: "facebook" },
      "req-facebook-direct-missing-message",
    );

    expect(result.success).toBe(false);
    expect(result.error).toBe("facebook_post_message_missing");
    expect(fetchWiiiConnectFacebookPages).not.toHaveBeenCalled();
    expect(previewWiiiConnectFacebookPost).not.toHaveBeenCalled();
    expect(applyWiiiConnectFacebookPost).not.toHaveBeenCalled();
    expect(useHostContextStore.getState().lastActionResult?.summary).toContain(
      "facebook_post_message_missing",
    );
  });
});
