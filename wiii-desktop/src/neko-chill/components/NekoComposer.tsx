/**
 * Prompt composer — waku-fidelity card (#893, task #12): rounded-13 card on
 * the composer surface, 11.5px control chips row, 26px circular submit.
 * Enter gửi, Shift+Enter xuống dòng; Dừng thay chỗ nút gửi khi streaming.
 */
import { useState } from "react";
import { ArrowUp, Square } from "lucide-react";

interface NekoComposerProps {
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
  /** Chip label: agent đang phục vụ phiên (waku: provider/model chips). */
  agentLabel?: string;
}

export function NekoComposer({
  disabled,
  streaming,
  onSend,
  onCancel,
  agentLabel,
}: NekoComposerProps) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const text = draft.trim();
    if (!text || disabled || streaming) return;
    setDraft("");
    onSend(text);
  };

  return (
    <div className="shrink-0 px-5 pb-4">
      <div className="mx-auto w-full max-w-[720px] rounded-[13px] border border-[var(--nk-border)] bg-[var(--nk-composer)] p-2.5">
        <textarea
          className="max-h-40 min-h-[40px] w-full resize-none bg-transparent px-1 pt-0.5 text-[13.5px] leading-[20px] text-[var(--nk-text)] placeholder:text-[var(--nk-ghost)] focus:outline-none"
          rows={Math.min(draft.split("\n").length || 1, 5)}
          placeholder="Nhắn cho agent…"
          value={draft}
          disabled={disabled}
          data-testid="neko-composer-input"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="mt-2 flex items-center gap-1 text-[11.5px] leading-[14px]">
          {agentLabel ? (
            <span className="rounded px-1.5 py-0.5 text-[var(--nk-text-3)]">
              {agentLabel}
            </span>
          ) : null}
          <span className="rounded px-1.5 py-0.5 text-[var(--nk-ghost)]">
            Enter gửi · Shift+Enter xuống dòng
          </span>
          <div className="flex-1" />
          {streaming ? (
            <button
              type="button"
              className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-[var(--nk-danger-soft)] text-[var(--nk-danger)] transition-colors hover:bg-[var(--nk-danger)] hover:text-[var(--nk-on-inverse)]"
              onClick={onCancel}
              title="Dừng"
              data-testid="neko-cancel"
            >
              <Square aria-hidden="true" className="h-2.5 w-2.5 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-[var(--nk-inverse)] text-[var(--nk-on-inverse)] disabled:opacity-35 transition-opacity"
              disabled={disabled || !draft.trim()}
              onClick={submit}
              title="Gửi"
              data-testid="neko-send"
            >
              <ArrowUp aria-hidden="true" className="h-3 w-3" strokeWidth={1.8} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
