export const NEKO_PROVIDER_CAPABILITY_NAMES = [
  "resume",
  "fork",
  "modelSelection",
  "reasoning",
  "modes",
  "slashCommands",
  "approvals",
  "toolEvents",
  "usage",
  "diff",
  "subagents",
  "nativeReview",
  "sessionList",
  "sessionHistory",
  "backgroundWork",
] as const;

export type NekoProviderCapability = (typeof NEKO_PROVIDER_CAPABILITY_NAMES)[number];
export type NekoProviderCapabilityMap = Record<NekoProviderCapability, boolean>;
export type NekoProviderIntegration =
  | "native-structured"
  | "acp"
  | "structured-sdk"
  | "structured-cli"
  | "pty";
export type NekoProviderAuthOwner = "provider" | "wiii" | "user-credential" | "none";
export type NekoProviderExtensionValue = string | number | boolean | null;
export type NekoProviderAvailability = "available" | "not_installed" | "host_unsupported";

export interface NekoDetectedProvider {
  id: string;
  name: string;
  version: string | null;
  found: boolean;
  availability: NekoProviderAvailability;
  supportsProfiles: boolean;
}

export interface NekoLaunchProfile {
  id: string;
  provider: string;
  model: string | null;
  active: boolean;
}

export interface NekoProviderCapabilitySnapshot {
  v: 1;
  providerId: string;
  providerVersion: string | null;
  integration: NekoProviderIntegration;
  protocol: string;
  capabilities: NekoProviderCapabilityMap;
  extensions: Record<string, NekoProviderExtensionValue>;
}

export interface NekoProviderCapabilitySnapshotInput {
  providerId: string;
  providerVersion: string | null;
  integration?: NekoProviderIntegration;
  protocol?: string;
  established?: Partial<NekoProviderCapabilityMap>;
  extensions?: Record<string, unknown>;
}

const SECRET_LIKE_EXTENSION = /(?:authorization|cookie|credential|password|secret|token|api[-_]?key)/i;
const MAX_EXTENSION_COUNT = 16;
const MAX_EXTENSION_KEY_LENGTH = 64;
const MAX_EXTENSION_STRING_LENGTH = 256;

export function emptyProviderCapabilities(): NekoProviderCapabilityMap {
  return Object.fromEntries(
    NEKO_PROVIDER_CAPABILITY_NAMES.map((name) => [name, false]),
  ) as NekoProviderCapabilityMap;
}

function normalizeExtensions(
  value: Record<string, unknown> | undefined,
): Record<string, NekoProviderExtensionValue> {
  if (!value) return {};
  const entries = Object.entries(value);
  if (entries.length > MAX_EXTENSION_COUNT) {
    throw new Error("Provider extension set exceeds the durable snapshot limit.");
  }
  const normalized: Record<string, NekoProviderExtensionValue> = {};
  for (const [key, extension] of entries) {
    if (
      !key ||
      key.length > MAX_EXTENSION_KEY_LENGTH ||
      SECRET_LIKE_EXTENSION.test(key) ||
      !(extension === null || ["string", "number", "boolean"].includes(typeof extension)) ||
      (typeof extension === "number" && !Number.isFinite(extension)) ||
      (typeof extension === "string" && extension.length > MAX_EXTENSION_STRING_LENGTH)
    ) {
      throw new Error(`Provider extension "${key}" is not safe for durable storage.`);
    }
    normalized[key] = extension as NekoProviderExtensionValue;
  }
  return normalized;
}

export function isNekoProviderCapabilitySnapshot(
  value: unknown,
): value is NekoProviderCapabilitySnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Record<string, unknown>;
  if (
    snapshot.v !== 1 ||
    typeof snapshot.providerId !== "string" ||
    !snapshot.providerId ||
    !(snapshot.providerVersion === null || typeof snapshot.providerVersion === "string") ||
    !["native-structured", "acp", "structured-sdk", "structured-cli", "pty"].includes(
      snapshot.integration as string,
    ) ||
    typeof snapshot.protocol !== "string" ||
    !snapshot.protocol ||
    !snapshot.capabilities ||
    typeof snapshot.capabilities !== "object" ||
    !snapshot.extensions ||
    typeof snapshot.extensions !== "object" ||
    Array.isArray(snapshot.extensions)
  ) return false;

  const capabilities = snapshot.capabilities as Record<string, unknown>;
  if (
    Object.keys(capabilities).length !== NEKO_PROVIDER_CAPABILITY_NAMES.length ||
    !NEKO_PROVIDER_CAPABILITY_NAMES.every((name) => typeof capabilities[name] === "boolean")
  ) return false;

  try {
    normalizeExtensions(snapshot.extensions as Record<string, unknown>);
    return true;
  } catch {
    return false;
  }
}

/**
 * Build a complete fail-closed snapshot. Registry metadata is supplied by
 * the provider registry; direct callers must provide integration/protocol.
 */
export function createRawProviderCapabilitySnapshot(
  input: Required<Pick<NekoProviderCapabilitySnapshotInput, "providerId" | "providerVersion" | "integration" | "protocol">> &
    Pick<NekoProviderCapabilitySnapshotInput, "established" | "extensions">,
): NekoProviderCapabilitySnapshot {
  if (!input.providerId || !input.protocol) {
    throw new Error("Provider capability snapshot requires provider and protocol identity.");
  }
  const capabilities = emptyProviderCapabilities();
  for (const [name, established] of Object.entries(input.established ?? {})) {
    if (!NEKO_PROVIDER_CAPABILITY_NAMES.includes(name as NekoProviderCapability)) {
      throw new Error(`Unknown normalized provider capability "${name}".`);
    }
    if (typeof established !== "boolean") {
      throw new Error(`Provider capability "${name}" must be boolean.`);
    }
    capabilities[name as NekoProviderCapability] = established;
  }
  return {
    v: 1,
    providerId: input.providerId,
    providerVersion: input.providerVersion,
    integration: input.integration,
    protocol: input.protocol,
    capabilities,
    extensions: normalizeExtensions(input.extensions),
  };
}
