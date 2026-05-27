import {
  Cable,
  ChevronDown,
  GraduationCap,
  MousePointer2,
  Network,
  Route,
  Server,
  Workflow,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  buildCapabilityStatusViewModel,
  runtimePathFromLifecycleEvents,
  type CapabilityDashboardSection,
  type CapabilityStatusItem,
  type CapabilityStatusTone,
} from "@/lib/capability-status";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";

const toneClasses: Record<CapabilityStatusTone, string> = {
  ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  pending: "border-sky-200 bg-sky-50 text-sky-700",
  off: "border-[var(--border)] bg-surface-secondary text-text-tertiary",
};

const dashboardToneClasses: Record<CapabilityStatusTone, string> = {
  ok: "border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50",
  warn: "border-amber-200 bg-white text-amber-800 hover:bg-amber-50",
  pending: "border-sky-200 bg-white text-sky-700 hover:bg-sky-50",
  off: "border-[var(--border)] bg-white text-text-tertiary hover:bg-surface-secondary",
};

const subtleToneClasses: Record<CapabilityStatusTone, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  pending: "bg-sky-500",
  off: "bg-zinc-400",
};

const iconById: Record<CapabilityStatusItem["id"], typeof Server> = {
  server: Server,
  host: Cable,
  host_actions: Workflow,
  lms_authoring: GraduationCap,
  pointy: MousePointer2,
};

const sectionIconById: Record<CapabilityDashboardSection["id"], typeof Server> = {
  server: Server,
  host: Cable,
  host_actions: Workflow,
  lms_authoring: GraduationCap,
  pointy: MousePointer2,
  wiii_connect: Network,
  path: Route,
};

interface CapabilityStatusBarProps {
  compact?: boolean;
}

interface PanelPosition {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}

const DEFAULT_PANEL_POSITION: PanelPosition = {
  top: 48,
  left: 12,
  width: 768,
  maxHeight: 448,
};

function isEmbeddedWindow(): boolean {
  if (typeof window === "undefined") return false;
  return window.parent !== window;
}

function computePanelPosition(anchor: HTMLElement | null): PanelPosition {
  if (typeof window === "undefined" || !anchor) {
    return DEFAULT_PANEL_POSITION;
  }
  const margin = 12;
  const gap = 8;
  const minHeight = 240;
  const preferredHeight = 448;
  const preferredWidth = 768;
  const rect = anchor.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.min(preferredWidth, Math.max(320, viewportWidth - margin * 2));
  const left = Math.min(
    Math.max(rect.left, margin),
    Math.max(margin, viewportWidth - width - margin),
  );
  const spaceBelow = viewportHeight - rect.bottom - margin;
  const spaceAbove = rect.top - margin;
  const openBelow = spaceBelow >= minHeight || spaceBelow >= spaceAbove;
  const availableHeight = Math.max(
    minHeight,
    openBelow ? spaceBelow - gap : spaceAbove - gap,
  );
  const maxHeight = Math.min(preferredHeight, availableHeight);
  const top = openBelow
    ? Math.min(rect.bottom + gap, viewportHeight - maxHeight - margin)
    : Math.max(margin, rect.top - maxHeight - gap);

  return { top, left, width, maxHeight };
}

export function CapabilityStatusBar({ compact = false }: CapabilityStatusBarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [panelPosition, setPanelPosition] = useState<PanelPosition>(
    DEFAULT_PANEL_POSITION,
  );
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
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
  const isEmbedded = isEmbeddedWindow();

  const runtimePath = useMemo(
    () =>
      runtimePathFromLifecycleEvents(
        streamingLifecycleEvents,
        lastCompletedLifecycleEvents,
      ),
    [streamingLifecycleEvents, lastCompletedLifecycleEvents],
  );

  const viewModel = useMemo(
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

  useEffect(() => {
    if (!isOpen) return;
    const updatePosition = () => {
      setPanelPosition(computePanelPosition(toggleRef.current));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [isOpen]);

  const dashboardPanel = isOpen ? (
    <div
      id={panelId}
      role="region"
      aria-label="Dashboard trạng thái runtime"
      className="fixed z-[1000] overflow-hidden rounded-lg border border-[var(--border)] bg-white shadow-xl"
      style={{
        top: panelPosition.top,
        left: panelPosition.left,
        width: panelPosition.width,
        maxHeight: panelPosition.maxHeight,
      }}
      data-testid="capability-dashboard-panel"
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Route size={15} className="shrink-0 text-text-secondary" aria-hidden="true" />
          <span className="truncate text-sm font-semibold text-text">
            Dashboard runtime
          </span>
        </div>
        <span
          className={`shrink-0 rounded-md border px-2 py-1 text-[11px] ${toneClasses[viewModel.overallTone]}`}
        >
          {viewModel.summary}
        </span>
      </div>

      <div
        className="overflow-auto px-3 py-1"
        style={{ maxHeight: Math.max(160, panelPosition.maxHeight - 45) }}
      >
        {viewModel.sections.map((section) => {
          const Icon = sectionIconById[section.id];
          return (
            <section
              key={section.id}
              className="border-b border-[var(--border)] py-3 last:border-b-0"
              data-testid={`capability-dashboard-section-${section.id}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${subtleToneClasses[section.tone]}`}
                    aria-hidden="true"
                  />
                  <Icon size={14} className="shrink-0 text-text-secondary" aria-hidden="true" />
                  <h3 className="truncate text-xs font-semibold uppercase text-text-secondary">
                    {section.title}
                  </h3>
                </div>
                <span className="max-w-[45%] truncate text-right text-xs font-medium text-text">
                  {section.summary}
                </span>
              </div>

              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                {section.metrics.map((metric, index) => (
                  <div
                    key={`${section.id}-${metric.label}-${index}`}
                    className="min-w-0 rounded-md bg-surface-secondary px-2 py-1.5"
                  >
                    <dt className="truncate text-[10px] uppercase tracking-wide text-text-tertiary">
                      {metric.label}
                    </dt>
                    <dd
                      className={`mt-0.5 truncate text-xs font-medium ${
                        metric.tone ? toneTextClass(metric.tone) : "text-text"
                      }`}
                    >
                      {metric.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          );
        })}
      </div>
    </div>
  ) : null;

  return (
    <div
      className={`relative max-w-full ${compact ? "pb-0.5" : "pb-2"}`}
      aria-label="Trạng thái kết nối Wiii"
      data-testid="capability-status-bar"
    >
      <div className="flex max-w-full items-center gap-1.5 overflow-x-auto">
        <button
          ref={toggleRef}
          type="button"
          className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 text-[11px] leading-none transition-colors ${dashboardToneClasses[viewModel.overallTone]}`}
          aria-expanded={isOpen}
          aria-controls={panelId}
          title="Mở dashboard runtime và capability"
          data-testid="capability-dashboard-toggle"
          onClick={() => setIsOpen((current) => !current)}
        >
          <Route size={13} aria-hidden="true" />
          <span className="font-medium">Runtime</span>
          <span className="opacity-80">{viewModel.summary}</span>
          <ChevronDown
            size={12}
            className={`transition-transform ${isOpen ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>

        {viewModel.items.map((item) => {
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

      {dashboardPanel
        ? typeof document === "undefined"
          ? dashboardPanel
          : createPortal(dashboardPanel, document.body)
        : null}
    </div>
  );
}

function toneTextClass(tone: CapabilityStatusTone): string {
  if (tone === "ok") return "text-emerald-700";
  if (tone === "warn") return "text-amber-800";
  if (tone === "pending") return "text-sky-700";
  return "text-text-tertiary";
}
