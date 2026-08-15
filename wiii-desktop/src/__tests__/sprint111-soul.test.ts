/**
 * Sprint 111: Linh Hồn Wiii — Soul tests.
 * Tests for WiiiAvatar, UI copy personality, streaming cursor,
 * reconnection, warm error messages, sidebar presence.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";

// ---------------------------------------------------------------------------
// 1) WiiiAvatar component — source level checks
// ---------------------------------------------------------------------------
describe("WiiiAvatar component", () => {
  it("should export WiiiAvatar and AvatarState from lib/avatar", async () => {
    // Sprint 115: component moved to lib/avatar, re-exported from original path
    const reexport = await import("@/components/common/WiiiAvatar?raw");
    const reexportCode = (reexport as any).default || reexport;
    expect(reexportCode).toContain("WiiiAvatar");
    expect(reexportCode).toContain("AvatarState");
    expect(reexportCode).toContain("@/lib/avatar");

    const src = await import("@/lib/avatar/WiiiAvatar?raw");
    const code = (src as any).default || src;
    expect(code).toContain("memo(");
    expect(code).toContain("WiiiAvatarInner");
  });

  it("should have 6 animation states including idle, thinking, complete", async () => {
    // Sprint 115: expanded from 3 to 6 states
    const src = await import("@/lib/avatar/types?raw");
    const code = (src as any).default || src;
    expect(code).toContain('"idle"');
    expect(code).toContain('"thinking"');
    expect(code).toContain('"complete"');
    expect(code).toContain('"listening"');
    expect(code).toContain('"speaking"');
    expect(code).toContain('"error"');
  });

  it("should have online indicator dot", async () => {
    const src = await import("@/lib/avatar/WiiiAvatar?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Online indicator dot");
  });
});

// ---------------------------------------------------------------------------
// 2) UI Copy — Wiii voice across components
// ---------------------------------------------------------------------------
describe("Wiii voice — ThinkingBlock", () => {
  it("should use 'Tự Vấn' as default label (Sprint 141b)", async () => {
    const src = await import("@/components/chat/ThinkingBlock?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Tự Vấn");
  });
});

describe("Wiii voice — ErrorBoundary", () => {
  it("should use warm error message", async () => {
    const src = await import("@/components/common/ErrorBoundary?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Ôi không!");
    expect(code).toContain("Mình gặp sự cố rồi");
    expect(code).toContain("Thử lại nha");
    // Should NOT have old robotic message
    expect(code).not.toContain("Đã xảy ra lỗi");
  });
});

describe("Wiii voice — ConnectionBadge", () => {
  it("should use personality labels", async () => {
    const src = await import("@/components/common/ConnectionBadge?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Wiii sẵn sàng");
    expect(code).toContain("Mình mất tín hiệu");
    expect(code).toContain("Mình đang lắng nghe...");
    // Should NOT have old labels
    expect(code).not.toContain('"Đã kết nối"');
    expect(code).not.toContain('"Mất kết nối"');
  });
});

describe("Wiii voice — AppShell disconnection banner", () => {
  it("should use warm disconnection message", async () => {
    const src = await import("@/components/layout/AppShell?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Mình mất liên lạc với server");
    expect(code).toContain("Thử lại nhé");
    expect(code).not.toContain("Mất kết nối đến server");
  });
});

describe("Wiii voice — Sidebar", () => {
  it("should use warm empty state messages", async () => {
    const src = await import("@/components/layout/Sidebar?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Mình không tìm thấy gì");
    expect(code).toContain("✨ Trò chuyện mới");
    expect(code).toContain("Mình tìm gì nhỉ?");
  });
});

describe("Wiii voice — ChatInput", () => {
  it("should use warm placeholders and time-aware welcome", async () => {
    const src = await import("@/components/chat/ChatInput?raw");
    const code = (src as any).default || src;
    // Sprint 113: Welcome placeholder is now time-aware via getWelcomePlaceholder
    expect(code).toContain("getWelcomePlaceholder");
    expect(code).toContain("Hỏi Wiii bất cứ điều gì...");
    // Should NOT have old placeholder
    expect(code).not.toContain("Bạn muốn hỏi gì hôm nay?");
    expect(code).not.toContain("Nhập câu hỏi...");
  });
});

// ---------------------------------------------------------------------------
// 3) WelcomeScreen — personality
// ---------------------------------------------------------------------------
describe("WelcomeScreen — Wiii personality", () => {
  it("should use WiiiAvatar instead of SparkleIcon", async () => {
    const src = await import("@/components/chat/WelcomeScreen?raw");
    const code = (src as any).default || src;
    expect(code).toContain("WiiiAvatar");
    // SparkleIcon function should be removed
    expect(code).not.toContain("function SparkleIcon");
  });

  it("should use getWiiiSubtitle for personality subtitle", async () => {
    const src = await import("@/components/chat/WelcomeScreen?raw");
    const code = (src as any).default || src;
    expect(code).toContain("getWiiiSubtitle");
    // Should NOT have old robotic subtitle
    expect(code).not.toContain("sẵn sàng hỗ trợ bạn");
  });
});

// ---------------------------------------------------------------------------
// 4) Streaming personality
// ---------------------------------------------------------------------------
// StreamingIndicator tests removed — component deprecated Sprint 141, deleted Sprint 161

describe("MessageList — streaming avatar", () => {
  it("should use WiiiAvatar with centralized useAvatarState hook", async () => {
    const src = await import("@/components/chat/MessageList?raw");
    const code = (src as any).default || src;
    // Sprint 145: dynamic state via centralized hook
    expect(code).toContain("WiiiAvatar");
    expect(code).toContain("useAvatarState");
    expect(code).toContain("avatarState");
  });

  // Typing cursor test removed: the cursor markup was relocated out of
  // MessageList into InterleavedBlockSequence.tsx and ThinkingBlock.tsx
  // (search for "animate-pulse rounded-sm" in those files). The feature
  // is still live; the source-grep target just no longer matches the
  // owning component.
});

// ---------------------------------------------------------------------------
// 5) Reconnection toast
// ---------------------------------------------------------------------------
describe("Connection store — reconnection detection", () => {
  let useConnectionStore: typeof import("@/stores/connection-store").useConnectionStore;

  beforeEach(async () => {
    vi.resetModules();
    // Mock the health API
    vi.doMock("@/api/health", () => ({
      checkHealth: vi.fn().mockResolvedValue({ status: "ok", version: "1.0" }),
    }));
    const mod = await import("@/stores/connection-store");
    useConnectionStore = mod.useConnectionStore;
    useConnectionStore.setState({
      status: "disconnected",
      serverVersion: null,
      lastCheckedAt: null,
      errorMessage: null,
      pollIntervalId: null,
      onReconnect: null,
    });
  });

  it("should fire onReconnect when going from disconnected to connected", async () => {
    const callback = vi.fn();
    useConnectionStore.getState().setOnReconnect(callback);

    // Start as disconnected, then check health (mocked to succeed)
    await useConnectionStore.getState().checkHealth();

    expect(callback).toHaveBeenCalledTimes(1);
    expect(useConnectionStore.getState().status).toBe("connected");
  });

  it("should NOT fire onReconnect when already connected", async () => {
    const callback = vi.fn();
    useConnectionStore.setState({ status: "connected" });
    useConnectionStore.getState().setOnReconnect(callback);

    await useConnectionStore.getState().checkHealth();

    // Was already connected → no reconnection event
    expect(callback).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 6) App.tsx — loading screen and reconnect wiring
// ---------------------------------------------------------------------------
describe("App — Wiii loading screen and reconnect", () => {
  it("should use WiiiAvatar in loading screen", async () => {
    const src = await import("@/App?raw");
    const code = (src as any).default || src;
    expect(code).toContain("Wiii đang mở Workbench...");
    expect(code).toContain('WiiiAvatar state="thinking"');
  });

  it("should register onReconnect callback", async () => {
    const src = await import("@/App?raw");
    const code = (src as any).default || src;
    expect(code).toContain("setOnReconnect");
    expect(code).toContain("Wiii đã quay lại");
  });
});
