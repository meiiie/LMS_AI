import { getClient } from "./client";

export type HostActionAuditEventType =
  | "preview_created"
  | "apply_confirmed"
  | "publish_confirmed";

export interface HostActionAuditRequest {
  event_type: HostActionAuditEventType;
  action: string;
  request_id: string;
  summary?: string;
  host_type?: string;
  host_name?: string;
  page_type?: string;
  page_title?: string;
  user_role?: string;
  workflow_stage?: string;
  preview_kind?: string;
  preview_token?: string;
  target_type?: string;
  target_id?: string;
  surface?: string;
  metadata?: Record<string, unknown>;
}

interface HostActionAuditResponse {
  status: "success";
  event_type: string;
  action: string;
  request_id: string;
}

export interface HostActionResultRequest {
  action: string;
  request_id: string;
  success: boolean;
  summary?: string;
  error?: string;
  data?: Record<string, unknown>;
}

interface HostActionResultResponse {
  status: "accepted" | "ignored";
  action: string;
  request_id: string;
  matched: boolean;
  reason?: string;
}

export async function submitHostActionAudit(
  body: HostActionAuditRequest,
): Promise<HostActionAuditResponse> {
  return getClient().post<HostActionAuditResponse>("/api/v1/host-actions/audit", body);
}

export async function submitHostActionResult(
  body: HostActionResultRequest,
): Promise<HostActionResultResponse> {
  return getClient().post<HostActionResultResponse>("/api/v1/host-actions/result", body);
}
