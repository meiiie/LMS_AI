import { useEffect } from "react";
import { Sparkles } from "lucide-react";
import { useOrgAdminStore } from "@/stores/org-admin-store";
import type { AdminAuthEvent } from "@/api/types";
import type { OrgHostActionView } from "@/stores/org-admin-store";

const VIEW_OPTIONS: Array<{ id: OrgHostActionView; label: string }> = [
  { id: "all", label: "Tất cả" },
  { id: "previews", label: "Preview" },
  { id: "applies", label: "Apply" },
  { id: "publishes", label: "Publish" },
];

export function OrgManagerAudit({ orgId }: { orgId: string }) {
  const {
    hostActionEvents,
    hostActionEventsTotal,
    hostActionEventsPage,
    hostActionView,
    hostActionLoading,
    fetchHostActionEvents,
    setHostActionView,
  } = useOrgAdminStore();

  useEffect(() => {
    void fetchHostActionEvents(orgId, 0);
  }, [orgId, hostActionView, fetchHostActionEvents]);

  const totalPages = Math.max(1, Math.ceil(hostActionEventsTotal / 20));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {VIEW_OPTIONS.map((view) => (
          <button
            key={view.id}
            type="button"
            onClick={() => setHostActionView(view.id)}
            className={`min-h-[40px] rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              hostActionView === view.id
                ? "bg-[var(--accent)] text-white"
                : "border border-border bg-surface-secondary text-text-secondary hover:text-text"
            }`}
          >
            {view.label}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border bg-surface-secondary/30 p-4">
        <div className="mb-4 flex items-start gap-3">
          <div className="rounded-lg bg-[var(--accent)]/10 p-2 text-[var(--accent)]">
            <Sparkles size={16} />
          </div>
          <div>
            <div className="text-sm font-medium text-text">
              Timeline host action của tổ chức
            </div>
            <div className="text-xs text-text-secondary">
              Theo dõi preview, apply và publish mà Wiii đã đề xuất hoặc thực
              hiện trong tổ chức này.
            </div>
          </div>
        </div>

        {hostActionEvents.length === 0 && !hostActionLoading ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-xs text-text-tertiary">
            Chưa có host action nào cho chế độ xem hiện tại.
          </div>
        ) : (
          <ol className="space-y-4" aria-label="Org host action timeline">
            {hostActionEvents.map((entry) => (
              <OrgTimelineItem key={entry.id} entry={entry} />
            ))}
          </ol>
        )}
      </div>

      {hostActionEventsTotal > 0 && (
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>
            Trang {hostActionEventsPage + 1} / {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() =>
                void fetchHostActionEvents(
                  orgId,
                  Math.max(0, hostActionEventsPage - 1),
                )
              }
              disabled={hostActionEventsPage === 0 || hostActionLoading}
              className="min-h-[36px] rounded-lg border border-border px-3 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Trước
            </button>
            <button
              type="button"
              onClick={() =>
                void fetchHostActionEvents(
                  orgId,
                  Math.min(totalPages - 1, hostActionEventsPage + 1),
                )
              }
              disabled={
                hostActionEventsPage + 1 >= totalPages || hostActionLoading
              }
              className="min-h-[36px] rounded-lg border border-border px-3 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Sau
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function OrgTimelineItem({ entry }: { entry: AdminAuthEvent }) {
  const metadata = (entry.metadata ?? {}) as Record<string, unknown>;
  const summary =
    typeof metadata.summary === "string" && metadata.summary.trim().length > 0
      ? metadata.summary
      : entry.reason || entry.event_type;
  const target =
    typeof metadata.target_label === "string" &&
    metadata.target_label.trim().length > 0
      ? metadata.target_label
      : typeof metadata.lesson_id === "string"
        ? metadata.lesson_id
        : typeof metadata.quiz_id === "string"
          ? metadata.quiz_id
          : "—";

  return (
    <li className="relative pl-6">
      <span
        aria-hidden="true"
        className="absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full bg-[var(--accent)] shadow-[0_0_0_4px_rgba(59,130,246,0.12)]"
      />
      <span
        aria-hidden="true"
        className="absolute bottom-[-16px] left-[5px] top-4 w-px bg-border"
      />
      <div className="rounded-xl border border-border bg-surface px-4 py-3 shadow-sm">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[var(--accent)]/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">
            {formatEventLabel(entry.event_type)}
          </span>
          <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] font-mono text-text-secondary">
            {String(metadata.preview_kind || entry.provider)}
          </span>
          <span className="ml-auto text-xs text-text-tertiary">
            {entry.created_at
              ? new Date(entry.created_at).toLocaleString("vi-VN")
              : "—"}
          </span>
        </div>
        <div className="space-y-2">
          <div className="text-sm font-medium text-text">{summary}</div>
          <div className="grid gap-2 text-xs text-text-secondary sm:grid-cols-2">
            <MetaItem label="User" value={entry.user_id} />
            <MetaItem label="Target" value={String(target)} mono />
            <MetaItem
              label="Request"
              value={String(metadata.request_id || "—")}
              mono
            />
            <MetaItem
              label="Surface"
              value={String(metadata.surface || "preview_panel")}
            />
          </div>
        </div>
      </div>
    </li>
  );
}

function MetaItem({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <span className="block text-[11px] uppercase tracking-wider text-text-tertiary">
        {label}
      </span>
      <span className={`${mono ? "font-mono" : ""} text-text`}>{value}</span>
    </div>
  );
}

function formatEventLabel(eventType: string): string {
  if (eventType.endsWith("preview_created")) return "Preview";
  if (eventType.endsWith("apply_confirmed")) return "Apply";
  if (eventType.endsWith("publish_confirmed")) return "Publish";
  return eventType;
}
