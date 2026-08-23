/** App version */
export const APP_VERSION = "1.2.0";

/** App name */
export const APP_NAME = "Wiii";

function isLocalBrowserHost(): boolean {
  if (typeof window === "undefined") return false;
  const { hostname } = window.location;
  return hostname === "localhost" || hostname === "127.0.0.1";
}

/** Default server URL — localhost in dev, same-origin in production web builds.
 *  Docker Compose exposes the backend via nginx on :8080 (app FastAPI :8000 is
 *  internal-only when nginx is up). When testing the dev compose stack directly
 *  (no nginx), set ``VITE_API_URL=http://localhost:8000`` in ``wiii-desktop/.env``
 *  to override. */
export const DEFAULT_SERVER_URL = (() => {
  const envOverride =
    typeof import.meta !== "undefined"
      ? (import.meta.env?.VITE_API_URL as string | undefined)
      : undefined;
  if (envOverride) return envOverride;
  if (
    (typeof import.meta !== "undefined" && import.meta.env?.DEV) ||
    isLocalBrowserHost()
  ) {
    return "http://localhost:8000";
  }
  if (
    typeof window !== "undefined" &&
    "__TAURI_INTERNALS__" in window
  ) {
    // A packaged Tauri page is served from tauri.localhost, not from Wiii's
    // API. First launch must ask for a real endpoint instead of silently
    // sending requests to the WebView origin.
    return "";
  }
  return typeof window !== "undefined" ? window.location.origin : "";
})();

/** Default user settings */
// Sprint 194b: DEFAULT_USER_ID removed — anonymous UUID generated at runtime
export const DEFAULT_USER_ROLE = "student" as const;
export const DEFAULT_DISPLAY_NAME = "User";
export const DEFAULT_DOMAIN = "maritime";
export const DEFAULT_LANGUAGE = "vi" as const;

/** Health check interval (ms) */
export const HEALTH_CHECK_INTERVAL = 30_000;

/** SSE streaming version */
export const DEFAULT_STREAMING_VERSION = "v3" as const;

/** Maximum message length */
export const MAX_MESSAGE_LENGTH = 10_000;

/** Context info polling interval (ms) — Sprint 80 */
export const CONTEXT_POLL_INTERVAL = 30_000;

/** Sprint 156: Personal workspace org ID (no multi-tenant) */
export const PERSONAL_ORG_ID = "personal";
