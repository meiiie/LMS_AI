/**
 * Unit tests for Sprint 166: Preview Architecture — Cards, Store, Registry.
 * Tests type shapes, chat store preview actions, renderer registry,
 * SSE event type, UI store preview panel state, and settings defaults.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useSettingsStore } from "@/stores/settings-store";
import type {
  ContentBlock,
  PreviewItemData,
  PreviewBlockData,
  PreviewType,
  SSEEventType,
} from "@/api/types";

// ---- Helpers ----

function makePreviewItem(overrides?: Partial<PreviewItemData>): PreviewItemData {
  return {
    preview_type: "document",
    preview_id: `preview-${Math.random().toString(36).slice(2, 8)}`,
    title: "Test Document",
    snippet: "A short snippet",
    url: "https://example.com/doc",
    ...overrides,
  };
}

function getBlocks(): ContentBlock[] {
  return useChatStore.getState().streamingBlocks;
}

function findPreviewBlocks(blocks: ContentBlock[]): PreviewBlockData[] {
  return blocks.filter((b) => b.type === "preview") as PreviewBlockData[];
}

// ---- Reset stores before each test ----

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
    streamingDomainNotice: "",
    streamingPhases: [],
    streamingPreviews: [],
    _activeSubagentGroupId: null,
    streamError: "",
    streamCompletedAt: null,
  });

  useUIStore.setState({
    sidebarOpen: true,
    activeView: "chat",
    sourcesPanelOpen: false,
    selectedSourceIndex: null,
    commandPaletteOpen: false,
    inputFocused: false,
    characterPanelOpen: false,
    previewPanelOpen: false,
    selectedPreviewId: null,
  });
});

// =============================================================================
// 1. PreviewItemData type shape tests (4)
// =============================================================================
describe("PreviewItemData — Type Shape", () => {
  it("has required fields: preview_type, preview_id, title", () => {
    const item: PreviewItemData = {
      preview_type: "document",
      preview_id: "doc-001",
      title: "COLREG Rule 7",
    };
    expect(item.preview_type).toBe("document");
    expect(item.preview_id).toBe("doc-001");
    expect(item.title).toBe("COLREG Rule 7");
  });

  it("accepts all five preview types", () => {
    const types: PreviewType[] = ["document", "product", "web", "link", "code", "host_action"];
    for (const t of types) {
      const item: PreviewItemData = {
        preview_type: t,
        preview_id: `${t}-1`,
        title: `Title for ${t}`,
      };
      expect(item.preview_type).toBe(t);
    }
  });

  it("supports optional fields: snippet, url, image_url, citation_index, metadata", () => {
    const item: PreviewItemData = {
      preview_type: "product",
      preview_id: "prod-001",
      title: "Test Product",
      snippet: "A great product",
      url: "https://shopee.vn/item/123",
      image_url: "https://img.shopee.vn/123.jpg",
      citation_index: 1,
      metadata: { price: "500.000 VND", rating: 4.5 },
    };
    expect(item.snippet).toBe("A great product");
    expect(item.url).toContain("shopee.vn");
    expect(item.image_url).toContain("123.jpg");
    expect(item.citation_index).toBe(1);
    expect(item.metadata?.price).toBe("500.000 VND");
  });

  it("allows undefined optional fields", () => {
    const item: PreviewItemData = {
      preview_type: "web",
      preview_id: "web-001",
      title: "Search Result",
    };
    expect(item.snippet).toBeUndefined();
    expect(item.url).toBeUndefined();
    expect(item.image_url).toBeUndefined();
    expect(item.citation_index).toBeUndefined();
    expect(item.metadata).toBeUndefined();
  });

  it("supports host action preview metadata for operator flows", () => {
    const item: PreviewItemData = {
      preview_type: "host_action",
      preview_id: "host-action-1",
      title: "Xem trước cập nhật bài học",
      snippet: "Preview ready. Confirm explicitly when you want me to apply it.",
      metadata: {
        preview_kind: "lesson_patch",
        preview_token: "preview-123",
        lesson_id: "lesson-1",
        changed_fields: ["title", "content"],
      },
    };
    expect(item.preview_type).toBe("host_action");
    expect(item.metadata?.preview_kind).toBe("lesson_patch");
  });
});

// =============================================================================
// 2. PreviewBlockData type shape tests (3)
// =============================================================================
describe("PreviewBlockData — Type Shape", () => {
  it("has type='preview', id, and items array", () => {
    const block: PreviewBlockData = {
      type: "preview",
      id: "block-001",
      items: [makePreviewItem()],
    };
    expect(block.type).toBe("preview");
    expect(block.id).toBeTruthy();
    expect(block.items).toHaveLength(1);
  });

  it("supports optional node field", () => {
    const block: PreviewBlockData = {
      type: "preview",
      id: "block-002",
      items: [],
      node: "rag_agent",
    };
    expect(block.node).toBe("rag_agent");
  });

  it("is included in ContentBlock union", () => {
    const blocks: ContentBlock[] = [
      { type: "preview", id: "block-003", items: [makePreviewItem()] },
    ];
    expect(blocks[0].type).toBe("preview");
  });
});

// =============================================================================
// 3. Chat store: addPreviewItem tests (6)
// =============================================================================
describe("Chat Store — addPreviewItem", () => {
  it("adds item to streamingPreviews", () => {
    useChatStore.getState().startStreaming();
    const item = makePreviewItem({ preview_id: "p1" });
    useChatStore.getState().addPreviewItem(item, "rag_agent");

    const previews = useChatStore.getState().streamingPreviews;
    expect(previews).toHaveLength(1);
    expect(previews[0].preview_id).toBe("p1");
  });

  it("dedup by preview_id — adding same ID twice only stores once", () => {
    useChatStore.getState().startStreaming();
    const item = makePreviewItem({ preview_id: "dup-1" });
    useChatStore.getState().addPreviewItem(item, "rag_agent");
    useChatStore.getState().addPreviewItem(item, "rag_agent");

    const previews = useChatStore.getState().streamingPreviews;
    expect(previews).toHaveLength(1);
  });

  it("creates new preview block in streamingBlocks", () => {
    useChatStore.getState().startStreaming();
    const item = makePreviewItem({ preview_id: "p2" });
    useChatStore.getState().addPreviewItem(item, "rag_agent");

    const blocks = getBlocks();
    const previewBlocks = findPreviewBlocks(blocks);
    expect(previewBlocks).toHaveLength(1);
    expect(previewBlocks[0].items).toHaveLength(1);
    expect(previewBlocks[0].node).toBe("rag_agent");
  });

  it("groups adjacent previews from same node into single block", () => {
    useChatStore.getState().startStreaming();
    const item1 = makePreviewItem({ preview_id: "p3", title: "Doc 1" });
    const item2 = makePreviewItem({ preview_id: "p4", title: "Doc 2" });

    useChatStore.getState().addPreviewItem(item1, "rag_agent");
    useChatStore.getState().addPreviewItem(item2, "rag_agent");

    const previewBlocks = findPreviewBlocks(getBlocks());
    expect(previewBlocks).toHaveLength(1);
    expect(previewBlocks[0].items).toHaveLength(2);
    expect(previewBlocks[0].items[0].title).toBe("Doc 1");
    expect(previewBlocks[0].items[1].title).toBe("Doc 2");
  });

  it("creates separate block when node changes", () => {
    useChatStore.getState().startStreaming();
    const item1 = makePreviewItem({ preview_id: "p5" });
    const item2 = makePreviewItem({ preview_id: "p6" });

    useChatStore.getState().addPreviewItem(item1, "rag_agent");
    // Insert an answer block to break the sequence
    useChatStore.getState().appendStreamingContent("Some answer text");
    useChatStore.getState().addPreviewItem(item2, "direct_agent");

    const previewBlocks = findPreviewBlocks(getBlocks());
    expect(previewBlocks).toHaveLength(2);
    expect(previewBlocks[0].node).toBe("rag_agent");
    expect(previewBlocks[1].node).toBe("direct_agent");
  });

  it("creates separate block when different node even if adjacent", () => {
    useChatStore.getState().startStreaming();
    const item1 = makePreviewItem({ preview_id: "p7" });
    const item2 = makePreviewItem({ preview_id: "p8" });

    useChatStore.getState().addPreviewItem(item1, "rag_agent");
    useChatStore.getState().addPreviewItem(item2, "tutor_agent");

    const previewBlocks = findPreviewBlocks(getBlocks());
    expect(previewBlocks).toHaveLength(2);
    expect(previewBlocks[0].node).toBe("rag_agent");
    expect(previewBlocks[1].node).toBe("tutor_agent");
  });
});

// =============================================================================
// 4. Chat store: startStreaming resets (1)
// =============================================================================
describe("Chat Store — startStreaming resets previews", () => {
  it("streamingPreviews clears on startStreaming", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().addPreviewItem(makePreviewItem(), "rag");

    expect(useChatStore.getState().streamingPreviews).toHaveLength(1);

    useChatStore.getState().startStreaming();

    expect(useChatStore.getState().streamingPreviews).toHaveLength(0);
    expect(getBlocks()).toHaveLength(0);
  });
});

// =============================================================================
// 5. Chat store: finalizeStream persists previews (2)
// =============================================================================
describe("Chat Store — finalizeStream persists previews", () => {
  it("previews are saved to the finalized message", () => {
    const convId = "test-conv-166-preview";
    useChatStore.setState({
      activeConversationId: convId,
      conversations: [
        {
          id: convId,
          title: "Test Preview Conv",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          messages: [
            { id: "msg-u1", role: "user", content: "Show me documents", timestamp: new Date().toISOString() },
          ],
        },
      ],
    });

    const store = useChatStore.getState();
    store.startStreaming();

    const item1 = makePreviewItem({ preview_id: "final-p1", preview_type: "document" });
    const item2 = makePreviewItem({ preview_id: "final-p2", preview_type: "product" });
    store.addPreviewItem(item1, "rag_agent");
    store.addPreviewItem(item2, "product_search");
    store.appendStreamingContent("Here are the results.");

    store.finalizeStream({ processing_time: 1.5, model: "gemini", agent_type: "rag" } as any);

    const freshState = useChatStore.getState();
    const conv = freshState.conversations[0];
    const lastMsg = conv.messages[conv.messages.length - 1];

    expect(lastMsg.role).toBe("assistant");
    expect(lastMsg.previews).toBeDefined();
    expect(lastMsg.previews).toHaveLength(2);
    expect(lastMsg.previews![0].preview_id).toBe("final-p1");
    expect(lastMsg.previews![1].preview_id).toBe("final-p2");
  });

  it("preview blocks are preserved in saved message blocks", () => {
    const convId = "test-conv-166-blocks";
    useChatStore.setState({
      activeConversationId: convId,
      conversations: [
        {
          id: convId,
          title: "Test",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          messages: [
            { id: "msg-u2", role: "user", content: "Q?", timestamp: new Date().toISOString() },
          ],
        },
      ],
    });

    const store = useChatStore.getState();
    store.startStreaming();
    store.addPreviewItem(makePreviewItem({ preview_id: "blk-p1" }), "rag");
    store.appendStreamingContent("Answer.");
    store.finalizeStream({ processing_time: 0.5, model: "gemini", agent_type: "rag" } as any);

    const conv = useChatStore.getState().conversations[0];
    const lastMsg = conv.messages[conv.messages.length - 1];
    expect(lastMsg.blocks).toBeDefined();

    const previewBlock = lastMsg.blocks!.find((b) => b.type === "preview");
    expect(previewBlock).toBeDefined();
    expect((previewBlock as PreviewBlockData).items).toHaveLength(1);
  });
});

// =============================================================================
// 6. Preview renderer registry (5)
// =============================================================================
describe("Preview Renderer Registry", () => {
  // We test the registry's dispatch by importing and verifying that the
  // correct component exists for each type. Since these are React components
  // and we're doing logic-only tests, we verify the PREVIEW_REGISTRY mapping
  // via the exports from the previews index.

  it("exports PreviewCardRenderer function", { timeout: 15_000 }, async () => {
    const mod = await import("@/components/chat/previews/index");
    expect(typeof mod.PreviewCardRenderer).toBe("function");
  });

  it("exports DocumentPreviewCard", { timeout: 15_000 }, async () => {
    const mod = await import("@/components/chat/previews/index");
    expect(typeof mod.DocumentPreviewCard).toBe("function");
  });

  it("exports ProductPreviewCard", async () => {
    const mod = await import("@/components/chat/previews/index");
    expect(typeof mod.ProductPreviewCard).toBe("function");
  });

  it("exports WebPreviewCard", async () => {
    const mod = await import("@/components/chat/previews/index");
    expect(typeof mod.WebPreviewCard).toBe("function");
  });

  it("exports CodePreviewCard and LinkPreviewCard", async () => {
    const mod = await import("@/components/chat/previews/index");
    expect(typeof mod.CodePreviewCard).toBe("function");
    expect(typeof mod.LinkPreviewCard).toBe("function");
  });
});

// =============================================================================
// 7. SSE event type includes "preview" (1)
// =============================================================================
describe("SSE Event Type", () => {
  it('"preview" is a valid SSEEventType value', () => {
    // TypeScript compile-time check: assigning "preview" to SSEEventType
    const eventType: SSEEventType = "preview";
    expect(eventType).toBe("preview");

    // Verify it is one of the known event types
    const allTypes: SSEEventType[] = [
      "thinking", "thinking_delta", "answer", "sources", "metadata",
      "done", "error", "tool_call", "tool_result", "status",
      "thinking_start", "thinking_end", "domain_notice",
      "emotion", "action_text", "browser_screenshot", "preview",
    ];
    expect(allTypes).toContain("preview");
  });
});

// =============================================================================
// 8. UI store: preview panel state (5)
// =============================================================================
describe("UI Store — Preview Panel State", () => {
  it("openPreview sets previewPanelOpen and selectedPreviewId", () => {
    useUIStore.getState().openPreview("preview-abc");

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(true);
    expect(state.selectedPreviewId).toBe("preview-abc");
  });

  it("closePreview clears both previewPanelOpen and selectedPreviewId", () => {
    useUIStore.getState().openPreview("preview-xyz");
    useUIStore.getState().closePreview();

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(false);
    expect(state.selectedPreviewId).toBeNull();
  });

  it("openPreview closes sourcesPanelOpen (mutual exclusion)", () => {
    // Open sources panel first
    useUIStore.getState().toggleSourcesPanel();
    expect(useUIStore.getState().sourcesPanelOpen).toBe(true);

    // Open preview — should close sources
    useUIStore.getState().openPreview("preview-mut");

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(true);
    expect(state.sourcesPanelOpen).toBe(false);
  });

  it("closeAll clears preview panel state", () => {
    useUIStore.getState().openPreview("preview-all");
    expect(useUIStore.getState().previewPanelOpen).toBe(true);

    useUIStore.getState().closeAll();

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(false);
    expect(state.selectedPreviewId).toBeNull();
    expect(state.activeView).toBe("chat");
    expect(state.commandPaletteOpen).toBe(false);
    expect(state.sourcesPanelOpen).toBe(false);
    expect(state.characterPanelOpen).toBe(false);
  });

  it("togglePreviewPanel toggles previewPanelOpen", () => {
    expect(useUIStore.getState().previewPanelOpen).toBe(false);

    useUIStore.getState().togglePreviewPanel();
    expect(useUIStore.getState().previewPanelOpen).toBe(true);

    useUIStore.getState().togglePreviewPanel();
    expect(useUIStore.getState().previewPanelOpen).toBe(false);
  });
});

// =============================================================================
// 9. Settings store — show_previews defaults (2)
// =============================================================================
describe("Settings Store — show_previews", () => {
  it("show_previews defaults to true", () => {
    const settings = useSettingsStore.getState().settings;
    expect(settings.show_previews).toBe(true);
  });

  it("show_previews can be toggled to false", async () => {
    await useSettingsStore.getState().updateSettings({ show_previews: false });
    expect(useSettingsStore.getState().settings.show_previews).toBe(false);

    await useSettingsStore.getState().updateSettings({ show_previews: true });
    expect(useSettingsStore.getState().settings.show_previews).toBe(true);
  });
});
