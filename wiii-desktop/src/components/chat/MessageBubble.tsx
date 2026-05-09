import { useState, useCallback, memo, lazy, Suspense } from "react";
import { motion } from "motion/react";
import { Check, Copy, FileText, Film, Pencil, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import type { ContentBlock, Message, MoodType } from "@/api/types";
import type { AvatarState, SoulEmotionData } from "@/lib/avatar/types";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import { ThinkingBlock } from "./ThinkingBlock";
import { InterleavedBlockSequence } from "./InterleavedBlockSequence";
import { ModelSwitchPromptCard } from "./ModelSwitchPromptCard";
import { SourceCitation } from "./SourceCitation";
import { MessageMentions } from "./MessageMentions";
import { useSettingsStore } from "@/stores/settings-store";
import { useChatStore } from "@/stores/chat-store";
import { useToastStore } from "@/stores/toast-store";
import { submitFeedback } from "@/api/feedback";
import { formatRelativeTime, formatAbsoluteTime } from "@/lib/date-utils";
import { userMessageEntry, aiMessageEntry } from "@/lib/animations";
import { useReducedMotion, motionSafe } from "@/hooks/useReducedMotion";
import { formatBytes } from "@/lib/document-context";

const SuggestedQuestions = lazy(async () => {
  const mod = await import("./SuggestedQuestions");
  return { default: mod.SuggestedQuestions };
});

const ReasoningTrace = lazy(async () => {
  const mod = await import("./ReasoningTrace");
  return { default: mod.ReasoningTrace };
});

interface MessageBubbleProps {
  message: Message;
  isLastAssistant?: boolean;
  liveAvatarState?: AvatarState;
  liveAvatarMood?: MoodType;
  liveSoulEmotion?: SoulEmotionData | null;
  onSuggestedQuestion?: (q: string) => void;
  onRegenerate?: () => void;
  onEditMessage?: (content: string) => void;
}

function getRoutingMethod(message: Message): string {
  const metadata = message.metadata;
  if (!metadata || typeof metadata !== "object") return "";
  const routingMetadata = (metadata as Record<string, unknown>).routing_metadata;
  if (!routingMetadata || typeof routingMetadata !== "object") return "";
  const method = (routingMetadata as Record<string, unknown>).method;
  return typeof method === "string" ? method.trim() : "";
}

function isLocalSocialFastPath(message: Message): boolean {
  const method = getRoutingMethod(message);
  return method === "always_on_social_fast_path" || method === "always_on_chatter_fast_path";
}

function shouldShowRuntimeModelBadge(message: Message): boolean {
  if (!message.metadata || typeof message.metadata !== "object") return false;
  if (isLocalSocialFastPath(message)) return false;
  const runtimeAuthoritative = (message.metadata as Record<string, unknown>).runtime_authoritative;
  if (runtimeAuthoritative === false) return false;
  const model = (message.metadata as Record<string, unknown>).model;
  return typeof model === "string" && model.trim().length > 0;
}

export const MessageBubble = memo(function MessageBubble({
  message,
  isLastAssistant,
  liveAvatarState,
  liveAvatarMood,
  liveSoulEmotion,
  onSuggestedQuestion,
  onRegenerate,
  onEditMessage,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const reduced = useReducedMotion();
  const { show_thinking, show_reasoning_trace, thinking_level } = useSettingsStore(
    (s) => s.settings,
  );

  if (isUser) {
    return (
      <motion.div
        className="flex justify-end group/msg"
        data-message-role="user"
        variants={motionSafe(reduced, userMessageEntry)}
        initial={reduced ? false : "hidden"}
        animate="visible"
      >
        <div className="max-w-[min(85%,800px)]">
          <div className="bg-[var(--user-bg)] rounded-xl px-4 py-2.5 relative">
            <p className="text-[15px] leading-[1.7] font-sans text-text selectable">
              <MessageMentions text={message.content} />
            </p>

            {message.images && message.images.length > 0 && (
              <div className="flex gap-2 flex-wrap mt-2">
                {message.images.map((img, i) => (
                  <img
                    key={i}
                    src={img.type === "base64" ? `data:${img.media_type};base64,${img.data}` : img.data}
                    alt={`Anh ${i + 1}`}
                    className="max-w-[200px] max-h-[200px] rounded-lg object-cover cursor-pointer hover:opacity-90 transition-opacity"
                    onClick={() => {
                      const safeImageTypes = ["image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"];
                      if (img.type === "base64" && !safeImageTypes.includes(img.media_type)) return;
                      window.open(img.type === "base64" ? `data:${img.media_type};base64,${img.data}` : img.data);
                    }}
                  />
                ))}
              </div>
            )}

            {message.documents && message.documents.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {message.documents.map((doc) => (
                  <div
                    key={doc.id || doc.file_name}
                    className="flex max-w-[260px] items-start gap-2 rounded-lg border border-[var(--border)] bg-white/55 px-2.5 py-2 text-xs text-text-secondary"
                  >
                    {doc.media_kind === "video" ? (
                      <Film size={14} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                    ) : (
                      <FileText size={14} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                    )}
                    <div className="min-w-0">
                      <div className="truncate font-medium text-text">{doc.file_name}</div>
                      <div className="mt-0.5 truncate text-[11px] text-text-tertiary">
                        {doc.parser || "MarkItDown"} · {formatBytes(doc.size_bytes)}
                        {doc.char_count ? ` · ${doc.char_count} ký tự` : ""}
                        {doc.extracted_image_count ? ` · ${doc.extracted_image_count} khung hình` : ""}
                        {doc.truncated ? " · đã rút gọn" : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {onEditMessage && (
              <div className="absolute -left-10 top-1/2 -translate-y-1/2 opacity-0 group-hover/msg:opacity-100 transition-opacity">
                <button
                  onClick={() => onEditMessage(message.content)}
                  className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-tertiary hover:text-text-secondary"
                  title="Chỉnh sửa"
                  aria-label="Chỉnh sửa tin nhắn"
                >
                  <Pencil size={14} />
                </button>
              </div>
            )}
          </div>

          {message.timestamp && (
            <div
              className="mt-0.5 text-right text-[10px] text-text-tertiary opacity-0 group-hover/msg:opacity-100 transition-opacity"
              title={formatAbsoluteTime(message.timestamp)}
            >
              {formatRelativeTime(message.timestamp)}
            </div>
          )}
        </div>
      </motion.div>
    );
  }

  const messageMood: MoodType | undefined = (() => {
    const md = message.metadata?.mood as { mood?: string } | undefined;
    const value = md?.mood;
    const valid: string[] = ["excited", "warm", "concerned", "gentle", "neutral"];
    return valid.includes(value ?? "") ? (value as MoodType) : undefined;
  })();

  const hasBlocks = Boolean(message.blocks && message.blocks.length > 0);
  const hasInlineVisualBlock = Boolean(
    message.blocks?.some((block) => block.type === "visual"),
  );
  const isSocialFastPath = isLocalSocialFastPath(message);
  const showThinkingForMessage = show_thinking;
  const showReasoningTraceForMessage = show_reasoning_trace && !isSocialFastPath;
  const metadataAgentLabel = resolveAgentLabel(
    typeof message.metadata?.agent_type === "string" ? (message.metadata.agent_type as string) : undefined,
    hasBlocks,
  );

  return (
    <motion.div
      className="flex gap-2.5 group/msg"
      data-message-role="assistant"
      variants={motionSafe(reduced, aiMessageEntry)}
      initial={reduced ? false : "hidden"}
      animate="visible"
    >
      {isLastAssistant ? (
        <motion.div layoutId="wiii-active-avatar">
          <WiiiAvatar
            state={liveAvatarState ?? "idle"}
            size={64}
            mood={liveAvatarMood ?? messageMood}
            soulEmotion={liveSoulEmotion}
          />
        </motion.div>
      ) : (
        <WiiiAvatar state="idle" size={24} mood={messageMood} />
      )}

      <div className="flex-1 min-w-0">
        {hasBlocks ? (
          <BlockRenderer
            blocks={message.blocks as ContentBlock[]}
            showThinking={showThinkingForMessage}
            thinkingLevel={thinking_level}
            onSuggestedQuestion={onSuggestedQuestion}
            message={message}
          />
        ) : (
          <LegacyRenderer message={message} showThinking={showThinkingForMessage} />
        )}

        {message.sources && message.sources.length > 0 && (
          <SourceCitation sources={message.sources} />
        )}

        {message.domain_notice && (
          <div className="mt-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-700 dark:text-amber-400 flex items-center gap-2">
            <span className="text-amber-500">&#x1F4A1;</span>
            <span>{message.domain_notice}</span>
          </div>
        )}

        {showReasoningTraceForMessage && message.reasoning_trace && (
          <Suspense fallback={null}>
            <ReasoningTrace trace={message.reasoning_trace} />
          </Suspense>
        )}

        {isLastAssistant ? (
          <ModelSwitchPromptCard
            metadata={message.metadata}
            onRetryOnce={onRegenerate}
          />
        ) : null}

        <div className="mt-2 flex items-center gap-2">
          {message.metadata && !hasInlineVisualBlock && (
            <div className="flex items-center gap-3 text-[11px] text-text-tertiary">
              {metadataAgentLabel && (
                <span className="px-1.5 py-0.5 rounded bg-[var(--surface-tertiary)]">
                  {metadataAgentLabel}
                </span>
              )}
              {typeof message.metadata.processing_time === "number" && (
                <span>Tổng {(message.metadata.processing_time as number).toFixed(1)}s</span>
              )}
              {shouldShowRuntimeModelBadge(message) && typeof message.metadata.model === "string" && (
                <span>{message.metadata.model as string}</span>
              )}
            </div>
          )}

          <MessageActions
            message={message}
            isLastAssistant={isLastAssistant}
            onRegenerate={onRegenerate}
          />
        </div>

        {message.timestamp && (
          <div
            className="mt-0.5 text-[10px] text-text-tertiary opacity-0 group-hover/msg:opacity-100 transition-opacity"
            title={formatAbsoluteTime(message.timestamp)}
          >
            {formatRelativeTime(message.timestamp)}
          </div>
        )}

        {message.suggested_questions &&
          message.suggested_questions.length > 0 &&
          onSuggestedQuestion && (
            <Suspense fallback={null}>
              <SuggestedQuestions
                questions={message.suggested_questions}
                onSelect={onSuggestedQuestion}
              />
            </Suspense>
          )}
      </div>
    </motion.div>
  );
}, areMessageBubblePropsEqual);

/**
 * Phase 35 — custom comparator for MessageBubble.
 *
 * Default `memo` uses shallow equality. That re-renders every historical
 * bubble whenever the active streaming bubble's `liveAvatarState`,
 * `liveAvatarMood`, `liveSoulEmotion` props change (which happens many
 * times per second during NVIDIA stream). Historical bubbles don't care
 * about these live props — they're only meaningful for `isLastAssistant`.
 *
 * Custom comparator skips re-render when:
 *  - message reference unchanged (assumed immutable per turn)
 *  - role-relevant props unchanged
 *  - live-* props compared ONLY for the last assistant bubble
 *
 * Net effect: streaming bubble re-renders, historical bubbles do not.
 */
function areMessageBubblePropsEqual(
  prev: MessageBubbleProps,
  next: MessageBubbleProps,
): boolean {
  if (prev.message !== next.message) return false;
  if (prev.isLastAssistant !== next.isLastAssistant) return false;
  if (prev.onSuggestedQuestion !== next.onSuggestedQuestion) return false;
  if (prev.onRegenerate !== next.onRegenerate) return false;
  if (prev.onEditMessage !== next.onEditMessage) return false;

  // Live avatar/mood/soul props matter ONLY for the active streaming bubble.
  if (next.isLastAssistant) {
    if (prev.liveAvatarState !== next.liveAvatarState) return false;
    if (prev.liveAvatarMood !== next.liveAvatarMood) return false;
    if (prev.liveSoulEmotion !== next.liveSoulEmotion) return false;
  }

  return true;
}

const AGENT_LABELS: Record<string, string | null> = {
  chat: null,
  rag: "Tra cứu",
  tutor: "Giải thích",
  direct: null,
  memory: "Ngữ cảnh",
  memory_agent: "Ngữ cảnh",
  product_search_agent: "Đối chiếu",
  code_studio_agent: null,
  parallel_dispatch: null,
  synthesizer: null,
  supervisor: null,
};

function resolveAgentLabel(agentType?: string, hasBlocks = false): string | null {
  if (!agentType) return null;
  const normalized = agentType.toLowerCase().trim();
  if (hasBlocks) {
    return AGENT_LABELS[normalized] ?? null;
  }
  if (normalized in AGENT_LABELS) {
    return AGENT_LABELS[normalized];
  }
  if (normalized.endsWith("_agent")) {
    return null;
  }
  return agentType;
}

function MessageActions({
  message,
  isLastAssistant,
  onRegenerate,
}: {
  message: Message;
  isLastAssistant?: boolean;
  onRegenerate?: () => void;
}) {
  const { addToast } = useToastStore();
  const setMessageFeedback = useChatStore((s) => s.setMessageFeedback);
  const activeConv = useChatStore((s) => s.activeConversation());
  const [copied, setCopied] = useState(false);
  const feedback = message.feedback ?? null;

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      addToast("success", "Đã sao chép tin nhắn!");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Ignore clipboard failures in insecure contexts.
    }
  }, [message.content, addToast]);

  const handleFeedback = useCallback(
    (rating: "up" | "down") => {
      const newRating = feedback === rating ? null : rating;
      setMessageFeedback(message.id, newRating);
      const sessionId = activeConv?.session_id || activeConv?.id || "";
      if (newRating && sessionId) {
        submitFeedback(message.id, sessionId, newRating).catch(() => {});
      }
    },
    [feedback, message.id, activeConv, setMessageFeedback],
  );

  return (
    <div className="flex items-center gap-0.5 opacity-0 group-hover/msg:opacity-100 transition-opacity ml-auto">
      <motion.button
        onClick={handleCopy}
        className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-tertiary hover:text-text-secondary transition-colors"
        title="Sao chép"
        aria-label="Sao chép tin nhắn"
        whileHover={{ scale: 1.15 }}
        whileTap={{ scale: 0.9 }}
      >
        {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
      </motion.button>

      {isLastAssistant && onRegenerate && (
        <motion.button
          onClick={onRegenerate}
          className="p-1.5 rounded-md hover:bg-surface-tertiary text-text-tertiary hover:text-text-secondary transition-colors"
          title="Tạo lại"
          aria-label="Tạo lại phản hồi"
          whileHover={{ scale: 1.15, rotate: 15 }}
          whileTap={{ scale: 0.9 }}
        >
          <RefreshCw size={14} />
        </motion.button>
      )}

      <motion.button
        onClick={() => handleFeedback("up")}
        className={`p-1.5 rounded-md hover:bg-surface-tertiary transition-colors ${
          feedback === "up" ? "text-green-500" : "text-text-tertiary hover:text-text-secondary"
        }`}
        title="Phản hồi tốt"
        aria-label="Đánh giá tốt"
        whileHover={{ scale: 1.15, y: -2 }}
        whileTap={{ scale: 0.9 }}
      >
        <ThumbsUp size={14} />
      </motion.button>

      <motion.button
        onClick={() => handleFeedback("down")}
        className={`p-1.5 rounded-md hover:bg-surface-tertiary transition-colors ${
          feedback === "down" ? "text-red-500" : "text-text-tertiary hover:text-text-secondary"
        }`}
        title="Phản hồi chưa tốt"
        aria-label="Đánh giá chưa tốt"
        whileHover={{ scale: 1.15, y: 2 }}
        whileTap={{ scale: 0.9 }}
      >
        <ThumbsDown size={14} />
      </motion.button>
    </div>
  );
}

function BlockRenderer({
  blocks,
  showThinking,
  thinkingLevel = "balanced",
  onSuggestedQuestion,
}: {
  blocks: ContentBlock[];
  showThinking: boolean;
  thinkingLevel?: import("@/api/types").ThinkingLevel;
  onSuggestedQuestion?: (q: string) => void;
  message: Message;
}) {
  return (
    <InterleavedBlockSequence
      blocks={blocks}
      showThinking={showThinking}
      thinkingLevel={thinkingLevel}
      onSuggestedQuestion={onSuggestedQuestion}
    />
  );
}

function LegacyRenderer({
  message,
  showThinking,
}: {
  message: Message;
  showThinking: boolean;
}) {
  return (
    <>
      {showThinking && (message.thinking || (message.tool_calls && message.tool_calls.length > 0)) && (
        <ThinkingBlock
          content={message.thinking || ""}
          savedDuration={
            message.metadata?.processing_time
              ? Math.round(Number(message.metadata.processing_time))
              : undefined
          }
          toolCalls={message.tool_calls}
        />
      )}

      <div className="assistant-response">
        <MarkdownRenderer content={message.content} />
      </div>
    </>
  );
}
