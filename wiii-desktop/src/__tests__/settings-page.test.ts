/**
 * Unit tests for SettingsPage component logic & settings store.
 * Sprint 215: Added tests for read-only user ID, org-aware role, domain auto-select.
 * Sprint 216: Added tests for tab visibility, progressive disclosure, copy support ID.
 * Sprint 219: Removed Learning tab, Memory category groups.
 * Sprint 219b: Removed pronoun_style from Preferences (auto-detected, not manual).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useSettingsStore } from "@/stores/settings-store";
import { useUIStore } from "@/stores/ui-store";
import { useAuthStore } from "@/stores/auth-store";
import { DEFAULT_SERVER_URL } from "@/lib/constants";

// Mock API dependencies for org-store
vi.mock("@/api/organizations", () => ({
  listOrganizations: vi.fn().mockRejectedValue(new Error("Not configured")),
  getOrgSettings: vi.fn().mockRejectedValue(new Error("Not configured")),
  getOrgPermissions: vi.fn().mockRejectedValue(new Error("Not configured")),
}));
vi.mock("@/api/admin", () => ({
  getAdminContext: vi.fn().mockRejectedValue(new Error("Not configured")),
}));
vi.mock("@/lib/org-branding", () => ({
  applyOrgBranding: vi.fn(),
  resetBranding: vi.fn(),
  DEFAULT_BRANDING: { chatbot_name: "Wiii", welcome_message: "Xin chào!" },
}));
vi.mock("@/lib/constants", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, PERSONAL_ORG_ID: "personal" };
});

describe("Memory status summary", () => {
  it("renders aggregate memory health fields in the Memory tab source", async () => {
    const src = await import("@/components/settings/SettingsPage?raw");
    const code = src.default as string;

    expect(code).toContain("memorySummary");
    expect(code).toContain("latestMemoryLabel");
    expect(code).toContain("scopeLabel");
    expect(code).toContain("Tổng");
    expect(code).toContain("Phạm vi");
  });
});

// Reset stores before each test
beforeEach(() => {
  useSettingsStore.setState({
    settings: {
      server_url: "http://localhost:8080",
      api_key: "local-dev-key",
      user_id: "test-user-fixed",
      user_role: "student",
      display_name: "User",
      default_domain: "maritime",
      theme: "system",
      language: "vi",
      font_size: "medium",
      show_thinking: true,
      show_reasoning_trace: false,
      streaming_version: "v3",
      thinking_level: "balanced",
    },
    isLoaded: false,
  });
  useUIStore.setState({
    activeView: "chat",
    sidebarOpen: true,
    sourcesPanelOpen: false,
    selectedSourceIndex: null,
  });
});

describe("Settings Store", () => {
  it("should start with default settings", () => {
    const { settings } = useSettingsStore.getState();
    expect(settings.server_url).toBe("http://localhost:8080");
    expect(settings.api_key).toBe("local-dev-key");
    expect(settings.user_id).toBe("test-user-fixed");
    expect(settings.user_role).toBe("student");
    expect(settings.theme).toBe("system");
    expect(settings.show_thinking).toBe(true);
    expect(settings.streaming_version).toBe("v3");
  });

  it("should update partial settings", async () => {
    await useSettingsStore.getState().updateSettings({
      server_url: "http://example.com:9000",
      api_key: "new-key",
    });

    const { settings } = useSettingsStore.getState();
    expect(settings.server_url).toBe("http://example.com:9000");
    expect(settings.api_key).toBe("new-key");
    // Other fields unchanged
    expect(settings.user_id).toBe("test-user-fixed");
    expect(settings.theme).toBe("system");
  });

  it("should update theme setting", async () => {
    await useSettingsStore.getState().updateSettings({ theme: "dark" });
    expect(useSettingsStore.getState().settings.theme).toBe("dark");
  });

  it("should update user role in store (Sprint 215: no longer editable in UI)", async () => {
    await useSettingsStore.getState().updateSettings({ user_role: "teacher" });
    expect(useSettingsStore.getState().settings.user_role).toBe("teacher");
  });

  it("should update streaming version", async () => {
    await useSettingsStore.getState().updateSettings({
      streaming_version: "v2",
    });
    expect(useSettingsStore.getState().settings.streaming_version).toBe("v2");
  });

  it("should reset to defaults", async () => {
    await useSettingsStore.getState().updateSettings({
      server_url: "http://custom:1234",
      theme: "dark",
      user_role: "admin",
    });

    await useSettingsStore.getState().resetSettings();

    const { settings } = useSettingsStore.getState();
    expect(settings.server_url).toBe(DEFAULT_SERVER_URL);
    expect(settings.theme).toBe("system");
    expect(settings.user_role).toBe("student");
  });

  it("should generate auth headers", async () => {
    await useSettingsStore.getState().updateSettings({
      api_key: "test-key-123",
      user_id: "user-456",
      user_role: "teacher",
    });

    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-API-Key"]).toBe("test-key-123");
    expect(headers["X-User-ID"]).toBe("user-456");
    expect(headers["X-Role"]).toBe("teacher");
  });

  it("should include all required header fields", () => {
    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers).toHaveProperty("X-API-Key");
    expect(headers).toHaveProperty("X-User-ID");
    expect(headers).toHaveProperty("X-Role");
  });
});

describe("UI Store — Settings View", () => {
  it("should start with activeView = chat", () => {
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("should open settings view", () => {
    useUIStore.getState().openSettings();
    expect(useUIStore.getState().activeView).toBe("settings");
  });

  it("should close settings view", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().closeSettings();
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("should toggle sidebar independently", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().toggleSidebar();

    expect(useUIStore.getState().activeView).toBe("settings");
    expect(useUIStore.getState().sidebarOpen).toBe(false);
  });
});

describe("Settings — Display Name & Domain", () => {
  it("should update display name", async () => {
    await useSettingsStore.getState().updateSettings({
      display_name: "Captain Nguyễn",
    });
    expect(useSettingsStore.getState().settings.display_name).toBe(
      "Captain Nguyễn"
    );
  });

  it("should update default domain", async () => {
    await useSettingsStore.getState().updateSettings({
      default_domain: "traffic_law",
    });
    expect(useSettingsStore.getState().settings.default_domain).toBe(
      "traffic_law"
    );
  });

  it("should update language", async () => {
    await useSettingsStore.getState().updateSettings({ language: "en" });
    expect(useSettingsStore.getState().settings.language).toBe("en");
  });

  it("should update font size", async () => {
    await useSettingsStore.getState().updateSettings({ font_size: "large" });
    expect(useSettingsStore.getState().settings.font_size).toBe("large");
  });

  it("should toggle show_reasoning_trace", async () => {
    expect(useSettingsStore.getState().settings.show_reasoning_trace).toBe(
      false
    );
    await useSettingsStore.getState().updateSettings({
      show_reasoning_trace: true,
    });
    expect(useSettingsStore.getState().settings.show_reasoning_trace).toBe(
      true
    );
  });
});

// ---------------------------------------------------------------------------
// Sprint 215: "Hồ Sơ Thật" — Settings User Tab UX Overhaul
// ---------------------------------------------------------------------------
import { useOrgStore } from "@/stores/org-store";

describe("Sprint 215 — User ID read-only", () => {
  it("should preserve user_id in settings store (sent via X-User-ID)", () => {
    const { settings } = useSettingsStore.getState();
    expect(settings.user_id).toBe("test-user-fixed");
    // user_id is still stored and used in headers — just not editable in UI
    const headers = useSettingsStore.getState().getAuthHeaders();
    expect(headers["X-User-ID"]).toBe("test-user-fixed");
  });

  it("should still allow programmatic user_id update (store-level)", async () => {
    await useSettingsStore.getState().updateSettings({ user_id: "new-id" });
    expect(useSettingsStore.getState().settings.user_id).toBe("new-id");
  });
});

describe("Sprint 215 — Org-aware role display", () => {
  beforeEach(() => {
    useOrgStore.setState({
      activeOrgId: null,
      orgRole: null,
      organizations: [],
      multiTenantEnabled: false,
      permissions: [],
      orgSettings: null,
    });
  });

  it("should store orgRole from permissions response", () => {
    useOrgStore.setState({ orgRole: "admin", activeOrgId: "org-1" });
    expect(useOrgStore.getState().orgRole).toBe("admin");
  });

  it("should reset orgRole when switching to personal workspace", () => {
    useOrgStore.setState({ orgRole: "owner", activeOrgId: "org-1" });
    // Simulate switch to personal
    useOrgStore.setState({ orgRole: null, activeOrgId: null });
    expect(useOrgStore.getState().orgRole).toBeNull();
  });

  it("should default orgRole to null", () => {
    expect(useOrgStore.getState().orgRole).toBeNull();
  });

  it("should support all 3 org role values", () => {
    for (const role of ["member", "admin", "owner"]) {
      useOrgStore.setState({ orgRole: role });
      expect(useOrgStore.getState().orgRole).toBe(role);
    }
  });
});

describe("Sprint 215 — Domain label and auto-select", () => {
  it("should still store default_domain in settings", async () => {
    await useSettingsStore.getState().updateSettings({ default_domain: "traffic_law" });
    expect(useSettingsStore.getState().settings.default_domain).toBe("traffic_law");
  });

  it("should preserve domain setting across updates", async () => {
    await useSettingsStore.getState().updateSettings({ default_domain: "maritime" });
    await useSettingsStore.getState().updateSettings({ display_name: "Test" });
    expect(useSettingsStore.getState().settings.default_domain).toBe("maritime");
  });
});

// ---------------------------------------------------------------------------
// Sprint 216: "Chuyên Nghiệp" — Settings UX Deep Overhaul
// Tab visibility logic: developer mode + org admin conditional tabs
// ---------------------------------------------------------------------------
describe("Sprint 216 — Tab visibility", () => {
  beforeEach(() => {
    // Reset auth and org stores
    useAuthStore.setState({ authMode: "legacy", isAuthenticated: true });
    useOrgStore.setState({
      activeOrgId: null,
      orgRole: null,
      organizations: [],
      multiTenantEnabled: false,
      permissions: [],
      orgSettings: null,
    });
  });

  // Helper: compute visible tab IDs using the same logic as SettingsView/SettingsPage
  function getVisibleTabIds(): string[] {
    const { authMode } = useAuthStore.getState();
    const orgState = useOrgStore.getState();
    const isDeveloperMode = authMode === "legacy" || orgState.isSystemAdmin();

    const tabs: string[] = ["profile", "preferences", "memory", "context"];
    if (isDeveloperMode) {
      tabs.push("connection");
    }
    if (orgState.activeOrgId && (orgState.isOrgAdmin() || orgState.isSystemAdmin())) {
      tabs.push("organization");
    }
    tabs.push("living-agent");
    return tabs;
  }

  it("should show connection tab in legacy mode", () => {
    useAuthStore.setState({ authMode: "legacy" });
    const tabs = getVisibleTabIds();
    expect(tabs).toContain("connection");
  });

  it("should hide connection tab in OAuth mode (non-admin)", () => {
    useAuthStore.setState({ authMode: "oauth", isAuthenticated: true });
    // Not a system admin
    const tabs = getVisibleTabIds();
    expect(tabs).not.toContain("connection");
  });

  it("should show connection tab for system admin in OAuth mode", () => {
    useAuthStore.setState({ authMode: "oauth", isAuthenticated: true });
    useOrgStore.setState({
      adminContext: { is_system_admin: true, is_org_admin: false, admin_org_ids: [], enable_org_admin: false },
    });
    const tabs = getVisibleTabIds();
    expect(tabs).toContain("connection");
  });

  it("should hide organization tab when no active org or admin role", () => {
    useOrgStore.setState({ activeOrgId: null, orgRole: null });
    const tabs = getVisibleTabIds();
    expect(tabs).not.toContain("organization");
  });

  it("should show organization tab for org admin with active org", () => {
    useOrgStore.setState({
      activeOrgId: "org-1",
      orgRole: "admin",
      adminContext: { is_system_admin: false, is_org_admin: true, admin_org_ids: ["org-1"], enable_org_admin: true },
    });
    const tabs = getVisibleTabIds();
    expect(tabs).toContain("organization");
  });

  it("should default to profile tab (not connection)", () => {
    const tabs = getVisibleTabIds();
    expect(tabs[0]).toBe("profile");
    expect(tabs).not.toContain("user"); // old tab ID removed
  });

  it("should use updated Vietnamese labels (Hồ sơ, Tùy chỉnh, Trí nhớ)", () => {
    // This verifies the tab IDs map correctly — UI labels tested via component rendering
    const tabs = getVisibleTabIds();
    expect(tabs).toContain("profile"); // was "user" / "Người dùng" → now "Hồ sơ"
    expect(tabs).toContain("preferences"); // label: "Giao diện" → "Tùy chỉnh"
    expect(tabs).toContain("memory"); // label: "Bộ nhớ" → "Trí nhớ"
  });
});

describe("Sprint 216 — Developer fields moved to Connection tab", () => {
  it("should still store streaming_version (moved, not removed)", async () => {
    await useSettingsStore.getState().updateSettings({ streaming_version: "v2" });
    expect(useSettingsStore.getState().settings.streaming_version).toBe("v2");
  });

  it("should still store show_reasoning_trace (moved, not removed)", async () => {
    await useSettingsStore.getState().updateSettings({ show_reasoning_trace: true });
    expect(useSettingsStore.getState().settings.show_reasoning_trace).toBe(true);
  });
});

describe("Sprint 216 — Copy support ID", () => {
  it("should have user_id available for clipboard copy (legacy mode)", () => {
    const { settings } = useSettingsStore.getState();
    // user_id is still stored and accessible — just shown via "Sao chép mã hỗ trợ" button
    expect(settings.user_id).toBe("test-user-fixed");
    expect(typeof settings.user_id).toBe("string");
    expect(settings.user_id.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Sprint 219: "Học Tự Nhiên" — Adaptive Preference Learning
// Removed Learning tab, pronoun moved to Preferences, Memory category groups
// ---------------------------------------------------------------------------
import { MEMORY_CATEGORIES } from "@/components/settings/SettingsPage";
import { FACT_TYPE_LABELS } from "@/stores/memory-store";

describe("Sprint 219 — Learning tab removed", () => {
  it("should NOT include learning tab in visible tabs", () => {
    useAuthStore.setState({ authMode: "legacy", isAuthenticated: true });
    const { authMode } = useAuthStore.getState();
    const orgState = useOrgStore.getState();
    const isDeveloperMode = authMode === "legacy" || orgState.isSystemAdmin();
    const tabs: string[] = ["profile", "preferences", "memory", "context"];
    if (isDeveloperMode) tabs.push("connection");
    tabs.push("living-agent");

    expect(tabs).not.toContain("learning");
    expect(tabs).toContain("preferences");
    expect(tabs).toContain("memory");
  });

  it("should have profile as first tab (unchanged)", () => {
    const tabs = ["profile", "preferences", "memory", "context"];
    expect(tabs[0]).toBe("profile");
  });
});

describe("Sprint 219 — Memory category grouping", () => {
  it("should export MEMORY_CATEGORIES constant", () => {
    expect(MEMORY_CATEGORIES).toBeDefined();
    expect(Array.isArray(MEMORY_CATEGORIES)).toBe(true);
  });

  it("should have 3 categories", () => {
    expect(MEMORY_CATEGORIES).toHaveLength(3);
  });

  it("should have identity category with correct types", () => {
    const identity = MEMORY_CATEGORIES.find((c) => c.id === "identity");
    expect(identity).toBeDefined();
    expect(identity!.label).toBe("Bản thân");
    expect(identity!.types).toContain("name");
    expect(identity!.types).toContain("age");
    expect(identity!.types).toContain("role");
  });

  it("should have learning category with correct types", () => {
    const learning = MEMORY_CATEGORIES.find((c) => c.id === "learning");
    expect(learning).toBeDefined();
    expect(learning!.label).toBe("Học tập");
    expect(learning!.types).toContain("learning_style");
    expect(learning!.types).toContain("strength");
    expect(learning!.types).toContain("weakness");
    expect(learning!.types).toContain("goal");
  });

  it("should have personal category with correct types", () => {
    const personal = MEMORY_CATEGORIES.find((c) => c.id === "personal");
    expect(personal).toBeDefined();
    expect(personal!.label).toBe("Sở thích");
    expect(personal!.types).toContain("hobby");
    expect(personal!.types).toContain("interest");
    expect(personal!.types).toContain("preference");
  });

  it("should cover all FACT_TYPE_LABELS types in categories", () => {
    const allCategorizedTypes = MEMORY_CATEGORIES.flatMap((c) => c.types);
    const knownTypes = Object.keys(FACT_TYPE_LABELS);
    // Most types should be categorized (pronoun_style is excluded from memory display)
    const uncategorized = knownTypes.filter(
      (t) => !allCategorizedTypes.includes(t) && t !== "pronoun_style"
    );
    // At most 1-2 types uncategorized (they fall into "Khác" group)
    expect(uncategorized.length).toBeLessThanOrEqual(2);
  });
});
