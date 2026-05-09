/**
 * ArtifactPanel - side panel for expanded artifact viewing.
 *
 * Type-aware panel:
 * - HTML/React default to live preview
 * - Document/Excel/Table/Chart default to meaningful preview
 * - Code keeps source first
 * - Generated files always expose a direct download action
 */
import { memo, useMemo, useCallback, useState, useEffect } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  X,
  Copy,
  Check,
  Code2,
  Eye,
  Terminal,
  Play,
  Download,
  Globe,
  FileText,
  FileSpreadsheet,
  Table2,
  BarChart3,
} from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { ArtifactRenderer } from "@/components/chat/artifacts";
import type { ArtifactData } from "@/api/types";
import {
  artifactPreviewSnippet,
  describeArtifactFile,
  resolveArtifactFileUrl,
} from "@/lib/artifact-file";

type ArtifactTabId = "code" | "preview" | "output";

interface ArtifactTabConfig {
  id: ArtifactTabId;
  label: string;
  icon: typeof Code2;
}

const PANEL_ICONS: Record<string, typeof Code2> = {
  code: Code2,
  html: Globe,
  react: Code2,
  table: Table2,
  chart: BarChart3,
  document: FileText,
  excel: FileSpreadsheet,
};

function artifactHasOutput(artifact: ArtifactData): boolean {
  return Boolean(
    artifact.metadata?.output ||
    artifact.metadata?.error ||
    artifact.metadata?.image_url,
  );
}

function getArtifactTabs(artifact: ArtifactData): ArtifactTabConfig[] {
  const tabs: ArtifactTabConfig[] = [];
  const hasOutput = artifactHasOutput(artifact);

  if (artifact.artifact_type === "code") {
    tabs.push({ id: "code", label: "Mã nguồn", icon: Code2 });
    if (hasOutput)
      tabs.push({ id: "output", label: "Kết quả", icon: Terminal });
    return tabs;
  }

  if (artifact.artifact_type === "html" || artifact.artifact_type === "react") {
    tabs.push({ id: "preview", label: "Xem trước", icon: Eye });
    tabs.push({ id: "code", label: "Mã nguồn", icon: Code2 });
    if (hasOutput)
      tabs.push({ id: "output", label: "Kết quả", icon: Terminal });
    return tabs;
  }

  tabs.push({
    id: "preview",
    label:
      artifact.artifact_type === "excel"
        ? "Dữ liệu"
        : artifact.artifact_type === "chart"
          ? "Biểu đồ"
          : artifact.artifact_type === "table"
            ? "Bảng"
            : "Nội dung",
    icon: Eye,
  });
  tabs.push({ id: "code", label: "Chi tiết", icon: Code2 });
  if (hasOutput) tabs.push({ id: "output", label: "Kết quả", icon: Terminal });
  return tabs;
}

function getDefaultArtifactTab(artifact: ArtifactData): ArtifactTabId {
  return artifact.artifact_type === "code" ? "code" : "preview";
}

/** Shared content for both inline and overlay modes */
function ArtifactPanelContent({
  artifact,
  tabs,
  artifactActiveTab,
  setArtifactTab,
  closeArtifact,
  resolvedFileUrl,
  fileDescription,
  HeaderIcon,
}: {
  artifact: ArtifactData;
  tabs: ArtifactTabConfig[];
  artifactActiveTab: ArtifactTabId;
  setArtifactTab: (tab: ArtifactTabId) => void;
  closeArtifact: () => void;
  resolvedFileUrl: string | null;
  fileDescription: string | null;
  HeaderIcon: typeof Code2;
}) {
  return (
    <>
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border shrink-0 artifact-panel-shell__header">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
          <HeaderIcon size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-text truncate">
            {artifact.title}
          </div>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-text-tertiary">
            <span className="uppercase tracking-[0.08em]">
              {artifact.artifact_type}
            </span>
            {fileDescription && (
              <span className="truncate">{fileDescription}</span>
            )}
            {artifact.language && (
              <span className="font-mono">{artifact.language}</span>
            )}
          </div>
        </div>
        {resolvedFileUrl && (
          <a
            href={resolvedFileUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-surface-tertiary text-text-tertiary hover:text-text transition-colors text-xs"
            title="Mở hoặc tải file đã tạo"
          >
            <Download size={14} />
            Tải file
          </a>
        )}
        <button
          onClick={closeArtifact}
          className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-tertiary hover:text-text transition-colors"
          aria-label="Đóng panel artifact"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex border-b border-border shrink-0 artifact-panel-shell__tabs">
        {tabs.map((tab) => {
          const TabIcon = tab.icon;
          const isActive = artifactActiveTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setArtifactTab(tab.id)}
              data-active={isActive ? "true" : "false"}
              className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition-colors ${
                isActive
                  ? "text-[var(--accent)]"
                  : "text-text-tertiary hover:text-text-secondary"
              } artifact-panel-shell__tab`}
            >
              <TabIcon size={14} />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-auto">
        {artifactActiveTab === "preview" && <PreviewTab artifact={artifact} />}
        {artifactActiveTab === "code" &&
          (artifact.artifact_type === "code" ||
          artifact.artifact_type === "html" ||
          artifact.artifact_type === "react" ? (
            <CodeTab artifact={artifact} />
          ) : (
            <DetailsTab artifact={artifact} resolvedFileUrl={resolvedFileUrl} />
          ))}
        {artifactActiveTab === "output" && <OutputTab artifact={artifact} />}
      </div>
    </>
  );
}

export const ArtifactPanel = memo(function ArtifactPanel({
  inline,
}: {
  inline?: boolean;
}) {
  const {
    artifactPanelOpen,
    selectedArtifactId,
    artifactActiveTab,
    closeArtifact,
    setArtifactTab,
    _ephemeralArtifact,
  } = useUIStore();
  const serverUrl = useSettingsStore((s) => s.settings.server_url);

  const streamingArtifacts = useChatStore((s) => s.streamingArtifacts);
  const messages = useChatStore((s) => s.activeConversation()?.messages);
  const messageCount = messages?.length ?? 0;

  const artifact = useMemo<ArtifactData | null>(() => {
    if (!selectedArtifactId) return null;
    if (
      _ephemeralArtifact &&
      _ephemeralArtifact.artifact_id === selectedArtifactId
    ) {
      return _ephemeralArtifact;
    }
    const streaming = streamingArtifacts.find(
      (item) => item.artifact_id === selectedArtifactId,
    );
    if (streaming) return streaming;
    if (messages) {
      for (const message of messages) {
        const found = message.artifacts?.find(
          (item) => item.artifact_id === selectedArtifactId,
        );
        if (found) return found;
      }
    }
    return null;
  }, [
    selectedArtifactId,
    streamingArtifacts,
    messages,
    messageCount,
    _ephemeralArtifact,
  ]);

  const resolvedFileUrl = useMemo(
    () => (artifact ? resolveArtifactFileUrl(artifact, serverUrl) : null),
    [artifact, serverUrl],
  );
  const tabs = useMemo(
    () => (artifact ? getArtifactTabs(artifact) : []),
    [artifact],
  );
  const HeaderIcon = artifact
    ? PANEL_ICONS[artifact.artifact_type] || Code2
    : Code2;
  const fileDescription = artifact ? describeArtifactFile(artifact) : null;

  useEffect(() => {
    if (!artifact) return;
    const defaultTab = getDefaultArtifactTab(artifact);
    setArtifactTab(defaultTab);
  }, [artifact?.artifact_id, artifact, setArtifactTab]);

  useEffect(() => {
    if (!artifact || tabs.length === 0) return;
    if (!tabs.some((tab) => tab.id === artifactActiveTab)) {
      setArtifactTab(tabs[0].id);
    }
  }, [artifact, tabs, artifactActiveTab, setArtifactTab]);

  if (!artifactPanelOpen || !artifact) return null;

  const contentProps = {
    artifact,
    tabs,
    artifactActiveTab,
    setArtifactTab,
    closeArtifact,
    resolvedFileUrl,
    fileDescription,
    HeaderIcon,
  };

  // Sprint 233: Inline mode — render directly inside resizable split panel
  if (inline) {
    return (
      <div className="h-full flex flex-col artifact-panel-shell">
        <ArtifactPanelContent {...contentProps} />
      </div>
    );
  }

  // Mobile / overlay fallback — original fixed positioning
  return (
    <AnimatePresence>
      <motion.div
        key="artifact-panel"
        initial={{ x: "100%", opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: "100%", opacity: 0 }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className="fixed right-0 top-[var(--titlebar-height,32px)] bottom-[var(--statusbar-height,24px)] w-[52vw] max-w-[860px] min-w-[420px] border-l border-border z-40 flex flex-col shadow-xl artifact-panel-shell"
      >
        <ArtifactPanelContent {...contentProps} />
      </motion.div>
    </AnimatePresence>
  );
});

function CodeTab({ artifact }: { artifact: ArtifactData }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(artifact.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard errors.
    }
  }, [artifact.content]);

  const codeBlock = `\`\`\`${artifact.language || ""}\n${artifact.content}\n\`\`\``;

  return (
    <div className="relative">
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-surface-tertiary hover:bg-border text-text-secondary transition-colors"
          title="Sao chép"
        >
          {copied ? (
            <Check size={12} className="text-green-500" />
          ) : (
            <Copy size={12} />
          )}
          {copied ? "Đã sao chép" : "Sao chép"}
        </button>
      </div>

      <div className="p-4 text-sm">
        <MarkdownRenderer content={codeBlock} />
      </div>
    </div>
  );
}

function PreviewTab({ artifact }: { artifact: ArtifactData }) {
  return <ArtifactRenderer artifact={artifact} mode="panel" />;
}

function DetailsTab({
  artifact,
  resolvedFileUrl,
}: {
  artifact: ArtifactData;
  resolvedFileUrl: string | null;
}) {
  const metadataEntries = Object.entries(artifact.metadata || {})
    .filter(([key, value]) => {
      if (value == null || value === "") return false;
      return !["output", "error", "image_url", "table_data"].includes(key);
    })
    .slice(0, 12);

  const summary = artifactPreviewSnippet(artifact, 500);
  const filename = describeArtifactFile(artifact);

  return (
    <div className="p-5 space-y-4">
      <div className="rounded-2xl border border-border bg-surface-secondary p-4">
        <div className="text-sm font-medium text-text">{artifact.title}</div>
        {filename && (
          <div className="text-xs text-text-tertiary mt-1">{filename}</div>
        )}
        <div className="text-xs text-text-tertiary mt-1">
          Loại artifact: {artifact.artifact_type}
        </div>
        {resolvedFileUrl && (
          <a
            href={resolvedFileUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 mt-3 px-3 py-2 rounded-xl bg-surface-tertiary hover:bg-border text-text-secondary hover:text-text transition-colors text-xs"
          >
            <Download size={14} />
            Mở file đã tạo
          </a>
        )}
      </div>

      {metadataEntries.length > 0 && (
        <div className="rounded-2xl border border-border bg-surface-secondary overflow-hidden">
          <div className="px-4 py-3 border-b border-border text-xs uppercase tracking-wider text-text-tertiary">
            Metadata
          </div>
          <div className="divide-y divide-border/60">
            {metadataEntries.map(([key, value]) => (
              <div
                key={key}
                className="px-4 py-3 flex items-start gap-4 text-sm"
              >
                <div className="w-32 shrink-0 text-text-tertiary">{key}</div>
                <div className="min-w-0 text-text break-words">
                  {typeof value === "string" ? value : JSON.stringify(value)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-surface-secondary p-4">
        <div className="text-xs uppercase tracking-wider text-text-tertiary mb-2">
          Tóm tắt nội dung
        </div>
        <pre className="text-sm text-text-secondary whitespace-pre-wrap leading-relaxed">
          {summary}
        </pre>
      </div>
    </div>
  );
}

function OutputTab({ artifact }: { artifact: ArtifactData }) {
  const output = artifact.metadata?.output;
  const error = artifact.metadata?.error;
  const imageUrl = artifact.metadata?.image_url;

  if (!output && !error && !imageUrl) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-text-tertiary py-16">
        <Play size={32} className="mb-3 opacity-50" />
        <p className="text-sm">Artifact này không có kênh output riêng.</p>
        <p className="text-xs mt-1 opacity-70">
          Hãy xem tab preview hoặc chi tiết để làm việc với file đã tạo.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      {output && (
        <div>
          <div className="text-[10px] text-text-tertiary font-medium mb-1 uppercase tracking-wider">
            stdout
          </div>
          <pre className="bg-surface-secondary rounded-lg p-3 text-xs font-mono text-text-secondary overflow-auto max-h-[300px] whitespace-pre-wrap">
            {output}
          </pre>
        </div>
      )}

      {error && (
        <div>
          <div className="text-[10px] text-red-500 font-medium mb-1 uppercase tracking-wider">
            stderr
          </div>
          <pre className="bg-red-50 dark:bg-red-950/30 rounded-lg p-3 text-xs font-mono text-red-600 dark:text-red-400 overflow-auto max-h-[200px] whitespace-pre-wrap">
            {error}
          </pre>
        </div>
      )}

      {imageUrl && (
        <div>
          <div className="text-[10px] text-text-tertiary font-medium mb-1 uppercase tracking-wider">
            Output
          </div>
          <img
            src={
              typeof imageUrl === "string" && imageUrl.startsWith("data:")
                ? imageUrl
                : `data:image/png;base64,${imageUrl}`
            }
            alt="Execution output"
            className="rounded-lg max-w-full"
          />
        </div>
      )}
    </div>
  );
}
