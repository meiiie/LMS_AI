/**
 * EmbedApp — Stripped-down App for iframe embed.
 * Sprint 176: Wiii Chat Embed for LMS iframe integration.
 *
 * Removed vs App.tsx:
 * - AppShell, Sidebar, TitleBar, StatusBar
 * - SettingsPage, CommandPalette, LoginScreen
 * - useKeyboardShortcuts (avoid conflicts with parent)
 * - AvatarPreview dev tool
 * - detectSubdomainOrg (not needed in embed)
 *
 * Init flow:
 * 1. parseEmbedConfig() from URL hash
 * 2. Validate config (show error if invalid)
 * 3. Initialize settings, auth, org, domain stores
 * 4. initClient() with proper headers
 * 5. Render <ChatView /> directly (no shell)
 * 6. sendReadySignal() to parent
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { ChatView } from "@/components/chat/ChatView";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { ToastContainer } from "@/components/common/Toast";
import { useSettingsStore } from "@/stores/settings-store";
import { useAuthStore } from "@/stores/auth-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useContextStore } from "@/stores/context-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { useChatStore } from "@/stores/chat-store";
import { initClient } from "@/api/client";
import "@/lib/context-bridge";
import { parseEmbedConfig, validateEmbedConfig, getAuthMode } from "@/lib/embed-auth";
import { sendReadySignal, sendError, setParentOrigin } from "@/lib/embed-bridge";
import { buildAuthUserFromJwt, toCompatibilitySettingsRole } from "@/lib/auth-user";
import type { EmbedConfig } from "@/lib/embed-auth";

const PreviewPanel = lazy(async () => {
  const mod = await import("@/components/layout/PreviewPanel");
  return { default: mod.PreviewPanel };
});

export default function EmbedApp() {
  const [embedConfig, setEmbedConfig] = useState<EmbedConfig | null>(null);
  const [initError, setInitError] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);

  const { updateSettings } = useSettingsStore();
  const { setLegacyMode, loginWithTokens } = useAuthStore();
  const { startPolling, stopPolling } = useConnectionStore();
  const { startPolling: startContextPolling, stopPolling: stopContextPolling } = useContextStore();
  const { fetchDomains, setActiveDomain, setOrgFilter } = useDomainStore();
  const { fetchOrganizations, setActiveOrg, fetchAdminContext } = useOrgStore();
  const { loadConversations } = useChatStore();

  // Step 1: Parse config on mount
  useEffect(() => {
    const config = parseEmbedConfig();
    const error = validateEmbedConfig(config);

    if (error) {
      setInitError(error);
      sendError("AUTH_MISSING", error);
      return;
    }

    setEmbedConfig(config);

    // Sprint 194b (C3): Set parent origin for secure postMessage
    // Sprint 194c (D2): Only use config.server as fallback if HTTPS (production)
    // Priority: explicit parent_origin config → document.referrer → HTTPS server URL
    const serverOrigin = config.server
      ? (() => {
          try {
            const u = new URL(config.server!);
            return u.protocol === "https:" ? u.origin : null;
          } catch {
            return null;
          }
        })()
      : null;
    const parentOrigin = (config as any).parent_origin
      || (document.referrer ? new URL(document.referrer).origin : null)
      || serverOrigin;
    if (parentOrigin) {
      setParentOrigin(parentOrigin);
    }

    // Store config globally for storage.ts namespace
    (window as any).__WIII_EMBED_CONFIG__ = config;

    // Sprint 220c: Widget mode — set data attribute for CSS overrides
    if (config.mode === "widget" || config.hide_welcome) {
      document.documentElement.setAttribute("data-embed-mode", "widget");
    }
  }, []);

  // Step 2: Initialize stores when config is parsed
  useEffect(() => {
    if (!embedConfig) return;

    async function initialize(config: EmbedConfig) {
      try {
        // 2a. Settings — server URL, user info, org, domain
        const serverUrl = config.server || window.location.origin;
        const settingsUpdate: Record<string, any> = {
          server_url: serverUrl,
        };

        if (config.org) settingsUpdate.organization_id = config.org;
        if (config.domain) settingsUpdate.default_domain = config.domain;
        if (config.theme) settingsUpdate.theme = config.theme;
        if (config.role) settingsUpdate.user_role = config.role;

        const authMode = getAuthMode(config);

        if (authMode === "legacy") {
          settingsUpdate.api_key = config.api_key;
          settingsUpdate.user_id = config.user_id;
        }

        await updateSettings(settingsUpdate);

        // 2b. Auth — JWT or legacy mode
        if (authMode === "jwt" && config.token) {
          const user = buildAuthUserFromJwt(config.token);
          const embedRole =
            typeof config.role === "string" && config.role.trim()
              ? config.role.trim()
              : user.host_role || user.legacy_role || user.role;
          await updateSettings({
            user_role: toCompatibilitySettingsRole({
              role: embedRole,
              legacy_role: embedRole,
            }),
          });
          // Set user_id in settings so useSSEStream sends correct user_id in chat body
          // Also update global config so storage.ts getEmbedPrefix() can namespace per-user
          if (user.id) {
            await updateSettings({ user_id: user.id });
            (window as any).__WIII_EMBED_CONFIG__.user_id = user.id;
          }
          await loginWithTokens(
            config.token,
            config.refresh_token || "",
            3600, // Default 1h expiry
            user
          );
        } else {
          await setLegacyMode();
        }

        // 2c. Load persisted conversations (with user-switch detection)
        // Sprint 226: Detect user change — if new JWT has different user_id,
        // switch to that user's conversation store to prevent cross-user leakage.
        // __WIII_EMBED_PREV_USER_ID__ persists across iframe hash changes (same origin).
        const prevUserId = (window as any).__WIII_EMBED_PREV_USER_ID__ as string | undefined;
        const newUserId = useSettingsStore.getState().settings.user_id;
        if (prevUserId && newUserId && prevUserId !== newUserId) {
          await useChatStore.getState().switchUser(newUserId);
        } else {
          await loadConversations();
        }
        if (newUserId) {
          (window as any).__WIII_EMBED_PREV_USER_ID__ = newUserId;
        }

        // Sprint 220c: Session resumption — match by session_id from embed config
        if (config.session_id) {
          const chatState = useChatStore.getState();
          const match = chatState.conversations.find(
            (c) => c.session_id === config.session_id,
          );
          if (match) {
            chatState.setActiveConversation(match.id);
          }
        }

        // 2d. Initialize HTTP client
        const headers: Record<string, string> = {};

        if (authMode === "jwt" && config.token) {
          headers["Authorization"] = `Bearer ${config.token}`;
        } else {
          headers["X-API-Key"] = config.api_key || "";
          headers["X-User-ID"] = config.user_id || "";
          headers["X-Role"] = config.role || "student";
        }

        if (config.org) {
          headers["X-Organization-ID"] = config.org;
        }

        initClient(serverUrl, headers);

        // 2e. Fetch domains and orgs
        fetchDomains();
        if (config.domain) {
          setActiveDomain(config.domain);
        }

        if (config.org) {
          fetchOrganizations().then(() => {
            setActiveOrg(config.org!);
            const org = useOrgStore.getState().organizations.find((o) => o.id === config.org);
            if (org) {
              setOrgFilter(org.allowed_domains);
            }
          });
        }

        // Sprint 226 local: fetch admin context so the Sidebar's
        // "Hệ Quản Trị" / "Quản Lý Tổ Chức" buttons appear for admin JWTs
        // inside the iframe embed too.
        if (authMode === "jwt") {
          fetchAdminContext();
        }

        // 2f. Start health polling
        startPolling();

        setIsReady(true);

        // 2g. Signal parent
        sendReadySignal();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Initialization failed";
        setInitError(msg);
        sendError("INIT_FAILED", msg);
      }
    }

    initialize(embedConfig);

    return () => {
      stopPolling();
    };
  }, [embedConfig]); // eslint-disable-line react-hooks/exhaustive-deps

  // Action PostMessages that need app state (clear-chat) — gated by isReady
  useEffect(() => {
    if (!isReady) return;

    const actionHandler = (event: MessageEvent) => {
      const msgType = event.data?.type;
      if (msgType !== 'wiii:clear-chat') return;

      // Create new conversation — old one stays in history
      const chatState = useChatStore.getState();
      const domain = useDomainStore.getState().activeDomainId || embedConfig?.domain;
      const org = embedConfig?.org;
      chatState.createConversation(domain, org);

      // Reply to parent
      if (event.source && event.origin) {
        (event.source as Window).postMessage(
          { type: 'wiii:chat-cleared' },
          event.origin
        );
      }
    };

    window.addEventListener('message', actionHandler);
    return () => window.removeEventListener('message', actionHandler);
  }, [isReady, embedConfig]);

  // Context polling for active conversation
  const activeConv = useChatStore((s) => s.activeConversation());
  const sessionId = activeConv?.session_id || activeConv?.id || "";
  useEffect(() => {
    if (sessionId && isReady) {
      startContextPolling(sessionId);
    }
    return () => {
      stopContextPolling();
    };
  }, [sessionId, isReady, startContextPolling, stopContextPolling]);

  // Auto-refresh JWT (same as App.tsx)
  const { authMode, isAuthenticated, isTokenExpiringSoon, refreshAccessToken } = useAuthStore();
  useEffect(() => {
    if (authMode !== "oauth" || !isAuthenticated) return;
    const interval = setInterval(() => {
      if (isTokenExpiringSoon()) {
        const serverUrl = embedConfig?.server || window.location.origin;
        refreshAccessToken(serverUrl);
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [authMode, isAuthenticated, isTokenExpiringSoon, refreshAccessToken, embedConfig?.server]);

  // Error state
  if (initError) {
    return (
      <div className="flex items-center justify-center h-screen bg-surface p-4">
        <div className="text-center max-w-md">
          <p className="text-lg font-semibold text-red-600 mb-2">Wiii Embed Error</p>
          <p className="text-sm text-text-secondary">{initError}</p>
        </div>
      </div>
    );
  }

  // Loading state
  if (!isReady) {
    return (
      <div className="flex items-center justify-center h-screen bg-surface">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-text-tertiary">Wiii...</span>
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <div className="h-screen w-full overflow-hidden">
        <ChatView />
        <Suspense fallback={null}>
          <PreviewPanel />
        </Suspense>
      </div>
      <ToastContainer />
    </ErrorBoundary>
  );
}
