/**
 * KnowledgeGraph — Sprint 191: "Mắt Tri Thức"
 *
 * Knowledge graph visualization using Mermaid diagrams.
 * Shows document→chunk relationships and cross-doc similarity.
 */
import { useCallback, useState } from "react";
import {
  Loader2,
  AlertCircle,
  FileText,
  Link2,
  PlayCircle,
} from "lucide-react";
import MermaidDiagram from "@/components/common/MermaidDiagram";
import { getKnowledgeGraph } from "@/api/admin";
import type { KnowledgeGraphResponse } from "@/api/types";

interface Props {
  orgId: string;
}

export function KnowledgeGraph({ orgId }: Props) {
  const [data, setData] = useState<KnowledgeGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maxNodes, setMaxNodes] = useState(50);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getKnowledgeGraph(orgId, { max_nodes: maxNodes });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  }, [orgId, maxNodes]);

  const controls = (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3 text-xs sm:flex-row sm:flex-wrap sm:items-center">
      <div className="flex items-center gap-2">
        <span className="text-text-secondary">Max nodes:</span>
        <input
          type="range"
          min={10}
          max={100}
          step={10}
          value={maxNodes}
          onChange={(e) => setMaxNodes(Number(e.target.value))}
          className="w-28"
        />
        <span className="w-8 text-text-tertiary">{maxNodes}</span>
      </div>
      {data && (
        <span className="text-text-tertiary sm:ml-auto">
          {data.computation_ms}ms
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
        {data ? "Cập nhật" : "Tạo đồ thị"}
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-3">
        {controls}
        <div className="flex items-center justify-center rounded-xl border border-border bg-surface/70 py-12 text-text-secondary">
          <Loader2 size={20} className="mr-2 animate-spin" />
          Đang dựng đồ thị tài liệu và chunk...
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
            Thử giảm số node tối đa để đồ thị nhẹ hơn và dễ đọc hơn.
          </p>
        </div>
      </div>
    );
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="space-y-3">
        {controls}
        <div className="rounded-xl border border-dashed border-border bg-surface/60 px-4 py-8 text-center">
          <PlayCircle
            size={28}
            className="mx-auto mb-3 text-text-tertiary opacity-60"
          />
          <p className="text-sm font-medium text-text">
            Chưa dựng đồ thị tri thức.
          </p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-text-secondary">
            Bấm tạo đồ thị để xem quan hệ tài liệu, chunk và các cạnh tương
            đồng. Wiii giữ bước này thủ công để bạn kiểm soát chi phí tính toán
            và độ rối của sơ đồ.
          </p>
          <button
            type="button"
            onClick={fetchData}
            className="mt-4 inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90"
          >
            <PlayCircle size={14} />
            Tạo đồ thị
          </button>
        </div>
      </div>
    );
  }

  const docCount = data.nodes.filter((n) => n.node_type === "document").length;
  const chunkCount = data.nodes.filter((n) => n.node_type === "chunk").length;
  const containsEdges = data.edges.filter(
    (e) => e.edge_type === "contains",
  ).length;
  const similarEdges = data.edges.filter(
    (e) => e.edge_type === "similar_to",
  ).length;

  return (
    <div className="space-y-3">
      {controls}

      {/* Stats bar */}
      <div className="flex items-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400">
          <FileText size={12} />
          {docCount} tài liệu
        </span>
        <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
          <FileText size={12} />
          {chunkCount} chunk
        </span>
        <span className="inline-flex items-center gap-1 text-text-secondary">
          <Link2 size={12} />
          {containsEdges} chứa
        </span>
        {similarEdges > 0 && (
          <span className="inline-flex items-center gap-1 text-violet-600 dark:text-violet-400">
            <Link2 size={12} />
            {similarEdges} tương tự
          </span>
        )}
      </div>

      {/* Mermaid diagram */}
      <div className="rounded-xl border border-border bg-surface p-4 overflow-x-auto">
        <MermaidDiagram code={data.mermaid_code} />
      </div>
    </div>
  );
}
