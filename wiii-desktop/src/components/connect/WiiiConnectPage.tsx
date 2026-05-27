import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Cable,
  CheckCircle2,
  CloudSun,
  Code2,
  Database,
  FileText,
  Globe2,
  GraduationCap,
  Info,
  Lock,
  MousePointer2,
  Network,
  PlugZap,
  Route,
  Server,
  Workflow,
  type LucideIcon,
  XCircle,
} from "lucide-react";
import type {
  WiiiConnectRuntimeConnection,
  WiiiConnectRuntimePathCapability,
  WiiiConnectRuntimeSnapshot,
} from "@/api/types";
import { FullPageView, type FullPageTab } from "@/components/layout/FullPageView";
import {
  buildCapabilityStatusViewModel,
  runtimePathFromLifecycleEvents,
  type CapabilityDashboardSection,
  type CapabilityStatusTone,
  type RuntimePathSnapshot,
} from "@/lib/capability-status";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useUIStore } from "@/stores/ui-store";

type ConnectTab = "connections" | "paths" | "runtime";

const tabs: FullPageTab[] = [
  { id: "connections", label: "Kết nối", icon: <PlugZap size={15} /> },
  { id: "paths", label: "Path policy", icon: <Route size={15} /> },
  { id: "runtime", label: "Runtime", icon: <Activity size={15} /> },
];

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
  if (status === "preview") return "Preview";
  if (status === "pending") return "Đang chờ";
  if (status === "expired") return "Hết hạn";
  if (status === "error") return "Lỗi";
  if (status === "disabled") return "Tắt";
  if (status === "not_connected") return "Chưa nối";
  return compactText(status, "Không rõ");
}

function compactText(value: unknown, fallback = "Chưa có"): string {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  return text.length > 72 ? `${text.slice(0, 69)}...` : text;
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
  const [activeTab, setActiveTab] = useState<ConnectTab>("connections");
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
