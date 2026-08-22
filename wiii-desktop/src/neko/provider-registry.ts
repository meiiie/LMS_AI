import {
  createRawProviderCapabilitySnapshot,
  type NekoProviderAuthOwner,
  type NekoProviderCapabilitySnapshot,
  type NekoProviderCapabilitySnapshotInput,
  type NekoProviderIntegration,
} from "./contracts";

export interface NekoProviderDefinition {
  id: string;
  capabilityId: string;
  name: string;
  integration: NekoProviderIntegration;
  protocol: string;
  authOwner: NekoProviderAuthOwner;
  description: string;
}

const DEFINITIONS = [
  {
    id: "neko",
    capabilityId: "neko-core",
    name: "Neko Core",
    integration: "acp",
    protocol: "acp-v1",
    authOwner: "provider",
    description: "Runtime ACP cục bộ, phiên bền vững và profile do Neko Core quản lý.",
  },
  {
    id: "gemini",
    capabilityId: "gemini-cli",
    name: "Gemini CLI",
    integration: "acp",
    protocol: "acp-v1",
    authOwner: "provider",
    description: "Agent ACP cục bộ dùng cấu hình và tài khoản của Gemini CLI.",
  },
  {
    id: "codex",
    capabilityId: "codex",
    name: "Codex",
    integration: "native-structured",
    protocol: "codex-app-server",
    authOwner: "provider",
    description: "Codex App Server sở hữu đăng nhập, model và provider thread.",
  },
] as const satisfies readonly NekoProviderDefinition[];

const BY_ID = new Map<string, NekoProviderDefinition>(
  DEFINITIONS.map((definition) => [definition.id, definition]),
);

export function listProviderDefinitions(): readonly NekoProviderDefinition[] {
  return DEFINITIONS;
}

export function findProviderDefinition(providerId: string): NekoProviderDefinition | null {
  return BY_ID.get(providerId) ?? null;
}

export function requireProviderDefinition(providerId: string): NekoProviderDefinition {
  const definition = findProviderDefinition(providerId);
  if (!definition) throw new Error(`Unknown Neko provider "${providerId}".`);
  return definition;
}

export function createProviderCapabilitySnapshot(
  input: Pick<NekoProviderCapabilitySnapshotInput, "providerId" | "providerVersion" | "established" | "extensions">,
): NekoProviderCapabilitySnapshot {
  const definition = requireProviderDefinition(input.providerId);
  return createRawProviderCapabilitySnapshot({
    providerId: input.providerId,
    providerVersion: input.providerVersion?.trim() || null,
    integration: definition.integration,
    protocol: definition.protocol,
    established: input.established,
    extensions: input.extensions,
  });
}
