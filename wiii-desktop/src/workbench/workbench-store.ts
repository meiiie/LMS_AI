import { create } from "zustand";
import { loadStore, saveStore } from "@/lib/storage";
import type { WorkbenchHost } from "./host";

export type WorkbenchSurface = "local" | "managed";

const WORKBENCH_STORE = "wiii-workbench.json";
const WORKBENCH_SURFACE_KEY = "surface";
const LEGACY_MODE_STORE = "neko-chill-mode.json";
const LEGACY_MODE_KEY = "mode";
const AUTH_STORE = "auth_state";
const AUTH_KEY = "data";

function isSurface(value: unknown): value is WorkbenchSurface {
  return value === "local" || value === "managed";
}

function hostAllowsLocalSurface(host: WorkbenchHost): boolean {
  return host.capabilities.localProcess && host.capabilities.localWorkspace;
}

/**
 * Resolve the initial surface without mutating any legacy state.
 *
 * Existing desktop users keep their prior intent. A fresh desktop install is
 * local-first, while a browser fails closed onto a remotely-backed surface.
 */
export function resolveInitialWorkbenchSurface(
  host: WorkbenchHost,
  storedSurface: unknown,
  legacyMode: unknown,
  hasManagedAccount: boolean,
): WorkbenchSurface {
  if (!hostAllowsLocalSurface(host)) return "managed";
  if (isSurface(storedSurface)) return storedSurface;
  if (legacyMode === "wiii") return "managed";
  if (legacyMode === "neko-chill") return "local";
  return hasManagedAccount ? "managed" : "local";
}

interface WorkbenchState {
  surface: WorkbenchSurface;
  isLoaded: boolean;
  load: (host: WorkbenchHost) => Promise<void>;
  setSurface: (
    surface: WorkbenchSurface,
    host: WorkbenchHost,
  ) => Promise<void>;
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  surface: "local",
  isLoaded: false,

  load: async (host) => {
    const [storedSurface, legacyMode, authState] = await Promise.all([
      loadStore<unknown>(WORKBENCH_STORE, WORKBENCH_SURFACE_KEY, null),
      loadStore<unknown>(LEGACY_MODE_STORE, LEGACY_MODE_KEY, null),
      loadStore<unknown>(AUTH_STORE, AUTH_KEY, null),
    ]);

    set({
      surface: resolveInitialWorkbenchSurface(
        host,
        storedSurface,
        legacyMode,
        authState !== null && authState !== undefined,
      ),
      isLoaded: true,
    });
  },

  setSurface: async (surface, host) => {
    const next =
      surface === "local" && !hostAllowsLocalSurface(host)
        ? "managed"
        : surface;
    set({ surface: next });
    await saveStore(WORKBENCH_STORE, WORKBENCH_SURFACE_KEY, next);
  },
}));
