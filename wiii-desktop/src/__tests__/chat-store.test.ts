/**
 * Unit tests for chat store (Zustand).
 * Tests conversation CRUD, message handling, streaming state.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "@/stores/chat-store";

// Reset store before each test
beforeEach(() => {
  useChatStore.setState({
    conversations: [],
    activeConversationId: null,
    isLoaded: false,
    isStreaming: false,
    streamingContent: "",
    streamingThinking: "",
    streamingSources: [],
    streamingStep: "",
    streamingBlocks: [],
    streamingStartTime: null,
    streamingSteps: [],
    streamCompletedAt: null,
    lastCompletedConversationId: null,
  });
});

describe("Chat Store — Conversations", () => {
  it("should create a conversation and set it as active", () => {
    const store = useChatStore.getState();
    const id = store.createConversation("maritime");

    expect(id).toBeTruthy();
    expect(useChatStore.getState().activeConversationId).toBe(id);
    expect(useChatStore.getState().conversations).toHaveLength(1);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.title).toBe("Cuộc trò chuyện mới");
    expect(conv.domain_id).toBe("maritime");
    expect(conv.messages).toEqual([]);
  });

  it("should create conversation without domain", () => {
    const store = useChatStore.getState();
    const id = store.createConversation();

    const conv = useChatStore.getState().conversations[0];
    expect(conv.id).toBe(id);
    expect(conv.domain_id).toBeUndefined();
  });

  it("should create multiple conversations", () => {
    const store = useChatStore.getState();
    const id1 = store.createConversation("maritime");
    const id2 = store.createConversation("traffic_law");

    expect(useChatStore.getState().conversations).toHaveLength(2);
    // Most recent conversation should be active
    expect(useChatStore.getState().activeConversationId).toBe(id2);
    // Most recent should be first in array (prepended)
    expect(useChatStore.getState().conversations[0].id).toBe(id2);
    expect(useChatStore.getState().conversations[1].id).toBe(id1);
  });

  it("should delete a conversation", () => {
    const store = useChatStore.getState();
    const id1 = store.createConversation("maritime");
    const id2 = store.createConversation("traffic_law");

    useChatStore.getState().deleteConversation(id2);

    expect(useChatStore.getState().conversations).toHaveLength(1);
    expect(useChatStore.getState().conversations[0].id).toBe(id1);
  });

  it("should switch active conversation when active is deleted", () => {
    const store = useChatStore.getState();
    const id1 = store.createConversation("maritime");
    store.createConversation("traffic_law");

    // Active is id2, delete it
    useChatStore.getState().deleteConversation(
      useChatStore.getState().activeConversationId!
    );

    // Should fall back to first remaining conversation
    expect(useChatStore.getState().activeConversationId).toBe(id1);
  });

  it("should set active conversation", () => {
    const store = useChatStore.getState();
    const id1 = store.createConversation("maritime");
    store.createConversation("traffic_law");

    useChatStore.getState().setActiveConversation(id1);
    expect(useChatStore.getState().activeConversationId).toBe(id1);
  });

  it("should rename a conversation", () => {
    const store = useChatStore.getState();
    const id = store.createConversation("maritime");

    useChatStore.getState().renameConversation(id, "My Custom Title");

    const conv = useChatStore.getState().conversations[0];
    expect(conv.title).toBe("My Custom Title");
  });
});

describe("Chat Store — Messages", () => {
  it("should add a user message to active conversation", () => {
    const store = useChatStore.getState();
    const convId = store.createConversation("maritime");

    useChatStore.getState().addUserMessage("Hello, Wiii!");

    const conv = useChatStore.getState().conversations.find((c) => c.id === convId)!;
    expect(conv.messages).toHaveLength(1);
    expect(conv.messages[0].role).toBe("user");
    expect(conv.messages[0].content).toBe("Hello, Wiii!");
    expect(conv.messages[0].id).toBeTruthy();
    expect(conv.messages[0].timestamp).toBeTruthy();
  });

  it("should auto-title from first message", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");

    useChatStore.getState().addUserMessage("Giải thích Quy tắc 15 COLREGs");

    const conv = useChatStore.getState().conversations[0];
    expect(conv.title).toBe("Giải thích Quy tắc 15 COLREGs");
  });

  it("should truncate long messages for auto-title", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");

    const longMessage = "A".repeat(100);
    useChatStore.getState().addUserMessage(longMessage);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.title.length).toBeLessThanOrEqual(53); // 50 chars + "..."
    expect(conv.title).toContain("...");
  });

  it("should not change title on second message", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");

    useChatStore.getState().addUserMessage("First question");
    useChatStore.getState().addUserMessage("Second question");

    const conv = useChatStore.getState().conversations[0];
    expect(conv.title).toBe("First question");
  });

  it("should return null when no active conversation", () => {
    const messageId = useChatStore.getState().addUserMessage("No conversation");
    expect(messageId).toBeNull();
  });
});

describe("Chat Store — Streaming", () => {
  it("should start streaming state", () => {
    useChatStore.getState().startStreaming();

    const state = useChatStore.getState();
    expect(state.isStreaming).toBe(true);
    expect(state.streamingContent).toBe("");
    expect(state.streamingThinking).toBe("");
    expect(state.streamingSources).toEqual([]);
    expect(state.streamingStep).toBe("");
  });

  it("should append streaming content", () => {
    useChatStore.getState().startStreaming();

    useChatStore.getState().appendStreamingContent("Hello ");
    useChatStore.getState().appendStreamingContent("world!");

    expect(useChatStore.getState().streamingContent).toBe("Hello world!");
  });

  it("strips split WIII_SOUL metadata from streaming answer content", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.appendStreamingContent('<! --WIII_SOUL: {"mood":"warm"');

    expect(useChatStore.getState().streamingContent).toBe("");

    store.appendStreamingContent("}--> Nut gui tin nhan.");

    expect(useChatStore.getState().streamingContent).toBe("Nut gui tin nhan.");
    expect(useChatStore.getState().streamingBlocks[0]?.type).toBe("answer");
  });

  it("should set streaming thinking", () => {
    useChatStore.getState().startStreaming();

    useChatStore.getState().setStreamingThinking("Step 1: Analyzing...");
    expect(useChatStore.getState().streamingThinking).toBe("Step 1: Analyzing...");

    // Second thinking should be concatenated
    useChatStore.getState().setStreamingThinking("Step 2: Retrieving...");
    expect(useChatStore.getState().streamingThinking).toBe(
      "Step 1: Analyzing...\nStep 2: Retrieving..."
    );
  });

  it("should dedupe identical streaming thinking lines when narrator repeats itself", () => {
    useChatStore.getState().startStreaming();

    useChatStore.getState().setStreamingThinking("Mình đang nghe xem câu này thực sự cần gì.");
    useChatStore.getState().setStreamingThinking("Mình đang nghe xem câu này thực sự cần gì.");

    const state = useChatStore.getState();
    expect(state.streamingThinking).toBe("Mình đang nghe xem câu này thực sự cần gì.");
    expect(state.streamingBlocks).toHaveLength(1);
    expect(state.streamingBlocks[0]?.type).toBe("thinking");
  });

  it("should set streaming step", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().setStreamingStep("retrieval");

    expect(useChatStore.getState().streamingStep).toBe("retrieval");
  });

  it("should set streaming sources", () => {
    useChatStore.getState().startStreaming();

    const sources = [
      { title: "COLREGs", content: "Rule 15", page_number: 42 },
    ];
    useChatStore.getState().setStreamingSources(sources);

    expect(useChatStore.getState().streamingSources).toEqual(sources);
  });

  it("should merge streaming sources from repeated source events", () => {
    useChatStore.getState().startStreaming();

    useChatStore.getState().setStreamingSources([
      {
        title: "Weather Hải Phòng",
        content: "Cloudy.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
    ]);
    useChatStore.getState().setStreamingSources([
      {
        title: "Weather Hải Phòng duplicate",
        content: "Cloudy duplicate.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
      {
        title: "Forecast",
        content: "Rain chance.",
        url: "https://meteo.example/forecast",
        source_type: "web",
      },
    ]);

    expect(useChatStore.getState().streamingSources).toEqual([
      {
        title: "Weather Hải Phòng",
        content: "Cloudy.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
      {
        title: "Forecast",
        content: "Rain chance.",
        url: "https://meteo.example/forecast",
        source_type: "web",
      },
    ]);
  });

  it("should attach late source events to the finalized assistant message", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("weather");
    store.startStreaming();
    store.appendStreamingContent("Weather answer.");

    useChatStore.getState().finalizeStream({
      processing_time: 2.4,
      model: "qwen",
      agent_type: "direct",
      request_id: "req-weather",
    } as any);

    useChatStore.getState().setStreamingSources([
      {
        title: "Hai Phong forecast",
        content: "Rain.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
    ]);
    useChatStore.getState().setStreamingSources([
      {
        title: "Hai Phong forecast duplicate",
        content: "Rain duplicate.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
      {
        title: "AccuWeather",
        content: "Cloudy.",
        url: "https://accuweather.example/hai-phong",
        source_type: "web",
      },
    ]);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.messages[1].sources).toEqual([
      {
        title: "Hai Phong forecast",
        content: "Rain.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
      {
        title: "AccuWeather",
        content: "Cloudy.",
        url: "https://accuweather.example/hai-phong",
        source_type: "web",
      },
    ]);
    expect(useChatStore.getState().streamingSources).toEqual([]);
  });

  it("attaches late source events to the finalized conversation after switching chats", () => {
    const store = useChatStore.getState();
    const firstId = store.createConversation("maritime");
    store.addUserMessage("weather");
    store.startStreaming();
    store.appendStreamingContent("Weather answer.");

    useChatStore.getState().finalizeStream({
      processing_time: 2.4,
      model: "qwen",
      agent_type: "direct",
      request_id: "req-weather",
    } as any);

    const secondId = useChatStore.getState().createConversation("maritime");
    expect(useChatStore.getState().activeConversationId).toBe(secondId);

    useChatStore.getState().setStreamingSources([
      {
        title: "Hai Phong forecast",
        content: "Rain.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
    ]);

    const state = useChatStore.getState();
    const first = state.conversations.find((item) => item.id === firstId);
    const second = state.conversations.find((item) => item.id === secondId);

    expect(first?.messages[1].sources).toEqual([
      {
        title: "Hai Phong forecast",
        content: "Rain.",
        url: "https://weather.example/hai-phong",
        source_type: "web",
      },
    ]);
    expect(
      second?.messages.some((message) => Boolean(message.sources?.length)),
    ).toBe(false);
  });

  it("should finalize stream into an assistant message", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test question");
    store.startStreaming();
    store.appendStreamingContent("This is the answer.");
    store.setStreamingThinking("I analyzed the question...");

    useChatStore.getState().finalizeStream({
      processing_time: 1.5,
      model: "gemini-pro",
      agent_type: "rag",
    });

    const state = useChatStore.getState();
    expect(state.isStreaming).toBe(false);
    expect(state.streamingContent).toBe("");
    expect(state.streamingThinking).toBe("");

    const conv = state.conversations[0];
    expect(conv.messages).toHaveLength(2); // user + assistant
    expect(conv.messages[1].role).toBe("assistant");
    expect(conv.messages[1].content).toBe("This is the answer.");
    expect(conv.messages[1].thinking).toBe("I analyzed the question...");
  });

  it("prefers richer metadata thinking when stream rail is thinner", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test question");
    store.startStreaming();
    store.appendStreamingContent("This is the answer.");
    store.setStreamingThinking("Mình đang chốt ý chính.");

    useChatStore.getState().finalizeStream({
      processing_time: 1.5,
      model: "gemini-pro",
      agent_type: "direct",
      thinking_content:
        "Mình đang chốt ý chính.\n\nSau đó mình nối lại The Wiii Lab và Bông để câu trả lời vẫn giữ đúng lõi sống của Wiii.",
    } as any);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.messages[1].thinking).toContain("The Wiii Lab");
    const thinkingBlock = conv.messages[1].blocks?.find((block) => block.type === "thinking");
    expect(thinkingBlock?.type).toBe("thinking");
    if (thinkingBlock?.type === "thinking") {
      expect(thinkingBlock.content).toContain("The Wiii Lab");
    }
  });

  it("ignores late metadata that belongs to a different request", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test question");
    store.startStreaming();
    store.appendStreamingContent("Fast answer.");

    useChatStore.getState().finalizeStream({
      processing_time: 1.2,
      model: "glm-5",
      agent_type: "rag",
      request_id: "req-fast",
    } as any);

    useChatStore.getState().setPendingStreamMetadata({
      processing_time: 112.1,
      model: "glm-5",
      agent_type: "rag",
      request_id: "req-stale",
    } as any);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.messages[1].metadata?.processing_time).toBe(1.2);
    expect(conv.messages[1].metadata?.request_id).toBe("req-fast");
  });

  it("allows a late metadata patch when the request id matches the current assistant turn", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test question");
    store.startStreaming();
    store.appendStreamingContent("Fast answer.");

    useChatStore.getState().finalizeStream({
      processing_time: 1.2,
      model: "glm-5",
      agent_type: "rag",
      request_id: "req-fast",
    } as any);

    useChatStore.getState().setPendingStreamMetadata({
      processing_time: 1.6,
      model: "glm-5",
      agent_type: "rag",
      request_id: "req-fast",
    } as any);

    const conv = useChatStore.getState().conversations[0];
    expect(conv.messages[1].metadata?.processing_time).toBe(1.6);
    expect(conv.messages[1].metadata?.request_id).toBe("req-fast");
  });

  it("should handle stream error", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test");
    store.startStreaming();

    useChatStore.getState().setStreamError("Connection timeout");

    const state = useChatStore.getState();
    expect(state.isStreaming).toBe(false);

    const conv = state.conversations[0];
    expect(conv.messages).toHaveLength(2);
    expect(conv.messages[1].role).toBe("assistant");
    expect(conv.messages[1].content).toContain("Connection timeout");
  });

  it("attaches structured metadata to stream error messages", () => {
    const store = useChatStore.getState();
    store.createConversation("maritime");
    store.addUserMessage("Test");
    store.startStreaming();

    useChatStore.getState().setStreamError("Provider unavailable", {
      provider: "google",
      reason_code: "rate_limit",
      model_switch_prompt: {
        title: "Doi model de tiep tuc?",
        message: "Gemini dang cham gioi han.",
        trigger: "provider_unavailable",
        options: [{ provider: "zhipu", label: "Zhipu GLM" }],
        allow_retry_once: true,
        allow_session_switch: true,
      },
    });

    const conv = useChatStore.getState().conversations[0];
    expect(conv.messages[1].metadata?.provider).toBe("google");
    expect(
      (conv.messages[1].metadata?.model_switch_prompt as { title?: string } | undefined)?.title,
    ).toBe("Doi model de tiep tuc?");
  });

  it("should clear streaming state", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().appendStreamingContent("partial");
    useChatStore.getState().setStreamingStep("thinking");

    useChatStore.getState().clearStreaming();

    const state = useChatStore.getState();
    expect(state.isStreaming).toBe(false);
    expect(state.streamingContent).toBe("");
    expect(state.streamingStep).toBe("");
  });
});

describe("Chat Store — Active Conversation Getter", () => {
  it("should return undefined when no conversations", () => {
    const conv = useChatStore.getState().activeConversation();
    expect(conv).toBeUndefined();
  });

  it("should return the active conversation", () => {
    const store = useChatStore.getState();
    const id = store.createConversation("maritime");

    const conv = useChatStore.getState().activeConversation();
    expect(conv).toBeDefined();
    expect(conv!.id).toBe(id);
  });
});
