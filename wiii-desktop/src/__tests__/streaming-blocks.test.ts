/**
 * Interleaved streaming blocks regression suite.
 *
 * The current chat UI treats tool execution as a first-class block instead of
 * only nesting tool calls inside a thinking card. These tests lock that
 * behavior so the renderer can present:
 *   thinking -> tool_execution -> thinking -> answer -> artifact
 */
import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "@/stores/chat-store";
import type { ContentBlock, ThinkingBlockData, ToolExecutionBlockData } from "@/api/types";

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
    streamingArtifacts: [],
    pendingStreamMetadata: null,
    _activeSubagentGroupId: null,
    streamError: "",
    streamCompletedAt: null,
  });
});

function getBlocks(): ContentBlock[] {
  return useChatStore.getState().streamingBlocks;
}

function stateToolCalls() {
  return useChatStore.getState().streamingToolCalls;
}

function thinkingAt(blocks: ContentBlock[], index: number): ThinkingBlockData {
  const block = blocks[index];
  expect(block.type).toBe("thinking");
  return block as ThinkingBlockData;
}

function toolAt(blocks: ContentBlock[], index: number): ToolExecutionBlockData {
  const block = blocks[index];
  expect(block.type).toBe("tool_execution");
  return block as ToolExecutionBlockData;
}

function contentOf(block: ContentBlock): string {
  return (block as { content: string }).content;
}

describe("streaming blocks", () => {
  it("resets all streaming blocks on startStreaming", () => {
    useChatStore.setState({
      streamingBlocks: [{ type: "answer", id: "old-1", content: "old" }],
    });

    useChatStore.getState().startStreaming();
    expect(getBlocks()).toEqual([]);
  });

  it("builds thinking -> tool_execution -> answer for a simple tool flow", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingThinking("Analyzing the question...");
    store.appendToolCall({
      id: "tc-1",
      name: "search_documents",
      args: { query: "COLREGs Rule 15" },
    });
    store.updateToolCallResult("tc-1", "Found 3 documents");
    store.appendStreamingContent("Rule 15 states that...");

    const blocks = getBlocks();
    expect(blocks).toHaveLength(3);
    expect(blocks[0].type).toBe("thinking");
    expect(blocks[1].type).toBe("tool_execution");
    expect(blocks[2].type).toBe("answer");

    expect(thinkingAt(blocks, 0).toolCalls).toHaveLength(1);
    expect(thinkingAt(blocks, 0).toolCalls[0].result).toBe("Found 3 documents");
    expect(toolAt(blocks, 1).tool.result).toBe("Found 3 documents");
    expect(contentOf(blocks[2])).toBe("Rule 15 states that...");
    expect(thinkingAt(blocks, 0).endTime).toBeGreaterThan(0);
  });

  it("supports interleaved multi-step flows with two reasoning steps and two tool strips", () => {
    const store = useChatStore.getState();
    store.startStreaming();

    store.setStreamingStep("phan_tich");
    store.setStreamingThinking("Searching knowledge base...");
    store.appendToolCall({
      id: "tc-1",
      name: "search_documents",
      args: { query: "SOLAS Chapter II" },
    });
    store.updateToolCallResult("tc-1", "2 documents found");
    store.appendStreamingContent("SOLAS Chapter II covers ");

    store.setStreamingStep("bo_sung");
    store.setStreamingThinking("Need more details on regulation 10...");
    store.appendToolCall({
      id: "tc-2",
      name: "search_documents",
      args: { query: "SOLAS regulation 10" },
    });
    store.appendStreamingContent("fire protection measures.");

    const blocks = getBlocks();
    expect(blocks.map((block) => block.type)).toEqual([
      "thinking",
      "tool_execution",
      "answer",
      "thinking",
      "tool_execution",
      "answer",
    ]);

    expect(thinkingAt(blocks, 0).toolCalls[0].id).toBe("tc-1");
    expect(thinkingAt(blocks, 3).toolCalls[0].id).toBe("tc-2");
    expect(toolAt(blocks, 4).tool.args?.query).toBe("SOLAS regulation 10");
    expect(contentOf(blocks[5])).toBe("fire protection measures.");
    expect(thinkingAt(blocks, 3).endTime).toBeGreaterThan(0);
  });

  it("keeps answer-only flows compact", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.appendStreamingContent("Hello ");
    store.appendStreamingContent("world!");

    const blocks = getBlocks();
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("answer");
    expect(contentOf(blocks[0])).toBe("Hello world!");
  });

  it("keeps direct thinking -> answer without creating a tool strip", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingThinking("This is a simple greeting.");
    store.appendStreamingContent("Xin chao! Toi la Wiii.");

    const blocks = getBlocks();
    expect(blocks.map((block) => block.type)).toEqual(["thinking", "answer"]);
    expect(thinkingAt(blocks, 0).toolCalls).toEqual([]);
  });

  it("uses streamingStep as the label for a new thinking block", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingStep("retrieval");
    store.setStreamingThinking("Searching...");

    const blocks = getBlocks();
    expect(thinkingAt(blocks, 0).label).toBe("retrieval");
  });

  it("does not use technical streaming steps as thinking labels", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingStep("Chuyển sang direct");
    store.setStreamingThinking("Mình đang nghe kỹ thêm một chút.");

    const blocks = getBlocks();
    expect(thinkingAt(blocks, 0).label).toBeUndefined();
  });

  it("concatenates consecutive thinking updates inside the same open block", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingThinking("Line 1");
    store.setStreamingThinking("Line 2");
    store.setStreamingThinking("Line 3");

    const blocks = getBlocks();
    expect(blocks).toHaveLength(1);
    expect(thinkingAt(blocks, 0).content).toBe("Line 1\nLine 2\nLine 3");
  });

  it("associates tool results with the correct thinking step and tool strip", () => {
    const store = useChatStore.getState();
    store.startStreaming();

    store.setStreamingThinking("Search 1");
    store.appendToolCall({ id: "t1", name: "fn1" });
    store.appendStreamingContent("partial");
    store.setStreamingThinking("Search 2");
    store.appendToolCall({ id: "t2", name: "fn2" });

    store.updateToolCallResult("t1", "result-1");
    store.updateToolCallResult("t2", "result-2");

    const blocks = getBlocks();
    expect(thinkingAt(blocks, 0).toolCalls[0].result).toBe("result-1");
    expect(toolAt(blocks, 1).tool.result).toBe("result-1");
    expect(thinkingAt(blocks, 3).toolCalls[0].result).toBe("result-2");
    expect(toolAt(blocks, 4).tool.result).toBe("result-2");
  });

  it("preserves orphan tool calls as standalone tool_execution blocks", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.appendToolCall({
      id: "tc-orphan",
      name: "auto_search",
      args: { q: "test" },
    });

    const blocks = getBlocks();
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("tool_execution");
    expect(toolAt(blocks, 0).tool.id).toBe("tc-orphan");
  });

  it("deduplicates replayed tool calls by id", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingThinking("Need a search.");
    store.appendToolCall({
      id: "tc-replay",
      name: "tool_web_search",
      args: { query: "first query" },
    });
    store.appendToolCall({
      id: "tc-replay",
      name: "tool_web_search",
      args: { query: "replayed query" },
    });

    const blocks = getBlocks();
    expect(stateToolCalls()).toHaveLength(1);
    expect(
      blocks.filter((block) => block.type === "tool_execution"),
    ).toHaveLength(1);
    expect(toolAt(blocks, 1).tool.args?.query).toBe("replayed query");
    expect(thinkingAt(blocks, 0).toolCalls).toHaveLength(1);
  });

  it("keeps completed tool calls completed when a duplicate call is replayed", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.appendToolCall({
      id: "tc-complete-replay",
      name: "tool_web_search",
      args: { query: "weather" },
    });
    store.updateToolCallResult("tc-complete-replay", "Found sources");
    store.appendToolCall({
      id: "tc-complete-replay",
      name: "tool_web_search",
      args: { query: "weather" },
    });

    const blocks = getBlocks();
    expect(stateToolCalls()).toHaveLength(1);
    expect(blocks).toHaveLength(1);
    expect(toolAt(blocks, 0).status).toBe("completed");
    expect(toolAt(blocks, 0).tool.result).toBe("Found sources");
  });

  it("places a late tool_execution block after an answer when no new thinking step exists", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.appendStreamingContent("Some text");
    store.appendToolCall({
      id: "tc-late",
      name: "correction_search",
    });

    const blocks = getBlocks();
    expect(blocks.map((block) => block.type)).toEqual(["answer", "tool_execution"]);
    expect(toolAt(blocks, 1).tool.id).toBe("tc-late");
  });

  it("closes the active thinking block when an answer starts", () => {
    const store = useChatStore.getState();
    store.startStreaming();
    store.setStreamingThinking("Analyzing...");

    let blocks = getBlocks();
    expect(thinkingAt(blocks, 0).endTime).toBeUndefined();

    store.appendStreamingContent("Answer");
    blocks = getBlocks();
    expect(thinkingAt(blocks, 0).endTime).toBeGreaterThan(0);
  });
});
