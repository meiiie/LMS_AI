/**
 * Inline permission gate (FR-006) — waku-fidelity card: quiet raised surface,
 * reject stays the prominent default (fail-closed by design), allow is
 * the bordered secondary.
 */
import type { PermissionRequest } from "../drivers/types";

interface PermissionCardProps {
  request: PermissionRequest;
  onResolve: (optionId: string | null) => void;
  resolving?: boolean;
}

export function PermissionCard({ request, onResolve, resolving = false }: PermissionCardProps) {
  const allows = request.options.filter((o) => o.kind.startsWith("allow"));
  const rejects = request.options.filter((o) => !o.kind.startsWith("allow"));

  return (
    <div
      className="my-2 rounded-[10px] border border-[var(--nk-border-strong)] bg-[var(--nk-raised)] px-4 py-3"
      data-testid="permission-card"
      aria-busy={resolving}
    >
      <p className="text-[11.5px] font-medium uppercase tracking-wide text-[var(--nk-warning)]">
        Agent xin phép
      </p>
      <p className="mb-3 mt-1 text-[13px] text-[var(--nk-text)]">{request.title}</p>
      <div className="flex flex-wrap gap-1.5">
        {rejects.map((option) => (
          <button
            key={option.optionId}
            type="button"
            className="rounded-lg bg-[var(--nk-inverse)] px-3 py-1.5 text-[12px] font-medium text-[var(--nk-on-inverse)] transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-50"
            disabled={resolving}
            onClick={() => onResolve(option.optionId)}
          >
            {option.label}
          </button>
        ))}
        {allows.map((option) => (
          <button
            key={option.optionId}
            type="button"
            className="rounded-lg border border-[var(--nk-border-strong)] px-3 py-1.5 text-[12px] text-[var(--nk-text-2)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)] disabled:cursor-wait disabled:opacity-50"
            disabled={resolving}
            onClick={() => onResolve(option.optionId)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {resolving ? (
        <p
          className="mt-2 text-[11px] text-[var(--nk-text-3)]"
          role="status"
          aria-live="polite"
        >
          Đang lưu quyết định…
        </p>
      ) : null}
    </div>
  );
}
