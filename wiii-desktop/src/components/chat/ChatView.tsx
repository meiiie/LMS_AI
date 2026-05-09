/**
 * ChatView — main chat area orchestrator.
 * Sprint 82b: Welcome mode — WelcomeScreen owns input (centered composition).
 * Chat mode — MessageList + ChatInput at bottom (unchanged).
 * Sprint 105: Compaction warning banner when context utilization >= 75%.
 */
import {
  lazy,
  Suspense,
  useState,
  useMemo,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, X } from "lucide-react";
import { useChatStore } from "@/stores/chat-store";
import { useContextStore } from "@/stores/context-store";
import { useToastStore } from "@/stores/toast-store";
import { useSSEStream } from "@/hooks/useSSEStream";
import { slideDown } from "@/lib/animations";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import type {
  ChatDocumentAttachment,
  ChatDocumentContext,
  ImageInput,
} from "@/api/types";

const WelcomeScreen = lazy(async () => {
  const mod = await import("./WelcomeScreen");
  return { default: mod.WelcomeScreen };
});

function WelcomeFallback({
  onSendMessage,
  onCancel,
}: {
  onSendMessage: (
    message: string,
    images?: ImageInput[],
    forceSkills?: string[],
    documents?: ChatDocumentAttachment[],
    documentContext?: ChatDocumentContext,
  ) => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex-1 flex flex-col items-center px-6 pt-[12vh] pb-8 welcome-bg">
      <div className="w-full max-w-[720px] flex flex-col items-center gap-6">
        <p
          className="text-center font-normal text-text-secondary leading-[1.5]"
          style={{
            fontFamily: "var(--font-serif)",
            fontSize: "clamp(1.875rem, 1.2rem + 2vw, 2.5rem)",
          }}
        >
          Wiii đang mở không gian chào bạn.
        </p>
        <div className="w-full">
          <ChatInput onSend={onSendMessage} onCancel={onCancel} centered />
        </div>
      </div>
    </div>
  );
}

export function ChatView() {
  const { activeConversationId, conversations } = useChatStore();
  const { sendMessage, cancelStream } = useSSEStream();
  const [editingMessage, setEditingMessage] = useState<string | null>(null);

  // Context warning state
  const { info, compact } = useContextStore();
  const { addToast } = useToastStore();
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Sprint 85: Memoize active conversation lookup — O(n) -> O(1) on re-renders
  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId),
    [conversations, activeConversationId],
  );

  // Welcome-back toast when switching to existing conversation with messages
  const prevConvIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      activeConversationId &&
      prevConvIdRef.current !== null &&
      prevConvIdRef.current !== activeConversationId &&
      activeConversation &&
      activeConversation.messages.length > 0
    ) {
      addToast("info", "Tiếp tục nào! Mình nhớ cuộc trò chuyện này.");
    }
    prevConvIdRef.current = activeConversationId;
  }, [activeConversationId, activeConversation, addToast]);

  // Reset banner dismissed state when session or utilization changes significantly
  const utilization = info?.utilization ?? 0;
  const sessionId =
    activeConversation?.session_id || activeConversation?.id || "";

  useEffect(() => {
    setBannerDismissed(false);
  }, [sessionId]);

  const showWarningBanner =
    !bannerDismissed && (info?.needs_compaction === true || utilization >= 75);

  const handleCompactFromBanner = async () => {
    await compact(sessionId);
    setBannerDismissed(true);
    addToast("success", "Wiii đã tóm tắt xong, nhớ rõ hơn rồi!");
  };

  // No active conversation OR empty conversation — show welcome screen
  // Sprint 220c: Skip welcome in widget/embed mode
  const embedCfg = (window as any).__WIII_EMBED_CONFIG__;
  const hideWelcome = embedCfg?.hide_welcome || embedCfg?.mode === "widget";
  const showWelcome =
    !hideWelcome &&
    (!activeConversation || activeConversation.messages.length === 0);

  // Sprint 85: Wrap callbacks with useCallback to prevent child re-renders
  const handleRegenerate = useCallback(() => {
    if (!activeConversation) return;
    const msgs = activeConversation.messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === "user") {
        sendMessage(msgs[i].content);
        return;
      }
    }
  }, [activeConversation, sendMessage]);

  const handleEditMessage = useCallback((content: string) => {
    setEditingMessage(content);
  }, []);

  const handleSend = useCallback(
    (
      message: string,
      images?: ImageInput[],
      forceSkills?: string[],
      documents?: ChatDocumentAttachment[],
      documentContext?: ChatDocumentContext,
    ) => {
      setEditingMessage(null);
      sendMessage(message, images, forceSkills, documents, documentContext);
    },
    [sendMessage],
  );

  if (showWelcome) {
    // Welcome mode: WelcomeScreen owns the entire viewport including input
    return (
      <div className="flex flex-col h-full">
        <Suspense
          fallback={
            <WelcomeFallback
              onSendMessage={handleSend}
              onCancel={cancelStream}
            />
          }
        >
          <WelcomeScreen onSendMessage={handleSend} onCancel={cancelStream} />
        </Suspense>
      </div>
    );
  }

  // Chat mode: MessageList + ChatInput at bottom
  return (
    <div className="flex flex-col h-full">
      <MessageList
        messages={activeConversation?.messages ?? []}
        onSuggestedQuestion={handleSend}
        onCancel={cancelStream}
        onRegenerate={handleRegenerate}
        onEditMessage={handleEditMessage}
      />

      {/* Compaction warning banner */}
      <AnimatePresence>
        {showWarningBanner && (
          <motion.div
            variants={slideDown}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="flex items-center gap-2 px-4 py-2 bg-yellow-50 dark:bg-yellow-950/30 border-t border-yellow-200 dark:border-yellow-800 text-sm"
          >
            <AlertTriangle
              size={14}
              className="shrink-0 text-yellow-600 dark:text-yellow-400"
            />
            <button
              onClick={handleCompactFromBanner}
              className="flex-1 text-left text-yellow-800 dark:text-yellow-200 hover:underline"
            >
              Mình cần tóm tắt lại cuộc trò chuyện để nhớ rõ hơn (
              {Math.round(utilization)}%). Nhấn đây nhé!
            </button>
            <button
              onClick={() => setBannerDismissed(true)}
              className="shrink-0 p-0.5 rounded hover:bg-yellow-200 dark:hover:bg-yellow-900 text-yellow-600 dark:text-yellow-400"
            >
              <X size={14} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <ChatInput
        onSend={handleSend}
        onCancel={cancelStream}
        editingMessage={editingMessage}
        onClearEdit={() => setEditingMessage(null)}
      />
    </div>
  );
}
