import { useEffect } from "react";
import {
  Activity,
  BookOpen,
  CheckCircle,
  Clock,
  FileText,
  Sparkles,
  Users,
} from "lucide-react";
import { useOrgAdminStore } from "@/stores/org-admin-store";

export function OrgManagerActivity({ orgId }: { orgId: string }) {
  const {
    orgDetail,
    members,
    documents,
    documentsLoading,
    hostActionEvents,
    hostActionEventsTotal,
    hostActionLoading,
    fetchDocuments,
    fetchHostActionEvents,
  } = useOrgAdminStore();

  useEffect(() => {
    void fetchDocuments(orgId);
    void fetchHostActionEvents(orgId, 0);
  }, [orgId, fetchDocuments, fetchHostActionEvents]);

  const readyDocuments = documents.filter(
    (doc) => doc.status === "ready",
  ).length;
  const processingDocuments = documents.filter((doc) =>
    ["uploading", "processing"].includes(doc.status),
  ).length;
  const failedDocuments = documents.filter(
    (doc) => doc.status === "failed",
  ).length;
  const adminMembers = members.filter((member) =>
    ["admin", "owner", "org_admin"].includes(member.role),
  ).length;
  const recentMembers = members
    .slice()
    .sort((a, b) =>
      String(b.joined_at || "").localeCompare(String(a.joined_at || "")),
    )
    .slice(0, 5);
  const recentDocuments = documents.slice(0, 5);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border bg-surface-secondary p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-[var(--accent)]/10 p-2 text-[var(--accent)]">
            <Activity size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-text">
              Nhịp hoạt động tổ chức
            </h3>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-text-secondary">
              Đây là bảng kiểm nhanh cho quản trị viên tổ chức: thành viên có ổn
              không, tri thức đã sẵn sàng chưa, và Wiii đã ghi nhận host action
              nào gần đây.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <ActivityStat
          icon={<Users size={18} />}
          label="Thành viên"
          value={members.length}
          detail={`${adminMembers} quản trị viên`}
        />
        <ActivityStat
          icon={<BookOpen size={18} />}
          label="Tài liệu sẵn sàng"
          value={readyDocuments}
          detail={
            documentsLoading
              ? "Đang kiểm tra kho tri thức"
              : `${documents.length} tài liệu tổng`
          }
        />
        <ActivityStat
          icon={<Clock size={18} />}
          label="Đang xử lý"
          value={processingDocuments}
          detail={
            failedDocuments > 0
              ? `${failedDocuments} tài liệu lỗi`
              : "Không có lỗi parsing"
          }
        />
        <ActivityStat
          icon={<Sparkles size={18} />}
          label="Host actions"
          value={hostActionEventsTotal}
          detail={
            hostActionLoading ? "Đang tải timeline" : "Preview, apply, publish"
          }
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <ActivityCard
          title="Thành viên gần đây"
          description="Theo dõi ai vừa tham gia và quyền của họ."
        >
          {recentMembers.length > 0 ? (
            <div className="space-y-2">
              {recentMembers.map((member) => (
                <div
                  key={member.user_id}
                  className="flex items-center justify-between gap-3 rounded-lg bg-surface px-3 py-2 text-xs"
                >
                  <span className="truncate font-mono text-text">
                    {member.user_id}
                  </span>
                  <span className="shrink-0 rounded-full bg-surface-tertiary px-2 py-0.5 text-text-secondary">
                    {member.role}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <QuietEmpty text="Chưa có thành viên nào được tải. Kiểm tra tab Thành viên để thêm người dùng." />
          )}
        </ActivityCard>

        <ActivityCard
          title="Tình trạng tri thức"
          description="Kiểm tra nhanh các tài liệu đang nuôi RAG của tổ chức."
        >
          {documentsLoading ? (
            <QuietEmpty text="Wiii đang đọc danh sách tài liệu để cập nhật trạng thái tri thức." />
          ) : recentDocuments.length > 0 ? (
            <div className="space-y-2">
              {recentDocuments.map((doc) => (
                <div
                  key={doc.document_id}
                  className="rounded-lg bg-surface px-3 py-2 text-xs"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-text">{doc.filename}</span>
                    <span className="shrink-0 rounded-full bg-surface-tertiary px-2 py-0.5 text-text-secondary">
                      {doc.status}
                    </span>
                  </div>
                  <div className="mt-1 flex gap-3 text-[11px] text-text-tertiary">
                    <span>{doc.page_count ?? 0} trang</span>
                    <span>{doc.chunk_count ?? 0} phân đoạn</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <QuietEmpty text="Chưa có tài liệu. Mở tab Tri thức để upload PDF và kích hoạt RAG theo tổ chức." />
          )}
        </ActivityCard>

        <ActivityCard
          title="Host action gần đây"
          description="Các thay đổi Wiii đề xuất hoặc thực hiện trong host surface."
        >
          {hostActionLoading ? (
            <QuietEmpty text="Wiii đang tải timeline host action có phân trang." />
          ) : hostActionEvents.length > 0 ? (
            <div className="space-y-2">
              {hostActionEvents.slice(0, 4).map((event) => (
                <div
                  key={event.id}
                  className="rounded-lg bg-surface px-3 py-2 text-xs"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-text">
                      {event.event_type}
                    </span>
                    <span className="shrink-0 text-[11px] text-text-tertiary">
                      {event.created_at
                        ? new Date(event.created_at).toLocaleString("vi-VN")
                        : "—"}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] text-text-secondary">
                    {event.reason ||
                      "Sự kiện đã được ghi lại để truy vết thao tác host."}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <QuietEmpty text="Chưa có host action. Khi Wiii preview/apply/publish, các sự kiện sẽ hiện ở đây và tab Host actions." />
          )}
        </ActivityCard>
      </div>

      <div className="rounded-2xl border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold text-text">
          Gợi ý vận hành tiếp theo
        </h3>
        <div className="mt-3 grid gap-3 text-xs text-text-secondary md:grid-cols-3">
          <NextStep
            icon={<Users size={14} />}
            text="Kiểm tra vai trò thành viên trước khi bật quyền nhạy cảm."
          />
          <NextStep
            icon={<FileText size={14} />}
            text="Upload tài liệu chuẩn vào Tri thức trước khi test RAG dài."
          />
          <NextStep
            icon={<CheckCircle size={14} />}
            text={`Trạng thái tổ chức: ${orgDetail?.is_active ? "đang hoạt động" : "cần kiểm tra"}.`}
          />
        </div>
      </div>
    </div>
  );
}

function ActivityStat({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-secondary p-4">
      <div className="flex items-center gap-2 text-text-secondary">
        <span className="rounded-lg bg-[var(--accent)]/10 p-2 text-[var(--accent)]">
          {icon}
        </span>
        <span className="text-xs">{label}</span>
      </div>
      <div className="mt-3 text-2xl font-bold text-text">{value}</div>
      <p className="mt-1 text-xs text-text-tertiary">{detail}</p>
    </div>
  );
}

function ActivityCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface-secondary p-4">
      <h3 className="text-sm font-semibold text-text">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-text-secondary">
        {description}
      </p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function QuietEmpty({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface/70 px-3 py-4 text-center text-xs leading-5 text-text-tertiary">
      {text}
    </div>
  );
}

function NextStep({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-surface-secondary px-3 py-2">
      <span className="mt-0.5 shrink-0 text-[var(--accent)]">{icon}</span>
      <span>{text}</span>
    </div>
  );
}
