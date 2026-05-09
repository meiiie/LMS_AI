/**
 * Admin API module — Sprint 179: "Quản Trị Toàn Diện"
 *
 * Endpoints for the admin panel: dashboard, users, feature flags,
 * analytics, audit logs, and GDPR operations.
 */
import type {
  AdminContext,
  AdminDashboard,
  AdminUser,
  AdminUserSearchParams,
  AdminUserSearchResponse,
  AdminFeatureFlag,
  AdminFlagUpdateBody,
  AdminOrgDetail,
  AdminOrgMember,
  AnalyticsOverview,
  LlmUsageAnalytics,
  LlmRuntimeConfig,
  LlmRuntimeAuditRefreshBody,
  LlmRuntimeUpdateBody,
  ModelCatalogResponse,
  EmbeddingSpaceMigrationPlanRequest,
  EmbeddingSpaceMigrationPlanResponse,
  EmbeddingSpaceMigrationPromoteRequest,
  EmbeddingSpaceMigrationRunRequest,
  EmbeddingSpaceMigrationRunResponse,
  UserAnalytics,
  AdminAuditLogsResponse,
  AdminAuthEventsResponse,
  GdprExportResponse,
  GdprForgetResponse,
} from "./types";
import { getClient } from "./client";

const PREFIX = "/api/v1/admin";

// ---------------------------------------------------------------------------
// Sprint 181: Admin Context (Two-Tier Admin)
// ---------------------------------------------------------------------------

/** Get current user's admin capabilities (system admin vs org admin) */
export async function getAdminContext(): Promise<AdminContext> {
  const client = getClient();
  return client.get<AdminContext>("/api/v1/users/me/admin-context");
}

/** Get admin dashboard stats */
export async function getAdminDashboard(): Promise<AdminDashboard> {
  const client = getClient();
  return client.get<AdminDashboard>(`${PREFIX}/dashboard`);
}

/** Search users with filters and pagination */
export async function searchAdminUsers(
  params?: AdminUserSearchParams,
): Promise<AdminUserSearchResponse> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.email) query.set("email", params.email);
  if (params?.role) query.set("role", params.role);
  if (params?.platform_role) query.set("platform_role", params.platform_role);
  if (params?.org_id) query.set("org_id", params.org_id);
  if (params?.status) query.set("status", params.status);
  if (params?.sort) query.set("sort", params.sort);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return client.get<AdminUserSearchResponse>(
    `${PREFIX}/users${qs ? `?${qs}` : ""}`,
  );
}

/** Get all feature flags (optionally filtered by org) */
export async function getFeatureFlags(
  orgId?: string,
): Promise<AdminFeatureFlag[]> {
  const client = getClient();
  const query = orgId ? `?org_id=${orgId}` : "";
  return client.get<AdminFeatureFlag[]>(`${PREFIX}/feature-flags${query}`);
}

/** Get organization detail */
export async function getAdminOrgDetail(
  orgId: string,
): Promise<AdminOrgDetail> {
  const client = getClient();
  return client.get<AdminOrgDetail>(`/api/v1/organizations/${orgId}`);
}

/** Get organization members */
export async function getAdminOrgMembers(
  orgId: string,
): Promise<AdminOrgMember[]> {
  const client = getClient();
  return client.get<AdminOrgMember[]>(`/api/v1/organizations/${orgId}/members`);
}

/** Toggle a feature flag */
export async function toggleFeatureFlag(
  key: string,
  body: AdminFlagUpdateBody,
): Promise<AdminFeatureFlag> {
  const client = getClient();
  return client.patch<AdminFeatureFlag>(`${PREFIX}/feature-flags/${key}`, body);
}

/** Delete a feature flag override */
export async function deleteFeatureFlagOverride(
  key: string,
  organizationId?: string,
): Promise<{ deleted: boolean; key: string }> {
  const client = getClient();
  const query = organizationId ? `?organization_id=${organizationId}` : "";
  return client.delete<{ deleted: boolean; key: string }>(
    `${PREFIX}/feature-flags/${key}${query}`,
  );
}

/** Get analytics overview */
export async function getAnalyticsOverview(params?: {
  from?: string;
  to?: string;
  org_id?: string;
}): Promise<AnalyticsOverview> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.from) query.set("from", params.from);
  if (params?.to) query.set("to", params.to);
  if (params?.org_id) query.set("org_id", params.org_id);
  const qs = query.toString();
  return client.get<AnalyticsOverview>(
    `${PREFIX}/analytics/overview${qs ? `?${qs}` : ""}`,
  );
}

/** Get LLM usage analytics */
export async function getLlmUsageAnalytics(params?: {
  from?: string;
  to?: string;
  org_id?: string;
  model?: string;
  group_by?: string;
}): Promise<LlmUsageAnalytics> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.from) query.set("from", params.from);
  if (params?.to) query.set("to", params.to);
  if (params?.org_id) query.set("org_id", params.org_id);
  if (params?.model) query.set("model", params.model);
  if (params?.group_by) query.set("group_by", params.group_by);
  const qs = query.toString();
  return client.get<LlmUsageAnalytics>(
    `${PREFIX}/analytics/llm-usage${qs ? `?${qs}` : ""}`,
  );
}

export async function getLlmRuntimeConfig(): Promise<LlmRuntimeConfig> {
  const client = getClient();
  return client.get<LlmRuntimeConfig>(`${PREFIX}/llm-runtime`);
}

export async function updateLlmRuntimeConfig(
  body: LlmRuntimeUpdateBody,
): Promise<LlmRuntimeConfig> {
  const client = getClient();
  return client.patch<LlmRuntimeConfig>(`${PREFIX}/llm-runtime`, body);
}

export async function getModelCatalog(): Promise<ModelCatalogResponse> {
  const client = getClient();
  return client.get<ModelCatalogResponse>(`${PREFIX}/model-catalog`);
}

export async function refreshLlmRuntimeAudit(
  body: LlmRuntimeAuditRefreshBody = {},
): Promise<ModelCatalogResponse> {
  const client = getClient();
  return client.post<ModelCatalogResponse>(`${PREFIX}/llm-runtime/audit`, body);
}

export async function refreshVisionRuntimeAudit(
  body: LlmRuntimeAuditRefreshBody = {},
): Promise<LlmRuntimeConfig> {
  const client = getClient();
  return client.post<LlmRuntimeConfig>(
    `${PREFIX}/llm-runtime/vision-audit`,
    body,
  );
}

export async function planEmbeddingSpaceMigration(
  body: EmbeddingSpaceMigrationPlanRequest,
): Promise<EmbeddingSpaceMigrationPlanResponse> {
  const client = getClient();
  return client.post<EmbeddingSpaceMigrationPlanResponse>(
    `${PREFIX}/llm-runtime/embedding-space/plan`,
    body,
  );
}

export async function runEmbeddingSpaceMigration(
  body: EmbeddingSpaceMigrationRunRequest,
): Promise<EmbeddingSpaceMigrationRunResponse> {
  const client = getClient();
  return client.post<EmbeddingSpaceMigrationRunResponse>(
    `${PREFIX}/llm-runtime/embedding-space/migrate`,
    body,
  );
}

export async function promoteEmbeddingSpaceMigration(
  body: EmbeddingSpaceMigrationPromoteRequest,
): Promise<EmbeddingSpaceMigrationRunResponse> {
  const client = getClient();
  return client.post<EmbeddingSpaceMigrationRunResponse>(
    `${PREFIX}/llm-runtime/embedding-space/promote`,
    body,
  );
}

/** Get user analytics */
export async function getUserAnalytics(params?: {
  from?: string;
  to?: string;
  org_id?: string;
}): Promise<UserAnalytics> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.from) query.set("from", params.from);
  if (params?.to) query.set("to", params.to);
  if (params?.org_id) query.set("org_id", params.org_id);
  const qs = query.toString();
  return client.get<UserAnalytics>(
    `${PREFIX}/analytics/users${qs ? `?${qs}` : ""}`,
  );
}

/** Get admin audit logs */
export async function getAuditLogs(params?: {
  actor_id?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  from?: string;
  to?: string;
  org_id?: string;
  limit?: number;
  offset?: number;
}): Promise<AdminAuditLogsResponse> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.actor_id) query.set("actor_id", params.actor_id);
  if (params?.action) query.set("action", params.action);
  if (params?.target_type) query.set("target_type", params.target_type);
  if (params?.target_id) query.set("target_id", params.target_id);
  if (params?.from) query.set("from", params.from);
  if (params?.to) query.set("to", params.to);
  if (params?.org_id) query.set("org_id", params.org_id);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return client.get<AdminAuditLogsResponse>(
    `${PREFIX}/audit-logs${qs ? `?${qs}` : ""}`,
  );
}

/** Get auth events */
export async function getAuthEvents(params?: {
  user_id?: string;
  event_type?: string;
  provider?: string;
  from?: string;
  to?: string;
  org_id?: string;
  limit?: number;
  offset?: number;
}): Promise<AdminAuthEventsResponse> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.user_id) query.set("user_id", params.user_id);
  if (params?.event_type) query.set("event_type", params.event_type);
  if (params?.provider) query.set("provider", params.provider);
  if (params?.from) query.set("from", params.from);
  if (params?.to) query.set("to", params.to);
  if (params?.org_id) query.set("org_id", params.org_id);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return client.get<AdminAuthEventsResponse>(
    `${PREFIX}/auth-events${qs ? `?${qs}` : ""}`,
  );
}

/** Export user data (GDPR) */
export async function gdprExportUser(
  userId: string,
): Promise<GdprExportResponse> {
  const client = getClient();
  return client.post<GdprExportResponse>(
    `${PREFIX}/users/${userId}/export`,
    {},
  );
}

/** Forget user data (GDPR) */
export async function gdprForgetUser(
  userId: string,
): Promise<GdprForgetResponse> {
  const client = getClient();
  return client.post<GdprForgetResponse>(`${PREFIX}/users/${userId}/forget`, {
    confirm: true,
  });
}

// ---------------------------------------------------------------------------
// Sprint 180: User management actions
// ---------------------------------------------------------------------------

/** Deactivate a user (admin only) */
export async function deactivateUser(userId: string): Promise<AdminUser> {
  const client = getClient();
  return client.post<AdminUser>(`/api/v1/users/${userId}/deactivate`, {});
}

/** Reactivate a user (admin only) */
export async function reactivateUser(userId: string): Promise<AdminUser> {
  const client = getClient();
  return client.post<AdminUser>(`/api/v1/users/${userId}/reactivate`, {});
}

/** Change user role (admin only) */
export async function changeUserRole(
  userId: string,
  role: string,
): Promise<AdminUser> {
  const client = getClient();
  return client.patch<AdminUser>(`/api/v1/users/${userId}/role`, { role });
}

/** Change user platform role (admin only). */
export async function changeUserPlatformRole(
  userId: string,
  platformRole: "user" | "platform_admin",
): Promise<AdminUser> {
  const client = getClient();
  return client.patch<AdminUser>(`/api/v1/users/${userId}/role`, {
    platform_role: platformRole,
    role: platformRole === "platform_admin" ? "admin" : "student",
  });
}

// ---------------------------------------------------------------------------
// Sprint 180: Org member management
// ---------------------------------------------------------------------------

/** Add member to organization */
export async function addOrgMember(
  orgId: string,
  userId: string,
  role?: string,
): Promise<void> {
  const client = getClient();
  await client.post<unknown>(`/api/v1/organizations/${orgId}/members`, {
    user_id: userId,
    role: role ?? "member",
  });
}

/** Remove member from organization */
export async function removeOrgMember(
  orgId: string,
  userId: string,
): Promise<void> {
  const client = getClient();
  await client.delete<unknown>(
    `/api/v1/organizations/${orgId}/members/${userId}`,
  );
}

// ---------------------------------------------------------------------------
// Sprint 190: Org Knowledge Management
// ---------------------------------------------------------------------------

import type {
  OrgDocument,
  OrgDocumentListResponse,
  ScatterResponse,
  KnowledgeGraphResponse,
  RagFlowResponse,
} from "./types";

/** Upload a PDF document to org knowledge base */
export async function uploadOrgDocument(
  orgId: string,
  file: File,
): Promise<OrgDocument> {
  const client = getClient();
  const formData = new FormData();
  formData.append("file", file);
  return client.postFormData<OrgDocument>(
    `/api/v1/organizations/${orgId}/knowledge/upload`,
    formData,
  );
}

/** List documents in org knowledge base */
export async function listOrgDocuments(
  orgId: string,
  docStatus?: string,
): Promise<OrgDocumentListResponse> {
  const client = getClient();
  const query = docStatus ? `?doc_status=${docStatus}` : "";
  return client.get<OrgDocumentListResponse>(
    `/api/v1/organizations/${orgId}/knowledge/documents${query}`,
  );
}

/** Get a specific org document */
export async function getOrgDocument(
  orgId: string,
  docId: string,
): Promise<OrgDocument> {
  const client = getClient();
  return client.get<OrgDocument>(
    `/api/v1/organizations/${orgId}/knowledge/documents/${docId}`,
  );
}

/** Delete an org document (soft-delete + remove embeddings) */
export async function deleteOrgDocument(
  orgId: string,
  docId: string,
): Promise<void> {
  const client = getClient();
  await client.delete<unknown>(
    `/api/v1/organizations/${orgId}/knowledge/documents/${docId}`,
  );
}

// ---------------------------------------------------------------------------
// Sprint 191: Knowledge Visualization
// ---------------------------------------------------------------------------

const KNOWLEDGE_VISUALIZATION_TIMEOUT_MS = 15_000;

/** Get PCA/t-SNE scatter data for org knowledge embeddings */
export async function getKnowledgeScatter(
  orgId: string,
  params?: { method?: "pca" | "tsne"; dimensions?: 2 | 3; limit?: number },
): Promise<ScatterResponse> {
  const client = getClient();
  const query = new URLSearchParams();
  if (params?.method) query.set("method", params.method);
  if (params?.dimensions) query.set("dimensions", String(params.dimensions));
  if (params?.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return client.get<ScatterResponse>(
    `/api/v1/organizations/${orgId}/knowledge/visualize/scatter${qs ? `?${qs}` : ""}`,
    undefined,
    KNOWLEDGE_VISUALIZATION_TIMEOUT_MS,
  );
}

/** Get knowledge graph (document/chunk nodes + similarity edges + Mermaid code) */
export async function getKnowledgeGraph(
  orgId: string,
  params?: { max_nodes?: number },
): Promise<KnowledgeGraphResponse> {
  const client = getClient();
  const query = params?.max_nodes ? `?max_nodes=${params.max_nodes}` : "";
  return client.get<KnowledgeGraphResponse>(
    `/api/v1/organizations/${orgId}/knowledge/visualize/graph${query}`,
    undefined,
    KNOWLEDGE_VISUALIZATION_TIMEOUT_MS,
  );
}

/** Simulate RAG retrieval flow for a query */
export async function simulateRagFlow(
  orgId: string,
  queryText: string,
  topK?: number,
): Promise<RagFlowResponse> {
  const client = getClient();
  return client.post<RagFlowResponse>(
    `/api/v1/organizations/${orgId}/knowledge/visualize/rag-flow`,
    { query: queryText, top_k: topK ?? 10 },
  );
}
