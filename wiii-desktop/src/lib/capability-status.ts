import type {
  WiiiConnectRuntimeConnection,
  WiiiConnectRuntimeSnapshot,
  ChatLifecycleTelemetryEvent,
} from "@/api/types";
import type {
  HostCapabilities,
  HostContext,
} from "@/stores/host-context-store";

export type RuntimeConnectionStatus =
  | "connected"
  | "degraded"
  | "disconnected"
  | "checking";

export type CapabilityStatusTone = "ok" | "warn" | "off" | "pending";

export type CapabilityStatusItemId =
  | "server"
  | "host"
  | "host_actions"
  | "lms_authoring"
  | "pointy";

export interface CapabilityStatusItem {
  id: CapabilityStatusItemId;
  label: string;
  value: string;
  tone: CapabilityStatusTone;
  title: string;
}

export interface RuntimePathSnapshot {
  lane?: string;
  eventName?: string;
  phase?: string;
  status?: string;
  message?: string;
  hostSurface?: string;
  observedTools?: string[];
  suppressedTools?: string[];
  previewRequired?: boolean;
  previewEmitted?: boolean;
  approvalTokenPresent?: boolean;
  applyAttempted?: boolean;
  wiiiConnect?: WiiiConnectRuntimeSnapshot | null;
  receivedAtMs?: number;
}

export function latestRuntimeLifecycleEvent(
  streamingEvents: ChatLifecycleTelemetryEvent[],
  completedEvents: ChatLifecycleTelemetryEvent[],
): ChatLifecycleTelemetryEvent | null {
  const source = streamingEvents.length > 0 ? streamingEvents : completedEvents;
  for (let index = source.length - 1; index >= 0; index -= 1) {
    const event = source[index];
    if (event) return event;
  }
  return null;
}

export function runtimePathFromLifecycleEvents(
  streamingEvents: ChatLifecycleTelemetryEvent[],
  completedEvents: ChatLifecycleTelemetryEvent[],
): RuntimePathSnapshot | null {
  const event = latestRuntimeLifecycleEvent(streamingEvents, completedEvents);
  if (!event) return null;
  return {
    lane: event.lane,
    eventName: event.event_name,
    phase: event.phase,
    status: event.status,
    message: event.message,
    hostSurface: event.capabilities?.host_surface,
    observedTools: event.capabilities?.observed_tools
      ? [...event.capabilities.observed_tools]
      : undefined,
    suppressedTools: event.capabilities?.suppressed_tools
      ? [...event.capabilities.suppressed_tools]
      : undefined,
    previewRequired: event.capabilities?.preview_required,
    previewEmitted: event.capabilities?.preview_emitted,
    approvalTokenPresent: event.capabilities?.approval_token_present,
    applyAttempted: event.capabilities?.apply_attempted,
    wiiiConnect: event.capabilities?.wiii_connect ?? null,
    receivedAtMs: event.received_at_ms,
  };
}

export interface CapabilityDashboardMetric {
  label: string;
  value: string;
  tone?: CapabilityStatusTone;
}

export type CapabilityDashboardSectionId =
  | CapabilityStatusItemId
  | "wiii_connect"
  | "path";

export interface CapabilityDashboardSection {
  id: CapabilityDashboardSectionId;
  title: string;
  summary: string;
  tone: CapabilityStatusTone;
  metrics: CapabilityDashboardMetric[];
}

export interface CapabilityStatusViewModel {
  items: CapabilityStatusItem[];
  sections: CapabilityDashboardSection[];
  summary: string;
  overallTone: CapabilityStatusTone;
}

interface BuildCapabilityStatusInput {
  connectionStatus: RuntimeConnectionStatus;
  capabilities: HostCapabilities | null;
  currentContext: HostContext | null;
  isEmbedded: boolean;
  serverVersion?: string | null;
  lastCheckedAt?: string | null;
  errorMessage?: string | null;
  runtimePath?: RuntimePathSnapshot | null;
}

const LMS_PREVIEW_TOOLS = [
  "authoring.preview_lesson_patch",
  "authoring.generate_course_from_document",
];

const LMS_APPLY_TOOLS = [
  "authoring.apply_lesson_patch",
  "authoring.apply_course_plan",
];

function normalizedToolNames(capabilities: HostCapabilities | null): Set<string> {
  const names = new Set<string>();
  for (const tool of capabilities?.tools ?? []) {
    const name = String(tool?.name ?? "").trim();
    if (name) names.add(name);
  }
  return names;
}

function hasTool(names: Set<string>, candidates: string[]): boolean {
  return candidates.some((name) => names.has(name));
}

function hasToolPrefix(names: Set<string>, prefix: string): boolean {
  for (const name of names) {
    if (name.startsWith(prefix)) return true;
  }
  return false;
}

function hostIdentity(
  capabilities: HostCapabilities | null,
  currentContext: HostContext | null,
) {
  const hostType = String(
    currentContext?.host_type || capabilities?.host_type || "",
  ).trim();
  const hostName = String(
    currentContext?.host_name || capabilities?.host_name || "",
  ).trim();
  const connectorId = String(
    currentContext?.connector_id || capabilities?.connector_id || "",
  ).trim();
  return {
    hostType,
    hostName,
    connectorId,
    isLms: hostType.toLowerCase() === "lms",
  };
}

function availableTargetCount(currentContext: HostContext | null): number {
  const availableTargets = currentContext?.page?.metadata?.available_targets;
  return Array.isArray(availableTargets) ? availableTargets.length : 0;
}

function compactValue(value: string | null | undefined, fallback = "Chưa có"): string {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) return fallback;
  return trimmed.length > 64 ? `${trimmed.slice(0, 61)}...` : trimmed;
}

function formatCheckedAt(value: string | null | undefined): string {
  if (!value) return "Chưa kiểm tra";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return compactValue(value);
  return date.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatToolGroupSummary(names: string[] | undefined): string {
  if (!names || names.length === 0) return "Không";
  const groups = new Set(
    names.map((name) => {
      const lower = name.toLowerCase();
      if (lower.includes("authoring") || lower.includes("lms")) return "LMS";
      if (lower.includes("host")) return "Host";
      if (lower.startsWith("ui.") || lower.includes("pointy")) return "UI";
      if (lower.includes("web") || lower.includes("search")) return "Web";
      if (lower.includes("memory")) return "Memory";
      return "Khác";
    }),
  );
  return `${names.length} tool (${Array.from(groups).join(", ")})`;
}

function isWiiiConnectReady(connection: WiiiConnectRuntimeConnection): boolean {
  return connection.agent_ready === true || connection.active === true || connection.status === "connected";
}

function wiiiConnectConnectionTone(
  connection: WiiiConnectRuntimeConnection,
): CapabilityStatusTone {
  if (connection.status === "error" || connection.status === "expired") return "warn";
  if (connection.status === "pending" || connection.status === "preview") return "pending";
  if (connection.status === "disabled" || connection.status === "not_connected") return "off";
  return isWiiiConnectReady(connection) ? "ok" : "warn";
}

function formatConnectionStatus(status: string | undefined): string {
  if (status === "connected") return "Đã kết nối";
  if (status === "preview") return "Preview";
  if (status === "pending") return "Đang chờ";
  if (status === "expired") return "Hết hạn";
  if (status === "error") return "Lỗi";
  if (status === "disabled") return "Tắt";
  if (status === "not_connected") return "Chưa nối";
  return compactValue(status, "Không rõ");
}

function serverStatusItem(status: RuntimeConnectionStatus): CapabilityStatusItem {
  if (status === "connected") {
    return {
      id: "server",
      label: "Máy chủ",
      value: "Đã kết nối",
      tone: "ok",
      title: "Backend đang phản hồi health check.",
    };
  }
  if (status === "checking") {
    return {
      id: "server",
      label: "Máy chủ",
      value: "Đang kiểm tra",
      tone: "pending",
      title: "Wiii đang kiểm tra kết nối backend.",
    };
  }
  if (status === "degraded") {
    return {
      id: "server",
      label: "Máy chủ",
      value: "Gián đoạn",
      tone: "warn",
      title: "Backend phản hồi nhưng chưa ở trạng thái khỏe hoàn toàn.",
    };
  }
  return {
    id: "server",
    label: "Máy chủ",
    value: "Mất kết nối",
    tone: "off",
    title: "Frontend chưa kết nối được backend.",
  };
}

function hostStatusItem(
  capabilities: HostCapabilities | null,
  currentContext: HostContext | null,
  isEmbedded: boolean,
): CapabilityStatusItem {
  const { hostType, hostName, connectorId, isLms } = hostIdentity(
    capabilities,
    currentContext,
  );
  if (hostType || hostName || connectorId) {
    return {
      id: "host",
      label: isLms ? "LMS" : "Host",
      value: hostName || connectorId || hostType || "Đã kết nối",
      tone: "ok",
      title: isLms
        ? "Wiii đang nhận ngữ cảnh từ LMS."
        : "Wiii đang nhận ngữ cảnh từ host.",
    };
  }
  return {
    id: "host",
    label: "Host",
    value: isEmbedded ? "Đang chờ" : "Cá nhân",
    tone: isEmbedded ? "pending" : "off",
    title: isEmbedded
      ? "Embed đã mở nhưng host chưa gửi context/capabilities."
      : "Wiii đang chạy độc lập, không ở trong LMS/host.",
  };
}

function hostActionStatusItem(toolNames: Set<string>): CapabilityStatusItem {
  const count = toolNames.size;
  if (count > 0) {
    return {
      id: "host_actions",
      label: "Hành động host",
      value: `${count} tác vụ`,
      tone: "ok",
      title: "Host đã khai báo các tác vụ Wiii có thể preview/request.",
    };
  }
  return {
    id: "host_actions",
    label: "Hành động host",
    value: "Chưa nối",
    tone: "off",
    title: "Chưa có host action bridge cho lượt hiện tại.",
  };
}

function lmsAuthoringStatusItem(
  capabilities: HostCapabilities | null,
  currentContext: HostContext | null,
  toolNames: Set<string>,
): CapabilityStatusItem {
  const { isLms } = hostIdentity(capabilities, currentContext);
  const hasPreview = hasTool(toolNames, LMS_PREVIEW_TOOLS);
  const hasApply = hasTool(toolNames, LMS_APPLY_TOOLS);

  if (isLms && hasPreview && hasApply) {
    return {
      id: "lms_authoring",
      label: "LMS soạn bài",
      value: "Preview + Apply",
      tone: "ok",
      title: "LMS authoring đã có preview và apply qua approval_token.",
    };
  }
  if (isLms && hasPreview) {
    return {
      id: "lms_authoring",
      label: "LMS soạn bài",
      value: "Preview",
      tone: "warn",
      title: "LMS authoring có preview nhưng chưa có apply action.",
    };
  }
  return {
    id: "lms_authoring",
    label: "LMS soạn bài",
    value: isLms ? "Chỉ đọc" : "Chưa nối",
    tone: isLms ? "warn" : "off",
    title: isLms
      ? "LMS đang kết nối nhưng chưa khai báo authoring actions."
      : "Chưa có LMS authoring connection.",
  };
}

function pointyStatusItem(
  currentContext: HostContext | null,
  toolNames: Set<string>,
  isEmbedded: boolean,
): CapabilityStatusItem {
  const hasHostPointy =
    hasTool(toolNames, ["ui.cursor_move", "ui.highlight"])
    || hasToolPrefix(toolNames, "ui.");
  const targets = availableTargetCount(currentContext);

  if (hasHostPointy) {
    return {
      id: "pointy",
      label: "Pointy",
      value: "Host",
      tone: "ok",
      title: "Host đã khai báo UI actions cho Pointy.",
    };
  }
  if (targets > 0) {
    return {
      id: "pointy",
      label: "Pointy",
      value: `${targets} target`,
      tone: "ok",
      title: "Pointy đã quét được target trong giao diện hiện tại.",
    };
  }
  if (!isEmbedded) {
    return {
      id: "pointy",
      label: "Pointy",
      value: "Local",
      tone: "pending",
      title: "Pointy local sẵn sàng quét target trong Wiii standalone.",
    };
  }
  return {
    id: "pointy",
    label: "Pointy",
    value: "Chưa nối",
    tone: "off",
    title: "Embed chưa có UI action bridge hoặc target inventory cho Pointy.",
  };
}

function buildRuntimeSection(
  item: CapabilityStatusItem,
  input: BuildCapabilityStatusInput,
): CapabilityDashboardSection {
  const metrics: CapabilityDashboardMetric[] = [
    { label: "Kết nối", value: item.value, tone: item.tone },
    { label: "Phiên bản", value: compactValue(input.serverVersion, "Chưa báo") },
    { label: "Health check", value: formatCheckedAt(input.lastCheckedAt) },
  ];
  if (input.errorMessage) {
    metrics.push({
      label: "Lỗi gần nhất",
      value: compactValue(input.errorMessage),
      tone: "warn",
    });
  }
  return {
    id: "server",
    title: "Runtime backend",
    summary: item.value,
    tone: item.tone,
    metrics,
  };
}

function buildHostSection(
  item: CapabilityStatusItem,
  input: BuildCapabilityStatusInput,
): CapabilityDashboardSection {
  const { hostType, hostName, connectorId } = hostIdentity(
    input.capabilities,
    input.currentContext,
  );
  return {
    id: "host",
    title: "Host & LMS",
    summary: item.value,
    tone: item.tone,
    metrics: [
      { label: "Loại host", value: compactValue(hostType, input.isEmbedded ? "Đang chờ" : "Standalone") },
      { label: "Tên host", value: compactValue(hostName, "Chưa có") },
      { label: "Connector", value: compactValue(connectorId, "Chưa có") },
      {
        label: "Tài nguyên",
        value: `${input.capabilities?.resources?.length ?? 0} resource`,
      },
      {
        label: "Surface",
        value: `${input.capabilities?.surfaces?.length ?? 0} surface`,
      },
    ],
  };
}

function buildHostActionSection(
  item: CapabilityStatusItem,
  capabilities: HostCapabilities | null,
): CapabilityDashboardSection {
  const tools = capabilities?.tools ?? [];
  const mutating = tools.filter((tool) => tool.mutates_state).length;
  const confirmations = tools.filter((tool) => tool.requires_confirmation).length;
  return {
    id: "host_actions",
    title: "Hành động host",
    summary: item.value,
    tone: item.tone,
    metrics: [
      { label: "Tổng tác vụ", value: `${tools.length} tác vụ` },
      {
        label: "Ghi dữ liệu",
        value: mutating > 0 ? `${mutating} tác vụ` : "Không",
        tone: mutating > 0 ? "warn" : "ok",
      },
      {
        label: "Cần xác nhận",
        value: confirmations > 0 ? `${confirmations} tác vụ` : "Không",
        tone: confirmations > 0 ? "warn" : "ok",
      },
      {
        label: "Mặc định",
        value: tools.length > 0 ? "Bind theo host" : "Không bind",
      },
    ],
  };
}

function buildLmsAuthoringSection(
  item: CapabilityStatusItem,
  input: BuildCapabilityStatusInput,
  toolNames: Set<string>,
): CapabilityDashboardSection {
  const { isLms } = hostIdentity(input.capabilities, input.currentContext);
  const hasPreview = hasTool(toolNames, LMS_PREVIEW_TOOLS);
  const hasApply = hasTool(toolNames, LMS_APPLY_TOOLS);
  return {
    id: "lms_authoring",
    title: "LMS soạn bài",
    summary: item.value,
    tone: item.tone,
    metrics: [
      { label: "Kết nối LMS", value: isLms ? "Có" : "Chưa nối", tone: isLms ? "ok" : "off" },
      { label: "Preview", value: hasPreview ? "Có" : "Thiếu", tone: hasPreview ? "ok" : "warn" },
      {
        label: "Apply",
        value: hasApply ? "Qua approval_token" : "Thiếu",
        tone: hasApply ? "ok" : "warn",
      },
      {
        label: "An toàn",
        value: isLms ? "Preview trước, apply sau" : "Không mutate",
      },
    ],
  };
}

function buildPointySection(
  item: CapabilityStatusItem,
  currentContext: HostContext | null,
  toolNames: Set<string>,
  isEmbedded: boolean,
): CapabilityDashboardSection {
  const hasHostPointy =
    hasTool(toolNames, ["ui.cursor_move", "ui.highlight"])
    || hasToolPrefix(toolNames, "ui.");
  const targets = availableTargetCount(currentContext);
  return {
    id: "pointy",
    title: "Pointy",
    summary: item.value,
    tone: item.tone,
    metrics: [
      { label: "Bridge UI", value: hasHostPointy ? "Host" : isEmbedded ? "Chưa nối" : "Local" },
      { label: "Target", value: `${targets} target` },
      {
        label: "Trạng thái",
        value: hasHostPointy || targets > 0 || !isEmbedded ? "Sẵn sàng" : "Chờ host",
        tone: item.tone,
      },
    ],
  };
}

function buildWiiiConnectSection(
  snapshot: WiiiConnectRuntimeSnapshot | null | undefined,
): CapabilityDashboardSection {
  if (!snapshot) {
    return {
      id: "wiii_connect",
      title: "Wiii Connect",
      summary: "Chưa có snapshot",
      tone: "pending",
      metrics: [
        { label: "Snapshot", value: "Chưa có" },
        { label: "Nguồn", value: "Chờ chat_lifecycle" },
      ],
    };
  }

  const connections = snapshot.connections ?? [];
  const readyCount = connections.filter(isWiiiConnectReady).length;
  const warningCount = (snapshot.warnings?.length ?? 0)
    + connections.reduce((total, connection) => total + (connection.warnings?.length ?? 0), 0);
  const pathCount = snapshot.path_capabilities?.length ?? 0;
  const metrics: CapabilityDashboardMetric[] = [
    { label: "Phiên bản", value: compactValue(snapshot.version) },
    { label: "Surface", value: compactValue(snapshot.surface, "Không rõ") },
    {
      label: "Agent-ready",
      value: `${readyCount}/${connections.length} kết nối`,
      tone: readyCount > 0 ? "ok" : "pending",
    },
    {
      label: "Cảnh báo",
      value: warningCount > 0 ? `${warningCount} cảnh báo` : "Không",
      tone: warningCount > 0 ? "warn" : "ok",
    },
    {
      label: "Path policy",
      value: pathCount > 0 ? `${pathCount} path` : "Chưa có",
      tone: pathCount > 0 ? "ok" : "pending",
    },
  ];

  for (const connection of connections.slice(0, 10)) {
    const status = formatConnectionStatus(connection.status);
    const detailCount = [
      typeof connection.attachment_count === "number" ? `${connection.attachment_count} file` : "",
      typeof connection.source_ref_count === "number" ? `${connection.source_ref_count} nguồn` : "",
      typeof connection.target_count === "number" ? `${connection.target_count} target` : "",
      typeof connection.tool_count === "number" ? `${connection.tool_count} tool` : "",
    ].filter(Boolean);
    metrics.push({
      label: compactValue(connection.label || connection.slug),
      value: detailCount.length > 0 ? `${status} · ${detailCount.join(", ")}` : status,
      tone: wiiiConnectConnectionTone(connection),
    });
  }

  return {
    id: "wiii_connect",
    title: "Wiii Connect",
    summary: `${readyCount}/${connections.length} sẵn sàng`,
    tone: warningCount > 0 ? "warn" : readyCount > 0 ? "ok" : "pending",
    metrics,
  };
}

function buildPathSection(
  runtimePath: RuntimePathSnapshot | null | undefined,
): CapabilityDashboardSection {
  if (!runtimePath) {
    return {
      id: "path",
      title: "Path lượt gần nhất",
      summary: "Chưa có lượt chạy",
      tone: "pending",
      metrics: [
        { label: "Path", value: "Chưa có" },
        { label: "Tool đã thấy", value: "Không" },
        { label: "Tool bị chặn", value: "Không" },
      ],
    };
  }

  const blocked = runtimePath.suppressedTools?.length ?? 0;
  return {
    id: "path",
    title: "Path lượt gần nhất",
    summary: compactValue(runtimePath.lane || runtimePath.eventName, "Đang theo dõi"),
    tone: runtimePath.status === "error" ? "warn" : "ok",
    metrics: [
      { label: "Path", value: compactValue(runtimePath.lane, "Chưa phân loại") },
      { label: "Pha", value: compactValue(runtimePath.phase, "Chưa có") },
      { label: "Sự kiện", value: compactValue(runtimePath.eventName, "Chưa có") },
      { label: "Surface", value: compactValue(runtimePath.hostSurface, "Không") },
      { label: "Tool đã thấy", value: formatToolGroupSummary(runtimePath.observedTools) },
      {
        label: "Tool bị chặn",
        value: formatToolGroupSummary(runtimePath.suppressedTools),
        tone: blocked > 0 ? "warn" : "ok",
      },
    ],
  };
}

function summarizeOverall(items: CapabilityStatusItem[]): {
  summary: string;
  tone: CapabilityStatusTone;
} {
  const server = items.find((item) => item.id === "server");
  const host = items.find((item) => item.id === "host");
  const lms = items.find((item) => item.id === "lms_authoring");
  if (server?.tone === "off") return { summary: "Runtime mất kết nối", tone: "off" };
  if (server?.tone === "warn") return { summary: "Runtime gián đoạn", tone: "warn" };
  if (server?.tone === "pending") return { summary: "Đang kiểm tra runtime", tone: "pending" };
  if (lms?.tone === "ok") return { summary: "LMS sẵn sàng", tone: "ok" };
  if (host?.tone === "ok") return { summary: "Host đã nối", tone: "ok" };
  return { summary: "Runtime sẵn sàng", tone: "ok" };
}

export function buildCapabilityStatusViewModel(
  input: BuildCapabilityStatusInput,
): CapabilityStatusViewModel {
  const toolNames = normalizedToolNames(input.capabilities);
  const items = [
    serverStatusItem(input.connectionStatus),
    hostStatusItem(input.capabilities, input.currentContext, input.isEmbedded),
    hostActionStatusItem(toolNames),
    lmsAuthoringStatusItem(input.capabilities, input.currentContext, toolNames),
    pointyStatusItem(input.currentContext, toolNames, input.isEmbedded),
  ];
  const byId = new Map(items.map((item) => [item.id, item]));
  const overall = summarizeOverall(items);

  return {
    items,
    sections: [
      buildRuntimeSection(byId.get("server")!, input),
      buildHostSection(byId.get("host")!, input),
      buildHostActionSection(byId.get("host_actions")!, input.capabilities),
      buildLmsAuthoringSection(byId.get("lms_authoring")!, input, toolNames),
      buildPointySection(byId.get("pointy")!, input.currentContext, toolNames, input.isEmbedded),
      buildWiiiConnectSection(input.runtimePath?.wiiiConnect),
      buildPathSection(input.runtimePath),
    ],
    summary: overall.summary,
    overallTone: overall.tone,
  };
}

export function buildCapabilityStatuses(
  input: BuildCapabilityStatusInput,
): CapabilityStatusItem[] {
  return buildCapabilityStatusViewModel(input).items;
}
