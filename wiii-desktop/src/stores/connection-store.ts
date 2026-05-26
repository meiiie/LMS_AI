/**
 * Connection store — monitors server health.
 * Sprint 111: Reconnection detection for celebration toast.
 */
import { create } from "zustand";
import { checkHealth } from "@/api/health";
import { HEALTH_CHECK_INTERVAL } from "@/lib/constants";

type ConnectionStatus = "connected" | "degraded" | "disconnected" | "checking";

interface ConnectionState {
  status: ConnectionStatus;
  serverVersion: string | null;
  lastCheckedAt: string | null;
  errorMessage: string | null;
  consecutiveFailures: number;
  pollIntervalId: ReturnType<typeof setInterval> | null;
  /** Fires once when connection recovers from disconnected → connected */
  onReconnect: (() => void) | null;

  // Actions
  checkHealth: () => Promise<void>;
  startPolling: (intervalMs?: number) => void;
  stopPolling: () => void;
  setOnReconnect: (cb: (() => void) | null) => void;
}

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  status: "checking",
  serverVersion: null,
  lastCheckedAt: null,
  errorMessage: null,
  consecutiveFailures: 0,
  pollIntervalId: null,
  onReconnect: null,

  checkHealth: async () => {
    const prevStatus = get().status;
    const prevFailures = get().consecutiveFailures;
    set({ status: "checking" });
    try {
      const health = await checkHealth();
      const newStatus = health.status === "ok" || health.status === "healthy" ? "connected" : "degraded";
      set({
        status: newStatus,
        serverVersion: health.version ?? null,
        lastCheckedAt: new Date().toISOString(),
        errorMessage: null,
        consecutiveFailures: 0,
      });
      // Detect reconnection: was disconnected/degraded, now connected
      if (newStatus === "connected" && (prevStatus === "disconnected" || prevStatus === "degraded")) {
        get().onReconnect?.();
      }
    } catch (err) {
      const consecutiveFailures = prevFailures + 1;
      const shouldDisconnect = prevStatus === "disconnected" || consecutiveFailures >= 2;
      set({
        status: shouldDisconnect ? "disconnected" : "degraded",
        lastCheckedAt: new Date().toISOString(),
        errorMessage: err instanceof Error ? err.message : "Unknown error",
        consecutiveFailures,
      });
    }
  },

  startPolling: (intervalMs = HEALTH_CHECK_INTERVAL) => {
    const { pollIntervalId } = get();
    if (pollIntervalId) clearInterval(pollIntervalId);

    // Check immediately
    get().checkHealth();

    // Then poll at interval
    const id = setInterval(() => get().checkHealth(), intervalMs);
    set({ pollIntervalId: id });
  },

  stopPolling: () => {
    const { pollIntervalId } = get();
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      set({ pollIntervalId: null });
    }
  },

  setOnReconnect: (cb) => set({ onReconnect: cb }),
}));
