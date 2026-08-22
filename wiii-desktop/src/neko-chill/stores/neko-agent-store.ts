/**
 * Detected local providers. Neko Control owns host discovery; this store only
 * caches the roster needed by the current session launcher.
 */
import { create } from "zustand";
import { getNekoControlClient } from "@/neko/control-client";
import type {
  NekoDetectedProvider,
  NekoLaunchProfile,
} from "@/neko/contracts";

export interface DetectedAgent extends NekoDetectedProvider {}
export interface AgentLaunchProfile extends NekoLaunchProfile {}

/** Read-only, workspace-aware Neko profile discovery. Other agents return none. */
export async function loadAgentProfiles(
  agent: DetectedAgent,
  workspacePath: string,
): Promise<AgentLaunchProfile[]> {
  if (agent.id !== "neko" || !agent.binary || !workspacePath) return [];
  return getNekoControlClient().listProfiles({
    providerId: agent.id,
    program: agent.binary,
    workspacePath,
  });
}

interface NekoAgentState {
  agents: DetectedAgent[];
  isLoading: boolean;
  detect: () => Promise<void>;
}

/** Rust-side detection; resolves empty in browser dev (no Tauri runtime). */
async function detectAgents(): Promise<DetectedAgent[]> {
  return getNekoControlClient().listProviders();
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
