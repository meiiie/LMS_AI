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

export interface CapabilityStatusItem {
  id: "server" | "host" | "host_actions" | "lms_authoring" | "pointy";
  label: string;
  value: string;
  tone: CapabilityStatusTone;
  title: string;
}

interface BuildCapabilityStatusInput {
  connectionStatus: RuntimeConnectionStatus;
  capabilities: HostCapabilities | null;
  currentContext: HostContext | null;
  isEmbedded: boolean;
}

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
  const hostType = String(
    currentContext?.host_type || capabilities?.host_type || "",
  ).trim();
  const hostName = String(
    currentContext?.host_name || capabilities?.host_name || "",
  ).trim();
  const connectorId = String(
    currentContext?.connector_id || capabilities?.connector_id || "",
  ).trim();
  const isLms = hostType.toLowerCase() === "lms";
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
  const isLms = String(
    currentContext?.host_type || capabilities?.host_type || "",
  ).toLowerCase() === "lms";
  const hasPreview = hasTool(toolNames, [
    "authoring.preview_lesson_patch",
    "authoring.generate_course_from_document",
  ]);
  const hasApply = hasTool(toolNames, [
    "authoring.apply_lesson_patch",
    "authoring.apply_course_plan",
  ]);

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
  const hasHostPointy = hasTool(toolNames, ["ui.cursor_move", "ui.highlight"])
    || hasToolPrefix(toolNames, "ui.");
  const availableTargets = currentContext?.page?.metadata?.available_targets;
  const hasLocalTargets = Array.isArray(availableTargets) && availableTargets.length > 0;

  if (hasHostPointy) {
    return {
      id: "pointy",
      label: "Pointy",
      value: "Host",
      tone: "ok",
      title: "Host đã khai báo UI actions cho Pointy.",
    };
  }
  if (hasLocalTargets) {
    return {
      id: "pointy",
      label: "Pointy",
      value: `${availableTargets.length} target`,
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

export function buildCapabilityStatuses({
  connectionStatus,
  capabilities,
  currentContext,
  isEmbedded,
}: BuildCapabilityStatusInput): CapabilityStatusItem[] {
  const toolNames = normalizedToolNames(capabilities);
  return [
    serverStatusItem(connectionStatus),
    hostStatusItem(capabilities, currentContext, isEmbedded),
    hostActionStatusItem(toolNames),
    lmsAuthoringStatusItem(capabilities, currentContext, toolNames),
    pointyStatusItem(currentContext, toolNames, isEmbedded),
  ];
}
