/**
 * ArtifactCard - compact inline card in chat message.
 *
 * Artifacts should feel like first-class outputs, not raw blobs in a transcript.
 * The card surfaces what was created, what kind of artifact it is, and the
 * primary actions: inspect and download.
 */
import { memo, useCallback, type KeyboardEvent, type MouseEvent } from "react";
import {
  BarChart3,
  Code2,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Globe,
  Table2,
} from "lucide-react";
import type { ArtifactData, ArtifactType } from "@/api/types";
import { useSettingsStore } from "@/stores/settings-store";
import { useUIStore } from "@/stores/ui-store";
import { ArtifactRenderer } from "./artifacts";
import {
  artifactHasBinaryFile,
  artifactPreviewSnippet,
  describeArtifactFile,
  resolveArtifactFileUrl,
} from "@/lib/artifact-file";

interface ArtifactCardProps {
  artifact: ArtifactData;
}

const ARTIFACT_ICONS: Record<ArtifactType, typeof Code2> = {
  code: Code2,
  html: Globe,
  react: Code2,
  table: Table2,
  chart: BarChart3,
  document: FileText,
  excel: FileSpreadsheet,
};

const ARTIFACT_LABELS: Record<ArtifactType, string> = {
  code: "Code",
  html: "HTML",
  react: "React",
  table: "Bảng dữ liệu",
  chart: "Biểu đồ",
  document: "Tài liệu",
  excel: "Excel",
};

const ARTIFACT_CTA_LABELS: Record<ArtifactType, string> = {
  code: "Mở chi tiết",
  html: "Mở bản xem",
  react: "Mở bản xem",
  table: "Mở bảng",
  chart: "Mở biểu đồ",
  document: "Mở tài liệu",
  excel: "Mở bảng tính",
};

const MAX_PREVIEW_LINES = 6;

export const ArtifactCard = memo(function ArtifactCard({
  artifact,
}: ArtifactCardProps) {
  const openArtifact = useUIStore((s) => s.openArtifact);
  const serverUrl = useSettingsStore((s) => s.settings.server_url);
  const Icon = ARTIFACT_ICONS[artifact.artifact_type] || Code2;
  const label =
    ARTIFACT_LABELS[artifact.artifact_type] || artifact.artifact_type;
  const ctaLabel = ARTIFACT_CTA_LABELS[artifact.artifact_type] || "Mở chi tiết";
  const resolvedFileUrl = resolveArtifactFileUrl(artifact, serverUrl);
  const downloadable = artifactHasBinaryFile(artifact);
  const previewText = artifactPreviewSnippet(artifact, 220);
  const lines = previewText.split("\n");
  const previewLines = lines.slice(0, MAX_PREVIEW_LINES);
  const hasMore = lines.length > MAX_PREVIEW_LINES;
  const useRichPreview =
    artifact.artifact_type !== "code" && artifact.artifact_type !== "react";

  const excelMeta =
    artifact.artifact_type === "excel"
      ? `${artifact.metadata?.row_count ?? "?"} hàng x ${artifact.metadata?.column_count ?? "?"} cột`
      : null;
  const subMeta = excelMeta || describeArtifactFile(artifact);

  const handleOpen = useCallback(() => {
    openArtifact(artifact.artifact_id);
  }, [openArtifact, artifact.artifact_id]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handleOpen();
      }
    },
    [handleOpen],
  );

  const handleDownloadClick = useCallback(
    (event: MouseEvent<HTMLAnchorElement>) => {
      event.stopPropagation();
    },
    [],
  );

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={handleOpen}
      onKeyDown={handleKeyDown}
      className="artifact-card-shell group/artifact"
      aria-label={`Mở artifact: ${artifact.title}`}
    >
      <div className="artifact-card-shell__header">
        <div className="artifact-card-shell__icon">
          <Icon size={16} className="text-[var(--accent)] shrink-0" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="artifact-card-shell__eyebrow">
            <span className="artifact-card-shell__type">{label}</span>
            {artifact.language && (
              <span className="artifact-card-shell__language">
                {artifact.language}
              </span>
            )}
          </div>
          <div className="artifact-card-shell__title">{artifact.title}</div>
          {subMeta && (
            <div className="artifact-card-shell__meta">{subMeta}</div>
          )}
        </div>

        <div className="artifact-card-shell__actions">
          <span className="artifact-card-shell__open">
            <ExternalLink size={13} />
            {ctaLabel}
          </span>

          {downloadable && resolvedFileUrl && (
            <a
              href={resolvedFileUrl}
              target="_blank"
              rel="noreferrer"
              onClick={handleDownloadClick}
              className="artifact-card-shell__download"
              title="Tải file"
              aria-label={`Tải file ${artifact.title}`}
            >
              <Download size={13} />
              Tải file
            </a>
          )}
        </div>
      </div>

      {useRichPreview ? (
        <div className="artifact-card-shell__preview pointer-events-none">
          <ArtifactRenderer artifact={artifact} mode="card" />
        </div>
      ) : previewText ? (
        <div className="artifact-card-shell__preview artifact-card-shell__preview--code">
          <pre className="text-xs font-mono text-text-secondary leading-relaxed overflow-hidden whitespace-pre-wrap">
            <code>
              {previewLines.join("\n")}
              {hasMore && "\n..."}
            </code>
          </pre>
        </div>
      ) : null}

      {artifact.metadata?.execution_status && (
        <div
          className="artifact-card-shell__status"
          role="status"
          aria-label={`Trạng thái: ${artifact.metadata.execution_status}`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              artifact.metadata.execution_status === "success"
                ? "bg-green-500"
                : artifact.metadata.execution_status === "error"
                  ? "bg-red-500"
                  : artifact.metadata.execution_status === "running"
                    ? "bg-amber-500 animate-pulse"
                    : "bg-gray-400"
            }`}
          />
          <span className="text-[10px] text-text-tertiary">
            {artifact.metadata.execution_status === "success" &&
              "Đã chạy thành công"}
            {artifact.metadata.execution_status === "error" && "Lỗi thực thi"}
            {artifact.metadata.execution_status === "running" && "Đang chạy..."}
            {artifact.metadata.execution_status === "pending" && "Chưa chạy"}
          </span>
        </div>
      )}
    </article>
  );
});
