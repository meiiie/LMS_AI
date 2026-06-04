import { useEffect } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useToastStore } from "@/stores/toast-store";
import { PERSONAL_ORG_ID } from "@/lib/constants";

const SESSION_STORAGE_KEY = "wiii:scheduled_notification_ws_session";
const INITIAL_RECONNECT_MS = 5_000;
const MAX_RECONNECT_MS = 30_000;

export interface ScheduledTaskNotificationPayload {
  type?: string;
  task_id?: string;
  mode?: string;
  content?: unknown;
  trigger?: string;
  [key: string]: unknown;
}

type AutonomousNotificationPayload = ScheduledTaskNotificationPayload;

export function buildScheduledNotificationWebSocketUrl(
  serverUrl: string,
  sessionId: string,
  organizationId?: string | null,
): string {
  const base = new URL(serverUrl);
  const url = new URL(`/api/v1/ws/${encodeURIComponent(sessionId)}`, base.origin);
  url.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  if (organizationId && organizationId !== PERSONAL_ORG_ID) {
    url.searchParams.set("org_id", organizationId);
  }
  return url.toString();
}

export function parseScheduledTaskNotification(
  raw: unknown,
): ScheduledTaskNotificationPayload | null {
  if (typeof raw !== "string") return null;
  try {
    const parsed = JSON.parse(raw) as ScheduledTaskNotificationPayload;
    if (!parsed || parsed.type !== "scheduled_task") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function parseAutonomousNotification(
  raw: unknown,
): AutonomousNotificationPayload | null {
  if (typeof raw !== "string") return null;
  try {
    const parsed = JSON.parse(raw) as AutonomousNotificationPayload;
    if (
      parsed &&
      (parsed.type === "scheduled_task" || parsed.type === "proactive_message")
    ) {
      return parsed;
    }
    return null;
  } catch {
    const content = raw.trim();
    if (!content) return null;
    return {
      type: "proactive_message",
      content,
      transport: "plain_text",
    };
  }
}

export function scheduledTaskToastMessage(
  payload: ScheduledTaskNotificationPayload,
): string {
  const content =
    typeof payload.content === "string" && payload.content.trim()
      ? payload.content.trim()
      : "Task đã đến giờ.";
  return payload.mode === "agent"
    ? `Task tự động: ${content}`
    : `Nhắc việc: ${content}`;
}

export function proactiveNotificationToastMessage(
  payload: AutonomousNotificationPayload,
): string {
  const content =
    typeof payload.content === "string" && payload.content.trim()
      ? payload.content.trim()
      : "Wiii c\u00f3 c\u1eadp nh\u1eadt m\u1edbi.";
  return `Wiii ch\u1ee7 \u0111\u1ed9ng: ${content}`;
}

function makeSessionId(): string {
  const runtimeCrypto =
    typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  const randomId =
    runtimeCrypto && typeof runtimeCrypto.randomUUID === "function"
      ? runtimeCrypto.randomUUID()
      : makeRandomHexId(runtimeCrypto);
  return `scheduled-${randomId}`;
}

function makeRandomHexId(runtimeCrypto: Crypto | undefined): string {
  if (runtimeCrypto && typeof runtimeCrypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    runtimeCrypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  return `${Date.now().toString(36)}-no-crypto`;
}

function getScheduledNotificationSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing) return existing;
    const created = makeSessionId();
    sessionStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return makeSessionId();
  }
}

export function useScheduledTaskNotifications(): void {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const authUser = useAuthStore((state) => state.user);
  const authMode = useAuthStore((state) => state.authMode);
  const accessToken = useAuthStore((state) => state.tokens?.access_token || "");
  const settings = useSettingsStore((state) => state.settings);
  const settingsLoaded = useSettingsStore((state) => state.isLoaded);
  const addToast = useToastStore((state) => state.addToast);

  useEffect(() => {
    if (
      !settingsLoaded ||
      !isAuthenticated ||
      !settings.server_url ||
      typeof WebSocket === "undefined"
    ) {
      return;
    }

    const userId = authUser?.id || settings.user_id;
    if (!userId) return;

    const organizationId =
      authUser?.active_organization_id || settings.organization_id || "";
    const userRole = authUser?.legacy_role || authUser?.role || settings.user_role;
    let stopped = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempt = 0;

    const clearReconnectTimer = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const scheduleReconnect = (connect: () => void) => {
      if (stopped) return;
      const delay = Math.min(
        INITIAL_RECONNECT_MS * 2 ** reconnectAttempt,
        MAX_RECONNECT_MS,
      );
      reconnectAttempt += 1;
      clearReconnectTimer();
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      if (stopped) return;
      let url: string;
      try {
        url = buildScheduledNotificationWebSocketUrl(
          settings.server_url,
          getScheduledNotificationSessionId(),
          organizationId,
        );
      } catch (error) {
        console.warn("[ScheduledNotifications] Invalid server URL:", error);
        return;
      }

      try {
        socket = new WebSocket(url);
      } catch (error) {
        console.warn("[ScheduledNotifications] WebSocket open failed:", error);
        scheduleReconnect(connect);
        return;
      }

      socket.onopen = () => {
        reconnectAttempt = 0;
        socket?.send(
          JSON.stringify({
            type: "auth",
            api_key: settings.api_key || undefined,
            access_token: authMode === "oauth" ? accessToken || undefined : undefined,
            user_id: userId,
            role: userRole,
            organization_id: organizationId || undefined,
          }),
        );
      };

      socket.onmessage = (event) => {
        const payload = parseAutonomousNotification(event.data);
        if (!payload) return;
        addToast(
          "info",
          payload.type === "scheduled_task"
            ? scheduledTaskToastMessage(payload)
            : proactiveNotificationToastMessage(payload),
          8_000,
        );
      };

      socket.onclose = () => {
        if (!stopped) scheduleReconnect(connect);
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      clearReconnectTimer();
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close();
      }
    };
  }, [
    addToast,
    accessToken,
    authMode,
    authUser?.active_organization_id,
    authUser?.id,
    authUser?.legacy_role,
    authUser?.role,
    isAuthenticated,
    settings.api_key,
    settings.organization_id,
    settings.server_url,
    settings.user_id,
    settings.user_role,
    settingsLoaded,
  ]);
}
