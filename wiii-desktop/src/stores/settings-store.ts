/**
 * Settings store — persisted via tauri-plugin-store.
 * Manages server URL, API key, user info, theme, etc.
 *
 * Sprint 194b: Security hardening
 * - Removed hardcoded DEFAULT_USER_ID — anonymous UUID generated at runtime
 * - facebook_cookie moved to secure-token-storage (PII protection)
 * - getAuthHeaders() no longer sends X-User-ID/X-Role in OAuth mode
 * - Legacy mode role restricted to student/teacher (no admin escalation)
 */
import { create } from "zustand";
import type { AppSettings } from "@/api/types";
import {
  DEFAULT_SERVER_URL,
  DEFAULT_USER_ROLE,
  DEFAULT_DISPLAY_NAME,
  DEFAULT_DOMAIN,
  DEFAULT_LANGUAGE,
  DEFAULT_STREAMING_VERSION,
} from "@/lib/constants";
import {
  GOOGLE_DEFAULT_MODEL,
  OPENAI_DEFAULT_MODEL,
  OPENAI_DEFAULT_MODEL_ADVANCED,
  OLLAMA_DEFAULT_BASE_URL,
  OLLAMA_DEFAULT_KEEP_ALIVE,
  OLLAMA_DEFAULT_MODEL,
  ZHIPU_DEFAULT_BASE_URL,
  ZHIPU_DEFAULT_MODEL,
  ZHIPU_DEFAULT_MODEL_ADVANCED,
} from "@/lib/llm-presets";
// Sprint 218: Static import replaces require() — fixes Vite ESM browser mode
// No circular dependency: auth-store does NOT import settings-store at module level
import { useAuthStore } from "@/stores/auth-store";

/**
 * Generate a unique anonymous user ID.
 * Uses crypto.randomUUID when available (modern browsers + Node 19+),
 * falls back to a simple UUID v4 implementation.
 */
function generateAnonymousId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `anon-${crypto.randomUUID()}`;
  }
  // Fallback for older environments
  return `anon-${"xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  })}`;
}

function hasTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function isLocalPreviewHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function migrateLocalPreviewServerUrl(
  serverUrl: string | undefined,
  hostname: string,
): string | undefined {
  if (!isLocalPreviewHost(hostname) || !serverUrl) return serverUrl;
  const localPreviewDefault = DEFAULT_SERVER_URL || "http://localhost:8080";
  if (
    serverUrl === "http://localhost:8001" ||
    serverUrl === "http://127.0.0.1:8001" ||
    serverUrl === "http://localhost:8080" ||
    serverUrl === "http://127.0.0.1:8080"
  ) {
    return localPreviewDefault;
  }
  return serverUrl;
}

export function normalizeLoadedSettingsForHost(
  saved: Partial<AppSettings> | null,
  hostname: string,
): AppSettings {
  const merged = { ...DEFAULT_SETTINGS, ...(saved || {}) };

  if (!merged.user_id || merged.user_id === "desktop-user") {
    merged.user_id = generateAnonymousId();
  }

  merged.server_url = migrateLocalPreviewServerUrl(merged.server_url, hostname) || merged.server_url;

  // Preview builds running on localhost should still talk to the local backend.
  if (isLocalPreviewHost(hostname) && !merged.server_url) {
    merged.server_url = DEFAULT_SERVER_URL || "http://localhost:8080";
  }

  return merged;
}

function normalizeLoadedSettings(saved: Partial<AppSettings> | null): AppSettings {
  const hostname = typeof window !== "undefined" ? window.location.hostname : "";
  return normalizeLoadedSettingsForHost(saved, hostname);
}

const DEFAULT_SETTINGS: AppSettings = {
  server_url: DEFAULT_SERVER_URL,
  api_key: "",
  llm_provider: "google",
  google_model: GOOGLE_DEFAULT_MODEL,
  openai_base_url: "",
  openai_model: OPENAI_DEFAULT_MODEL,
  openai_model_advanced: OPENAI_DEFAULT_MODEL_ADVANCED,
  zhipu_base_url: ZHIPU_DEFAULT_BASE_URL,
  zhipu_model: ZHIPU_DEFAULT_MODEL,
  zhipu_model_advanced: ZHIPU_DEFAULT_MODEL_ADVANCED,
  ollama_base_url: OLLAMA_DEFAULT_BASE_URL,
  ollama_model: OLLAMA_DEFAULT_MODEL,
  ollama_keep_alive: OLLAMA_DEFAULT_KEEP_ALIVE,
  llm_failover_enabled: true,
  llm_failover_chain: ["google", "zhipu", "ollama", "openrouter"],
  user_id: "",  // Sprint 194b: empty — generated on first load, never hardcoded
  user_role: DEFAULT_USER_ROLE,
  display_name: DEFAULT_DISPLAY_NAME,
  default_domain: DEFAULT_DOMAIN,
  theme: "system",
  language: DEFAULT_LANGUAGE,
  show_thinking: true,
  show_reasoning_trace: false,
  streaming_version: DEFAULT_STREAMING_VERSION,
  thinking_level: "balanced",
  pointy_voice_enabled: false,
  // Sprint 194b: facebook_cookie removed — moved to secure-token-storage (H5)
  show_previews: true,  // Sprint 166: Rich preview cards
  show_artifacts: true, // Sprint 167: Interactive artifacts
};

interface SettingsState {
  settings: AppSettings;
  isLoaded: boolean;

  // Actions
  loadSettings: () => Promise<void>;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
  getAuthHeaders: () => Record<string, string>;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: DEFAULT_SETTINGS,
  isLoaded: false,

  loadSettings: async () => {
    if (!hasTauriRuntime()) {
      try {
        const raw = localStorage.getItem("wiii:app_settings");
        if (raw) {
          const saved = JSON.parse(raw) as Partial<AppSettings>;
          const merged = normalizeLoadedSettings(saved);
          localStorage.setItem("wiii:app_settings", JSON.stringify(merged));
          set({ settings: merged, isLoaded: true });
          return;
        }
      } catch { /* ignore */ }

      set({
        settings: normalizeLoadedSettings({ user_id: generateAnonymousId() }),
        isLoaded: true,
      });
      return;
    }

    try {
      const { Store } = await import("@tauri-apps/plugin-store");
      const store = await Store.load("settings.json");
      const saved = await store.get<AppSettings>("app_settings");

      if (saved) {
        const merged = normalizeLoadedSettings(saved);
        // Persist immediately so migrations stay stable across sessions
        await store.set("app_settings", merged);
        await store.save();

        set({
          settings: merged,
          isLoaded: true,
        });
      } else {
        // First launch — generate anonymous ID
        const fresh = normalizeLoadedSettings({ user_id: generateAnonymousId() });
        set({ settings: fresh, isLoaded: true });
        // Persist so user_id is stable
        await store.set("app_settings", fresh);
        await store.save();
      }
    } catch (err) {
      console.warn("[Settings] Failed to load, using defaults:", err);
      // Final fallback: generate anonymous ID in memory
      set({
        settings: normalizeLoadedSettings({ user_id: generateAnonymousId() }),
        isLoaded: true,
      });
    }
  },

  updateSettings: async (partial) => {
    const newSettings = { ...get().settings, ...partial };
    set({ settings: newSettings });

    if (!hasTauriRuntime()) {
      try {
        localStorage.setItem("wiii:app_settings", JSON.stringify(newSettings));
      } catch { /* ignore */ }
      return;
    }

    try {
      const { Store } = await import("@tauri-apps/plugin-store");
      const store = await Store.load("settings.json");
      await store.set("app_settings", newSettings);
      await store.save();
    } catch (err) {
      console.warn("[Settings] Failed to save:", err);
      // Browser fallback: save to localStorage
      try {
        localStorage.setItem("wiii:app_settings", JSON.stringify(newSettings));
      } catch { /* ignore */ }
    }
  },

  resetSettings: async () => {
    // Sprint 194b: Generate fresh anonymous ID on reset
    const resetWith = { ...DEFAULT_SETTINGS, user_id: generateAnonymousId() };
    set({ settings: resetWith });

    if (!hasTauriRuntime()) {
      try {
        localStorage.setItem("wiii:app_settings", JSON.stringify(resetWith));
      } catch { /* ignore */ }
      return;
    }

    try {
      const { Store } = await import("@tauri-apps/plugin-store");
      const store = await Store.load("settings.json");
      await store.set("app_settings", resetWith);
      await store.save();
    } catch (err) {
      console.warn("[Settings] Failed to reset:", err);
    }
  },

  getAuthHeaders: () => {
    const { settings } = get();
    const headers: Record<string, string> = {};

    // Sprint 157: Try OAuth JWT first, fallback to API key
    // Sprint 218: Uses static import (require() fails in Vite ESM browser mode)
    // Issue #108: Defensive runtime check — if oauth mode but the token has
    // already expired, fall through to the legacy api_key path for THIS
    // request (don't mutate the store; that's loadAuth's job at startup).
    // Without this, every request between token expiry and the next loadAuth
    // would silently send a dead Bearer.
    const STALE_TOKEN_GRACE_MS = 30_000;
    const authState = useAuthStore.getState();
    const hasFreshOAuthToken =
      authState.authMode === "oauth" &&
      !!authState.tokens?.access_token &&
      typeof authState.tokens?.expires_at === "number" &&
      authState.tokens.expires_at + STALE_TOKEN_GRACE_MS >= Date.now();
    if (hasFreshOAuthToken) {
      // Sprint 194b (H1): OAuth mode — identity from JWT only
      // DO NOT send X-User-ID or X-Role — backend extracts from token
      headers["Authorization"] = `Bearer ${authState.tokens!.access_token}`;
      // Sprint 156: Include org ID when not personal workspace
      if (settings.organization_id && settings.organization_id !== "personal") {
        headers["X-Organization-ID"] = settings.organization_id;
      }
      return headers;
    }

    // Legacy API key mode
    // Sprint 192: API key from settings (secure store loaded at init)
    if (settings.api_key) headers["X-API-Key"] = settings.api_key;
    headers["X-User-ID"] = settings.user_id;
    // Sprint 194b (C4): Legacy mode — restrict role escalation.
    // In production, backend enforces its own check (enforce_api_key_role_restriction).
    // Dev mode allows admin for testing convenience.
    const safeRole = ["student", "teacher", "admin"].includes(settings.user_role)
      ? settings.user_role
      : "student";
    headers["X-Role"] = safeRole;
    // Sprint 156: Include org ID when not personal workspace
    if (settings.organization_id && settings.organization_id !== "personal") {
      headers["X-Organization-ID"] = settings.organization_id;
    }
    return headers;
  },
}));

// Sprint 194b: Export for testing
export { generateAnonymousId };
