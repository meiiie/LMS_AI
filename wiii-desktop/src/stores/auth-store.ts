/**
 * Auth store — manages authentication state.
 * Sprint 157: Google OAuth login, JWT tokens, user profile.
 * Sprint 176: Secure token storage + refresh mutex.
 *
 * Two auth modes:
 * 1. OAuth (Google login) — JWT tokens managed by this store
 * 2. Legacy (API key) — backward compat for development/LMS backends
 */
import { create } from "zustand";
import { loadStore, saveStore } from "@/lib/storage";
import {
  storeTokens,
  loadTokens,
  clearTokens,
} from "@/lib/secure-token-storage";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatar_url?: string;
  role: string;
  legacy_role?: string;
  platform_role?: "user" | "platform_admin";
  organization_role?: string;
  host_role?: string;
  role_source?: string;
  active_organization_id?: string;
  connector_id?: string;
  identity_version?: string;
}

interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_at: number; // Unix timestamp (ms)
}

interface AuthState {
  isAuthenticated: boolean;
  isLoaded: boolean; // Sprint 218: true after loadAuth() completes (prevents API race condition)
  user: AuthUser | null;
  tokens: AuthTokens | null;
  authMode: "oauth" | "legacy"; // oauth = Google login, legacy = API key

  // Actions
  loadAuth: () => Promise<void>;
  loginWithTokens: (
    accessToken: string,
    refreshToken: string,
    expiresIn: number,
    user: AuthUser,
  ) => Promise<void>;
  logout: () => Promise<void>;
  setLegacyMode: () => Promise<void>;
  refreshAccessToken: (serverUrl: string) => Promise<boolean>;

  // Helpers
  getAuthHeaders: () => Record<string, string>;
  isTokenExpiringSoon: () => boolean;
}

const AUTH_STORE_KEY = "auth_state";

// Sprint 176: Mutex for concurrent refresh prevention
let _refreshPromise: Promise<boolean> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  isAuthenticated: false,
  isLoaded: false,
  user: null,
  tokens: null,
  authMode: "legacy",

  loadAuth: async () => {
    try {
      // Sprint 176: Load tokens from dedicated secure store
      const secureTokens = await loadTokens();

      // Load user/authMode from regular store
      const saved = await loadStore<{
        user: AuthUser | null;
        authMode: "oauth" | "legacy";
        tokens?: AuthTokens | null; // Legacy field — migration source
      } | null>(AUTH_STORE_KEY, "data", null);

      // Sprint 176: Migration — if secure store is empty, check old location
      let tokens: AuthTokens | null = null;
      if (secureTokens) {
        tokens = secureTokens;
      } else if (saved?.tokens) {
        // Migrate tokens from old location to secure store
        tokens = saved.tokens;
        try {
          await storeTokens(
            tokens.access_token,
            tokens.refresh_token,
            tokens.expires_at,
          );
          // Clear tokens from old location
          await saveStore(AUTH_STORE_KEY, "data", {
            user: saved.user,
            authMode: saved.authMode,
          });
        } catch {
          // Migration failed — use old tokens anyway
        }
      }

      // Issue #108: Treat OAuth state as stale and self-heal when:
      //   1. Tokens are missing (logout / partial state / secure-store wiped), OR
      //   2. Tokens have expired by more than 30s (clock-skew tolerance) and no
      //      refresh has run.
      // Stale OAuth gets demoted to "legacy" so getAuthHeaders() takes the
      // X-API-Key path instead of sending a dead Bearer token.
      const STALE_TOKEN_GRACE_MS = 30_000;
      const isTokenExpired =
        !!tokens &&
        typeof tokens.expires_at === "number" &&
        tokens.expires_at + STALE_TOKEN_GRACE_MS < Date.now();
      const hasUsableOAuthTokens = !!tokens && !isTokenExpired;

      if (hasUsableOAuthTokens && saved?.user) {
        set({
          isAuthenticated: true,
          isLoaded: true,
          user: saved.user,
          tokens,
          authMode: saved.authMode || "oauth",
        });
      } else if (saved?.authMode === "legacy") {
        // Phase 31 fix: A persisted ``legacy`` authMode means the previous
        // session either chose api_key login OR was demoted from oauth
        // because tokens went stale. In the SECOND case the legacy
        // ``settings.api_key`` may be the dev placeholder ("local-dev-key")
        // or an empty string — neither will pass backend verification, and
        // the app would silently render an "authenticated" UI whose every
        // API call returns 401 "Invalid API key". Force a fresh credential
        // check by treating that case as ``isAuthenticated=false`` so the
        // login screen renders.
        let hasUsableLegacyKey = false;
        try {
          const { useSettingsStore } = await import(
            "@/stores/settings-store"
          );
          const apiKey = useSettingsStore.getState().settings.api_key || "";
          // The hardcoded "local-dev-key" placeholder is treated as "no
          // credential" — backend always rejects it because it never
          // matches the .env API_KEY config (≥16 chars in production).
          hasUsableLegacyKey =
            apiKey.length >= 16 && apiKey !== "local-dev-key";
        } catch {
          hasUsableLegacyKey = false;
        }
        set({
          authMode: "legacy",
          isAuthenticated: hasUsableLegacyKey,
          isLoaded: true,
        });
      } else if (saved?.authMode === "oauth") {
        // Saved oauth mode but tokens are missing/stale — demote to legacy
        // and persist the corrected mode so subsequent loads don't loop.
        set({
          isAuthenticated: false,
          isLoaded: true,
          user: null,
          tokens: null,
          authMode: "legacy",
        });
        try {
          await saveStore(AUTH_STORE_KEY, "data", {
            user: null,
            authMode: "legacy",
          });
        } catch {
          // Persistence failure is non-fatal; in-memory state is still corrected.
        }
      } else {
        // Sprint 218: Mark as loaded even if no saved auth found
        set({ isLoaded: true });
      }
    } catch (err) {
      console.warn("[Auth] Failed to load saved auth:", err);
      // Sprint 218: Mark as loaded even on error so app doesn't hang
      set({ isLoaded: true });
    }
  },

  loginWithTokens: async (accessToken, refreshToken, expiresIn, user) => {
    const tokens: AuthTokens = {
      access_token: accessToken,
      refresh_token: refreshToken,
      expires_at: Date.now() + expiresIn * 1000,
    };

    set({
      isAuthenticated: true,
      isLoaded: true,
      user,
      tokens,
      authMode: "oauth",
    });

    // Sprint 176: Store tokens in dedicated secure store
    try {
      await storeTokens(accessToken, refreshToken, tokens.expires_at);
    } catch (err) {
      console.warn("[Auth] Failed to save tokens:", err);
    }

    // Save user/authMode to regular store (no tokens)
    try {
      await saveStore(AUTH_STORE_KEY, "data", {
        user,
        authMode: "oauth",
      });
    } catch (err) {
      console.warn("[Auth] Failed to save auth:", err);
    }
  },

  logout: async () => {
    const { tokens, authMode } = get();
    let maintenance:
      | typeof import("@/stores/auth-store-maintenance")
      | null = null;

    try {
      maintenance = await import("@/stores/auth-store-maintenance");
    } catch {
      maintenance = null;
    }

    // Try to revoke on server (OAuth mode only — legacy has no Bearer token)
    if (tokens?.access_token) {
      try {
        await maintenance?.revokeServerSession(tokens.access_token);
      } catch {
        // Best effort — ignore server errors
      }
    }

    // Sprint 193: For legacy mode, clear API key from settings
    if (authMode === "legacy") {
      try {
        await maintenance?.clearLegacyApiKey();
      } catch {
        // ignore
      }
    }

    // Sprint 218: Clear ALL user-specific stores to prevent cross-user data leakage
    // Each store may contain PII (memories, conversations, emotions, journal, etc.)
    try {
      maintenance?.resetUserScopedStores();
    } catch { /* ignore */ }

    set({
      isAuthenticated: false,
      user: null,
      tokens: null,
      authMode: "oauth",
    });

    // Sprint 176: Clear both stores
    try {
      await clearTokens();
    } catch {
      // ignore
    }
    try {
      await saveStore(AUTH_STORE_KEY, "data", {
        user: null,
        authMode: "oauth",
      });
    } catch {
      // ignore
    }
  },

  setLegacyMode: async () => {
    set({ authMode: "legacy", isAuthenticated: true });
    try {
      await saveStore(AUTH_STORE_KEY, "data", {
        user: null,
        authMode: "legacy",
      });
    } catch (err) {
      console.warn("[Auth] Failed to save legacy mode:", err);
    }
  },

  refreshAccessToken: async (serverUrl: string) => {
    // Sprint 176: Mutex — if refresh already in-flight, reuse the promise
    if (_refreshPromise) {
      return _refreshPromise;
    }

    const doRefresh = async (): Promise<boolean> => {
      const { tokens, user } = get();
      if (!tokens?.refresh_token) return false;

      try {
        const resp = await fetch(`${serverUrl}/api/v1/auth/token/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: tokens.refresh_token }),
        });

        if (!resp.ok) {
          console.warn("[Auth] Refresh failed:", resp.status);
          await get().logout();
          return false;
        }

        const data = await resp.json();
        const newTokens: AuthTokens = {
          access_token: data.access_token,
          refresh_token: data.refresh_token,
          expires_at: Date.now() + data.expires_in * 1000,
        };

        set({ tokens: newTokens });

        // Sprint 176: Persist to secure store
        try {
          await storeTokens(
            newTokens.access_token,
            newTokens.refresh_token,
            newTokens.expires_at,
          );
        } catch {
          // ignore
        }
        try {
          await saveStore(AUTH_STORE_KEY, "data", {
            user,
            authMode: "oauth",
          });
        } catch {
          // ignore
        }

        return true;
      } catch (err) {
        console.warn("[Auth] Refresh error:", err);
        return false;
      }
    };

    _refreshPromise = doRefresh();
    try {
      return await _refreshPromise;
    } finally {
      _refreshPromise = null;
    }
  },

  getAuthHeaders: (): Record<string, string> => {
    const { tokens, authMode } = get();
    if (authMode === "oauth" && tokens?.access_token) {
      return { Authorization: `Bearer ${tokens.access_token}` };
    }
    return {};
  },

  isTokenExpiringSoon: () => {
    const { tokens } = get();
    if (!tokens) return false;
    // Expiring within 5 minutes
    return tokens.expires_at - Date.now() < 5 * 60 * 1000;
  },
}));

// Sprint 176: Export for testing
export function _getRefreshPromise(): Promise<boolean> | null {
  return _refreshPromise;
}
export function _resetRefreshPromise(): void {
  _refreshPromise = null;
}
