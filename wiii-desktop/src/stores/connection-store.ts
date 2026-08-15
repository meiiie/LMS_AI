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
  isChecking: boolean;
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

let healthCheckGeneration = 0;
let healthCheckInFlight: { generation: number; promise: Promise<void> } | null = null;

export const useConnectionStore = create<ConnectionState>((set, get) => ({
  status: "checking",
  isChecking: false,
  serverVersion: null,
  lastCheckedAt: null,
  errorMessage: null,
  consecutiveFailures: 0,
  pollIntervalId: null,
  onReconnect: null,

  checkHealth: () => {
    // Poll ticks, a manual retry, and React remounts can overlap. One shared
    // request keeps the newest result from being overwritten by an older one.
    const generation = healthCheckGeneration;
    if (healthCheckInFlight?.generation === generation) {
      return healthCheckInFlight.promise;
    }

    const run = async () => {
      const prevStatus = get().status;
      const prevFailures = get().consecutiveFailures;
      set({ isChecking: true });
      try {
        const health = await checkHealth();
        if (generation !== healthCheckGeneration) return;
        const newStatus =
          health.status === "ok" || health.status === "healthy"
            ? "connected"
            : "degraded";
        set({
          status: newStatus,
          isChecking: false,
          serverVersion: health.version ?? null,
          lastCheckedAt: new Date().toISOString(),
          errorMessage: null,
          consecutiveFailures: 0,
        });
        if (
          newStatus === "connected" &&
          (prevStatus === "disconnected" || prevStatus === "degraded")
        ) {
          get().onReconnect?.();
        }
      } catch (err) {
        if (generation !== healthCheckGeneration) return;
        const consecutiveFailures = prevFailures + 1;
        const shouldDisconnect =
          prevStatus === "disconnected" || consecutiveFailures >= 2;
        set({
          status: shouldDisconnect ? "disconnected" : "degraded",
          isChecking: false,
          lastCheckedAt: new Date().toISOString(),
          errorMessage: err instanceof Error ? err.message : "Unknown error",
          consecutiveFailures,
        });
      }
    };

    const tracked = { generation, promise: Promise.resolve() };
    tracked.promise = run().finally(() => {
      if (healthCheckInFlight === tracked) healthCheckInFlight = null;
    });
    healthCheckInFlight = tracked;
    return tracked.promise;
  },

  startPolling: (intervalMs = HEALTH_CHECK_INTERVAL) => {
    const { pollIntervalId } = get();
    if (pollIntervalId) clearInterval(pollIntervalId);
    healthCheckGeneration += 1;

    // Check immediately
    get().checkHealth();

    // Then poll at interval
    const id = setInterval(() => get().checkHealth(), intervalMs);
    set({ pollIntervalId: id });
  },

  stopPolling: () => {
    // Ignore a response from the previous endpoint/auth lifecycle.
    healthCheckGeneration += 1;
    const { pollIntervalId } = get();
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      set({ pollIntervalId: null });
    }
    set({ isChecking: false });
  },

  setOnReconnect: (cb) => set({ onReconnect: cb }),
}));
