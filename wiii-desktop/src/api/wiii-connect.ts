import { getClient } from "./client";
import type {
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
