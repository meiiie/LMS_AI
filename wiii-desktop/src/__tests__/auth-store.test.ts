/**
 * Sprint 157 + 176: Auth store tests.
 * Tests OAuth login, logout, token refresh, legacy mode.
 * Sprint 176: Secure token storage, refresh mutex, migration.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore, _getRefreshPromise, _resetRefreshPromise } from "@/stores/auth-store";
import type { AuthUser } from "@/stores/auth-store";

// Mock storage
vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn().mockResolvedValue(null),
  saveStore: vi.fn().mockResolvedValue(undefined),
  deleteStore: vi.fn().mockResolvedValue(undefined),
}));

// Mock secure token storage
vi.mock("@/lib/secure-token-storage", () => ({
  storeTokens: vi.fn().mockResolvedValue(undefined),
  loadTokens: vi.fn().mockResolvedValue(null),
  clearTokens: vi.fn().mockResolvedValue(undefined),
}));

const MOCK_USER: AuthUser = {
  id: "user-123",
  email: "test@gmail.com",
  name: "Test User",
  avatar_url: "https://example.com/avatar.jpg",
  role: "student",
  platform_role: "user",
};

function resetStore() {
  useAuthStore.setState({
    isAuthenticated: false,
    isLoaded: false,
    user: null,
    tokens: null,
    authMode: "legacy",
  });
  _resetRefreshPromise();
}

describe("AuthStore", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it("has correct initial state", () => {
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(state.tokens).toBeNull();
    expect(state.authMode).toBe("legacy");
  });

  it("loginWithTokens sets authenticated state", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token-abc",
      "refresh-token-xyz",
      1800,
      MOCK_USER,
    );

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoaded).toBe(true);
    expect(state.user).toEqual(MOCK_USER);
    expect(state.tokens?.access_token).toBe("access-token-abc");
    expect(state.tokens?.refresh_token).toBe("refresh-token-xyz");
    expect(state.authMode).toBe("oauth");
  });

  it("loginWithTokens sets correct expires_at", async () => {
    const before = Date.now();
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800, // 30 minutes
      MOCK_USER,
    );
    const after = Date.now();

    const expiresAt = useAuthStore.getState().tokens!.expires_at;
    // expires_at should be ~30 minutes from now
    expect(expiresAt).toBeGreaterThanOrEqual(before + 1800 * 1000);
    expect(expiresAt).toBeLessThanOrEqual(after + 1800 * 1000);
  });

  it("logout clears auth state", async () => {
    // Login first
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800,
      MOCK_USER,
    );
    expect(useAuthStore.getState().isAuthenticated).toBe(true);

    // Logout
    await useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(state.tokens).toBeNull();
  });

  it("setLegacyMode enables legacy auth", async () => {
    await useAuthStore.getState().setLegacyMode();
    const state = useAuthStore.getState();
    expect(state.authMode).toBe("legacy");
    expect(state.isAuthenticated).toBe(true);
  });

  it("getAuthHeaders returns Bearer token in oauth mode", async () => {
    await useAuthStore.getState().loginWithTokens(
      "my-access-token",
      "refresh-token",
      1800,
      MOCK_USER,
    );

    const headers = useAuthStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer my-access-token");
  });

  it("getAuthHeaders returns empty in legacy mode", async () => {
    await useAuthStore.getState().setLegacyMode();
    const headers = useAuthStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("getAuthHeaders returns empty when not authenticated", () => {
    const headers = useAuthStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBeUndefined();
    expect(Object.keys(headers)).toHaveLength(0);
  });

  it("isTokenExpiringSoon returns false for fresh tokens", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800, // 30 minutes — well beyond 5-minute threshold
      MOCK_USER,
    );

    expect(useAuthStore.getState().isTokenExpiringSoon()).toBe(false);
  });

  it("isTokenExpiringSoon returns true for nearly-expired tokens", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      120, // 2 minutes — within 5-minute threshold
      MOCK_USER,
    );

    expect(useAuthStore.getState().isTokenExpiringSoon()).toBe(true);
  });

  it("isTokenExpiringSoon returns false when no tokens", () => {
    expect(useAuthStore.getState().isTokenExpiringSoon()).toBe(false);
  });

  it("loginWithTokens stores tokens in secure storage", async () => {
    const { storeTokens } = await import("@/lib/secure-token-storage");

    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800,
      MOCK_USER,
    );

    expect(storeTokens).toHaveBeenCalledWith(
      "access-token",
      "refresh-token",
      expect.any(Number),
    );
  });

  it("loginWithTokens saves user/authMode to regular store without tokens", async () => {
    const { saveStore } = await import("@/lib/storage");

    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800,
      MOCK_USER,
    );

    expect(saveStore).toHaveBeenCalledWith(
      "auth_state",
      "data",
      expect.objectContaining({
        user: MOCK_USER,
        authMode: "oauth",
      }),
    );

    // Verify no tokens in regular store
    const lastCall = (saveStore as any).mock.calls.find(
      (c: any[]) => c[0] === "auth_state",
    );
    expect(lastCall[2]).not.toHaveProperty("tokens");
  });

  it("preserves platform_role in oauth auth state", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800,
      {
        ...MOCK_USER,
        role: "admin",
        platform_role: "platform_admin",
      },
    );

    expect(useAuthStore.getState().user?.platform_role).toBe("platform_admin");
    expect(useAuthStore.getState().user?.role).toBe("admin");
  });

  it("refreshAccessToken calls server and updates tokens", async () => {
    // Setup: logged in with tokens
    await useAuthStore.getState().loginWithTokens(
      "old-access-token",
      "old-refresh-token",
      1800,
      MOCK_USER,
    );

    // Mock fetch for refresh endpoint
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-access-token",
        refresh_token: "new-refresh-token",
        expires_in: 1800,
      }),
    });
    globalThis.fetch = mockFetch;

    const result = await useAuthStore.getState().refreshAccessToken("http://localhost:8000");
    expect(result).toBe(true);
    expect(useAuthStore.getState().tokens?.access_token).toBe("new-access-token");
    expect(useAuthStore.getState().tokens?.refresh_token).toBe("new-refresh-token");
  });

  it("refreshAccessToken logs out on failure", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token",
      "refresh-token",
      1800,
      MOCK_USER,
    );

    const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    globalThis.fetch = mockFetch;

    const result = await useAuthStore.getState().refreshAccessToken("http://localhost:8000");
    expect(result).toBe(false);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  // Sprint 176: New tests

  it("refreshAccessToken stores new tokens in secure storage", async () => {
    const { storeTokens } = await import("@/lib/secure-token-storage");

    await useAuthStore.getState().loginWithTokens(
      "old-access",
      "old-refresh",
      1800,
      MOCK_USER,
    );
    vi.clearAllMocks();

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-access",
        refresh_token: "new-refresh",
        expires_in: 1800,
      }),
    });
    globalThis.fetch = mockFetch;

    await useAuthStore.getState().refreshAccessToken("http://localhost:8000");

    expect(storeTokens).toHaveBeenCalledWith(
      "new-access",
      "new-refresh",
      expect.any(Number),
    );
  });

  it("refresh mutex prevents concurrent refresh calls", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access",
      "refresh",
      1800,
      MOCK_USER,
    );

    let resolveFirst: (v: any) => void;
    const firstFetch = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    let fetchCallCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      fetchCallCount++;
      return firstFetch;
    });

    // Fire two concurrent refresh calls
    const p1 = useAuthStore.getState().refreshAccessToken("http://localhost:8000");
    const p2 = useAuthStore.getState().refreshAccessToken("http://localhost:8000");

    // Resolve the fetch
    resolveFirst!({
      ok: true,
      json: async () => ({
        access_token: "new",
        refresh_token: "new-r",
        expires_in: 1800,
      }),
    });

    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toBe(true);
    expect(r2).toBe(true);

    // Only ONE fetch call should have been made (mutex dedup)
    expect(fetchCallCount).toBe(1);
  });

  it("logout clears secure token storage", async () => {
    const { clearTokens } = await import("@/lib/secure-token-storage");

    await useAuthStore.getState().loginWithTokens(
      "access",
      "refresh",
      1800,
      MOCK_USER,
    );

    await useAuthStore.getState().logout();

    expect(clearTokens).toHaveBeenCalled();
  });

  it("loadAuth migrates tokens from old location", async () => {
    const { loadTokens, storeTokens } = await import("@/lib/secure-token-storage");
    const { loadStore } = await import("@/lib/storage");

    // Secure store empty
    (loadTokens as any).mockResolvedValue(null);

    // Old location has tokens
    (loadStore as any).mockResolvedValue({
      user: MOCK_USER,
      authMode: "oauth",
      tokens: {
        access_token: "old-access",
        refresh_token: "old-refresh",
        expires_at: Date.now() + 1800000,
      },
    });

    await useAuthStore.getState().loadAuth();

    // Should have migrated to secure store
    expect(storeTokens).toHaveBeenCalledWith(
      "old-access",
      "old-refresh",
      expect.any(Number),
    );

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.tokens?.access_token).toBe("old-access");
  });

  it("loadAuth prefers secure store over old location", async () => {
    const { loadTokens } = await import("@/lib/secure-token-storage");
    const { loadStore } = await import("@/lib/storage");

    // Secure store has tokens
    (loadTokens as any).mockResolvedValue({
      access_token: "secure-access",
      refresh_token: "secure-refresh",
      expires_at: Date.now() + 1800000,
    });

    // Old location also has tokens (should be ignored)
    (loadStore as any).mockResolvedValue({
      user: MOCK_USER,
      authMode: "oauth",
      tokens: {
        access_token: "old-access",
        refresh_token: "old-refresh",
        expires_at: Date.now() + 1800000,
      },
    });

    await useAuthStore.getState().loadAuth();

    const state = useAuthStore.getState();
    expect(state.tokens?.access_token).toBe("secure-access");
  });
});
