/**
 * DocumentArtifact - preview for document-style artifacts.
 *
 * For generated DOCX files we show the structured preview text plus a clear
 * download action, instead of pretending the binary file is directly inline.
 */
import { Download, FileText } from "lucide-react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { ArtifactData } from "@/api/types";
import { useSettingsStore } from "@/stores/settings-store";
import {
  artifactPreviewSnippet,
  describeArtifactFile,
  resolveArtifactFileUrl,
} from "@/lib/artifact-file";

interface Props {
  artifact: ArtifactData;
  mode: "card" | "panel";
}

export default function DocumentArtifact({ artifact, mode }: Props) {
  const serverUrl = useSettingsStore((s) => s.settings.server_url);
  const fileUrl = resolveArtifactFileUrl(artifact, serverUrl);
  const language = artifact.language?.toLowerCase() || "";
  const isMarkdown = language === "markdown" || language === "md" || !language;
  const preview = artifactPreviewSnippet(artifact, mode === "card" ? 180 : 600);
  const filename = describeArtifactFile(artifact);
  const contentType =
    typeof artifact.metadata?.content_type === "string"
      ? artifact.metadata.content_type
      : null;

  if (mode === "card") {
    return (
      <div className="p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
            <FileText size={18} />
          </div>
          <div className="min-w-0 flex-1">
            {filename && (
              <div className="text-[11px] text-text-tertiary">{filename}</div>
            )}
            {contentType && (
              <div className="text-[11px] text-text-tertiary mt-1">
                {contentType}
              </div>
            )}
          </div>
          {fileUrl && (
            <a
              href={fileUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-surface-tertiary hover:bg-border text-text-secondary hover:text-text transition-colors text-xs shrink-0"
            >
              <Download size={14} />
              Tải file
            </a>
          )}
        </div>
        <div className="rounded-2xl border border-border/70 bg-surface-secondary/80 px-3 py-3 text-sm text-text-secondary leading-relaxed whitespace-pre-wrap">
          {preview}
        </div>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="rounded-2xl border border-border bg-surface-secondary p-4 flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
          <FileText size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-text">{artifact.title}</div>
          {filename && (
            <div className="text-xs text-text-tertiary mt-1">{filename}</div>
          )}
          {contentType && (
            <div className="text-xs text-text-tertiary mt-1">{contentType}</div>
          )}
        </div>
        {fileUrl && (
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-surface-tertiary hover:bg-border text-text-secondary hover:text-text transition-colors text-xs shrink-0"
          >
            <Download size={14} />
            Tải file
          </a>
        )}
      </div>

      {isMarkdown ? (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <MarkdownRenderer content={artifact.content} />
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-surface-secondary p-4">
          <pre className="text-sm text-text-secondary whitespace-pre-wrap leading-relaxed">
            {preview}
          </pre>
        </div>
      )}
    </div>
  );
}
