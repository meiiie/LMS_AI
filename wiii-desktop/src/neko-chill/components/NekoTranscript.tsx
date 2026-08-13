/**
 * Neko Chill transcript — workspace-shell styling (#904): 780px
 * centered column, quiet thinking rail, dot-status tool rows, shared
 * MarkdownRenderer for answers. Virtualization: follow-up #891.
 */
import { useEffect, useRef } from "react";
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
}

export function NekoTranscript({ session, onResolvePermission }: NekoTranscriptProps) {
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
