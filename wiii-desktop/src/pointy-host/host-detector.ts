/**
 * Host environment detector (Wiii Pointy v3.0 — Phase F1).
 *
 * Distinguishes the runtime context Wiii is running in so the agent
 * prompt can describe the user's actual surface accurately, KHÔNG
 * hallucinate "trang LMS" khi user đang ở standalone Wiii desktop.
 *
 * Detection signals (in priority order):
 *
 * 1. **Iframe parent** — if `window.parent !== window`, we're embedded
 *    in another page (LMS / partner app / preview). The parent is
 *    treated as the host and we report `host_type=lms` until the LMS
 *    pushes its own richer context (Sprint 222 host bridge).
 *
 * 2. **URL hostname** — `localhost` / `127.0.0.1` / `*.local` →
 *    standalone dev; otherwise we publish the actual hostname so the
 *    AI knows the real domain (e.g., `wiii.holilihu.online`).
 *
 * 3. **URL path** — `/chat`, `/`, `/?preview=pointy` → page_type
 *    inferred from route. Heuristic only; the agent receives the raw
 *    URL too so it can decide.
 *
 * Output is consumed by ``mountPointyAwareness`` in
 * ``pointy-host/integration.ts`` and published into HostContextStore;
 * backend `_inject_host_context` reads it from chat-request body.
 */

export interface HostEnvironment {
  /** "wiii-desktop" (standalone) | "lms" (iframe parent) | "wiii-web" (web SPA at remote URL) */
  host_type: string;
  /** Display name surfaced in agent prompt. */
  host_name: string;
  /** True when running standalone (not embedded). */
  is_standalone: boolean;
  /** True when running inside another page's iframe. */
  is_embedded: boolean;
  /** Full URL of current page. */
  page_url: string;
  /** Page route hint — "chat" | "demo" | "settings" | "unknown". */
  page_type: string;
  /** Page title — usually `<title>` from document. */
  page_title: string;
  /** Hostname (e.g., "localhost", "wiii.holilihu.online"). */
  hostname: string;
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
const WIII_PRODUCTION_HOSTS = ["wiii.holilihu.online"]; // resurrect-ready

export function detectHostEnvironment(): HostEnvironment {
  if (typeof window === "undefined") {
    // SSR / test fallback.
    return {
      host_type: "wiii-desktop",
      host_name: "Wiii Desktop",
      is_standalone: true,
      is_embedded: false,
      page_url: "",
      page_type: "unknown",
      page_title: "",
      hostname: "",
    };
  }

  const hostname = window.location.hostname;
  const pathname = window.location.pathname || "/";
  const search = window.location.search || "";
  const url = window.location.href;
  const title = typeof document !== "undefined" ? document.title : "";

  const isLocal = LOCAL_HOSTS.has(hostname) || hostname.endsWith(".local");
  const isProduction = WIII_PRODUCTION_HOSTS.includes(hostname);
  const isEmbedded = window.parent !== window;

  // Iframe parent = embedded in another app (LMS most common).
  if (isEmbedded) {
    return {
      host_type: "lms",
      host_name: "LMS Maritime (embedded)",
      is_standalone: false,
      is_embedded: true,
      page_url: url,
      page_type: inferPageType(pathname, search),
      page_title: title,
      hostname,
    };
  }

  // Standalone (top window). Differentiate dev vs production.
  if (isLocal) {
    return {
      host_type: "wiii-desktop",
      host_name: "Wiii Desktop (localhost dev)",
      is_standalone: true,
      is_embedded: false,
      page_url: url,
      page_type: inferPageType(pathname, search),
      page_title: title,
      hostname,
    };
  }

  if (isProduction) {
    return {
      host_type: "wiii-web",
      host_name: "Wiii Web",
      is_standalone: true,
      is_embedded: false,
      page_url: url,
      page_type: inferPageType(pathname, search),
      page_title: title,
      hostname,
    };
  }

  // Unknown remote hostname — Wiii running somewhere we haven't classified.
  return {
    host_type: "wiii-web",
    host_name: `Wiii Web (${hostname})`,
    is_standalone: true,
    is_embedded: false,
    page_url: url,
    page_type: inferPageType(pathname, search),
    page_title: title,
    hostname,
  };
}

function inferPageType(pathname: string, search: string): string {
  if (search.includes("preview=pointy")) return "demo";
  if (pathname === "/" || pathname.startsWith("/chat")) return "chat";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/embed")) return "embed";
  return "unknown";
}

/** True when this Wiii instance is the standalone desktop / web app
 * (NOT embedded inside a host page). Use this gate to skip iframe-host
 * code paths (PostMessage host actions, etc.) that would silently
 * timeout when there's no parent. */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return true;
  return window.parent === window;
}
