/**
 * Root App component — initializes stores, mounts layout.
 * Sprint 106: Loading screen during init.
 */
import { lazy, Suspense, useEffect } from "react";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { useSettingsStore } from "@/stores/settings-store";
import { useAuthStore } from "@/stores/auth-store";
import type { AuthUser } from "@/stores/auth-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useContextStore } from "@/stores/context-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useToastStore } from "@/stores/toast-store";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useScheduledTaskNotifications } from "@/hooks/useScheduledTaskNotifications";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import { initClient } from "@/api/client";
import { buildAuthUserFromPayload, toCompatibilitySettingsRole } from "@/lib/auth-user";

const AppShell = lazy(async () => {
  const mod = await import("@/components/layout/AppShell");
  return { default: mod.AppShell };
});

const LoginScreen = lazy(async () => {
  const mod = await import("@/components/auth/LoginScreen");
  return { default: mod.LoginScreen };
});

const CommandPalette = lazy(async () => {
  const mod = await import("@/components/common/CommandPalette");
  return { default: mod.CommandPalette };
});

const AvatarPreview = lazy(async () => {
  const mod = await import("@/components/common/AvatarPreview");
  return { default: mod.AvatarPreview };
});

const PointyPreview = lazy(async () => {
  const mod = await import("@/components/common/PointyPreview");
  return { default: mod.PointyPreview };
});

function BootSplash({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-surface">
      <div className="flex flex-col items-center gap-4">
        <WiiiAvatar state="thinking" size={48} />
        <span className="text-sm text-text-tertiary">{label}</span>
      </div>
    </div>
  );
}

export default function App() {
  // Dev tool: ?preview=avatar shows avatar preview page
  if (window.location.search.includes("preview=avatar")) {
    return (
      <Suspense fallback={<BootSplash label="Wiii đang mở bản xem trước..." />}>
        <AvatarPreview />
      </Suspense>
    );
  }

  // Wiii Pointy demo: ?preview=pointy showcases the spring-physics
  // multi-cursor system. Standalone — no auth, no chat boot, just
  // visual verification of the cursor architecture.
  if (window.location.search.includes("preview=pointy")) {
    return (
      <Suspense fallback={<BootSplash label="Wiii Pointy đang khởi động..." />}>
        <PointyPreview />
      </Suspense>
    );
  }

  const { loadSettings, settings, updateSettings, isLoaded: settingsLoaded } = useSettingsStore();
  const { loadAuth, loginWithTokens, isAuthenticated, isLoaded: authLoaded, authMode, user: authUser, isTokenExpiringSoon, refreshAccessToken } = useAuthStore();
  const { startPolling, stopPolling, setOnReconnect } = useConnectionStore();
  const { startPolling: startContextPolling, stopPolling: stopContextPolling } =
    useContextStore();
  const { fetchDomains, setOrgFilter } = useDomainStore();
  const { fetchOrganizations, setActiveOrg, detectSubdomainOrg, fetchAdminContext } = useOrgStore();
  const { loadConversations, isLoaded: chatsLoaded } = useChatStore();
  const { commandPaletteOpen, closeCommandPalette } = useUIStore();
  const { addToast } = useToastStore();

  // Register global keyboard shortcuts
  useKeyboardShortcuts();
  useScheduledTaskNotifications();

  // Sprint 193: Handle web OAuth callback (hash-based token delivery)
  // Must run BEFORE auth state is checked so tokens are available immediately.
  useEffect(() => {
    if (!window.location.hash) return;
    const params = new URLSearchParams(window.location.hash.substring(1));
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");
    if (!accessToken || !refreshToken) return;

    const expiresIn = parseInt(params.get("expires_in") || "900", 10);
    const user: AuthUser = buildAuthUserFromPayload({
      user_id: params.get("user_id") || "",
      email: params.get("email") || "",
      name: params.get("name") || "",
      avatar_url: params.get("avatar_url") || "",
      role: params.get("role") || "",
      legacy_role: params.get("legacy_role") || "",
      platform_role: params.get("platform_role") || "user",
      organization_role: params.get("organization_role") || "",
      host_role: params.get("host_role") || "",
      role_source: params.get("role_source") || "",
      active_organization_id: params.get("active_organization_id") || "",
      organization_id: params.get("organization_id") || "",
      connector_id: params.get("connector_id") || "",
      identity_version: params.get("identity_version") || "",
    });

    // Sprint 193b: Extract organization_id from OAuth callback
    const orgId = user.active_organization_id || params.get("organization_id") || "";

    // Login immediately, then persist settings + clear hash
    loginWithTokens(accessToken, refreshToken, expiresIn, user).then(async () => {
      updateSettings({
        user_id: user.id,
        display_name: user.name || user.email,
        user_role: toCompatibilitySettingsRole(user),
        ...(orgId ? { organization_id: orgId } : {}),
      });
      // Sprint 218: Switch chat store to new user's conversations
      await useChatStore.getState().switchUser(user.id);
      // Clear hash AFTER login succeeds to prevent token leakage in browser history
      window.history.replaceState(null, "", window.location.pathname);
    }).catch((err) => {
      console.error("[OAuth] Login failed:", err);
      addToast("error", "Đăng nhập thất bại. Vui lòng thử lại.");
      // Clear hash even on failure to prevent stale token in URL
      window.history.replaceState(null, "", window.location.pathname);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Initialize on mount
  useEffect(() => {
    async function init() {
      // 1. Load persisted settings
      await loadSettings();
      // 2. Load persisted auth state (Sprint 157)
      await loadAuth();
      // 3. Load persisted conversations
      await loadConversations();
    }
    init();
  }, [loadSettings, loadAuth, loadConversations]);

  // When settings AND auth are loaded, initialize client and start health polling
  useEffect(() => {
    // Sprint 218: Guard on BOTH settingsLoaded AND authLoaded to prevent race condition
    // Without authLoaded, API calls fire before OAuth tokens are available → 401
    if (!settingsLoaded || !authLoaded) return;
    if (!isAuthenticated) return;
    if (settings.server_url) {
      // Sprint 192: Initialize HTTP client with dynamic header resolver
      // Headers are resolved at request time from getAuthHeaders() — always fresh
      const client = initClient(settings.server_url, {});
      client.setHeaderResolver(() => useSettingsStore.getState().getAuthHeaders());
      // Sprint 192 + Phase 31 (#207): 401 interceptor.
      //   - oauth mode: try silent token refresh; ``refreshAccessToken``
      //     returns true on success → original request retries.
      //   - legacy mode: nothing to refresh. The api_key shipped with the
      //     request is invalid (placeholder, stale, or mis-synced with
      //     backend's .env). Force-logout clears state + lets the user
      //     re-authenticate fresh instead of leaving them stuck on a
      //     broken-looking app where every call silently 401s.
      client.setOnUnauthorized(async () => {
        const authState = useAuthStore.getState();
        if (authState.authMode === "oauth") {
          return authState.refreshAccessToken(
            useSettingsStore.getState().settings.server_url,
          );
        }
        if (authState.authMode === "legacy" && authState.isAuthenticated) {
          await authState.logout();
        }
        return false;
      });

      // Start health check polling
      startPolling();

      // Register reconnection celebration
      setOnReconnect(() => addToast("success", "Wiii đã quay lại rồi nè! ✨"));

      // Fetch available domains
      fetchDomains();

      // Sprint 175: Detect org from subdomain (web deployment)
      detectSubdomainOrg();

      // Sprint 156: Fetch organizations + restore saved org
      fetchOrganizations().then(async () => {
        // Sprint 181: Fetch admin context after auth/org init.
        // Issue #112: await it so the auto-pick branch below can rely on
        // isSystemAdmin() being populated.
        await fetchAdminContext();
        // Sprint 175: If subdomain detected, use it (skip saved org)
        const subdomainOrg = useOrgStore.getState().subdomainOrgId;
        let orgToActivate = subdomainOrg || settings.organization_id;
        // Issue #112: System admin without an active org cannot reach the
        // "Quản lý tổ chức" sidebar button (gated on activeOrgId !== "personal"),
        // so the Knowledge upload + visual knowledge graph/scatter UI is
        // unreachable. Auto-pick the first non-personal org as a starting point.
        if (!orgToActivate && useOrgStore.getState().isSystemAdmin()) {
          const orgs = useOrgStore.getState().organizations;
          const firstRealOrg = orgs.find((o) => o.id && o.id !== "personal");
          if (firstRealOrg) orgToActivate = firstRealOrg.id;
        }
        if (orgToActivate) {
          setActiveOrg(orgToActivate);
          const org = useOrgStore.getState().organizations.find((o) => o.id === orgToActivate);
          if (org) {
            setOrgFilter(org.allowed_domains);
          }
        }
      });
    }

    return () => {
      stopPolling();
    };
  }, [settingsLoaded, authLoaded, isAuthenticated, settings.server_url, settings.api_key, settings.user_id, settings.user_role, startPolling, stopPolling, fetchDomains, fetchOrganizations, setActiveOrg, setOrgFilter, setOnReconnect, addToast, detectSubdomainOrg, fetchAdminContext, refreshAccessToken]);

  // Start context polling when active conversation changes (handles mid-session creation)
  const activeConv = useChatStore((s) => s.activeConversation());
  const sessionId = activeConv?.session_id || activeConv?.id || "";
  useEffect(() => {
    if (sessionId && settings.server_url) {
      startContextPolling(sessionId);
    }
    return () => {
      stopContextPolling();
    };
  }, [sessionId, settings.server_url, startContextPolling, stopContextPolling]);

  // Sprint 157: Auto-refresh JWT before expiration
  useEffect(() => {
    if (authMode !== "oauth" || !isAuthenticated) return;
    const interval = setInterval(() => {
      if (isTokenExpiringSoon()) {
        refreshAccessToken(settings.server_url);
      }
    }, 60_000); // Check every minute
    return () => clearInterval(interval);
  }, [authMode, isAuthenticated, isTokenExpiringSoon, refreshAccessToken, settings.server_url]);

  // Wiii Pointy v2.4 — mount awareness layer khi user đã authenticated.
  // PageScanner quét DOM cho pointable elements + CursorAwareness track
  // cursor state, publish vào HostContextStore → backend tự nhận qua
  // host_context.page.metadata trong chat request.
  useEffect(() => {
    if (!isAuthenticated) return;
    let unmount: (() => void) | null = null;
    void import("@/pointy-host/integration").then(
      ({ mountPointyAwareness }) => {
        unmount = mountPointyAwareness();
      },
    );
    return () => {
      if (unmount) unmount();
    };
  }, [isAuthenticated]);

  // Keep settings.user_id in sync with auth.user.id in OAuth mode.
  // Fixes race condition where loadSettings() loads stale anonymous UUID from
  // localStorage before loginWithTokens() updates it — any code using
  // settings.user_id (chat requests, memory tab, etc.) stays correct.
  useEffect(() => {
    if (authMode === "oauth" && authUser?.id && settings.user_id !== authUser.id) {
      updateSettings({ user_id: authUser.id });
    }
  }, [authMode, authUser?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Loading screen while stores initialize
  if (!settingsLoaded || !authLoaded || !chatsLoaded) {
    return <BootSplash label="Wiii đang thức dậy..." />;
  }

  // Sprint 157: Show login screen when not authenticated
  if (!isAuthenticated) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<BootSplash label="Wiii đang mở cổng đăng nhập..." />}>
          <LoginScreen />
        </Suspense>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <Suspense fallback={<BootSplash label="Wiii đang mở không gian trò chuyện..." />}>
        <AppShell />
      </Suspense>
      <Suspense fallback={null}>
        <CommandPalette open={commandPaletteOpen} onClose={closeCommandPalette} />
      </Suspense>
    </ErrorBoundary>
  );
}
