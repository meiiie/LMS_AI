import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import type {
  NekoDetectedProvider,
  NekoLaunchProfile,
} from "./contracts";
import {
  findProviderDefinition,
  providerLaunchArgs,
  requireProviderDefinition,
} from "./provider-registry";

export interface NekoProviderSpawnRequest {
  providerId: string;
  profileId?: string;
}

export interface NekoProviderProfileRequest {
  providerId: string;
  workspacePath: string;
}

export interface NekoSpawnedProvider {
  provider: NekoDetectedProvider;
  transport: AcpTransport;
}

/** Replaceable bridge from Wiii clients to Neko's native authority. */
export interface NekoControlClient {
  listProviders(): Promise<NekoDetectedProvider[]>;
  listProfiles(request: NekoProviderProfileRequest): Promise<NekoLaunchProfile[]>;
  spawnProvider(request: NekoProviderSpawnRequest): Promise<NekoSpawnedProvider>;
}

class TauriNekoControlClient implements NekoControlClient {
  async listProviders(): Promise<NekoDetectedProvider[]> {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const providers = await invoke<NekoDetectedProvider[]>("neko_detect_agents");
      if (!Array.isArray(providers)) return [];
      return providers.flatMap((provider) => {
        const definition = findProviderDefinition(provider.id);
        return definition ? [{ ...provider, name: definition.name }] : [];
      });
    } catch {
      // Browser/web hosts have no local process authority.
      return [];
    }
  }

  async listProfiles(request: NekoProviderProfileRequest): Promise<NekoLaunchProfile[]> {
    const provider = requireProviderDefinition(request.providerId);
    if (!provider.profileArgument || !request.workspacePath) return [];
    try {
      const detected = (await this.listProviders()).find(
        (candidate) => candidate.id === provider.id,
      );
      if (!detected?.found || !detected.binary) return [];
      const { invoke } = await import("@tauri-apps/api/core");
      const profiles = await invoke<NekoLaunchProfile[]>("neko_agent_profiles", {
        program: detected.binary,
        cwd: request.workspacePath,
      });
      return Array.isArray(profiles) ? profiles : [];
    } catch {
      return [];
    }
  }

  async spawnProvider(request: NekoProviderSpawnRequest): Promise<NekoSpawnedProvider> {
    const provider = requireProviderDefinition(request.providerId);
    const detected = (await this.listProviders()).find(
      (candidate) => candidate.id === provider.id,
    );
    if (!detected?.found || !detected.binary) {
      throw new Error(`Provider "${provider.name}" is not available on this host.`);
    }
    const args = providerLaunchArgs(request.providerId, request.profileId);
    const { invoke } = await import("@tauri-apps/api/core");
    const { listen } = await import("@tauri-apps/api/event");
    const procId = await invoke<number>("neko_spawn_agent", {
      program: detected.binary,
      args,
    });

    const lineHandlers: Array<(line: string) => void> = [];
    const exitHandlers: Array<(code: number | null) => void> = [];
    let killed = false;
    let unlistenLine: (() => void) | null = null;
    let unlistenExit: (() => void) | null = null;

    try {
      unlistenLine = await listen<string>(`neko-agent://line/${procId}`, (event) => {
        for (const handler of lineHandlers) handler(event.payload);
      });
      unlistenExit = await listen<number | null>(`neko-agent://exit/${procId}`, (event) => {
        for (const handler of exitHandlers) handler(event.payload ?? null);
      });
    } catch (error) {
      unlistenLine?.();
      unlistenExit?.();
      await invoke("neko_kill_agent", { procId }).catch(() => {});
      throw error;
    }

    const transport: AcpTransport = {
      async send(line: string): Promise<void> {
        await invoke("neko_write_stdin", { procId, line });
      },
      onLine(handler: (line: string) => void): void {
        lineHandlers.push(handler);
      },
      onExit(handler: (code: number | null) => void): void {
        exitHandlers.push(handler);
      },
      async kill(): Promise<void> {
        if (killed) return;
        killed = true;
        unlistenLine?.();
        unlistenExit?.();
        await invoke("neko_kill_agent", { procId }).catch(() => {
          // The native process table already observed process exit.
        });
      },
    };
    return { provider: detected, transport };
  }
}

const defaultClient: NekoControlClient = new TauriNekoControlClient();

export function getNekoControlClient(): NekoControlClient {
  return defaultClient;
}
