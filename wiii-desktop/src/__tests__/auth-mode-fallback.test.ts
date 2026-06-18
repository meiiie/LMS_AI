/**
 * Issue #108 — auth-store self-heals when OAuth state goes stale.
 *
 * Tests:
 *   1. loadAuth() keeps oauth+valid-tokens as oauth (no demotion)
 *   2. loadAuth() refreshes oauth+expired-tokens before showing login
 *   3. loadAuth() clears oauth+null-tokens without falling back to legacy
 *   4. getAuthHeaders() returns Authorization when tokens are fresh
 *   5. getAuthHeaders() does not send stale OAuth or legacy headers when tokens are expired
 *   6. getAuthHeaders() returns Authorization when token is within 30s grace window
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import { useSettingsStore } from "@/stores/settings-store";


// Reset stores + mocks before each test
beforeEach(() => {
  useAuthStore.setState({
    isAuthenticated: false,
    isLoaded: false,
    user: null,
    tokens: null,
    authMode: "legacy",
  });
  useSettingsStore.setState({
    settings: {
      ...useSettingsStore.getState().settings,
      api_key: "local-dev-key",
      user_id: "test-user",
      user_role: "student",
    },
    isLoaded: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});


describe("auth-store loadAuth — self-heal stale OAuth (Issue #108)", () => {
  it("keeps oauth mode when tokens are valid", async () => {
    const futureExpiry = Date.now() + 60_000; // 60s from now
    // Stub loadTokens + loadStore to return oauth state with fresh tokens
    vi.doMock("@/lib/secure-token-storage", () => ({
      loadTokens: async () => ({
        access_token: "valid-access",
        refresh_token: "refresh",
        expires_at: futureExpiry,
      }),
      storeTokens: async () => {},
      clearTokens: async () => {},
    }));
    vi.doMock("@/lib/storage", () => ({
      loadStore: async () => ({
        user: { id: "u1", email: "u@x.com", name: "U" },
        authMode: "oauth",
      }),
      saveStore: async () => {},
    }));
    vi.resetModules();
    const { useAuthStore: mod } = await import("@/stores/auth-store");
    await mod.getState().loadAuth();

    const s = mod.getState();
    expect(s.authMode).toBe("oauth");
    expect(s.tokens?.access_token).toBe("valid-access");
    expect(s.isAuthenticated).toBe(true);
  });

  it("refreshes oauth tokens on load when access token is expired", async () => {
    const pastExpiry = Date.now() - 60_000; // 60s ago
    const storeTokens = vi.fn();
    vi.doMock("@/lib/secure-token-storage", () => ({
      loadTokens: async () => ({
        access_token: "expired-access",
        refresh_token: "refresh",
        expires_at: pastExpiry,
      }),
      storeTokens,
      clearTokens: async () => {},
    }));
    vi.doMock("@/lib/storage", () => ({
      loadStore: async () => ({
        user: { id: "u1", email: "u@x.com", name: "U" },
        authMode: "oauth",
      }),
      saveStore: async () => {},
    }));
    vi.doMock("@/stores/settings-store", () => ({
      useSettingsStore: {
        getState: () => ({ settings: { server_url: "https://wiii.example" } }),
      },
    }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-access",
        refresh_token: "new-refresh",
        expires_in: 1800,
      }),
    }));
    vi.resetModules();
    const { useAuthStore: mod } = await import("@/stores/auth-store");
    await mod.getState().loadAuth();

    const s = mod.getState();
    expect(s.authMode).toBe("oauth");
    expect(s.tokens?.access_token).toBe("new-access");
    expect(s.tokens?.refresh_token).toBe("new-refresh");
    expect(s.isAuthenticated).toBe(true);
    expect(storeTokens).toHaveBeenCalledWith(
      "new-access",
      "new-refresh",
      expect.any(Number),
    );
  });

  it("shows oauth login when expired token refresh fails", async () => {
    const pastExpiry = Date.now() - 60_000;
    vi.doMock("@/lib/secure-token-storage", () => ({
      loadTokens: async () => ({
        access_token: "expired-access",
        refresh_token: "refresh",
        expires_at: pastExpiry,
      }),
      storeTokens: async () => {},
      clearTokens: async () => {},
    }));
    let savedPayload: any = null;
    vi.doMock("@/lib/storage", () => ({
      loadStore: async () => ({
        user: { id: "u1", email: "u@x.com", name: "U" },
        authMode: "oauth",
      }),
      saveStore: async (_k: string, _f: string, payload: any) => {
        savedPayload = payload;
      },
    }));
    vi.doMock("@/stores/settings-store", () => ({
      useSettingsStore: {
        getState: () => ({ settings: { server_url: "https://wiii.example" } }),
      },
    }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }));
    vi.resetModules();
    const { useAuthStore: mod } = await import("@/stores/auth-store");
    await mod.getState().loadAuth();

    const s = mod.getState();
    expect(s.authMode).toBe("oauth");
    expect(s.tokens).toBeNull();
    expect(s.isAuthenticated).toBe(false);
    expect(s.isLoaded).toBe(true);
    expect(savedPayload?.authMode).toBe("oauth");
  });

  it("clears oauth auth when no tokens are present", async () => {
    vi.doMock("@/lib/secure-token-storage", () => ({
      loadTokens: async () => null,
      storeTokens: async () => {},
      clearTokens: async () => {},
    }));
    let savedPayload: any = null;
    vi.doMock("@/lib/storage", () => ({
      loadStore: async () => ({
        user: { id: "u1", email: "u@x.com", name: "U" },
        authMode: "oauth",
        // Note: no `tokens` field either
      }),
      saveStore: async (_k: string, _f: string, payload: any) => {
        savedPayload = payload;
      },
    }));
    vi.resetModules();
    const { useAuthStore: mod } = await import("@/stores/auth-store");
    await mod.getState().loadAuth();

    const s = mod.getState();
    expect(s.authMode).toBe("oauth");
    expect(s.tokens).toBeNull();
    expect(savedPayload?.authMode).toBe("oauth");
  });
});


describe("settings-store getAuthHeaders — runtime stale-token defense (Issue #108)", () => {
  it("returns Authorization when oauth tokens are fresh", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      authMode: "oauth",
      tokens: {
        access_token: "fresh-jwt",
        refresh_token: "r",
        expires_at: Date.now() + 60_000, // 60s in future
      },
      user: null,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer fresh-jwt");
    expect(headers["X-API-Key"]).toBeUndefined();
  });

  it("does not send stale OAuth or legacy headers when oauth tokens are expired", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      authMode: "oauth",
      tokens: {
        access_token: "stale-jwt",
        refresh_token: "r",
        expires_at: Date.now() - 60_000, // 60s in past
      },
      user: null,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBeUndefined();
    expect(headers["X-API-Key"]).toBeUndefined();
    expect(headers["X-User-ID"]).toBeUndefined();
    expect(Object.keys(headers)).toHaveLength(0);
  });

  it("treats tokens within 30s of expiry as fresh (clock-skew tolerance)", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      authMode: "oauth",
      tokens: {
        access_token: "almost-expired",
        refresh_token: "r",
        expires_at: Date.now() - 10_000, // 10s past, within 30s grace
      },
      user: null,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer almost-expired");
  });
});
