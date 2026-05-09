/**
 * Unit tests for chat store persistence.
 * Tests loadConversations, persist after mutations, and debounce behavior.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useChatStore } from "@/stores/chat-store";

// Mock the storage module
vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn().mockResolvedValue([]),
  saveStore: vi.fn().mockResolvedValue(undefined),
}));

import { loadStore, saveStore } from "@/lib/storage";

const mockLoadStore = vi.mocked(loadStore);
const mockSaveStore = vi.mocked(saveStore);

// Reset store and mocks before each test
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
    streamingToolCalls: [],
    streamingBlocks: [],
    streamingStartTime: null,
    streamingSteps: [],
  });
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Chat Persistence — loadConversations", () => {
  it("should load empty conversations", async () => {
    mockLoadStore.mockResolvedValue([]);

    await useChatStore.getState().loadConversations();

    const state = useChatStore.getState();
    expect(state.isLoaded).toBe(true);
    expect(state.conversations).toEqual([]);
    expect(state.activeConversationId).toBeNull();
  });

  it("should load saved conversations and set first as active", async () => {
    const savedConversations = [
      {
        id: "conv-1",
        title: "Maritime Safety",
        domain_id: "maritime",
        created_at: "2026-02-09T00:00:00Z",
        updated_at: "2026-02-09T00:00:00Z",
        messages: [
          {
            id: "msg-1",
            role: "user" as const,
            content: "What is COLREGs?",
            timestamp: "2026-02-09T00:00:00Z",
          },
        ],
      },
      {
        id: "conv-2",
        title: "Traffic Law",
        domain_id: "traffic_law",
        created_at: "2026-02-08T00:00:00Z",
        updated_at: "2026-02-08T00:00:00Z",
        messages: [],
      },
    ];

    mockLoadStore.mockResolvedValue(savedConversations);

    await useChatStore.getState().loadConversations();

    const state = useChatStore.getState();
    expect(state.isLoaded).toBe(true);
    expect(state.conversations).toHaveLength(2);
    expect(state.activeConversationId).toBe("conv-1");
    expect(state.conversations[0].title).toBe("Maritime Safety");
    expect(state.conversations[0].messages).toHaveLength(1);
  });

  it("should handle load failure gracefully", async () => {
    mockLoadStore.mockRejectedValue(new Error("Storage unavailable"));

    await useChatStore.getState().loadConversations();

    const state = useChatStore.getState();
    expect(state.isLoaded).toBe(true);
    expect(state.conversations).toEqual([]);
  });

  it("should call loadStore with correct params", async () => {
    await useChatStore.getState().loadConversations();

    expect(mockLoadStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      []
    );
  });
});

describe("Chat Persistence — Save after mutations", () => {
  it("should persist immediately after createConversation", async () => {
    useChatStore.getState().createConversation("maritime");

    // Immediate persist — flush timers
    await vi.advanceTimersByTimeAsync(0);

    expect(mockSaveStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      expect.arrayContaining([
        expect.objectContaining({
          domain_id: "maritime",
          title: "Cuộc trò chuyện mới",
        }),
      ])
    );
  });

  it("should persist immediately after deleteConversation", async () => {
    const id = useChatStore.getState().createConversation("maritime");
    vi.clearAllMocks();

    useChatStore.getState().deleteConversation(id);
    await vi.advanceTimersByTimeAsync(0);

    expect(mockSaveStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      []
    );
  });

  it("should persist immediately after renameConversation", async () => {
    const id = useChatStore.getState().createConversation("maritime");
    vi.clearAllMocks();

    useChatStore.getState().renameConversation(id, "Renamed");
    await vi.advanceTimersByTimeAsync(0);

    expect(mockSaveStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      expect.arrayContaining([
        expect.objectContaining({ title: "Renamed" }),
      ])
    );
  });

  it("should debounce persist after addUserMessage", async () => {
    useChatStore.getState().createConversation("maritime");
    vi.clearAllMocks();

    useChatStore.getState().addUserMessage("Hello");

    // Should not persist immediately
    await vi.advanceTimersByTimeAsync(100);
    // The immediate persist from createConversation is cleared, new one from addUserMessage is debounced
    const callsBeforeDebounce = mockSaveStore.mock.calls.length;

    // After debounce interval (2s)
    await vi.advanceTimersByTimeAsync(2000);

    expect(mockSaveStore.mock.calls.length).toBeGreaterThan(callsBeforeDebounce);
  });

  it("should persist immediately after finalizeStream", async () => {
    useChatStore.getState().createConversation("maritime");
    useChatStore.getState().addUserMessage("Test");
    useChatStore.getState().startStreaming();
    useChatStore.getState().appendStreamingContent("Answer");
    vi.clearAllMocks();

    useChatStore.getState().finalizeStream({
      processing_time: 1.0,
      model: "gemini",
      agent_type: "rag",
    });

    await vi.advanceTimersByTimeAsync(0);

    expect(mockSaveStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      expect.arrayContaining([
        expect.objectContaining({
          messages: expect.arrayContaining([
            expect.objectContaining({ role: "user", content: "Test" }),
            expect.objectContaining({ role: "assistant", content: "Answer" }),
          ]),
        }),
      ])
    );
  });

  it("should persist immediately after setStreamError", async () => {
    useChatStore.getState().createConversation("maritime");
    useChatStore.getState().addUserMessage("Test");
    useChatStore.getState().startStreaming();
    vi.clearAllMocks();

    useChatStore.getState().setStreamError("Timeout");

    await vi.advanceTimersByTimeAsync(0);

    expect(mockSaveStore).toHaveBeenCalledWith(
      "conversations.json",
      "conversations",
      expect.arrayContaining([
        expect.objectContaining({
          messages: expect.arrayContaining([
            expect.objectContaining({
              role: "assistant",
              content: expect.stringContaining("Timeout"),
            }),
          ]),
        }),
      ])
    );
  });
});

describe("Chat Persistence — isLoaded flag", () => {
  it("should start as false", () => {
    expect(useChatStore.getState().isLoaded).toBe(false);
  });

  it("should be true after successful load", async () => {
    mockLoadStore.mockResolvedValue([]);
    await useChatStore.getState().loadConversations();
    expect(useChatStore.getState().isLoaded).toBe(true);
  });

  it("should be true even after failed load", async () => {
    mockLoadStore.mockRejectedValue(new Error("fail"));
    await useChatStore.getState().loadConversations();
    expect(useChatStore.getState().isLoaded).toBe(true);
  });

  it("should remain true after logout clear so App can leave boot splash", () => {
    useChatStore.setState({
      conversations: [
        {
          id: "conv-logout",
          title: "Logout case",
          domain_id: "maritime",
          created_at: "2026-05-09T00:00:00Z",
          updated_at: "2026-05-09T00:00:00Z",
          messages: [],
        },
      ],
      activeConversationId: "conv-logout",
      isLoaded: true,
    });

    useChatStore.getState().clearForLogout();

    const state = useChatStore.getState();
    expect(state.conversations).toEqual([]);
    expect(state.activeConversationId).toBeNull();
    expect(state.isLoaded).toBe(true);
  });
});
