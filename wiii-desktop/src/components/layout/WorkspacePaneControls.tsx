import { Pin, Radio } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";

export function WorkspacePaneControls() {
  const follow = useUIStore((state) => state.workspaceFollowAgent);
  const pinned = useUIStore((state) => state.workspacePinned);
  const setFollow = useUIStore((state) => state.setWorkspaceFollowAgent);
  const setPinned = useUIStore((state) => state.setWorkspacePinned);

  return (
    <div className="flex items-center gap-0.5" aria-label="Điều khiển Workspace">
      <button
        type="button"
        aria-label="Theo nội dung agent đang tạo"
        aria-pressed={follow}
        title="Follow agent"
        className={`grid h-7 w-7 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/30 ${follow ? "bg-surface-tertiary text-[var(--accent)]" : "text-text-tertiary hover:bg-surface-tertiary hover:text-text"}`}
        onClick={() => setFollow(!follow)}
      >
        <Radio aria-hidden="true" size={14} />
      </button>
      <button
        type="button"
        aria-label="Ghim nội dung hiện tại"
        aria-pressed={pinned}
        title="Pin current surface"
        className={`grid h-7 w-7 place-items-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/30 ${pinned ? "bg-surface-tertiary text-[var(--accent)]" : "text-text-tertiary hover:bg-surface-tertiary hover:text-text"}`}
        onClick={() => setPinned(!pinned)}
      >
        <Pin aria-hidden="true" size={14} />
      </button>
    </div>
  );
}
