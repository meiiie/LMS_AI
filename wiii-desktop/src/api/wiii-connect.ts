import { getClient } from "./client";
import type {
  WiiiConnectActivationReadinessResponse,
  WiiiConnectAuthorizationUrlDecision,
  RuntimeFlowDoctorHistoryReport,
  RuntimeFlowDoctorReport,
  RuntimeFlowSessionEventPruneReport,
  SemanticMemoryWriteDoctorHistoryReport,
  SemanticMemoryWriteDoctorReport,
  WiiiConnectDoctorReport,
  WiiiConnectFacebookPagesResponse,
  WiiiConnectFacebookPostApplyResponse,
  WiiiConnectFacebookPostPreviewResponse,
  WiiiConnectEffectiveActionInventoryResponse,
  WiiiConnectProviderConnectionListResponse,
  WiiiConnectProviderConnectionStatus,
  WiiiConnectProviderDisconnectResponse,
  WiiiConnectProviderScopeGrantResponse,
  WiiiConnectProviderRegistryResponse,
  WiiiConnectRuntimeSnapshot,
  WiiiConnectSessionStartBody,
  WiiiConnectSessionStartDecision,
} from "./types";

export async function fetchWiiiConnectProviders(): Promise<WiiiConnectProviderRegistryResponse> {
  return getClient().get<WiiiConnectProviderRegistryResponse>("/api/v1/wiii-connect/providers");
}

export async function fetchWiiiConnectSnapshot(options: {
  query?: string;
  surface?: string;
} = {}): Promise<WiiiConnectRuntimeSnapshot> {
  const params: Record<string, string> = {};
  if (options.query) params.query = options.query;
  if (options.surface) params.surface = options.surface;
  return getClient().get<WiiiConnectRuntimeSnapshot>("/api/v1/wiii-connect/snapshot", params);
}

export async function fetchWiiiConnectDoctor(options: {
  query?: string;
  surface?: string;
} = {}): Promise<WiiiConnectDoctorReport> {
  const params: Record<string, string> = {};
  if (options.query) params.query = options.query;
  if (options.surface) params.surface = options.surface;
  return getClient().get<WiiiConnectDoctorReport>("/api/v1/wiii-connect/doctor", params);
}

export async function fetchRecentRuntimeFlowDoctor(options: {
  orgId?: string;
  limit?: number;
} = {}): Promise<RuntimeFlowDoctorReport> {
  const params: Record<string, string> = {
    limit: String(options.limit ?? 50),
  };
  if (options.orgId) params.org_id = options.orgId;
  return getClient().get<RuntimeFlowDoctorReport>(
    "/api/v1/admin/runtime-flow/doctor/recent",
    params,
  );
}

export async function fetchRuntimeFlowDoctorHistory(options: {
  orgId?: string;
  limit?: number;
  bucketLimit?: number;
} = {}): Promise<RuntimeFlowDoctorHistoryReport> {
  const params: Record<string, string> = {
    limit: String(options.limit ?? 500),
    bucket_limit: String(options.bucketLimit ?? 24),
  };
  if (options.orgId) params.org_id = options.orgId;
  return getClient().get<RuntimeFlowDoctorHistoryReport>(
    "/api/v1/admin/runtime-flow/doctor/history",
    params,
  );
}

export async function fetchRecentSemanticMemoryDoctor(options: {
  orgId?: string;
  limit?: number;
} = {}): Promise<SemanticMemoryWriteDoctorReport> {
  const params: Record<string, string> = {
    limit: String(options.limit ?? 50),
  };
  if (options.orgId) params.org_id = options.orgId;
  return getClient().get<SemanticMemoryWriteDoctorReport>(
    "/api/v1/admin/semantic-memory/doctor/recent",
    params,
  );
}

export async function fetchSemanticMemoryDoctorHistory(options: {
  orgId?: string;
  limit?: number;
  bucketLimit?: number;
} = {}): Promise<SemanticMemoryWriteDoctorHistoryReport> {
  const params: Record<string, string> = {
    limit: String(options.limit ?? 500),
    bucket_limit: String(options.bucketLimit ?? 24),
  };
  if (options.orgId) params.org_id = options.orgId;
  return getClient().get<SemanticMemoryWriteDoctorHistoryReport>(
    "/api/v1/admin/semantic-memory/doctor/history",
    params,
  );
}

export async function pruneRuntimeFlowSessionEvents(options: {
  retentionDays?: number;
  orgId?: string;
  eventType?: string;
  dryRun?: boolean;
} = {}): Promise<RuntimeFlowSessionEventPruneReport> {
  const params = new URLSearchParams();
  if (typeof options.retentionDays === "number") {
    params.set("retention_days", String(options.retentionDays));
  }
  if (options.orgId) params.set("org_id", options.orgId);
  if (options.eventType) params.set("event_type", options.eventType);
  params.set("dry_run", options.dryRun === false ? "false" : "true");
  const query = params.toString();
  return getClient().post<RuntimeFlowSessionEventPruneReport>(
    `/api/v1/admin/runtime-flow/session-events/prune${query ? `?${query}` : ""}`,
    {},
  );
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

export async function fetchWiiiConnectProviderEffectiveActions(
  slug: string,
  options: {
    connectionRef?: string;
    probeDatabase?: boolean;
  } = {},
): Promise<WiiiConnectEffectiveActionInventoryResponse> {
  return getClient().get<WiiiConnectEffectiveActionInventoryResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/effective-actions`,
    {
      connection_ref: options.connectionRef ?? "",
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
  const params: Record<string, string> = {
    connection_ref: options.connectionRef ?? "",
    probe_database: options.probeDatabase === false ? "false" : "true",
  };
  if (options.actionSlug) {
    params.action_slug = options.actionSlug;
  }
  return getClient().get<WiiiConnectActivationReadinessResponse>(
    `/api/v1/wiii-connect/providers/${encodeURIComponent(slug)}/activation-readiness`,
    params,
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
