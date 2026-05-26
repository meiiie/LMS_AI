import {
  Cable,
  GraduationCap,
  MousePointer2,
  Server,
  Workflow,
} from "lucide-react";
import { useMemo } from "react";
import {
  buildCapabilityStatuses,
  type CapabilityStatusItem,
  type CapabilityStatusTone,
} from "@/lib/capability-status";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";

const toneClasses: Record<CapabilityStatusTone, string> = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  pending: "border-sky-200 bg-sky-50 text-sky-700",
  off: "border-[var(--border)] bg-surface-secondary text-text-tertiary",
};

const iconById: Record<CapabilityStatusItem["id"], typeof Server> = {
  server: Server,
  host: Cable,
  host_actions: Workflow,
  lms_authoring: GraduationCap,
  pointy: MousePointer2,
};

interface CapabilityStatusBarProps {
  compact?: boolean;
}

function isEmbeddedWindow(): boolean {
  if (typeof window === "undefined") return false;
  return window.parent !== window;
}

export function CapabilityStatusBar({ compact = false }: CapabilityStatusBarProps) {
  const connectionStatus = useConnectionStore((state) => state.status);
  const capabilities = useHostContextStore((state) => state.capabilities);
  const currentContext = useHostContextStore((state) => state.currentContext);
  const isEmbedded = isEmbeddedWindow();

  const items = useMemo(
    () =>
      buildCapabilityStatuses({
        connectionStatus,
        capabilities,
        currentContext,
        isEmbedded,
      }),
    [connectionStatus, capabilities, currentContext, isEmbedded],
  );

  return (
    <div
      className={`flex max-w-full items-center gap-1.5 overflow-x-auto ${
        compact ? "pb-0.5" : "pb-2"
      }`}
      aria-label="Trạng thái kết nối Wiii"
      data-testid="capability-status-bar"
    >
      {items.map((item) => {
        const Icon = iconById[item.id];
        return (
          <span
            key={item.id}
            className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 text-[11px] leading-none ${toneClasses[item.tone]}`}
            title={item.title}
            data-testid={`capability-status-${item.id}`}
          >
            <Icon size={13} aria-hidden="true" />
            <span className="font-medium">{item.label}</span>
            <span className="opacity-80">{item.value}</span>
          </span>
        );
      })}
    </div>
  );
}
