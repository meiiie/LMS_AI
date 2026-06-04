import { Eye, FilePenLine, ClipboardCheck, Rocket, Send } from "lucide-react";
import type { PreviewItemData } from "@/api/types";

interface Props {
  item: PreviewItemData;
  onClick?: () => void;
}

function resolveIcon(kind?: string) {
  switch (kind) {
    case "lesson_patch":
      return FilePenLine;
    case "quiz_commit":
      return ClipboardCheck;
    case "quiz_publish":
      return Rocket;
    case "facebook_post":
      return Send;
    default:
      return Eye;
  }
}

function resolveBadge(kind?: string) {
  switch (kind) {
    case "lesson_patch":
      return "lesson patch";
    case "quiz_commit":
      return "quiz commit";
    case "quiz_publish":
      return "quiz publish";
    case "facebook_post":
      return "facebook";
    default:
      return "preview";
  }
}

export function HostActionPreviewCard({ item, onClick }: Props) {
  const previewKind = (item.metadata?.preview_kind as string | undefined) ?? "";
  const Icon = resolveIcon(previewKind);
  const badge = resolveBadge(previewKind);
  const targetLabel =
    (item.metadata?.target_label as string | undefined) ??
    (item.metadata?.lesson_title as string | undefined) ??
    (item.metadata?.quiz_title as string | undefined) ??
    "";
  const confirmation = item.metadata?.requires_confirmation === true;

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-3 rounded-lg border border-[var(--border,#e5e5e0)]
        bg-[var(--surface,#ffffff)] p-3 text-left transition-colors w-full
        hover:bg-[var(--surface-hover,#fafaf5)]
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      aria-label={`Preview thao tác host: ${item.title}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[var(--accent,#c2662d)]/10 text-[var(--accent,#c2662d)]">
            <Icon size={18} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-[var(--accent,#c2662d)]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--accent,#c2662d)]">
                {badge}
              </span>
              {confirmation && (
                <span className="rounded bg-[var(--surface-secondary,#f5f5f0)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[var(--text-tertiary,#999)]">
                  confirm
                </span>
              )}
            </div>
            <h4 className="mt-1 text-sm font-medium text-[var(--text-primary,#1a1a1a)] line-clamp-2">
              {item.title}
            </h4>
          </div>
        </div>
      </div>

      {item.snippet && (
        <p className="text-xs leading-relaxed text-[var(--text-secondary,#6b6b6b)] line-clamp-3">
          {item.snippet}
        </p>
      )}

      <div className="flex flex-wrap gap-2 text-[11px] text-[var(--text-tertiary,#999)]">
        {targetLabel && (
          <span className="rounded bg-[var(--surface-secondary,#f5f5f0)] px-2 py-1">
            {targetLabel}
          </span>
        )}
        {typeof item.metadata?.changed_count === "number" && (
          <span className="rounded bg-[var(--surface-secondary,#f5f5f0)] px-2 py-1">
            {item.metadata.changed_count} thay đổi
          </span>
        )}
        {typeof item.metadata?.question_count === "number" && (
          <span className="rounded bg-[var(--surface-secondary,#f5f5f0)] px-2 py-1">
            {item.metadata.question_count} câu hỏi
          </span>
        )}
      </div>
    </button>
  );
}
