import { useState, useEffect, useCallback } from "react";
import { motion } from "motion/react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown } from "lucide-react";
import type { ContentBlock, Message } from "@/api/types";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useAvatarState } from "@/hooks/useAvatarState";
import { MessageBubble } from "./MessageBubble";
import {
  InterleavedBlockSequence,
  shouldRenderReasoningRail,
} from "./InterleavedBlockSequence";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import { SourceCitation } from "./SourceCitation";

const VIRTUALIZATION_THRESHOLD = 50;
const MESSAGE_GAP = 20;

function isHiddenTechnicalStreamingBlock(_block: ContentBlock) {
  return false;
}

function hasVisibleThinkingContent(block: ContentBlock) {
  if (block.type !== "thinking") return true;
  const content = typeof block.content === "string" ? block.content.trim() : "";
  const summary = "summary" in block && typeof block.summary === "string"
    ? block.summary.trim()
    : "";
  return Boolean(content || summary);
}

export function getVisibleStreamingBlocks(
  blocks: ContentBlock[],
  showThinking: boolean,
  thinkingLevel: string,
): ContentBlock[] {
  const includeThinking = shouldRenderReasoningRail(
    blocks,
    showThinking,
    thinkingLevel as import("@/api/types").ThinkingLevel,
  );
  return blocks.filter((block) => {
    if (!hasVisibleThinkingContent(block)) return false;
    return includeThinking || !["thinking", "action_text"].includes(block.type);
  });
}

export function hasRenderableStreamingBlocks(blocks: ContentBlock[]): boolean {
  return blocks.some((block) => hasVisibleThinkingContent(block) && !isHiddenTechnicalStreamingBlock(block));
}

export function shouldAutoFollowLatestMessage(message?: Pick<Message, "role"> | null): boolean {
  return message?.role === "user";
}

interface MessageListProps {
  messages: Message[];
  onSuggestedQuestion: (q: string) => void;
  onCancel?: () => void;
  onRegenerate?: () => void;
  onEditMessage?: (content: string) => void;
}

export function MessageList({
  messages,
  onSuggestedQuestion,
  onCancel: _onCancel,
  onRegenerate,
  onEditMessage,
}: MessageListProps) {
  const {
    isStreaming,
    streamingBlocks,
    streamingPhases,
    streamingSources,
    streamingContent,
    streamingStep,
    streamingStartTime,
  } = useChatStore();

  const { show_thinking, thinking_level } = useSettingsStore((s) => s.settings);
  const { state: avatarState, mood: avatarMood, soulEmotion } = useAvatarState();
  const visibleStreamingBlocks = getVisibleStreamingBlocks(streamingBlocks, show_thinking, thinking_level);
  const shouldHideTimer = hasRenderableStreamingBlocks(visibleStreamingBlocks) || Boolean(streamingContent);
  const scrollDependency = isStreaming
    ? `${messages.length}:${streamingContent.length}:${streamingBlocks.length}:${streamingPhases.length}:${streamingStep ?? ""}`
    : messages.length;

  const { containerRef, scrollToBottom, isAtBottom } = useAutoScroll(
    scrollDependency,
  );

  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIdx = i;
      break;
    }
  }

  const useVirtual = messages.length > VIRTUALIZATION_THRESHOLD;
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => containerRef.current,
    estimateSize: useCallback((index: number) => (
      messages[index]?.role === "user" ? 70 : 200
    ), [messages]),
    overscan: 5,
    gap: MESSAGE_GAP,
    enabled: useVirtual,
  });

  const scrollToLatestMessage = useCallback((behavior: ScrollBehavior = "smooth") => {
    scrollToBottom(behavior);
    if (useVirtual && messages.length > 0) {
      requestAnimationFrame(() => {
        virtualizer.scrollToIndex(messages.length - 1, {
          align: "end",
          behavior,
        });
      });
    }
  }, [messages.length, scrollToBottom, useVirtual, virtualizer]);

  const latestMessage = messages[messages.length - 1];
  useEffect(() => {
    if (!shouldAutoFollowLatestMessage(latestMessage)) return;
    scrollToLatestMessage("auto");
  }, [latestMessage?.id, latestMessage?.role, scrollToLatestMessage]);

  return (
    <div className="relative flex-1 overflow-hidden chat-stage">
      <div
        ref={containerRef}
        className="h-full overflow-y-auto px-4 py-6 scroll-container chat-stage__scroller"
        role="log"
        aria-label="Lịch sử trò chuyện với Wiii"
        aria-live={isStreaming ? "off" : "polite"}
        aria-relevant="additions text"
        tabIndex={0}
      >
        {useVirtual ? (
          <div className="chat-lane">
            <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const msg = messages[virtualRow.index];
                const isLast = virtualRow.index === lastAssistantIdx && msg.role === "assistant";
                return (
                  <div
                    key={msg.id}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <MessageBubble
                      message={msg}
                      isLastAssistant={isLast}
                      liveAvatarState={isLast ? avatarState : undefined}
                      liveAvatarMood={isLast ? avatarMood : undefined}
                      liveSoulEmotion={isLast ? soulEmotion : undefined}
                      onSuggestedQuestion={onSuggestedQuestion}
                      onRegenerate={isLast ? onRegenerate : undefined}
                      onEditMessage={msg.role === "user" ? onEditMessage : undefined}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="chat-lane space-y-5">
            {messages.map((msg, idx) => {
              const isLast = idx === lastAssistantIdx && msg.role === "assistant";
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLastAssistant={isLast}
                  liveAvatarState={isLast ? avatarState : undefined}
                  liveAvatarMood={isLast ? avatarMood : undefined}
                  liveSoulEmotion={isLast ? soulEmotion : undefined}
                  onSuggestedQuestion={onSuggestedQuestion}
                  onRegenerate={isLast ? onRegenerate : undefined}
                  onEditMessage={msg.role === "user" ? onEditMessage : undefined}
                />
              );
            })}
          </div>
        )}

        {isStreaming && (
          <div className="chat-lane mt-5">
            <div className="flex gap-2.5 animate-slide-in">
              <motion.div layoutId="wiii-active-avatar">
                <WiiiAvatar state={avatarState} size={64} mood={avatarMood} soulEmotion={soulEmotion} />
              </motion.div>

              <div className="flex-1 min-w-0">
                <InterleavedBlockSequence
                  blocks={visibleStreamingBlocks}
                  showThinking={show_thinking}
                  thinkingLevel={thinking_level}
                  isStreaming
                  livePhases={streamingPhases}
                  onSuggestedQuestion={onSuggestedQuestion}
                />

                {/* Streaming timer — only show when no thinking blocks visible yet */}
                {streamingStartTime && !shouldHideTimer && (
                  <StreamingTimer
                    startTime={streamingStartTime}
                    hasAnswer={false}
                    statusText={streamingStep}
                  />
                )}

                {streamingSources && streamingSources.length > 0 && (
                  <SourceCitation sources={streamingSources} />
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {!isAtBottom && (
        <button
          onClick={() => scrollToLatestMessage()}
          className="absolute bottom-4 right-4 w-9 h-9 rounded-full bg-surface border border-border shadow-lg flex items-center justify-center text-text-secondary hover:text-text hover:bg-surface-secondary transition-all animate-fade-in"
          title="Cuộn xuống cuối"
          aria-label="Cuộn xuống cuối"
        >
          <ChevronDown size={18} />
        </button>
      )}
    </div>
  );
}

// ThinkingIndicatorDelayed removed — StreamingTimer handles this now

function StreamingTimer({
  startTime,
  hasAnswer,
  statusText,
}: {
  startTime: number;
  hasAnswer?: boolean;
  statusText?: string;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(Math.floor((Date.now() - startTime) / 1000));
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [startTime]);

  const timeStr = elapsed >= 60
    ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`
    : `${elapsed}s`;

  // Phase 35 — `<output>` with `aria-live="polite"` so screen readers announce
  // progress without interrupting current speech. `aria-atomic="true"` so the
  // entire status reads each update instead of fragmenting.
  return (
    <output
      className="streaming-timer mt-1.5"
      aria-live="polite"
      aria-atomic="true"
    >
      <span className="streaming-timer__dot" aria-hidden="true" />
      <span className="streaming-timer__label">
        {hasAnswer ? "Wiii đang hoàn thiện" : "Wiii đang suy nghĩ"}
      </span>
      <span className="streaming-timer__time">{timeStr}</span>
      {statusText?.trim() ? (
        <span className="streaming-timer__status ml-2 text-text-secondary">
          {statusText.trim()}
        </span>
      ) : null}
    </output>
  );
}
