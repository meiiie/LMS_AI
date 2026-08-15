/**
 * SettingsView — Sprint 192: Full-page settings.
 * Sprint 216: Progressive disclosure — dynamic tab visibility, label renames.
 *
 * Replaces SettingsPage modal. Reuses all existing tab sub-components
 * from SettingsPage inside the FullPageView layout.
 */
import { useState, useMemo, useEffect } from "react";
import {
  Server,
  User,
  Palette,
  Brain,
  Database,
  Building2,
  Heart,
  Settings,
} from "lucide-react";
import { useSettingsStore } from "@/stores/settings-store";
import { useUIStore } from "@/stores/ui-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useToastStore } from "@/stores/toast-store";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { FullPageView } from "@/components/layout/FullPageView";
import type { FullPageTab } from "@/components/layout/FullPageView";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import {
  ConnectionTab,
  UserTab,
  PreferencesTab,
  MemoryTab,
  ContextTab,
} from "./SettingsPage";
import { OrgSettingsTab } from "./OrgSettingsTab";
import { LivingAgentPanel } from "@/components/living-agent/LivingAgentPanel";
import { initClient } from "@/api/client";
import { setTheme } from "@/lib/theme";
import {
  clearGeminiApiKey,
  clearOllamaApiKey,
  clearOpenRouterApiKey,
  storeFacebookCookie,
  loadFacebookCookie,
} from "@/lib/secure-token-storage";
import type { AppSettings } from "@/api/types";

type SettingsTab = "connection" | "profile" | "preferences" | "memory" | "context" | "organization" | "living-agent";

export function SettingsView() {
  const { settings, updateSettings, resetSettings } = useSettingsStore();
  const { navigateToChat } = useUIStore();
  const { checkHealth } = useConnectionStore();
  const { addToast } = useToastStore();
  const { authMode, user: authUser } = useAuthStore();
  const { activeOrgId, isSystemAdmin, isOrgAdmin } = useOrgStore();

  // Sprint 216: Progressive disclosure — hide developer/admin tabs from regular users
  const isDeveloperMode = authMode === "legacy" || isSystemAdmin();
  const hasOrgAdminAccess = isOrgAdmin() || isSystemAdmin();

  const visibleTabs = useMemo(() => {
    const tabs: (FullPageTab & { id: SettingsTab })[] = [
      { id: "profile", label: "Hồ sơ", icon: <User size={16} /> },
      { id: "preferences", label: "Tùy chỉnh", icon: <Palette size={16} /> },
      { id: "memory", label: "Trí nhớ", icon: <Brain size={16} /> },
      { id: "context", label: "Ngữ cảnh", icon: <Database size={16} /> },
    ];
    if (isDeveloperMode) {
      tabs.push({ id: "connection", label: "Kết nối", icon: <Server size={16} /> });
    }
    if (activeOrgId && hasOrgAdminAccess) {
      tabs.push({ id: "organization", label: "Tổ chức", icon: <Building2 size={16} /> });
    }
    tabs.push({ id: "living-agent", label: "Linh hồn", icon: <Heart size={16} /> });
    return tabs;
  }, [isDeveloperMode, activeOrgId, hasOrgAdminAccess]);

  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  // Sprint 216: If current tab becomes hidden, fallback to profile
  useEffect(() => {
    if (!visibleTabs.some((t) => t.id === activeTab)) {
      setActiveTab("profile");
    }
  }, [visibleTabs, activeTab]);
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "success" | "error">("idle");
  const [testMessage, setTestMessage] = useState("");
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  // Sprint 194b (H5): facebook_cookie loaded from secure storage, not settings
  const [draft, setDraft] = useState({
    server_url: settings.server_url,
    api_key: settings.api_key,
    facebook_cookie: "",
  });
  useEffect(() => {
    loadFacebookCookie().then((cookie) => {
      if (cookie) setDraft((d) => ({ ...d, facebook_cookie: cookie }));
    }).catch(() => { /* ignore */ });
  }, []);

  const handleTestConnection = async () => {
    setTestStatus("testing");
    setTestMessage("");
    try {
      initClient(
        draft.server_url,
        authMode === "oauth"
          ? useSettingsStore.getState().getAuthHeaders()
          : {
              "X-API-Key": draft.api_key,
              "X-User-ID": settings.user_id,
              "X-Role": settings.user_role,
            },
      );
      await checkHealth();
      const currentStatus = useConnectionStore.getState().status;
      if (currentStatus === "connected") {
        setTestStatus("success");
        setTestMessage("Wiii nghe thấy bạn rồi!");
      } else {
        setTestStatus("error");
        setTestMessage(useConnectionStore.getState().errorMessage || "Không thể kết nối");
      }
    } catch {
      setTestStatus("error");
      setTestMessage("Không thể kết nối đến server");
    }
  };

  const handleSaveConnection = async () => {
    // Sprint 194b (H5): Save facebook_cookie to secure storage
    if (draft.facebook_cookie) {
      try { await storeFacebookCookie(draft.facebook_cookie); } catch { /* ignore */ }
    }
    await updateSettings({
      server_url: draft.server_url,
      api_key: draft.api_key,
    });
    initClient(
      draft.server_url,
      authMode === "oauth"
        ? useSettingsStore.getState().getAuthHeaders()
        : {
            "X-API-Key": draft.api_key,
            "X-User-ID": settings.user_id,
            "X-Role": settings.user_role,
          },
    );
    checkHealth();
    addToast("success", "Wiii ghi nhớ cài đặt rồi!");
  };

  const handleUpdateField = async <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    await updateSettings({ [key]: value });
    if (key === "theme") setTheme(value as "light" | "dark" | "system");
    if (key === "user_id" || key === "user_role") {
      const updated = useSettingsStore.getState().settings;
      initClient(
        updated.server_url,
        authMode === "oauth"
          ? useSettingsStore.getState().getAuthHeaders()
          : {
              "X-API-Key": updated.api_key,
              "X-User-ID": updated.user_id,
              "X-Role": updated.user_role,
            },
      );
    }
    addToast("success", "Wiii nhớ rồi!");
  };

  return (
    <>
      <FullPageView
        title="Cài đặt"
        icon={<Settings size={20} />}
        tabs={visibleTabs}
        activeTab={activeTab}
        onTabChange={(id) => setActiveTab(id as SettingsTab)}
        onClose={navigateToChat}
        footer={
          <button
            onClick={() => setShowResetConfirm(true)}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors mb-1"
          >
            Quên tất cả
          </button>
        }
      >
        {activeTab === "connection" && (
          <ConnectionTab
            draft={draft}
            setDraft={setDraft}
            testStatus={testStatus}
            testMessage={testMessage}
            connStatus={useConnectionStore.getState().status}
            onTest={handleTestConnection}
            onSave={handleSaveConnection}
            settings={settings}
            onUpdate={handleUpdateField}
          />
        )}
        {activeTab === "profile" && (
          <UserTab settings={settings} onUpdate={handleUpdateField} />
        )}
        {activeTab === "preferences" && (
          <PreferencesTab settings={settings} onUpdate={handleUpdateField} />
        )}
        {activeTab === "memory" && <MemoryTab userId={authMode === "oauth" && authUser?.id ? authUser.id : settings.user_id} />}
        {activeTab === "context" && <ContextTab />}
        {activeTab === "organization" && <OrgSettingsTab />}
        {activeTab === "living-agent" && <LivingAgentPanel />}
      </FullPageView>

      <ConfirmDialog
        open={showResetConfirm}
        title="Wiii sẽ quên bạn?"
        message="Mọi cài đặt sẽ trở về mặc định. Wiii bắt đầu lại từ đầu. Bạn chắc chắn chứ?"
        confirmLabel="Quên tất cả"
        cancelLabel="Thôi, giữ lại"
        variant="danger"
        onConfirm={async () => {
          await resetSettings();
          // Sprint 194b (H5): Clear facebook cookie from secure storage
          try {
            const { clearFacebookCookie } = await import("@/lib/secure-token-storage");
            await clearFacebookCookie();
            await clearGeminiApiKey();
            await clearOpenRouterApiKey();
            await clearOllamaApiKey();
          } catch { /* ignore */ }
          setDraft({
            server_url: "http://localhost:8000",
            // Phase 31 fix: same as SettingsPage. The "local-dev-key"
            // placeholder never matched the backend's .env API_KEY, so
            // legacy fallback would always 401. Empty string forces the
            // user through dev-login / magic-link / OAuth.
            api_key: "",
            facebook_cookie: "",
          });
          setTheme("system");
          setShowResetConfirm(false);
          addToast("success", "Wiii bắt đầu lại. Cảm ơn vì đã quen mình!");
        }}
        onCancel={() => setShowResetConfirm(false)}
      />
    </>
  );
}
