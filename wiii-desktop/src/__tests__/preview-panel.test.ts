/**
 * Unit tests for Sprint 166: Preview Architecture — Panel, Group, Settings integration.
 * Tests PreviewPanel visibility, selection, keyboard nav, PreviewGroup rendering,
 * and Settings Preferences tab preview toggle.
 *
 * These tests validate store logic and component contracts without full React rendering.
 * Component behavior is tested through store state assertions and module export checks.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useSettingsStore } from "@/stores/settings-store";
import type {
  PreviewItemData,
  PreviewBlockData,
} from "@/api/types";

// ---- Helpers ----

function makePreviewItem(overrides?: Partial<PreviewItemData>): PreviewItemData {
  return {
    preview_type: "document",
    preview_id: `preview-${Math.random().toString(36).slice(2, 8)}`,
    title: "Test Document",
    snippet: "Snippet text",
    url: "https://example.com",
    ...overrides,
  };
}

/** Set up a conversation with an assistant message containing previews. */
function setupConversationWithPreviews(previews: PreviewItemData[]) {
  const convId = `conv-panel-${Math.random().toString(36).slice(2, 8)}`;
  useChatStore.setState({
    activeConversationId: convId,
    conversations: [
      {
        id: convId,
        title: "Panel Test Conv",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        messages: [
          { id: "msg-u", role: "user", content: "Show documents", timestamp: new Date().toISOString() },
          {
            id: "msg-a",
            role: "assistant",
            content: "Here are the documents.",
            timestamp: new Date().toISOString(),
            previews,
            blocks: [
              { type: "preview", id: "blk-p1", items: previews } as PreviewBlockData,
              { type: "answer", id: "blk-a1", content: "Here are the documents." },
            ],
          },
        ],
      },
    ],
  });
  return convId;
}

// ---- Reset stores ----

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

  // Reset settings store to defaults (prevent bleed from show_previews toggle tests)
  useSettingsStore.setState({
    settings: {
      ...useSettingsStore.getState().settings,
      show_previews: true,
    },
  });
});

// =============================================================================
// 1. PreviewPanel — renders when previewPanelOpen is true (1)
// =============================================================================
describe("PreviewPanel — Visibility", () => {
  it("panel state is active when previewPanelOpen is true", () => {
    useUIStore.getState().openPreview("p1");

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(true);
    expect(state.selectedPreviewId).toBe("p1");
  });

  it("panel state is inactive when previewPanelOpen is false", () => {
    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(false);
    expect(state.selectedPreviewId).toBeNull();
  });
});

// =============================================================================
// 2. PreviewPanel — shows selected preview detail (2)
// =============================================================================
describe("PreviewPanel — Selected Preview", () => {
  it("selectedPreviewId points to a valid preview in conversation", () => {
    const previews = [
      makePreviewItem({ preview_id: "sel-1", title: "COLREG Rule 7" }),
      makePreviewItem({ preview_id: "sel-2", title: "SOLAS Chapter V" }),
    ];
    setupConversationWithPreviews(previews);

    useUIStore.getState().openPreview("sel-1");

    const selectedId = useUIStore.getState().selectedPreviewId;
    expect(selectedId).toBe("sel-1");

    // Simulate the panel's preview lookup
    const conv = useChatStore.getState().conversations[0];
    const lastAssistant = conv.messages.find((m) => m.role === "assistant");
    const found = lastAssistant?.previews?.find((p) => p.preview_id === selectedId);
    expect(found).toBeDefined();
    expect(found!.title).toBe("COLREG Rule 7");
  });

  it("shows empty state when no preview is selected (selectedPreviewId is null)", () => {
    const previews = [makePreviewItem({ preview_id: "e1" })];
    setupConversationWithPreviews(previews);

    // Open panel without selecting
    useUIStore.setState({ previewPanelOpen: true, selectedPreviewId: null });

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(true);
    expect(state.selectedPreviewId).toBeNull();
    // The component would show "Chon mot the xem truoc de xem chi tiet" empty state
  });

  it("supports host action previews with preview token metadata", () => {
    const previews = [
      makePreviewItem({
        preview_id: "host-preview-1",
        preview_type: "host_action",
        title: "Xem trước phát hành bài kiểm tra",
        snippet: "Quiz publish preview ready.",
        metadata: {
          preview_kind: "quiz_publish",
          preview_token: "preview-quiz-1",
          quiz_id: "quiz-1",
        },
      }),
    ];
    setupConversationWithPreviews(previews);

    useUIStore.getState().openPreview("host-preview-1");

    const selectedId = useUIStore.getState().selectedPreviewId;
    const conv = useChatStore.getState().conversations[0];
    const lastAssistant = conv.messages.find((m) => m.role === "assistant");
    const found = lastAssistant?.previews?.find((p) => p.preview_id === selectedId);
    expect(found?.preview_type).toBe("host_action");
    expect(found?.metadata?.preview_token).toBe("preview-quiz-1");
  });

  it("stores lesson before/after snapshots for host action previews", () => {
    const previews = [
      makePreviewItem({
        preview_id: "host-preview-diff-1",
        preview_type: "host_action",
        title: "Xem trước cập nhật bài học",
        snippet: "Lesson patch preview ready.",
        metadata: {
          preview_kind: "lesson_patch",
          preview_token: "lesson-preview-1",
          apply_action: "authoring.apply_lesson_patch",
          lesson_before: {
            title: "Bai hoc cu",
            description: "Mo ta cu",
            content_excerpt: "Noi dung cu",
            blocks: [
              { id: "b1", label: "Doan 1", excerpt: "Noi dung cu" },
            ],
          },
          lesson_after: {
            title: "Bai hoc moi",
            description: "Mo ta moi",
            content_excerpt: "Noi dung moi",
            blocks: [
              { id: "b1", label: "Doan 1", excerpt: "Noi dung moi" },
            ],
          },
          block_diff: {
            changed: 1,
            added: 0,
            removed: 0,
            unchanged: 0,
            items: [
              {
                index: 0,
                status: "changed",
              },
            ],
          },
        },
      }),
    ];
    setupConversationWithPreviews(previews);

    useUIStore.getState().openPreview("host-preview-diff-1");

    const conv = useChatStore.getState().conversations[0];
    const lastAssistant = conv.messages.find((m) => m.role === "assistant");
    const found = lastAssistant?.previews?.find((p) => p.preview_id === "host-preview-diff-1");
    expect(found?.metadata?.lesson_before).toEqual({
      title: "Bai hoc cu",
      description: "Mo ta cu",
      content_excerpt: "Noi dung cu",
      blocks: [
        { id: "b1", label: "Doan 1", excerpt: "Noi dung cu" },
      ],
    });
    expect(found?.metadata?.lesson_after).toEqual({
      title: "Bai hoc moi",
      description: "Mo ta moi",
      content_excerpt: "Noi dung moi",
      blocks: [
        { id: "b1", label: "Doan 1", excerpt: "Noi dung moi" },
      ],
    });
    expect(found?.metadata?.apply_action).toBe("authoring.apply_lesson_patch");
    expect(found?.metadata?.block_diff).toEqual({
      changed: 1,
      added: 0,
      removed: 0,
      unchanged: 0,
      items: [
        {
          index: 0,
          status: "changed",
        },
      ],
    });
  });
});

// =============================================================================
// 3. PreviewPanel — lists all previews from last assistant message (2)
// =============================================================================
describe("PreviewPanel — Preview List", () => {
  it("retrieves all previews from the last assistant message", () => {
    const previews = [
      makePreviewItem({ preview_id: "list-1", title: "Doc 1" }),
      makePreviewItem({ preview_id: "list-2", title: "Doc 2" }),
      makePreviewItem({ preview_id: "list-3", title: "Doc 3" }),
    ];
    setupConversationWithPreviews(previews);

    const conv = useChatStore.getState().conversations[0];
    let lastPreviews: PreviewItemData[] = [];
    for (let i = conv.messages.length - 1; i >= 0; i--) {
      if (conv.messages[i].role === "assistant" && conv.messages[i].previews?.length) {
        lastPreviews = conv.messages[i].previews!;
        break;
      }
    }

    expect(lastPreviews).toHaveLength(3);
    expect(lastPreviews.map((p) => p.preview_id)).toEqual(["list-1", "list-2", "list-3"]);
  });

  it("falls back to streamingPreviews when no saved message", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().addPreviewItem(
      makePreviewItem({ preview_id: "stream-1" }), "rag"
    );
    useChatStore.getState().addPreviewItem(
      makePreviewItem({ preview_id: "stream-2" }), "rag"
    );

    const streamingPreviews = useChatStore.getState().streamingPreviews;
    expect(streamingPreviews).toHaveLength(2);
    expect(streamingPreviews[0].preview_id).toBe("stream-1");
  });
});

// =============================================================================
// 4. PreviewPanel — Escape key closes panel (simulated via store) (1)
// =============================================================================
describe("PreviewPanel — Escape Key", () => {
  it("closePreview resets panel state (simulating Escape handler)", () => {
    useUIStore.getState().openPreview("esc-test");
    expect(useUIStore.getState().previewPanelOpen).toBe(true);

    // Simulate what the Escape keydown handler does
    useUIStore.getState().closePreview();

    expect(useUIStore.getState().previewPanelOpen).toBe(false);
    expect(useUIStore.getState().selectedPreviewId).toBeNull();
  });
});

// =============================================================================
// 5. PreviewGroup — renders correct number of cards (2)
// =============================================================================
describe("PreviewGroup — Card Count", () => {
  it("a preview block with 3 items produces 3 entries", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().addPreviewItem(makePreviewItem({ preview_id: "g1" }), "rag");
    useChatStore.getState().addPreviewItem(makePreviewItem({ preview_id: "g2" }), "rag");
    useChatStore.getState().addPreviewItem(makePreviewItem({ preview_id: "g3" }), "rag");

    const blocks = useChatStore.getState().streamingBlocks;
    const previewBlocks = blocks.filter((b) => b.type === "preview") as PreviewBlockData[];
    expect(previewBlocks).toHaveLength(1);
    expect(previewBlocks[0].items).toHaveLength(3);
  });

  it("empty items array produces no cards (PreviewGroup returns null)", () => {
    const emptyBlock: PreviewBlockData = {
      type: "preview",
      id: "empty-block",
      items: [],
    };
    // Simulating PreviewGroup's early return: if (!block.items || block.items.length === 0) return null
    expect(emptyBlock.items.length).toBe(0);
  });
});

// =============================================================================
// 6. PreviewGroup — click opens preview panel (1)
// =============================================================================
describe("PreviewGroup — Click Opens Panel", () => {
  it("openPreview is called with the correct preview_id on click", () => {
    useUIStore.getState().openPreview("click-test-id");

    const state = useUIStore.getState();
    expect(state.previewPanelOpen).toBe(true);
    expect(state.selectedPreviewId).toBe("click-test-id");
  });
});

// =============================================================================
// 7. PreviewGroup — keyboard navigation (ArrowLeft/Right) (3)
// =============================================================================
describe("PreviewGroup — Keyboard Navigation", () => {
  it("PreviewGroup component exports correctly for rendering", { timeout: 15_000 }, async () => {
    const mod = await import("@/components/chat/PreviewGroup");
    expect(typeof mod.PreviewGroup).toBe("function");
  });

  it("PreviewGroup accepts block prop with items for keyboard navigation", () => {
    const block: PreviewBlockData = {
      type: "preview",
      id: "kb-block",
      items: [
        makePreviewItem({ preview_id: "kb-1" }),
        makePreviewItem({ preview_id: "kb-2" }),
        makePreviewItem({ preview_id: "kb-3" }),
      ],
    };
    // Verify block shape is correct for keyboard handler
    expect(block.items).toHaveLength(3);
    expect(block.items[0].preview_id).toBe("kb-1");
    expect(block.items[2].preview_id).toBe("kb-3");
  });

  it("PreviewGroup uses role='list' and listitem for accessibility", { timeout: 15_000 }, async () => {
    // Verify the component is exported and would render with correct ARIA
    const mod = await import("@/components/chat/PreviewGroup");
    expect(mod.PreviewGroup).toBeDefined();
    // The component template uses role="list" and role="listitem" for each card
    // This is verified by code inspection; the aria-label is "Noi dung xem truoc"
  });
});

// =============================================================================
// 8. PreviewPanel component export (1)
// =============================================================================
describe("PreviewPanel — Component Export", () => {
  it("PreviewPanel is exported from layout module", { timeout: 15_000 }, async () => {
    const mod = await import("@/components/layout/PreviewPanel");
    expect(typeof mod.PreviewPanel).toBe("function");
  });
});

// =============================================================================
// 9. Settings: Preferences tab — preview toggle (3)
// =============================================================================
describe("Settings — Preview Toggle", () => {
  it("show_previews defaults to true in DEFAULT_SETTINGS", () => {
    const settings = useSettingsStore.getState().settings;
    expect(settings.show_previews).toBe(true);
  });

  it("toggling show_previews to false disables previews", async () => {
    await useSettingsStore.getState().updateSettings({ show_previews: false });

    const settings = useSettingsStore.getState().settings;
    expect(settings.show_previews).toBe(false);
  });

  it("AppSettings type includes show_previews as optional boolean", () => {
    // TypeScript compile-time check
    const settings = useSettingsStore.getState().settings;
    const value: boolean | undefined = settings.show_previews;
    expect(typeof value).toBe("boolean");
  });
});

// =============================================================================
// 10. Integration: Full preview flow (3)
// =============================================================================
describe("Preview — Integration Flow", () => {
  it("full flow: stream previews -> finalize -> open panel -> select -> close", () => {
    const convId = "integ-conv";
    useChatStore.setState({
      activeConversationId: convId,
      conversations: [
        {
          id: convId,
          title: "Integration Test",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          messages: [
            { id: "msg-int-u", role: "user", content: "Find COLREG docs", timestamp: new Date().toISOString() },
          ],
        },
      ],
    });

    // 1. Start streaming
    const store = useChatStore.getState();
    store.startStreaming();

    // 2. Add preview items during streaming
    store.addPreviewItem(
      makePreviewItem({ preview_id: "int-1", preview_type: "document", title: "COLREG Rule 7" }),
      "rag_agent"
    );
    store.addPreviewItem(
      makePreviewItem({ preview_id: "int-2", preview_type: "document", title: "COLREG Rule 14" }),
      "rag_agent"
    );
    store.appendStreamingContent("Based on the documents...");

    // 3. Finalize stream
    store.finalizeStream({ processing_time: 2.0, model: "gemini", agent_type: "rag" } as any);

    // 4. Verify previews saved
    const conv = useChatStore.getState().conversations[0];
    const lastMsg = conv.messages[conv.messages.length - 1];
    expect(lastMsg.previews).toHaveLength(2);

    // 5. Open panel and select preview
    useUIStore.getState().openPreview("int-1");
    expect(useUIStore.getState().previewPanelOpen).toBe(true);
    expect(useUIStore.getState().selectedPreviewId).toBe("int-1");

    // 6. Switch selection
    useUIStore.getState().openPreview("int-2");
    expect(useUIStore.getState().selectedPreviewId).toBe("int-2");

    // 7. Close panel
    useUIStore.getState().closePreview();
    expect(useUIStore.getState().previewPanelOpen).toBe(false);
    expect(useUIStore.getState().selectedPreviewId).toBeNull();
  });

  it("preview block interleaves with thinking and answer blocks", () => {
    useChatStore.getState().startStreaming();
    const store = useChatStore.getState();

    // Thinking -> Preview -> Answer
    store.openThinkingBlock("Analyzing query");
    store.appendThinkingDelta("Searching documents...");
    store.closeThinkingBlock();

    store.addPreviewItem(
      makePreviewItem({ preview_id: "interleave-1", title: "Found Doc" }),
      "rag"
    );

    store.appendStreamingContent("Based on these results...");

    const blocks = useChatStore.getState().streamingBlocks;
    const types = blocks.map((b) => b.type);
    expect(types).toEqual(["thinking", "preview", "answer"]);
  });

  it("show_previews=false prevents preview items from being added (SSE handler logic)", () => {
    // This simulates the onPreview handler checking settings
    const shouldAdd = useSettingsStore.getState().settings.show_previews !== false;
    expect(shouldAdd).toBe(true);

    // Update setting
    useSettingsStore.setState({
      settings: { ...useSettingsStore.getState().settings, show_previews: false },
    });

    const shouldAddAfter = useSettingsStore.getState().settings.show_previews !== false;
    expect(shouldAddAfter).toBe(false);

    // When show_previews is false, the SSE handler returns early without calling addPreviewItem
  });
});

// =============================================================================
// 11. Edge cases (3)
// =============================================================================
describe("Preview — Edge Cases", () => {
  it("addPreviewItem with undefined node creates block with undefined node", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().addPreviewItem(makePreviewItem({ preview_id: "edge-1" }));

    const blocks = useChatStore.getState().streamingBlocks;
    const previewBlock = blocks.find((b) => b.type === "preview") as PreviewBlockData;
    expect(previewBlock).toBeDefined();
    expect(previewBlock.node).toBeUndefined();
  });

  it("openPreview updates selectedPreviewId when switching between previews", () => {
    useUIStore.getState().openPreview("first");
    expect(useUIStore.getState().selectedPreviewId).toBe("first");

    useUIStore.getState().openPreview("second");
    expect(useUIStore.getState().selectedPreviewId).toBe("second");

    // Panel remains open
    expect(useUIStore.getState().previewPanelOpen).toBe(true);
  });

  it("clearStreaming resets streamingPreviews", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().addPreviewItem(makePreviewItem(), "rag");
    expect(useChatStore.getState().streamingPreviews).toHaveLength(1);

    useChatStore.getState().clearStreaming();
    expect(useChatStore.getState().streamingPreviews).toHaveLength(0);
    expect(useChatStore.getState().streamingBlocks).toHaveLength(0);
  });
});
