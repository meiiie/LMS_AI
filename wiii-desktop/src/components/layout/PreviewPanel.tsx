/**
 * PreviewPanel — slide-in side panel showing expanded preview content.
 * Sprint 166: Follows SourcesPanel pattern.
 * Fixed right panel, Escape to close, expanded preview with full data.
 */
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { X, Eye, ExternalLink } from "lucide-react";
import {
  submitHostActionAudit,
  type HostActionAuditEventType,
} from "@/api/host-actions";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";
import {
  useHostContextStore,
  type ActionResult,
} from "@/stores/host-context-store";
import { useToastStore } from "@/stores/toast-store";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { LazyImage } from "@/components/chat/PreviewCard";
import { slideInRight } from "@/lib/animations";
import {
  formatSourcePages,
  normalizeSourceReferences,
  sourceReferenceLabel,
  type PreviewSourceReference,
} from "@/lib/source-references";
import type { PreviewItemData } from "@/api/types";

const HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE =
  "LMS đang giữ quyền áp dụng trong hộp thoại preview. Hãy xác nhận trực tiếp trong LMS để Wiii không tự thay đổi dữ liệu.";

/** Shared content for both inline and overlay modes */
function PreviewPanelContent({
  previews,
  selected,
  selectedPreviewId,
  closePreview,
}: {
  previews: PreviewItemData[];
  selected: PreviewItemData | null;
  selectedPreviewId: string | null;
  closePreview: () => void;
}) {
  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0 preview-panel-shell__header">
        <div className="flex items-center gap-2">
          <Eye size={16} className="text-[var(--accent)]" />
          <span className="font-medium text-sm text-text">Xem trước</span>
          <span className="text-xs text-text-tertiary">
            ({previews.length})
          </span>
        </div>
        <button
          onClick={closePreview}
          className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-secondary transition-colors"
          aria-label="Đóng panel xem trước"
        >
          <X size={16} />
        </button>
      </div>

      {/* Selected preview detail */}
      {selected ? (
        <ExpandedPreview item={selected} />
      ) : (
        <div className="flex flex-col items-center justify-center flex-1 text-text-tertiary text-sm p-4">
          <Eye size={32} className="mb-2 opacity-40" />
          <p>Chọn một thẻ xem trước để xem chi tiết.</p>
        </div>
      )}

      {/* Preview list */}
      {previews.length > 1 && (
        <div className="border-t border-border p-2 max-h-[35vh] overflow-y-auto">
          <div className="text-xs text-text-tertiary px-2 py-1 mb-1">
            Tất cả xem trước
          </div>
          <div className="space-y-1">
            {previews.map((p) => (
              <PreviewListItem
                key={p.preview_id}
                item={p}
                isSelected={selectedPreviewId === p.preview_id}
                onSelect={() => useUIStore.getState().openPreview(p.preview_id)}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export function PreviewPanel({ inline }: { inline?: boolean }) {
  const { previewPanelOpen, selectedPreviewId, closePreview } = useUIStore();
  const panelRef = useRef<HTMLDivElement>(null);

  // Get all previews from the last assistant message
  const previews = useChatStore((s) => {
    const conv = s.activeConversation();
    if (!conv) return [];
    for (let i = conv.messages.length - 1; i >= 0; i--) {
      const msg = conv.messages[i];
      if (msg.role === "assistant" && msg.previews && msg.previews.length > 0) {
        return msg.previews;
      }
    }
    // Also check streaming previews
    if (s.streamingPreviews.length > 0) return s.streamingPreviews;
    return [];
  });

  // Close on Escape
  useEffect(() => {
    if (!previewPanelOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePreview();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [previewPanelOpen, closePreview]);

  const selected = selectedPreviewId
    ? (previews.find((p) => p.preview_id === selectedPreviewId) ?? null)
    : null;

  if (!previewPanelOpen) return null;

  const contentProps = { previews, selected, selectedPreviewId, closePreview };

  // Sprint 233: Inline mode — render directly inside resizable split panel
  if (inline) {
    return (
      <div
        ref={panelRef}
        className="h-full flex flex-col preview-panel-shell"
        role="complementary"
        aria-label="Xem trước nội dung"
      >
        <PreviewPanelContent {...contentProps} />
      </div>
    );
  }

  // Mobile / overlay fallback — original fixed positioning
  return (
    <AnimatePresence>
      {previewPanelOpen && (
        <motion.div
          ref={panelRef}
          variants={slideInRight}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed right-0 top-11 bottom-0 w-[420px] max-w-[90vw] border-l border-border shadow-xl z-40 flex flex-col preview-panel-shell"
          role="complementary"
          aria-label="Xem trước nội dung"
        >
          <PreviewPanelContent {...contentProps} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Expanded view of the selected preview */
function ExpandedPreview({ item }: { item: PreviewItemData }) {
  const isProduct = item.preview_type === "product";
  const isHostAction = item.preview_type === "host_action";
  const metadataEntries = isHostAction
    ? buildHostActionMetadataEntries(item)
    : [];
  const sourceReferences = isHostAction
    ? normalizeSourceReferences(
        item.metadata?.source_references ?? item.metadata?.sourceReferences,
      )
    : [];
  const hostContext = useHostContextStore((s) => s.currentContext);
  const hostCapabilities = useHostContextStore((s) => s.capabilities);
  const [operatorState, setOperatorState] = useState<{
    status: "idle" | "running" | "success" | "error";
    message?: string;
  }>({ status: "idle" });
  const applyConfig = isHostAction ? resolveHostActionApplyConfig(item) : null;
  const previewKind =
    typeof item.metadata?.preview_kind === "string"
      ? item.metadata.preview_kind
      : "";
  const previewToken =
    typeof item.metadata?.preview_token === "string"
      ? item.metadata.preview_token
      : "";
  const approvalToken =
    typeof item.metadata?.approval_token === "string"
      ? item.metadata.approval_token
      : "";
  const applyNeedsHostApproval = Boolean(
    applyConfig &&
      !approvalToken &&
      hostActionRequiresInput(
        applyConfig.action,
        "approval_token",
        hostCapabilities,
        hostContext,
      ),
  );
  const canExecuteApply = Boolean(
    isHostAction &&
      applyConfig &&
      previewToken &&
      hostContext?.host_type &&
      !applyNeedsHostApproval,
  );

  useEffect(() => {
    setOperatorState({ status: "idle" });
  }, [item.preview_id]);

  const handleApply = async () => {
    if (!applyConfig || !previewToken || operatorState.status === "running") {
      return;
    }

    const requestId = `req-preview-apply-${Math.random().toString(36).slice(2, 12)}`;
    setOperatorState({
      status: "running",
      message:
        previewKind === "facebook_post"
          ? "Wiii đang gửi bài đăng sang Facebook..."
          : "Wiii đang gửi xác nhận sang LMS...",
    });
    try {
      const facebookPostBody =
        previewKind === "facebook_post"
          ? asRecord(item.metadata?.facebook_post_body)
          : null;
      const applyParams: Record<string, string> = facebookPostBody
        ? Object.fromEntries(
            Object.entries(facebookPostBody)
              .filter(([, value]) => typeof value === "string")
              .map(([key, value]) => [key, String(value)]),
          )
        : {
            preview_token: previewToken,
          };
      if (approvalToken) {
        applyParams.approval_token = approvalToken;
      }
      if (previewKind === "facebook_post") {
        applyParams.provider_slug = "facebook";
        applyParams.preview_evidence_id =
          typeof item.metadata?.preview_evidence_id === "string"
            ? item.metadata.preview_evidence_id
            : previewToken;
        applyParams.preview_token = previewToken;
      }

      const result = await useHostContextStore
        .getState()
        .requestAction(applyConfig.action, applyParams, requestId);
      if (!result.success) {
        if (isHostPreviewApprovalRequired(result)) {
          setOperatorState({
            status: "idle",
            message: HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE,
          });
          useToastStore
            .getState()
            .addToast("info", HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE, 4500);
          return;
        }
        throw new Error(result.error || "Không thể áp dụng thay đổi này.");
      }

      const successMessage =
        typeof result.data?.summary === "string" &&
        result.data.summary.trim().length > 0
          ? result.data.summary.trim()
          : applyConfig.successLabel;
      setOperatorState({ status: "success", message: successMessage });
      useToastStore.getState().addToast("success", successMessage, 3500);

      const auditRequest = buildManualHostActionAuditRequest(
        item,
        applyConfig.action,
        requestId,
        result.data || {},
        hostContext,
        hostCapabilities,
      );
      if (auditRequest) {
        void submitHostActionAudit(auditRequest).catch((err) => {
          console.warn(
            "[PreviewPanel] host action audit failed:",
            err instanceof Error ? err.message : String(err),
          );
        });
      }
    } catch (error) {
      if (isHostPreviewApprovalRequired(error)) {
        setOperatorState({
          status: "idle",
          message: HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE,
        });
        useToastStore
          .getState()
          .addToast("info", HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE, 4500);
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "Không thể áp dụng thay đổi này.";
      setOperatorState({ status: "error", message });
      useToastStore.getState().addToast("error", message, 4500);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Large image */}
      {item.image_url && (
        <div className="rounded-lg overflow-hidden bg-surface-secondary">
          <LazyImage src={item.image_url} alt={item.title} />
        </div>
      )}

      {/* Title + type badge */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)]">
            {item.preview_type}
          </span>
          {item.citation_index != null && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[var(--source-badge)] text-[var(--source-text)]">
              [{item.citation_index}]
            </span>
          )}
          {isProduct && item.metadata?.platform != null && (
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-secondary text-text-tertiary uppercase tracking-wider">
              {String(item.metadata.platform)}
            </span>
          )}
        </div>
        <h3 className="text-base font-semibold text-text leading-snug">
          {item.title}
        </h3>
      </div>

      {/* Product-specific: prominent price */}
      {isProduct &&
        (item.metadata?.price != null ||
          item.metadata?.extracted_price != null) && (
          <div className="text-xl font-bold text-[var(--accent)]">
            {String(item.metadata.extracted_price || item.metadata.price)}
          </div>
        )}

      {/* Snippet / description */}
      {item.snippet && (
        <div className="text-sm font-serif text-text-secondary leading-relaxed">
          <MarkdownRenderer content={item.snippet} />
        </div>
      )}

      {isHostAction && (
        <div className="space-y-3 rounded-xl border border-border bg-surface-secondary/50 p-3">
          {metadataEntries.length > 0 && (
            <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
              {metadataEntries.map((entry) => (
                <div key={entry.label}>
                  <span className="block text-xs text-text-tertiary">
                    {entry.label}
                  </span>
                  <span className="font-medium text-text">{entry.value}</span>
                </div>
              ))}
            </div>
          )}
          {sourceReferences.length > 0 && (
            <HostActionSourceReferences references={sourceReferences} />
          )}
          {(item.metadata?.next_step as string | undefined) && (
            <div className="rounded-lg bg-[var(--accent)]/8 px-3 py-2 text-sm text-text">
              <span className="block text-xs uppercase tracking-wider text-[var(--accent)]">
                Bước tiếp theo
              </span>
              <span>{String(item.metadata?.next_step)}</span>
            </div>
          )}
          {(item.metadata?.preview_token as string | undefined) && (
            <div className="rounded-lg bg-surface px-3 py-2 text-xs text-text-secondary">
              Preview token:{" "}
              <span className="font-mono text-text">
                {String(item.metadata?.preview_token)}
              </span>
            </div>
          )}
          {applyConfig && (
            <div className="rounded-lg border border-border bg-surface px-3 py-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-text">
                    Xác nhận của giáo viên
                  </div>
                  <div className="text-xs text-text-secondary">
                    Wiii đã dựng preview để bạn xem kỹ trước. Nếu thấy ổn, bạn
                    có thể xác nhận áp dụng ngay tại đây.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleApply}
                  disabled={
                    !canExecuteApply ||
                    operatorState.status === "running" ||
                    operatorState.status === "success"
                  }
                  className={`min-h-[44px] rounded-lg px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 ${
                    canExecuteApply && operatorState.status !== "success"
                      ? "bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90"
                      : "cursor-not-allowed bg-surface-secondary text-text-tertiary"
                  }`}
                  aria-disabled={
                    !canExecuteApply ||
                    operatorState.status === "running" ||
                    operatorState.status === "success"
                  }
                >
                  {operatorState.status === "running"
                    ? "Đang áp dụng..."
                    : applyConfig.label}
                </button>
              </div>
              <div
                aria-live="polite"
                className="mt-2 text-xs text-text-secondary"
              >
                {!canExecuteApply && operatorState.status === "idle"
                  ? applyNeedsHostApproval
                    ? HOST_PREVIEW_APPROVAL_REQUIRED_MESSAGE
                    : "CTA này chỉ hoạt động khi Wiii đang được nhúng trong host sidebar có bridge xác nhận."
                  : operatorState.message}
              </div>
            </div>
          )}
          {renderHostActionPreviewDetails(item)}
        </div>
      )}

      {/* Product metadata grid */}
      {isProduct && item.metadata && (
        <div className="grid grid-cols-2 gap-2 text-sm">
          {item.metadata.seller != null && (
            <div>
              <span className="text-text-tertiary block text-xs">
                Người bán
              </span>
              <span className="text-text font-medium">
                {String(item.metadata.seller)}
              </span>
            </div>
          )}
          {item.metadata.rating != null && (
            <div>
              <span className="text-text-tertiary block text-xs">Đánh giá</span>
              <span className="text-text font-medium">
                {String(item.metadata.rating)} / 5 ★
              </span>
            </div>
          )}
          {item.metadata.sold_count != null && (
            <div>
              <span className="text-text-tertiary block text-xs">Đã bán</span>
              <span className="text-text font-medium">
                {String(item.metadata.sold_count)}
              </span>
            </div>
          )}
          {item.metadata.location != null &&
            String(item.metadata.location) !== "" && (
              <div>
                <span className="text-text-tertiary block text-xs">Vị trí</span>
                <span className="text-text font-medium">
                  {String(item.metadata.location)}
                </span>
              </div>
            )}
          {item.metadata.delivery != null &&
            String(item.metadata.delivery) !== "" && (
              <div className="col-span-2">
                <span className="text-text-tertiary block text-xs">
                  Giao hàng
                </span>
                <span className="text-text font-medium">
                  {String(item.metadata.delivery)}
                </span>
              </div>
            )}
        </div>
      )}

      {/* Non-product metadata (original generic display) */}
      {!isProduct && item.metadata && Object.keys(item.metadata).length > 0 && (
        <div className="space-y-1.5">
          {item.metadata.price != null && (
            <div className="text-sm">
              <span className="text-text-tertiary">Giá: </span>
              <span className="font-semibold text-[var(--accent)]">
                {String(item.metadata.price)}
              </span>
            </div>
          )}
          {item.metadata.rating != null && (
            <div className="text-sm">
              <span className="text-text-tertiary">Đánh giá: </span>
              <span className="text-text">
                {String(item.metadata.rating)} / 5
              </span>
            </div>
          )}
          {item.metadata.platform != null && (
            <div className="text-sm">
              <span className="text-text-tertiary">Nền tảng: </span>
              <span className="text-text">
                {String(item.metadata.platform)}
              </span>
            </div>
          )}
          {item.metadata.relevance_score != null && (
            <div className="text-sm">
              <span className="text-text-tertiary">Độ liên quan: </span>
              <span className="text-text">
                {(Number(item.metadata.relevance_score) * 100).toFixed(0)}%
              </span>
            </div>
          )}
          {item.metadata.page_number != null && (
            <div className="text-sm">
              <span className="text-text-tertiary">Trang: </span>
              <span className="text-text">
                {String(item.metadata.page_number)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* URL link — validate scheme to prevent javascript:/data: injection */}
      {item.url && /^https?:\/\//i.test(item.url) && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className={`inline-flex items-center gap-1.5 text-sm text-white
            ${isProduct ? "bg-[var(--accent)] hover:bg-[var(--accent)]/90 px-4 py-2 rounded-lg font-medium" : "text-[var(--accent)] hover:underline"}`}
        >
          <ExternalLink size={14} />
          {isProduct ? "Mở trên sàn" : "Mở liên kết gốc"}
        </a>
      )}
    </div>
  );
}

function buildHostActionMetadataEntries(
  item: PreviewItemData,
): Array<{ label: string; value: string }> {
  const entries: Array<{ label: string; value: string }> = [];
  const push = (label: string, value: unknown) => {
    const normalized = String(value ?? "").trim();
    if (!normalized) return;
    entries.push({ label, value: normalized });
  };

  push("Loại preview", item.metadata?.preview_kind);
  push("Action", item.metadata?.action);
  push("Target", item.metadata?.target_label);
  push("Lesson", item.metadata?.lesson_id);
  push("Quiz", item.metadata?.quiz_id);
  push("Course", item.metadata?.course_id);
  push("Workflow", item.metadata?.workflow_stage);

  const changedFields = Array.isArray(item.metadata?.changed_fields)
    ? item.metadata?.changed_fields.filter(
        (field): field is string => typeof field === "string",
      )
    : [];
  if (changedFields.length > 0) {
    push("Trường sẽ đổi", changedFields.join(", "));
  }

  if (typeof item.metadata?.question_count === "number") {
    push("Số câu hỏi", item.metadata?.question_count);
  }

  return entries;
}

function renderHostActionPreviewDetails(item: PreviewItemData) {
  const lessonBefore = asRecord(item.metadata?.lesson_before);
  const lessonAfter = asRecord(item.metadata?.lesson_after);
  const blockDiff = asRecord(item.metadata?.block_diff);
  const quizPlan = asRecord(item.metadata?.quiz_plan);
  const publishPlan = asRecord(item.metadata?.publish_plan);

  if (lessonBefore && lessonAfter) {
    return (
      <div className="space-y-3">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Trước / sau
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <HostActionSnapshotCard title="Hiện tại" snapshot={lessonBefore} />
          <HostActionSnapshotCard
            title="Đề xuất"
            snapshot={lessonAfter}
            emphasize
          />
        </div>
        {blockDiff && <HostActionBlockDiffCard blockDiff={blockDiff} />}
      </div>
    );
  }

  if (quizPlan) {
    return (
      <div className="space-y-2 rounded-lg bg-surface px-3 py-3">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Kế hoạch quiz
        </div>
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <MetaInline label="Mode" value={String(quizPlan.mode || "draft")} />
          <MetaInline
            label="Số câu hỏi"
            value={String(quizPlan.question_count || 0)}
          />
          <MetaInline
            label="Thời lượng"
            value={`${String(quizPlan.time_limit_minutes || 0)} phút`}
          />
          <MetaInline
            label="Số lần làm"
            value={String(quizPlan.max_attempts || 1)}
          />
          <MetaInline
            label="Điểm đạt"
            value={String(quizPlan.passing_score || 0)}
          />
        </div>
        {typeof quizPlan.title === "string" &&
          quizPlan.title.trim().length > 0 && (
            <div className="text-sm text-text">
              <span className="text-text-tertiary">Tiêu đề: </span>
              <span className="font-medium">{quizPlan.title}</span>
            </div>
          )}
        {typeof quizPlan.description === "string" &&
          quizPlan.description.trim().length > 0 && (
            <div className="text-sm text-text-secondary leading-relaxed">
              {quizPlan.description}
            </div>
          )}
      </div>
    );
  }

  if (publishPlan) {
    return (
      <div className="space-y-2 rounded-lg bg-surface px-3 py-3">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Kế hoạch publish
        </div>
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <MetaInline label="Quiz" value={String(publishPlan.quiz_id || "—")} />
          <MetaInline
            label="Lesson"
            value={String(publishPlan.lesson_id || "—")}
          />
          <MetaInline
            label="Status"
            value={String(publishPlan.status || "ready")}
          />
        </div>
        {typeof publishPlan.title === "string" &&
          publishPlan.title.trim().length > 0 && (
            <div className="text-sm text-text">
              <span className="text-text-tertiary">Tiêu đề: </span>
              <span className="font-medium">{publishPlan.title}</span>
            </div>
          )}
      </div>
    );
  }

  if (item.metadata?.preview_kind === "facebook_post") {
    return (
      <div className="space-y-3 rounded-lg bg-surface px-3 py-3">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Facebook post
        </div>
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <MetaInline
            label="Page"
            value={String(item.metadata?.page_label || item.metadata?.page_id || "-")}
          />
          <MetaInline
            label="Ảnh"
            value={item.metadata?.image_present ? "Có ảnh" : "Không có ảnh"}
          />
        </div>
        {typeof item.metadata?.message === "string" && (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-text">
            {item.metadata.message}
          </p>
        )}
      </div>
    );
  }

  return null;
}

function HostActionSourceReferences({
  references,
}: {
  references: PreviewSourceReference[];
}) {
  return (
    <section
      aria-label="Nguồn tài liệu"
      className="rounded-lg border border-border bg-surface px-3 py-3"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Nguồn tài liệu
        </div>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-text-secondary">
          {references.length}
        </span>
      </div>
      <div className="space-y-2">
        {references.map((ref, index) => (
          <div
            key={`${ref.kind || "source"}-${ref.chapter_index ?? "x"}-${ref.lesson_index ?? "x"}-${index}`}
            className="rounded-md bg-surface-secondary px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-text">
                {sourceReferenceLabel(ref)}
              </span>
              <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] text-text-secondary">
                Trang {formatSourcePages(ref.source_pages)}
              </span>
              {ref.kind && (
                <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] uppercase tracking-wider text-text-tertiary">
                  {ref.kind}
                </span>
              )}
            </div>
            {ref.excerpt && (
              <div className="mt-1 text-xs leading-relaxed text-text-secondary">
                {ref.excerpt}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function HostActionBlockDiffCard({
  blockDiff,
}: {
  blockDiff: Record<string, unknown>;
}) {
  const items = Array.isArray(blockDiff.items)
    ? blockDiff.items.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === "object" && !Array.isArray(item)),
      )
    : [];

  return (
    <section className="rounded-lg border border-border bg-surface px-3 py-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
          Diff theo block
        </div>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-text-secondary">
          {String(blockDiff.changed ?? 0)} đổi
        </span>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-text-secondary">
          {String(blockDiff.added ?? 0)} thêm
        </span>
        <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-text-secondary">
          {String(blockDiff.removed ?? 0)} xóa
        </span>
      </div>
      {items.length > 0 ? (
        <div className="space-y-2">
          {items.map((item, index) => (
            <HostActionBlockDiffRow
              key={`${String(item.status || "diff")}-${index}`}
              item={item}
            />
          ))}
        </div>
      ) : (
        <div className="text-sm text-text-secondary">
          Không có thay đổi theo block để hiển thị.
        </div>
      )}
    </section>
  );
}

function HostActionBlockDiffRow({ item }: { item: Record<string, unknown> }) {
  const status = String(item.status || "changed");
  const before = asRecord(item.before);
  const after = asRecord(item.after);
  const toneClass =
    status === "added"
      ? "border-emerald-200/70 bg-emerald-50/50"
      : status === "removed"
        ? "border-rose-200/70 bg-rose-50/50"
        : status === "changed"
          ? "border-amber-200/70 bg-amber-50/50"
          : "border-border bg-surface-secondary/60";

  return (
    <div className={`rounded-lg border px-3 py-3 ${toneClass}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-text">
          {String(
            after?.label ||
              before?.label ||
              `Block ${Number(item.index || 0) + 1}`,
          )}
        </div>
        <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] uppercase tracking-wider text-text-secondary">
          {status}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {before && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wider text-text-tertiary">
              Trước
            </div>
            <div className="rounded-md bg-surface px-3 py-2 text-sm text-text-secondary leading-relaxed">
              {String(before.excerpt || "—")}
            </div>
          </div>
        )}
        {after && (
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wider text-text-tertiary">
              Sau
            </div>
            <div className="rounded-md bg-surface px-3 py-2 text-sm text-text-secondary leading-relaxed">
              {String(after.excerpt || "—")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function HostActionSnapshotCard({
  title,
  snapshot,
  emphasize,
}: {
  title: string;
  snapshot: Record<string, unknown>;
  emphasize?: boolean;
}) {
  return (
    <section
      aria-label={title}
      className={`rounded-lg border px-3 py-3 ${
        emphasize
          ? "border-[var(--accent)]/30 bg-[var(--accent)]/5"
          : "border-border bg-surface"
      }`}
    >
      <div className="mb-2 text-[11px] uppercase tracking-wider text-text-tertiary">
        {title}
      </div>
      <div className="space-y-2">
        {typeof snapshot.title === "string" &&
          snapshot.title.trim().length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                Tiêu đề
              </div>
              <div className="text-sm font-medium text-text">
                {snapshot.title}
              </div>
            </div>
          )}
        {typeof snapshot.description === "string" &&
          snapshot.description.trim().length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                Mô tả
              </div>
              <div className="text-sm text-text-secondary leading-relaxed">
                {snapshot.description}
              </div>
            </div>
          )}
        {typeof snapshot.content_excerpt === "string" &&
          snapshot.content_excerpt.trim().length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                Nội dung
              </div>
              <div className="rounded-md bg-surface-secondary px-3 py-2 text-sm text-text-secondary leading-relaxed">
                {snapshot.content_excerpt}
              </div>
            </div>
          )}
        {Array.isArray(snapshot.blocks) && snapshot.blocks.length > 0 && (
          <div>
            <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
              Blocks
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {snapshot.blocks
                .filter((block): block is Record<string, unknown> =>
                  Boolean(
                    block && typeof block === "object" && !Array.isArray(block),
                  ),
                )
                .slice(0, 6)
                .map((block, index) => (
                  <span
                    key={`${String(block.id || index)}`}
                    className="rounded-full bg-surface-secondary px-2 py-1 text-[11px] text-text-secondary"
                  >
                    {String(block.label || block.type || `Block ${index + 1}`)}
                  </span>
                ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function MetaInline({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="block text-[11px] uppercase tracking-wider text-text-tertiary">
        {label}
      </span>
      <span className="text-text">{value}</span>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function resolveHostActionApplyConfig(item: PreviewItemData): {
  action: string;
  label: string;
  successLabel: string;
} | null {
  const explicitAction =
    typeof item.metadata?.apply_action === "string" &&
    item.metadata.apply_action.trim().length > 0
      ? item.metadata.apply_action.trim()
      : "";
  const previewKind =
    typeof item.metadata?.preview_kind === "string"
      ? item.metadata.preview_kind
      : "";

  const action =
    explicitAction ||
    (previewKind === "lesson_patch"
      ? "authoring.apply_lesson_patch"
      : previewKind === "quiz_commit"
        ? "assessment.apply_quiz_commit"
        : previewKind === "quiz_publish"
          ? "publish.apply_quiz"
          : previewKind === "facebook_post"
            ? "wiii_connect.facebook_post.apply"
            : "");
  if (!action) {
    return null;
  }

  if (action === "authoring.apply_lesson_patch") {
    return {
      action,
      label: "Xác nhận áp dụng vào bài học",
      successLabel: "Đã áp dụng cập nhật bài học vào LMS.",
    };
  }
  if (action === "assessment.apply_quiz_commit") {
    return {
      action,
      label: "Xác nhận commit quiz",
      successLabel: "Đã commit quiz vào LMS.",
    };
  }
  if (action === "publish.apply_quiz") {
    return {
      action,
      label: "Xác nhận publish quiz",
      successLabel: "Đã publish quiz trên LMS.",
    };
  }
  if (action === "wiii_connect.facebook_post.apply") {
    return {
      action,
      label: "Đăng lên Facebook",
      successLabel: "Đã đăng bài lên Facebook.",
    };
  }
  return {
    action,
    label: "Xác nhận áp dụng",
    successLabel: "Đã áp dụng thay đổi vào host.",
  };
}

function hostActionRequiresInput(
  action: string,
  property: string,
  hostCapabilities: ReturnType<
    typeof useHostContextStore.getState
  >["capabilities"],
  hostContext: ReturnType<typeof useHostContextStore.getState>["currentContext"],
): boolean {
  const capabilityTools = hostCapabilities?.tools ?? [];
  const contextActions = hostContext?.available_actions ?? [];
  return [...capabilityTools, ...contextActions].some((tool) => {
    if (!tool || typeof tool !== "object") {
      return false;
    }
    const candidate = tool as {
      action?: unknown;
      input_schema?: unknown;
      name?: unknown;
    };
    const toolName =
      typeof candidate.name === "string"
        ? candidate.name
        : typeof candidate.action === "string"
          ? candidate.action
          : "";
    return (
      toolName === action &&
      schemaRequiresProperty(candidate.input_schema, property)
    );
  });
}

function schemaRequiresProperty(schema: unknown, property: string): boolean {
  if (!schema || typeof schema !== "object") {
    return false;
  }
  const required = (schema as { required?: unknown }).required;
  return (
    Array.isArray(required) &&
    required.some((field) => field === property)
  );
}

function isHostPreviewApprovalRequired(result: unknown): boolean {
  if (result instanceof Error) {
    return result.message.includes("host_preview_approval_required");
  }
  if (!result || typeof result !== "object") {
    return false;
  }

  const actionResult = result as ActionResult;
  const error = typeof actionResult.error === "string" ? actionResult.error : "";
  const code =
    typeof actionResult.data?.code === "string"
      ? actionResult.data.code
      : typeof actionResult.data?.error_code === "string"
        ? actionResult.data.error_code
        : "";
  return [error, code].some((value) =>
    value.includes("host_preview_approval_required"),
  );
}

function mapManualHostActionAuditEvent(
  action: string,
): HostActionAuditEventType | null {
  switch (action) {
    case "authoring.apply_lesson_patch":
    case "assessment.apply_quiz_commit":
      return "apply_confirmed";
    case "publish.apply_quiz":
      return "publish_confirmed";
    default:
      return null;
  }
}

function buildManualHostActionAuditRequest(
  item: PreviewItemData,
  action: string,
  requestId: string,
  data: Record<string, unknown>,
  hostContext: ReturnType<
    typeof useHostContextStore.getState
  >["currentContext"],
  hostCapabilities: ReturnType<
    typeof useHostContextStore.getState
  >["capabilities"],
) {
  const eventType = mapManualHostActionAuditEvent(action);
  if (!eventType) {
    return null;
  }
  const sourceReferences = normalizeSourceReferences(
    item.metadata?.source_references ?? item.metadata?.sourceReferences,
  );

  return {
    event_type: eventType,
    action,
    request_id: requestId,
    summary: typeof data.summary === "string" ? data.summary : item.snippet,
    host_type: hostContext?.host_type,
    host_name: hostCapabilities?.host_name || hostContext?.host_name,
    page_type: hostContext?.page?.type,
    page_title: hostContext?.page?.title,
    user_role: hostContext?.user_role,
    workflow_stage: hostContext?.workflow_stage,
    preview_kind:
      typeof item.metadata?.preview_kind === "string"
        ? item.metadata.preview_kind
        : undefined,
    preview_token:
      typeof item.metadata?.preview_token === "string"
        ? item.metadata.preview_token
        : undefined,
    target_type:
      typeof item.metadata?.lesson_id === "string"
        ? "lesson"
        : typeof item.metadata?.quiz_id === "string"
          ? "quiz"
          : undefined,
    target_id:
      typeof item.metadata?.lesson_id === "string"
        ? item.metadata.lesson_id
        : typeof item.metadata?.quiz_id === "string"
          ? item.metadata.quiz_id
          : undefined,
    surface: "preview_panel",
    metadata: {
      request_id: requestId,
      target_label:
        typeof item.metadata?.target_label === "string"
          ? item.metadata.target_label
          : undefined,
      course_id:
        typeof item.metadata?.course_id === "string"
          ? item.metadata.course_id
          : undefined,
      lesson_id:
        typeof item.metadata?.lesson_id === "string"
          ? item.metadata.lesson_id
          : undefined,
      quiz_id:
        typeof item.metadata?.quiz_id === "string"
          ? item.metadata.quiz_id
          : undefined,
      changed_fields: Array.isArray(item.metadata?.changed_fields)
        ? item.metadata.changed_fields
        : undefined,
      question_count:
        typeof item.metadata?.question_count === "number"
          ? item.metadata.question_count
          : undefined,
      source_references:
        sourceReferences.length > 0 ? sourceReferences : undefined,
    },
  };
}

/** Compact list item for the preview list at the bottom */
function PreviewListItem({
  item,
  isSelected,
  onSelect,
}: {
  item: PreviewItemData;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
        isSelected
          ? "bg-[var(--accent)]/10 border border-[var(--accent)]/30"
          : "hover:bg-surface-tertiary border border-transparent"
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="text-[10px] uppercase tracking-wider font-semibold px-1 py-0.5 rounded bg-surface-secondary text-text-tertiary shrink-0 mt-0.5">
          {item.preview_type}
        </span>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-text truncate">{item.title}</div>
          {item.snippet && !isSelected && (
            <div className="text-xs text-text-secondary mt-0.5 line-clamp-1">
              {item.snippet.slice(0, 100)}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
