/**
 * SSE (Server-Sent Events) stream parser for Wiii /chat/stream/v3.
 *
 * Protocol (from maritime-ai-service/app/api/v1/chat_stream.py):
 *   event: <type>\n
 *   data: <json>\n
 *   \n
 *
 * Supported event types are defined by SSEEventHandler below.
 */
import type {
  SSEThinkingEvent,
  SSEThinkingDeltaEvent,
  SSEAnswerEvent,
  SSESourcesEvent,
  SSEMetadataEvent,
  SSEDoneEvent,
  SSEErrorEvent,
  SSEToolCallEvent,
  SSEToolResultEvent,
  SSEStatusEvent,
  SSEChatLifecycleEvent,
  SSEThinkingStartEvent,
  SSEThinkingEndEvent,
  SSEDomainNoticeEvent,
  SSEEmotionEvent,
  SSEActionTextEvent,
  SSEBrowserScreenshotEvent,
  SSEPreviewEvent,
  SSEArtifactEvent,
  SSEVisualEvent,
  SSEVisualCommitEvent,
  SSEVisualDisposeEvent,
  SSEHostActionEvent,
  SSEPointyActionEvent,
  SSECodeOpenEvent,
  SSECodeDeltaEvent,
  SSECodeCompleteEvent,
} from "./types";

export interface SSEEventHandler {
  onThinking: (data: SSEThinkingEvent) => void;
  onThinkingDelta?: (data: SSEThinkingDeltaEvent) => void;
  onAnswer: (data: SSEAnswerEvent) => void;
  onSources: (data: SSESourcesEvent) => void;
  onMetadata: (data: SSEMetadataEvent) => void;
  onDone: (data?: SSEDoneEvent) => void;
  onError: (data: SSEErrorEvent) => void;
  onToolCall: (data: SSEToolCallEvent) => void;
  onToolResult: (data: SSEToolResultEvent) => void;
  onStatus: (data: SSEStatusEvent) => void;
  onChatLifecycle?: (data: SSEChatLifecycleEvent) => void;
  onThinkingStart?: (data: SSEThinkingStartEvent) => void;
  onThinkingEnd?: (data: SSEThinkingEndEvent) => void;
  onDomainNotice?: (data: SSEDomainNoticeEvent) => void;
  /** Sprint 135: Soul emotion — LLM-driven avatar expression */
  onEmotion?: (data: SSEEmotionEvent) => void;
  /** Sprint 147: Bold action text between thinking blocks */
  onActionText?: (data: SSEActionTextEvent) => void;
  /** Sprint 153: Browser screenshot — Playwright visual transparency */
  onBrowserScreenshot?: (data: SSEBrowserScreenshotEvent) => void;
  /** Sprint 166: Rich preview card */
  onPreview?: (data: SSEPreviewEvent) => void;
  /** Sprint 167: Interactive artifact */
  onArtifact?: (data: SSEArtifactEvent) => void;
  /** Sprint 230: Structured inline visual */
  onVisual?: (data: SSEVisualEvent) => void;
  onVisualOpen?: (data: SSEVisualEvent) => void;
  onVisualPatch?: (data: SSEVisualEvent) => void;
  onVisualCommit?: (data: SSEVisualCommitEvent) => void;
  onVisualDispose?: (data: SSEVisualDisposeEvent) => void;
  /** Sprint 222b: Host action request from AI agent */
  onHostAction?: (data: SSEHostActionEvent) => void;
  /** Wiii Pointy: agent-controlled cursor / spotlight overlay */
  onPointyAction?: (data: SSEPointyActionEvent) => void;
  /** Code Studio: session opened */
  onCodeOpen?: (data: SSECodeOpenEvent) => void;
  /** Code Studio: chunked code content */
  onCodeDelta?: (data: SSECodeDeltaEvent) => void;
  /** Code Studio: full code + trigger preview */
  onCodeComplete?: (data: SSECodeCompleteEvent) => void;
  /** Transport keepalive comment such as ": keepalive" */
  onKeepAlive?: () => void;
}

/**
 * Parse an SSE stream from ReadableStream<Uint8Array>.
 *
 * Handles:
 * - Partial JSON across TCP chunks (buffer accumulation)
 * - Multi-line data fields
 * - Abort signal for cancellation
 */
/** Result from parseSSEStream, carries reconnection metadata. */
export interface SSEStreamResult {
  /** Last event ID received (for reconnection via Last-Event-ID header). */
  lastEventId: string | null;
  /** Whether the stream emitted an explicit done event. */
  sawDone: boolean;
  /** Event types dispatched in order, for lightweight dev tracing. */
  eventOrder: string[];
}

export async function parseSSEStream(
  stream: ReadableStream<Uint8Array>,
  handlers: SSEEventHandler,
  abortSignal?: AbortSignal
): Promise<SSEStreamResult> {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = "";
  let lastEventId: string | null = null;
  let sawDone = false;
  const eventOrder: string[] = [];

  const parseBufferedEvents = (flushTail: boolean = false) => {
    buffer = normalizeChunk(buffer);

    while (true) {
      const separatorIndex = buffer.indexOf("\n\n");
      if (separatorIndex === -1) break;

      const eventStr = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      if (!eventStr.trim()) continue;

      if (dispatchEventString(eventStr, handlers, eventOrder, (id) => {
        lastEventId = id;
      })) {
        sawDone = true;
      }
    }

    if (flushTail && buffer.trim()) {
      const trailingEvent = buffer;
      buffer = "";
      if (dispatchEventString(trailingEvent, handlers, eventOrder, (id) => {
        lastEventId = id;
      })) {
        sawDone = true;
      }
    }
  };

  try {
    while (true) {
      if (abortSignal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += normalizeChunk(decoder.decode(value, { stream: true }));
      parseBufferedEvents();
    }
  } finally {
    buffer += normalizeChunk(decoder.decode());
    parseBufferedEvents(true);
    reader.releaseLock();
  }

  return { lastEventId, sawDone, eventOrder };
}

function normalizeChunk(chunk: string): string {
  return chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function dispatchEventString(
  eventStr: string,
  handlers: SSEEventHandler,
  eventOrder: string[],
  setLastEventId: (value: string) => void,
): boolean {
  const lines = eventStr.trim().split("\n");
  if (lines.length > 0 && lines.every((line) => line.trim().startsWith(":"))) {
    eventOrder.push("keepalive");
    handlers.onKeepAlive?.();
    return false;
  }

  let eventType = "";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5));
    } else if (line.startsWith("id: ")) {
      setLastEventId(line.slice(4).trim());
    } else if (line.startsWith("id:")) {
      setLastEventId(line.slice(3).trim());
    }
  }

  if (!eventType || dataLines.length === 0) return false;

  const dataStr = dataLines.join("\n");

  try {
    const parsed = JSON.parse(dataStr);
    eventOrder.push(eventType);
    dispatchEvent(eventType, parsed, handlers);
    return eventType === "done";
  } catch {
    console.warn(`[SSE] Failed to parse JSON for event "${eventType}":`, dataStr);
    return false;
  }
}

function dispatchEvent(
  eventType: string,
  data: unknown,
  handlers: SSEEventHandler
) {
  // Sprint 153b: Type safety guard — ensure data is an object for all events except done
  if (eventType !== "done" && (data === null || data === undefined || typeof data !== "object")) {
    console.warn(`[SSE] Invalid data for event "${eventType}":`, data);
    return;
  }

  switch (eventType) {
    case "thinking":
      handlers.onThinking(data as SSEThinkingEvent);
      break;
    case "answer":
    case "answer_delta": {
      // v5.0 F8 (2026-05-06): backend emits `answer_delta` for streaming
      // chunks (chat_stream_presenter.py:386). Frontend previously only
      // handled `answer` → answer_delta hit default branch, content
      // never reached onAnswer / fullAnswerTextRef → embodied parser
      // had nothing to scan. Treat both event types identically.
      const answerData = data as SSEAnswerEvent;
      if (typeof answerData.content === "string") {
        handlers.onAnswer(answerData);
      }
      break;
    }
    case "sources":
      handlers.onSources(data as SSESourcesEvent);
      break;
    case "metadata":
      handlers.onMetadata(data as SSEMetadataEvent);
      break;
    case "done":
      handlers.onDone(
        data && typeof data === "object" ? data as SSEDoneEvent : undefined,
      );
      break;
    case "error":
      handlers.onError(data as SSEErrorEvent);
      break;
    case "tool_call": {
      // Sprint 153b: Guard — content must have name and id
      const tcData = data as SSEToolCallEvent;
      if (tcData.content && typeof tcData.content.name === "string" && typeof tcData.content.id === "string") {
        handlers.onToolCall(tcData);
      }
      break;
    }
    case "tool_result": {
      // Sprint 153b: Guard — content must have id
      const trData = data as SSEToolResultEvent;
      if (trData.content && typeof trData.content.id === "string") {
        handlers.onToolResult(trData);
      }
      break;
    }
    case "status":
      handlers.onStatus(data as SSEStatusEvent);
      break;
    case "chat_lifecycle":
      handlers.onChatLifecycle?.(data as SSEChatLifecycleEvent);
      break;
    case "thinking_delta": {
      // Sprint 153b: Guard — content must be string
      const tdData = data as SSEThinkingDeltaEvent;
      if (typeof tdData.content === "string") {
        handlers.onThinkingDelta?.(tdData);
      }
      break;
    }
    case "thinking_start":
      handlers.onThinkingStart?.(data as SSEThinkingStartEvent);
      break;
    case "thinking_end":
      handlers.onThinkingEnd?.(data as SSEThinkingEndEvent);
      break;
    case "domain_notice":
      handlers.onDomainNotice?.(data as SSEDomainNoticeEvent);
      break;
    case "emotion":
      handlers.onEmotion?.(data as SSEEmotionEvent);
      break;
    case "action_text":
      handlers.onActionText?.(data as SSEActionTextEvent);
      break;
    case "browser_screenshot":
      handlers.onBrowserScreenshot?.(data as SSEBrowserScreenshotEvent);
      break;
    case "preview":
      handlers.onPreview?.(data as SSEPreviewEvent);
      break;
    case "artifact":
      handlers.onArtifact?.(data as SSEArtifactEvent);
      break;
    case "visual":
      if (handlers.onVisualOpen) {
        handlers.onVisualOpen(data as SSEVisualEvent);
      } else {
        handlers.onVisual?.(data as SSEVisualEvent);
      }
      break;
    case "visual_open":
      handlers.onVisualOpen?.(data as SSEVisualEvent);
      break;
    case "visual_patch":
      handlers.onVisualPatch?.(data as SSEVisualEvent);
      break;
    case "visual_commit":
      handlers.onVisualCommit?.(data as SSEVisualCommitEvent);
      break;
    case "visual_dispose":
      handlers.onVisualDispose?.(data as SSEVisualDisposeEvent);
      break;
    case "host_action":
      handlers.onHostAction?.(data as SSEHostActionEvent);
      break;
    case "pointy_action":
      handlers.onPointyAction?.(data as SSEPointyActionEvent);
      break;
    case "code_open":
      handlers.onCodeOpen?.(data as SSECodeOpenEvent);
      break;
    case "code_delta":
      handlers.onCodeDelta?.(data as SSECodeDeltaEvent);
      break;
    case "code_complete":
      handlers.onCodeComplete?.(data as SSECodeCompleteEvent);
      break;
    default:
      console.warn(`[SSE] Unknown event type: ${eventType}`);
  }
}
