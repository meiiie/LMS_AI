import { useEffect, useMemo, useState } from "react";
import { DiffEditor, Editor } from "@monaco-editor/react";
import {
  Code2,
  Eye,
  File,
  FileCode2,
  FileImage,
  FileText,
  GitCompareArrows,
  LoaderCircle,
  Pin,
  Radio,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { NekoSession } from "../stores/neko-session-store";
import {
  useNekoWorkspaceStore,
  type ObservedWorkspaceActivity,
} from "../stores/neko-workspace-store";
import type { WorkspaceEntry, WorkspaceFile } from "../workspace-files";

interface NekoWorkspacePaneProps {
  session: NekoSession;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function fileIcon(path: string, kind?: WorkspaceFile["kind"]) {
  const className = "h-3.5 w-3.5 shrink-0";
  if (kind === "image" || /\.(?:gif|jpe?g|png|webp)$/i.test(path)) {
    return <FileImage aria-hidden="true" className={className} />;
  }
  if (/\.(?:html?|jsx?|tsx?|css|json|py|rs|go|java|rb|sh|sql|ya?ml)$/i.test(path)) {
    return <FileCode2 aria-hidden="true" className={className} />;
  }
  if (/\.(?:md|mdx|txt|pdf)$/i.test(path)) {
    return <FileText aria-hidden="true" className={className} />;
  }
  return <File aria-hidden="true" className={className} />;
}

function activityLabel(activity: ObservedWorkspaceActivity | undefined): string | null {
  if (!activity) return null;
  const action =
    activity.operation === "read"
      ? "Đang đọc"
      : activity.operation === "delete"
        ? "Đang xóa"
        : activity.operation === "move"
          ? "Đang chuyển"
          : "Đang sửa";
  if (activity.status === "pending" || activity.status === "in_progress") return action;
  if (activity.status === "failed" || activity.status === "cancelled") return "Không áp dụng";
  return activity.operation === "read" ? "Đã đọc" : "Đã cập nhật";
}

function secureHtml(content: string): string {
  const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src data: blob:;">`;
  if (/<head(?:\s[^>]*)?>/i.test(content)) {
    return content.replace(/<head(?:\s[^>]*)?>/i, (head) => `${head}${csp}`);
  }
  return `<!doctype html><html><head>${csp}</head><body>${content}</body></html>`;
}

function canPreview(file: WorkspaceFile): boolean {
  return (
    file.kind === "image" ||
    file.kind === "pdf" ||
    file.language === "html" ||
    file.language === "markdown" ||
    file.path.toLowerCase().endsWith(".svg")
  );
}

function FilePreview({ file }: { file: WorkspaceFile }) {
  if (file.kind === "image" && file.dataUrl) {
    return (
      <div className="grid h-full place-items-center overflow-auto bg-[var(--nk-inset)] p-6">
        <img src={file.dataUrl} alt={file.name} className="max-h-full max-w-full rounded-lg shadow-sm" />
      </div>
    );
  }
  if (file.kind === "pdf" && file.dataUrl) {
    return (
      <iframe
        title={`Xem trước ${file.name}`}
        src={file.dataUrl}
        sandbox=""
        className="h-full w-full border-0 bg-white"
      />
    );
  }
  if (file.language === "markdown" && file.content !== null) {
    return (
      <article className="h-full overflow-auto bg-[var(--nk-composer)] px-8 py-6 text-[14px] leading-6">
        <MarkdownRenderer content={file.content} />
      </article>
    );
  }
  if (
    file.content !== null &&
    (file.language === "html" || file.path.toLowerCase().endsWith(".svg"))
  ) {
    return (
      <iframe
        title={`Xem trước ${file.name}`}
        srcDoc={secureHtml(file.content)}
        sandbox="allow-scripts"
        className="h-full w-full border-0 bg-white"
      />
    );
  }
  return null;
}

function EmptyContent({ tab }: { tab: "files" | "changes" }) {
  return (
    <div className="grid h-full place-items-center px-8 text-center">
      <div className="max-w-xs">
        {tab === "files" ? (
          <FileCode2 aria-hidden="true" className="mx-auto h-8 w-8 text-[var(--nk-ghost)]" />
        ) : (
          <GitCompareArrows aria-hidden="true" className="mx-auto h-8 w-8 text-[var(--nk-ghost)]" />
        )}
        <p className="mt-3 text-[13px] font-medium text-[var(--nk-text-2)]">
          {tab === "files" ? "Chọn một file để xem" : "Chọn một thay đổi để so sánh"}
        </p>
        <p className="mt-1 text-[11.5px] leading-5 text-[var(--nk-text-3)]">
          Pane này theo dõi đúng workspace của phiên và cập nhật khi agent thao tác.
        </p>
      </div>
    </div>
  );
}

function FileRow({
  entry,
  selected,
  activity,
  onClick,
}: {
  entry: WorkspaceEntry;
  selected: boolean;
  activity?: ObservedWorkspaceActivity;
  onClick: () => void;
}) {
  const label = activityLabel(activity);
  return (
    <button
      type="button"
      className={`group flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--nk-focus-soft)] ${
        selected ? "bg-[var(--nk-item-active)] text-[var(--nk-text)]" : "text-[var(--nk-text-2)] hover:bg-[var(--nk-overlay)]"
      }`}
      onClick={onClick}
      title={entry.path}
    >
      <span className="mt-0.5 text-[var(--nk-text-3)]">{fileIcon(entry.path)}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[11.5px]">{entry.path}</span>
        {label ? (
          <span className={`mt-0.5 flex items-center gap-1 text-[9.5px] ${
            activity?.status === "pending" || activity?.status === "in_progress"
              ? "text-[var(--nk-accent)]"
              : "text-[var(--nk-text-3)]"
          }`}>
            <span className={`h-1 w-1 rounded-full ${
              activity?.status === "pending" || activity?.status === "in_progress"
                ? "animate-pulse bg-[var(--nk-accent)]"
                : "bg-[var(--nk-ghost)]"
            }`} />
            {label}
          </span>
        ) : null}
      </span>
    </button>
  );
}

export function NekoWorkspacePane({ session }: NekoWorkspacePaneProps) {
  const workspace = session.workspace;
  const pane = useNekoWorkspaceStore((state) => state.sessions[session.id]);
  const {
    close,
    openChange,
    openFile,
    refresh,
    setFollowAgent,
    setPinned,
    setTab,
  } = useNekoWorkspaceStore();
  const [query, setQuery] = useState("");
  const [fileView, setFileView] = useState<"code" | "preview">("code");

  const filteredEntries = useMemo(() => {
    if (!pane) return [];
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return pane.entries;
    return pane.entries.filter((entry) =>
      entry.path.toLocaleLowerCase().includes(normalized),
    );
  }, [pane, query]);

  useEffect(() => {
    const file = pane?.selectedFile;
    setFileView(file && canPreview(file) && file.language === "html" ? "preview" : "code");
  }, [pane?.selectedFile?.path]);

  useEffect(() => {
    if (!pane?.open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close(session.id);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, pane?.open, session.id]);

  if (!workspace || !pane?.open) return null;

  const selectedActivity = pane.selectedPath
    ? pane.activities[pane.selectedPath]
    : undefined;
  const selectedActivityLabel = activityLabel(selectedActivity);

  return (
    <aside
      className="flex h-full min-h-0 flex-col bg-[var(--nk-composer)]"
      aria-label="Workspace của phiên"
      data-testid="neko-workspace-pane"
    >
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[var(--nk-border)] px-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[12.5px] font-semibold text-[var(--nk-text)]">Workspace</h2>
          <p className="truncate text-[9.5px] text-[var(--nk-text-3)]">{workspace.name}</p>
        </div>
        <button
          type="button"
          aria-label="Theo agent"
          aria-pressed={pane.followAgent}
          title="Tự mở file agent đang thao tác"
          className={`grid h-7 w-7 place-items-center rounded-md transition-colors ${pane.followAgent ? "bg-[var(--nk-overlay-strong)] text-[var(--nk-accent)]" : "text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)]"}`}
          onClick={() => setFollowAgent(session.id, !pane.followAgent)}
        >
          <Radio aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Ghim nội dung"
          aria-pressed={pane.pinned}
          title="Không để event mới đổi file đang xem"
          className={`grid h-7 w-7 place-items-center rounded-md transition-colors ${pane.pinned ? "bg-[var(--nk-overlay-strong)] text-[var(--nk-accent)]" : "text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)]"}`}
          onClick={() => setPinned(session.id, !pane.pinned)}
        >
          <Pin aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Làm mới workspace"
          aria-busy={pane.refreshing}
          className="grid h-7 w-7 place-items-center rounded-md text-[var(--nk-text-3)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] disabled:opacity-50"
          disabled={pane.refreshing}
          onClick={() => void refresh(session.id, workspace)}
        >
          <RefreshCw aria-hidden="true" className={`h-3.5 w-3.5 ${pane.refreshing ? "animate-spin" : ""}`} />
        </button>
        <button
          type="button"
          aria-label="Đóng workspace"
          className="grid h-7 w-7 place-items-center rounded-md text-[var(--nk-text-3)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)]"
          onClick={() => close(session.id)}
        >
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </header>

      <nav className="flex h-9 shrink-0 items-end gap-1 border-b border-[var(--nk-border)] px-3" aria-label="Nội dung workspace">
        {(["files", "changes"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            aria-pressed={pane.activeTab === tab}
            className={`relative flex h-9 items-center gap-1.5 px-2 text-[11px] font-medium transition-colors ${pane.activeTab === tab ? "text-[var(--nk-text)]" : "text-[var(--nk-text-3)] hover:text-[var(--nk-text-2)]"}`}
            onClick={() => setTab(session.id, tab)}
          >
            {tab === "files" ? <File aria-hidden="true" className="h-3.5 w-3.5" /> : <GitCompareArrows aria-hidden="true" className="h-3.5 w-3.5" />}
            {tab === "files" ? "Files" : "Changes"}
            <span className="font-mono text-[9px] text-[var(--nk-ghost)]">
              {tab === "files" ? pane.entries.length : pane.changes.length}
            </span>
            {pane.activeTab === tab ? <span className="absolute inset-x-1 bottom-0 h-px bg-[var(--nk-accent)]" /> : null}
          </button>
        ))}
        {pane.unseenChanges > 0 ? (
          <span className="ml-auto mb-2 rounded-md bg-[var(--nk-danger-soft)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--nk-danger)]">
            {pane.unseenChanges} mới
          </span>
        ) : null}
      </nav>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(11rem,30%)_minmax(0,1fr)]">
        <section className="flex min-h-0 flex-col border-r border-[var(--nk-border)] bg-[var(--nk-sidebar)]">
          {pane.activeTab === "files" ? (
            <div className="relative m-2 shrink-0">
              <Search aria-hidden="true" className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--nk-ghost)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Lọc file…"
                aria-label="Lọc file workspace"
                className="h-7 w-full rounded-md border border-[var(--nk-border)] bg-[var(--nk-composer)] pl-7 pr-2 text-[10.5px] text-[var(--nk-text)] outline-none placeholder:text-[var(--nk-ghost)] focus:border-[var(--nk-border-strong)] focus:ring-2 focus:ring-[var(--nk-focus-soft)]"
              />
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-auto px-1.5 pb-2">
            {pane.activeTab === "files" ? (
              filteredEntries.length ? (
                filteredEntries.map((entry) => (
                  <FileRow
                    key={entry.path}
                    entry={entry}
                    selected={pane.selectedPath === entry.path}
                    activity={pane.activities[entry.path]}
                    onClick={() => void openFile(session.id, workspace, entry.path)}
                  />
                ))
              ) : (
                <p className="px-2 py-4 text-[10.5px] leading-4 text-[var(--nk-text-3)]">
                  {pane.refreshing ? "Đang đọc cây file…" : "Không tìm thấy file phù hợp."}
                </p>
              )
            ) : pane.isGit === false ? (
              <p className="px-2 py-4 text-[10.5px] leading-4 text-[var(--nk-text-3)]">
                Workspace chưa có Git. File agent chạm vẫn xuất hiện trong tab Files.
              </p>
            ) : pane.changes.length ? (
              pane.changes.map((change) => (
                <button
                  key={change.path}
                  type="button"
                  className={`flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${pane.selectedPath === change.path ? "bg-[var(--nk-item-active)]" : "hover:bg-[var(--nk-overlay)]"}`}
                  onClick={() => void openChange(session.id, workspace, change.path)}
                >
                  <span className={`mt-0.5 w-3 shrink-0 font-mono text-[9px] font-semibold ${change.status === "deleted" ? "text-[var(--nk-danger)]" : "text-[var(--nk-accent)]"}`}>
                    {change.status === "untracked" ? "U" : change.status === "added" ? "A" : change.status === "deleted" ? "D" : change.status === "renamed" ? "R" : "M"}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--nk-text-2)]">{change.path}</span>
                  {change.staged ? <span className="text-[8px] text-[var(--nk-ghost)]">staged</span> : null}
                </button>
              ))
            ) : (
              <p className="px-2 py-4 text-[10.5px] leading-4 text-[var(--nk-text-3)]">
                {pane.refreshing ? "Đang kiểm tra thay đổi…" : "Workspace đang sạch."}
              </p>
            )}
          </div>
          {pane.filesTruncated && pane.activeTab === "files" ? (
            <p className="shrink-0 border-t border-[var(--nk-border)] px-3 py-2 text-[9px] text-[var(--nk-text-3)]">
              Đã giới hạn 2.500 file. Dùng ô lọc để thu hẹp.
            </p>
          ) : null}
        </section>

        <section className="flex min-h-0 min-w-0 flex-col bg-[var(--nk-canvas)]">
          {pane.selectedPath ? (
            <div className="flex h-9 shrink-0 items-center gap-2 border-b border-[var(--nk-border)] px-3">
              <span className="text-[var(--nk-text-3)]">{fileIcon(pane.selectedPath, pane.selectedFile?.kind)}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-[var(--nk-text-2)]">{pane.selectedPath}</span>
              {selectedActivityLabel ? <span className="text-[9px] text-[var(--nk-accent)]">{selectedActivityLabel}</span> : null}
              {pane.selectedFile && canPreview(pane.selectedFile) ? (
                <div className="flex rounded-md bg-[var(--nk-inset)] p-0.5">
                  <button type="button" aria-label="Xem mã" className={`grid h-6 w-6 place-items-center rounded ${fileView === "code" ? "bg-[var(--nk-composer)] text-[var(--nk-text)] shadow-sm" : "text-[var(--nk-text-3)]"}`} onClick={() => setFileView("code")}><Code2 aria-hidden="true" className="h-3 w-3" /></button>
                  <button type="button" aria-label="Xem trước" className={`grid h-6 w-6 place-items-center rounded ${fileView === "preview" ? "bg-[var(--nk-composer)] text-[var(--nk-text)] shadow-sm" : "text-[var(--nk-text-3)]"}`} onClick={() => setFileView("preview")}><Eye aria-hidden="true" className="h-3 w-3" /></button>
                </div>
              ) : null}
              {pane.selectedFile ? <span className="font-mono text-[8.5px] text-[var(--nk-ghost)]">{formatBytes(pane.selectedFile.size)}</span> : null}
            </div>
          ) : null}

          <div className="min-h-0 flex-1">
            {pane.loading ? (
              <div className="grid h-full place-items-center" role="status">
                <span className="flex items-center gap-2 text-[11px] text-[var(--nk-text-3)]"><LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />Đang mở nội dung…</span>
              </div>
            ) : pane.error ? (
              <div className="grid h-full place-items-center px-8 text-center" role="alert">
                <div className="max-w-sm">
                  <p className="text-[12px] font-medium text-[var(--nk-danger)]">Không thể mở nội dung</p>
                  <p className="mt-1 break-words text-[10.5px] leading-5 text-[var(--nk-text-3)]">{pane.error}</p>
                </div>
              </div>
            ) : pane.activeTab === "changes" && pane.selectedDiff ? (
              pane.selectedDiff.binary ? (
                <div className="grid h-full place-items-center text-[11px] text-[var(--nk-text-3)]">Diff nhị phân không thể hiển thị an toàn.</div>
              ) : (
                <DiffEditor
                  original={pane.selectedDiff.original}
                  modified={pane.selectedDiff.modified}
                  language={pane.selectedDiff.language}
                  theme={document.documentElement.classList.contains("dark") ? "vs-dark" : "light"}
                  options={{ readOnly: true, domReadOnly: true, automaticLayout: true, minimap: { enabled: false }, renderSideBySide: true, wordWrap: "on" }}
                />
              )
            ) : pane.activeTab === "files" && pane.selectedFile ? (
              fileView === "preview" && canPreview(pane.selectedFile) ? (
                <FilePreview file={pane.selectedFile} />
              ) : pane.selectedFile.content !== null ? (
                <Editor
                  value={pane.selectedFile.content}
                  language={pane.selectedFile.language}
                  theme={document.documentElement.classList.contains("dark") ? "vs-dark" : "light"}
                  options={{ readOnly: true, domReadOnly: true, automaticLayout: true, minimap: { enabled: false }, wordWrap: "on", scrollBeyondLastLine: false, fontSize: 12 }}
                />
              ) : (
                <FilePreview file={pane.selectedFile} />
              )
            ) : (
              <EmptyContent tab={pane.activeTab} />
            )}
          </div>
        </section>
      </div>
    </aside>
  );
}
