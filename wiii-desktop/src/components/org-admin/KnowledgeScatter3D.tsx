/**
 * KnowledgeScatter3D — Sprint 191: "Mắt Tri Thức"
 *
 * Plotly 3D scatter showing embedding clusters with interactive rotation.
 * Lazy-loaded to avoid bundle bloat.
 */
import { lazy, Suspense, useCallback, useState } from "react";
import type { ComponentType } from "react";
import { Loader2, AlertCircle, PlayCircle } from "lucide-react";
import { getKnowledgeScatter } from "@/api/admin";
import type {
  ScatterResponse,
  ScatterDocument,
  ScatterPoint,
} from "@/api/types";

// Lazy-load Plotly (1.5MB gl3d-dist-min)
const Plot = lazy(async () => {
  const [plotlyMod, factoryMod] = await Promise.all([
    import("plotly.js-gl3d-dist-min" as string),
    import("react-plotly.js/factory" as string),
  ]);
  const Plotly = plotlyMod.default || plotlyMod;
  const createPlotlyComponent = factoryMod.default || factoryMod;
  const PlotComponent = createPlotlyComponent(Plotly) as ComponentType<any>;
  return { default: PlotComponent };
});

interface Props {
  orgId: string;
}

export function KnowledgeScatter3D({ orgId }: Props) {
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
        dimensions: 3,
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
          Đang dựng không gian 3D cho các phân đoạn tài liệu...
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
            3D cần tải thêm thư viện và dữ liệu nhiều hơn. Nếu chậm, hãy giảm
            giới hạn hoặc dùng 2D trước.
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
          <p className="text-sm font-medium text-text">Chưa chạy biểu đồ 3D.</p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-text-secondary">
            Bấm tạo biểu đồ khi cần xoay và quan sát cụm embedding theo không
            gian 3 chiều. Wiii sẽ không tải Plotly hay gọi API nặng trước khi
            bạn yêu cầu.
          </p>
          <button
            type="button"
            onClick={fetchData}
            className="mt-4 inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90"
          >
            <PlayCircle size={14} />
            Tạo biểu đồ 3D
          </button>
        </div>
      </div>
    );
  }

  // Group by document for traces
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

  const traces = Array.from(grouped.values()).map(({ doc, points }) => ({
    type: "scatter3d" as const,
    mode: "markers" as const,
    name: doc.name,
    x: points.map((p) => p.x),
    y: points.map((p) => p.y),
    z: points.map((p) => p.z ?? 0),
    text: points.map(
      (p) =>
        `${p.document_name}${p.page_number != null ? ` (tr.${p.page_number})` : ""}\n${p.content_preview}`,
    ),
    hoverinfo: "text" as const,
    marker: {
      size: 4,
      color: doc.color,
      opacity: 0.7,
    },
  }));

  const isDark =
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark");

  const layout = {
    autosize: true,
    height: 450,
    margin: { l: 0, r: 0, t: 30, b: 0 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: isDark ? "#94a3b8" : "#475569", size: 10 },
    scene: {
      xaxis: { showgrid: true, gridcolor: isDark ? "#334155" : "#e2e8f0" },
      yaxis: { showgrid: true, gridcolor: isDark ? "#334155" : "#e2e8f0" },
      zaxis: { showgrid: true, gridcolor: isDark ? "#334155" : "#e2e8f0" },
    },
    legend: { font: { size: 10 } },
  };

  return (
    <div className="space-y-3">
      {controls}

      {/* 3D Chart */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <Suspense
          fallback={
            <div className="flex items-center justify-center py-12 text-text-secondary">
              <Loader2 size={20} className="animate-spin mr-2" />
              Đang tải thư viện 3D...
            </div>
          }
        >
          <Plot
            data={traces}
            layout={layout}
            config={{
              responsive: true,
              displayModeBar: true,
              displaylogo: false,
            }}
            style={{ width: "100%", height: 450 }}
          />
        </Suspense>
      </div>
    </div>
  );
}
