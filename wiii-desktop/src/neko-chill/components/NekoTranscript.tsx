/**
 * Neko Chill transcript — workspace-shell styling (#904): 780px
 * centered column, quiet thinking rail, dot-status tool rows, shared
 * MarkdownRenderer for answers. Virtualization: follow-up #891.
 */
import { useEffect, useRef } from "react";
import { Command, FolderGit2 } from "lucide-react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { ContentBlock } from "@/api/types";
import type { NekoSession } from "../stores/neko-session-store";
import { PermissionCard } from "./PermissionCard";

/** Remove one matching outer emphasis pair without interpreting reasoning as HTML. */
export function formatReasoningLabel(content: string): string {
  const trimmed = content.trim();
  for (const marker of ["**", "__", "*", "_"]) {
    if (
      trimmed.length > marker.length * 2 &&
      trimmed.startsWith(marker) &&
      trimmed.endsWith(marker)
    ) {
      return trimmed.slice(marker.length, -marker.length).trim();
    }
  }
  return trimmed;
}

function Block({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case "thinking":
      return (
        <div className="my-2 whitespace-pre-wrap border-l-2 border-[var(--nk-border-strong)] pl-3 text-[12.5px] leading-[19px] text-[var(--nk-text-3)]">
          {formatReasoningLabel(block.content)}
        </div>
      );
    case "tool_execution":
      return (
        <div className="my-1.5 flex items-center gap-2 text-[12.5px]" data-testid="tool-strip">
          <span
            className={
              block.status === "pending"
                ? "inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--nk-warning)] animate-pulse"
                : "inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--nk-success)]"
            }
          />
          <span className="font-medium text-[var(--nk-text-2)]">{block.tool.name}</span>
          {block.tool.result ? (
            <span className="truncate text-[var(--nk-text-3)]">— {block.tool.result}</span>
          ) : null}
        </div>
      );
    case "answer":
      return <MarkdownRenderer content={block.content} className="my-2 text-[13.5px]" />;
    default:
      // Cloud-only block kinds never arrive from local drivers in v0.
      return null;
  }
}

interface NekoTranscriptProps {
  session: NekoSession;
  onResolvePermission: (optionId: string | null) => void;
  onInsertPrompt: (text: string) => void;
}

const STARTER_PROMPTS = [
  {
    label: "Kiểm tra dự án này",
    prompt: "Kiểm tra dự án này và cho tôi biết điểm cần chú ý.",
  },
  {
    label: "Tóm tắt cấu trúc",
    prompt: "Tóm tắt cấu trúc dự án và đề xuất bước tiếp theo.",
  },
];

export function NekoTranscript({
  session,
  onResolvePermission,
  onInsertPrompt,
}: NekoTranscriptProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageCount = session.messages.length;
  const lastMessage = session.messages[messageCount - 1];
  const lastBlockCount = lastMessage?.blocks?.length ?? 0;

  useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ block: "end" });
    }
  }, [messageCount, lastBlockCount, session.pendingPermission]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto" data-testid="neko-transcript">
      <div className="mx-auto w-full max-w-[780px] px-6 py-4">
        {session.messages.length === 0 && session.status === "idle" ? (
          <section className="mx-auto flex max-w-[560px] flex-col items-center px-4 py-[10vh] text-center" aria-label="Bắt đầu phiên">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--nk-inset)] text-[var(--nk-text-2)]">
              <FolderGit2 aria-hidden="true" className="h-[18px] w-[18px]" />
            </span>
            <h2 className="mt-4 text-[18px] font-medium tracking-[-0.02em] text-[var(--nk-text)]">
              Sẵn sàng trong {session.workspace?.name ?? "dự án này"}
            </h2>
            <p className="mt-1.5 max-w-[460px] text-[12.5px] leading-5 text-[var(--nk-text-3)]">
              Agent chỉ làm việc trong thư mục đã chọn. Hãy mô tả kết quả bạn muốn;
              các gợi ý dưới đây chỉ được chèn vào ô soạn để bạn xem lại.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {STARTER_PROMPTS.map((starter) => (
                <button
                  key={starter.label}
                  type="button"
                  aria-label={`Chèn gợi ý ${starter.label}`}
                  className="rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] px-3 py-2 text-[12px] text-[var(--nk-text-2)] transition-colors hover:border-[var(--nk-border-strong)] hover:bg-[var(--nk-raised)] hover:text-[var(--nk-text)]"
                  onClick={() => onInsertPrompt(starter.prompt)}
                >
                  {starter.label}
                </button>
              ))}
            </div>
            <p className="mt-5 flex items-center gap-1.5 text-[10.5px] text-[var(--nk-ghost)]">
              <Command aria-hidden="true" className="h-3 w-3" />
              Gõ / để xem lệnh · Ctrl+K để tìm mọi phiên và lệnh
            </p>
          </section>
        ) : null}
        {session.messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="my-3 flex justify-end">
              <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-[var(--nk-raised)] px-3.5 py-2 text-[13.5px] leading-[20px] text-[var(--nk-text)]">
                {message.text}
              </div>
            </div>
          ) : (
            <div key={message.id} className="my-3">
              {(message.blocks ?? []).map((block) => (
                <Block key={block.id} block={block} />
              ))}
            </div>
          ),
        )}
        {session.pendingPermission ? (
          <PermissionCard
            request={session.pendingPermission}
            onResolve={onResolvePermission}
          />
        ) : null}
        {session.status === "streaming" && !session.pendingPermission ? (
          <p className="my-2 flex items-center gap-2 text-[12.5px] text-[var(--nk-text-3)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--nk-accent)] animate-pulse" />
            {session.agentName} đang làm việc…
          </p>
        ) : null}
        {session.status === "error" ? (
          <p className="my-2 text-[12.5px] text-[var(--nk-danger)]">{session.statusDetail}</p>
        ) : null}
        {session.status === "exited" && session.statusDetail ? (
          <p className="my-2 text-[12.5px] text-[var(--nk-text-3)]">{session.statusDetail}</p>
        ) : null}
        {session.status === "idle" && session.statusDetail ? (
          <p className="my-2 text-[12.5px] text-[var(--nk-warning)]">{session.statusDetail}</p>
        ) : null}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
