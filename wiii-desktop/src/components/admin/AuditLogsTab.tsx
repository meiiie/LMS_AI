/**
 * Audit Logs tab - admin actions, auth events, and host action timeline.
 */
import { useEffect } from "react";
import { ChevronLeft, ChevronRight, Loader2, Sparkles } from "lucide-react";
import { useAdminStore } from "@/stores/admin-store";
import type { AuditSubTab } from "@/stores/admin-store";
import type { AdminAuthEvent } from "@/api/types";

const PAGE_SIZE = 20;

const SUB_TABS: { id: AuditSubTab; label: string }[] = [
  { id: "admin", label: "Admin actions" },
  { id: "auth", label: "Auth events" },
  { id: "host_actions", label: "Host actions" },
];

export function AuditLogsTab() {
  const {
    auditSubTab,
    setAuditSubTab,
    auditLogs,
    auditLogsTotal,
    auditLogsPage,
    authEvents,
    authEventsTotal,
    authEventsPage,
    hostActionEvents,
    hostActionEventsTotal,
    hostActionEventsPage,
    loading,
    fetchAuditLogs,
    fetchAuthEvents,
    fetchHostActionEvents,
  } = useAdminStore();

  useEffect(() => {
    if (auditSubTab === "admin") {
      void fetchAuditLogs(0);
      return;
    }
    if (auditSubTab === "auth") {
      void fetchAuthEvents(0);
      return;
    }
    void fetchHostActionEvents(0);
  }, [auditSubTab, fetchAuditLogs, fetchAuthEvents, fetchHostActionEvents]);

  return (
    <div className="space-y-4">
      <div className="flex gap-1.5">
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setAuditSubTab(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              auditSubTab === tab.id
                ? "bg-[var(--accent)] text-white"
                : "bg-surface-secondary text-text-secondary hover:text-text border border-border"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {auditSubTab === "admin" ? (
        <AdminAuditTable
          entries={auditLogs}
          total={auditLogsTotal}
          page={auditLogsPage}
          loading={loading}
          onPageChange={(nextPage) => void fetchAuditLogs(nextPage)}
        />
      ) : auditSubTab === "auth" ? (
        <AuthEventsTable
          entries={authEvents}
          total={authEventsTotal}
          page={authEventsPage}
          loading={loading}
          onPageChange={(nextPage) => void fetchAuthEvents(nextPage)}
        />
      ) : (
        <HostActionTimeline
          entries={hostActionEvents}
          total={hostActionEventsTotal}
          page={hostActionEventsPage}
          loading={loading}
          onPageChange={(nextPage) => void fetchHostActionEvents(nextPage)}
        />
      )}
    </div>
  );
}

function AdminAuditTable({
  entries,
  total,
  page,
  loading,
  onPageChange,
}: {
  entries: {
    id: string;
    actor_name: string;
    action: string;
    target_type: string;
    target_id: string;
    ip_address: string;
    occurred_at: string | null;
  }[];
  total: number;
  page: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-secondary text-text-secondary text-left">
              <th className="px-4 py-2.5 font-medium">Time</th>
              <th className="px-4 py-2.5 font-medium">Actor</th>
              <th className="px-4 py-2.5 font-medium">Action</th>
              <th className="px-4 py-2.5 font-medium">Target</th>
              <th className="px-4 py-2.5 font-medium">IP</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-text-tertiary text-xs"
                >
                  <EmptyAuditState
                    title="Chưa có admin action nào"
                    description="Khi quản trị viên đổi role, cập nhật feature flag hoặc thao tác dữ liệu hệ thống, Wiii sẽ ghi lại tại đây để dễ truy vết."
                  />
                </td>
              </tr>
            )}
            {entries.length === 0 && loading && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-text-tertiary text-xs"
                >
                  <LoadingAuditState label="Đang tải admin actions..." />
                </td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr
                key={entry.id}
                className="border-t border-border hover:bg-surface-secondary transition-colors"
              >
                <td className="px-4 py-2.5 text-xs text-text-tertiary whitespace-nowrap">
                  {entry.occurred_at
                    ? new Date(entry.occurred_at).toLocaleString("vi-VN")
                    : "—"}
                </td>
                <td className="px-4 py-2.5 text-text">
                  {entry.actor_name || "—"}
                </td>
                <td className="px-4 py-2.5">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-surface-tertiary text-text-secondary font-mono">
                    {entry.action}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-text-secondary truncate max-w-[200px]">
                  {entry.target_type}: {entry.target_id}
                </td>
                <td className="px-4 py-2.5 text-xs text-text-tertiary font-mono">
                  {entry.ip_address}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <PaginationBar
          page={page}
          totalPages={totalPages}
          total={total}
          loading={loading}
          onPageChange={onPageChange}
        />
      )}
    </>
  );
}

function AuthEventsTable({
  entries,
  total,
  page,
  loading,
  onPageChange,
}: {
  entries: AdminAuthEvent[];
  total: number;
  page: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-secondary text-text-secondary text-left">
              <th className="px-4 py-2.5 font-medium">Time</th>
              <th className="px-4 py-2.5 font-medium">User</th>
              <th className="px-4 py-2.5 font-medium">Event</th>
              <th className="px-4 py-2.5 font-medium">Provider</th>
              <th className="px-4 py-2.5 font-medium">Result</th>
              <th className="px-4 py-2.5 font-medium">IP</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-text-tertiary text-xs"
                >
                  <EmptyAuditState
                    title="Chưa có auth event nào"
                    description="Các lần đăng nhập, refresh token, OAuth/dev-login và sự kiện bảo mật tài khoản sẽ xuất hiện ở đây khi hệ thống ghi nhận được."
                  />
                </td>
              </tr>
            )}
            {entries.length === 0 && loading && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-text-tertiary text-xs"
                >
                  <LoadingAuditState label="Đang tải auth events..." />
                </td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr
                key={entry.id}
                className="border-t border-border hover:bg-surface-secondary transition-colors"
              >
                <td className="px-4 py-2.5 text-xs text-text-tertiary whitespace-nowrap">
                  {entry.created_at
                    ? new Date(entry.created_at).toLocaleString("vi-VN")
                    : "—"}
                </td>
                <td className="px-4 py-2.5 text-text text-xs truncate max-w-[150px]">
                  {entry.user_id}
                </td>
                <td className="px-4 py-2.5">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-surface-tertiary text-text-secondary font-mono">
                    {entry.event_type}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-text-secondary">
                  {entry.provider}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                      entry.result === "success"
                        ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300"
                        : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300"
                    }`}
                  >
                    {entry.result}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-text-tertiary font-mono">
                  {entry.ip_address}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <PaginationBar
          page={page}
          totalPages={totalPages}
          total={total}
          loading={loading}
          onPageChange={onPageChange}
        />
      )}
    </>
  );
}

function HostActionTimeline({
  entries,
  total,
  page,
  loading,
  onPageChange,
}: {
  entries: AdminAuthEvent[];
  total: number;
  page: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <div className="rounded-lg border border-border bg-surface-secondary/30 p-4">
        <div className="mb-4 flex items-start gap-3">
          <div className="rounded-lg bg-[var(--accent)]/10 p-2 text-[var(--accent)]">
            <Sparkles size={16} />
          </div>
          <div>
            <div className="text-sm font-medium text-text">
              Host action timeline
            </div>
            <div className="text-xs text-text-secondary">
              Preview, apply, and publish events emitted by Wiii into the host
              surface.
            </div>
          </div>
        </div>

        {entries.length === 0 && !loading ? (
          <EmptyAuditState
            title="Chưa có host action nào"
            description="Khi Wiii tạo preview, apply thay đổi hoặc publish nội dung vào host surface, timeline này sẽ cho thấy ai làm gì và vào lúc nào."
          />
        ) : entries.length === 0 && loading ? (
          <LoadingAuditState label="Đang tải host actions..." />
        ) : (
          <ol className="space-y-4" aria-label="Host action timeline">
            {entries.map((entry) => (
              <HostActionTimelineItem key={entry.id} entry={entry} />
            ))}
          </ol>
        )}
      </div>

      {total > 0 && (
        <PaginationBar
          page={page}
          totalPages={totalPages}
          total={total}
          loading={loading}
          onPageChange={onPageChange}
        />
      )}
    </>
  );
}

function EmptyAuditState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-dashed border-border bg-surface/60 px-4 py-6 text-center">
      <p className="text-sm font-medium text-text">{title}</p>
      <p className="mt-2 text-xs leading-5 text-text-secondary">
        {description}
      </p>
    </div>
  );
}

function LoadingAuditState({ label }: { label: string }) {
  return (
    <div
      aria-busy="true"
      className="mx-auto flex max-w-xl items-start justify-center gap-3 rounded-lg border border-border bg-surface/70 px-4 py-6 text-left"
    >
      <Loader2
        size={16}
        className="mt-0.5 shrink-0 animate-spin text-[var(--accent)]"
      />
      <div>
        <p className="text-sm font-medium text-text">{label}</p>
        <p className="mt-1 text-xs leading-5 text-text-secondary">
          Wiii đang truy vấn nhật ký có phân trang. Nếu chưa có dữ liệu, bảng sẽ
          chuyển sang empty-state có giải thích thay vì chỉ hiện header trống.
        </p>
      </div>
    </div>
  );
}

function HostActionTimelineItem({ entry }: { entry: AdminAuthEvent }) {
  const metadata = (entry.metadata ?? {}) as Record<string, unknown>;
  const previewKind =
    typeof metadata.preview_kind === "string" ? metadata.preview_kind : "";
  const summary =
    typeof metadata.summary === "string" && metadata.summary.trim().length > 0
      ? metadata.summary
      : entry.reason || entry.event_type;
  const actionLabel =
    typeof metadata.action === "string" && metadata.action.trim().length > 0
      ? metadata.action
      : entry.event_type;
  const targetId =
    typeof metadata.target_id === "string" &&
    metadata.target_id.trim().length > 0
      ? metadata.target_id
      : "—";
  const surface =
    typeof metadata.surface === "string" && metadata.surface.trim().length > 0
      ? metadata.surface
      : "—";
  const requestId =
    typeof metadata.request_id === "string" &&
    metadata.request_id.trim().length > 0
      ? metadata.request_id
      : "—";
  const changedFields = Array.isArray(metadata.changed_fields)
    ? metadata.changed_fields.filter(
        (field): field is string =>
          typeof field === "string" && field.trim().length > 0,
      )
    : [];

  return (
    <li className="relative pl-6">
      <span
        aria-hidden="true"
        className="absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full bg-[var(--accent)] shadow-[0_0_0_4px_rgba(59,130,246,0.12)]"
      />
      <span
        aria-hidden="true"
        className="absolute left-[5px] top-4 bottom-[-16px] w-px bg-border"
      />
      <div className="rounded-xl border border-border bg-surface px-4 py-3 shadow-sm">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[var(--accent)]/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">
            {formatHostActionEvent(entry.event_type)}
          </span>
          <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] font-mono text-text-secondary">
            {entry.provider}
          </span>
          {previewKind.length > 0 && (
            <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] font-mono text-text-secondary">
              {previewKind}
            </span>
          )}
          <span className="ml-auto text-xs text-text-tertiary">
            {entry.created_at
              ? new Date(entry.created_at).toLocaleString("vi-VN")
              : "—"}
          </span>
        </div>

        <div className="space-y-3">
          <div className="text-sm font-medium text-text">{summary}</div>

          <div className="grid gap-2 text-xs text-text-secondary sm:grid-cols-2">
            <MetaItem label="Action" value={actionLabel} />
            <MetaItem label="User" value={entry.user_id} />
            <MetaItem label="Target" value={targetId} mono />
            <MetaItem label="Surface" value={surface} />
            <MetaItem label="Request" value={requestId} mono />
            <MetaItem label="Org" value={entry.organization_id || "—"} mono />
          </div>

          {changedFields.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wider text-text-tertiary">
                Changed fields
              </div>
              <div className="flex flex-wrap gap-1.5">
                {changedFields.map((field) => (
                  <span
                    key={field}
                    className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-text"
                  >
                    {field}
                  </span>
                ))}
              </div>
            </div>
          )}

          {typeof metadata.question_count === "number" && (
            <div className="text-xs text-text-secondary">
              Question count:{" "}
              <span className="font-medium text-text">
                {String(metadata.question_count)}
              </span>
            </div>
          )}
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

function formatHostActionEvent(eventType: string): string {
  if (eventType === "host_action.preview_created") return "preview";
  if (eventType === "host_action.apply_confirmed") return "apply";
  if (eventType === "host_action.publish_confirmed") return "publish";
  return eventType.replace(/^host_action\./, "");
}

function PaginationBar({
  page,
  totalPages,
  total,
  loading,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const startIdx = page * PAGE_SIZE + 1;
  const endIdx = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="flex items-center justify-between text-xs text-text-secondary">
      <span>
        {startIdx}-{endIdx} of {total}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page === 0 || loading}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded border border-border hover:bg-surface-tertiary disabled:opacity-30 transition-colors"
        >
          <ChevronLeft size={12} />
          Prev
        </button>
        <span>
          {page + 1} / {totalPages || 1}
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages - 1 || loading || totalPages === 0}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded border border-border hover:bg-surface-tertiary disabled:opacity-30 transition-colors"
        >
          Next
          <ChevronRight size={12} />
        </button>
      </div>
    </div>
  );
}
