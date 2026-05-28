import { getClient } from "./client";
import type {
  WiiiConnectAuthorizationUrlDecision,
  WiiiConnectProviderConnectionListResponse,
  WiiiConnectProviderConnectionStatus,
  WiiiConnectProviderRegistryResponse,
  WiiiConnectSessionStartBody,
  WiiiConnectSessionStartDecision,
} from "./types";

export async function fetchWiiiConnectProviders(): Promise<WiiiConnectProviderRegistryResponse> {
  return getClient().get<WiiiConnectProviderRegistryResponse>("/api/v1/wiii-connect/providers");
}

export async function fetchWiiiConnectProviderStatus(
  slug: string,
): Promise<WiiiConnectProviderConnectionStatus> {
  return getClient().get<WiiiConnectProviderConnectionStatus>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/status`,
  );
}

export async function startWiiiConnectProviderSession(
  slug: string,
  body: WiiiConnectSessionStartBody = {},
): Promise<WiiiConnectSessionStartDecision> {
  return getClient().post<WiiiConnectSessionStartDecision>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/sessions`,
    body,
  );
}

export async function createWiiiConnectProviderAuthorizationUrl(
  slug: string,
  body: WiiiConnectSessionStartBody = {},
): Promise<WiiiConnectAuthorizationUrlDecision> {
  return getClient().post<WiiiConnectAuthorizationUrlDecision>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/authorization-url`,
    body,
  );
}

export async function fetchWiiiConnectProviderConnections(
  slug: string,
  options: { probeDatabase?: boolean } = {},
): Promise<WiiiConnectProviderConnectionListResponse> {
  return getClient().get<WiiiConnectProviderConnectionListResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/connections`,
    {
      probe_database: options.probeDatabase === false ? "false" : "true",
    },
  );
}

export function buildWiiiConnectProviderCallbackUrl(slug: string): string {
  return getClient().getUrl(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/callback`,
  );
}
