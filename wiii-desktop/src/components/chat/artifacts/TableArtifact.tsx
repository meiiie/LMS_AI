import { useState, useMemo } from "react";
import { ArrowUpDown, Download, Table2 } from "lucide-react";
import type { ArtifactData } from "@/api/types";
import { useSettingsStore } from "@/stores/settings-store";
import { resolveArtifactFileUrl } from "@/lib/artifact-file";

interface Props {
  artifact: ArtifactData;
  mode: "card" | "panel";
}

const MAX_CARD_ROWS = 5;

export default function TableArtifact({ artifact, mode }: Props) {
  const serverUrl = useSettingsStore((s) => s.settings.server_url);
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const fileUrl = resolveArtifactFileUrl(artifact, serverUrl);

  const rows = useMemo<Record<string, unknown>[]>(() => {
    try {
      const parsed = JSON.parse(artifact.content);
      if (Array.isArray(parsed)) return parsed;
      if (
        artifact.metadata?.table_data &&
        Array.isArray(artifact.metadata.table_data)
      ) {
        return artifact.metadata.table_data as Record<string, unknown>[];
      }
      return [];
    } catch {
      return [];
    }
  }, [artifact.content, artifact.metadata?.table_data]);

  const columns = useMemo(() => {
    if (rows.length === 0) return [];
    return Object.keys(rows[0]);
  }, [rows]);

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sortColumn];
      const vb = b[sortColumn];
      const cmp = String(va ?? "").localeCompare(String(vb ?? ""), undefined, {
        numeric: true,
      });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortColumn, sortDir]);

  const displayRows =
    mode === "card" ? sortedRows.slice(0, MAX_CARD_ROWS) : sortedRows;

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDir((direction) => (direction === "asc" ? "desc" : "asc"));
      return;
    }
    setSortColumn(column);
    setSortDir("asc");
  };

  if (rows.length === 0) {
    return (
      <div className="p-4">
        <div className="rounded-2xl border border-border bg-surface-secondary p-4 flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center shrink-0">
            <Table2 size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-text">
              {artifact.title}
            </div>
            <div className="text-xs text-text-tertiary mt-1">
              Bảng dữ liệu đã được tạo. Mở tệp gốc để xem đầy đủ nếu cần.
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
              Mở tệp
            </a>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {mode === "panel" && fileUrl && (
        <div className="flex justify-end px-4 pt-2">
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-xs text-text-secondary hover:text-text px-2 py-1 rounded bg-surface-tertiary hover:bg-border transition-colors"
          >
            <Download size={12} />
            Mở tệp gốc
          </a>
        </div>
      )}

      <div
        className={
          mode === "card" ? "overflow-auto max-h-[200px]" : "overflow-auto"
        }
      >
        <table className="w-full text-xs">
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  onClick={() => handleSort(column)}
                  className="sticky top-0 bg-surface-tertiary px-3 py-2 text-left text-text-secondary font-medium cursor-pointer hover:bg-border/50 transition-colors"
                >
                  <span className="flex items-center gap-1">
                    {column}
                    <ArrowUpDown size={10} className="text-text-tertiary" />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, index) => (
              <tr
                key={index}
                className="border-t border-border/50 hover:bg-surface-secondary transition-colors"
              >
                {columns.map((column) => (
                  <td key={column} className="px-3 py-1.5 text-text">
                    {String(row[column] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {mode === "card" && rows.length > MAX_CARD_ROWS && (
          <div className="text-center text-[10px] text-text-tertiary py-1">
            +{rows.length - MAX_CARD_ROWS} hàng khác
          </div>
        )}
      </div>
    </div>
  );
}
