/**
 * ExcelArtifact - table-first preview for generated spreadsheet artifacts.
 *
 * If the backend provides tabular JSON, render it inline.
 * If only the binary file is available, show a clear download action.
 */
import { useState, useMemo, useCallback } from "react";
import { ArrowUpDown, Download, FileSpreadsheet } from "lucide-react";
import type { ArtifactData } from "@/api/types";
import { useSettingsStore } from "@/stores/settings-store";
import { resolveArtifactFileUrl } from "@/lib/artifact-file";

interface Props {
  artifact: ArtifactData;
  mode: "card" | "panel";
}

const MAX_CARD_ROWS = 8;
const PAGE_SIZE = 50;

export default function ExcelArtifact({ artifact, mode }: Props) {
  const serverUrl = useSettingsStore((s) => s.settings.server_url);
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const fileUrl = resolveArtifactFileUrl(artifact, serverUrl);

  const { rows, columns } = useMemo(() => {
    try {
      const parsed = JSON.parse(artifact.content);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return {
          rows: parsed as Record<string, unknown>[],
          columns: Object.keys(parsed[0]),
        };
      }
    } catch {
      // Binary-only workbook: no inline JSON payload.
    }
    return { rows: [] as Record<string, unknown>[], columns: [] as string[] };
  }, [artifact.content]);

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sortColumn];
      const vb = b[sortColumn];
      if (typeof va === "number" && typeof vb === "number") {
        return sortDir === "asc" ? va - vb : vb - va;
      }
      const cmp = String(va ?? "").localeCompare(String(vb ?? ""), undefined, {
        numeric: true,
      });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortColumn, sortDir]);

  const totalPages = Math.ceil(sortedRows.length / PAGE_SIZE);
  const displayRows =
    mode === "card"
      ? sortedRows.slice(0, MAX_CARD_ROWS)
      : sortedRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const handleSort = useCallback((col: string) => {
    setSortColumn((prev) => {
      if (prev === col) {
        setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
        return col;
      }
      setSortDir("asc");
      return col;
    });
  }, []);

  const handleCsvDownload = useCallback(() => {
    if (rows.length === 0 || columns.length === 0) return;
    const header = columns.join(",");
    const csvRows = rows.map((row) =>
      columns
        .map((column) => `"${String(row[column] ?? "").replace(/"/g, '""')}"`)
        .join(","),
    );
    const csv = [header, ...csvRows].join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${artifact.title || "data"}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [rows, columns, artifact.title]);

  if (rows.length === 0) {
    return (
      <div className="p-4">
        <div className="rounded-2xl border border-border bg-surface-secondary p-4 flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
            <FileSpreadsheet size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-text">
              {artifact.title}
            </div>
            <div className="text-xs text-text-tertiary mt-1">
              Bảng tính đã tạo xong. Bạn có thể tải file .xlsx để xem đầy đủ.
            </div>
          </div>
          {fileUrl && (
            <a
              href={fileUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-surface-tertiary hover:bg-border text-text-secondary hover:text-text transition-colors text-xs shrink-0"
            >
              <Download size={14} />
              Tải XLSX
            </a>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        className={`flex items-center justify-between ${mode === "panel" ? "px-4 pt-2" : "px-4 pt-4"}`}
      >
        <span className="text-xs text-text-tertiary">
          {rows.length} hàng x {columns.length} cột
        </span>
        <div className="flex items-center gap-2">
          {fileUrl && (
            <a
              href={fileUrl}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-xs text-text-secondary hover:text-text px-2.5 py-1.5 rounded-lg bg-surface-tertiary hover:bg-border transition-colors"
            >
              <Download size={12} />
              Tải XLSX
            </a>
          )}
          {mode === "panel" && (
            <button
              onClick={handleCsvDownload}
              className="flex items-center gap-1 text-xs text-text-secondary hover:text-text px-2.5 py-1.5 rounded-lg bg-surface-tertiary hover:bg-border transition-colors"
            >
              <Download size={12} />
              Tải CSV
            </button>
          )}
        </div>
      </div>

      <div
        className={`overflow-auto ${mode === "panel" ? "px-4 pb-4" : "px-4 pb-3"}`}
      >
        <table className="w-full text-xs">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  onClick={() => handleSort(col)}
                  className="sticky top-0 bg-surface-tertiary px-3 py-2 text-left text-text-secondary font-medium cursor-pointer hover:bg-border/50 transition-colors whitespace-nowrap"
                >
                  <span className="flex items-center gap-1">
                    {col}
                    <ArrowUpDown size={10} className="text-text-tertiary" />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, idx) => (
              <tr
                key={idx}
                className="border-t border-border/50 hover:bg-surface-secondary transition-colors"
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className="px-3 py-1.5 text-text whitespace-nowrap"
                  >
                    {String(row[col] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mode === "panel" && totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 py-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 text-xs rounded bg-surface-tertiary disabled:opacity-50 hover:bg-border transition-colors"
          >
            Trước
          </button>
          <span className="text-xs text-text-tertiary">
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 text-xs rounded bg-surface-tertiary disabled:opacity-50 hover:bg-border transition-colors"
          >
            Sau
          </button>
        </div>
      )}

      {mode === "card" && rows.length > MAX_CARD_ROWS && (
        <div className="text-center text-[10px] text-text-tertiary pb-3">
          +{rows.length - MAX_CARD_ROWS} hàng khác
        </div>
      )}
    </div>
  );
}
