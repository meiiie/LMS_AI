/**
 * Inline permission gate (FR-006). Minimal v0 pulled forward from Phase 4 so
 * an agent approval request can never hang a turn without a visible surface.
 * Reject stays visually primary — fail-closed by design.
 */
import type { PermissionRequest } from "../drivers/types";

interface PermissionCardProps {
  request: PermissionRequest;
  onResolve: (optionId: string | null) => void;
}

export function PermissionCard({ request, onResolve }: PermissionCardProps) {
  const allows = request.options.filter((o) => o.kind.startsWith("allow"));
  const rejects = request.options.filter((o) => !o.kind.startsWith("allow"));

  return (
    <div
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-4 py-3 my-2"
      data-testid="permission-card"
    >
      <p className="text-sm font-medium mb-1">Agent xin phép</p>
      <p className="text-sm text-text-secondary mb-3">{request.title}</p>
      <div className="flex flex-wrap gap-2">
        {rejects.map((option) => (
          <button
            key={option.optionId}
            type="button"
            className="text-sm rounded-md border border-border px-3 py-1.5 font-medium hover:bg-surface-hover transition-colors"
            onClick={() => onResolve(option.optionId)}
          >
            {option.label}
          </button>
        ))}
        {allows.map((option) => (
          <button
            key={option.optionId}
            type="button"
            className="text-sm rounded-md border border-amber-500/50 text-amber-600 px-3 py-1.5 hover:bg-amber-500/10 transition-colors"
            onClick={() => onResolve(option.optionId)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
