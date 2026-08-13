/**
 * Prompt composer (T303, FR-007). Enter gửi, Shift+Enter xuống dòng;
 * nút Dừng hiện trong lúc streaming và gọi session/cancel qua driver.
 */
import { useState } from "react";

interface NekoComposerProps {
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function NekoComposer({ disabled, streaming, onSend, onCancel }: NekoComposerProps) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const text = draft.trim();
    if (!text || disabled || streaming) return;
    setDraft("");
    onSend(text);
  };

  return (
    <div className="border-t border-border px-6 py-4">
      <div className="flex items-end gap-2">
        <textarea
          className="flex-1 resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-border min-h-[44px] max-h-40"
          rows={draft.split("\n").length > 4 ? 4 : draft.split("\n").length || 1}
          placeholder="Nhắn cho agent… (Enter để gửi, Shift+Enter xuống dòng)"
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
        {streaming ? (
          <button
            type="button"
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-surface-hover transition-colors"
            onClick={onCancel}
            data-testid="neko-cancel"
          >
            Dừng
          </button>
        ) : (
          <button
            type="button"
            className="rounded-lg bg-text-primary text-surface px-4 py-2 text-sm font-medium disabled:opacity-40 transition-opacity"
            disabled={disabled || !draft.trim()}
            onClick={submit}
            data-testid="neko-send"
          >
            Gửi
          </button>
        )}
      </div>
    </div>
  );
}
