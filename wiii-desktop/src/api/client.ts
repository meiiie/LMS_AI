/**
 * HTTP client for Wiii backend API.
 *
 * Uses @tauri-apps/plugin-http to bypass CORS when running in Tauri.
 * Falls back to native browser fetch when running in a regular browser.
 */
import { DEFAULT_SERVER_URL } from "@/lib/constants";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Default request timeout in milliseconds (60 seconds) */
export const DEFAULT_TIMEOUT_MS = 60_000;

export class ApiHttpError extends Error {
  status: number;
  body: Record<string, unknown> | null;

  constructor(
    message: string,
    status: number,
    body: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiHttpError";
    this.status = status;
    this.body = body;
  }
}

export interface AuthRecoveryContext {
  status: number;
  detail: string;
  body: Record<string, unknown> | null;
}

const RECOVERABLE_AUTH_403_MARKERS = [
  "active organization does not match authenticated organization",
  "authenticated token does not carry an active organization",
  "organization context required for chat request scope",
  "user is not a member of organization",
];

function detailFromParsedBody(body: Record<string, unknown> | null): string {
  if (!body) return "";
  if (typeof body.message === "string") return body.message;
  if (typeof body.detail === "string") return body.detail;
  if (body.detail) return JSON.stringify(body.detail);
  return "";
}

/**
 * Adaptive fetch — uses Tauri plugin-http in Tauri, native fetch in browser.
 * Sprint 85: Adds configurable timeout via AbortController.
 */
async function adaptiveFetch(
  url: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  // Sprint 85: Timeout via AbortController — prevents hung requests
  const controller = new AbortController();
  const existingSignal = init?.signal;

  // Merge with any existing abort signal
  if (existingSignal) {
    existingSignal.addEventListener("abort", () =>
      controller.abort(existingSignal.reason),
    );
  }
  const timeoutId = setTimeout(
    () => controller.abort("Request timeout"),
    timeoutMs,
  );

  try {
    const fetchInit: RequestInit = { ...init, signal: controller.signal };
    if (isTauri) {
      try {
        const { fetch: tauriFetch } = await import("@tauri-apps/plugin-http");
        return await tauriFetch(url, fetchInit);
      } catch {
        // Fallback if plugin fails to load
        return await fetch(url, fetchInit);
      }
    }
    return await fetch(url, fetchInit);
  } finally {
    clearTimeout(timeoutId);
  }
}

export class WiiiClient {
  private baseUrl: string;
  private headers: Record<string, string>;
  private headerResolver?: () => Record<string, string>;
  private onUnauthorized?: (context?: AuthRecoveryContext) => Promise<boolean>;

  constructor(baseUrl: string, headers: Record<string, string> = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, ""); // Remove trailing slash
    this.headers = headers;
  }

  /** Update authentication headers (static — prefer setHeaderResolver for dynamic) */
  setHeaders(headers: Record<string, string>) {
    this.headers = headers;
  }

  /** Sprint 192: Set dynamic header resolver — called before each request */
  setHeaderResolver(resolver: () => Record<string, string>) {
    this.headerResolver = resolver;
  }

  /** Sprint 192/231: Set auth recovery handler for token refresh or clean logout. */
  setOnUnauthorized(handler: (context?: AuthRecoveryContext) => Promise<boolean>) {
    this.onUnauthorized = handler;
  }

  /** Update base URL */
  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/+$/, "");
  }

  /** Resolve current headers — dynamic resolver takes priority */
  private resolveHeaders(): Record<string, string> {
    return this.headerResolver ? this.headerResolver() : this.headers;
  }

  /** Sprint 213: Extract detailed error message from backend response body */
  private async _throwApiError(response: Response): Promise<never> {
    let detail = response.statusText;
    let parsedBody: Record<string, unknown> | null = null;
    try {
      const body = await response.json();
      if (body && typeof body === "object" && !Array.isArray(body)) {
        parsedBody = body as Record<string, unknown>;
      }
      if (
        typeof parsedBody?.message === "string" &&
        parsedBody.message.trim()
      ) {
        detail = parsedBody.message;
      } else if (
        typeof parsedBody?.detail === "string" &&
        parsedBody.detail.trim()
      ) {
        detail = parsedBody.detail;
      } else if (parsedBody?.detail) {
        detail = JSON.stringify(parsedBody.detail);
      }
    } catch {
      /* Body not JSON — keep statusText */
    }
    throw new ApiHttpError(detail, response.status, parsedBody);
  }

  private async _authRecoveryContext(
    response: Response,
  ): Promise<AuthRecoveryContext | null> {
    if (response.status === 401) {
      let parsedBody: Record<string, unknown> | null = null;
      try {
        const body = await response.clone().json();
        if (body && typeof body === "object" && !Array.isArray(body)) {
          parsedBody = body as Record<string, unknown>;
        }
      } catch {
        parsedBody = null;
      }
      return {
        status: response.status,
        detail: detailFromParsedBody(parsedBody),
        body: parsedBody,
      };
    }

    if (response.status !== 403) return null;

    let parsedBody: Record<string, unknown> | null = null;
    try {
      const body = await response.clone().json();
      if (body && typeof body === "object" && !Array.isArray(body)) {
        parsedBody = body as Record<string, unknown>;
      }
    } catch {
      parsedBody = null;
    }

    const detail = detailFromParsedBody(parsedBody);
    const normalizedDetail = detail.toLowerCase();
    const isRecoverable403 = RECOVERABLE_AUTH_403_MARKERS.some((marker) =>
      normalizedDetail.includes(marker),
    );
    if (!isRecoverable403) return null;

    return {
      status: response.status,
      detail,
      body: parsedBody,
    };
  }

  private async _retryAfterAuthRecovery(
    response: Response,
    retry: () => Promise<Response>,
  ): Promise<Response> {
    if (!this.onUnauthorized) return response;

    const context = await this._authRecoveryContext(response);
    if (!context) return response;

    const recovered = await this.onUnauthorized(context);
    if (recovered) {
      return await retry();
    }
    return response;
  }

  /** GET request */
  async get<T>(
    path: string,
    params?: Record<string, string>,
    timeoutMs: number = DEFAULT_TIMEOUT_MS,
  ): Promise<T> {
    const url = new URL(path, this.baseUrl);
    if (params) {
      Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    }

    let response = await adaptiveFetch(
      url.toString(),
      {
        method: "GET",
        headers: this.resolveHeaders(),
      },
      timeoutMs,
    );

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(
        url.toString(),
        {
          method: "GET",
          headers: this.resolveHeaders(),
        },
        timeoutMs,
      ),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** POST request (JSON) */
  async post<T>(path: string, body: unknown): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "POST",
      headers: {
        ...this.resolveHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "POST",
        headers: {
          ...this.resolveHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** GET request with extra headers (e.g. X-Session-ID) */
  async getWithHeaders<T>(
    path: string,
    extraHeaders: Record<string, string>,
    params?: Record<string, string>,
  ): Promise<T> {
    const url = new URL(path, this.baseUrl);
    if (params) {
      Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    }

    let response = await adaptiveFetch(url.toString(), {
      method: "GET",
      headers: { ...this.resolveHeaders(), ...extraHeaders },
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url.toString(), {
        method: "GET",
        headers: { ...this.resolveHeaders(), ...extraHeaders },
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** POST request with extra headers (e.g. X-Session-ID) */
  async postWithHeaders<T>(
    path: string,
    body: unknown,
    extraHeaders: Record<string, string>,
  ): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "POST",
      headers: {
        ...this.resolveHeaders(),
        "Content-Type": "application/json",
        ...extraHeaders,
      },
      body: JSON.stringify(body),
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "POST",
        headers: {
          ...this.resolveHeaders(),
          "Content-Type": "application/json",
          ...extraHeaders,
        },
        body: JSON.stringify(body),
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** DELETE request */
  async delete<T>(path: string): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "DELETE",
      headers: this.resolveHeaders(),
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "DELETE",
        headers: this.resolveHeaders(),
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** PUT request (JSON) */
  async put<T>(path: string, body: unknown): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "PUT",
      headers: {
        ...this.resolveHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "PUT",
        headers: {
          ...this.resolveHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** PATCH request (JSON) */
  async patch<T>(path: string, body: unknown): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "PATCH",
      headers: {
        ...this.resolveHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "PATCH",
        headers: {
          ...this.resolveHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /** POST request with multipart/form-data (e.g., file uploads) */
  async postFormData<T>(
    path: string,
    formData: FormData,
    timeoutMs: number = DEFAULT_TIMEOUT_MS,
  ): Promise<T> {
    const url = new URL(path, this.baseUrl).toString();

    // Do NOT set Content-Type — browser sets it with boundary automatically
    const { "Content-Type": _, ...headersWithoutCT } = this.resolveHeaders();

    let response = await adaptiveFetch(url, {
      method: "POST",
      headers: headersWithoutCT,
      body: formData,
    }, timeoutMs);

    response = await this._retryAfterAuthRecovery(response, () => {
      const { "Content-Type": __, ...retryHeaders } = this.resolveHeaders();
      return adaptiveFetch(url, {
        method: "POST",
        headers: retryHeaders,
        body: formData,
      }, timeoutMs);
    });

    if (!response.ok) {
      await this._throwApiError(response);
    }

    return (await response.json()) as T;
  }

  /**
   * POST request that returns a ReadableStream for SSE streaming.
   * Used for /chat/stream/v3 endpoint.
   * Sprint 153b: Added signal param so callers can abort the initial HTTP request.
   */
  async postStream(
    path: string,
    body: unknown,
    extraHeaders?: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>> {
    const url = new URL(path, this.baseUrl).toString();

    let response = await adaptiveFetch(url, {
      method: "POST",
      headers: {
        ...this.resolveHeaders(),
        "Content-Type": "application/json",
        ...extraHeaders,
      },
      body: JSON.stringify(body),
      signal,
    });

    response = await this._retryAfterAuthRecovery(response, () =>
      adaptiveFetch(url, {
        method: "POST",
        headers: {
          ...this.resolveHeaders(),
          "Content-Type": "application/json",
          ...extraHeaders,
        },
        body: JSON.stringify(body),
        signal,
      }),
    );

    if (!response.ok) {
      await this._throwApiError(response);
    }

    if (!response.body) {
      throw new Error("No response body for streaming");
    }

    return response.body;
  }

  /** Get the full URL for a path */
  getUrl(path: string): string {
    return new URL(path, this.baseUrl).toString();
  }
}

/** Singleton client instance */
let _client: WiiiClient | null = null;

export function getClient(): WiiiClient {
  if (!_client) {
    _client = new WiiiClient(DEFAULT_SERVER_URL || "http://localhost:8000");
  }
  return _client;
}

export function initClient(baseUrl: string, headers: Record<string, string>) {
  _client = new WiiiClient(baseUrl, headers);
  return _client;
}
