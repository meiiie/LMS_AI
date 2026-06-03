/**
 * Settings page — modal overlay for app configuration.
 * Sections: Connection, User, Preferences, Memory, Context.
 * Sprint 105: Context tab + enhanced MemoryTab with search/filter/animation.
 * Sprint 106: Focus trap for accessibility.
 */
import { useState, useMemo, useEffect, useRef } from "react";
import {
  X,
  Server,
  User,
  Palette,
  Brain,
  Database,
  CheckCircle,
  AlertCircle,
  Loader2,
  Trash2,
  Search,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { motion } from "motion/react";
import { useSettingsStore } from "@/stores/settings-store";
import { useUIStore } from "@/stores/ui-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useMemoryStore, FACT_TYPE_LABELS } from "@/stores/memory-store";
import { useContextStore } from "@/stores/context-store";
import { useChatStore } from "@/stores/chat-store";
import { useToastStore } from "@/stores/toast-store";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import { staggerContainer, staggerItem } from "@/lib/animations";
import { formatTokens } from "@/lib/format";
import { initClient } from "@/api/client";
import { setTheme } from "@/lib/theme";
import { useOrgStore } from "@/stores/org-store";
import { useDomainStore } from "@/stores/domain-store";
import { useAuthStore } from "@/stores/auth-store";
import { getOrgDisplayName } from "@/lib/org-config";
import { PERSONAL_ORG_ID } from "@/lib/constants";
import {
  fetchConnectedWorkspaces,
  fetchIdentities,
  fetchProfile,
  unlinkIdentity,
} from "@/api/users";
import type {
  AppSettings,
  ConnectedWorkspace,
  UserIdentity,
  UserProfile,
} from "@/api/types";
import { OrgSettingsTab } from "./OrgSettingsTab";
import { LivingAgentPanel } from "@/components/living-agent/LivingAgentPanel";
import { LlmRuntimePolicyEditor } from "@/components/runtime/LlmRuntimePolicyEditor";
import { Building2, Heart } from "lucide-react";
import {
  clearGeminiApiKey,
  clearOllamaApiKey,
  clearOpenRouterApiKey,
  clearZhipuApiKey,
  storeFacebookCookie,
  loadFacebookCookie,
} from "@/lib/secure-token-storage";

type Tab =
  | "connection"
  | "profile"
  | "preferences"
  | "memory"
  | "context"
  | "organization"
  | "living-agent";

export function SettingsPage() {
  const { settings, updateSettings, resetSettings } = useSettingsStore();
  const { closeSettings } = useUIStore();
  const { checkHealth, status: connStatus } = useConnectionStore();

  const { addToast } = useToastStore();
  const { authMode, user: authUser } = useAuthStore();
  const { activeOrgId, isSystemAdmin, isOrgAdmin } = useOrgStore();
  const [activeTab, setActiveTab] = useState<Tab>("profile");
  const [testStatus, setTestStatus] = useState<
    "idle" | "testing" | "success" | "error"
  >("idle");
  const [testMessage, setTestMessage] = useState("");
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Auto-focus close button on mount (Sprint 110)
  useEffect(() => {
    if (dialogRef.current) {
      const firstFocusable = dialogRef.current.querySelector<HTMLElement>(
        'button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      firstFocusable?.focus();
    }
  }, []);

  // Focus trap + Escape to close (Sprint 106)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeSettings();
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [closeSettings]);

  // Local draft state for connection fields (commit on save)
  // Sprint 194b (H5): facebook_cookie loaded from secure storage, not settings
  const [draft, setDraft] = useState({
    server_url: settings.server_url,
    api_key: settings.api_key,
    facebook_cookie: "",
  });
  // Load facebook cookie from secure storage on mount
  useEffect(() => {
    loadFacebookCookie()
      .then((cookie) => {
        if (cookie) setDraft((d) => ({ ...d, facebook_cookie: cookie }));
      })
      .catch(() => {
        /* ignore */
      });
  }, []);

  const handleTestConnection = async () => {
    setTestStatus("testing");
    setTestMessage("");

    try {
      const authHeaders =
        authMode === "oauth"
          ? useSettingsStore.getState().getAuthHeaders()
          : {
              "X-API-Key": draft.api_key,
              "X-User-ID": settings.user_id,
              "X-Role": settings.user_role,
            };
      // Temporarily init client with draft values to test
      initClient(draft.server_url, authHeaders);

      await checkHealth();

      const currentStatus = useConnectionStore.getState().status;
      if (currentStatus === "connected") {
        setTestStatus("success");
        setTestMessage("Wiii nghe thấy bạn rồi!");
      } else {
        setTestStatus("error");
        setTestMessage(
          useConnectionStore.getState().errorMessage || "Không thể kết nối",
        );
      }
    } catch {
      setTestStatus("error");
      setTestMessage("Không thể kết nối đến server");
    }
  };

  const handleSaveConnection = async () => {
    // Sprint 194b (H5): Save facebook_cookie to secure storage, not settings
    if (draft.facebook_cookie) {
      try {
        await storeFacebookCookie(draft.facebook_cookie);
      } catch {
        /* ignore */
      }
    }
    await updateSettings({
      server_url: draft.server_url,
      api_key: draft.api_key,
    });

    // Re-init client with new settings
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

  const handleUpdateField = async <K extends keyof AppSettings>(
    key: K,
    value: AppSettings[K],
  ) => {
    await updateSettings({ [key]: value });

    // Apply theme immediately
    if (key === "theme") {
      setTheme(value as "light" | "dark" | "system");
    }

    // Re-init client if auth headers changed
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

  // Sprint 216: Progressive disclosure — dynamic tab visibility
  const isDeveloperMode = authMode === "legacy" || isSystemAdmin();
  const tabs = useMemo(() => {
    const result: { id: Tab; label: string; icon: React.ReactNode }[] = [
      { id: "profile", label: "Hồ sơ", icon: <User size={16} /> },
      { id: "preferences", label: "Tùy chỉnh", icon: <Palette size={16} /> },
      { id: "memory", label: "Trí nhớ", icon: <Brain size={16} /> },
      { id: "context", label: "Ngữ cảnh", icon: <Database size={16} /> },
    ];
    if (isDeveloperMode) {
      result.push({
        id: "connection",
        label: "Kết nối",
        icon: <Server size={16} />,
      });
    }
    if (activeOrgId && (isOrgAdmin() || isSystemAdmin())) {
      result.push({
        id: "organization",
        label: "Tổ chức",
        icon: <Building2 size={16} />,
      });
    }
    result.push({
      id: "living-agent",
      label: "Linh hồn",
      icon: <Heart size={16} />,
    });
    return result;
  }, [isDeveloperMode, activeOrgId]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <div
        ref={dialogRef}
        className="bg-surface rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col border border-border animate-scale-in"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2.5">
            <WiiiAvatar state="idle" size={22} />
            <h2 id="settings-title" className="text-lg font-semibold text-text">
              Cài đặt cho Wiii
            </h2>
          </div>
          <button
            onClick={closeSettings}
            className="p-1.5 rounded-lg hover:bg-surface-tertiary transition-colors text-text-secondary"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border px-5 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-3 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-[var(--accent)] text-[var(--accent)]"
                  : "border-transparent text-text-secondary hover:text-text"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {activeTab === "connection" && (
            <ConnectionTab
              draft={draft}
              setDraft={setDraft}
              testStatus={testStatus}
              testMessage={testMessage}
              connStatus={connStatus}
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

          {activeTab === "memory" && (
            <MemoryTab
              userId={
                authMode === "oauth" && authUser?.id
                  ? authUser.id
                  : // Legacy/dev mode: backend under ENVIRONMENT=production forces
                    // auth.user_id="api-client" for API-key auth, so match that on
                    // the client side to avoid a 403 ownership mismatch.
                    authMode === "legacy"
                    ? "api-client"
                    : settings.user_id
              }
            />
          )}

          {activeTab === "context" && <ContextTab />}
          {activeTab === "organization" && <OrgSettingsTab />}
          {activeTab === "living-agent" && <LivingAgentPanel />}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-5 py-3 border-t border-border">
          <button
            onClick={() => setShowResetConfirm(true)}
            className="text-sm text-text-tertiary hover:text-red-500 transition-colors"
          >
            Quên tất cả
          </button>
          <button
            onClick={closeSettings}
            className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] transition-colors"
          >
            Đóng
          </button>
        </div>

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
              const { clearFacebookCookie } =
                await import("@/lib/secure-token-storage");
              await clearFacebookCookie();
              await clearGeminiApiKey();
              await clearOpenRouterApiKey();
              await clearZhipuApiKey();
              await clearOllamaApiKey();
            } catch {
              /* ignore */
            }
            setDraft({
              server_url: "http://localhost:8080",
              // Phase 31 fix: don't seed a placeholder api_key. The
              // hardcoded "local-dev-key" never matched the backend's
              // .env API_KEY (≥16 chars required), so legacy fallback
              // would always 401. Empty string forces the user through
              // dev-login / magic-link / OAuth, which gives a real JWT.
              api_key: "",
              facebook_cookie: "",
            });
            setTheme("system");
            setShowResetConfirm(false);
            addToast("success", "Wiii bắt đầu lại. Cảm ơn vì đã quen mình!");
          }}
          onCancel={() => setShowResetConfirm(false)}
        />
      </div>
    </div>
  );
}

/* ===== Connection Tab ===== */
export interface ConnectionTabProps {
  draft: { server_url: string; api_key: string; facebook_cookie: string };
  setDraft: (d: {
    server_url: string;
    api_key: string;
    facebook_cookie: string;
  }) => void;
  testStatus: "idle" | "testing" | "success" | "error";
  testMessage: string;
  connStatus: string;
  onTest: () => void;
  onSave: () => void;
  // Sprint 216: Developer fields moved from Preferences tab
  settings?: AppSettings;
  onUpdate?: <K extends keyof AppSettings>(
    key: K,
    value: AppSettings[K],
  ) => void;
}

export function ConnectionTab({
  draft,
  setDraft,
  testStatus,
  testMessage,
  onTest,
  onSave,
  settings,
  onUpdate,
}: ConnectionTabProps) {
  const { addToast } = useToastStore();

  return (
    <div className="space-y-4">
      <FieldGroup label="Server URL">
        <input
          type="url"
          value={draft.server_url}
          onChange={(e) => setDraft({ ...draft, server_url: e.target.value })}
          placeholder="http://localhost:8080"
          className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
      </FieldGroup>

      <FieldGroup label="API Key">
        <input
          type="password"
          value={draft.api_key}
          onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
          placeholder="your-api-key"
          className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
      </FieldGroup>

      <FieldGroup
        label="Facebook Cookie"
        hint="Cho phep tim kiem trong hoi nhom Facebook. Lay tu DevTools > Application > Cookies."
      >
        <input
          type="password"
          value={draft.facebook_cookie}
          onChange={(e) =>
            setDraft({ ...draft, facebook_cookie: e.target.value })
          }
          placeholder="c_user=...; xs=...; datr=..."
          className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
      </FieldGroup>

      <div className="flex gap-3">
        <button
          onClick={onTest}
          disabled={testStatus === "testing"}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm font-medium hover:bg-surface-tertiary transition-colors disabled:opacity-50"
        >
          {testStatus === "testing" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : testStatus === "success" ? (
            <CheckCircle size={14} className="text-green-500" />
          ) : testStatus === "error" ? (
            <AlertCircle size={14} className="text-red-500" />
          ) : (
            <Server size={14} />
          )}
          Kiểm tra kết nối
        </button>
        <button
          onClick={onSave}
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] transition-colors"
        >
          Lưu
        </button>
      </div>

      {testMessage && (
        <div
          className={`flex items-center gap-2 p-3 rounded-lg text-sm ${
            testStatus === "success"
              ? "bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-300"
              : "bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300"
          }`}
        >
          {testStatus === "success" ? (
            <CheckCircle size={16} />
          ) : (
            <AlertCircle size={16} />
          )}
          {testMessage}
        </div>
      )}

      {settings && (
        <div className="mt-6 pt-4 border-t border-border">
          <LlmRuntimePolicyEditor
            variant="settings"
            onToast={(message, tone) => addToast(tone, message)}
          />
        </div>
      )}

      {settings && onUpdate && (
        <div className="mt-6 pt-4 border-t border-border">
          <div className="text-xs font-medium text-text-tertiary uppercase tracking-wider mb-3">
            Cong cu nha phat trien
          </div>

          <FieldGroup label="Streaming version">
            <div className="flex gap-2">
              {[
                { value: "v3" as const, label: "V3 (SSE)" },
                { value: "v2" as const, label: "V2" },
                { value: "v1" as const, label: "V1" },
              ].map((v) => (
                <button
                  key={v.value}
                  onClick={() => onUpdate("streaming_version", v.value)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    settings.streaming_version === v.value
                      ? "bg-[var(--accent)] text-white"
                      : "border border-border hover:bg-surface-tertiary text-text-secondary"
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </FieldGroup>

          <div className="mt-3">
            <ToggleField
              label="Hien thi reasoning trace"
              description="Xem chi tiet cac buoc xu ly"
              checked={settings.show_reasoning_trace}
              onChange={(v) => onUpdate("show_reasoning_trace", v)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/* ===== User Tab (Sprint 158: OAuth-aware) ===== */
export interface UserTabProps {
  settings: AppSettings;
  onUpdate: <K extends keyof AppSettings>(
    key: K,
    value: AppSettings[K],
  ) => void;
}

export function UserTab({ settings, onUpdate }: UserTabProps) {
  const {
    organizations,
    multiTenantEnabled,
    activeOrgId,
    setActiveOrg,
    orgRole,
  } = useOrgStore();
  // Sprint 218: Subscribe to `domains` so component re-renders after fetchDomains() completes
  const {
    domains: _domainList,
    getFilteredDomains,
    setOrgFilter,
  } = useDomainStore();
  const { updateSettings } = useSettingsStore();
  const { isAuthenticated, user, authMode, logout } = useAuthStore();
  const { addToast } = useToastStore();
  const filteredDomains = getFilteredDomains();
  const isOAuth = authMode === "oauth" && isAuthenticated && user;

  // Linked accounts state (OAuth mode only)
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [connectedWorkspaces, setConnectedWorkspaces] = useState<
    ConnectedWorkspace[]
  >([]);
  const [identities, setIdentities] = useState<UserIdentity[]>([]);
  const [identitiesLoading, setIdentitiesLoading] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [unlinkingId, setUnlinkingId] = useState<string | null>(null);

  useEffect(() => {
    if (!isOAuth) {
      setProfile(null);
      setConnectedWorkspaces([]);
      setIdentities([]);
      setProfileLoading(false);
      setIdentitiesLoading(false);
      return;
    }
    let cancelled = false;
    setProfileLoading(true);
    setIdentitiesLoading(true);
    Promise.allSettled([
      fetchProfile(),
      fetchConnectedWorkspaces(),
      fetchIdentities(),
    ])
      .then((results) => {
        if (cancelled) return;
        const [profileResult, workspaceResult, identitiesResult] = results;
        if (profileResult.status === "fulfilled") {
          setProfile(profileResult.value);
        }
        if (workspaceResult.status === "fulfilled") {
          setConnectedWorkspaces(workspaceResult.value);
        }
        if (identitiesResult.status === "fulfilled") {
          setIdentities(identitiesResult.value);
        }
      })
      .catch(() => {
        /* silent — non-critical */
      })
      .finally(() => {
        if (!cancelled) {
          setProfileLoading(false);
          setIdentitiesLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isOAuth]);

  const handleUnlink = async (identityId: string) => {
    setUnlinkingId(identityId);
    try {
      await unlinkIdentity(identityId);
      setIdentities((prev) => prev.filter((i) => i.id !== identityId));
      addToast("success", "Wiii đã hủy liên kết tài khoản");
    } catch {
      addToast("error", "Không thể hủy liên kết");
    } finally {
      setUnlinkingId(null);
    }
  };

  const handleLogout = async () => {
    await logout();
    addToast("success", "Đã đăng xuất");
  };

  const effectiveProfile = isOAuth ? profile : null;
  const identityBadge = (() => {
    if (!isOAuth) {
      const legacyRoleLabels: Record<string, string> = {
        admin: "Quản trị viên",
        teacher: "Giảng viên",
        student: "Người dùng",
      };
      return legacyRoleLabels[settings.user_role] || "Người dùng";
    }
    return effectiveProfile?.platform_role === "platform_admin"
      ? "Platform Admin"
      : "Wiii User";
  })();
  const orgMembershipLabel = (() => {
    const role = effectiveProfile?.organization_role || orgRole;
    if (!role) return null;
    const orgRoleLabels: Record<string, string> = {
      owner: "Chủ sở hữu tổ chức",
      org_admin: "Quản trị tổ chức",
      admin: "Quản trị tổ chức",
      member: "Thành viên tổ chức",
    };
    return orgRoleLabels[role] || "Thành viên tổ chức";
  })();
  const hostOverlayLabel = (() => {
    if (!isOAuth) return null;
    if (!effectiveProfile?.host_role) return null;
    const hostRoleLabels: Record<string, string> = {
      teacher: "Vai trò host: Giảng viên",
      student: "Vai trò host: Học viên",
      admin: "Vai trò host: Quản trị host",
      org_admin: "Vai trò host: Quản trị tổ chức host",
    };
    return (
      hostRoleLabels[effectiveProfile.host_role] ||
      `Vai trò host: ${effectiveProfile.host_role}`
    );
  })();

  const handleOrgChange = (orgId: string) => {
    const newOrgId = orgId === PERSONAL_ORG_ID ? null : orgId;
    setActiveOrg(newOrgId);
    updateSettings({ organization_id: newOrgId });
    const org = organizations.find((o) => o.id === orgId);
    setOrgFilter(org?.allowed_domains ?? []);
  };

  const PROVIDER_LABELS: Record<string, string> = {
    google: "Google",
    lms: "LMS",
    api_key: "API Key",
  };

  return (
    <div className="space-y-4">
      {/* Sprint 216: OAuth profile card with copy support ID + role badge */}
      {isOAuth && user && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-surface-secondary border border-border">
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              className="w-10 h-10 rounded-full"
            />
          ) : (
            <div className="w-10 h-10 rounded-full bg-[var(--accent-light)] flex items-center justify-center text-[var(--accent)] font-bold text-sm">
              {(user.name || user.email || "?")[0].toUpperCase()}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text truncate">
              {user.name || "Chưa đặt tên"}
            </div>
            <div className="text-xs text-text-tertiary truncate">
              {user.email}
            </div>
            {orgMembershipLabel && (
              <div className="text-[11px] text-text-tertiary truncate">
                {orgMembershipLabel}
                {activeOrgId ? ` • ${activeOrgId}` : ""}
              </div>
            )}
            {hostOverlayLabel && (
              <div className="text-[11px] text-text-tertiary truncate">
                {hostOverlayLabel}
              </div>
            )}
            {(effectiveProfile?.connected_workspaces_count ||
              connectedWorkspaces.length) > 0 && (
              <div className="text-[11px] text-text-tertiary truncate">
                {effectiveProfile?.connected_workspaces_count ||
                  connectedWorkspaces.length}{" "}
                không gian đã kết nối
              </div>
            )}
            <button
              onClick={() => {
                navigator.clipboard.writeText(user.id);
                addToast("success", "Đã sao chép mã hỗ trợ");
              }}
              className="text-[10px] text-text-tertiary hover:text-text-secondary transition-colors"
              title="Sao chép mã hỗ trợ"
            >
              Sao chép mã hỗ trợ
            </button>
          </div>
          <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
            {identityBadge}
          </span>
        </div>
      )}

      {/* Sprint 216: Legacy profile card (consistent with OAuth) */}
      {!isOAuth && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-surface-secondary border border-border">
          <div className="w-10 h-10 rounded-full bg-[var(--accent-light)] flex items-center justify-center text-[var(--accent)] font-bold text-sm">
            {(settings.display_name || "?")[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text truncate">
              {settings.display_name || "Người dùng"}
            </div>
            <button
              onClick={() => {
                navigator.clipboard.writeText(settings.user_id);
                addToast("success", "Đã sao chép mã hỗ trợ");
              }}
              className="text-[10px] text-text-tertiary hover:text-text-secondary transition-colors"
              title="Sao chép mã hỗ trợ"
            >
              Sao chép mã hỗ trợ
            </button>
          </div>
          <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
            {identityBadge}
          </span>
        </div>
      )}

      {/* Name field — editable in both modes */}
      <FieldGroup label="Tên hiển thị" hint="Bảo mình tên bạn để nhớ nhé">
        <input
          type="text"
          value={isOAuth && user ? user.name || "" : settings.display_name}
          onChange={(e) => onUpdate("display_name", e.target.value)}
          placeholder="Bạn tên gì?"
          className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
        />
      </FieldGroup>

      {/* OAuth mode: Linked accounts section */}
      {isOAuth && (
        <div>
          <div className="text-sm font-medium text-text-secondary mb-1.5">
            Không gian đã kết nối
          </div>
          {profileLoading ? (
            <div className="flex items-center gap-2 text-xs text-text-tertiary py-2">
              <Loader2 size={12} className="animate-spin" />
              Đang tải hồ sơ Wiii...
            </div>
          ) : connectedWorkspaces.length === 0 ? (
            <div className="text-xs text-text-tertiary py-2">
              Chưa có workspace/plugin nào được kết nối bền vững.
            </div>
          ) : (
            <div className="space-y-1.5 mb-4">
              {connectedWorkspaces.map((workspace) => (
                <div
                  key={workspace.id}
                  className="p-2 rounded-lg border border-border bg-surface-secondary"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-[var(--accent-light)] text-[var(--accent)]">
                      {(
                        workspace.host_name ||
                        workspace.connector_id ||
                        workspace.host_type
                      ).trim()}
                    </span>
                    <span className="text-[10px] text-text-tertiary uppercase tracking-wide">
                      {workspace.status}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {workspace.host_type}
                    {workspace.host_workspace_id
                      ? ` • ${workspace.host_workspace_id}`
                      : ""}
                  </div>
                  {workspace.last_used_at && (
                    <div className="text-[11px] text-text-tertiary">
                      Dùng gần nhất:{" "}
                      {new Date(workspace.last_used_at).toLocaleString("vi-VN")}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="text-sm font-medium text-text-secondary mb-1.5">
            Tài khoản liên kết
          </div>
          {identitiesLoading ? (
            <div className="flex items-center gap-2 text-xs text-text-tertiary py-2">
              <Loader2 size={12} className="animate-spin" />
              Đang tải...
            </div>
          ) : identities.length === 0 ? (
            <div className="text-xs text-text-tertiary py-2">
              Không có tài khoản liên kết
            </div>
          ) : (
            <div className="space-y-1.5">
              {identities.map((identity) => (
                <div
                  key={identity.id}
                  className="flex items-center gap-2 p-2 rounded-lg border border-border bg-surface-secondary"
                >
                  <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-[var(--accent-light)] text-[var(--accent)]">
                    {PROVIDER_LABELS[identity.provider] || identity.provider}
                  </span>
                  <span className="flex-1 text-xs text-text truncate">
                    {identity.email ||
                      identity.display_name ||
                      identity.provider_sub}
                  </span>
                  <button
                    onClick={() => handleUnlink(identity.id)}
                    disabled={
                      identities.length <= 1 || unlinkingId === identity.id
                    }
                    className="text-xs text-red-500 hover:text-red-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    title={
                      identities.length <= 1
                        ? "Không thể hủy tài khoản cuối cùng"
                        : "Hủy liên kết"
                    }
                  >
                    {unlinkingId === identity.id ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      "Hủy"
                    )}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sprint 156: Organization selector (only when multi-tenant) */}
      {multiTenantEnabled && organizations.length > 1 && (
        <FieldGroup
          label="Không gian làm việc"
          hint="Chọn tổ chức bạn thuộc về"
        >
          <select
            value={activeOrgId || PERSONAL_ORG_ID}
            onChange={(e) => handleOrgChange(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {getOrgDisplayName(org)}
              </option>
            ))}
          </select>
        </FieldGroup>
      )}

      {/* Sprint 215: Domain → "Lĩnh vực kiến thức" + auto-select when single */}
      <FieldGroup
        label="Lĩnh vực kiến thức"
        hint="Wiii sẽ ưu tiên tra cứu lĩnh vực này"
      >
        {filteredDomains.length === 1 ? (
          <div className="w-full px-3 py-2 rounded-lg border border-border bg-surface-tertiary text-text text-sm">
            {filteredDomains[0].name_vi || filteredDomains[0].name}
            <span className="block text-xs text-text-tertiary mt-0.5">
              Tự động — chỉ có 1 lĩnh vực khả dụng
            </span>
          </div>
        ) : filteredDomains.length > 1 ? (
          <select
            value={settings.default_domain}
            onChange={(e) => onUpdate("default_domain", e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          >
            {filteredDomains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name_vi || d.name}
              </option>
            ))}
          </select>
        ) : (
          <div className="w-full px-3 py-2 rounded-lg border border-border bg-surface-tertiary text-text-tertiary text-sm">
            Chưa có lĩnh vực
          </div>
        )}
      </FieldGroup>

      {/* Sprint 193: Logout button — visible for all auth modes */}
      <button
        onClick={handleLogout}
        className="w-full px-4 py-2 rounded-lg border border-red-300 dark:border-red-800 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
      >
        Đăng xuất
      </button>
    </div>
  );
}

/* ===== Preferences Tab ===== */
export interface PreferencesTabProps {
  settings: AppSettings;
  onUpdate: <K extends keyof AppSettings>(
    key: K,
    value: AppSettings[K],
  ) => void;
}

export function PreferencesTab({ settings, onUpdate }: PreferencesTabProps) {
  const themes: { value: "light" | "dark" | "system"; label: string }[] = [
    { value: "light", label: "Sáng" },
    { value: "dark", label: "Tối" },
    { value: "system", label: "Hệ thống" },
  ];

  return (
    <div className="space-y-4">
      <FieldGroup label="Giao diện">
        <div className="flex gap-2">
          {themes.map((t) => (
            <button
              key={t.value}
              onClick={() => onUpdate("theme", t.value)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                settings.theme === t.value
                  ? "bg-[var(--accent)] text-white"
                  : "border border-border hover:bg-surface-tertiary text-text-secondary"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </FieldGroup>

      <ToggleField
        label="Hiển thị suy luận"
        description="Xem quá trình suy nghĩ của Wiii"
        checked={settings.show_thinking}
        onChange={(v) => onUpdate("show_thinking", v)}
      />

      {/* Sprint 140: Thinking Level Control */}
      {settings.show_thinking && (
        <FieldGroup label="Mức độ hiển thị suy nghĩ">
          <div className="flex gap-2">
            {[
              {
                value: "minimal" as const,
                label: "Tối giản",
                desc: "Chỉ hiện tiến trình",
              },
              {
                value: "balanced" as const,
                label: "Cân bằng",
                desc: "Thu gọn suy nghĩ",
              },
              {
                value: "detailed" as const,
                label: "Chi tiết",
                desc: "Mở rộng tất cả",
              },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => onUpdate("thinking_level", opt.value)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs text-center transition-all ${
                  settings.thinking_level === opt.value
                    ? "bg-[var(--accent)] text-white"
                    : "bg-[var(--surface-tertiary)] text-text-secondary hover:bg-[var(--border)]"
                }`}
                title={opt.desc}
              >
                <div className="font-medium">{opt.label}</div>
                <div
                  className={`mt-0.5 text-[10px] ${
                    settings.thinking_level === opt.value
                      ? "text-white/80"
                      : "text-text-tertiary"
                  }`}
                >
                  {opt.desc}
                </div>
              </button>
            ))}
          </div>
        </FieldGroup>
      )}

      {/* Sprint 166: Preview Cards Toggle */}
      <ToggleField
        label="Xem trước nội dung"
        description="Hiển thị thẻ xem trước cho tài liệu, sản phẩm, và liên kết"
        checked={settings.show_previews !== false}
        onChange={(v) => onUpdate("show_previews", v)}
      />

      {/* Sprint 167: Artifacts toggle */}
      <ToggleField
        label="Không gian sáng tạo"
        description="Hiển thị artifact tương tác (code, HTML, bảng dữ liệu) với khả năng thực thi"
        checked={settings.show_artifacts !== false}
        onChange={(v) => onUpdate("show_artifacts", v)}
      />
    </div>
  );
}

/* ===== Memory Tab (Sprint 80, enhanced Sprint 105, Sprint 219: category grouping) ===== */

/** Sprint 219: Category groups for organized memory display */
export const MEMORY_CATEGORIES: {
  id: string;
  label: string;
  types: string[];
}[] = [
  {
    id: "identity",
    label: "Bản thân",
    types: [
      "name",
      "age",
      "location",
      "hometown",
      "organization",
      "role",
      "pronoun_style",
    ],
  },
  {
    id: "learning",
    label: "Học tập",
    types: ["learning_style", "level", "strength", "weakness", "goal"],
  },
  {
    id: "personal",
    label: "Sở thích",
    types: ["hobby", "interest", "preference", "emotion", "recent_topic"],
  },
];

/** Render a memory value in a human-readable way.
 * Some types (e.g. pronoun_style) store a JSON object as their value. */
function formatMemoryValue(type: string, value: string): string {
  if (type === "pronoun_style") {
    try {
      const p = JSON.parse(value) as Record<string, string>;
      const parts: string[] = [];
      if (p.user_called) parts.push(`Wiii gọi bạn: "${p.user_called}"`);
      if (p.ai_self) parts.push(`Wiii tự xưng: "${p.ai_self}"`);
      if (p.user_self) parts.push(`Bạn tự xưng: "${p.user_self}"`);
      return parts.length > 0 ? parts.join(" · ") : value;
    } catch {
      return value;
    }
  }
  return value;
}

export function MemoryTab({ userId }: { userId: string }) {
  const {
    memories,
    memorySummary,
    isLoading,
    error,
    fetchMemories,
    deleteOne,
    clearAll,
  } = useMemoryStore();
  const { addToast } = useToastStore();
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState<string | null>(null);
  const [collapsedCategories, setCollapsedCategories] = useState<
    Record<string, boolean>
  >({});

  // Fetch on mount and whenever userId changes
  useEffect(() => {
    if (userId) fetchMemories(userId);
  }, [userId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Compute type counts for filter chips
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const mem of memories) {
      counts[mem.type] = (counts[mem.type] || 0) + 1;
    }
    return counts;
  }, [memories]);

  // Filter memories by search + type
  const filteredMemories = useMemo(() => {
    let result = memories;
    if (filterType) {
      result = result.filter((m) => m.type === filterType);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (m) =>
          m.value.toLowerCase().includes(q) ||
          (FACT_TYPE_LABELS[m.type] || m.type).toLowerCase().includes(q),
      );
    }
    return result;
  }, [memories, filterType, searchQuery]);

  // Sprint 219: Group filtered memories by category
  const groupedMemories = useMemo(() => {
    const categorizedTypes = new Set(MEMORY_CATEGORIES.flatMap((c) => c.types));
    const groups: {
      id: string;
      label: string;
      items: typeof filteredMemories;
    }[] = [];

    for (const cat of MEMORY_CATEGORIES) {
      const items = filteredMemories.filter((m) => cat.types.includes(m.type));
      if (items.length > 0) {
        groups.push({ id: cat.id, label: cat.label, items });
      }
    }

    // Uncategorized items
    const uncategorized = filteredMemories.filter(
      (m) => !categorizedTypes.has(m.type),
    );
    if (uncategorized.length > 0) {
      groups.push({ id: "other", label: "Khác", items: uncategorized });
    }

    return groups;
  }, [filteredMemories]);

  const handleClearAll = async () => {
    await clearAll(userId);
    setShowClearConfirm(false);
    addToast("success", "Wiii quên hết rồi, bắt đầu lại nha!");
  };

  const handleDeleteOne = async (memoryId: string) => {
    await deleteOne(userId, memoryId);
    addToast("success", "Wiii đã quên điều này");
  };

  const toggleCategory = (categoryId: string) => {
    setCollapsedCategories((prev) => ({
      ...prev,
      [categoryId]: !prev[categoryId],
    }));
  };

  const uniqueTypes = Object.keys(typeCounts).sort();
  const summaryTypeCount = memorySummary
    ? Object.keys(memorySummary.type_counts).length
    : uniqueTypes.length;
  const latestMemoryLabel = memorySummary?.latest_created_at
    ? new Date(memorySummary.latest_created_at).toLocaleDateString("vi-VN", {
        day: "numeric",
        month: "numeric",
        year: "numeric",
      })
    : "Chưa có";
  const scopeLabel = memorySummary?.org_scoped ? "Theo tổ chức" : "Cá nhân";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-text">
            Wiii nhớ gì về bạn
          </div>
          <div className="text-xs text-text-tertiary">
            Mình ghi nhớ để hiểu bạn hơn
          </div>
        </div>
        {memories.length > 0 && (
          <button
            onClick={() => setShowClearConfirm(true)}
            disabled={isLoading}
            className="text-xs text-red-500 hover:text-red-700 transition-colors disabled:opacity-50"
          >
            Xóa tất cả
          </button>
        )}
      </div>

      {memorySummary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-lg border border-border bg-surface-secondary px-3 py-2">
            <div className="text-[10px] font-medium uppercase text-text-tertiary">
              Tổng
            </div>
            <div className="text-sm font-semibold text-text">
              {memorySummary.total}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-surface-secondary px-3 py-2">
            <div className="text-[10px] font-medium uppercase text-text-tertiary">
              Loại
            </div>
            <div className="text-sm font-semibold text-text">
              {summaryTypeCount}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-surface-secondary px-3 py-2">
            <div className="text-[10px] font-medium uppercase text-text-tertiary">
              Gần nhất
            </div>
            <div className="truncate text-sm font-semibold text-text">
              {latestMemoryLabel}
            </div>
          </div>
          <div className="rounded-lg border border-border bg-surface-secondary px-3 py-2">
            <div className="text-[10px] font-medium uppercase text-text-tertiary">
              Phạm vi
            </div>
            <div className="truncate text-sm font-semibold text-text">
              {scopeLabel}
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={showClearConfirm}
        title="Xóa tất cả bộ nhớ?"
        message="Wiii sẽ quên tất cả thông tin đã ghi nhận về bạn. Bạn không thể hoàn tác."
        confirmLabel="Xóa tất cả"
        cancelLabel="Hủy"
        variant="danger"
        onConfirm={handleClearAll}
        onCancel={() => setShowClearConfirm(false)}
      />

      {/* Search input */}
      {memories.length > 0 && (
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Tìm kiếm..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
          />
        </div>
      )}

      {/* Type filter chips */}
      {uniqueTypes.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setFilterType(null)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
              filterType === null
                ? "bg-[var(--accent)] text-white"
                : "bg-surface-tertiary text-text-secondary hover:text-text"
            }`}
          >
            Tất cả ({memories.length})
          </button>
          {uniqueTypes.map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(filterType === type ? null : type)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                filterType === type
                  ? "bg-[var(--accent)] text-white"
                  : "bg-surface-tertiary text-text-secondary hover:text-text"
              }`}
            >
              {FACT_TYPE_LABELS[type] || type} ({typeCounts[type]})
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="text-xs text-red-500 p-2 rounded-lg bg-red-50 dark:bg-red-950/30">
          {error}
        </div>
      )}

      {isLoading && memories.length === 0 ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-text-tertiary" />
        </div>
      ) : memories.length === 0 ? (
        <div className="text-center text-text-tertiary text-xs py-8">
          Mình chưa nhớ gì về bạn. Kể cho Wiii nghe nhé!
        </div>
      ) : filteredMemories.length === 0 ? (
        <div className="text-center text-text-tertiary text-xs py-8">
          Không tìm thấy kết quả.
        </div>
      ) : (
        <div className="space-y-3">
          {groupedMemories.map((group) => (
            <div
              key={group.id}
              className="rounded-lg border border-border overflow-hidden"
            >
              {/* Category header — collapsible */}
              <button
                onClick={() => toggleCategory(group.id)}
                className="flex items-center justify-between w-full px-3 py-2 bg-surface-secondary hover:bg-surface-tertiary transition-colors"
              >
                <div className="flex items-center gap-2">
                  {collapsedCategories[group.id] ? (
                    <ChevronRight size={14} className="text-text-tertiary" />
                  ) : (
                    <ChevronDown size={14} className="text-text-tertiary" />
                  )}
                  <span className="text-sm font-medium text-text">
                    {group.label}
                  </span>
                </div>
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
                  {group.items.length}
                </span>
              </button>

              {/* Category items */}
              {!collapsedCategories[group.id] && (
                <motion.div
                  variants={staggerContainer}
                  initial="hidden"
                  animate="visible"
                  className="divide-y divide-border"
                >
                  {group.items.map((mem) => (
                    <motion.div
                      key={mem.id}
                      variants={staggerItem}
                      className="flex items-center gap-3 px-3 py-2 group"
                    >
                      <span className="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-[var(--accent-light)] text-[var(--accent)]">
                        {FACT_TYPE_LABELS[mem.type] || mem.type}
                      </span>
                      <span className="flex-1 text-sm text-text truncate">
                        {formatMemoryValue(mem.type, mem.value)}
                      </span>
                      <span className="shrink-0 text-[10px] text-text-tertiary">
                        {new Date(mem.created_at).toLocaleDateString("vi-VN", {
                          day: "numeric",
                          month: "numeric",
                        })}
                      </span>
                      <button
                        onClick={() => handleDeleteOne(mem.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 hover:text-red-600 transition-all"
                        title="Xóa"
                        aria-label="Xóa thông tin này"
                      >
                        <Trash2 size={12} />
                      </button>
                    </motion.div>
                  ))}
                </motion.div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ===== Context Tab (Sprint 105) ===== */
export function ContextTab() {
  const { info, status, isLoading, error, fetchContextInfo, compact, clear } =
    useContextStore();
  const activeConv = useChatStore((s) => s.activeConversation());
  const sessionId = activeConv?.session_id || activeConv?.id || "";
  const { addToast } = useToastStore();
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  // Fetch on mount — Sprint 165: useEffect to avoid setState during render
  useEffect(() => {
    if (sessionId) fetchContextInfo(sessionId);
  }, [sessionId]);

  const utilization = info ? Math.round(info.utilization ?? 0) : 0;
  const totalBudget = info?.total_budget ?? 0;
  const totalUsed = info?.total_used ?? 0;

  const STATUS_BAR_COLORS: Record<string, string> = {
    unknown: "bg-gray-300",
    green: "bg-green-500",
    yellow: "bg-yellow-500",
    orange: "bg-orange-500",
    red: "bg-red-500",
  };

  const handleCompact = async () => {
    await compact(sessionId);
    addToast("success", "Wiii tóm tắt xong rồi!");
  };

  const handleClear = async () => {
    await clear(sessionId);
    setShowClearConfirm(false);
    addToast("success", "Wiii quên cuộc trò chuyện này rồi");
  };

  if (!sessionId) {
    return (
      <div className="text-center text-text-tertiary text-xs py-8">
        Chưa có cuộc trò chuyện nào. Bắt đầu nói chuyện với Wiii nha!
      </div>
    );
  }

  if (isLoading && !info) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={20} className="animate-spin text-text-tertiary" />
      </div>
    );
  }

  if (!info) {
    return (
      <div className="text-center text-text-tertiary text-xs py-8">
        Không thể tải thông tin ngữ cảnh.
        {error && <div className="text-red-500 mt-1">{error}</div>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm font-medium text-text">Bộ nhớ hội thoại</div>
        <div className="text-xs text-text-tertiary">
          Mình đang theo dõi cuộc trò chuyện này
        </div>
      </div>

      {/* Utilization bar */}
      <div>
        <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
          <span>Sử dụng: {utilization}%</span>
          <span>
            {formatTokens(totalUsed)}/{formatTokens(totalBudget)} tokens
          </span>
        </div>
        <div className="w-full h-3 bg-surface-tertiary rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${STATUS_BAR_COLORS[status]}`}
            style={{ width: `${Math.min(utilization, 100)}%` }}
          />
        </div>
      </div>

      {/* Layer breakdown */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-text-secondary">
          Phân bổ bộ nhớ
        </div>
        {info.layers && (
          <div className="space-y-1.5">
            <LayerBar
              label="Cấu hình hệ thống"
              layer={info.layers.system_prompt}
            />
            <LayerBar
              label="Kiến thức về bạn"
              layer={info.layers.core_memory}
            />
            <LayerBar label="Tóm tắt" layer={info.layers.summary} />
            <LayerBar label="Tin nhắn" layer={info.layers.recent_messages} />
          </div>
        )}
      </div>

      {/* Message stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Bao gồm" value={info.messages_included} />
        <StatCard label="Bị bỏ" value={info.messages_dropped} />
        <StatCard label="Tổng" value={info.total_history_messages} />
      </div>

      {/* Summary info */}
      <div className="text-xs text-text-secondary">
        Tóm tắt:{" "}
        {info.has_summary ? `${info.running_summary_chars} ký tự` : "Chưa có"}
      </div>

      {error && (
        <div className="text-xs text-red-500 p-2 rounded-lg bg-red-50 dark:bg-red-950/30">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleCompact}
          disabled={isLoading || !sessionId}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-border text-sm font-medium hover:bg-surface-tertiary transition-colors disabled:opacity-50"
        >
          {isLoading && <Loader2 size={14} className="animate-spin" />}
          Tóm tắt ngay
        </button>
        <button
          onClick={() => setShowClearConfirm(true)}
          disabled={isLoading || !sessionId}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-red-300 dark:border-red-800 text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors disabled:opacity-50"
        >
          Xóa ngữ cảnh
        </button>
      </div>

      <ConfirmDialog
        open={showClearConfirm}
        title="Xóa ngữ cảnh hội thoại?"
        message="Tất cả lịch sử hội thoại và tóm tắt sẽ bị xóa. Bạn không thể hoàn tác."
        confirmLabel="Xóa ngữ cảnh"
        cancelLabel="Hủy"
        variant="danger"
        onConfirm={handleClear}
        onCancel={() => setShowClearConfirm(false)}
      />
    </div>
  );
}

/* ===== Context Tab helpers ===== */
export function LayerBar({
  label,
  layer,
}: {
  label: string;
  layer: { budget: number; used: number };
}) {
  const pct =
    layer.budget > 0 ? Math.round((layer.used / layer.budget) * 100) : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-text-secondary mb-0.5">
        <span>{label}</span>
        <span>
          {formatTokens(layer.used)}/{formatTokens(layer.budget)}
        </span>
      </div>
      <div className="w-full h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
        <div
          className="h-full rounded-full bg-[var(--accent)] transition-all duration-300"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-2 rounded-lg bg-surface-secondary border border-border text-center">
      <div className="text-lg font-semibold text-text">{value}</div>
      <div className="text-[10px] text-text-tertiary">{label}</div>
    </div>
  );
}

/* ===== Shared UI primitives ===== */
export function FieldGroup({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-1.5">
        {label}
      </label>
      {hint && (
        <div className="text-[11px] text-text-tertiary -mt-0.5 mb-1.5">
          {hint}
        </div>
      )}
      {children}
    </div>
  );
}

export function ToggleField({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <div>
        <div className="text-sm font-medium text-text">{label}</div>
        <div className="text-xs text-text-tertiary">{description}</div>
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          checked ? "bg-[var(--accent)]" : "bg-gray-300 dark:bg-gray-600"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}
