/**
 * Neko Chill transcript (T303, FR-005) — renders the session's messages from
 * the ContentBlock vocabulary using the shared markdown stack. Deliberately a
 * thin list; virtualization for very long transcripts is a follow-up noted in
 * the spec's edge cases.
 */
import { useEffect, useRef } from "react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { ContentBlock } from "@/api/types";
import type { NekoSession } from "../stores/neko-session-store";
import { PermissionCard } from "./PermissionCard";

function Block({ block }: { block: ContentBlock }) {
  switch (block.type) {
    case "thinking":
      return (
        <div className="border-l-2 border-border pl-3 my-2 text-sm text-text-tertiary whitespace-pre-wrap">
          {block.content}
        </div>
      );
    case "tool_execution":
      return (
        <div className="flex items-center gap-2 my-1.5 text-sm" data-testid="tool-strip">
          <span
            className={
              block.status === "pending"
                ? "inline-block h-2 w-2 rounded-full bg-amber-400 animate-pulse"
                : "inline-block h-2 w-2 rounded-full bg-green-500"
            }
          />
          <span className="font-medium">{block.tool.name}</span>
          {block.tool.result ? (
            <span className="text-text-tertiary truncate max-w-[24rem]">
              — {block.tool.result}
            </span>
          ) : null}
        </div>
      );
    case "answer":
      return <MarkdownRenderer content={block.content} className="my-2" />;
    default:
      // Cloud-only block kinds (visual, artifact, …) never arrive from the
      // local drivers in v0.
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

  // Follow the stream (v0: always stick to bottom while content grows).
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messageCount, lastBlockCount, session.pendingPermission]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4" data-testid="neko-transcript">
      {session.messages.map((message) =>
        message.role === "user" ? (
          <div key={message.id} className="flex justify-end my-3">
            <div className="max-w-[80%] rounded-2xl bg-surface-secondary px-4 py-2.5 text-sm whitespace-pre-wrap">
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
        <p className="text-sm text-text-tertiary animate-pulse my-2">
          {session.agentName} đang làm việc…
        </p>
      ) : null}
      {session.status === "exited" || session.status === "error" ? (
        <p className="text-sm text-red-500 my-2">{session.statusDetail}</p>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}
