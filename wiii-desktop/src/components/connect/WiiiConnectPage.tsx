import { useEffect, useMemo, useRef, useState } from "react";
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
  Info,
  Loader2,
  Lock,
  MousePointer2,
  Network,
  PlugZap,
  RefreshCw,
  Route,
  Search,
  Server,
  Unplug,
  Workflow,
  type LucideIcon,
  XCircle,
} from "lucide-react";
import type {
  WiiiConnectActivationGate,
  WiiiConnectActivationReadinessResponse,
  WiiiConnectAuthorizationUrlDecision,
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
  buildWiiiConnectProviderCallbackUrl,
  createWiiiConnectProviderAuthorizationUrl,
  disconnectWiiiConnectProviderConnection,
  fetchWiiiConnectProviderActivationReadiness,
  fetchWiiiConnectProviderConnections,
  fetchWiiiConnectProviders,
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
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
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

interface ProviderDisconnectState {
  response?: WiiiConnectProviderDisconnectResponse;
  loading: boolean;
  error?: string;
  lastUpdatedAt?: string;
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

function compactText(value: unknown, fallback = "Chưa có"): string {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  return text.length > 72 ? `${text.slice(0, 69)}...` : text;
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
    .map(([key]) => key);
  return enabled.length > 0 ? enabled.join(", ") : "Không";
}

function pathList(value: string[] | undefined): string {
  if (!value || value.length === 0) return "Không";
  return value.join(", ");
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
  const readyCount = connections.filter(
    (item) => item.agent_ready || item.active || item.status === "connected",
  ).length;
  const warningCount =
    (snapshot?.warnings?.length ?? 0) +
    connections.reduce((total, item) => total + (item.warnings?.length ?? 0), 0);
  return {
    total: connections.length,
    ready: readyCount,
    warningCount,
    pathCount: snapshot?.path_capabilities?.length ?? 0,
  };
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
    const reason = connectionResponse?.reason;
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
      statusDetail: fromBackend
        ? "Backend registry đã khai báo provider này; agent action vẫn bị khóa cho đến khi có scope, policy và audit."
        : "Wiii chưa có adapter, vault và permission gate cho kết nối này.",
      agentReady: false,
      connected: tone === "ok",
      registrySource: definition.source ?? "local",
      detailRows: [
        ["Provider", providerKindLabels[definition.provider] ?? definition.provider],
        ["Nguồn", fromBackend ? "Backend registry" : "Local fallback"],
        ["Auth", compactText(definition.authMode, "Chưa khai báo")],
        ["Action", definition.actionCount != null ? `${definition.actionCount}` : "Chưa khai báo"],
        ["Trạng thái", connectionStatus],
        ["Account", providerConnectionSummary(providerConnection)],
        ["Vault ref", providerConnection?.vault_ref_present ? "Có" : "Chưa"],
        ["Scope", providerConnection ? scopeSummary(providerConnection.scopes) : "Chưa"],
        ["Agent-ready", "Chưa"],
        ["Mutation", "Bị chặn cho đến khi có curated action và execution gateway"],
        ...(reason ? ([["Lý do", compactText(reason)]] as Array<[string, string]>) : []),
      ],
      requirements: definition.requirements,
      disabledReason: fromBackend
        ? "Provider có trong registry backend. Kết nối account được phép khi backend cấp URL; action vẫn fail-closed."
        : "Cần thiết kế adapter/vault/policy trước khi bật Connect.",
    };
  });
}

function buildConnectionCatalogCards(
  snapshot: WiiiConnectRuntimeSnapshot | null,
  fallbackModel: CapabilityStatusViewModel,
  providerRegistry: WiiiConnectProviderRegistryEntry[] | null,
  providerConnectionLists: Record<string, ProviderConnectionListState> = {},
): CatalogCard[] {
  return [
    ...buildNativeCatalogCards(snapshot, fallbackModel),
    ...buildExternalCatalogCards(providerRegistry, providerConnectionLists),
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
  if (readiness.ready_to_execute_readonly) return "ok";
  if (readiness.ready_to_connect) return "pending";
  return "warn";
}

function readinessBooleanLabel(value: boolean | undefined): string {
  return value ? "Sẵn sàng" : "Chưa sẵn sàng";
}

function readinessGateLabel(key: string): string {
  const labels: Record<string, string> = {
    provider_registered: "Provider registry",
    provider_adapter: "Adapter",
    vault: "Vault",
    persistent_storage: "Storage",
    audit_ledger: "Audit ledger",
    connect_policy: "Connect policy",
    curated_readonly_action: "Read-only action",
    local_connection: "Connection",
    execution_gateway: "Execution gateway",
  };
  return labels[key] ?? compactText(key.replaceAll("_", " "));
}

function readinessGateTone(gate: WiiiConnectActivationGate): CapabilityStatusTone {
  return gate.ready ? "ok" : "warn";
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
  readinessError,
  sessionError,
  authorizationError,
  connectionList,
  onRefreshReadiness,
  onRequestSession,
  onRequestAuthorization,
  onRefreshConnections,
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
  readinessError?: string;
  sessionError?: string;
  authorizationError?: string;
  connectionList?: ProviderConnectionListState;
  onRefreshReadiness?: (card: CatalogCard) => Promise<unknown>;
  onRequestSession?: (card: CatalogCard) => Promise<void>;
  onRequestAuthorization?: (card: CatalogCard) => Promise<void>;
  onRefreshConnections?: (card: CatalogCard) => Promise<unknown>;
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
              <dt className="text-text-tertiary">Agent read-only</dt>
              <dd className="mt-0.5 font-medium text-text">
                {readinessBooleanLabel(readiness?.ready_to_execute_readonly)}
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
}: {
  snapshot: WiiiConnectRuntimeSnapshot | null;
  fallbackModel: CapabilityStatusViewModel;
  providerRegistry: WiiiConnectProviderRegistryEntry[] | null;
  providerRegistryLoaded: boolean;
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
    () => buildConnectionCatalogCards(snapshot, fallbackModel, providerRegistry, providerConnectionLists),
    [snapshot, fallbackModel, providerRegistry, providerConnectionLists],
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
        actionSlug: "GMAIL_FETCH_EMAILS",
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
    if (readinessState?.loading || readinessState?.response || readinessState?.error) return;
    void refreshActivationReadiness(selectedCard);
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
                      {card.connected ? "Theo policy" : "Fail-closed"}
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
          readinessError={
            selectedCard ? providerReadinessStates[selectedCard.providerSlug]?.error : undefined
          }
          sessionError={selectedCard ? sessionErrors[selectedCard.providerSlug] : undefined}
          authorizationError={selectedCard ? authorizationErrors[selectedCard.providerSlug] : undefined}
          connectionList={selectedCard ? providerConnectionLists[selectedCard.providerSlug] : undefined}
          onRefreshReadiness={refreshActivationReadiness}
          onRequestSession={requestSessionDecision}
          onRequestAuthorization={requestAuthorizationUrl}
          onRefreshConnections={refreshProviderConnections}
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

function RuntimeSection({
  runtimePath,
}: {
  runtimePath: RuntimePathSnapshot | null;
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
    </div>
  );
}

export function WiiiConnectPage() {
  const [activeTab, setActiveTab] = useState<ConnectTab>("catalog");
  const [providerRegistry, setProviderRegistry] = useState<WiiiConnectProviderRegistryEntry[] | null>(null);
  const [providerRegistryLoaded, setProviderRegistryLoaded] = useState(false);
  const navigateToChat = useUIStore((state) => state.navigateToChat);
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

  const runtimePath = useMemo(
    () =>
      runtimePathFromLifecycleEvents(
        streamingLifecycleEvents,
        lastCompletedLifecycleEvents,
      ),
    [streamingLifecycleEvents, lastCompletedLifecycleEvents],
  );
  const snapshot = runtimePath?.wiiiConnect ?? null;
  const stats = snapshotStats(snapshot);
  const isEmbedded = isEmbeddedWindow();

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

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
              value={snapshot ? `${stats.pathCount}` : "Đang chờ"}
              tone={stats.pathCount > 0 ? "ok" : "pending"}
            />
            <SummaryMetric
              icon={AlertTriangle}
              label="Cảnh báo"
              value={`${stats.warningCount}`}
              tone={stats.warningCount > 0 ? "warn" : "ok"}
            />
          </div>
        </section>

        {activeTab === "catalog" && (
          <ConnectionCatalog
            snapshot={snapshot}
            fallbackModel={fallbackModel}
            providerRegistry={providerRegistry}
            providerRegistryLoaded={providerRegistryLoaded}
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
          <PathPolicyTable paths={snapshot?.path_capabilities ?? []} />
        )}

        {activeTab === "runtime" && (
          <RuntimeSection runtimePath={runtimePath} />
        )}
      </div>
    </FullPageView>
  );
}
