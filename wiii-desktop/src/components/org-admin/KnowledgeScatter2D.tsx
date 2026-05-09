/**
 * KnowledgeScatter2D — Sprint 191: "Mắt Tri Thức"
 *
 * Recharts-based 2D scatter plot showing embedding clusters.
 * One <Scatter> per document, colored by doc color.
 * Controls: PCA/t-SNE toggle, limit slider.
 */
import { useCallback, useState } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Loader2, AlertCircle, PlayCircle } from "lucide-react";
import { getKnowledgeScatter } from "@/api/admin";
import type {
  ScatterResponse,
  ScatterDocument,
  ScatterPoint,
} from "@/api/types";

interface Props {
  orgId: string;
}

export function KnowledgeScatter2D({ orgId }: Props) {
  const [data, setData] = useState<ScatterResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [method, setMethod] = useState<"pca" | "tsne">("pca");
  const [limit, setLimit] = useState(500);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getKnowledgeScatter(orgId, {
        method,
        dimensions: 2,
        limit,
      });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  }, [orgId, method, limit]);

  const controls = (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3 text-xs sm:flex-row sm:flex-wrap sm:items-center">
      <div className="flex items-center gap-2">
        <span className="text-text-secondary">Phương pháp:</span>
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value as "pca" | "tsne")}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-xs text-text"
        >
          <option value="pca">PCA</option>
          <option value="tsne">t-SNE</option>
        </select>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-text-secondary">Giới hạn:</span>
        <input
          type="range"
          min={100}
          max={1000}
          step={100}
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="w-28"
        />
        <span className="w-8 text-text-tertiary">{limit}</span>
      </div>
      {data && (
        <span className="text-text-tertiary sm:ml-auto">
          {data.points.length} điểm | {data.computation_ms}ms | {data.method}
        </span>
      )}
      <button
        type="button"
        onClick={fetchData}
        disabled={loading}
        className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 sm:ml-auto"
      >
        {loading ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <PlayCircle size={14} />
        )}
        {data ? "Cập nhật" : "Tạo biểu đồ"}
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-3">
        {controls}
        <div className="flex items-center justify-center rounded-xl border border-border bg-surface/70 py-12 text-text-secondary">
          <Loader2 size={20} className="mr-2 animate-spin" />
          Đang tính PCA/t-SNE cho các phân đoạn tài liệu...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        {controls}
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-8 text-center text-sm text-red-600 dark:border-red-900/60 dark:bg-red-950/20">
          <div className="flex items-center gap-2">
            <AlertCircle size={16} />
            {error}
          </div>
          <p className="max-w-lg text-xs text-red-500/80">
            Nếu tập tài liệu lớn, hãy giảm giới hạn điểm hoặc thử PCA trước
            t-SNE.
          </p>
        </div>
      </div>
    );
  }

  if (!data || data.points.length === 0) {
    return (
      <div className="space-y-3">
        {controls}
        <div className="rounded-xl border border-dashed border-border bg-surface/60 px-4 py-8 text-center">
          <PlayCircle
            size={28}
            className="mx-auto mb-3 text-text-tertiary opacity-60"
          />
          <p className="text-sm font-medium text-text">Chưa chạy biểu đồ 2D.</p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-text-secondary">
            Bấm tạo biểu đồ khi bạn thật sự muốn xem không gian embedding. Cách
            này giúp tab Tri thức mở nhanh, không tự phát sinh yêu cầu tính toán
            nặng.
          </p>
          <button
            type="button"
            onClick={fetchData}
            className="mt-4 inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90"
          >
            <PlayCircle size={14} />
            Tạo biểu đồ 2D
          </button>
        </div>
      </div>
    );
  }

  // Group points by document
  const grouped = new Map<
    string,
    { doc: ScatterDocument; points: ScatterPoint[] }
  >();
  for (const doc of data.documents) {
    grouped.set(doc.id, { doc, points: [] });
  }
  for (const pt of data.points) {
    const entry = grouped.get(pt.document_id);
    if (entry) entry.points.push(pt);
  }

  return (
    <div className="space-y-3">
      {controls}

      {/* Chart */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <ResponsiveContainer width="100%" height={400}>
          <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis type="number" dataKey="x" name="X" tick={{ fontSize: 10 }} />
            <YAxis type="number" dataKey="y" name="Y" tick={{ fontSize: 10 }} />
            <Tooltip
              content={({ payload }) => {
                if (!payload || payload.length === 0) return null;
                const pt = payload[0].payload as ScatterPoint;
                return (
                  <div className="rounded-lg border border-border bg-surface p-2 shadow-lg max-w-xs">
                    <p className="text-xs font-medium text-text truncate">
                      {pt.document_name}
                    </p>
                    {pt.page_number != null && (
                      <p className="text-xs text-text-tertiary">
                        Trang {pt.page_number}
                      </p>
                    )}
                    <p className="text-xs text-text-secondary mt-1 line-clamp-3">
                      {pt.content_preview}
                    </p>
                  </div>
                );
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: 11 }}
              formatter={(value: string) => (
                <span className="text-text-secondary text-xs">{value}</span>
              )}
            />
            {Array.from(grouped.values()).map(({ doc, points }) => (
              <Scatter
                key={doc.id}
                name={doc.name}
                data={points}
                fill={doc.color}
                opacity={0.7}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
