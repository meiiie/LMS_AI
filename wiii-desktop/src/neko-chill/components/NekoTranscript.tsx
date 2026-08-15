/**
 * Neko Chill transcript — workspace-shell styling (#904): 780px
 * centered column, quiet thinking rail, dot-status tool rows, shared
 * MarkdownRenderer for answers, with measured row virtualization for long sessions.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, BookOpen, Command, FolderGit2 } from "lucide-react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { ContentBlock } from "@/api/types";
import type { NekoSession } from "../stores/neko-session-store";
import { PermissionCard } from "./PermissionCard";

export const NEKO_TRANSCRIPT_VIRTUALIZATION_THRESHOLD = 50;

export function shouldVirtualizeTranscript(messageCount: number): boolean {
  return messageCount > NEKO_TRANSCRIPT_VIRTUALIZATION_THRESHOLD;
}

export function dispatchedKnowledgeContexts(session: NekoSession) {
  const dispatched = new Set(
    session.events.flatMap((event) =>
      event.data.type === "dispatch-invoked" && event.data.action === "knowledge"
        ? [event.data.targetEventId]
        : [],
    ),
  );
  return session.events.flatMap((event) =>
    event.eventId &&
    event.data.type === "knowledge-context" &&
    dispatched.has(event.eventId)
      ? [event.data]
      : [],
  );
}

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

function MessageRow({ message }: { message: NekoSession["messages"][number] }) {
  return message.role === "user" ? (
    <div className="my-3 flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-[var(--nk-raised)] px-3.5 py-2 text-[13.5px] leading-[20px] text-[var(--nk-text)]">
        {message.text}
      </div>
    </div>
  ) : (
    <div className="my-3">
      {(message.blocks ?? []).map((block) => (
        <Block key={block.id} block={block} />
      ))}
    </div>
  );
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [followingTail, setFollowingTail] = useState(true);
  const messageCount = session.messages.length;
  const lastMessage = session.messages[messageCount - 1];
  const lastBlockCount = lastMessage?.blocks?.length ?? 0;
  const useVirtual = shouldVirtualizeTranscript(messageCount);
  const knowledgeContexts = useMemo(
    () => dispatchedKnowledgeContexts(session),
    [session.events],
  );
  const virtualizer = useVirtualizer({
    count: messageCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: useCallback(
      (index: number) => (session.messages[index]?.role === "user" ? 64 : 180),
      [session.messages],
    ),
    overscan: 6,
    gap: 4,
    enabled: useVirtual,
  });

  const scrollToLatest = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      if (useVirtual && messageCount > 0) {
        virtualizer.scrollToIndex(messageCount - 1, { align: "end", behavior });
      } else if (typeof bottomRef.current?.scrollIntoView === "function") {
        bottomRef.current.scrollIntoView({ block: "end", behavior });
      }
    },
    [messageCount, useVirtual, virtualizer],
  );

  useEffect(() => {
    setFollowingTail(true);
  }, [session.id]);

  useEffect(() => {
    if (lastMessage?.role === "user") setFollowingTail(true);
  }, [lastMessage?.id, lastMessage?.role]);

  useEffect(() => {
    if (!followingTail) return;
    requestAnimationFrame(() => scrollToLatest());
  }, [followingTail, lastBlockCount, messageCount, scrollToLatest, session.pendingPermission]);

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        className="h-full overflow-y-auto"
        data-testid="neko-transcript"
        role="log"
        aria-label="Lịch sử phiên Neko Chill"
        aria-live={session.status === "streaming" ? "off" : "polite"}
        onScroll={(event) => {
          const viewport = event.currentTarget;
          const distanceFromTail =
            viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
          setFollowingTail(distanceFromTail < 96);
        }}
      >
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
        {useVirtual ? (
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((row) => {
              const message = session.messages[row.index];
              return (
                <div
                  key={message.id}
                  ref={virtualizer.measureElement}
                  data-index={row.index}
                  className="absolute left-0 top-0 w-full"
                  style={{ transform: `translateY(${row.start}px)` }}
                >
                  <MessageRow message={message} />
                </div>
              );
            })}
          </div>
        ) : (
          session.messages.map((message) => <MessageRow key={message.id} message={message} />)
        )}
        {knowledgeContexts.map((context) => (
          <details
            key={context.contextId}
            className="my-2 rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] px-3 py-2"
            data-testid="knowledge-evidence"
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[11.5px] font-medium text-[var(--nk-text-2)]">
              <BookOpen aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-accent)]" />
              Wiii Knowledge · {context.sources.length} nguồn đã đưa vào model
            </summary>
            <ol className="mt-2 space-y-1 border-t border-[var(--nk-border)] pt-2 text-[10.5px] text-[var(--nk-text-3)]">
              {context.sources.map((source, index) => (
                <li key={source.sourceId} className="flex gap-2">
                  <span className="tabular-nums text-[var(--nk-text-2)]">[{index + 1}]</span>
                  <span className="min-w-0 truncate">
                    {source.title}
                    {source.documentId ? ` · ${source.documentId}` : ""}
                    {source.pageNumber > 0 ? ` · trang ${source.pageNumber}` : ""}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        ))}
        {session.pendingPermission ? (
          <PermissionCard
            request={session.pendingPermission}
            resolving={session.resolvingPermissionId === session.pendingPermission.requestId}
            blockedByCancel={session.cancelPending}
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
      {!followingTail ? (
        <button
          type="button"
          className="absolute bottom-3 left-1/2 z-10 flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-full border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] px-3 text-[11px] font-medium text-[var(--nk-text-2)] shadow-sm transition-colors hover:bg-[var(--nk-raised)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--nk-focus-soft)]"
          onClick={() => {
            setFollowingTail(true);
            scrollToLatest("smooth");
          }}
          aria-label="Đi tới tin nhắn mới nhất"
        >
          <ArrowDown aria-hidden="true" className="h-3.5 w-3.5" />
          Mới nhất
        </button>
      ) : null}
    </div>
  );
}
