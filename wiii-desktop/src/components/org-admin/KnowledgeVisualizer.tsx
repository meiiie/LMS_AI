/**
 * KnowledgeVisualizer — Sprint 191: "Mắt Tri Thức"
 *
 * Container with 4 sub-tabs: 2D Scatter | 3D Scatter | Đồ thị | RAG Flow.
 * Renders below the document list in OrgManagerKnowledge.
 */
import { useState } from "react";
import { ScatterChart, Network, GitBranch, Search, Eye } from "lucide-react";
import { KnowledgeScatter2D } from "./KnowledgeScatter2D";
import { KnowledgeScatter3D } from "./KnowledgeScatter3D";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { RagFlowVisualizer } from "./RagFlowVisualizer";

type VizTab = "scatter2d" | "scatter3d" | "graph" | "ragflow";

const TABS: { id: VizTab; label: string; icon: React.ReactNode }[] = [
  { id: "scatter2d", label: "2D Scatter", icon: <ScatterChart size={14} /> },
  { id: "scatter3d", label: "3D Scatter", icon: <ScatterChart size={14} /> },
  { id: "graph", label: "Đồ thị", icon: <Network size={14} /> },
  { id: "ragflow", label: "RAG Flow", icon: <Search size={14} /> },
];

interface KnowledgeVisualizerProps {
  orgId: string;
  hasDocuments: boolean;
}

export function KnowledgeVisualizer({
  orgId,
  hasDocuments,
}: KnowledgeVisualizerProps) {
  const [activeTab, setActiveTab] = useState<VizTab>("scatter2d");

  if (!hasDocuments) {
    return (
      <div className="mt-6 rounded-xl border border-border bg-surface p-6 text-center">
        <GitBranch
          size={32}
          className="mx-auto mb-2 text-text-tertiary opacity-50"
        />
        <p className="text-sm text-text-tertiary">
          Tải lên tài liệu trước để xem trực quan hóa
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6">
      <div className="mb-4 rounded-xl border border-border bg-surface/70 p-4">
        <div className="flex items-start gap-3">
          <Eye size={18} className="mt-0.5 shrink-0 text-[var(--accent)]" />
          <div>
            <p className="text-sm font-medium text-text">
              Mắt tri thức đã sẵn sàng.
            </p>
            <p className="mt-1 text-xs leading-5 text-text-secondary">
              Wiii sẽ không tự chạy PCA/t-SNE hay đồ thị khi bạn chỉ mở tab.
              Chọn kiểu nhìn, chỉnh tham số nếu cần, rồi bấm tạo biểu đồ để
              tránh treo UI trên tập tài liệu lớn.
            </p>
          </div>
        </div>
      </div>

      {/* Sub-tab bar */}
      <div
        className="mb-4 flex items-center gap-1 overflow-x-auto border-b border-border"
        role="tablist"
        aria-label="Trực quan hóa tri thức"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? "border-[var(--accent)] text-[var(--accent)]"
                : "border-transparent text-text-secondary hover:text-text hover:border-border"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="min-h-[300px]">
        {activeTab === "scatter2d" && <KnowledgeScatter2D orgId={orgId} />}
        {activeTab === "scatter3d" && <KnowledgeScatter3D orgId={orgId} />}
        {activeTab === "graph" && <KnowledgeGraph orgId={orgId} />}
        {activeTab === "ragflow" && <RagFlowVisualizer orgId={orgId} />}
      </div>
    </div>
  );
}
