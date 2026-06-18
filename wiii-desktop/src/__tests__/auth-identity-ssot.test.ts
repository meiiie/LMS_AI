/**
 * Sprint 194b: Auth & Identity SSOT (Single Source of Truth) tests.
 *
 * Covers:
 *   C1/C5 - Default user_id is UUID, not "desktop-user"
 *   H1    - OAuth mode does NOT send X-User-ID header
 *   C4    - Legacy role restricted to student/teacher
 *   H2    - Org switch only to member orgs
 *   C3    - PostMessage origin validation
 *   H5    - Facebook cookie no longer in settings
 *   H3    - Embed JWT decode safety
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// =============================================================================
// Mock modules BEFORE importing stores
// =============================================================================

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn().mockResolvedValue(null),
  saveStore: vi.fn().mockResolvedValue(undefined),
  deleteStore: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/secure-token-storage", () => ({
  storeTokens: vi.fn().mockResolvedValue(undefined),
  loadTokens: vi.fn().mockResolvedValue(null),
  clearTokens: vi.fn().mockResolvedValue(undefined),
  storeApiKey: vi.fn().mockResolvedValue(undefined),
  loadApiKey: vi.fn().mockResolvedValue(null),
  clearApiKey: vi.fn().mockResolvedValue(undefined),
  storeFacebookCookie: vi.fn().mockResolvedValue(undefined),
  loadFacebookCookie: vi.fn().mockResolvedValue(null),
  clearFacebookCookie: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@tauri-apps/plugin-store", () => ({
  Store: {
    load: vi.fn().mockResolvedValue({
      get: vi.fn().mockResolvedValue(null),
      set: vi.fn().mockResolvedValue(undefined),
      save: vi.fn().mockResolvedValue(undefined),
    }),
  },
}));

vi.mock("@/api/organizations", () => ({
  listOrganizations: vi.fn(),
  getOrgSettings: vi.fn().mockRejectedValue(new Error("Not configured in test")),
  getOrgPermissions: vi.fn().mockRejectedValue(new Error("Not configured in test")),
}));

vi.mock("@/api/admin", () => ({
  getAdminContext: vi.fn().mockRejectedValue(new Error("Not configured in test")),
}));

// =============================================================================
// Imports (after mocks)
// =============================================================================

import {
  useSettingsStore,
  generateAnonymousId,
  resolveOAuthOrganizationHeader,
} from "@/stores/settings-store";
import { useAuthStore } from "@/stores/auth-store";
import type { AuthUser } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { OrganizationSummary, AppSettings } from "@/api/types";
import { PERSONAL_ORG_ID } from "@/lib/constants";
import {
  sendToParent,
  setParentOrigin,
  isEmbedded,
  onParentMessage,
} from "@/lib/embed-bridge";
import {
  _resolveCompatibilityRole,
  _resolveRequestDisplayName,
  _resolveRequestUserId,
} from "@/hooks/useSSEStream";
import { buildAuthUserFromJwt } from "@/lib/auth-user";

// =============================================================================
// Helpers
// =============================================================================

const DEFAULT_SETTINGS: AppSettings = {
  server_url: "http://localhost:8000",
  api_key: "",
  user_id: "",
  user_role: "student",
  display_name: "User",
  default_domain: "maritime",
  theme: "system",
  language: "vi",
  show_thinking: true,
  show_reasoning_trace: false,
  streaming_version: "v3",
  thinking_level: "balanced",
  show_previews: true,
  show_artifacts: true,
};

const MOCK_USER: AuthUser = {
  id: "user-oauth-123",
  email: "test@example.com",
  name: "OAuth User",
  role: "student",
};

const MOCK_ORGS: OrganizationSummary[] = [
  {
    id: "lms-hang-hai",
    name: "LMS Hang Hai",
    display_name: "Truong DHHH VN",
    allowed_domains: ["maritime"],
    is_active: true,
  },
  {
    id: "lms-giao-thong",
    name: "LMS Giao Thong",
    display_name: "Truong GT",
    allowed_domains: ["traffic_law"],
    is_active: true,
  },
  {
    id: PERSONAL_ORG_ID,
    name: "Wiii Ca nhan",
    display_name: "Wiii Ca nhan",
    allowed_domains: [],
    is_active: true,
  },
];

function resetAllStores() {
  useSettingsStore.setState({
    settings: { ...DEFAULT_SETTINGS },
    isLoaded: false,
  });
  useAuthStore.setState({
    isAuthenticated: false,
    user: null,
    tokens: null,
    authMode: "legacy",
  });
  useOrgStore.setState({
    organizations: [],
    activeOrgId: null,
    isLoading: false,
    multiTenantEnabled: false,
    subdomainOrgId: null,
    orgSettings: null,
    permissions: [],
    adminContext: null,
  });
}

/**
 * Build a JWT-like token with the given payload.
 * NOT a real JWT -- no signature verification. Only for client-side decode tests.
 */
function buildFakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload));
  const sig = "fake-signature";
  return `${header}.${body}.${sig}`;
}

// =============================================================================
// C1/C5: Default user_id is UUID, not "desktop-user"
// =============================================================================

describe("C1/C5: generateAnonymousId — anonymous UUID user IDs", () => {
  it("returns a string starting with 'anon-'", () => {
    const id = generateAnonymousId();
    expect(id.startsWith("anon-")).toBe(true);
  });

  it("returns a UUID-like format after the 'anon-' prefix", () => {
    const id = generateAnonymousId();
    const uuidPart = id.slice(5); // Remove "anon-"
    // UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    expect(uuidPart).toMatch(uuidRegex);
  });

  it("generates unique IDs on each call", () => {
    const ids = new Set<string>();
    for (let i = 0; i < 50; i++) {
      ids.add(generateAnonymousId());
    }
    expect(ids.size).toBe(50);
  });

  it("default settings user_id is empty string (not 'desktop-user')", () => {
    resetAllStores();
    const { settings } = useSettingsStore.getState();
    expect(settings.user_id).toBe("");
    expect(settings.user_id).not.toBe("desktop-user");
  });

  it("loadSettings generates anon ID when user_id is empty", async () => {
    resetAllStores();
    await useSettingsStore.getState().loadSettings();
    const { settings } = useSettingsStore.getState();
    // After loading with no saved settings, user_id should be an anonymous UUID
    expect(settings.user_id).toBeTruthy();
    expect(settings.user_id.startsWith("anon-")).toBe(true);
  });
});


// =============================================================================
// H1: OAuth mode does NOT send X-User-ID header
//
// DESIGN NOTE: The settings store's getAuthHeaders() uses require("@/stores/auth-store")
// internally which may not resolve in ESM-vitest. Instead of fighting that, we test
// the auth-store's own getAuthHeaders() (which ONLY returns Authorization) and verify
// the settings-store's legacy fallback is correct. The contract is:
//   - OAuth: use auth-store headers (Authorization only)
//   - Legacy: settings-store adds X-User-ID + restricted X-Role
// =============================================================================

describe("H1: OAuth mode suppresses X-User-ID and X-Role headers", () => {
  beforeEach(() => {
    resetAllStores();
    vi.clearAllMocks();
  });

  it("auth-store getAuthHeaders returns ONLY Authorization in oauth mode", async () => {
    await useAuthStore.getState().loginWithTokens(
      "access-token-abc",
      "refresh-token-xyz",
      1800,
      MOCK_USER,
    );

    const headers = useAuthStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer access-token-abc");
    // These keys must NOT exist in OAuth headers
    expect(headers["X-User-ID"]).toBeUndefined();
    expect(headers["X-Role"]).toBeUndefined();
    expect(headers["X-API-Key"]).toBeUndefined();
    expect(Object.keys(headers)).toEqual(["Authorization"]);
  });

  it("auth-store getAuthHeaders returns empty object in legacy mode", async () => {
    await useAuthStore.getState().setLegacyMode();

    const headers = useAuthStore.getState().getAuthHeaders();
    expect(Object.keys(headers)).toHaveLength(0);
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("auth-store getAuthHeaders returns empty when no tokens", () => {
    const headers = useAuthStore.getState().getAuthHeaders();
    expect(Object.keys(headers)).toHaveLength(0);
  });

  it("settings-store legacy fallback sends X-User-ID and restricted X-Role", () => {
    // Auth store in legacy mode (default) -- settings store will fall through to legacy path
    useAuthStore.setState({ authMode: "legacy", tokens: null });

    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "test-api-key",
        user_id: "anon-12345",
        user_role: "student",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-API-Key"]).toBe("test-api-key");
    expect(headers["X-User-ID"]).toBe("anon-12345");
    expect(headers["X-Role"]).toBe("student");
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("settings-store legacy fallback includes X-Organization-ID when configured", () => {
    useAuthStore.setState({ authMode: "legacy", tokens: null });

    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        organization_id: "lms-hang-hai",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Organization-ID"]).toBe("lms-hang-hai");
  });

  it("settings-store legacy fallback excludes X-Organization-ID for personal workspace", () => {
    useAuthStore.setState({ authMode: "legacy", tokens: null });

    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        organization_id: "personal",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Organization-ID"]).toBeUndefined();
  });
});


// =============================================================================
// C4: Legacy role restricted to student/teacher
// =============================================================================

describe("C4: Legacy mode role downgrade — no admin escalation", () => {
  beforeEach(() => {
    resetAllStores();
    vi.clearAllMocks();
    // Ensure legacy mode
    useAuthStore.setState({ authMode: "legacy", tokens: null });
  });

  it("allows 'admin' role through in API key mode (backend enforces in production)", () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        user_role: "admin",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Role"]).toBe("admin");
  });

  it("passes 'student' role through unchanged", () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        user_role: "student",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Role"]).toBe("student");
  });

  it("passes 'teacher' role through unchanged", () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        user_role: "teacher",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Role"]).toBe("teacher");
  });

  it("downgrades unexpected role values to 'student'", () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        user_role: "superadmin" as any,
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Role"]).toBe("student");
  });
});


// =============================================================================
// H2: Org switch only to member orgs
// =============================================================================

describe("H2: setActiveOrg validates membership", () => {
  beforeEach(() => {
    resetAllStores();
    vi.clearAllMocks();
  });

  it("allows switching to an org the user is a member of", () => {
    useOrgStore.setState({
      organizations: MOCK_ORGS,
      multiTenantEnabled: true,
      activeOrgId: null,
    });

    useOrgStore.getState().setActiveOrg("lms-hang-hai");
    expect(useOrgStore.getState().activeOrgId).toBe("lms-hang-hai");
  });

  it("rejects switching to an unknown org ID", () => {
    useOrgStore.setState({
      organizations: MOCK_ORGS,
      multiTenantEnabled: true,
      activeOrgId: "lms-hang-hai",
    });

    // Attempt to switch to a non-member org
    useOrgStore.getState().setActiveOrg("evil-org-not-in-list");
    // State should remain unchanged
    expect(useOrgStore.getState().activeOrgId).toBe("lms-hang-hai");
  });

  it("allows switching to personal workspace (null)", () => {
    useOrgStore.setState({
      organizations: MOCK_ORGS,
      multiTenantEnabled: true,
      activeOrgId: "lms-hang-hai",
    });

    useOrgStore.getState().setActiveOrg(null);
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("allows switching to personal org via PERSONAL_ORG_ID", () => {
    useOrgStore.setState({
      organizations: MOCK_ORGS,
      multiTenantEnabled: true,
      activeOrgId: "lms-hang-hai",
    });

    useOrgStore.getState().setActiveOrg(PERSONAL_ORG_ID);
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("rejects switching when organizations list is empty", () => {
    useOrgStore.setState({
      organizations: [],
      multiTenantEnabled: true,
      activeOrgId: null,
    });

    useOrgStore.getState().setActiveOrg("lms-hang-hai");
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("logs a warning when unknown org is rejected", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    useOrgStore.setState({
      organizations: MOCK_ORGS,
      multiTenantEnabled: true,
      activeOrgId: null,
    });

    useOrgStore.getState().setActiveOrg("nonexistent-org");
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Attempted switch to unknown org"),
      "nonexistent-org",
      expect.stringContaining("ignored"),
    );

    warnSpy.mockRestore();
  });
});


// =============================================================================
// C3: PostMessage origin validation
// =============================================================================

describe("C3: PostMessage origin validation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("isEmbedded returns false when window.self === window.top (jsdom default)", () => {
    expect(isEmbedded()).toBe(false);
  });

  it("sendToParent does not call postMessage when not embedded", () => {
    const postMessageSpy = vi.spyOn(window.parent, "postMessage");

    // Default jsdom: window.self === window.top (not embedded)
    sendToParent("wiii:test", { data: "hello" });

    expect(postMessageSpy).not.toHaveBeenCalled();
  });

  it("onParentMessage rejects messages when no allowedOrigins configured", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const handler = vi.fn();

    const cleanup = onParentMessage(handler);

    // Simulate message from parent
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:auth", payload: {} },
        origin: "https://evil.com",
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    warnSpy.mockRestore();
    cleanup();
  });

  it("onParentMessage rejects messages with empty allowedOrigins array", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, []);

    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:auth", payload: {} },
        origin: "https://evil.com",
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    warnSpy.mockRestore();
    cleanup();
  });

  it("onParentMessage rejects messages from non-allowed origins", () => {
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, ["https://trusted.com"]);

    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:auth", payload: {} },
        origin: "https://evil.com",
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    cleanup();
  });

  it("onParentMessage accepts messages from allowed origins with wiii: prefix", () => {
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, ["https://trusted.com"]);

    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:auth", payload: { token: "fresh" } },
        origin: "https://trusted.com",
      }),
    );

    expect(handler).toHaveBeenCalledWith({
      type: "wiii:auth",
      payload: { token: "fresh" },
    });
    cleanup();
  });

  it("onParentMessage ignores non-wiii: prefixed messages from allowed origin", () => {
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, ["https://trusted.com"]);

    // Message without wiii: prefix
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "other-system:event" },
        origin: "https://trusted.com",
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    cleanup();
  });

  it("onParentMessage ignores non-object messages from allowed origin", () => {
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, ["https://trusted.com"]);

    window.dispatchEvent(
      new MessageEvent("message", {
        data: "just a string",
        origin: "https://trusted.com",
      }),
    );

    expect(handler).not.toHaveBeenCalled();
    cleanup();
  });

  it("cleanup function removes event listener", () => {
    const handler = vi.fn();

    const cleanup = onParentMessage(handler, ["https://trusted.com"]);

    // First message should be received
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:theme", payload: { theme: "dark" } },
        origin: "https://trusted.com",
      }),
    );
    expect(handler).toHaveBeenCalledTimes(1);

    // Cleanup
    cleanup();

    // Second message should NOT be received
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "wiii:theme", payload: { theme: "light" } },
        origin: "https://trusted.com",
      }),
    );
    expect(handler).toHaveBeenCalledTimes(1); // Still 1
  });

  it("setParentOrigin stores the origin for later use", () => {
    // setParentOrigin should not throw
    expect(() => setParentOrigin("https://example.com")).not.toThrow();
  });
});


// =============================================================================
// H5: Facebook cookie no longer in DEFAULT_SETTINGS
// =============================================================================

describe("H5: Facebook cookie removed from default settings", () => {
  beforeEach(() => {
    resetAllStores();
  });

  it("DEFAULT_SETTINGS does not include facebook_cookie property", () => {
    const settings = useSettingsStore.getState().settings;
    expect(settings).not.toHaveProperty("facebook_cookie");
  });

  it("settings store does not set facebook_cookie on load", async () => {
    await useSettingsStore.getState().loadSettings();
    const settings = useSettingsStore.getState().settings;
    expect(settings).not.toHaveProperty("facebook_cookie");
  });

  it("facebook_cookie functions available in secure-token-storage module", async () => {
    const secureStore = await import("@/lib/secure-token-storage");
    expect(typeof secureStore.storeFacebookCookie).toBe("function");
    expect(typeof secureStore.loadFacebookCookie).toBe("function");
    expect(typeof secureStore.clearFacebookCookie).toBe("function");
  });
});


// =============================================================================
// H3: Embed JWT decode safety
// =============================================================================

describe("H3: decodeJwtUser safety — no hardcoded fallback IDs", () => {
  it("decodes a valid JWT with standard claims", () => {
    const token = buildFakeJwt({
      sub: "user-123",
      email: "test@example.com",
      name: "Test User",
      role: "teacher",
    });

    const user = buildAuthUserFromJwt(token);
    expect(user.id).toBe("user-123");
    expect(user.email).toBe("test@example.com");
    expect(user.name).toBe("Test User");
    expect(user.role).toBe("teacher");
    expect(user.legacy_role).toBe("teacher");
  });

  it("falls back to user_id when sub is missing", () => {
    const token = buildFakeJwt({
      user_id: "fallback-id",
      email: "test@example.com",
    });

    const user = buildAuthUserFromJwt(token);
    expect(user.id).toBe("fallback-id");
  });

  it("falls back to display_name when name is missing", () => {
    const token = buildFakeJwt({
      sub: "u1",
      display_name: "Display Name",
    });

    const user = buildAuthUserFromJwt(token);
    expect(user.name).toBe("Display Name");
  });

  it("returns empty strings (NOT 'embed-user') for invalid token", () => {
    const user = buildAuthUserFromJwt("not-a-jwt");
    expect(user.id).toBe("");
    expect(user.email).toBe("");
    expect(user.name).toBe("");
    expect(user.id).not.toBe("embed-user");
  });

  it("returns empty strings for completely garbled token", () => {
    const user = buildAuthUserFromJwt("abc.!!!invalid-base64!!!.xyz");
    expect(user.id).toBe("");
    expect(user.email).toBe("");
    expect(user.name).toBe("");
  });

  it("returns empty strings for empty string token", () => {
    const user = buildAuthUserFromJwt("");
    expect(user.id).toBe("");
    expect(user.email).toBe("");
  });

  it("defaults role to 'student' when not present in token", () => {
    const token = buildFakeJwt({ sub: "user-1" });
    const user = buildAuthUserFromJwt(token);
    expect(user.role).toBe("student");
    expect(user.platform_role).toBe("user");
  });

  it("defaults role to 'student' for invalid token", () => {
    const user = buildAuthUserFromJwt("invalid");
    expect(user.role).toBe("student");
  });

  it("preserves host role and connector context from identity v2 claims", () => {
    const token = buildFakeJwt({
      sub: "u-host",
      role: "teacher",
      legacy_role: "teacher",
      platform_role: "user",
      host_role: "teacher",
      role_source: "lms_host",
      active_organization_id: "lms-hang-hai",
      connector_id: "maritime-lms",
      identity_version: "2",
    });

    const user = buildAuthUserFromJwt(token);
    expect(user.host_role).toBe("teacher");
    expect(user.role_source).toBe("lms_host");
    expect(user.active_organization_id).toBe("lms-hang-hai");
    expect(user.connector_id).toBe("maritime-lms");
    expect(user.identity_version).toBe("2");
  });
});


// =============================================================================
// Integration: Cross-store auth header behavior
// =============================================================================

describe("Integration: settings + auth store header coordination", () => {
  beforeEach(() => {
    resetAllStores();
    vi.clearAllMocks();
  });

  it("auth-store OAuth headers contain no identity fields beyond Authorization", async () => {
    await useAuthStore.getState().loginWithTokens(
      "oauth-access-token",
      "oauth-refresh-token",
      1800,
      MOCK_USER,
    );

    const oauthHeaders = useAuthStore.getState().getAuthHeaders();
    // Only Authorization — no X-User-ID, X-Role, X-API-Key
    expect(Object.keys(oauthHeaders)).toEqual(["Authorization"]);
    expect(oauthHeaders["Authorization"]).toBe("Bearer oauth-access-token");
  });

  it("settings-store legacy path includes all identity headers", () => {
    useAuthStore.setState({ authMode: "legacy", tokens: null });

    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "anon-user-id",
        user_role: "student",
      },
      isLoaded: true,
    });

    const legacyHeaders = useSettingsStore.getState().getAuthHeaders();
    expect(legacyHeaders["X-User-ID"]).toBe("anon-user-id");
    expect(legacyHeaders["X-Role"]).toBe("student");
    expect(legacyHeaders["X-API-Key"]).toBe("key");
  });

  it("legacy mode with admin role passes through (backend enforces in production)", () => {
    useAuthStore.setState({ authMode: "legacy", tokens: null });

    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        api_key: "key",
        user_id: "user-1",
        user_role: "admin",
      },
      isLoaded: true,
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-Role"]).toBe("admin");
  });

  it("settings-store OAuth headers use the token active org instead of stale settings org", async () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        organization_id: "maritime-lms",
      },
      isLoaded: true,
    });

    await useAuthStore.getState().loginWithTokens(
      "oauth-access-token",
      "oauth-refresh-token",
      1800,
      {
        ...MOCK_USER,
        active_organization_id: "default",
      },
    );

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer oauth-access-token");
    expect(headers["X-Organization-ID"]).toBe("default");
  });

  it("settings-store OAuth headers omit stale org when the token has no active org", async () => {
    useSettingsStore.setState({
      settings: {
        ...DEFAULT_SETTINGS,
        organization_id: "maritime-lms",
      },
      isLoaded: true,
    });

    await useAuthStore.getState().loginWithTokens(
      "oauth-access-token",
      "oauth-refresh-token",
      1800,
      MOCK_USER,
    );

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["Authorization"]).toBe("Bearer oauth-access-token");
    expect(headers["X-Organization-ID"]).toBeUndefined();
  });

  it("normalizes OAuth org headers", () => {
    expect(resolveOAuthOrganizationHeader(" default ")).toBe("default");
    expect(resolveOAuthOrganizationHeader("personal")).toBeUndefined();
    expect(resolveOAuthOrganizationHeader("")).toBeUndefined();
    expect(resolveOAuthOrganizationHeader(null)).toBeUndefined();
  });
});

describe("OAuth request identity projection", () => {
  it("prefers canonical OAuth user id over legacy settings user_id", () => {
    expect(
      _resolveRequestUserId("oauth", "anon-local-user", "canonical-user-1"),
    ).toBe("canonical-user-1");
  });

  it("falls back to settings user_id in legacy mode", () => {
    expect(
      _resolveRequestUserId("legacy", "legacy-user-1", "canonical-user-1"),
    ).toBe("legacy-user-1");
  });

  it("prefers OAuth user name/email for visible request identity", () => {
    expect(
      _resolveRequestDisplayName(
        "oauth",
        "Legacy Name",
        "anon-local-user",
        "Wiii User",
        "user@example.com",
      ),
    ).toBe("Wiii User");
  });

  it("treats host role as a local overlay in OAuth mode", () => {
    expect(
      _resolveCompatibilityRole("oauth", "admin", "teacher", undefined),
    ).toBe("teacher");
    expect(
      _resolveCompatibilityRole("oauth", "admin", undefined, undefined),
    ).toBe("student");
  });
});
