/**
 * LoginScreen — Google OAuth + Magic Link email login for Wiii Desktop.
 * Sprint 157: "Đăng Nhập"
 * Sprint 224: Magic link email login flow (secondary option)
 *
 * Shows a centered login card with Google OAuth button (primary),
 * email magic link login (secondary), and developer mode toggle.
 */
import { useState, useEffect, useRef } from "react";
import { useSettingsStore } from "@/stores/settings-store";
import { useAuthStore } from "@/stores/auth-store";
import type { AuthUser } from "@/stores/auth-store";
import type { AppSettings } from "@/api/types";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import {
  buildAuthUserFromPayload,
  toCompatibilitySettingsRole,
} from "@/lib/auth-user";
import { DEFAULT_SERVER_URL } from "@/lib/constants";

// Dynamic import that bypasses Vite static analysis (plugin may not be installed)
const _oauthMod = "@fabianlars/tauri-plugin-oauth";
function loadOAuth(): Promise<{
  start: (opts: { ports: number[] }) => Promise<number>;
  onUrl: (cb: (url: string) => void) => void;
  cancel: (port: number) => Promise<void>;
}> {
  return import(/* @vite-ignore */ _oauthMod) as Promise<any>;
}

export function resolveDevModeSettingsPatch(
  settings: Pick<AppSettings, "server_url" | "api_key" | "user_role">,
  hostname: string,
): Partial<AppSettings> {
  const isLocalBrowser = hostname === "localhost" || hostname === "127.0.0.1";
  const patch: Partial<AppSettings> = {};

  if (!settings.server_url && isLocalBrowser) {
    patch.server_url = DEFAULT_SERVER_URL || "http://localhost:8080";
  }

  if (
    isLocalBrowser &&
    settings.api_key === "local-dev-key" &&
    (!settings.user_role || settings.user_role === "student")
  ) {
    patch.user_role = "admin";
  }

  return patch;
}

export function LoginScreen() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDevMode, setShowDevMode] = useState(false);
  const { settings, updateSettings } = useSettingsStore();
  const { loginWithTokens, setLegacyMode } = useAuthStore();

  // Sprint 224: Magic link email login state
  const [emailValue, setEmailValue] = useState("");
  const [emailState, setEmailState] = useState<"idle" | "waiting">("idle");
  const [resendCooldown, setResendCooldown] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);

  // Sprint 193: Detect Tauri vs browser environment
  const isTauri = !!(window as any).__TAURI_INTERNALS__;

  // Issue #88: One-click dev login on localhost. Probe the backend's
  // /auth/dev-login/status (public, unauthenticated) on mount and only show
  // the button when both the host is localhost AND the backend opts in.
  // The probe runs once per mount, so a misconfigured remote backend cannot
  // surprise-render the button.
  const [devLoginEnabled, setDevLoginEnabled] = useState(false);
  useEffect(() => {
    const isLocalHost =
      typeof window !== "undefined" &&
      (window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1");
    if (!isLocalHost || !settings.server_url) {
      setDevLoginEnabled(false);
      return;
    }
    let cancelled = false;
    fetch(`${settings.server_url}/api/v1/auth/dev-login/status`)
      .then((res) => (res.ok ? res.json() : { enabled: false }))
      .then((data) => {
        if (!cancelled) setDevLoginEnabled(Boolean(data?.enabled));
      })
      .catch(() => {
        if (!cancelled) setDevLoginEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, [settings.server_url]);

  const handleGoogleLogin = async () => {
    setError(null);
    setIsLoading(true);

    try {
      // Security: validate server URL scheme before redirect
      try {
        const serverUrl = new URL(settings.server_url);
        if (!["http:", "https:"].includes(serverUrl.protocol)) {
          throw new Error("URL server không hợp lệ");
        }
      } catch {
        setError(
          "URL server không hợp lệ. Vui lòng kiểm tra Cài đặt → Kết nối.",
        );
        setIsLoading(false);
        return;
      }

      // Sprint 193: Web browser flow — redirect with hash-based token delivery
      // Security: use URL constructor to prevent query parameter injection
      if (!isTauri) {
        const loginUrlObj = new URL(
          "/api/v1/auth/google/login",
          settings.server_url,
        );
        loginUrlObj.searchParams.set("redirect_uri", window.location.origin);
        window.location.href = loginUrlObj.toString();
        return; // Page will navigate away — no finally needed
      }

      // Tauri desktop flow — tauri-plugin-oauth localhost port
      let port: number;
      try {
        const oauth = await loadOAuth();
        port = await oauth.start({ ports: [8765, 8766, 8767, 8768, 8769] });
      } catch {
        // Fallback: use a fixed port if plugin not available
        port = 8765;
      }

      // Open system browser to backend OAuth login
      const loginUrlObj = new URL(
        "/api/v1/auth/google/login",
        settings.server_url,
      );
      loginUrlObj.searchParams.set("port", String(port));
      const loginUrl = loginUrlObj.toString();

      try {
        const { open } = await import("@tauri-apps/plugin-shell");
        await open(loginUrl);
      } catch {
        // Browser fallback: use window.open
        window.open(loginUrl, "_blank");
      }

      // Wait for callback from the OAuth redirect to localhost
      // The tauri-plugin-oauth will capture the URL
      try {
        const oauth = await loadOAuth();
        const callbackUrl = await new Promise<string>((resolve, reject) => {
          const timeout = setTimeout(
            () =>
              reject(
                new Error(
                  "Hết thời gian chờ Google phản hồi. Vui lòng thử lại.",
                ),
              ),
            60000,
          );
          oauth.onUrl((url: string) => {
            clearTimeout(timeout);
            resolve(url);
          });
        });

        // Sprint 160b: Parse tokens from URL fragment (#) with fallback to query (?)
        // Fragments are never sent to the server — prevents token leakage to logs/proxies.
        const url = new URL(callbackUrl);
        const params = url.hash
          ? new URLSearchParams(url.hash.substring(1))
          : url.searchParams; // backward compat with pre-160b backends
        const accessToken = params.get("access_token");
        const refreshToken = params.get("refresh_token");
        const expiresIn = parseInt(params.get("expires_in") || "1800", 10);
        const userId = params.get("user_id") || "";
        const email = params.get("email") || "";
        const name = params.get("name") || "";
        const avatarUrl = params.get("avatar_url") || "";

        if (!accessToken || !refreshToken) {
          throw new Error(
            "Không nhận được thông tin đăng nhập từ Google. Vui lòng thử lại.",
          );
        }

        const user: AuthUser = buildAuthUserFromPayload({
          user_id: userId,
          email,
          name,
          avatar_url: avatarUrl,
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
        await loginWithTokens(accessToken, refreshToken, expiresIn, user);

        // Sync user info to settings
        await updateSettings({
          user_id: userId,
          display_name: name || email,
          user_role: toCompatibilitySettingsRole(user),
        });

        await oauth.cancel(port);
      } catch (oauthErr) {
        // If tauri-plugin-oauth isn't available, show manual instructions
        throw new Error(
          "Không thể nhận callback từ Google. Vui lòng thử lại hoặc dùng Developer Mode.",
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại");
    } finally {
      setIsLoading(false);
    }
  };

  // Issue #88: One-click local dev login. Calls /auth/dev-login, pipes
  // the response straight into the existing OAuth-style storage flow.
  const handleDevLogin = async () => {
    setError(null);
    setIsLoading(true);
    try {
      const res = await fetch(`${settings.server_url}/api/v1/auth/dev-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || `Dev login thất bại (${res.status})`);
      }
      const data = await res.json();
      const user: AuthUser = buildAuthUserFromPayload({
        user_id: data.user.id,
        email: data.user.email || "",
        name: data.user.name || "",
        avatar_url: data.user.avatar_url || "",
        role: data.user.role || "admin",
        legacy_role: data.user.legacy_role || "admin",
        platform_role: data.user.platform_role || "platform_admin",
        organization_role: data.user.organization_role || "",
        host_role: data.user.host_role || "",
        role_source: data.user.role_source || "platform",
        active_organization_id: data.user.active_organization_id || "",
        organization_id: data.organization_id || "",
        connector_id: "",
        identity_version: "2",
      });
      await loginWithTokens(
        data.access_token,
        data.refresh_token,
        data.expires_in,
        user,
      );
      await updateSettings({
        user_id: data.user.id,
        display_name: data.user.name || data.user.email || "Dev User",
        user_role: toCompatibilitySettingsRole(user),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dev login thất bại");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDevModeActivate = async () => {
    // Sprint 192: Save API key to secure store
    try {
      const { storeApiKey } = await import("@/lib/secure-token-storage");
      if (settings.api_key) {
        await storeApiKey(settings.api_key);
      }
    } catch {
      // Non-critical — API key stays in settings only
    }
    const localDevPatch = resolveDevModeSettingsPatch(
      settings,
      typeof window !== "undefined" ? window.location.hostname : "",
    );
    // Sprint 226 local fix: backend under ENVIRONMENT=production forces
    // auth.user_id="api-client" for API-key auth regardless of X-User-ID.
    // Align local settings.user_id so ownership-checked endpoints
    // (/memories/{user_id}, /insights/{user_id}, ...) match and don't 403.
    localDevPatch.user_id = "api-client";
    await updateSettings(localDevPatch);
    await setLegacyMode();
  };

  // Sprint 224: Magic link email login handler
  const handleEmailLogin = async () => {
    setError(null);
    setIsLoading(true);
    try {
      const res = await fetch(
        `${settings.server_url}/api/v1/auth/magic-link/request`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: emailValue.trim().toLowerCase() }),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Không thể gửi magic link");
      }
      const data = await res.json();
      setEmailState("waiting");
      setResendCooldown(45);

      // Close any existing WebSocket before opening a new one
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      // Connect WebSocket to listen for auth completion
      const wsUrl =
        settings.server_url.replace(/^http/, "ws") +
        `/api/v1/auth/magic-link/ws/${data.session_id}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // Dev convenience: when backend indicates Resend is a placeholder, it
      // returns the verify URL directly. Auto-open it after the WS is ready so
      // the magic link flow completes without waiting for an email.
      if (data.dev_verify_url) {
        ws.addEventListener(
          "open",
          () => {
            window.open(data.dev_verify_url, "_blank", "noopener,noreferrer");
          },
          { once: true },
        );
      }

      ws.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "auth_success") {
            const user: AuthUser = buildAuthUserFromPayload({
              ...msg.user,
              avatar_url: msg.user?.avatar_url || "",
            });
            await loginWithTokens(
              msg.access_token,
              msg.refresh_token,
              msg.expires_in,
              user,
            );
            await updateSettings({
              user_id: msg.user.id,
              display_name: msg.user.name || msg.user.email,
              user_role: toCompatibilitySettingsRole(user),
            });
          } else if (msg.type === "timeout") {
            setError("Phiên đăng nhập đã hết hạn. Vui lòng thử lại.");
            setEmailState("idle");
          }
        } catch (e) {
          console.error("WS message parse error:", e);
        }
      };

      ws.onerror = () => {
        setError("Mất kết nối. Vui lòng thử lại.");
        setEmailState("idle");
      };

      ws.onclose = () => {
        // Session ended (either success or timeout)
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại");
    } finally {
      setIsLoading(false);
    }
  };

  // Sprint 224: Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  // Sprint 224: Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  return (
    <div
      className="flex flex-col items-center h-screen pt-[10vh]"
      style={{
        background:
          "linear-gradient(180deg, var(--surface) 0%, var(--surface-secondary) 100%)",
      }}
      aria-busy={isLoading}
    >
      <div className="w-full max-w-[360px] mx-auto flex flex-col items-center px-6">
        {/* Wiii avatar */}
        <div className="mb-5">
          <WiiiAvatar state="idle" size={64} />
        </div>

        {/* Title */}
        <h1
          className="text-[32px] font-normal text-text text-center leading-tight"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          Chào mừng đến Wiii
        </h1>
        <p className="mt-2 mb-7 text-[15px] text-text-tertiary text-center">
          Trợ lý AI thông minh cho học tập và nghiên cứu
        </p>

        {/* Issue #88: One-click local dev login. Visible only when running
            on localhost AND the backend has enable_dev_login=true. Styled
            distinctively (dashed accent border + "DEV" badge) so it is
            unmistakably a development shortcut, not a production path. */}
        {devLoginEnabled && (
          <button
            data-testid="dev-login-button"
            onClick={handleDevLogin}
            disabled={isLoading}
            className="w-full mb-3 flex items-center justify-center gap-2 h-[44px] px-5 rounded-2xl border-2 border-dashed border-[var(--accent)] bg-[var(--accent)]/5 text-[14px] font-semibold text-[var(--accent)] hover:bg-[var(--accent)]/10 active:scale-[0.97] transition-all disabled:opacity-50"
          >
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[var(--accent)] text-white tracking-wider">
              DEV
            </span>
            <span>Đăng nhập nhanh — Local Dev</span>
          </button>
        )}

        {/* Google login button — primary CTA */}
        <button
          onClick={handleGoogleLogin}
          disabled={isLoading}
          className="w-full flex items-center justify-center gap-3 h-[48px] px-6 rounded-2xl bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-600 text-[15px] font-semibold text-gray-700 dark:text-gray-200 hover:border-gray-300 hover:shadow-lg active:scale-[0.97] transition-all disabled:opacity-50 shadow-md"
        >
          {isLoading ? (
            <div className="w-5 h-5 border-2 border-gray-300 dark:border-gray-600 border-t-gray-600 dark:border-t-gray-300 rounded-full animate-spin" />
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
          )}
          <span>
            {isLoading ? "Đang đăng nhập..." : "Đăng nhập với Google"}
          </span>
        </button>

        {/* Error message */}
        {error && (
          <div
            role="alert"
            aria-live="assertive"
            className="w-full p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300"
          >
            {error}
          </div>
        )}

        {/* Divider */}
        <div className="w-full flex items-center gap-3 my-2">
          <div className="flex-1 h-px bg-border" />
          <span className="text-[11px] text-text-quaternary">hoặc</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* Sprint 224: Magic link email login */}
        {emailState === "idle" ? (
          <div className="w-full flex flex-col gap-2.5">
            <label
              htmlFor="magic-link-email"
              className="text-xs font-medium text-text-tertiary"
            >
              Đăng nhập bằng email
            </label>
            <input
              id="magic-link-email"
              type="email"
              placeholder="you@example.com"
              value={emailValue}
              onChange={(e) => setEmailValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && emailValue.includes("@")) {
                  handleEmailLogin();
                }
              }}
              className="w-full h-[44px] px-4 rounded-xl bg-surface border border-border text-[15px] text-text placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-all"
            />
            <button
              onClick={handleEmailLogin}
              disabled={isLoading || !emailValue.includes("@")}
              className="w-full h-[44px] rounded-2xl bg-[var(--accent)] text-[15px] text-white font-semibold hover:opacity-90 active:scale-[0.97] transition-all disabled:opacity-35 shadow-sm"
            >
              {isLoading ? "Đang gửi..." : "Tiếp tục"}
            </button>
          </div>
        ) : (
          <div
            className="w-full flex flex-col items-center gap-3 py-2"
            aria-live="polite"
          >
            <div className="text-2xl">✉️</div>
            <p className="text-sm font-medium text-text text-center">
              Kiểm tra email của bạn
            </p>
            <p className="text-xs text-text-tertiary text-center">
              Chúng tôi đã gửi link đăng nhập đến{" "}
              <span className="font-medium text-text-secondary">
                {emailValue.trim().toLowerCase()}
              </span>
            </p>
            <div className="flex items-center gap-3 mt-1">
              <button
                onClick={handleEmailLogin}
                disabled={resendCooldown > 0 || isLoading}
                className="text-xs text-[var(--accent)] hover:opacity-80 transition-opacity disabled:opacity-50"
              >
                {resendCooldown > 0
                  ? `Gửi lại (${resendCooldown}s)`
                  : "Gửi lại"}
              </button>
              <span className="text-text-tertiary">·</span>
              <button
                onClick={() => {
                  setEmailState("idle");
                  setError(null);
                  if (wsRef.current) {
                    wsRef.current.close();
                    wsRef.current = null;
                  }
                }}
                className="text-xs text-text-tertiary hover:text-text-secondary transition-colors"
              >
                ← Quay lại
              </button>
            </div>
          </div>
        )}

        {/* Developer mode toggle */}
        {!showDevMode ? (
          <button
            onClick={() => setShowDevMode(true)}
            className="mt-3 text-[10px] text-text-quaternary hover:text-text-tertiary transition-colors"
          >
            Chế độ nhà phát triển
          </button>
        ) : (
          <div className="w-full flex flex-col gap-3">
            <p className="text-xs text-text-tertiary text-center">
              Dành cho nhà phát triển — nhập Khóa API thủ công
            </p>
            <input
              aria-label="Khóa API"
              type="password"
              placeholder="Khóa API"
              value={settings.api_key}
              onChange={(e) => updateSettings({ api_key: e.target.value })}
              className="w-full h-9 px-3 rounded-lg bg-surface-secondary border border-border text-sm text-text placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            />
            <button
              onClick={handleDevModeActivate}
              disabled={!settings.api_key}
              className="w-full h-9 rounded-lg bg-surface-tertiary text-sm text-text-secondary hover:bg-surface-secondary transition-colors disabled:opacity-50"
            >
              Tiếp tục với Khóa API
            </button>
          </div>
        )}

        {/* Footer — Terms & Privacy */}
        <div className="text-center mt-8 space-y-1.5">
          <p className="text-[11px] text-text-tertiary leading-relaxed">
            Bằng việc tiếp tục, bạn đồng ý với{" "}
            <a
              href="/terms.html"
              target="_blank"
              rel="noopener"
              className="underline underline-offset-2 hover:text-text-secondary transition-colors"
            >
              Điều khoản sử dụng
            </a>{" "}
            và{" "}
            <a
              href="/privacy.html"
              target="_blank"
              rel="noopener"
              className="underline underline-offset-2 hover:text-text-secondary transition-colors"
            >
              Chính sách bảo mật
            </a>
          </p>
          <p className="text-[10px] text-text-quaternary">by The Wiii Lab</p>
        </div>
      </div>
    </div>
  );
}
