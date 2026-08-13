/**
 * Shell-level mode selection (FR-001) — persisted before any auth runs.
 *
 * `wiii` is the authenticated cloud experience; `neko-chill` is the
 * no-login local-agent surface. App.tsx reads this store at the pre-auth
 * seam and must never start cloud init while the mode is `neko-chill`
 * (FR-002). Persistence rides the existing tauri-plugin-store wrapper
 * (localStorage fallback in browser dev).
 */
import { create } from "zustand";
import { loadStore, saveStore } from "@/lib/storage";

export type AppMode = "wiii" | "neko-chill";

const STORE_NAME = "neko-chill-mode.json";
const KEY = "mode";

interface ModeState {
  mode: AppMode;
  isLoaded: boolean;
  loadMode: () => Promise<void>;
  setMode: (mode: AppMode) => Promise<void>;
}

function isAppMode(value: unknown): value is AppMode {
  return value === "wiii" || value === "neko-chill";
}

export const useModeStore = create<ModeState>((set) => ({
  mode: "wiii",
  isLoaded: false,

  loadMode: async () => {
    const stored = await loadStore<string>(STORE_NAME, KEY, "");
    if (isAppMode(stored)) {
      set({ mode: stored, isLoaded: true });
      return;
    }
    // Desktop-first landing (#893): with no persisted (or a corrupt) mode,
    // signed-in users land in the cloud app, everyone else in the no-login
    // Neko Chill mode. This is a storage peek only — no cloud init runs.
    const auth = await loadStore<unknown>("auth_state", "data", null);
    set({ mode: auth ? "wiii" : "neko-chill", isLoaded: true });
  },

  setMode: async (mode: AppMode) => {
    set({ mode });
    await saveStore(STORE_NAME, KEY, mode);
  },
}));
