import { getClient } from "./client";
import type {
  WiiiConnectActivationReadinessResponse,
  WiiiConnectAuthorizationUrlDecision,
  WiiiConnectProviderConnectionListResponse,
  WiiiConnectProviderConnectionStatus,
  WiiiConnectProviderDisconnectResponse,
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

export async function fetchWiiiConnectProviderActivationReadiness(
  slug: string,
  options: {
    actionSlug?: string;
    connectionId?: string;
    probeDatabase?: boolean;
  } = {},
): Promise<WiiiConnectActivationReadinessResponse> {
  return getClient().get<WiiiConnectActivationReadinessResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/activation-readiness`,
    {
      action_slug: options.actionSlug ?? "GMAIL_FETCH_EMAILS",
      connection_id: options.connectionId ?? "",
      probe_database: options.probeDatabase === false ? "false" : "true",
    },
  );
}

export async function disconnectWiiiConnectProviderConnection(
  slug: string,
  connectionId: string,
): Promise<WiiiConnectProviderDisconnectResponse> {
  return getClient().delete<WiiiConnectProviderDisconnectResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/connections/${encodeURIComponent(connectionId)}`,
  );
}

export function buildWiiiConnectProviderCallbackUrl(slug: string): string {
  return getClient().getUrl(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/callback`,
  );
}
