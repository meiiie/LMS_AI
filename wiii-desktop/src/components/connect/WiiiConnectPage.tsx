import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Cable,
  CheckCircle2,
  CloudSun,
  Code2,
  Database,
  ExternalLink,
  FileText,
  Globe2,
  GraduationCap,
  Image as ImageIcon,
  Info,
  Loader2,
  Lock,
  MousePointer2,
  Network,
  PlugZap,
  RefreshCw,
  Route,
  Search,
  Send,
  Server,
  ShieldCheck,
  Unplug,
  Workflow,
  type LucideIcon,
  XCircle,
} from "lucide-react";
import type {
  RuntimeFlowDoctorHistoryReport,
  RuntimeFlowDoctorReport,
  RuntimeFlowDoctorSubagentSummary,
  RuntimeFlowSessionEventPruneReport,
  SemanticMemoryWriteDoctorHistoryReport,
  SemanticMemoryWriteDoctorReport,
  WiiiConnectActivationGate,
  WiiiConnectActivationReadinessResponse,
  WiiiConnectAuthorizationUrlDecision,
  WiiiConnectConnectionLifecycleDecision,
  WiiiConnectDoctorReport,
  WiiiConnectEffectiveActionInventoryResponse,
  WiiiConnectEffectiveActionRecord,
  WiiiConnectFacebookPagesResponse,
  WiiiConnectFacebookPostApplyResponse,
  WiiiConnectFacebookPostPreviewResponse,
  WiiiConnectOperationApprovalLedger,
  WiiiConnectProviderConnectionListResponse,
  WiiiConnectProviderConnectionRecord,
  WiiiConnectProviderDisconnectResponse,
  WiiiConnectProviderRegistryEntry,
  WiiiConnectSessionStartDecision,
  WiiiConnectRuntimeConnection,
  WiiiConnectRuntimePathCapability,
  WiiiConnectRuntimeSnapshot,
} from "@/api/types";
import {
  applyWiiiConnectFacebookPost,
  buildWiiiConnectProviderCallbackUrl,
  createWiiiConnectProviderAuthorizationUrl,
  disconnectWiiiConnectProviderConnection,
  fetchRecentRuntimeFlowDoctor,
  fetchRecentSemanticMemoryDoctor,
  fetchRuntimeFlowDoctorHistory,
  fetchSemanticMemoryDoctorHistory,
  fetchWiiiConnectDoctor,
  fetchWiiiConnectFacebookPages,
  fetchWiiiConnectProviderActivationReadiness,
  fetchWiiiConnectProviderConnections,
  fetchWiiiConnectProviderEffectiveActions,
  fetchWiiiConnectProviders,
  fetchWiiiConnectSnapshot,
  grantWiiiConnectProviderConnectionScopes,
  pruneRuntimeFlowSessionEvents,
  previewWiiiConnectFacebookPost,
  startWiiiConnectProviderSession,
} from "@/api/wiii-connect";
import { FullPageView, type FullPageTab } from "@/components/layout/FullPageView";
import {
  buildCapabilityStatusViewModel,
  runtimePathFromLifecycleEvents,
  type CapabilityDashboardSection,
  type CapabilityStatusItemId,
  type CapabilityStatusTone,
  type CapabilityStatusViewModel,
  type RuntimePathSnapshot,
} from "@/lib/capability-status";
import {
  buildRuntimeFlowLedgerViewModel,
  buildRuntimeFlowTraceViewModel,
  latestRuntimeFlowLedger,
  latestRuntimeFlowTrace,
  type RuntimeFlowLedgerViewModel,
  type RuntimeFlowTraceViewModel,
} from "@/lib/runtime-flow-trace";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useAuthStore } from "@/stores/auth-store";
import { useUIStore } from "@/stores/ui-store";

type ConnectTab = "catalog" | "connections" | "paths" | "runtime";
type ProviderFilter = "wiii_native" | "composio" | "channels" | "mcp" | "workflow";
type CatalogCategory =
  | "all"
  | "runtime"
  | "chat"
  | "productivity"
  | "automation"
  | "social"
  | "learning"
  | "platform";

interface NativeCatalogDefinition {
  slug: string;
  label: string;
  description: string;
  category: Exclude<CatalogCategory, "all">;
  icon: LucideIcon;
  fallbackId?: CapabilityStatusItemId;
}

interface ExternalCatalogDefinition {
  id: string;
  provider: Exclude<ProviderFilter, "wiii_native">;
  label: string;
  description: string;
  category: Exclude<CatalogCategory, "all">;
  icon: LucideIcon;
  requirements: string[];
  source?: "backend" | "local";
  authMode?: string;
  actionCount?: number;
}

interface CatalogCard {
  id: string;
  providerSlug: string;
  provider: ProviderFilter;
  providerLabel: string;
  label: string;
  description: string;
  category: Exclude<CatalogCategory, "all">;
  categoryLabel: string;
  icon: LucideIcon;
  tone: CapabilityStatusTone;
  status: string;
  statusDetail: string;
  agentReady: boolean;
  connected: boolean;
  connection?: WiiiConnectRuntimeConnection;
  registrySource?: "backend" | "local";
  detailRows: Array<[string, string]>;
  requirements?: string[];
  disabledReason?: string;
}

const WIII_CONNECT_RUNTIME_REFRESH_MS = 5_000;

interface ProviderConnectionListState {
  response?: WiiiConnectProviderConnectionListResponse;
  loading: boolean;
  error?: string;
  lastFetchedAt?: string;
}

interface ProviderActivationReadinessState {
  response?: WiiiConnectActivationReadinessResponse;
  loading: boolean;
  error?: string;
  lastFetchedAt?: string;
}

interface ProviderActionInventoryState {
  response?: WiiiConnectEffectiveActionInventoryResponse;
  loading: boolean;
  error?: string;
  lastFetchedAt?: string;
}

interface ProviderDisconnectState {
  response?: WiiiConnectProviderDisconnectResponse;
  loading: boolean;
  error?: string;
  lastUpdatedAt?: string;
}

interface FacebookPostDraftImage {
  base64: string;
  mediaType: string;
  filename: string;
  previewUrl: string;
}

interface FacebookPostComposerState {
  pages?: WiiiConnectFacebookPagesResponse;
  pagesLoading: boolean;
  pagesError?: string;
  scopeGrantLoading: boolean;
  scopeGrantError?: string;
  preview?: WiiiConnectFacebookPostPreviewResponse;
  previewLoading: boolean;
  previewError?: string;
  apply?: WiiiConnectFacebookPostApplyResponse;
  applyLoading: boolean;
  applyError?: string;
}

interface ProviderLifecycleStage {
  id: string;
  label: string;
  value: string;
  detail: string;
  tone: CapabilityStatusTone;
}

type ProviderConnectionFlowStatus =
  | "disconnected"
  | "authorizing"
  | "waiting"
  | "connected"
  | "expired"
  | "error"
  | "disconnecting";

interface ProviderConnectionFlowView {
  status: ProviderConnectionFlowStatus;
  label: string;
  detail: string;
  tone: CapabilityStatusTone;
}

interface ProviderNextAction {
  title: string;
  detail: string;
  tone: CapabilityStatusTone;
  items: string[];
}

const tabs: FullPageTab[] = [
  { id: "catalog", label: "Danh bạ", icon: <PlugZap size={15} /> },
  { id: "connections", label: "Snapshot", icon: <Database size={15} /> },
  { id: "paths", label: "Path policy", icon: <Route size={15} /> },
  { id: "runtime", label: "Runtime", icon: <Activity size={15} /> },
];

const providerFilters: Array<{
  id: ProviderFilter;
  label: string;
  hint: string;
}> = [
  { id: "wiii_native", label: "Wiii native", hint: "Runtime nội bộ" },
  { id: "composio", label: "Composio", hint: "OAuth broker" },
  { id: "channels", label: "Channels", hint: "Kênh chat" },
  { id: "mcp", label: "MCP Servers", hint: "Tool server" },
  { id: "workflow", label: "Workflow", hint: "Tự động hóa" },
];

const categoryFilters: Array<{ id: CatalogCategory; label: string }> = [
  { id: "all", label: "Tất cả" },
  { id: "chat", label: "Chat" },
  { id: "productivity", label: "Năng suất" },
  { id: "automation", label: "Công cụ & tự động" },
  { id: "social", label: "Xã hội" },
  { id: "learning", label: "Học tập" },
  { id: "platform", label: "Nền tảng" },
  { id: "runtime", label: "Runtime" },
];

const categoryLabelById = Object.fromEntries(
  categoryFilters.map((category) => [category.id, category.label]),
) as Record<CatalogCategory, string>;

const connectionIconBySlug: Record<string, LucideIcon> = {
  server: Server,
  host: Cable,
  host_actions: Workflow,
  lms_authoring: GraduationCap,
  document_corpus: FileText,
  pointy: MousePointer2,
  web_search: Globe2,
  weather: CloudSun,
  visual_runtime: Network,
  code_studio: Code2,
};

const nativeCatalogDefinitions: NativeCatalogDefinition[] = [
  {
    slug: "server",
    label: "Máy chủ Wiii",
    description: "Backend API, SSE và health check của phiên Wiii hiện tại.",
    category: "runtime",
    icon: Server,
    fallbackId: "server",
  },
  {
    slug: "host",
    label: "Host desktop/LMS",
    description: "Ngữ cảnh host mà Wiii đang nhận từ desktop, embed hoặc LMS.",
    category: "platform",
    icon: Cable,
    fallbackId: "host",
  },
  {
    slug: "host_actions",
    label: "Hành động host",
    description: "Các hành động host được phép preview/request trong surface hiện tại.",
    category: "automation",
    icon: Workflow,
    fallbackId: "host_actions",
  },
  {
    slug: "lms_authoring",
    label: "LMS soạn bài",
    description: "Preview/apply bài học qua LMS, luôn cần approval_token khi ghi dữ liệu.",
    category: "learning",
    icon: GraduationCap,
    fallbackId: "lms_authoring",
  },
  {
    slug: "document_corpus",
    label: "Tài liệu đã tải lên",
    description: "Nguồn tài liệu dùng cho trả lời có căn cứ và trích dẫn.",
    category: "learning",
    icon: FileText,
  },
  {
    slug: "pointy",
    label: "Pointy",
    description: "Target inventory và điều khiển UI khi path hiện tại cho phép.",
    category: "platform",
    icon: MousePointer2,
    fallbackId: "pointy",
  },
  {
    slug: "web_search",
    label: "Tìm kiếm web",
    description: "Tra cứu web khi user có intent live/current/search rõ ràng.",
    category: "runtime",
    icon: Globe2,
  },
  {
    slug: "weather",
    label: "Thời tiết",
    description: "Tra thời tiết khi câu hỏi cần dữ liệu hiện tại hoặc vị trí.",
    category: "runtime",
    icon: CloudSun,
  },
  {
    slug: "visual_runtime",
    label: "Visual runtime",
    description: "Runtime cho hình minh họa, chart và mô phỏng nội tuyến.",
    category: "learning",
    icon: Network,
  },
  {
    slug: "code_studio",
    label: "Code Studio",
    description: "Tạo và hiển thị app/artifact code trong đúng path.",
    category: "automation",
    icon: Code2,
  },
];

const externalCatalogDefinitions: ExternalCatalogDefinition[] = [
  {
    id: "facebook",
    provider: "composio",
    label: "Facebook",
    description: "Đăng, đọc và quản lý nội dung Facebook qua broker OAuth.",
    category: "social",
    icon: Globe2,
    requirements: ["OAuth app hoặc Composio toolkit", "Token vault", "Scope policy", "Execution audit"],
  },
  {
    id: "gmail",
    provider: "composio",
    label: "Gmail",
    description: "Đọc/tạo email khi người dùng cấp quyền rõ ràng.",
    category: "productivity",
    icon: FileText,
    requirements: ["OAuth consent", "Scope read/write tách riêng", "Vault mã hóa", "Preview trước khi gửi"],
  },
  {
    id: "google-calendar",
    provider: "composio",
    label: "Google Calendar",
    description: "Lịch cá nhân và lịch nhóm, không tự ghi nếu chưa xác nhận.",
    category: "productivity",
    icon: Workflow,
    requirements: ["OAuth calendar scopes", "Permission gate", "Preview sự kiện", "Audit trail"],
  },
  {
    id: "google-drive",
    provider: "composio",
    label: "Google Drive",
    description: "Tìm, đọc hoặc tạo file Drive theo scope được cấp.",
    category: "productivity",
    icon: FileText,
    requirements: ["Drive scopes tối thiểu", "File access boundary", "Vault", "Source reference"],
  },
  {
    id: "notion",
    provider: "composio",
    label: "Notion",
    description: "Tra cứu workspace và tạo trang khi đã kết nối.",
    category: "productivity",
    icon: Database,
    requirements: ["Notion OAuth", "Workspace allow-list", "Preview mutation", "Audit"],
  },
  {
    id: "slack",
    provider: "composio",
    label: "Slack",
    description: "Đọc kênh và soạn tin nhắn với xác nhận người dùng.",
    category: "chat",
    icon: Network,
    requirements: ["Workspace install", "Channel scopes", "Preview tin nhắn", "Rate-limit policy"],
  },
  {
    id: "github",
    provider: "composio",
    label: "GitHub",
    description: "Tạo issue, đọc PR hoặc thao tác repo qua quyền hẹp.",
    category: "platform",
    icon: Code2,
    requirements: ["GitHub App/OAuth", "Repo allow-list", "Write confirmation", "Audit"],
  },
  {
    id: "airtable",
    provider: "composio",
    label: "Airtable",
    description: "Đọc/cập nhật base sau khi đã có policy theo workspace.",
    category: "productivity",
    icon: Database,
    requirements: ["Workspace connection", "Schema sync", "Write preview", "Audit"],
  },
  {
    id: "asana",
    provider: "composio",
    label: "Asana",
    description: "Tạo hoặc cập nhật task khi path được phép.",
    category: "productivity",
    icon: Workflow,
    requirements: ["Project allow-list", "Task preview", "Token vault", "Audit"],
  },
  {
    id: "telegram",
    provider: "channels",
    label: "Telegram",
    description: "Kênh nhắn tin để Wiii nhận/gửi message khi có adapter.",
    category: "chat",
    icon: Network,
    requirements: ["Bot token vault", "Webhook gateway", "User binding", "Message audit"],
  },
  {
    id: "discord",
    provider: "channels",
    label: "Discord",
    description: "Kết nối server/channel cho trợ lý nhóm.",
    category: "chat",
    icon: Network,
    requirements: ["Discord app", "Guild allow-list", "Role policy", "Audit"],
  },
  {
    id: "messenger",
    provider: "channels",
    label: "Messenger",
    description: "Tin nhắn Facebook Page sau khi app qua review.",
    category: "chat",
    icon: Globe2,
    requirements: ["Meta app review", "Page token vault", "Webhook verify", "Permission audit"],
  },
  {
    id: "zalo",
    provider: "channels",
    label: "Zalo OA",
    description: "Kênh Zalo Official Account cho thị trường Việt Nam.",
    category: "chat",
    icon: Network,
    requirements: ["Zalo app/OA", "Webhook gateway", "User consent", "Audit"],
  },
  {
    id: "email-channel",
    provider: "channels",
    label: "Email channel",
    description: "Nhận/gửi email như một kênh hội thoại riêng.",
    category: "chat",
    icon: FileText,
    requirements: ["Inbound gateway", "SMTP policy", "Preview send", "Audit"],
  },
  {
    id: "local-mcp",
    provider: "mcp",
    label: "MCP cục bộ",
    description: "Server MCP chạy trên máy người dùng, cần permission gate.",
    category: "platform",
    icon: Server,
    requirements: ["Server registry", "Tool allow-list", "Permission gate", "Per-call audit"],
  },
  {
    id: "remote-mcp",
    provider: "mcp",
    label: "MCP từ xa",
    description: "MCP server remote được quản lý qua tenant/org policy.",
    category: "platform",
    icon: Network,
    requirements: ["Auth handshake", "Tenant isolation", "Tool schema review", "Audit"],
  },
  {
    id: "browser-mcp",
    provider: "mcp",
    label: "Browser MCP",
    description: "Điều khiển browser theo path và confirmation rõ ràng.",
    category: "automation",
    icon: Globe2,
    requirements: ["Surface binding", "Action preview", "Click safety", "Audit"],
  },
  {
    id: "filesystem-mcp",
    provider: "mcp",
    label: "Filesystem MCP",
    description: "Đọc/ghi file qua phạm vi thư mục được cấp quyền.",
    category: "automation",
    icon: FileText,
    requirements: ["Workspace boundary", "Mutation preview", "Path allow-list", "Audit"],
  },
  {
    id: "activepieces",
    provider: "workflow",
    label: "Activepieces",
    description: "Bridge workflow mã nguồn mở cho automation có kiểm soát.",
    category: "automation",
    icon: Workflow,
    requirements: ["Workflow adapter", "Input contract", "Approval gate", "Run ledger"],
  },
  {
    id: "n8n",
    provider: "workflow",
    label: "n8n",
    description: "Chạy workflow tự host hoặc cloud qua Wiii policy.",
    category: "automation",
    icon: Workflow,
    requirements: ["Webhook auth", "Workflow allow-list", "Preview data", "Run audit"],
  },
  {
    id: "windmill",
    provider: "workflow",
    label: "Windmill",
    description: "Script/workflow runner cho tác vụ nội bộ.",
    category: "automation",
    icon: Code2,
    requirements: ["Script registry", "Secrets boundary", "Confirmation", "Audit"],
  },
  {
    id: "pipedream",
    provider: "workflow",
    label: "Pipedream",
    description: "Workflow cloud broker khi cần tích hợp nhanh.",
    category: "automation",
    icon: PlugZap,
    requirements: ["Provider account", "Token policy", "Run preview", "Audit"],
  },
];

const statusToneClasses: Record<CapabilityStatusTone, string> = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  pending: "border-sky-200 bg-sky-50 text-sky-700",
  off: "border-[var(--border)] bg-surface-secondary text-text-tertiary",
};

const statusDotClasses: Record<CapabilityStatusTone, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  pending: "bg-sky-500",
  off: "bg-zinc-400",
};

const providerKindLabels: Record<string, string> = {
  wiii_native: "Wiii native",
  composio: "Composio",
  mcp: "MCP",
  custom_oauth: "OAuth riêng",
  workflow: "Workflow",
  channels: "Channels",
};

const mutationPolicyLabels: Record<string, string> = {
  none: "Không ghi dữ liệu",
  preview_only: "Chỉ preview",
  approval_token_required: "Cần approval_token",
  explicit_user_confirmation_required: "Cần xác nhận",
};

const delegationPolicyLabels: Record<string, string> = {
  direct_only: "Trực tiếp",
  delegate_to_path_agent: "Path agent",
  delegate_to_integration_agent: "Integration agent",
};

const externalProviderRows = [
  {
    provider: "Composio",
    kind: "composio",
    state: "Adapter chưa bật",
    note: "Dùng cho Facebook, Gmail, Notion, Slack khi có policy/vault.",
  },
  {
    provider: "MCP",
    kind: "mcp",
    state: "Adapter chưa bật",
    note: "Dùng cho server local/remote sau khi có permission gate.",
  },
  {
    provider: "OAuth riêng",
    kind: "custom_oauth",
    state: "Chưa triển khai",
    note: "Dùng khi Wiii tự sở hữu app, review quyền và token vault.",
  },
  {
    provider: "Workflow",
    kind: "workflow",
    state: "Chưa triển khai",
    note: "Dùng cho Activepieces, n8n, Windmill, Pipedream-like bridge.",
  },
];

function isEmbeddedWindow(): boolean {
  if (typeof window === "undefined") return false;
  return window.parent !== window;
}

async function openExternalUrl(url: string): Promise<void> {
  const parsed = new URL(url);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("unsupported_authorization_url");
  }
  try {
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(parsed.toString());
    return;
  } catch {
    window.open(parsed.toString(), "_blank", "noopener,noreferrer");
  }
}

function connectionTone(connection: WiiiConnectRuntimeConnection): CapabilityStatusTone {
  if (connection.status === "error" || connection.status === "expired") return "warn";
  if (connection.status === "pending" || connection.status === "preview") return "pending";
  if (connection.status === "disabled" || connection.status === "not_connected") return "off";
  return connection.agent_ready || connection.active || connection.status === "connected"
    ? "ok"
    : "warn";
}

function statusLabel(status: string | undefined): string {
  if (status === "connected") return "Đã kết nối";
  if (status === "authorizing") return "Đang xác thực";
  if (status === "waiting") return "Đang chờ";
  if (status === "disconnected") return "Chưa nối";
  if (status === "preview") return "Preview";
  if (status === "pending") return "Đang chờ";
  if (status === "expired") return "Hết hạn";
  if (status === "error") return "Lỗi";
  if (status === "disabled") return "Tắt";
  if (status === "not_connected") return "Chưa nối";
  return compactText(status, "Không rõ");
}

function providerConnectionTone(
  connection: WiiiConnectProviderConnectionRecord | undefined,
  response?: WiiiConnectProviderConnectionListResponse,
): CapabilityStatusTone {
  if (connection) {
    if (connection.state === "connected" || connection.active) return "ok";
    if (connection.state === "authorizing" || connection.state === "waiting") return "pending";
    if (connection.state === "expired" || connection.state === "error") return "warn";
    return "off";
  }
  if (response?.status === "blocked") return response.reason === "provider_disabled" ? "off" : "warn";
  if (response?.status === "ready") return "off";
  return "off";
}

function primaryProviderConnection(
  response: WiiiConnectProviderConnectionListResponse | undefined,
): WiiiConnectProviderConnectionRecord | undefined {
  return response?.connections?.[0];
}

function providerConnectionSummary(
  connection: WiiiConnectProviderConnectionRecord | undefined,
): string {
  if (!connection) return "Chưa có account";
  return compactText(
    connection.account_label ||
      (connection.external_account_ref_present ? "Provider account" : "") ||
      connection.reason,
    "Đã có connection",
  );
}

const sensitiveDisplayKeyMarkers = [
  "access_token",
  "api_key",
  "approval_token",
  "authorization",
  "bearer",
  "code=",
  "connection_id",
  "connection_ref",
  "credential",
  "password",
  "page_id",
  "provider_payload",
  "raw_payload",
  "refresh_token",
  "secret",
  "scheduled_publish_time",
  "token=",
  "vault",
];

function looksSensitiveDisplayText(value: string): boolean {
  const text = value.trim();
  const lower = text.toLowerCase();
  if (!text) return false;
  if (sensitiveDisplayKeyMarkers.some((marker) => lower.includes(marker))) return true;
  if (lower.startsWith("bearer ")) return true;
  if (/^(sk-|ak_|tp-|wcn_|ca_)/i.test(text)) return true;
  if (/^eyJ[\w-]*\.[\w-]*\.[\w-]*$/.test(text)) return true;
  return false;
}

function safeConnectorText(value: unknown, fallback = "Chưa có"): string {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  return looksSensitiveDisplayText(text) ? "[đã ẩn]" : text;
}

function compactText(value: unknown, fallback = "Chưa có"): string {
  const text = safeConnectorText(value, fallback);
  if (!text) return fallback;
  return text.length > 72 ? `${text.slice(0, 69)}...` : text;
}

const safeRuntimeDoctorCounterToken = /^[A-Za-z0-9_.:/-]{1,96}$/;
const RUNTIME_POST_TURN_LIFECYCLE_METRICS_SCHEMA = "wiii.post_turn_lifecycle_metrics.v1";
const RUNTIME_POST_TURN_LIFECYCLE_LEDGER_SCHEMA = "wiii.post_turn_lifecycle_ledger.v1";

function safeRuntimeDoctorCounterLabel(value: unknown): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) return "unknown";
  if (!safeRuntimeDoctorCounterToken.test(text)) return "[Ä‘Ã£ áº©n]";
  return compactText(text);
}

function countMapEntries(
  value: Record<string, number> | undefined,
  limit = 5,
): Array<[string, number]> {
  if (!value) return [];
  return Object.entries(value)
    .filter(([, count]) => typeof count === "number" && Number.isFinite(count))
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([label, count]) => [safeRuntimeDoctorCounterLabel(label), count]);
}

function disconnectResultTone(
  response: WiiiConnectProviderDisconnectResponse | undefined,
): CapabilityStatusTone {
  if (!response) return "off";
  if (response.local_disabled) return "ok";
  if (response.status === "blocked") return "warn";
  return response.status === "failed" ? "warn" : "off";
}

function locallyDisabledConnection(
  connection: WiiiConnectProviderConnectionRecord,
  reason = "user_disconnect_requested",
): WiiiConnectProviderConnectionRecord {
  return {
    ...connection,
    state: "disabled",
    active: false,
    scopes: {},
    reason,
    warnings: Array.from(new Set([...(connection.warnings ?? []), "disconnected_by_user"])),
  };
}

function responseWithLocallyDisabledConnection(
  response: WiiiConnectProviderConnectionListResponse | undefined,
  connection: WiiiConnectProviderConnectionRecord,
  reason = "user_disconnect_requested",
): WiiiConnectProviderConnectionListResponse {
  const disabled = locallyDisabledConnection(connection, reason);
  if (!response) {
    return {
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason,
      provider_slug: connection.provider_slug,
      provider_kind: "composio",
      connection_count: 1,
      connections: [disabled],
    };
  }
  return {
    ...response,
    status: "ready",
    reason,
    connection_count: Math.max(response.connection_count, 1),
    connections: response.connections.map((item) =>
      providerConnectionRef(item) === providerConnectionRef(connection) ? disabled : item,
    ),
  };
}

function providerConnectionRef(
  connection: WiiiConnectProviderConnectionRecord | null | undefined,
): string {
  return connection?.connection_ref || connection?.connection_id || "";
}

function defaultActivationActionSlug(card: CatalogCard): string {
  if (card.providerSlug === "facebook") return "FACEBOOK_LIST_MANAGED_PAGES";
  if (card.providerSlug === "gmail") return "GMAIL_FETCH_EMAILS";
  return "";
}

function formatCount(value: unknown, label: string): string | null {
  if (typeof value !== "number") return null;
  return `${value} ${label}`;
}

function formatDateTime(value: string | undefined | null): string {
  if (!value) return "Chưa có";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return compactText(value);
  return date.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
}

function scopeSummary(scopes: WiiiConnectRuntimeConnection["scopes"]): string {
  if (!scopes) return "Không";
  const enabled = Object.entries(scopes)
    .filter(([, value]) => value)
    .map(([key]) => safeConnectorText(key, "scope"));
  return enabled.length > 0 ? enabled.join(", ") : "Không";
}

function operationApprovalLedgerTone(
  ledger: WiiiConnectOperationApprovalLedger | null | undefined,
): CapabilityStatusTone {
  if (!ledger) return "off";
  if (ledger.blocked || ledger.status === "blocked" || ledger.status === "expired") {
    return "warn";
  }
  if (ledger.persistent && (ledger.status === "pending" || ledger.status === "consumed")) {
    return "ok";
  }
  if (ledger.status === "unavailable") return "pending";
  return "off";
}

function operationApprovalLedgerLabel(
  ledger: WiiiConnectOperationApprovalLedger | null | undefined,
): string {
  if (!ledger) return "Chưa có";
  if (ledger.blocked || ledger.status === "blocked") return "Bị chặn";
  if (ledger.status === "consumed" || ledger.consumed) return "Đã consume";
  if (ledger.status === "pending" && ledger.persistent) return "Đã ghi ledger";
  if (ledger.status === "unavailable") return "Fallback HMAC";
  return compactText(ledger.status, "Chưa có");
}

function pathList(value: string[] | undefined): string {
  if (!value || value.length === 0) return "Không";
  return value.map((item) => compactText(item)).join(", ");
}

function capabilityCount(connection: WiiiConnectRuntimeConnection): string {
  const count = connection.capabilities?.length ?? 0;
  return count > 0 ? `${count} capability` : "Không";
}

function connectionCounts(connection: WiiiConnectRuntimeConnection): string {
  return [
    formatCount(connection.attachment_count, "file"),
    formatCount(connection.document_count, "doc"),
    formatCount(connection.source_ref_count, "nguồn"),
    formatCount(connection.target_count, "target"),
    formatCount(connection.tool_count, "tool"),
  ]
    .filter(Boolean)
    .join(" · ");
}

function toolGroupSummary(names: string[] | undefined): string {
  if (!names || names.length === 0) return "Không";
  const groups = new Set(
    names.map((name) => {
      const lower = name.toLowerCase();
      if (lower.includes("authoring") || lower.includes("lms")) return "LMS";
      if (lower.includes("host")) return "Host";
      if (lower.startsWith("ui.") || lower.includes("pointy")) return "UI";
      if (lower.includes("web") || lower.includes("search")) return "Web";
      if (lower.includes("memory")) return "Memory";
      if (lower.includes("visual")) return "Visual";
      if (lower.includes("code")) return "Code";
      return "Khác";
    }),
  );
  return `${names.length} nhóm (${Array.from(groups).join(", ")})`;
}

function snapshotStats(snapshot: WiiiConnectRuntimeSnapshot | null) {
  const connections = snapshot?.connections ?? [];
  const pathReadiness = snapshot?.capability_summary?.path_readiness ?? [];
  const readyCount = connections.filter((item) => item.agent_ready).length;
  const warningCount =
    (snapshot?.warnings?.length ?? 0) +
    connections.reduce((total, item) => total + (item.warnings?.length ?? 0), 0);
  return {
    total: connections.length,
    ready: readyCount,
    warningCount,
    pathCount: snapshot?.path_capabilities?.length ?? pathReadiness.length,
    readyPathCount: pathReadiness.filter((item) => item.status === "ready").length,
    guardedPathCount: pathReadiness.filter((item) => item.status === "guarded").length,
    blockedPathCount: pathReadiness.filter((item) => item.status === "blocked").length,
  };
}

function capabilityPathStatusSummary(
  snapshot: WiiiConnectRuntimeSnapshot | null,
): string {
  const paths = snapshot?.capability_summary?.path_readiness ?? [];
  if (paths.length === 0) return "Chưa có";
  const ready = paths.filter((path) => path.status === "ready").length;
  const guarded = paths.filter((path) => path.status === "guarded").length;
  const blocked = paths.filter((path) => path.status === "blocked").length;
  return `${ready}/${paths.length} ready · ${guarded} guarded · ${blocked} blocked`;
}

function capabilityAttentionPath(
  snapshot: WiiiConnectRuntimeSnapshot | null,
): string {
  const paths = snapshot?.capability_summary?.path_readiness ?? [];
  const path = paths.find((item) => item.status !== "ready") ?? paths[0];
  if (!path) return "Không";
  return `${compactText(path.path)}: ${compactText(path.status)} (${compactText(path.reason)})`;
}

function doctorStatusTone(status: string | undefined): CapabilityStatusTone {
  if (status === "ready") return "ok";
  if (status === "degraded" || status === "blocked") return "warn";
  return "pending";
}

function pathDoctorTone(status: string | undefined): CapabilityStatusTone {
  if (status === "ready") return "ok";
  if (status === "guarded") return "pending";
  if (status === "blocked") return "warn";
  return "off";
}

function doctorMetric(report: WiiiConnectDoctorReport | null, key: string): string {
  const value = report?.summary?.[key];
  return typeof value === "number" ? String(value) : "0";
}

function runtimeDoctorMetric(report: RuntimeFlowDoctorReport | null, key: string): string {
  const value = report?.summary?.[key];
  return typeof value === "number" ? String(value) : "0";
}

function runtimeDoctorConfigNumber(
  report: { runtime_config?: Record<string, string | number | boolean> } | null | undefined,
  key: string,
): number | undefined {
  const value = report?.runtime_config?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function semanticMemoryDoctorMetric(
  report: SemanticMemoryWriteDoctorReport | null,
  key: string,
): string {
  const value = report?.summary?.[key];
  return typeof value === "number" ? String(value) : "0";
}

function runtimeDoctorCorrelationMetric(
  report: RuntimeFlowDoctorReport | null,
  key: string,
): string {
  const value = report?.request_correlation?.[key];
  return typeof value === "number" ? String(value) : "0";
}

function runtimeDoctorSubagentMetric(
  report: RuntimeFlowDoctorReport | null,
  key: keyof RuntimeFlowDoctorSubagentSummary,
): string {
  const value = report?.subagents?.[key];
  return typeof value === "number" ? String(value) : "0";
}

function runtimeDoctorAlertTone(
  severity: string | undefined,
): CapabilityStatusTone {
  if (severity === "critical" || severity === "error") return "warn";
  if (severity === "warning") return "pending";
  return "off";
}

function importantDoctorPaths(report: WiiiConnectDoctorReport | null) {
  return (report?.path_diagnostics ?? [])
    .filter((path) => path.status !== "ready")
    .slice(0, 6);
}

function importantDoctorProviders(report: WiiiConnectDoctorReport | null) {
  return (report?.provider_diagnostics ?? [])
    .filter((provider) => provider.provider_kind !== "wiii_native" || provider.status !== "ready")
    .slice(0, 8);
}

function doctorStageLabel(key: string | undefined): string {
  const labels: Record<string, string> = {
    registry: "Registry",
    adapter: "Adapter",
    account: "Account",
    agent_policy: "Agent policy",
    gateway: "Gateway",
  };
  const normalized = String(key ?? "").trim();
  return labels[normalized] ?? compactText(normalized.replaceAll("_", " "));
}

function providerDoctorCountSummary(
  provider: NonNullable<WiiiConnectDoctorReport["provider_diagnostics"]>[number],
): string {
  return [
    formatCount(provider.connection_count, "kết nối"),
    formatCount(provider.active_connection_count, "active"),
    formatCount(provider.action_count, "action"),
    formatCount(provider.scope_count, "scope"),
  ]
    .filter(Boolean)
    .join(" · ") || "Không";
}

function providerStageTone(status: string | undefined): CapabilityStatusTone {
  if (status === "ready") return "ok";
  if (status === "pending") return "pending";
  if (status === "blocked") return "warn";
  return "off";
}

function DoctorProviderStages({
  provider,
}: {
  provider: NonNullable<WiiiConnectDoctorReport["provider_diagnostics"]>[number];
}) {
  const stages = provider.stages ?? [];
  if (stages.length === 0) {
    return <span className="text-text-tertiary">Chưa có lifecycle</span>;
  }
  return (
    <div className="grid min-w-[280px] gap-1.5">
      {stages.map((stage) => (
        <div
          key={`${provider.provider_slug}-${stage.key}`}
          className="rounded-md border border-[var(--border)] bg-surface-secondary px-2 py-1.5"
        >
          <div className="flex min-w-0 items-center justify-between gap-2">
            <span className="truncate text-xs font-medium text-text">
              {doctorStageLabel(stage.key)}
            </span>
            <StatusPill tone={providerStageTone(stage.status)}>
              {compactText(stage.status)}
            </StatusPill>
          </div>
          <div className="mt-1 truncate text-xs text-text-secondary">
            {compactText(stage.reason)}
          </div>
          {stage.required_next && stage.required_next.length > 0 && (
            <div className="mt-1 truncate text-[11px] text-text-tertiary">
              {pathList(stage.required_next)}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function categoryLabel(category: CatalogCategory): string {
  return categoryLabelById[category] ?? "Khác";
}

function toCatalogCategory(value: unknown): Exclude<CatalogCategory, "all"> {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (
    normalized === "runtime" ||
    normalized === "chat" ||
    normalized === "productivity" ||
    normalized === "automation" ||
    normalized === "social" ||
    normalized === "learning" ||
    normalized === "platform"
  ) {
    return normalized;
  }
  return "automation";
}

function toProviderFilter(value: unknown): Exclude<ProviderFilter, "wiii_native"> | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (
    normalized === "composio" ||
    normalized === "channels" ||
    normalized === "mcp" ||
    normalized === "workflow"
  ) {
    return normalized;
  }
  return null;
}

function iconForExternalProvider(
  slug: string,
  provider: Exclude<ProviderFilter, "wiii_native">,
): LucideIcon {
  const normalized = slug.toLowerCase();
  if (provider === "mcp") return normalized.includes("local") ? Server : Network;
  if (provider === "workflow") return normalized.includes("script") ? Code2 : Workflow;
  if (provider === "channels") return normalized.includes("email") ? FileText : Network;
  if (normalized.includes("github")) return Code2;
  if (normalized.includes("drive") || normalized.includes("gmail")) return FileText;
  if (normalized.includes("calendar") || normalized.includes("asana")) return Workflow;
  if (normalized.includes("notion") || normalized.includes("airtable")) return Database;
  return Globe2;
}

function registryEntriesToExternalDefinitions(
  entries: WiiiConnectProviderRegistryEntry[] | null,
): ExternalCatalogDefinition[] | null {
  if (!entries || entries.length === 0) return null;
  const definitions = entries
    .map((entry): ExternalCatalogDefinition | null => {
      const provider = toProviderFilter(entry.provider_kind);
      if (!provider) return null;
      return {
        id: entry.slug,
        provider,
        label: entry.label || entry.slug,
        description:
          entry.description ||
          "Provider do backend registry khai báo; adapter vẫn fail-closed cho đến khi có vault, policy và audit.",
        category: toCatalogCategory(entry.category),
        icon: iconForExternalProvider(entry.slug, provider),
        requirements:
          entry.requirements && entry.requirements.length > 0
            ? entry.requirements
            : ["Vault", "Scope policy", "Execution gateway", "Audit ledger"],
        source: "backend",
        authMode: entry.auth_mode,
        actionCount: entry.action_count,
      };
    })
    .filter((definition): definition is ExternalCatalogDefinition => definition !== null);
  return definitions.length > 0 ? definitions : null;
}

function buildNativeCatalogCards(
  snapshot: WiiiConnectRuntimeSnapshot | null,
  fallbackModel: CapabilityStatusViewModel,
): CatalogCard[] {
  const bySlug = new Map((snapshot?.connections ?? []).map((connection) => [connection.slug, connection]));
  const fallbackById = new Map(fallbackModel.items.map((item) => [item.id, item]));

  return nativeCatalogDefinitions.map((definition) => {
    const connection = bySlug.get(definition.slug);
    if (connection) {
      const tone = connectionTone(connection);
      const counts = connectionCounts(connection);
      const detailRows: Array<[string, string]> = [
        ["Provider", providerKindLabels[connection.provider_kind ?? ""] ?? compactText(connection.provider_kind, "Provider")],
        ["Agent-ready", connection.agent_ready ? "Có" : "Chưa"],
        ["Scope", scopeSummary(connection.scopes)],
        ["Capability", capabilityCount(connection)],
        ["Path dùng", pathList(connection.required_for_paths)],
        ["Nguồn", compactText(connection.source)],
        ["Kiểm tra", formatDateTime(connection.last_checked_at)],
      ];
      if (counts) detailRows.push(["Tài nguyên", counts]);
      if (connection.reason) detailRows.push(["Lý do", compactText(connection.reason)]);
      return {
        id: `native-${definition.slug}`,
        providerSlug: definition.slug,
        provider: "wiii_native",
        providerLabel: "Wiii native",
        label: connection.label || definition.label,
        description: definition.description,
        category: definition.category,
        categoryLabel: categoryLabel(definition.category),
        icon: connectionIconBySlug[connection.slug] ?? definition.icon,
        tone,
        status: statusLabel(connection.status),
        statusDetail: connection.agent_ready ? "Sẵn sàng cho agent" : "Chưa đủ điều kiện agent-ready",
        agentReady: Boolean(connection.agent_ready),
        connected: tone === "ok",
        connection,
        detailRows,
      };
    }

    const fallback = definition.fallbackId
      ? fallbackById.get(definition.fallbackId)
      : undefined;
    if (fallback) {
      return {
        id: `native-${definition.slug}`,
        providerSlug: definition.slug,
        provider: "wiii_native",
        providerLabel: "Wiii native",
        label: definition.label,
        description: definition.description,
        category: definition.category,
        categoryLabel: categoryLabel(definition.category),
        icon: definition.icon,
        tone: fallback.tone,
        status: fallback.value,
        statusDetail: "Đang đọc từ fallback client vì chưa có snapshot backend.",
        agentReady: fallback.tone === "ok",
        connected: fallback.tone === "ok",
        detailRows: [
          ["Nguồn", "Fallback client"],
          ["Trạng thái", fallback.value],
          ["Ghi chú", fallback.title],
        ],
      };
    }

    return {
      id: `native-${definition.slug}`,
      providerSlug: definition.slug,
      provider: "wiii_native",
      providerLabel: "Wiii native",
      label: definition.label,
      description: definition.description,
      category: definition.category,
      categoryLabel: categoryLabel(definition.category),
      icon: definition.icon,
      tone: snapshot ? "off" : "pending",
      status: snapshot ? "Chưa khai báo" : "Chưa có snapshot",
      statusDetail: snapshot
        ? "Backend snapshot chưa khai báo connection này."
        : "Chờ chat_lifecycle.wiii_connect từ lượt runtime.",
      agentReady: false,
      connected: false,
      detailRows: [
        ["Nguồn", snapshot ? "Snapshot backend" : "Chưa có snapshot"],
        ["Trạng thái", snapshot ? "Chưa khai báo" : "Đang chờ"],
      ],
    };
  });
}

function buildExternalCatalogCards(
  providerRegistry: WiiiConnectProviderRegistryEntry[] | null,
  providerConnectionLists: Record<string, ProviderConnectionListState> = {},
  providerReadinessStates: Record<string, ProviderActivationReadinessState> = {},
): CatalogCard[] {
  const definitions =
    registryEntriesToExternalDefinitions(providerRegistry) ?? externalCatalogDefinitions;

  return definitions.map((definition) => {
    const fromBackend = definition.source === "backend";
    const connectionResponse = providerConnectionLists[definition.id]?.response;
    const providerConnection = primaryProviderConnection(connectionResponse);
    const tone = providerConnectionTone(providerConnection, connectionResponse);
    const connectionStatus = providerConnection
      ? statusLabel(providerConnection.state)
      : connectionResponse?.status === "blocked"
        ? "Bị chặn"
        : "Chưa nối";
    const readiness = providerReadinessStates[definition.id]?.response;
    const agentReady = readinessReadyForAction(readiness);
    const reason = connectionResponse?.reason;
    const statusDetail = externalAgentStatusDetail(fromBackend, readiness);
    return {
      id: `${definition.provider}-${definition.id}`,
      providerSlug: definition.id,
      provider: definition.provider,
      providerLabel: providerKindLabels[definition.provider] ?? definition.provider,
      label: definition.label,
      description: definition.description,
      category: definition.category,
      categoryLabel: categoryLabel(definition.category),
      icon: definition.icon,
      tone,
      status: connectionStatus,
      statusDetail,
      agentReady,
      connected: tone === "ok",
      registrySource: definition.source ?? "local",
      detailRows: [
        ["Provider", providerKindLabels[definition.provider] ?? definition.provider],
        ["Nguồn", fromBackend ? "Backend registry" : "Local fallback"],
        ["Auth", compactText(definition.authMode, "Chưa khai báo")],
        ["Action", externalActionSummary(readiness, definition.actionCount)],
        ["Trạng thái", connectionStatus],
        ["Account", providerConnectionSummary(providerConnection)],
        ["Vault ref", providerConnection?.vault_ref_present ? "Có" : "Chưa"],
        ["Scope", providerConnection ? scopeSummary(providerConnection.scopes) : "Chưa"],
        ["Agent-ready", agentReady ? "Có" : "Chưa"],
        ["Gateway", readinessGatewayStatus(readiness)],
        ["Mutation", "Write vẫn bị chặn ngoài allowlist"],
        ...(reason ? ([["Lý do", compactText(reason)]] as Array<[string, string]>) : []),
      ],
      requirements: definition.requirements,
      disabledReason: fromBackend ? statusDetail : "Cần thiết kế adapter/vault/policy trước khi bật Connect.",
    };
  });
}

function buildConnectionCatalogCards(
  snapshot: WiiiConnectRuntimeSnapshot | null,
  fallbackModel: CapabilityStatusViewModel,
  providerRegistry: WiiiConnectProviderRegistryEntry[] | null,
  providerConnectionLists: Record<string, ProviderConnectionListState> = {},
  providerReadinessStates: Record<string, ProviderActivationReadinessState> = {},
): CatalogCard[] {
  return [
    ...buildNativeCatalogCards(snapshot, fallbackModel),
    ...buildExternalCatalogCards(providerRegistry, providerConnectionLists, providerReadinessStates),
  ];
}

function SummaryMetric({
  icon: icon,
  label,
  value,
  tone = "off",
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  tone?: CapabilityStatusTone;
}) {
  const Icon = icon;
  return (
    <div className="min-w-0 rounded-lg border border-[var(--border)] bg-surface px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium uppercase text-text-tertiary">
        <Icon size={14} aria-hidden="true" />
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${statusDotClasses[tone]}`} aria-hidden="true" />
        <span className="truncate text-lg font-semibold text-text">{value}</span>
      </div>
    </div>
  );
}

function StatusPill({ tone, children }: { tone: CapabilityStatusTone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${statusToneClasses[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${statusDotClasses[tone]}`} aria-hidden="true" />
      {children}
    </span>
  );
}

function sessionDecisionTone(
  decision: WiiiConnectSessionStartDecision | undefined,
): CapabilityStatusTone {
  if (!decision) return "off";
  return decision.status === "ready" ? "ok" : "warn";
}

function activationReadinessTone(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): CapabilityStatusTone {
  if (!readiness) return "off";
  if (readinessReadyForAction(readiness)) return "ok";
  if (readiness.ready_to_connect) return "pending";
  return "warn";
}

function readinessReadyForAction(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): boolean {
  return Boolean(readiness?.ready_to_execute_action ?? readiness?.ready_to_execute_readonly);
}

function readinessReadyForReadonly(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): boolean {
  return Boolean(readiness?.ready_to_execute_readonly);
}

function readinessActionMutation(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): string {
  const value = readiness?.action?.mutation;
  return typeof value === "string" ? value : "";
}

function cardDefaultActionIsReadonly(card: CatalogCard): boolean {
  return ["FACEBOOK_LIST_MANAGED_PAGES", "GMAIL_FETCH_EMAILS"].includes(
    defaultActivationActionSlug(card),
  );
}

function readinessBooleanLabel(value: boolean | undefined): string {
  return value ? "Sẵn sàng" : "Chưa sẵn sàng";
}

function readinessGateReady(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
  key: string,
): boolean {
  return Boolean(readiness?.gates?.some((gate) => gate.key === key && gate.ready));
}

function readinessGatewayStatus(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): string {
  return compactText(readiness?.execution_gateway?.status, "Chưa đánh giá");
}

function externalActionSummary(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
  actionCount: number | undefined,
): string {
  if (
    readinessReadyForReadonly(readiness) ||
    readinessGateReady(readiness, "curated_readonly_action")
  ) {
    return "Read-only sẵn sàng";
  }
  if (readinessReadyForAction(readiness) || readinessGateReady(readiness, "curated_action")) {
    return "Action sẵn sàng";
  }
  if (actionCount != null) return `${actionCount}`;
  return "Chưa khai báo";
}

function externalAgentStatusDetail(
  fromBackend: boolean,
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): string {
  if (!fromBackend) {
    return "Wiii chưa có adapter, vault và permission gate cho kết nối này.";
  }
  if (readinessReadyForReadonly(readiness)) {
    return "Read-only action đã qua scope policy và execution gateway; mutation/write vẫn bị chặn ngoài allowlist.";
  }
  if (readinessReadyForAction(readiness)) {
    return "Action đã qua scope policy và execution gateway; mutation vẫn phải đúng preview/approval.";
  }
  if (readiness?.ready_to_connect) {
    return "Backend đã sẵn sàng cấp Connect Link; agent action vẫn chờ account, scope policy và execution gateway.";
  }
  return "Backend registry đã khai báo provider này; agent action vẫn bị khóa cho đến khi có scope, policy và audit.";
}

function externalControlLabel(card: CatalogCard): string {
  if (card.agentReady) return "Agent-ready";
  if (card.connected) return "Chờ policy";
  return "Fail-closed";
}

function readinessGateLabel(key: string): string {
  const labels: Record<string, string> = {
    provider_registered: "Provider registry",
    provider_adapter: "Adapter",
    vault: "Vault",
    persistent_storage: "Storage",
    audit_ledger: "Audit ledger",
    connect_policy: "Connect policy",
    curated_action: "Curated action",
    curated_readonly_action: "Read-only action",
    local_connection: "Connection",
    execution_gateway: "Execution gateway",
  };
  return labels[key] ?? compactText(key.replaceAll("_", " "));
}

function readinessGateTone(gate: WiiiConnectActivationGate): CapabilityStatusTone {
  return gate.ready ? "ok" : "warn";
}

function requirementDisplayLabel(value: string): string {
  const labels: Record<string, string> = {
    audit_ledger: "Bật audit ledger",
    complete_provider_oauth: "Hoàn tất OAuth/Connect Link",
    connect_policy: "Bật connect policy",
    connect_provider_account: "Kết nối account provider",
    curate_action: "Khai báo action đã kiểm duyệt",
    curate_readonly_action: "Khai báo action read-only đã kiểm duyệt",
    curated_action_catalog: "Khai báo catalog action đã kiểm duyệt",
    curated_readonly_action: "Khai báo action read-only đã kiểm duyệt",
    durable_audit_ledger: "Bật audit ledger bền vững",
    enable_curated_action_catalog: "Bật catalog action đã kiểm duyệt",
    enable_action_allowlist: "Bật action allowlist đã kiểm duyệt",
    enable_provider_agent_policy: "Bật policy agent cho provider",
    encrypted_vault_ref: "Cấu hình vault/token ref",
    execution_gateway: "Mở execution gateway read-only",
    provider_adapter: "Bind adapter provider",
    provider_managed_vault_ref: "Dùng vault ref do provider quản lý",
    provider_registered: "Khai báo provider trong registry",
    scope_policy: "Bật scope policy",
    vault: "Cấu hình vault",
  };
  return labels[value] ?? compactText(value.replaceAll("_", " "));
}

function blockedReadinessGates(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): WiiiConnectActivationGate[] {
  return (readiness?.gates ?? []).filter((gate) => !gate.ready);
}

function readableRequiredNext(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): string[] {
  const values = blockedReadinessGates(readiness).flatMap((gate) =>
    gate.required_next && gate.required_next.length > 0
      ? gate.required_next
      : [gate.key],
  );
  return Array.from(new Set(values.map(requirementDisplayLabel)));
}

function readinessConnectionPresent(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): boolean {
  const state = readiness?.connection?.state;
  return Boolean(
    readiness?.connection?.present &&
      state !== "disabled" &&
      state !== "not_connected" &&
      state !== "missing",
  );
}

function providerHasUsableConnection(
  connection: WiiiConnectProviderConnectionRecord | undefined,
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): boolean {
  if (connection) {
    return Boolean(
      (connection.active || connection.state === "connected") &&
        connection.state !== "disabled",
    );
  }
  return readinessConnectionPresent(readiness);
}

function gatewayLifecycleTone(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): CapabilityStatusTone {
  if (readinessReadyForAction(readiness)) return "ok";
  const status = String(readiness?.execution_gateway?.status ?? "").toLowerCase();
  if (!status) return "off";
  if (["allowed", "ready", "ok", "enabled"].includes(status)) return "ok";
  if (["blocked", "denied", "disabled", "error", "missing"].includes(status)) return "warn";
  return "pending";
}

function providerLifecycleStages({
  card,
  readiness,
  providerConnection,
  connectionList,
}: {
  card: CatalogCard;
  readiness: WiiiConnectActivationReadinessResponse | undefined;
  providerConnection: WiiiConnectProviderConnectionRecord | undefined;
  connectionList?: ProviderConnectionListState;
}): ProviderLifecycleStage[] {
  const accountPresent = providerHasUsableConnection(providerConnection, readiness);
  const accountState =
    providerConnection?.state ??
    readiness?.connection?.state ??
    (connectionList?.loading ? "waiting" : undefined);
  const registryFromBackend = card.registrySource === "backend";
  const registryTone: CapabilityStatusTone =
    card.provider === "wiii_native" ? card.tone : registryFromBackend ? "ok" : "off";
  const accountTone: CapabilityStatusTone = providerConnection
    ? providerConnectionTone(providerConnection, connectionList?.response)
    : accountPresent
      ? "ok"
      : connectionList?.loading || readinessStateIsConnectable(readiness)
        ? "pending"
        : "off";
  const agentTone: CapabilityStatusTone = readiness
    ? readinessReadyForAction(readiness)
      ? "ok"
      : accountPresent
        ? "warn"
        : readiness.ready_to_connect
          ? "pending"
          : "off"
    : card.agentReady
      ? "ok"
      : "off";

  return [
    {
      id: "registry",
      label: "Registry",
      value:
        card.provider === "wiii_native"
          ? "Runtime native"
          : registryFromBackend
            ? "Đã đăng ký"
            : "Local fallback",
      detail:
        card.provider === "wiii_native"
          ? "Đọc từ snapshot runtime hoặc fallback client."
          : registryFromBackend
            ? "Provider do backend khai báo; UI không tự giữ secret."
            : "Chỉ là catalog tham khảo, chưa được phép kết nối.",
      tone: registryTone,
    },
    {
      id: "account",
      label: "Account",
      value: accountPresent
        ? statusLabel(accountState)
        : connectionList?.loading
          ? "Đang đọc"
          : "Chưa có account",
      detail: accountPresent
        ? providerConnection
          ? providerConnectionSummary(providerConnection)
          : compactText(readiness?.connection?.reason, "Provider account đã được backend ghi nhận.")
        : "Cần OAuth/Connect Link trước khi agent nhìn thấy account này.",
      tone: accountTone,
    },
    {
      id: "agent-policy",
      label: "Agent policy",
      value: readinessReadyForAction(readiness)
        ? "Đã cho phép action"
        : card.agentReady
          ? "Agent-ready"
          : accountPresent
            ? "Chờ policy"
            : "Chưa agent-ready",
      detail: readinessReadyForAction(readiness)
        ? "Action đã qua scope policy và catalog đã kiểm duyệt."
        : accountPresent
          ? "Account đã kết nối nhưng policy/gateway vẫn đang chặn agent."
          : "Agent chưa được phép dùng provider này.",
      tone: agentTone,
    },
    {
      id: "gateway",
      label: "Gateway",
      value: readinessGatewayStatus(readiness),
      detail: compactText(
        readiness?.execution_gateway?.reason,
        "Chưa có quyết định execution gateway.",
      ),
      tone: gatewayLifecycleTone(readiness),
    },
  ];
}

function backendConnectionLifecycle(
  lifecycle: WiiiConnectConnectionLifecycleDecision | null | undefined,
): ProviderConnectionFlowView | null {
  const status = String(lifecycle?.status ?? "").toLowerCase();
  if (
    ![
      "disconnected",
      "authorizing",
      "waiting",
      "connected",
      "expired",
      "error",
      "disconnecting",
    ].includes(status)
  ) {
    return null;
  }
  const flowStatus = status as ProviderConnectionFlowStatus;
  const reason = compactText(lifecycle?.reason, "backend_lifecycle");
  const detail = `Backend lifecycle: ${reason}.`;
  if (flowStatus === "connected") {
    return {
      status: "connected",
      label: "Đã kết nối",
      detail,
      tone: "ok",
    };
  }
  if (flowStatus === "authorizing") {
    return {
      status: "authorizing",
      label: "Đang xác thực OAuth",
      detail,
      tone: "pending",
    };
  }
  if (flowStatus === "waiting") {
    return {
      status: "waiting",
      label: "Đang chờ OAuth hoàn tất",
      detail,
      tone: "pending",
    };
  }
  if (flowStatus === "expired") {
    return {
      status: "expired",
      label: "Kết nối hết hạn",
      detail,
      tone: "warn",
    };
  }
  if (flowStatus === "error") {
    return {
      status: "error",
      label: "Connection lỗi",
      detail,
      tone: "warn",
    };
  }
  if (flowStatus === "disconnecting") {
    return {
      status: "disconnecting",
      label: "Đang ngắt kết nối",
      detail,
      tone: "pending",
    };
  }
  return {
    status: "disconnected",
    label: lifecycle?.ready_to_connect ? "Sẵn sàng kết nối" : "Chưa kết nối",
    detail,
    tone: lifecycle?.ready_to_connect ? "pending" : "off",
  };
}

function providerConnectionFlow({
  card,
  readiness,
  providerConnection,
  connectionList,
  authorizationDecision,
  authorizationLoading,
  authorizationError,
  disconnectState,
}: {
  card: CatalogCard;
  readiness: WiiiConnectActivationReadinessResponse | undefined;
  providerConnection: WiiiConnectProviderConnectionRecord | undefined;
  connectionList?: ProviderConnectionListState;
  authorizationDecision?: WiiiConnectAuthorizationUrlDecision;
  authorizationLoading?: boolean;
  authorizationError?: string;
  disconnectState?: ProviderDisconnectState;
}): ProviderConnectionFlowView {
  if (card.provider === "wiii_native") {
    return {
      status: card.agentReady ? "connected" : "waiting",
      label: card.agentReady ? "Runtime ready" : "Chờ runtime",
      detail: card.agentReady
        ? "Connection native đã được backend runtime xác nhận."
        : "Chờ snapshot runtime từ host hoặc lượt chat phù hợp.",
      tone: card.agentReady ? "ok" : "pending",
    };
  }

  if (disconnectState?.loading) {
    return {
      status: "disconnecting",
      label: "Đang ngắt kết nối",
      detail: "Backend đang khóa local connection trước khi dọn provider.",
      tone: "pending",
    };
  }

  if (disconnectState?.error || authorizationError || (!readiness && connectionList?.error)) {
    return {
      status: "error",
      label: "Lỗi connection flow",
      detail:
        disconnectState?.error ||
        authorizationError ||
        connectionList?.error ||
        "Backend chưa trả được trạng thái connection.",
      tone: "warn",
    };
  }

  if (authorizationLoading) {
    return {
      status: "authorizing",
      label: "Đang xin Connect Link",
      detail: "Wiii đang yêu cầu backend cấp authorization URL.",
      tone: "pending",
    };
  }

  const canonicalFlow = backendConnectionLifecycle(
    providerConnection?.connection_lifecycle ??
      readiness?.connection_lifecycle ??
      connectionList?.response?.connection_lifecycle,
  );
  if (canonicalFlow && canonicalFlow.status !== "disconnected") {
    return canonicalFlow;
  }

  const connectionState = String(
    providerConnection?.state ?? readiness?.connection?.state ?? "",
  ).toLowerCase();
  const active = Boolean(providerConnection?.active || readiness?.connection?.active);

  if (active || connectionState === "connected") {
    return {
      status: "connected",
      label: "Đã kết nối",
      detail: "Backend đã thấy account active. Agent policy vẫn do readiness/gateway quyết định.",
      tone: "ok",
    };
  }

  if (connectionState === "expired") {
    return {
      status: "expired",
      label: "Kết nối hết hạn",
      detail: "OAuth/account đã hết hạn; cần reconnect trước khi agent thấy action.",
      tone: "warn",
    };
  }

  if (connectionState === "error") {
    return {
      status: "error",
      label: "Connection lỗi",
      detail: compactText(
        providerConnection?.reason ?? readiness?.connection?.reason,
        "Backend báo connection không dùng được.",
      ),
      tone: "warn",
    };
  }

  if (connectionState === "authorizing") {
    return {
      status: "authorizing",
      label: "Đang xác thực OAuth",
      detail: "OAuth flow đã bắt đầu nhưng backend chưa xác nhận account active.",
      tone: "pending",
    };
  }

  if (
    connectionState === "waiting" ||
    connectionState === "pending" ||
    (authorizationDecision?.status === "ready" && authorizationDecision.authorization_url)
  ) {
    return {
      status: "waiting",
      label: "Đang chờ OAuth hoàn tất",
      detail: "Hoàn tất cửa sổ Connect Link; Wiii sẽ poll lại connection thật.",
      tone: "pending",
    };
  }

  if (authorizationDecision?.status === "blocked") {
    return {
      status: "error",
      label: "Connect Link bị chặn",
      detail: compactText(authorizationDecision.reason, "Backend chưa thể phát hành link."),
      tone: "warn",
    };
  }

  if (connectionList?.loading) {
    return {
      status: "waiting",
      label: "Đang đọc connection backend",
      detail: "Wiii đang đồng bộ danh sách account thật từ backend.",
      tone: "pending",
    };
  }

  if (canonicalFlow) {
    return canonicalFlow;
  }

  return {
    status: "disconnected",
    label: readiness?.ready_to_connect ? "Sẵn sàng kết nối" : "Chưa kết nối",
    detail: readiness?.ready_to_connect
      ? "Backend đã sẵn sàng phát hành Connect Link khi người dùng bấm kết nối."
      : "Chưa có account provider hợp lệ trong Wiii Connect.",
    tone: readiness?.ready_to_connect ? "pending" : "off",
  };
}

function readinessStateIsConnectable(
  readiness: WiiiConnectActivationReadinessResponse | undefined,
): boolean {
  return Boolean(readiness?.ready_to_connect);
}

function providerNextAction({
  card,
  readiness,
  providerConnection,
  connectionList,
  authorizationDecision,
  authorizationLoading,
  authorizationError,
  disconnectState,
}: {
  card: CatalogCard;
  readiness: WiiiConnectActivationReadinessResponse | undefined;
  providerConnection: WiiiConnectProviderConnectionRecord | undefined;
  connectionList?: ProviderConnectionListState;
  authorizationDecision?: WiiiConnectAuthorizationUrlDecision;
  authorizationLoading?: boolean;
  authorizationError?: string;
  disconnectState?: ProviderDisconnectState;
}): ProviderNextAction {
  if (card.provider === "wiii_native") {
    return {
      title: card.agentReady ? "Đang dùng được trong runtime" : "Chờ runtime snapshot",
      detail: card.agentReady
        ? "Kết nối native này đã có trong path/capability hiện tại."
        : "Mở một lượt chat hoặc host tương ứng để backend phát snapshot mới.",
      tone: card.agentReady ? "ok" : "pending",
      items: card.requirements?.map(requirementDisplayLabel).slice(0, 3) ?? [],
    };
  }

  if (card.registrySource !== "backend") {
    return {
      title: "Chưa thể kết nối an toàn",
      detail:
        "Provider này mới là catalog cục bộ. Cần backend adapter, vault, policy và audit trước khi mở OAuth thật.",
      tone: "warn",
      items: [],
    };
  }

  const flow = providerConnectionFlow({
    card,
    readiness,
    providerConnection,
    connectionList,
    authorizationDecision,
    authorizationLoading,
    authorizationError,
    disconnectState,
  });

  if (flow.status === "disconnecting") {
    return {
      title: "Đang ngắt kết nối",
      detail: "Wiii đang khóa local connection và chờ backend phản hồi.",
      tone: "pending",
      items: ["Không mở schema mới trong lúc disconnect"],
    };
  }

  if (flow.status === "authorizing" || flow.status === "waiting") {
    return {
      title: flow.label,
      detail: flow.detail,
      tone: "pending",
      items: ["Không hiển thị raw connection id", "Không tự coi là agent-ready"],
    };
  }

  if (flow.status === "expired") {
    return {
      title: "Kết nối hết hạn, cần reconnect",
      detail:
        "Account đã từng tồn tại nhưng không còn dùng được. Bấm Kết nối qua Wiii để phát hành link reconnect.",
      tone: "warn",
      items: ["Reconnect provider", "Giữ agent tools đóng cho tới khi active"],
    };
  }

  if (flow.status === "error") {
    return {
      title: "Sửa lỗi connection flow",
      detail: flow.detail,
      tone: "warn",
      items: ["Đọc lại doctor/readiness", "Không retry action khi chưa ready"],
    };
  }

  if (!readiness && !connectionList?.response) {
    return {
      title: "Đọc trạng thái backend trước",
      detail:
        "Bấm kiểm tra readiness hoặc làm mới trạng thái để Wiii đọc account, policy và gateway thật.",
      tone: "pending",
      items: ["Không dùng dữ liệu đoán từ UI", "Không hiển thị token/provider payload"],
    };
  }

  if (readinessReadyForReadonly(readiness)) {
    return {
      title: "Sẵn sàng cho agent read-only",
      detail:
        "Agent có thể dùng action đọc đã kiểm duyệt; mutation/write vẫn bị chặn ngoài allowlist.",
      tone: "ok",
      items: ["Không tự mở write/admin scope", "Theo dõi audit khi agent gọi tool"],
    };
  }

  if (readinessReadyForAction(readiness)) {
    return {
      title: "Sẵn sàng cho agent action",
      detail:
        "Agent có thể dùng action đã kiểm duyệt. Mutation vẫn phải qua allowlist và approval riêng.",
      tone: "ok",
      items: ["Không tự mở write/admin scope", "Theo dõi audit khi agent gọi tool"],
    };
  }

  const hasAccount = providerHasUsableConnection(providerConnection, readiness);
  if (!hasAccount && readiness?.ready_to_connect) {
    return {
      title: "Mở OAuth/Connect Link với provider",
      detail:
        "Bấm Kết nối qua Wiii để backend cấp link. Sau khi OAuth xong, Wiii sẽ poll lại connection thật.",
      tone: "pending",
      items: readableRequiredNext(readiness),
    };
  }

  if (!hasAccount) {
    return {
      title: "Chưa có account provider",
      detail:
        "Backend chưa thấy account dùng được. Cần hoàn tất connect policy/vault trước khi mở cho agent.",
      tone: "warn",
      items: readableRequiredNext(readiness),
    };
  }

  const nextItems = readableRequiredNext(readiness);
  return {
    title: "Hoàn tất policy/gateway trước khi agent dùng",
    detail:
      "Account đã kết nối, nhưng agent chưa được phép chạy action. Đây là fail-closed đúng: UI không tự cấp quyền thay backend.",
    tone: "warn",
    items: nextItems.length > 0 ? nextItems : ["Kiểm tra scope policy", "Kiểm tra execution gateway"],
  };
}

function ProviderLifecyclePanel({
  card,
  readiness,
  providerConnection,
  connectionList,
  authorizationDecision,
  authorizationLoading,
  authorizationError,
  disconnectState,
}: {
  card: CatalogCard;
  readiness: WiiiConnectActivationReadinessResponse | undefined;
  providerConnection: WiiiConnectProviderConnectionRecord | undefined;
  connectionList?: ProviderConnectionListState;
  authorizationDecision?: WiiiConnectAuthorizationUrlDecision;
  authorizationLoading?: boolean;
  authorizationError?: string;
  disconnectState?: ProviderDisconnectState;
}) {
  const flow = providerConnectionFlow({
    card,
    readiness,
    providerConnection,
    connectionList,
    authorizationDecision,
    authorizationLoading,
    authorizationError,
    disconnectState,
  });
  const stages = providerLifecycleStages({
    card,
    readiness,
    providerConnection,
    connectionList,
  });
  const nextAction = providerNextAction({
    card,
    readiness,
    providerConnection,
    connectionList,
    authorizationDecision,
    authorizationLoading,
    authorizationError,
    disconnectState,
  });

  return (
    <section
      className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3"
      data-testid="wiii-connect-lifecycle-panel"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase text-text-tertiary">
          Vòng đời kết nối
        </div>
        <StatusPill tone={nextAction.tone}>
          {nextAction.tone === "ok"
            ? "ready"
            : nextAction.tone === "pending"
              ? "đang chờ"
              : nextAction.tone === "warn"
                ? "blocked"
                : "chưa bật"}
        </StatusPill>
      </div>

      <div
        className="mb-3 rounded-md border border-[var(--border)] bg-surface px-3 py-2"
        data-state={flow.status}
        data-testid="wiii-connect-connection-flow-state"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Connection flow
            </div>
            <div className="mt-1 truncate text-sm font-semibold text-text">
              {flow.label}
            </div>
          </div>
          <StatusPill tone={flow.tone}>{flow.status}</StatusPill>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          {flow.detail}
        </p>
      </div>

      <ol className="grid gap-2 sm:grid-cols-2">
        {stages.map((stage, index) => (
          <li
            key={`${card.id}-lifecycle-${stage.id}`}
            className="min-w-0 rounded-md border border-[var(--border)] bg-surface px-2 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs font-medium text-text-tertiary">
                {index + 1}. {stage.label}
              </span>
              <span className={`h-2 w-2 shrink-0 rounded-full ${statusDotClasses[stage.tone]}`} />
            </div>
            <div className="mt-1 truncate text-sm font-semibold text-text">
              {stage.value}
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-secondary">
              {stage.detail}
            </p>
          </li>
        ))}
      </ol>

      <div
        className={`mt-3 rounded-md border px-3 py-2 ${statusToneClasses[nextAction.tone]}`}
        data-testid="wiii-connect-next-action"
      >
        <div className="text-xs font-semibold uppercase">Bước tiếp theo</div>
        <div className="mt-1 text-sm font-semibold">{nextAction.title}</div>
        <p className="mt-1 text-xs leading-relaxed">{nextAction.detail}</p>
        {nextAction.items.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {nextAction.items.slice(0, 4).map((item) => (
              <span
                key={`${card.id}-next-${item}`}
                className="rounded-md border border-current/20 bg-white/45 px-2 py-1 text-xs"
              >
                {item}
              </span>
            ))}
          </div>
        )}
      </div>

      <p className="mt-2 text-xs text-text-tertiary">
        Agent không tự cấp quyền. Scope/write/admin phải đến từ policy hoặc approval riêng.
      </p>
    </section>
  );
}

function actionInventoryTone(
  inventory: WiiiConnectEffectiveActionInventoryResponse | undefined,
): CapabilityStatusTone {
  const status = String(inventory?.status ?? "").toLowerCase();
  if (status === "ready") return "ok";
  if (status === "guarded") return "pending";
  if (status === "blocked") return "warn";
  return "off";
}

function actionRecordTone(action: WiiiConnectEffectiveActionRecord): CapabilityStatusTone {
  if (action.executable_now || action.status === "ready") return "ok";
  if (action.visible_to_agent || action.status === "guarded") return "pending";
  return "off";
}

function actionStageLabel(key: string | undefined): string {
  const labels: Record<string, string> = {
    catalog: "Catalog",
    runtime_enablement: "Runtime",
    account: "Account",
    agent_policy: "Agent policy",
    gateway: "Gateway",
  };
  const normalized = String(key ?? "").trim();
  return labels[normalized] ?? compactText(normalized.replaceAll("_", " "));
}

function actionInventorySummary(
  inventory: WiiiConnectEffectiveActionInventoryResponse | undefined,
): string {
  if (!inventory) return "Chưa đồng bộ effective inventory";
  return `${inventory.visible_action_count}/${inventory.runtime_enabled_action_count} action agent-visible · ${inventory.executable_action_count} executable`;
}

function actionModelArgumentSummary(action: WiiiConnectEffectiveActionRecord): string {
  const keys = action.model_argument_keys ?? [];
  const safeKeys = keys
    .map((key) => compactText(key, ""))
    .filter((key) => key && key !== "[đã ẩn]");
  return safeKeys.length > 0 ? safeKeys.join(", ") : "Không";
}

function hiddenArgumentSummary(action: WiiiConnectEffectiveActionRecord): string {
  const count = action.hidden_argument_count ?? 0;
  return count > 0 ? `${count} backend-owned` : "Không";
}

function EffectiveActionInventoryPanel({
  inventoryState,
}: {
  inventoryState?: ProviderActionInventoryState;
}) {
  const inventory = inventoryState?.response;
  const actions = inventory?.actions ?? [];
  return (
    <section
      className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3"
      data-testid="wiii-connect-action-inventory-panel"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase text-text-tertiary">
          Effective actions
        </div>
        <StatusPill tone={actionInventoryTone(inventory)}>
          {inventory?.status ?? (inventoryState?.loading ? "đang đọc" : "chưa đọc")}
        </StatusPill>
      </div>
      <p className="text-xs leading-relaxed text-text-secondary">
        {inventory
          ? `${actionInventorySummary(inventory)}. Gateway: ${compactText(inventory.reason)}.`
          : "Danh sách action agent thật sự được thấy sẽ lấy từ backend policy, không lấy từ catalog tĩnh của UI."}
      </p>

      {actions.length > 0 && (
        <ul className="mt-3 space-y-2">
          {actions.slice(0, 6).map((action) => (
            <li
              key={`${action.provider_slug}-${action.slug}`}
              className="rounded-md border border-[var(--border)] bg-surface px-2 py-2"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-text">
                    {action.label || action.slug}
                  </div>
                  <div className="mt-0.5 truncate text-xs text-text-tertiary">
                    {action.slug} · {action.mutation}
                  </div>
                </div>
                <StatusPill tone={actionRecordTone(action)}>
                  {action.executable_now
                    ? "execute"
                    : action.visible_to_agent
                      ? "agent-visible"
                      : action.status}
                </StatusPill>
              </div>
              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                <div>
                  <span className="text-text-tertiary">Runtime</span>
                  <div className="font-medium text-text">
                    {action.runtime_enabled ? "Bật" : "Tắt"}
                  </div>
                </div>
                <div>
                  <span className="text-text-tertiary">Gateway</span>
                  <div className="font-medium text-text">{compactText(action.reason)}</div>
                </div>
                <div>
                  <span className="text-text-tertiary">Scope</span>
                  <div className="font-medium text-text">
                    {action.required_scopes?.join(", ") || "read"}
                  </div>
                </div>
                <div>
                  <span className="text-text-tertiary">Model args</span>
                  <div className="font-medium text-text">
                    {actionModelArgumentSummary(action)}
                  </div>
                </div>
                <div>
                  <span className="text-text-tertiary">Runtime-owned</span>
                  <div className="font-medium text-text">
                    {hiddenArgumentSummary(action)}
                  </div>
                </div>
              </div>
              {action.stages && action.stages.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {action.stages.slice(0, 5).map((stage) => (
                    <span
                      key={`${action.slug}-${stage.key}`}
                      className="max-w-full rounded-md border border-[var(--border)] px-2 py-1 text-xs text-text-secondary"
                    >
                      <span className="font-medium text-text">
                        {actionStageLabel(stage.key)}:
                      </span>{" "}
                      {compactText(stage.status)}
                      {stage.reason ? <> · {compactText(stage.reason)}</> : null}
                      {stage.required_next && stage.required_next.length > 0 ? (
                        <> · Tiếp: {pathList(stage.required_next.slice(0, 2))}</>
                      ) : null}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {inventoryState?.error && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-2 py-2 text-xs text-amber-800">
          {inventoryState.error}
        </div>
      )}
      {inventoryState?.lastFetchedAt && (
        <p className="mt-2 text-xs text-text-tertiary">
          Cập nhật {formatDateTime(inventoryState.lastFetchedAt)}
        </p>
      )}
    </section>
  );
}

function FacebookOperationApprovalLedgerStatus({
  ledger,
}: {
  ledger: WiiiConnectOperationApprovalLedger | null | undefined;
}) {
  if (!ledger) return null;
  const tone = operationApprovalLedgerTone(ledger);
  const detail = ledger.persistent
    ? compactText(ledger.reason, "ready")
    : "operation_approval_table_ready=false";
  return (
    <div
      data-testid="wiii-connect-facebook-approval-ledger"
      className="mt-3 rounded-md border border-[var(--border)] bg-surface px-3 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-text">Approval ledger</span>
        <StatusPill tone={tone}>{operationApprovalLedgerLabel(ledger)}</StatusPill>
      </div>
      <div className="mt-1 grid gap-1 text-text-secondary sm:grid-cols-3">
        <span>Status: {compactText(ledger.status, "unknown")}</span>
        <span>Reason: {detail}</span>
        <span>Persistent: {readinessBooleanLabel(ledger.persistent)}</span>
      </div>
    </div>
  );
}

function FacebookPostComposer({
  card,
  providerConnection,
  readiness,
  onRefreshConnections,
}: {
  card: CatalogCard;
  providerConnection: WiiiConnectProviderConnectionRecord | undefined;
  readiness: WiiiConnectActivationReadinessResponse | undefined;
  onRefreshConnections?: (card: CatalogCard) => Promise<unknown>;
}) {
  const [pageId, setPageId] = useState("");
  const [message, setMessage] = useState(
    "Wiii Connect test: bài đăng này đã đi qua preview và xác nhận trước khi đăng.",
  );
  const [image, setImage] = useState<FacebookPostDraftImage | null>(null);
  const [state, setState] = useState<FacebookPostComposerState>({
    pagesLoading: false,
    scopeGrantLoading: false,
    previewLoading: false,
    applyLoading: false,
  });

  useEffect(() => {
    return () => {
      if (image?.previewUrl) URL.revokeObjectURL(image.previewUrl);
    };
  }, [image?.previewUrl]);

  if (card.providerSlug !== "facebook" || card.registrySource !== "backend") {
    return null;
  }

  const connectionRef = providerConnectionRef(providerConnection);
  const connected = Boolean(
    connectionRef &&
      providerConnection &&
      (providerConnection.active || providerConnection.state === "connected") &&
      providerConnection.state !== "disabled",
  );
  const scopes: Record<string, boolean> = providerConnection?.scopes ?? {};
  const hasPostScopes = Boolean(scopes.read && scopes.preview && scopes.apply);
  const selectedPageId = pageId.trim();
  const canLoadPages = connected && Boolean(scopes.read);
  const canPreview = connected && hasPostScopes && Boolean(selectedPageId);
  const previewReady = Boolean(
    state.preview?.status === "ready" &&
      state.preview.approval_token &&
      state.preview.preview_evidence_id,
  );
  const canApply = canPreview && previewReady && !state.applyLoading;
  const imagePreviewUrl =
    image?.previewUrl && image.previewUrl.startsWith("blob:")
      ? image.previewUrl
      : "";
  const approvalLedger = state.apply?.approval_ledger ?? state.preview?.approval_ledger;

  const clearDecision = () => {
    setState((current) => ({
      ...current,
      preview: undefined,
      previewError: undefined,
      apply: undefined,
      applyError: undefined,
    }));
  };

  const grantScopes = async () => {
    if (!connectionRef || state.scopeGrantLoading) return;
    setState((current) => ({
      ...current,
      scopeGrantLoading: true,
      scopeGrantError: undefined,
    }));
    try {
      const response = await grantWiiiConnectProviderConnectionScopes(
        card.providerSlug,
        connectionRef,
        { read: true, preview: true, apply: true },
      );
      setState((current) => ({
        ...current,
        scopeGrantLoading: false,
        scopeGrantError: response.status === "ready" ? undefined : response.reason,
      }));
      await onRefreshConnections?.(card);
    } catch {
      setState((current) => ({
        ...current,
        scopeGrantLoading: false,
        scopeGrantError: "Không thể cấp scope qua backend.",
      }));
    }
  };

  const loadPages = async () => {
    if (!connectionRef || !canLoadPages || state.pagesLoading) return;
    setState((current) => ({
      ...current,
      pagesLoading: true,
      pagesError: undefined,
    }));
    try {
      const response = await fetchWiiiConnectFacebookPages(card.providerSlug, connectionRef);
      setState((current) => ({
        ...current,
        pages: response,
        pagesLoading: false,
        pagesError: response.status === "ready" ? undefined : response.reason,
      }));
      if (!pageId && response.pages?.[0]?.page_id) {
        setPageId(response.pages[0].page_id);
      }
    } catch {
      setState((current) => ({
        ...current,
        pagesLoading: false,
        pagesError: "Không thể đọc Page từ backend.",
      }));
    }
  };

  const chooseImage = async (file: File | undefined) => {
    if (!file) return;
    clearDecision();
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
      setState((current) => ({
        ...current,
        previewError: "Ảnh phải là PNG, JPEG, WebP hoặc GIF.",
      }));
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setState((current) => ({
        ...current,
        previewError: "Ảnh tối đa 10MB.",
      }));
      return;
    }
    const base64 = await readFileAsDataUrl(file);
    setImage((current) => {
      if (current?.previewUrl) URL.revokeObjectURL(current.previewUrl);
      return {
        base64,
        mediaType: file.type,
        filename: file.name,
        previewUrl: URL.createObjectURL(file),
      };
    });
  };

  const previewPost = async () => {
    if (!canPreview || state.previewLoading) return;
    setState((current) => ({
      ...current,
      previewLoading: true,
      previewError: undefined,
      apply: undefined,
      applyError: undefined,
    }));
    try {
      const response = await previewWiiiConnectFacebookPost(card.providerSlug, {
        connection_ref: connectionRef,
        page_id: selectedPageId,
        message,
        image_base64: image?.base64 ?? null,
        image_media_type: image?.mediaType ?? null,
        image_filename: image?.filename ?? null,
      });
      setState((current) => ({
        ...current,
        preview: response,
        previewLoading: false,
        previewError: response.status === "ready" ? undefined : response.reason,
      }));
    } catch {
      setState((current) => ({
        ...current,
        previewLoading: false,
        previewError: "Không thể tạo preview qua backend.",
      }));
    }
  };

  const applyPost = async () => {
    if (!canApply || !state.preview?.approval_token || !state.preview.preview_evidence_id) {
      return;
    }
    setState((current) => ({
      ...current,
      applyLoading: true,
      applyError: undefined,
    }));
    try {
      const response = await applyWiiiConnectFacebookPost(card.providerSlug, {
        connection_ref: connectionRef,
        page_id: selectedPageId,
        message,
        image_base64: image?.base64 ?? null,
        image_media_type: image?.mediaType ?? null,
        image_filename: image?.filename ?? null,
        approval_token: state.preview.approval_token,
        preview_evidence_id: state.preview.preview_evidence_id,
      });
      setState((current) => ({
        ...current,
        apply: response,
        applyLoading: false,
        applyError: response.status === "succeeded" ? undefined : response.reason,
      }));
    } catch {
      setState((current) => ({
        ...current,
        applyLoading: false,
        applyError: "Không thể đăng qua backend.",
      }));
    }
  };

  return (
    <section className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase text-text-tertiary">
          Facebook post
        </div>
        <StatusPill tone={connected ? (hasPostScopes ? "ok" : "warn") : "off"}>
          {connected ? (hasPostScopes ? "Có quyền" : "Cần scope") : "Chưa nối"}
        </StatusPill>
      </div>

      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <div className="rounded-md bg-surface px-2 py-2">
          <dt className="text-text-tertiary">Preview/apply</dt>
          <dd className="mt-0.5 font-medium text-text">
            {readinessBooleanLabel(readinessReadyForAction(readiness))}
          </dd>
        </div>
        <div className="rounded-md bg-surface px-2 py-2">
          <dt className="text-text-tertiary">Scope</dt>
          <dd className="mt-0.5 font-medium text-text">{scopeSummary(scopes)}</dd>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!connected || hasPostScopes || state.scopeGrantLoading}
          onClick={() => void grantScopes()}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-primary/30 bg-primary/10 px-3 text-sm font-medium text-primary disabled:border-[var(--border)] disabled:bg-surface disabled:text-text-tertiary"
        >
          {state.scopeGrantLoading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <ShieldCheck size={14} aria-hidden="true" />
          )}
          Cho phép đăng
        </button>
        <button
          type="button"
          disabled={!canLoadPages || state.pagesLoading}
          onClick={() => void loadPages()}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[var(--border)] bg-surface px-3 text-sm font-medium text-text-secondary disabled:text-text-tertiary"
        >
          <RefreshCw
            size={14}
            className={state.pagesLoading ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Đọc Page
        </button>
      </div>

      <label className="mt-3 block text-xs font-medium text-text-tertiary">
        Page
        <select
          value={pageId}
          onChange={(event) => {
            setPageId(event.target.value);
            clearDecision();
          }}
          className="mt-1 h-10 w-full rounded-md border border-[var(--border)] bg-surface px-3 text-sm text-text outline-none focus:border-primary"
        >
          <option value="">Chọn Page</option>
          {state.pages?.pages?.map((page) => (
            <option key={page.page_id} value={page.page_id}>
              {page.name || page.page_id}
            </option>
          ))}
        </select>
      </label>

      <label className="mt-3 block text-xs font-medium text-text-tertiary">
        Nội dung
        <textarea
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
            clearDecision();
          }}
          rows={4}
          className="mt-1 w-full resize-none rounded-md border border-[var(--border)] bg-surface px-3 py-2 text-sm text-text outline-none focus:border-primary"
        />
      </label>

      <div className="mt-3 grid gap-3">
        <label className="inline-flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-md border border-[var(--border)] bg-surface px-3 text-sm font-medium text-text-secondary hover:text-text">
          <ImageIcon size={15} aria-hidden="true" />
          Chọn ảnh
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="sr-only"
            onChange={(event) => void chooseImage(event.target.files?.[0])}
          />
        </label>
        {image && imagePreviewUrl && (
          <div className="overflow-hidden rounded-md border border-[var(--border)] bg-surface">
            <img
              src={imagePreviewUrl}
              alt=""
              className="h-36 w-full object-cover"
            />
            <div className="px-3 py-2 text-xs text-text-secondary">
              {image.filename}
            </div>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canPreview || state.previewLoading}
          onClick={() => void previewPost()}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[var(--border)] bg-surface px-3 text-sm font-medium text-text-secondary disabled:text-text-tertiary"
        >
          {state.previewLoading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <CheckCircle2 size={14} aria-hidden="true" />
          )}
          Tạo preview
        </button>
        <button
          type="button"
          aria-label="Dang bai da duyet"
          disabled={!canApply}
          onClick={() => void applyPost()}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 text-sm font-medium text-emerald-700 disabled:border-[var(--border)] disabled:bg-surface disabled:text-text-tertiary"
        >
          {state.applyLoading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <Send size={14} aria-hidden="true" />
          )}
          Đăng lên Facebook
        </button>
      </div>

      <FacebookOperationApprovalLedgerStatus ledger={approvalLedger} />

      {state.preview?.preview && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Preview sẵn sàng cho Page đã chọn.
        </div>
      )}
      {state.apply?.status === "succeeded" && (
        <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Đã gửi yêu cầu đăng qua gateway.
        </div>
      )}
      {[state.scopeGrantError, state.pagesError, state.previewError, state.applyError]
        .filter(Boolean)
        .map((error) => (
          <div
            key={String(error)}
            className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          >
            {error}
          </div>
        ))}
    </section>
  );
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error ?? new Error("file_read_failed"));
    reader.readAsDataURL(file);
  });
}

function ConnectionDetailPanel({
  card,
  readinessState,
  sessionDecision,
  authorizationDecision,
  sessionLoading,
  readinessLoading,
  authorizationLoading,
  disconnectState,
  actionInventoryState,
  readinessError,
  actionInventoryError,
  sessionError,
  authorizationError,
  connectionList,
  onRefreshReadiness,
  onRequestSession,
  onRequestAuthorization,
  onRefreshConnections,
  onRefreshActionInventory,
  onDisconnectConnection,
}: {
  card: CatalogCard | null;
  readinessState?: ProviderActivationReadinessState;
  sessionDecision?: WiiiConnectSessionStartDecision;
  authorizationDecision?: WiiiConnectAuthorizationUrlDecision;
  sessionLoading?: boolean;
  readinessLoading?: boolean;
  authorizationLoading?: boolean;
  disconnectState?: ProviderDisconnectState;
  actionInventoryState?: ProviderActionInventoryState;
  readinessError?: string;
  actionInventoryError?: string;
  sessionError?: string;
  authorizationError?: string;
  connectionList?: ProviderConnectionListState;
  onRefreshReadiness?: (card: CatalogCard) => Promise<unknown>;
  onRequestSession?: (card: CatalogCard) => Promise<void>;
  onRequestAuthorization?: (card: CatalogCard) => Promise<void>;
  onRefreshConnections?: (card: CatalogCard) => Promise<unknown>;
  onRefreshActionInventory?: (card: CatalogCard) => Promise<unknown>;
  onDisconnectConnection?: (
    card: CatalogCard,
    connection: WiiiConnectProviderConnectionRecord,
  ) => Promise<void>;
}) {
  if (!card) {
    return (
      <aside className="rounded-lg border border-dashed border-[var(--border)] bg-surface-secondary p-4 text-sm text-text-secondary">
        Chọn một kết nối để xem trạng thái, scope và điều kiện bật.
      </aside>
    );
  }

  const Icon = card.icon;
  const canRequestSession =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(onRequestSession);
  const canRequestAuthorization =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(onRequestAuthorization);
  const canRefreshConnections =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(onRefreshConnections);
  const canRefreshReadiness =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(onRefreshReadiness);
  const canRefreshActionInventory =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(onRefreshActionInventory);
  const providerConnection = primaryProviderConnection(connectionList?.response);
  const readiness = readinessState?.response;
  const canDisconnectConnection =
    card.provider !== "wiii_native" &&
    card.registrySource === "backend" &&
    Boolean(providerConnectionRef(providerConnection)) &&
    providerConnection?.state !== "disabled" &&
    Boolean(onDisconnectConnection);

  return (
    <aside className="rounded-lg border border-[var(--border)] bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-secondary text-text-secondary">
            <Icon size={19} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-text">{card.label}</h3>
            <p className="mt-1 text-sm text-text-secondary">{card.description}</p>
          </div>
        </div>
        <StatusPill tone={card.tone}>{card.status}</StatusPill>
      </div>

      <dl className="mt-4 grid gap-2 text-xs">
        {card.detailRows.map(([label, value]) => (
          <div key={`${card.id}-${label}`} className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-text-tertiary">{label}</dt>
            <dd className="mt-0.5 break-words font-medium text-text">{value}</dd>
          </div>
        ))}
      </dl>

      <ProviderLifecyclePanel
        card={card}
        readiness={readiness}
        providerConnection={providerConnection}
        connectionList={connectionList}
        authorizationDecision={authorizationDecision}
        authorizationLoading={authorizationLoading}
        authorizationError={authorizationError}
        disconnectState={disconnectState}
      />

      {(actionInventoryState || canRefreshActionInventory) && (
        <EffectiveActionInventoryPanel inventoryState={actionInventoryState} />
      )}

      {card.requirements && card.requirements.length > 0 && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-text-tertiary">
            <Lock size={13} aria-hidden="true" />
            Điều kiện bật
          </div>
          <ul className="space-y-1.5 text-sm text-text-secondary">
            {card.requirements.map((requirement) => (
              <li key={`${card.id}-${requirement}`} className="flex gap-2">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400" aria-hidden="true" />
                <span>{requirement}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(readinessState || canRefreshReadiness) && (
        <div
          className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3"
          data-testid="wiii-connect-readiness-panel"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Activation readiness
            </div>
            <StatusPill tone={activationReadinessTone(readiness)}>
              {readiness?.status ?? (readinessState?.loading ? "đang đọc" : "chưa đọc")}
            </StatusPill>
          </div>

          <dl className="grid gap-2 text-xs sm:grid-cols-2">
            <div className="rounded-md bg-surface px-2 py-2">
              <dt className="text-text-tertiary">Connect-ready</dt>
              <dd className="mt-0.5 font-medium text-text">
                {readinessBooleanLabel(readiness?.ready_to_connect)}
              </dd>
            </div>
            <div className="rounded-md bg-surface px-2 py-2">
              <dt className="text-text-tertiary">
                {readinessReadyForReadonly(readiness) ||
                readinessActionMutation(readiness) === "read" ||
                cardDefaultActionIsReadonly(card)
                  ? "Agent read-only"
                  : "Agent action"}
              </dt>
              <dd className="mt-0.5 font-medium text-text">
                {readinessBooleanLabel(readinessReadyForAction(readiness))}
              </dd>
            </div>
            <div className="rounded-md bg-surface px-2 py-2">
              <dt className="text-text-tertiary">Connection</dt>
              <dd className="mt-0.5 font-medium text-text">
                {readiness?.connection?.present
                  ? statusLabel(readiness.connection.state)
                  : "Chưa có account"}
              </dd>
            </div>
            <div className="rounded-md bg-surface px-2 py-2">
              <dt className="text-text-tertiary">Gateway</dt>
              <dd className="mt-0.5 font-medium text-text">
                {compactText(readiness?.execution_gateway?.status, "Chưa đánh giá")}
              </dd>
            </div>
          </dl>

          {readiness?.gates && readiness.gates.length > 0 && (
            <ul className="mt-3 grid gap-2">
              {readiness.gates.map((gate) => (
                <li
                  key={`${card.id}-readiness-${gate.key}`}
                  className="rounded-md border border-[var(--border)] bg-surface px-2 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium text-text">
                      {readinessGateLabel(gate.key)}
                    </span>
                    <StatusPill tone={readinessGateTone(gate)}>
                      {gate.ready ? "ok" : "blocked"}
                    </StatusPill>
                  </div>
                  <div className="mt-1 break-words text-xs text-text-tertiary">
                    {compactText(gate.reason)}
                  </div>
                  {gate.required_next && gate.required_next.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {gate.required_next.slice(0, 3).map((item) => (
                        <span
                          key={`${card.id}-readiness-${gate.key}-${item}`}
                          className="rounded-md border border-[var(--border)] px-2 py-1 text-xs text-text-secondary"
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {readinessState?.lastFetchedAt && (
            <p className="mt-2 text-xs text-text-tertiary">
              Cập nhật {formatDateTime(readinessState.lastFetchedAt)}
            </p>
          )}
        </div>
      )}

      {sessionDecision && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Quyết định backend
            </div>
            <StatusPill tone={sessionDecisionTone(sessionDecision)}>
              {sessionDecision.status}
            </StatusPill>
          </div>
          <dl className="grid gap-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Lý do</dt>
              <dd className="mt-0.5 font-medium text-text">{sessionDecision.reason}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Authorization URL</dt>
              <dd className="mt-0.5 font-medium text-text">
                {sessionDecision.authorization_url ? "Sẵn sàng từ backend" : "Không phát hành"}
              </dd>
            </div>
          </dl>
          {sessionDecision.required_next && sessionDecision.required_next.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {sessionDecision.required_next.map((requirement) => (
                <span
                  key={`${card.id}-decision-${requirement}`}
                  className="rounded-md border border-[var(--border)] bg-surface px-2 py-1 text-xs text-text-secondary"
                >
                  {requirement}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {authorizationDecision && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Connect Link backend
            </div>
            <StatusPill tone={sessionDecisionTone(authorizationDecision)}>
              {authorizationDecision.status}
            </StatusPill>
          </div>
          <dl className="grid gap-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Lý do</dt>
              <dd className="mt-0.5 font-medium text-text">{authorizationDecision.reason}</dd>
            </div>
            <div>
              <dt className="text-text-tertiary">URL</dt>
              <dd className="mt-0.5 font-medium text-text">
                {authorizationDecision.authorization_url ? "Backend đã cấp URL" : "Không phát hành"}
              </dd>
            </div>
          </dl>
          {authorizationDecision.required_next && authorizationDecision.required_next.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {authorizationDecision.required_next.map((requirement) => (
                <span
                  key={`${card.id}-auth-${requirement}`}
                  className="rounded-md border border-[var(--border)] bg-surface px-2 py-1 text-xs text-text-secondary"
                >
                  {requirement}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {connectionList && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Connection thật
            </div>
            <StatusPill tone={providerConnectionTone(providerConnection, connectionList.response)}>
              {providerConnection ? statusLabel(providerConnection.state) : connectionList.response?.status ?? "chưa đọc"}
            </StatusPill>
          </div>
          <dl className="grid gap-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Account</dt>
              <dd className="mt-0.5 font-medium text-text">
                {providerConnectionSummary(providerConnection)}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Lý do</dt>
              <dd className="mt-0.5 font-medium text-text">
                {connectionList.response?.reason ?? connectionList.error ?? "Chưa có"}
              </dd>
            </div>
            {connectionList.lastFetchedAt && (
              <div>
                <dt className="text-text-tertiary">Làm mới</dt>
                <dd className="mt-0.5 font-medium text-text">
                  {formatDateTime(connectionList.lastFetchedAt)}
                </dd>
              </div>
            )}
          </dl>
          {providerConnection?.warnings && providerConnection.warnings.length > 0 && (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-2 py-2 text-xs text-amber-800">
              {providerConnection.warnings.length} cảnh báo trong connection này.
            </div>
          )}
        </div>
      )}

      <FacebookPostComposer
        card={card}
        providerConnection={providerConnection}
        readiness={readiness}
        onRefreshConnections={onRefreshConnections}
      />

      {sessionError && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {sessionError}
        </div>
      )}

      {authorizationError && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {authorizationError}
        </div>
      )}

      {connectionList?.error && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {connectionList.error}
        </div>
      )}

      {readinessError && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {readinessError}
        </div>
      )}

      {actionInventoryError && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {actionInventoryError}
        </div>
      )}

      {disconnectState?.response && (
        <div className="mt-4 rounded-md border border-[var(--border)] bg-surface-secondary px-3 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-text-tertiary">
              Ngắt kết nối
            </div>
            <span data-testid="wiii-connect-disconnect-status">
              <StatusPill tone={disconnectResultTone(disconnectState.response)}>
                {disconnectState.response.local_disabled ? "Đã khóa local" : disconnectState.response.status}
              </StatusPill>
            </span>
          </div>
          <dl className="grid gap-2 text-xs">
            <div>
              <dt className="text-text-tertiary">Lý do</dt>
              <dd className="mt-0.5 font-medium text-text">
                {disconnectState.response.reason}
              </dd>
            </div>
            <div>
              <dt className="text-text-tertiary">Provider cleanup</dt>
              <dd className="mt-0.5 font-medium text-text">
                {disconnectState.response.status === "succeeded" ? "Đã gửi yêu cầu" : "Chờ xử lý"}
              </dd>
            </div>
            {disconnectState.lastUpdatedAt && (
              <div>
                <dt className="text-text-tertiary">Cập nhật</dt>
                <dd className="mt-0.5 font-medium text-text">
                  {formatDateTime(disconnectState.lastUpdatedAt)}
                </dd>
              </div>
            )}
          </dl>
        </div>
      )}

      {disconnectState?.error && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {disconnectState.error}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!canRefreshReadiness || readinessLoading}
          onClick={() => {
            if (canRefreshReadiness) void onRefreshReadiness?.(card);
          }}
          className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium ${
            canRefreshReadiness
              ? "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          <RefreshCw
            size={14}
            className={readinessLoading ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Kiểm tra readiness
        </button>

        <button
          type="button"
          disabled={!canRequestAuthorization || authorizationLoading}
          onClick={() => {
            if (canRequestAuthorization) void onRequestAuthorization?.(card);
          }}
          className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium ${
            canRequestAuthorization
              ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          {authorizationLoading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <ExternalLink size={14} aria-hidden="true" />
          )}
          {card.provider === "wiii_native"
            ? "Quan sát từ runtime"
            : canRequestAuthorization
              ? authorizationLoading
                ? "Đang mở..."
                : "Kết nối qua Wiii"
              : "Chưa thể kết nối"}
        </button>

        <button
          type="button"
          disabled={!canRefreshConnections || connectionList?.loading}
          onClick={() => {
            if (canRefreshConnections) void onRefreshConnections?.(card);
          }}
          className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium ${
            canRefreshConnections
              ? "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          <RefreshCw
            size={14}
            className={connectionList?.loading ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Làm mới trạng thái
        </button>

        <button
          type="button"
          data-testid="wiii-connect-disconnect-button"
          disabled={!canDisconnectConnection || disconnectState?.loading}
          onClick={() => {
            if (canDisconnectConnection && providerConnection) {
              void onDisconnectConnection?.(card, providerConnection);
            }
          }}
          className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium ${
            canDisconnectConnection
              ? "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          {disconnectState?.loading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <Unplug size={14} aria-hidden="true" />
          )}
          {disconnectState?.loading
            ? "Đang ngắt..."
            : providerConnection?.state === "disabled"
              ? "Đã ngắt"
              : "Ngắt kết nối"}
        </button>

        <button
          type="button"
          disabled={!canRequestSession || sessionLoading}
          onClick={() => {
            if (canRequestSession) void onRequestSession?.(card);
          }}
          className={`inline-flex h-9 items-center justify-center rounded-md border px-3 text-sm font-medium ${
            canRequestSession
              ? "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          {sessionLoading ? "Đang kiểm tra..." : "Kiểm tra policy"}
        </button>

        <button
          type="button"
          disabled={!canRefreshActionInventory || actionInventoryState?.loading}
          onClick={() => {
            if (canRefreshActionInventory) void onRefreshActionInventory?.(card);
          }}
          className={`inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-sm font-medium ${
            canRefreshActionInventory
              ? "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
              : "border-[var(--border)] bg-surface-secondary text-text-tertiary"
          }`}
        >
          <RefreshCw
            size={14}
            className={actionInventoryState?.loading ? "animate-spin" : ""}
            aria-hidden="true"
          />
          Đồng bộ actions
        </button>
      </div>
      <p className="mt-2 text-xs text-text-tertiary">
        {card.disabledReason ?? card.statusDetail}
      </p>
    </aside>
  );
}

function ConnectionCatalog({
  snapshot,
  fallbackModel,
  providerRegistry,
  providerRegistryLoaded,
  onRuntimeRefresh,
}: {
  snapshot: WiiiConnectRuntimeSnapshot | null;
  fallbackModel: CapabilityStatusViewModel;
  providerRegistry: WiiiConnectProviderRegistryEntry[] | null;
  providerRegistryLoaded: boolean;
  onRuntimeRefresh?: () => Promise<unknown>;
}) {
  const [provider, setProvider] = useState<ProviderFilter>("wiii_native");
  const [category, setCategory] = useState<CatalogCategory>("all");
  const [query, setQuery] = useState("");
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [sessionDecisions, setSessionDecisions] = useState<
    Record<string, WiiiConnectSessionStartDecision>
  >({});
  const [authorizationDecisions, setAuthorizationDecisions] = useState<
    Record<string, WiiiConnectAuthorizationUrlDecision>
  >({});
  const [sessionErrors, setSessionErrors] = useState<Record<string, string>>({});
  const [authorizationErrors, setAuthorizationErrors] = useState<Record<string, string>>({});
  const [sessionLoadingSlug, setSessionLoadingSlug] = useState<string | null>(null);
  const [authorizationLoadingSlug, setAuthorizationLoadingSlug] = useState<string | null>(null);
  const [providerReadinessStates, setProviderReadinessStates] = useState<
    Record<string, ProviderActivationReadinessState>
  >({});
  const [providerActionInventories, setProviderActionInventories] = useState<
    Record<string, ProviderActionInventoryState>
  >({});
  const [providerConnectionLists, setProviderConnectionLists] = useState<
    Record<string, ProviderConnectionListState>
  >({});
  const [disconnectStates, setDisconnectStates] = useState<
    Record<string, ProviderDisconnectState>
  >({});
  const connectionPollTokenRef = useRef(0);

  useEffect(() => {
    return () => {
      connectionPollTokenRef.current += 1;
    };
  }, []);

  const cards = useMemo(
    () =>
      buildConnectionCatalogCards(
        snapshot,
        fallbackModel,
        providerRegistry,
        providerConnectionLists,
        providerReadinessStates,
      ),
    [snapshot, fallbackModel, providerRegistry, providerConnectionLists, providerReadinessStates],
  );

  const normalizedQuery = query.trim().toLowerCase();
  const filteredCards = cards.filter((card) => {
    if (card.provider !== provider) return false;
    if (category !== "all" && card.category !== category) return false;
    if (!normalizedQuery) return true;
    return [card.label, card.description, card.categoryLabel, card.providerLabel]
      .join(" ")
      .toLowerCase()
      .includes(normalizedQuery);
  });

  const selectedCard =
    filteredCards.find((card) => card.id === selectedCardId) ?? filteredCards[0] ?? null;

  const refreshActivationReadiness = async (
    card: CatalogCard,
    connection?: WiiiConnectProviderConnectionRecord | null,
  ): Promise<WiiiConnectActivationReadinessResponse | null> => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return null;
    const slug = card.providerSlug;
    const selectedConnection =
      connection ?? primaryProviderConnection(providerConnectionLists[slug]?.response);
    setProviderReadinessStates((current) => ({
      ...current,
      [slug]: {
        ...current[slug],
        loading: true,
        error: undefined,
      },
    }));
    try {
      const response = await fetchWiiiConnectProviderActivationReadiness(slug, {
        actionSlug: defaultActivationActionSlug(card),
        connectionRef: providerConnectionRef(selectedConnection),
        probeDatabase: true,
      });
      setProviderReadinessStates((current) => ({
        ...current,
        [slug]: {
          response,
          loading: false,
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      return response;
    } catch {
      setProviderReadinessStates((current) => ({
        ...current,
        [slug]: {
          ...current[slug],
          loading: false,
          error: "Không thể đọc activation readiness từ backend.",
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      return null;
    }
  };

  const refreshActionInventory = async (
    card: CatalogCard,
    connection?: WiiiConnectProviderConnectionRecord | null,
  ): Promise<WiiiConnectEffectiveActionInventoryResponse | null> => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return null;
    const slug = card.providerSlug;
    const selectedConnection =
      connection ?? primaryProviderConnection(providerConnectionLists[slug]?.response);
    setProviderActionInventories((current) => ({
      ...current,
      [slug]: {
        ...current[slug],
        loading: true,
        error: undefined,
      },
    }));
    try {
      const response = await fetchWiiiConnectProviderEffectiveActions(slug, {
        connectionRef: providerConnectionRef(selectedConnection),
        probeDatabase: true,
      });
      setProviderActionInventories((current) => ({
        ...current,
        [slug]: {
          response,
          loading: false,
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      return response;
    } catch {
      setProviderActionInventories((current) => ({
        ...current,
        [slug]: {
          ...current[slug],
          loading: false,
          error: "Không thể đọc effective action inventory từ backend.",
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      return null;
    }
  };

  useEffect(() => {
    if (
      !selectedCard ||
      selectedCard.provider === "wiii_native" ||
      selectedCard.registrySource !== "backend"
    ) {
      return;
    }
    const slug = selectedCard.providerSlug;
    const connectionState = providerConnectionLists[slug];
    if (connectionState?.loading) return;
    if (!connectionState?.response && !connectionState?.error) {
      void refreshProviderConnections(selectedCard).then((response) => {
        if (!response) void refreshActivationReadiness(selectedCard);
      });
      return;
    }
    const readinessState = providerReadinessStates[slug];
    if (!readinessState?.loading && !readinessState?.response && !readinessState?.error) {
      void refreshActivationReadiness(selectedCard);
    }
    const inventoryState = providerActionInventories[slug];
    if (!inventoryState?.loading && !inventoryState?.response && !inventoryState?.error) {
      void refreshActionInventory(selectedCard);
    }
  }, [
    selectedCard?.id,
    selectedCard?.provider,
    selectedCard?.providerSlug,
    selectedCard?.registrySource,
    providerConnectionLists[selectedCard?.providerSlug ?? ""]?.loading,
    providerConnectionLists[selectedCard?.providerSlug ?? ""]?.response,
    providerConnectionLists[selectedCard?.providerSlug ?? ""]?.error,
    providerReadinessStates[selectedCard?.providerSlug ?? ""]?.loading,
    providerReadinessStates[selectedCard?.providerSlug ?? ""]?.response,
    providerReadinessStates[selectedCard?.providerSlug ?? ""]?.error,
    providerActionInventories[selectedCard?.providerSlug ?? ""]?.loading,
    providerActionInventories[selectedCard?.providerSlug ?? ""]?.response,
    providerActionInventories[selectedCard?.providerSlug ?? ""]?.error,
  ]);

  const requestSessionDecision = async (card: CatalogCard) => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return;
    const slug = card.providerSlug;
    setSessionLoadingSlug(slug);
    setSessionErrors((current) => {
      const next = { ...current };
      delete next[slug];
      return next;
    });
    try {
      const decision = await startWiiiConnectProviderSession(slug, {
        surface: "desktop",
        requested_scopes: { read: true },
        request_metadata: {
          source: "wiii_connect_page",
          provider: card.provider,
        },
      });
      setSessionDecisions((current) => ({ ...current, [slug]: decision }));
    } catch {
      setSessionErrors((current) => ({
        ...current,
        [slug]: "Không thể kiểm tra kết nối từ backend.",
      }));
    } finally {
      setSessionLoadingSlug((current) => (current === slug ? null : current));
    }
  };

  const refreshProviderConnections = async (
    card: CatalogCard,
  ): Promise<WiiiConnectProviderConnectionListResponse | null> => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return null;
    const slug = card.providerSlug;
    setProviderConnectionLists((current) => ({
      ...current,
      [slug]: {
        ...current[slug],
        loading: true,
        error: undefined,
      },
    }));
    try {
      const response = await fetchWiiiConnectProviderConnections(slug, {
        probeDatabase: true,
      });
      setProviderConnectionLists((current) => ({
        ...current,
        [slug]: {
          response,
          loading: false,
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      void refreshActivationReadiness(card, primaryProviderConnection(response));
      void refreshActionInventory(card, primaryProviderConnection(response));
      void onRuntimeRefresh?.();
      return response;
    } catch {
      setProviderConnectionLists((current) => ({
        ...current,
        [slug]: {
          ...current[slug],
          loading: false,
          error: "Không thể đọc trạng thái connection từ backend.",
          lastFetchedAt: new Date().toISOString(),
        },
      }));
      return null;
    }
  };

  const disconnectProviderConnection = async (
    card: CatalogCard,
    connection: WiiiConnectProviderConnectionRecord,
  ) => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return;
    const slug = card.providerSlug;
    connectionPollTokenRef.current += 1;
    setDisconnectStates((current) => ({
      ...current,
      [slug]: {
        ...current[slug],
        loading: true,
        error: undefined,
      },
    }));
    try {
      const response = await disconnectWiiiConnectProviderConnection(
        slug,
        providerConnectionRef(connection),
      );
      setDisconnectStates((current) => ({
        ...current,
        [slug]: {
          response,
          loading: false,
          lastUpdatedAt: new Date().toISOString(),
        },
      }));
      if (response.local_disabled) {
        const disabledConnection = locallyDisabledConnection(
          connection,
          "user_disconnect_requested",
        );
        setProviderConnectionLists((current) => ({
          ...current,
          [slug]: {
            ...current[slug],
            response: responseWithLocallyDisabledConnection(
              current[slug]?.response,
              connection,
              "user_disconnect_requested",
            ),
            loading: false,
            lastFetchedAt: new Date().toISOString(),
          },
        }));
        void refreshActivationReadiness(card, disabledConnection);
        void refreshActionInventory(card, disabledConnection);
        void onRuntimeRefresh?.();
      }
    } catch {
      setDisconnectStates((current) => ({
        ...current,
        [slug]: {
          ...current[slug],
          loading: false,
          error: "Không thể ngắt kết nối từ backend.",
          lastUpdatedAt: new Date().toISOString(),
        },
      }));
    }
  };

  const pollProviderConnectionsAfterAuthorization = async (card: CatalogCard) => {
    const pollToken = connectionPollTokenRef.current + 1;
    connectionPollTokenRef.current = pollToken;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      if (attempt > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
      }
      if (connectionPollTokenRef.current !== pollToken) return;
      const response = await refreshProviderConnections(card);
      if (connectionPollTokenRef.current !== pollToken) return;
      if (response?.connections.some((connection) => connection.state === "connected" || connection.active)) {
        return;
      }
    }
  };

  const requestAuthorizationUrl = async (card: CatalogCard) => {
    if (card.provider === "wiii_native" || card.registrySource !== "backend") return;
    const slug = card.providerSlug;
    setAuthorizationLoadingSlug(slug);
    setAuthorizationErrors((current) => {
      const next = { ...current };
      delete next[slug];
      return next;
    });
    try {
      const decision = await createWiiiConnectProviderAuthorizationUrl(slug, {
        surface: "desktop",
        redirect_uri: buildWiiiConnectProviderCallbackUrl(slug),
        probe_database: true,
        requested_scopes: { read: true },
        request_metadata: {
          source: "wiii_connect_page",
          provider: card.provider,
        },
      });
      setAuthorizationDecisions((current) => ({ ...current, [slug]: decision }));
      if (decision.status === "ready" && decision.authorization_url) {
        await openExternalUrl(decision.authorization_url);
        void pollProviderConnectionsAfterAuthorization(card);
      }
    } catch {
      setAuthorizationErrors((current) => ({
        ...current,
        [slug]: "Không thể bắt đầu Connect Link từ backend.",
      }));
    } finally {
      setAuthorizationLoadingSlug((current) => (current === slug ? null : current));
    }
  };

  return (
    <section className="space-y-4">
      <div className="rounded-lg border border-[var(--border)] bg-surface p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <PlugZap size={16} className="text-text-secondary" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-text">Danh bạ kết nối</h2>
            </div>
            <p className="mt-1 max-w-3xl text-sm text-text-secondary">
              Danh bạ kết nối giống OpenHuman: chọn provider trước, xem trạng thái thật,
              rồi mới mở adapter khi Wiii có vault, permission gate và audit.
            </p>
          </div>
          <StatusPill tone={providerRegistryLoaded || snapshot ? "ok" : "pending"}>
            {providerRegistryLoaded
              ? "Registry backend"
              : snapshot
                ? "Đọc từ snapshot backend"
                : "Đang dùng fallback local"}
          </StatusPill>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {providerFilters.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setProvider(item.id);
                setSelectedCardId(null);
              }}
              className={`inline-flex min-h-9 items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                provider === item.id
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
              }`}
              aria-pressed={provider === item.id}
            >
              <span>{item.label}</span>
              <span className="hidden text-xs font-normal text-text-tertiary sm:inline">
                {item.hint}
              </span>
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(240px,420px)_1fr]">
          <label className="relative block">
            <span className="sr-only">Tìm kết nối</span>
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
              aria-hidden="true"
            />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-surface-secondary pl-9 pr-3 text-sm text-text outline-none focus:border-primary"
              placeholder="Tìm kết nối..."
            />
          </label>

          <div className="flex flex-wrap gap-2">
            {categoryFilters.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setCategory(item.id);
                  setSelectedCardId(null);
                }}
                className={`inline-flex min-h-9 items-center rounded-md border px-3 py-1.5 text-sm ${
                  category === item.id
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-[var(--border)] bg-surface-secondary text-text-secondary hover:text-text"
                }`}
                aria-pressed={category === item.id}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          {filteredCards.map((card) => {
            const Icon = card.icon;
            const selected = selectedCard?.id === card.id;
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => setSelectedCardId(card.id)}
                className={`min-h-[168px] rounded-lg border bg-surface p-4 text-left transition-colors ${
                  selected
                    ? "border-primary/50 ring-2 ring-primary/10"
                    : "border-[var(--border)] hover:border-primary/30"
                }`}
                aria-pressed={selected}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-secondary text-text-secondary">
                      <Icon size={19} aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold text-text">{card.label}</h3>
                      <p className="mt-0.5 truncate text-xs text-text-tertiary">
                        {card.providerLabel} · {card.categoryLabel}
                      </p>
                    </div>
                  </div>
                  <StatusPill tone={card.tone}>{card.status}</StatusPill>
                </div>
                <p className="mt-3 line-clamp-2 text-sm text-text-secondary">
                  {card.description}
                </p>
                <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
                  <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                    <div className="text-text-tertiary">Agent-ready</div>
                    <div className="mt-0.5 truncate font-medium text-text">
                      {card.agentReady ? "Có" : "Chưa"}
                    </div>
                  </div>
                  <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                    <div className="text-text-tertiary">Điều khiển</div>
                    <div className="mt-0.5 truncate font-medium text-text">
                      {externalControlLabel(card)}
                    </div>
                  </div>
                </div>
              </button>
            );
          })}

          {filteredCards.length === 0 && (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-surface-secondary px-4 py-8 text-sm text-text-secondary sm:col-span-2 2xl:col-span-3">
              Không tìm thấy kết nối phù hợp với bộ lọc hiện tại.
            </div>
          )}
        </div>

        <ConnectionDetailPanel
          card={selectedCard}
          readinessState={
            selectedCard ? providerReadinessStates[selectedCard.providerSlug] : undefined
          }
          sessionDecision={selectedCard ? sessionDecisions[selectedCard.providerSlug] : undefined}
          authorizationDecision={selectedCard ? authorizationDecisions[selectedCard.providerSlug] : undefined}
          sessionLoading={selectedCard ? sessionLoadingSlug === selectedCard.providerSlug : false}
          readinessLoading={
            selectedCard
              ? Boolean(providerReadinessStates[selectedCard.providerSlug]?.loading)
              : false
          }
          authorizationLoading={selectedCard ? authorizationLoadingSlug === selectedCard.providerSlug : false}
          disconnectState={selectedCard ? disconnectStates[selectedCard.providerSlug] : undefined}
          actionInventoryState={selectedCard ? providerActionInventories[selectedCard.providerSlug] : undefined}
          readinessError={
            selectedCard ? providerReadinessStates[selectedCard.providerSlug]?.error : undefined
          }
          actionInventoryError={
            selectedCard ? providerActionInventories[selectedCard.providerSlug]?.error : undefined
          }
          sessionError={selectedCard ? sessionErrors[selectedCard.providerSlug] : undefined}
          authorizationError={selectedCard ? authorizationErrors[selectedCard.providerSlug] : undefined}
          connectionList={selectedCard ? providerConnectionLists[selectedCard.providerSlug] : undefined}
          onRefreshReadiness={refreshActivationReadiness}
          onRequestSession={requestSessionDecision}
          onRequestAuthorization={requestAuthorizationUrl}
          onRefreshConnections={refreshProviderConnections}
          onRefreshActionInventory={refreshActionInventory}
          onDisconnectConnection={disconnectProviderConnection}
        />
      </div>
    </section>
  );
}

function ConnectionsGrid({
  connections,
  snapshot,
}: {
  connections: WiiiConnectRuntimeConnection[];
  snapshot: WiiiConnectRuntimeSnapshot | null;
}) {
  if (connections.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border)] bg-surface-secondary px-4 py-8 text-sm text-text-secondary">
        Chưa có snapshot Wiii Connect từ backend. Trang đang chờ lượt chat runtime tiếp theo.
      </div>
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {connections.map((connection) => {
        const Icon = connectionIconBySlug[connection.slug] ?? Network;
        const tone = connectionTone(connection);
        const counts = connectionCounts(connection);
        return (
          <article
            key={`${connection.provider_kind ?? "provider"}-${connection.slug}`}
            className="min-w-0 rounded-lg border border-[var(--border)] bg-surface p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-secondary text-text-secondary">
                  <Icon size={18} aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-text">
                    {connection.label || connection.slug}
                  </h3>
                  <p className="mt-0.5 truncate text-xs text-text-tertiary">
                    {providerKindLabels[connection.provider_kind ?? ""] ?? compactText(connection.provider_kind, "Provider")}
                  </p>
                </div>
              </div>
              <StatusPill tone={tone}>{statusLabel(connection.status)}</StatusPill>
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
              <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                <dt className="text-text-tertiary">Agent-ready</dt>
                <dd className="mt-0.5 truncate font-medium text-text">
                  {connection.agent_ready ? "Có" : "Chưa"}
                </dd>
              </div>
              <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                <dt className="text-text-tertiary">Scope</dt>
                <dd className="mt-0.5 truncate font-medium text-text">
                  {scopeSummary(connection.scopes)}
                </dd>
              </div>
              <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                <dt className="text-text-tertiary">Capability</dt>
                <dd className="mt-0.5 truncate font-medium text-text">
                  {capabilityCount(connection)}
                </dd>
              </div>
              <div className="min-w-0 rounded-md bg-surface-secondary px-2 py-2">
                <dt className="text-text-tertiary">Path dùng</dt>
                <dd className="mt-0.5 truncate font-medium text-text">
                  {pathList(connection.required_for_paths)}
                </dd>
              </div>
            </dl>

            <div className="mt-3 space-y-1.5 text-xs text-text-secondary">
              <div className="flex min-w-0 justify-between gap-3">
                <span className="shrink-0 text-text-tertiary">Nguồn</span>
                <span className="truncate">{compactText(connection.source)}</span>
              </div>
              <div className="flex min-w-0 justify-between gap-3">
                <span className="shrink-0 text-text-tertiary">Kiểm tra</span>
                <span className="truncate">{formatDateTime(connection.last_checked_at)}</span>
              </div>
              {counts && (
                <div className="flex min-w-0 justify-between gap-3">
                  <span className="shrink-0 text-text-tertiary">Tài nguyên</span>
                  <span className="truncate">{counts}</span>
                </div>
              )}
              {connection.reason && (
                <div className="flex min-w-0 justify-between gap-3">
                  <span className="shrink-0 text-text-tertiary">Lý do</span>
                  <span className="truncate">{compactText(connection.reason)}</span>
                </div>
              )}
            </div>

            {connection.warnings && connection.warnings.length > 0 && (
              <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-2 py-2 text-xs text-amber-800">
                {connection.warnings.length} cảnh báo trong connection này.
              </div>
            )}
          </article>
        );
      })}

      {snapshot?.warnings && snapshot.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 md:col-span-2 xl:col-span-3">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={16} aria-hidden="true" />
            Snapshot có {snapshot.warnings.length} cảnh báo cần kiểm tra.
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderRoadmap() {
  return (
    <section className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <Lock size={16} className="text-text-secondary" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-text">Provider adapter chưa bật</h3>
      </div>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-surface">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
            <tr>
              <th className="px-3 py-2 font-medium">Provider</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 font-medium">Trạng thái</th>
              <th className="px-3 py-2 font-medium">Ghi chú</th>
            </tr>
          </thead>
          <tbody>
            {externalProviderRows.map((row) => (
              <tr key={row.provider} className="border-b border-[var(--border)] last:border-b-0">
                <td className="px-3 py-3 font-medium text-text">{row.provider}</td>
                <td className="px-3 py-3 text-text-secondary">
                  {providerKindLabels[row.kind] ?? row.kind}
                </td>
                <td className="px-3 py-3">
                  <StatusPill tone="off">{row.state}</StatusPill>
                </td>
                <td className="px-3 py-3 text-text-secondary">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LocalRuntimeFallback({
  sections,
}: {
  sections: CapabilityDashboardSection[];
}) {
  return (
    <section className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <Activity size={16} className="text-text-secondary" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-text">Fallback cục bộ</h3>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sections.slice(0, 5).map((section) => (
          <article
            key={section.id}
            className="min-w-0 rounded-lg border border-[var(--border)] bg-surface p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h4 className="truncate text-sm font-semibold text-text">
                  {section.title}
                </h4>
                <p className="mt-0.5 truncate text-xs text-text-tertiary">
                  {section.summary}
                </p>
              </div>
              <StatusPill tone={section.tone}>{section.summary}</StatusPill>
            </div>
            <dl className="mt-3 grid gap-2 text-xs">
              {section.metrics.slice(0, 4).map((metric, index) => (
                <div
                  key={`${section.id}-${metric.label}-${index}`}
                  className="min-w-0 rounded-md bg-surface-secondary px-2 py-2"
                >
                  <dt className="text-text-tertiary">{metric.label}</dt>
                  <dd className="mt-0.5 truncate font-medium text-text">
                    {metric.value}
                  </dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function CapabilitySummaryPanel({
  snapshot,
}: {
  snapshot: WiiiConnectRuntimeSnapshot | null;
}) {
  const summary = snapshot?.capability_summary;
  if (!summary) return null;

  const rows: Array<[string, string]> = [
    ["Provider đã nối", pathList(summary.connected_provider_slugs)],
    ["Provider agent-ready", pathList(summary.agent_ready_provider_slugs)],
    ["Scope đã cấp", pathList(summary.connected_scope_names)],
    ["Path readiness", capabilityPathStatusSummary(snapshot)],
    ["Path cần chú ý", capabilityAttentionPath(snapshot)],
    ["Tool group bị chặn", pathList(summary.suppressed_tool_groups)],
  ];

  return (
    <section
      className="mb-4 rounded-lg border border-[var(--border)] bg-surface p-4"
      data-testid="wiii-connect-capability-summary"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text">Capability snapshot</h3>
          <p className="mt-0.5 truncate text-xs text-text-tertiary">
            Connection, scope, path-ready và tool suppression do backend snapshot sở hữu.
          </p>
        </div>
        <StatusPill
          tone={
            (summary.path_readiness ?? []).some((path) => path.status === "blocked")
              ? "warn"
              : "ok"
          }
        >
          {capabilityPathStatusSummary(snapshot)}
        </StatusPill>
      </div>
      <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label} className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-xs text-text-tertiary">{label}</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function PathPolicyTable({
  paths,
}: {
  paths: WiiiConnectRuntimePathCapability[];
}) {
  if (paths.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border)] bg-surface-secondary px-4 py-8 text-sm text-text-secondary">
        Chưa có path policy trong snapshot runtime.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-surface">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
          <tr>
            <th className="px-3 py-2 font-medium">Path</th>
            <th className="px-3 py-2 font-medium">Kết nối bắt buộc</th>
            <th className="px-3 py-2 font-medium">Tool group được phép</th>
            <th className="px-3 py-2 font-medium">Tool group bị chặn</th>
            <th className="px-3 py-2 font-medium">Mutation</th>
            <th className="px-3 py-2 font-medium">Delegation</th>
          </tr>
        </thead>
        <tbody>
          {paths.map((path) => (
            <tr key={path.path} className="border-b border-[var(--border)] last:border-b-0">
              <td className="px-3 py-3 font-medium text-text">{path.path}</td>
              <td className="px-3 py-3 text-text-secondary">
                {pathList(path.required_connection_slugs)}
              </td>
              <td className="px-3 py-3 text-text-secondary">
                {pathList(path.allowed_tool_groups)}
              </td>
              <td className="px-3 py-3 text-text-secondary">
                {pathList(path.forbidden_tool_groups)}
              </td>
              <td className="px-3 py-3">
                <StatusPill
                  tone={
                    path.mutation_policy === "approval_token_required" ||
                    path.mutation_policy === "explicit_user_confirmation_required"
                      ? "warn"
                      : path.mutation_policy === "preview_only"
                        ? "pending"
                        : "ok"
                  }
                >
                  {mutationPolicyLabels[path.mutation_policy ?? "none"] ?? compactText(path.mutation_policy)}
                </StatusPill>
              </td>
              <td className="px-3 py-3 text-text-secondary">
                {delegationPolicyLabels[path.delegation_policy ?? "direct_only"] ?? compactText(path.delegation_policy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecentRuntimeFlowDoctorPanel({
  report,
  error,
  historyReport,
  historyError,
  pruneReport,
  pruneLoading,
  pruneError,
  onPruneDryRun,
  onPruneApply,
}: {
  report: RuntimeFlowDoctorReport | null;
  error?: string;
  historyReport: RuntimeFlowDoctorHistoryReport | null;
  historyError?: string;
  pruneReport: RuntimeFlowSessionEventPruneReport | null;
  pruneLoading?: boolean;
  pruneError?: string;
  onPruneDryRun?: () => void;
  onPruneApply?: () => void;
}) {
  const alerts = report?.alerts?.slice(0, 4) ?? [];
  const routeEntries = countMapEntries(report?.routes);
  const finalizationEntries = countMapEntries(report?.finalization_statuses, 4);
  const warningEntries = countMapEntries(report?.context_warnings, 4);
  const subagentWarningEntries = countMapEntries(report?.subagents?.warnings, 4);
  const latestBuckets = report?.alert_trend?.buckets?.slice(0, 3) ?? [];
  const historyBuckets = historyReport?.buckets?.slice(0, 8) ?? [];
  const backend = safeRuntimeDoctorCounterLabel(report?.runtime_config?.session_event_log_backend);
  const lifecycle = report?.lifecycle_registrations;
  const postTurnLifecycle = report?.post_turn_lifecycle;
  const postTurnLifecycleLedger = report?.post_turn_lifecycle_ledger;
  const postTurnStatusEntries = countMapEntries(postTurnLifecycle?.post_turn?.status_counts, 4);
  const postTurnReasonEntries = countMapEntries(postTurnLifecycle?.post_turn?.reason_counts, 4);
  const postTurnPolicyEntries = countMapEntries(
    postTurnLifecycle?.post_turn?.semantic_memory_policy_counts,
    4,
  );
  const backgroundGroupEntries = countMapEntries(
    postTurnLifecycle?.background_tasks?.group_counts,
    4,
  );
  const backgroundStatusEntries = countMapEntries(
    postTurnLifecycle?.background_tasks?.status_counts,
    4,
  );
  const ledgerBackgroundGroupEntries = countMapEntries(
    postTurnLifecycleLedger?.background_schedule?.group_counts,
    4,
  );
  const ledgerBackgroundStatusEntries = countMapEntries(
    postTurnLifecycleLedger?.background_schedule?.status_counts,
    4,
  );
  const lifecycleOwnerFallback = Object.values(lifecycle?.owner_counts ?? {}).filter(
    (count) => typeof count === "number" && Number.isFinite(count),
  ).length;
  const lifecycleHookTotal =
    runtimeDoctorConfigNumber(report, "lifecycle_hook_total") ??
    lifecycle?.registration_count ??
    0;
  const lifecycleOwnerCount =
    runtimeDoctorConfigNumber(report, "lifecycle_hook_owner_count") ??
    lifecycleOwnerFallback;
  const lifecycleRunEndCount =
    runtimeDoctorConfigNumber(report, "lifecycle_on_run_end_hook_count") ??
    lifecycle?.point_counts?.["on_run_end"] ??
    0;
  const lifecycleRunErrorCount =
    runtimeDoctorConfigNumber(report, "lifecycle_on_run_error_hook_count") ??
    lifecycle?.point_counts?.["on_run_error"] ??
    0;
  const lifecycleDefaultStatus = lifecycle?.default_runtime_hooks?.installed
    ? "installed"
    : lifecycle
      ? "missing"
      : "unknown";
  const lifecycleDefaultTone: CapabilityStatusTone =
    lifecycleDefaultStatus === "installed" ? "ok" : lifecycle ? "warn" : "off";
  const lifecyclePrivacyStrategy = safeRuntimeDoctorCounterLabel(
    lifecycle?.privacy?.identifier_strategy,
  );
  const postTurnPrivacyStrategy = safeRuntimeDoctorCounterLabel(
    postTurnLifecycle?.privacy?.identifier_strategy,
  );
  const postTurnSchema = safeRuntimeDoctorCounterLabel(
    postTurnLifecycle?.version ?? RUNTIME_POST_TURN_LIFECYCLE_METRICS_SCHEMA,
  );
  const postTurnLedgerSchema = safeRuntimeDoctorCounterLabel(
    postTurnLifecycleLedger?.version ?? RUNTIME_POST_TURN_LIFECYCLE_LEDGER_SCHEMA,
  );
  const postTurnWindow = safeRuntimeDoctorCounterLabel(postTurnLifecycle?.source?.window);
  const postTurnScope = postTurnLifecycle?.source?.org_scoped ? "org-scoped" : "process-wide";
  const postTurnLedgerWindow =
    postTurnLifecycleLedger?.source?.window === "runtime_flow_ledger_events"
      ? "ledger_events"
      : safeRuntimeDoctorCounterLabel(postTurnLifecycleLedger?.source?.window);
  const postTurnLedgerPrivacyStrategy = safeRuntimeDoctorCounterLabel(
    postTurnLifecycleLedger?.privacy?.identifier_strategy,
  );
  const privacyStrategy = safeRuntimeDoctorCounterLabel(report?.privacy?.identifier_strategy);
  const historyPrivacyStrategy = safeRuntimeDoctorCounterLabel(
    historyReport?.privacy?.identifier_strategy,
  );
  const matchedCount = pruneReport?.matched_count ?? 0;
  const deletedCount = pruneReport?.deleted_count ?? 0;
  const canApplyPrune =
    Boolean(pruneReport?.dry_run) &&
    matchedCount > 0 &&
    !pruneLoading &&
    !error &&
    Boolean(report);
  const pruneStatus = pruneError
    ? "unavailable"
    : pruneReport?.status ?? "not_checked";
  const pruneTone: CapabilityStatusTone = pruneError
    ? "warn"
    : pruneReport?.status === "pruned"
      ? "ok"
      : pruneReport?.dry_run
        ? "pending"
        : "off";

  return (
    <section
      className="rounded-lg border border-[var(--border)] bg-surface p-4 lg:col-span-2"
      data-testid="wiii-connect-runtime-flow-doctor-panel"
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-text-secondary" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">Aggregate runtime doctor</h3>
          </div>
          <p className="mt-1 text-xs text-text-secondary">
            {error
              ? "Chưa đọc được aggregate doctor report từ backend."
              : report
                ? "Recent runtime-flow ledger events, aggregate counts only."
                : "Đang chờ aggregate doctor report từ backend."}
          </p>
        </div>
        <StatusPill tone={doctorStatusTone(report?.status)}>
          {report?.status ?? (error ? "unavailable" : "checking")}
        </StatusPill>
      </div>

      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Turns</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorMetric(report, "turn_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Done seen</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorMetric(report, "done_seen_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Missing request ID</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorCorrelationMetric(report, "missing_request_id_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Raw content flags</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorMetric(report, "raw_content_flag_count")}
          </dd>
        </div>
      </dl>

      <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Subagent reports</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorSubagentMetric(report, "report_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Dropped keys</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorSubagentMetric(report, "state_dropped_key_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Thinking dropped</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorSubagentMetric(report, "thinking_dropped_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Subagent raw flags</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {runtimeDoctorSubagentMetric(report, "raw_content_flag_count")}
          </dd>
        </div>
      </dl>

      <dl
        className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
        data-testid="wiii-connect-runtime-lifecycle-hooks"
      >
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Lifecycle hooks</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {lifecycleHookTotal} hooks / {lifecycleOwnerCount} owners
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Default hooks</dt>
          <dd className="mt-0.5">
            <StatusPill tone={lifecycleDefaultTone}>{lifecycleDefaultStatus}</StatusPill>
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Run hooks</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            end {lifecycleRunEndCount} / error {lifecycleRunErrorCount}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Hook privacy</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {lifecyclePrivacyStrategy}
          </dd>
        </div>
      </dl>

      <div
        className="mt-3 rounded-lg border border-[var(--border)] bg-surface-secondary p-3"
        data-testid="wiii-connect-runtime-post-turn-lifecycle"
      >
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text">Post-turn lifecycle</div>
            <p className="mt-1 text-xs text-text-secondary">
              Metrics {postTurnSchema} / ledger {postTurnLedgerSchema}
            </p>
          </div>
          <StatusPill tone={postTurnLifecycle ? "ok" : "off"}>
            {postTurnLifecycle ? "metrics" : "missing"}
          </StatusPill>
        </div>

        <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Post-turn events</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycle?.post_turn?.event_count ?? 0}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Background events</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycle?.background_tasks?.event_count ?? 0}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Metric window</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnWindow}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Metric scope</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnScope}
            </dd>
          </div>
        </dl>

        <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Durable events</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycleLedger?.event_count ?? 0}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Missing ledger</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycleLedger?.missing_count ?? 0}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Scheduled turns</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycleLedger?.background_tasks_scheduled_count ?? 0}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface px-3 py-2">
            <dt className="text-xs text-text-tertiary">Durable task count</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {postTurnLifecycleLedger?.background_schedule?.task_count ?? 0}
            </dd>
          </div>
        </dl>

        <div className="mt-3 grid gap-3 lg:grid-cols-5">
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Status</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {postTurnStatusEntries.length > 0 ? postTurnStatusEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃ´ng</li>}
            </ul>
          </div>
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Reasons</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {postTurnReasonEntries.length > 0 ? postTurnReasonEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃ´ng</li>}
            </ul>
          </div>
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Memory policy</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {postTurnPolicyEntries.length > 0 ? postTurnPolicyEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃ´ng</li>}
            </ul>
          </div>
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Task groups</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {backgroundGroupEntries.length > 0 ? backgroundGroupEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃ´ng</li>}
            </ul>
          </div>
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Task status</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {backgroundStatusEntries.length > 0 ? backgroundStatusEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃ´ng</li>}
            </ul>
          </div>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Durable task groups</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {ledgerBackgroundGroupEntries.length > 0 ? ledgerBackgroundGroupEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃƒÂ´ng</li>}
            </ul>
          </div>
          <div className="rounded-md bg-surface p-3">
            <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Durable task status</div>
            <ul className="space-y-1 text-sm text-text-secondary">
              {ledgerBackgroundStatusEntries.length > 0 ? ledgerBackgroundStatusEntries.map(([label, count], index) => (
                <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                  <span className="truncate">{label}</span>
                  <span className="font-medium text-text">{count}</span>
                </li>
              )) : <li>KhÃƒÂ´ng</li>}
            </ul>
          </div>
        </div>

        <div className="mt-2 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
          <div>
            Backend: {safeRuntimeDoctorCounterLabel(postTurnLifecycle?.source?.metrics_backend)}
          </div>
          <div>Privacy: {postTurnPrivacyStrategy}</div>
          <div>
            Raw content: {postTurnLifecycle?.privacy?.raw_content_included ? "true" : "false"}
          </div>
          <div>Ledger window: {postTurnLedgerWindow}</div>
          <div>Ledger privacy: {postTurnLedgerPrivacyStrategy}</div>
          <div>
            Ledger raw content: {postTurnLifecycleLedger?.privacy?.raw_content_included ? "true" : "false"}
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Routes</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {routeEntries.length > 0 ? routeEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>Không</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Finalization</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {finalizationEntries.length > 0 ? finalizationEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>Không</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Context warnings</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {warningEntries.length > 0 ? warningEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>Không</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Subagent warnings</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {subagentWarningEntries.length > 0 ? subagentWarningEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>KhÃ´ng</li>}
          </ul>
        </div>
      </div>

      {alerts.length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {alerts.map((alert, index) => (
            <div
              key={`${alert.code}-${index}`}
              className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
            >
              <div className="flex min-w-0 items-center justify-between gap-2">
                <span className="truncate font-medium">
                  {safeRuntimeDoctorCounterLabel(alert.code)}
                </span>
                <StatusPill tone={runtimeDoctorAlertTone(alert.severity)}>
                  {safeRuntimeDoctorCounterLabel(alert.severity)}
                </StatusPill>
              </div>
              <div className="mt-1 text-xs">
                count {typeof alert.count === "number" ? alert.count : 0}
              </div>
            </div>
          ))}
        </div>
      )}

      {latestBuckets.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)]">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
              <tr>
                <th className="px-3 py-2 font-medium">Bucket</th>
                <th className="px-3 py-2 font-medium">Turns</th>
                <th className="px-3 py-2 font-medium">Alerts</th>
                <th className="px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {latestBuckets.map((bucket) => (
                <tr key={bucket.bucket_start} className="border-b border-[var(--border)] last:border-b-0">
                  <td className="px-3 py-2 font-medium text-text">
                    {formatDateTime(bucket.bucket_start)}
                  </td>
                  <td className="px-3 py-2 text-text-secondary">{bucket.turn_count}</td>
                  <td className="px-3 py-2 text-text-secondary">
                    {countMapEntries(bucket.alert_counts, 3)
                      .map(([label, count]) => `${label} ${count}`)
                      .join(", ") || "Không"}
                  </td>
                  <td className="px-3 py-2 text-text-secondary">
                    {countMapEntries(bucket.status_counts, 3)
                      .map(([label, count]) => `${label} ${count}`)
                      .join(", ") || "Không"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 rounded-lg border border-[var(--border)] bg-surface-secondary p-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text">Doctor history</div>
            <p className="mt-1 text-xs text-text-secondary">
              Recent aggregate doctor reports grouped by event hour.
            </p>
          </div>
          <StatusPill tone={historyError ? "warn" : historyBuckets.length > 0 ? "ok" : "off"}>
            {historyError ? "unavailable" : `${historyBuckets.length} buckets`}
          </StatusPill>
        </div>

        <div
          className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-surface"
          data-testid="wiii-connect-runtime-flow-doctor-history"
        >
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
              <tr>
                <th className="px-3 py-2 font-medium">Bucket</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Turns</th>
                <th className="px-3 py-2 font-medium">Missing request</th>
                <th className="px-3 py-2 font-medium">Subagents</th>
                <th className="px-3 py-2 font-medium">Alerts</th>
                <th className="px-3 py-2 font-medium">Top route</th>
              </tr>
            </thead>
            <tbody>
              {historyBuckets.length > 0 ? historyBuckets.map((bucket) => {
                const topRoute = countMapEntries(bucket.routes, 1)[0];
                const alertSummary = (bucket.alerts ?? [])
                  .slice(0, 2)
                  .map((alert) => `${safeRuntimeDoctorCounterLabel(alert.code)} ${alert.count ?? 0}`)
                  .join(", ");
                return (
                  <tr
                    key={bucket.bucket_start}
                    className="border-b border-[var(--border)] last:border-b-0"
                  >
                    <td className="px-3 py-2 font-medium text-text">
                      {formatDateTime(bucket.bucket_start)}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={doctorStatusTone(bucket.status)}>
                        {safeRuntimeDoctorCounterLabel(bucket.status)}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {bucket.summary?.turn_count ?? 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {typeof bucket.request_correlation?.missing_request_id_count === "number"
                        ? bucket.request_correlation.missing_request_id_count
                        : 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {`${bucket.subagents?.report_count ?? 0} reports / ${bucket.subagents?.warning_count ?? 0} warnings`}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {alertSummary || "KhÃ´ng"}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {topRoute ? `${topRoute[0]} ${topRoute[1]}` : "KhÃ´ng"}
                    </td>
                  </tr>
                );
              }) : (
                <tr>
                  <td className="px-3 py-3 text-text-secondary" colSpan={7}>
                    {historyError
                      ? "ChÆ°a Ä‘á»c Ä‘Æ°á»£c history report tá»« backend."
                      : "ChÆ°a cÃ³ doctor history."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-2 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
          <div>
            Buckets: {historyReport?.source?.bucket_count ?? historyBuckets.length}/
            {historyReport?.source?.bucket_limit ?? 0}
          </div>
          <div>
            Events: {historyReport?.source?.runtime_flow_ledger_event_count ?? 0}/
            {historyReport?.source?.session_event_count ?? 0}
          </div>
          <div>Privacy: {historyPrivacyStrategy}</div>
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
        <div>Backend: {backend}</div>
        <div>Privacy: {privacyStrategy}</div>
        <div>
          Events: {report?.source?.runtime_flow_ledger_event_count ?? 0}/
          {report?.source?.session_event_count ?? 0}
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-[var(--border)] bg-surface-secondary p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-text">
              <Database size={15} className="text-text-secondary" aria-hidden="true" />
              <span>Session event retention</span>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              Chạy dry-run trước khi prune ledger cũ; kết quả chỉ là aggregate counts.
            </p>
          </div>
          <StatusPill tone={pruneTone}>{pruneStatus}</StatusPill>
        </div>

        <dl
          className="mt-3 grid gap-2 text-xs sm:grid-cols-4"
          data-testid="wiii-connect-runtime-prune-report"
        >
          <div className="rounded-md bg-surface px-2 py-2">
            <dt className="text-text-tertiary">Matched</dt>
            <dd className="mt-0.5 font-medium text-text">{matchedCount}</dd>
          </div>
          <div className="rounded-md bg-surface px-2 py-2">
            <dt className="text-text-tertiary">Deleted</dt>
            <dd className="mt-0.5 font-medium text-text">{deletedCount}</dd>
          </div>
          <div className="rounded-md bg-surface px-2 py-2">
            <dt className="text-text-tertiary">Retention</dt>
            <dd className="mt-0.5 font-medium text-text">
              {pruneReport?.retention_days ?? "--"} days
            </dd>
          </div>
          <div className="rounded-md bg-surface px-2 py-2">
            <dt className="text-text-tertiary">Scope</dt>
            <dd className="mt-0.5 font-medium text-text">
              {pruneReport?.org_scoped ? "org-scoped" : "aggregate"}
            </dd>
          </div>
        </dl>

        <div className="mt-2 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
          <div>
            Cutoff: {pruneReport?.cutoff ? formatDateTime(pruneReport.cutoff) : "Chưa có"}
          </div>
          <div>
            Event filter: {pruneReport?.event_type_filter_applied ? "applied" : "not applied"}
          </div>
          <div>
            Privacy: {safeRuntimeDoctorCounterLabel(pruneReport?.privacy?.identifier_strategy)}
          </div>
        </div>

        {pruneError && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Không thể chạy retention control từ backend.
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="wiii-connect-runtime-prune-dry-run"
            disabled={pruneLoading || Boolean(error) || !report}
            onClick={() => onPruneDryRun?.()}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[var(--border)] bg-surface px-3 text-sm font-medium text-text-secondary disabled:text-text-tertiary"
          >
            <RefreshCw
              size={14}
              className={pruneLoading ? "animate-spin" : ""}
              aria-hidden="true"
            />
            Dry-run retention
          </button>
          <button
            type="button"
            data-testid="wiii-connect-runtime-prune-apply"
            disabled={!canApplyPrune}
            onClick={() => onPruneApply?.()}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 text-sm font-medium text-rose-700 disabled:border-[var(--border)] disabled:bg-surface disabled:text-text-tertiary"
          >
            {pruneLoading && canApplyPrune ? (
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            ) : (
              <AlertTriangle size={14} aria-hidden="true" />
            )}
            Prune matched events
          </button>
        </div>
      </div>
    </section>
  );
}

function SemanticMemoryDoctorPanel({
  report,
  error,
  historyReport,
  historyError,
}: {
  report: SemanticMemoryWriteDoctorReport | null;
  error?: string;
  historyReport: SemanticMemoryWriteDoctorHistoryReport | null;
  historyError?: string;
}) {
  const writeKindEntries = countMapEntries(report?.write_kinds, 4);
  const statusEntries = countMapEntries(report?.write_statuses, 4);
  const orgContextEntries = countMapEntries(report?.organization_contexts, 4);
  const warningEntries = countMapEntries(report?.warnings, 4);
  const historyBuckets = historyReport?.buckets?.slice(0, 8) ?? [];
  const backend = safeRuntimeDoctorCounterLabel(report?.runtime_config?.session_event_log_backend);
  const privacyStrategy = safeRuntimeDoctorCounterLabel(report?.privacy?.identifier_strategy);
  const historyPrivacyStrategy = safeRuntimeDoctorCounterLabel(
    historyReport?.privacy?.identifier_strategy,
  );

  return (
    <section
      className="rounded-lg border border-[var(--border)] bg-surface p-4 lg:col-span-2"
      data-testid="wiii-connect-semantic-memory-doctor-panel"
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Database size={16} className="text-text-secondary" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">Semantic memory doctor</h3>
          </div>
          <p className="mt-1 text-xs text-text-secondary">
            {error
              ? "Backend semantic-memory doctor is unavailable."
              : report
                ? "Post-turn memory write audits, aggregate counts only."
                : "Waiting for semantic-memory doctor report."}
          </p>
        </div>
        <StatusPill tone={doctorStatusTone(report?.status)}>
          {report?.status ?? (error ? "unavailable" : "checking")}
        </StatusPill>
      </div>

      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Writes</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "write_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Facts</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "stored_fact_total")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Insights</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "stored_insight_total")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Blocked</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "blocked_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Warnings</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "warning_count")}
          </dd>
        </div>
        <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
          <dt className="text-xs text-text-tertiary">Raw flags</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-text">
            {semanticMemoryDoctorMetric(report, "raw_content_flag_count")}
          </dd>
        </div>
      </dl>

      <div className="mt-3 grid gap-3 lg:grid-cols-4">
        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Write kinds</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {writeKindEntries.length > 0 ? writeKindEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>None</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Statuses</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {statusEntries.length > 0 ? statusEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>None</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Org context</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {orgContextEntries.length > 0 ? orgContextEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>None</li>}
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--border)] p-3">
          <div className="mb-2 text-xs font-medium uppercase text-text-tertiary">Warnings</div>
          <ul className="space-y-1 text-sm text-text-secondary">
            {warningEntries.length > 0 ? warningEntries.map(([label, count], index) => (
              <li key={`${label}-${index}`} className="flex min-w-0 justify-between gap-3">
                <span className="truncate">{label}</span>
                <span className="font-medium text-text">{count}</span>
              </li>
            )) : <li>None</li>}
          </ul>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-[var(--border)] bg-surface-secondary p-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-text">Memory write history</div>
            <p className="mt-1 text-xs text-text-secondary">
              Recent write doctor buckets grouped by event hour.
            </p>
          </div>
          <StatusPill tone={historyError ? "warn" : historyBuckets.length > 0 ? "ok" : "off"}>
            {historyError ? "unavailable" : `${historyBuckets.length} buckets`}
          </StatusPill>
        </div>

        <div
          className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-surface"
          data-testid="wiii-connect-semantic-memory-doctor-history"
        >
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
              <tr>
                <th className="px-3 py-2 font-medium">Bucket</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Writes</th>
                <th className="px-3 py-2 font-medium">Facts</th>
                <th className="px-3 py-2 font-medium">Insights</th>
                <th className="px-3 py-2 font-medium">Blocked</th>
                <th className="px-3 py-2 font-medium">Top kind</th>
                <th className="px-3 py-2 font-medium">Warnings</th>
              </tr>
            </thead>
            <tbody>
              {historyBuckets.length > 0 ? historyBuckets.map((bucket) => {
                const topKind = countMapEntries(bucket.write_kinds, 1)[0];
                const warnings = countMapEntries(bucket.warnings, 2)
                  .map(([label, count]) => `${label} ${count}`)
                  .join(", ");
                return (
                  <tr
                    key={bucket.bucket_start}
                    className="border-b border-[var(--border)] last:border-b-0"
                  >
                    <td className="px-3 py-2 font-medium text-text">
                      {formatDateTime(bucket.bucket_start)}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={doctorStatusTone(bucket.status)}>
                        {safeRuntimeDoctorCounterLabel(bucket.status)}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {bucket.summary?.write_count ?? 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {bucket.summary?.stored_fact_total ?? 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {bucket.summary?.stored_insight_total ?? 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {bucket.summary?.blocked_count ?? 0}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {topKind ? `${topKind[0]} ${topKind[1]}` : "None"}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {warnings || "None"}
                    </td>
                  </tr>
                );
              }) : (
                <tr>
                  <td className="px-3 py-3 text-text-secondary" colSpan={8}>
                    {historyError
                      ? "Backend semantic-memory history is unavailable."
                      : "No semantic-memory doctor history."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-2 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
          <div>
            Buckets: {historyReport?.source?.bucket_count ?? historyBuckets.length}/
            {historyReport?.source?.bucket_limit ?? 0}
          </div>
          <div>
            Events: {historyReport?.source?.semantic_memory_write_event_count ?? 0}/
            {historyReport?.source?.session_event_count ?? 0}
          </div>
          <div>Privacy: {historyPrivacyStrategy}</div>
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-text-tertiary sm:grid-cols-3">
        <div>Backend: {backend}</div>
        <div>Privacy: {privacyStrategy}</div>
        <div>
          Events: {report?.source?.semantic_memory_write_event_count ?? 0}/
          {report?.source?.session_event_count ?? 0}
        </div>
      </div>
    </section>
  );
}

function RuntimeSection({
  runtimePath,
  runtimeFlowLedger,
  runtimeFlowTrace,
  doctorReport,
  doctorError,
  recentRuntimeFlowDoctorReport,
  recentRuntimeFlowDoctorError,
  runtimeFlowDoctorHistoryReport,
  runtimeFlowDoctorHistoryError,
  recentSemanticMemoryDoctorReport,
  recentSemanticMemoryDoctorError,
  semanticMemoryDoctorHistoryReport,
  semanticMemoryDoctorHistoryError,
  runtimePruneReport,
  runtimePruneLoading,
  runtimePruneError,
  onRuntimePruneDryRun,
  onRuntimePruneApply,
}: {
  runtimePath: RuntimePathSnapshot | null;
  runtimeFlowLedger: RuntimeFlowLedgerViewModel;
  runtimeFlowTrace: RuntimeFlowTraceViewModel;
  doctorReport: WiiiConnectDoctorReport | null;
  doctorError?: string;
  recentRuntimeFlowDoctorReport: RuntimeFlowDoctorReport | null;
  recentRuntimeFlowDoctorError?: string;
  runtimeFlowDoctorHistoryReport: RuntimeFlowDoctorHistoryReport | null;
  runtimeFlowDoctorHistoryError?: string;
  recentSemanticMemoryDoctorReport: SemanticMemoryWriteDoctorReport | null;
  recentSemanticMemoryDoctorError?: string;
  semanticMemoryDoctorHistoryReport: SemanticMemoryWriteDoctorHistoryReport | null;
  semanticMemoryDoctorHistoryError?: string;
  runtimePruneReport: RuntimeFlowSessionEventPruneReport | null;
  runtimePruneLoading?: boolean;
  runtimePruneError?: string;
  onRuntimePruneDryRun?: () => void;
  onRuntimePruneApply?: () => void;
}) {
  const rows = [
    ["Path", compactText(runtimePath?.lane, "Chưa phân loại")],
    ["Pha", compactText(runtimePath?.phase)],
    ["Sự kiện", compactText(runtimePath?.eventName)],
    ["Trạng thái", compactText(runtimePath?.status)],
    ["Surface", compactText(runtimePath?.hostSurface, "Không")],
    ["Tool đã thấy", toolGroupSummary(runtimePath?.observedTools)],
    ["Tool bị chặn", toolGroupSummary(runtimePath?.suppressedTools)],
    ["Preview", runtimePath?.previewRequired ? "Cần preview" : "Không"],
    ["Apply", runtimePath?.approvalTokenPresent ? "Có approval evidence" : "Không"],
    ["Nhận lúc", runtimePath?.receivedAtMs != null ? formatDateTime(new Date(runtimePath.receivedAtMs).toISOString()) : "Chưa có"],
  ];
  const doctorPaths = importantDoctorPaths(doctorReport);
  const doctorProviders = importantDoctorProviders(doctorReport);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
      <section className="rounded-lg border border-[var(--border)] bg-surface p-4">
        <div className="mb-3 flex items-center gap-2">
          <Route size={16} className="text-text-secondary" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">Lượt runtime gần nhất</h3>
        </div>
        <dl className="grid gap-2 sm:grid-cols-2">
          {rows.map(([label, value]) => (
            <div key={label} className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
              <dt className="text-xs text-text-tertiary">{label}</dt>
              <dd className="mt-0.5 truncate text-sm font-medium text-text">{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-lg border border-[var(--border)] bg-surface p-4">
        <div className="mb-3 flex items-center gap-2">
          <Info size={16} className="text-text-secondary" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">Kỷ luật hiển thị</h3>
        </div>
        <ul className="space-y-2 text-sm text-text-secondary">
          <li className="flex gap-2">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" />
            Chỉ hiển thị snapshot đã sanitize từ runtime.
          </li>
          <li className="flex gap-2">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" />
            Không hiển thị token, payload provider, raw document hay approval_token.
          </li>
          <li className="flex gap-2">
            <XCircle size={16} className="mt-0.5 shrink-0 text-text-tertiary" aria-hidden="true" />
            Adapter bên ngoài chưa được bật nếu chưa có vault/policy/gate.
          </li>
        </ul>
      </section>

      <section
        className="rounded-lg border border-[var(--border)] bg-surface p-4 lg:col-span-2"
        data-testid="wiii-connect-runtime-flow-ledger"
      >
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-text-secondary" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">Runtime flow ledger</h3>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {runtimeFlowLedger.summary}
            </p>
          </div>
          <StatusPill tone={runtimeFlowLedger.tone}>
            {runtimeFlowLedger.present ? runtimeFlowLedger.version : "Đang chờ"}
          </StatusPill>
        </div>

        <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {runtimeFlowLedger.rows.map((row) => (
            <div key={row.label} className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
              <dt className="flex items-center justify-between gap-2 text-xs text-text-tertiary">
                <span>{row.label}</span>
                {row.tone && <span className={`h-2 w-2 rounded-full ${statusDotClasses[row.tone]}`} />}
              </dt>
              <dd className="mt-0.5 break-words text-sm font-medium text-text" title={row.value}>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>

        {runtimeFlowLedger.warnings.length > 0 && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <div className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle size={15} aria-hidden="true" />
              Cần kiểm tra ledger
            </div>
            <ul className="space-y-1 text-xs">
              {runtimeFlowLedger.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section
        className="rounded-lg border border-[var(--border)] bg-surface p-4 lg:col-span-2"
        data-testid="wiii-connect-runtime-flow-trace"
      >
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ShieldCheck size={16} className="text-text-secondary" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">Runtime flow trace</h3>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {runtimeFlowTrace.summary}
            </p>
          </div>
          <StatusPill tone={runtimeFlowTrace.tone}>
            {runtimeFlowTrace.present ? runtimeFlowTrace.version : "Đang chờ"}
          </StatusPill>
        </div>

        <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {runtimeFlowTrace.rows.map((row) => (
            <div key={row.label} className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
              <dt className="flex items-center justify-between gap-2 text-xs text-text-tertiary">
                <span>{row.label}</span>
                {row.tone && <span className={`h-2 w-2 rounded-full ${statusDotClasses[row.tone]}`} />}
              </dt>
              <dd className="mt-0.5 break-words text-sm font-medium text-text" title={row.value}>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>

        {runtimeFlowTrace.warnings.length > 0 && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <div className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle size={15} aria-hidden="true" />
              Cần kiểm tra trace
            </div>
            <ul className="space-y-1 text-xs">
              {runtimeFlowTrace.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section
        className="rounded-lg border border-[var(--border)] bg-surface p-4 lg:col-span-2"
        data-testid="wiii-connect-doctor-panel"
      >
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-text-secondary" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">Runtime doctor</h3>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {doctorError
                ? "Chưa đọc được doctor report từ backend."
                : doctorReport
                  ? "Tóm tắt path, connection và blocker từ cùng snapshot runtime."
                  : "Đang chờ doctor report từ backend."}
            </p>
          </div>
          <StatusPill tone={doctorStatusTone(doctorReport?.status)}>
            {doctorReport?.status ?? "checking"}
          </StatusPill>
        </div>

        <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-xs text-text-tertiary">Path sẵn sàng</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {doctorMetric(doctorReport, "ready_paths")}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-xs text-text-tertiary">Path guarded</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {doctorMetric(doctorReport, "guarded_paths")}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-xs text-text-tertiary">Path bị chặn</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {doctorMetric(doctorReport, "blocked_paths")}
            </dd>
          </div>
          <div className="min-w-0 rounded-md bg-surface-secondary px-3 py-2">
            <dt className="text-xs text-text-tertiary">External ready</dt>
            <dd className="mt-0.5 truncate text-sm font-medium text-text">
              {doctorMetric(doctorReport, "external_agent_ready_connections")}
            </dd>
          </div>
        </dl>

        {doctorPaths.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
                <tr>
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 font-medium">Trạng thái</th>
                  <th className="px-3 py-2 font-medium">Lý do</th>
                  <th className="px-3 py-2 font-medium">Thiếu</th>
                </tr>
              </thead>
              <tbody>
                {doctorPaths.map((path) => (
                  <tr key={path.path} className="border-b border-[var(--border)] last:border-b-0">
                    <td className="px-3 py-2 font-medium text-text">{path.path}</td>
                    <td className="px-3 py-2">
                      <StatusPill tone={pathDoctorTone(path.status)}>
                        {path.status}
                      </StatusPill>
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {compactText(path.reason)}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {pathList(path.missing_connection_slugs)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {doctorProviders.length > 0 && (
          <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">Provider diagnostics</caption>
              <thead className="border-b border-[var(--border)] bg-surface-secondary text-xs uppercase text-text-tertiary">
                <tr>
                  <th className="px-3 py-2 font-medium">Provider</th>
                  <th className="px-3 py-2 font-medium">Kết nối</th>
                  <th className="px-3 py-2 font-medium">Agent</th>
                  <th className="px-3 py-2 font-medium">Vòng đời</th>
                  <th className="px-3 py-2 font-medium">Bước tiếp</th>
                </tr>
              </thead>
              <tbody>
                {doctorProviders.map((provider) => (
                  <tr key={provider.provider_slug} className="border-b border-[var(--border)] last:border-b-0">
                    <td className="px-3 py-2">
                      <div className="font-medium text-text">{provider.label}</div>
                      <div className="text-xs text-text-tertiary">
                        {provider.provider_slug} · {compactText(provider.provider_kind)}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      <div className="font-medium text-text">{compactText(provider.connection_status)}</div>
                      <div className="text-xs text-text-tertiary">
                        {providerDoctorCountSummary(provider)}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={pathDoctorTone(provider.status)}>
                        {provider.status}
                      </StatusPill>
                      <div className="mt-1 text-xs text-text-secondary">
                        {compactText(provider.reason)}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      <DoctorProviderStages provider={provider} />
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {pathList(provider.required_next)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {doctorReport?.top_blockers && doctorReport.top_blockers.length > 0 && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {pathList(doctorReport.top_blockers.slice(0, 4))}
          </div>
        )}
      </section>

      <RecentRuntimeFlowDoctorPanel
        report={recentRuntimeFlowDoctorReport}
        error={recentRuntimeFlowDoctorError}
        historyReport={runtimeFlowDoctorHistoryReport}
        historyError={runtimeFlowDoctorHistoryError}
        pruneReport={runtimePruneReport}
        pruneLoading={runtimePruneLoading}
        pruneError={runtimePruneError}
        onPruneDryRun={onRuntimePruneDryRun}
        onPruneApply={onRuntimePruneApply}
      />

      <SemanticMemoryDoctorPanel
        report={recentSemanticMemoryDoctorReport}
        error={recentSemanticMemoryDoctorError}
        historyReport={semanticMemoryDoctorHistoryReport}
        historyError={semanticMemoryDoctorHistoryError}
      />
    </div>
  );
}

export function WiiiConnectPage() {
  const [activeTab, setActiveTab] = useState<ConnectTab>("catalog");
  const [providerRegistry, setProviderRegistry] = useState<WiiiConnectProviderRegistryEntry[] | null>(null);
  const [providerRegistryLoaded, setProviderRegistryLoaded] = useState(false);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<WiiiConnectRuntimeSnapshot | null>(null);
  const [runtimeSnapshotError, setRuntimeSnapshotError] = useState<string | undefined>();
  const [runtimeRefreshing, setRuntimeRefreshing] = useState(false);
  const [lastRuntimeRefreshAt, setLastRuntimeRefreshAt] = useState<string | null>(null);
  const [doctorReport, setDoctorReport] = useState<WiiiConnectDoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState<string | undefined>();
  const [recentRuntimeFlowDoctorReport, setRecentRuntimeFlowDoctorReport] =
    useState<RuntimeFlowDoctorReport | null>(null);
  const [recentRuntimeFlowDoctorError, setRecentRuntimeFlowDoctorError] =
    useState<string | undefined>();
  const [runtimeFlowDoctorHistoryReport, setRuntimeFlowDoctorHistoryReport] =
    useState<RuntimeFlowDoctorHistoryReport | null>(null);
  const [runtimeFlowDoctorHistoryError, setRuntimeFlowDoctorHistoryError] =
    useState<string | undefined>();
  const [recentSemanticMemoryDoctorReport, setRecentSemanticMemoryDoctorReport] =
    useState<SemanticMemoryWriteDoctorReport | null>(null);
  const [recentSemanticMemoryDoctorError, setRecentSemanticMemoryDoctorError] =
    useState<string | undefined>();
  const [semanticMemoryDoctorHistoryReport, setSemanticMemoryDoctorHistoryReport] =
    useState<SemanticMemoryWriteDoctorHistoryReport | null>(null);
  const [semanticMemoryDoctorHistoryError, setSemanticMemoryDoctorHistoryError] =
    useState<string | undefined>();
  const [runtimePruneReport, setRuntimePruneReport] =
    useState<RuntimeFlowSessionEventPruneReport | null>(null);
  const [runtimePruneError, setRuntimePruneError] = useState<string | undefined>();
  const [runtimePruneLoading, setRuntimePruneLoading] = useState(false);
  const runtimeControlPlaneMountedRef = useRef(false);
  const navigateToChat = useUIStore((state) => state.navigateToChat);
  const authMode = useAuthStore((state) => state.authMode);
  const authUser = useAuthStore((state) => state.user);
  const connectionStatus = useConnectionStore((state) => state.status);
  const serverVersion = useConnectionStore((state) => state.serverVersion);
  const lastCheckedAt = useConnectionStore((state) => state.lastCheckedAt);
  const errorMessage = useConnectionStore((state) => state.errorMessage);
  const capabilities = useHostContextStore((state) => state.capabilities);
  const currentContext = useHostContextStore((state) => state.currentContext);
  const streamingLifecycleEvents = useChatStore(
    (state) => state.streamingLifecycleEvents,
  );
  const lastCompletedLifecycleEvents = useChatStore(
    (state) => state.lastCompletedLifecycleEvents,
  );
  const activeConversation = useChatStore((state) => state.activeConversation());
  const pendingStreamMetadata = useChatStore((state) => state.pendingStreamMetadata);
  const isEmbedded = isEmbeddedWindow();

  useEffect(() => {
    runtimeControlPlaneMountedRef.current = true;
    return () => {
      runtimeControlPlaneMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    fetchWiiiConnectProviders()
      .then((response) => {
        if (!mounted) return;
        setProviderRegistry(response.providers ?? []);
        setProviderRegistryLoaded(true);
      })
      .catch(() => {
        if (!mounted) return;
        setProviderRegistry(null);
        setProviderRegistryLoaded(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const refreshRuntimeControlPlane = useCallback(async () => {
    const surface = isEmbedded ? "embed" : "desktop";
    const canReadRecentRuntimeDoctor =
      authMode === "legacy" || authUser?.platform_role === "platform_admin";
    if (runtimeControlPlaneMountedRef.current) {
      setRuntimeRefreshing(true);
    }
    try {
      const [
        snapshotResult,
        doctorResult,
        recentDoctorResult,
        doctorHistoryResult,
        semanticDoctorResult,
        semanticDoctorHistoryResult,
      ] = await Promise.allSettled([
        fetchWiiiConnectSnapshot({ surface }),
        fetchWiiiConnectDoctor({ surface }),
        canReadRecentRuntimeDoctor
          ? fetchRecentRuntimeFlowDoctor({
              orgId: authUser?.active_organization_id,
              limit: 50,
            })
          : Promise.resolve(null),
        canReadRecentRuntimeDoctor
          ? fetchRuntimeFlowDoctorHistory({
              orgId: authUser?.active_organization_id,
              limit: 500,
              bucketLimit: 24,
            })
          : Promise.resolve(null),
        canReadRecentRuntimeDoctor
          ? fetchRecentSemanticMemoryDoctor({
              orgId: authUser?.active_organization_id,
              limit: 50,
            })
          : Promise.resolve(null),
        canReadRecentRuntimeDoctor
          ? fetchSemanticMemoryDoctorHistory({
              orgId: authUser?.active_organization_id,
              limit: 500,
              bucketLimit: 24,
            })
          : Promise.resolve(null),
      ]);
      if (!runtimeControlPlaneMountedRef.current) return;
      if (snapshotResult.status === "fulfilled") {
        setRuntimeSnapshot(snapshotResult.value);
        setRuntimeSnapshotError(undefined);
      } else {
        setRuntimeSnapshotError(
          snapshotResult.reason instanceof Error
            ? snapshotResult.reason.message
            : "snapshot_unavailable",
        );
      }
      if (doctorResult.status === "fulfilled") {
        setDoctorReport(doctorResult.value);
        setDoctorError(undefined);
      } else {
        setDoctorError(
          doctorResult.reason instanceof Error
            ? doctorResult.reason.message
            : "doctor_unavailable",
        );
      }
      if (recentDoctorResult.status === "fulfilled" && recentDoctorResult.value) {
        setRecentRuntimeFlowDoctorReport(recentDoctorResult.value);
        setRecentRuntimeFlowDoctorError(undefined);
      } else {
        setRecentRuntimeFlowDoctorReport(null);
        setRecentRuntimeFlowDoctorError(
          recentDoctorResult.status === "rejected"
            ? recentDoctorResult.reason instanceof Error
              ? recentDoctorResult.reason.message
              : "runtime_flow_doctor_unavailable"
            : "operator_access_required",
        );
      }
      if (doctorHistoryResult.status === "fulfilled" && doctorHistoryResult.value) {
        setRuntimeFlowDoctorHistoryReport(doctorHistoryResult.value);
        setRuntimeFlowDoctorHistoryError(undefined);
      } else {
        setRuntimeFlowDoctorHistoryReport(null);
        setRuntimeFlowDoctorHistoryError(
          doctorHistoryResult.status === "rejected"
            ? doctorHistoryResult.reason instanceof Error
              ? doctorHistoryResult.reason.message
              : "runtime_flow_doctor_history_unavailable"
            : "operator_access_required",
        );
      }
      if (semanticDoctorResult.status === "fulfilled" && semanticDoctorResult.value) {
        setRecentSemanticMemoryDoctorReport(semanticDoctorResult.value);
        setRecentSemanticMemoryDoctorError(undefined);
      } else {
        setRecentSemanticMemoryDoctorReport(null);
        setRecentSemanticMemoryDoctorError(
          semanticDoctorResult.status === "rejected"
            ? semanticDoctorResult.reason instanceof Error
              ? semanticDoctorResult.reason.message
              : "semantic_memory_doctor_unavailable"
            : "operator_access_required",
        );
      }
      if (
        semanticDoctorHistoryResult.status === "fulfilled" &&
        semanticDoctorHistoryResult.value
      ) {
        setSemanticMemoryDoctorHistoryReport(semanticDoctorHistoryResult.value);
        setSemanticMemoryDoctorHistoryError(undefined);
      } else {
        setSemanticMemoryDoctorHistoryReport(null);
        setSemanticMemoryDoctorHistoryError(
          semanticDoctorHistoryResult.status === "rejected"
            ? semanticDoctorHistoryResult.reason instanceof Error
              ? semanticDoctorHistoryResult.reason.message
              : "semantic_memory_doctor_history_unavailable"
            : "operator_access_required",
        );
      }
      setLastRuntimeRefreshAt(new Date().toISOString());
    } finally {
      if (runtimeControlPlaneMountedRef.current) {
        setRuntimeRefreshing(false);
      }
    }
  }, [authMode, authUser?.active_organization_id, authUser?.platform_role, isEmbedded]);

  const runRuntimePruneDryRun = useCallback(async () => {
    const canReadRecentRuntimeDoctor =
      authMode === "legacy" || authUser?.platform_role === "platform_admin";
    if (!canReadRecentRuntimeDoctor) {
      setRuntimePruneError("operator_access_required");
      return;
    }
    setRuntimePruneLoading(true);
    setRuntimePruneError(undefined);
    try {
      const report = await pruneRuntimeFlowSessionEvents({
        orgId: authUser?.active_organization_id,
        eventType: "runtime_flow_ledger",
        dryRun: true,
      });
      if (!runtimeControlPlaneMountedRef.current) return;
      setRuntimePruneReport(report);
    } catch {
      if (!runtimeControlPlaneMountedRef.current) return;
      setRuntimePruneError("retention_prune_unavailable");
    } finally {
      if (runtimeControlPlaneMountedRef.current) {
        setRuntimePruneLoading(false);
      }
    }
  }, [authMode, authUser?.active_organization_id, authUser?.platform_role]);

  const runRuntimePruneApply = useCallback(async () => {
    const canReadRecentRuntimeDoctor =
      authMode === "legacy" || authUser?.platform_role === "platform_admin";
    if (
      !canReadRecentRuntimeDoctor ||
      !runtimePruneReport?.dry_run ||
      runtimePruneReport.matched_count <= 0
    ) {
      return;
    }
    setRuntimePruneLoading(true);
    setRuntimePruneError(undefined);
    try {
      const report = await pruneRuntimeFlowSessionEvents({
        retentionDays: runtimePruneReport.retention_days,
        orgId: authUser?.active_organization_id,
        eventType: "runtime_flow_ledger",
        dryRun: false,
      });
      if (!runtimeControlPlaneMountedRef.current) return;
      setRuntimePruneReport(report);
      await refreshRuntimeControlPlane();
    } catch {
      if (!runtimeControlPlaneMountedRef.current) return;
      setRuntimePruneError("retention_prune_unavailable");
    } finally {
      if (runtimeControlPlaneMountedRef.current) {
        setRuntimePruneLoading(false);
      }
    }
  }, [
    authMode,
    authUser?.active_organization_id,
    authUser?.platform_role,
    refreshRuntimeControlPlane,
    runtimePruneReport?.dry_run,
    runtimePruneReport?.matched_count,
    runtimePruneReport?.retention_days,
  ]);

  useEffect(() => {
    void refreshRuntimeControlPlane();
    const timer = window.setInterval(() => {
      void refreshRuntimeControlPlane();
    }, WIII_CONNECT_RUNTIME_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refreshRuntimeControlPlane]);

  const runtimePath = useMemo(
    () =>
      runtimePathFromLifecycleEvents(
        streamingLifecycleEvents,
        lastCompletedLifecycleEvents,
      ),
    [streamingLifecycleEvents, lastCompletedLifecycleEvents],
  );
  const runtimeFlowTrace = useMemo(
    () =>
      buildRuntimeFlowTraceViewModel(
        latestRuntimeFlowTrace(activeConversation?.messages, pendingStreamMetadata),
      ),
    [activeConversation?.messages, pendingStreamMetadata],
  );
  const runtimeFlowLedger = useMemo(
    () =>
      buildRuntimeFlowLedgerViewModel(
        latestRuntimeFlowLedger(activeConversation?.messages, pendingStreamMetadata),
      ),
    [activeConversation?.messages, pendingStreamMetadata],
  );
  const snapshot = runtimePath?.wiiiConnect ?? runtimeSnapshot;
  const stats = snapshotStats(snapshot);
  const runtimeSyncLabel = runtimeRefreshing
    ? "Đang đồng bộ"
    : lastRuntimeRefreshAt
      ? "Đã đồng bộ"
      : "Chờ đồng bộ";

  const fallbackModel = useMemo(
    () =>
      buildCapabilityStatusViewModel({
        connectionStatus,
        capabilities,
        currentContext,
        isEmbedded,
        serverVersion,
        lastCheckedAt,
        errorMessage,
        runtimePath,
      }),
    [
      connectionStatus,
      capabilities,
      currentContext,
      isEmbedded,
      serverVersion,
      lastCheckedAt,
      errorMessage,
      runtimePath,
    ],
  );

  const snapshotTone: CapabilityStatusTone =
    !snapshot ? "pending" : stats.warningCount > 0 ? "warn" : stats.ready > 0 ? "ok" : "off";

  return (
    <FullPageView
      title="Wiii Connect"
      subtitle="Connection registry V0"
      icon={<PlugZap size={18} />}
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={(id) => setActiveTab(id as ConnectTab)}
      onClose={navigateToChat}
    >
      <div className="space-y-6" data-testid="wiii-connect-page">
        <section>
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-xl font-semibold text-text">Wiii Connect</h1>
              <p className="mt-1 max-w-3xl text-sm text-text-secondary">
                Trạng thái kết nối, capability và path policy đang được Wiii dùng trong lượt runtime gần nhất.
              </p>
            </div>
            <StatusPill tone={snapshotTone}>
              {snapshot ? `${stats.ready}/${stats.total} agent-ready` : "Chưa có snapshot"}
            </StatusPill>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <SummaryMetric
              icon={Database}
              label="Kết nối"
              value={snapshot ? `${stats.total}` : `${fallbackModel.items.length} local`}
              tone={snapshot ? "ok" : "pending"}
            />
            <SummaryMetric
              icon={CheckCircle2}
              label="Agent-ready"
              value={snapshot ? `${stats.ready}/${stats.total}` : fallbackModel.summary}
              tone={snapshotTone}
            />
            <SummaryMetric
              icon={Route}
              label="Path policy"
              value={
                snapshot?.capability_summary
                  ? `${stats.readyPathCount}/${stats.pathCount} ready`
                  : snapshot
                    ? `${stats.pathCount}`
                    : "Đang chờ"
              }
              tone={
                stats.blockedPathCount > 0
                  ? "warn"
                  : stats.pathCount > 0
                    ? "ok"
                    : "pending"
              }
            />
            <SummaryMetric
              icon={AlertTriangle}
              label="Cảnh báo"
              value={`${stats.warningCount}${runtimeSnapshotError ? "+API" : ""}`}
              tone={stats.warningCount > 0 || runtimeSnapshotError ? "warn" : "ok"}
            />
            <SummaryMetric
              icon={RefreshCw}
              label="Runtime sync"
              value={runtimeSyncLabel}
              tone={
                runtimeSnapshotError || doctorError
                  ? "warn"
                  : lastRuntimeRefreshAt
                    ? "ok"
                    : "pending"
              }
            />
          </div>
        </section>

        {activeTab === "catalog" && (
          <ConnectionCatalog
            snapshot={snapshot}
            fallbackModel={fallbackModel}
            providerRegistry={providerRegistry}
            providerRegistryLoaded={providerRegistryLoaded}
            onRuntimeRefresh={refreshRuntimeControlPlane}
          />
        )}

        {activeTab === "connections" && (
          <>
            <ConnectionsGrid connections={snapshot?.connections ?? []} snapshot={snapshot} />
            {!snapshot && <LocalRuntimeFallback sections={fallbackModel.sections} />}
            <ProviderRoadmap />
          </>
        )}

        {activeTab === "paths" && (
          <>
            <CapabilitySummaryPanel snapshot={snapshot} />
            <PathPolicyTable paths={snapshot?.path_capabilities ?? []} />
          </>
        )}

        {activeTab === "runtime" && (
            <RuntimeSection
              runtimePath={runtimePath}
              runtimeFlowLedger={runtimeFlowLedger}
              runtimeFlowTrace={runtimeFlowTrace}
              doctorReport={doctorReport}
              doctorError={doctorError}
              recentRuntimeFlowDoctorReport={recentRuntimeFlowDoctorReport}
              recentRuntimeFlowDoctorError={recentRuntimeFlowDoctorError}
              runtimeFlowDoctorHistoryReport={runtimeFlowDoctorHistoryReport}
              runtimeFlowDoctorHistoryError={runtimeFlowDoctorHistoryError}
              recentSemanticMemoryDoctorReport={recentSemanticMemoryDoctorReport}
              recentSemanticMemoryDoctorError={recentSemanticMemoryDoctorError}
              semanticMemoryDoctorHistoryReport={semanticMemoryDoctorHistoryReport}
              semanticMemoryDoctorHistoryError={semanticMemoryDoctorHistoryError}
              runtimePruneReport={runtimePruneReport}
              runtimePruneLoading={runtimePruneLoading}
              runtimePruneError={runtimePruneError}
              onRuntimePruneDryRun={runRuntimePruneDryRun}
              onRuntimePruneApply={runRuntimePruneApply}
          />
        )}
      </div>
    </FullPageView>
  );
}
