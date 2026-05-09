/**
 * VisualArtifactCard — Claude-style artifact card for tool_create_visual_code.
 *
 * Shows a compact card in the reasoning rail with:
 * - Header: icon + status + title
 * - Body: code preview (first 6 lines of code_html, monospace)
 * - Status: spinner when pending, checkmark when complete
 * - Click: expand/collapse full code
 */
import { memo, useState, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  CheckCircle2,
  ChevronDown,
  Code2,
  Loader2,
  Palette,
} from "lucide-react";
import type { ToolExecutionBlockData } from "@/api/types";

interface VisualArtifactCardProps {
  block: ToolExecutionBlockData;
}

const MAX_PREVIEW_LINES = 6;

function extractTitle(args?: Record<string, unknown>): string {
  if (!args) return "Visual";
  if (typeof args.title === "string" && args.title.trim()) return args.title.trim();
  if (typeof args.visual_type === "string") return args.visual_type;
  return "Visual";
}

function extractCodePreview(args?: Record<string, unknown>): string[] {
  if (!args) return [];
  const code = typeof args.code_html === "string" ? args.code_html : "";
  if (!code.trim()) return [];
  return code.split("\n").slice(0, MAX_PREVIEW_LINES);
}

function extractVisualType(args?: Record<string, unknown>): string {
  if (!args) return "html";
  if (typeof args.visual_type === "string") return args.visual_type;
  return "html";
}

export const VisualArtifactCard = memo(function VisualArtifactCard({
  block,
}: VisualArtifactCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isPending = block.status === "pending";
  const title = useMemo(() => extractTitle(block.tool.args), [block.tool.args]);
  const codeLines = useMemo(() => extractCodePreview(block.tool.args), [block.tool.args]);
  const visualType = useMemo(() => extractVisualType(block.tool.args), [block.tool.args]);

  const fullCode = typeof block.tool.args?.code_html === "string" ? block.tool.args.code_html : "";
  const allLines = fullCode.split("\n");
  const hasMore = allLines.length > MAX_PREVIEW_LINES;

  return (
    <article
      className="visual-artifact-card group/visual-artifact"
      data-visual-type={visualType}
      data-status={isPending ? "pending" : "complete"}
    >
      {/* Header */}
      <div className="visual-artifact-card__header">
        <div className="visual-artifact-card__icon">
          <Palette size={16} className="text-[var(--accent)] shrink-0" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="visual-artifact-card__eyebrow">
            <Code2 size={10} className="opacity-50" />
            <span>{isPending ? "Đang tạo visual" : "Visual"}</span>
          </div>
          <div className="visual-artifact-card__title">{title}</div>
        </div>

        <div className="visual-artifact-card__status">
          {isPending ? (
            <Loader2 size={14} className="animate-spin text-[var(--accent)]" />
          ) : (
            <CheckCircle2 size={14} className="text-[var(--green)]" />
          )}
          <span className="text-[10px] text-[var(--text3)]">
            {isPending ? "Đang tạo..." : "Đã xong"}
          </span>
        </div>
      </div>

      {/* Code preview */}
      {codeLines.length > 0 && (
        <button
          type="button"
          className="visual-artifact-card__preview"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={expanded ? "Thu gọn code" : "Xem code"}
        >
          <pre className="visual-artifact-card__code">
            <code>
              {(expanded ? allLines : codeLines).join("\n")}
              {!expanded && hasMore && "\n..."}
            </code>
          </pre>

          {hasMore && (
            <div className="visual-artifact-card__toggle">
              <span>{expanded ? "Thu gon" : `+${allLines.length - MAX_PREVIEW_LINES} dong`}</span>
              <ChevronDown
                size={12}
                className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
              />
            </div>
          )}
        </button>
      )}

      {/* Building shimmer for pending state */}
      <AnimatePresence>
        {isPending && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="visual-artifact-card__shimmer"
            aria-hidden="true"
          >
            <div className="visual-artifact-card__shimmer-bar" />
            <div className="visual-artifact-card__shimmer-bar visual-artifact-card__shimmer-bar--short" />
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
});
