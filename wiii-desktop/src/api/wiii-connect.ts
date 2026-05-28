import { getClient } from "./client";
import type {
  WiiiConnectActivationReadinessResponse,
  WiiiConnectAuthorizationUrlDecision,
  WiiiConnectFacebookPagesResponse,
  WiiiConnectFacebookPostApplyResponse,
  WiiiConnectFacebookPostPreviewResponse,
  WiiiConnectProviderConnectionListResponse,
  WiiiConnectProviderConnectionStatus,
  WiiiConnectProviderDisconnectResponse,
  WiiiConnectProviderScopeGrantResponse,
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
    connectionRef?: string;
    probeDatabase?: boolean;
  } = {},
): Promise<WiiiConnectActivationReadinessResponse> {
  return getClient().get<WiiiConnectActivationReadinessResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/activation-readiness`,
    {
      action_slug: options.actionSlug ?? "GMAIL_FETCH_EMAILS",
      connection_ref: options.connectionRef ?? "",
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

export async function grantWiiiConnectProviderConnectionScopes(
  slug: string,
  connectionRef: string,
  scopes: Record<string, boolean>,
): Promise<WiiiConnectProviderScopeGrantResponse> {
  return getClient().post<WiiiConnectProviderScopeGrantResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/connections/${encodeURIComponent(connectionRef)}/scope-grant`,
    {
      surface: "desktop",
      scopes,
    },
  );
}

export async function fetchWiiiConnectFacebookPages(
  slug: string,
  connectionRef: string,
): Promise<WiiiConnectFacebookPagesResponse> {
  return getClient().get<WiiiConnectFacebookPagesResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/facebook/pages`,
    {
      connection_ref: connectionRef,
    },
  );
}

export interface WiiiConnectFacebookPostBody {
  surface?: string;
  connection_ref: string;
  page_id: string;
  message: string;
  image_base64?: string | null;
  image_media_type?: string | null;
  image_filename?: string | null;
  image_url?: string | null;
}

export async function previewWiiiConnectFacebookPost(
  slug: string,
  body: WiiiConnectFacebookPostBody,
): Promise<WiiiConnectFacebookPostPreviewResponse> {
  return getClient().post<WiiiConnectFacebookPostPreviewResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/facebook-post/preview`,
    {
      surface: "desktop",
      ...body,
    },
  );
}

export async function applyWiiiConnectFacebookPost(
  slug: string,
  body: WiiiConnectFacebookPostBody & {
    approval_token: string;
    preview_evidence_id: string;
  },
): Promise<WiiiConnectFacebookPostApplyResponse> {
  return getClient().post<WiiiConnectFacebookPostApplyResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/facebook-post/apply`,
    {
      surface: "desktop",
      ...body,
    },
  );
}

export function buildWiiiConnectProviderCallbackUrl(slug: string): string {
  return getClient().getUrl(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/callback`,
  );
}
