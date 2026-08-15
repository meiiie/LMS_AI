/**
 * Detected local ACP agents (T301, FR-003). Detection runs in Rust
 * (`neko_detect_agents`); this store caches the roster for the mode UI.
 */
import { create } from "zustand";

export interface DetectedAgent {
  id: string;
  name: string;
  /** Binary that answered the Rust probe; empty when not found. */
  binary: string;
  version: string | null;
  found: boolean;
}

export interface AgentLaunchProfile {
  id: string;
  provider: string;
  model: string | null;
  active: boolean;
}

/** Read-only, workspace-aware Neko profile discovery. Other agents return none. */
export async function loadAgentProfiles(
  agent: DetectedAgent,
  workspacePath: string,
): Promise<AgentLaunchProfile[]> {
  if (agent.id !== "neko" || !agent.binary || !workspacePath) return [];
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const profiles = await invoke<AgentLaunchProfile[]>("neko_agent_profiles", {
      program: agent.binary,
      cwd: workspacePath,
    });
    return Array.isArray(profiles) ? profiles : [];
  } catch {
    return [];
  }
}

interface NekoAgentState {
  agents: DetectedAgent[];
  isLoading: boolean;
  detect: () => Promise<void>;
}

/** Rust-side detection; resolves empty in browser dev (no Tauri runtime). */
async function detectAgents(): Promise<DetectedAgent[]> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<DetectedAgent[]>("neko_detect_agents");
  } catch {
    return [];
  }
}

export const useNekoAgentStore = create<NekoAgentState>((set) => ({
  agents: [],
  isLoading: false,

  detect: async () => {
    set({ isLoading: true });
    const agents = await detectAgents();
    set({ agents, isLoading: false });
  },
}));
