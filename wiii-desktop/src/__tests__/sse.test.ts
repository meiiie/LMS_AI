/**
 * Unit tests for SSE stream parser.
 * Tests buffer accumulation, event dispatch, partial JSON handling.
 */
import { describe, it, expect, vi } from "vitest";
import { parseSSEStream, type SSEEventHandler, type SSEStreamResult } from "@/api/sse";

// Helper: create a ReadableStream from string chunks
function createStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;

  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index++;
      } else {
        controller.close();
      }
    },
  });
}

function createHandlers(): SSEEventHandler & { calls: Record<string, unknown[]> } {
  const calls: Record<string, unknown[]> = {
    thinking: [],
    answer: [],
    sources: [],
    metadata: [],
    done: [],
    error: [],
    tool_call: [],
    tool_result: [],
    status: [],
    chat_lifecycle: [],
    visual: [],
    visual_open: [],
    visual_patch: [],
    visual_commit: [],
    visual_dispose: [],
    keepalive: [],
  };

  return {
    calls,
    onThinking: (data) => calls.thinking.push(data),
    onAnswer: (data) => calls.answer.push(data),
    onSources: (data) => calls.sources.push(data),
    onMetadata: (data) => calls.metadata.push(data),
    onDone: (data) => calls.done.push(data || {}),
    onError: (data) => calls.error.push(data),
    onToolCall: (data) => calls.tool_call.push(data),
    onToolResult: (data) => calls.tool_result.push(data),
    onStatus: (data) => calls.status.push(data),
    onChatLifecycle: (data) => calls.chat_lifecycle.push(data),
    onVisual: (data) => calls.visual.push(data),
    onVisualOpen: (data) => calls.visual_open.push(data),
    onVisualPatch: (data) => calls.visual_patch.push(data),
    onVisualCommit: (data) => calls.visual_commit.push(data),
    onVisualDispose: (data) => calls.visual_dispose.push(data),
    onKeepAlive: () => calls.keepalive.push({}),
  };
}

describe("SSE Parser", () => {
  it("should parse a single thinking event", async () => {
    const stream = createStream([
      'event: thinking\ndata: {"content":"Analyzing query...","step":"query_analysis"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.thinking).toHaveLength(1);
    expect(handlers.calls.thinking[0]).toEqual({
      content: "Analyzing query...",
      step: "query_analysis",
    });
  });

  it("should parse multiple answer events", async () => {
    const stream = createStream([
      'event: answer\ndata: {"content":"Hello "}\n\n',
      'event: answer\ndata: {"content":"world!"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(2);
    expect(handlers.calls.answer[0]).toEqual({ content: "Hello " });
    expect(handlers.calls.answer[1]).toEqual({ content: "world!" });
  });

  it("should parse sources event with array", async () => {
    const sources = [
      { title: "COLREGs Rule 15", content: "Crossing situation...", page_number: 42 },
      { title: "SOLAS Chapter III", content: "Life-saving appliances...", page_number: 15 },
    ];

    const stream = createStream([
      `event: sources\ndata: ${JSON.stringify({ sources })}\n\n`,
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.sources).toHaveLength(1);
    expect((handlers.calls.sources[0] as { sources: unknown[] }).sources).toHaveLength(2);
    expect((handlers.calls.sources[0] as { sources: unknown[] }).sources[0]).toMatchObject({
      title: "COLREGs Rule 15",
    });
  });

  it("should parse metadata event", async () => {
    const stream = createStream([
      'event: metadata\ndata: {"processing_time":1.5,"streaming_version":"v3"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.metadata).toHaveLength(1);
    expect(handlers.calls.metadata[0]).toMatchObject({
      processing_time: 1.5,
      streaming_version: "v3",
    });
  });

  it("should parse visual events", async () => {
    const visual = {
      id: "visual-1",
      visual_session_id: "vs-1",
      type: "comparison",
      renderer_kind: "template",
      shell_variant: "editorial",
      patch_strategy: "spec_merge",
      figure_group_id: "fg-vs-1",
      figure_index: 1,
      figure_total: 1,
      pedagogical_role: "comparison",
      chrome_mode: "editorial",
      claim: "Figure nay dat hai co che canh nhau de doc nhanh.",
      narrative_anchor: "after-lead",
      runtime: "svg",
      title: "A vs B",
      summary: "Structured visual summary",
      spec: { left: { title: "A" }, right: { title: "B" } },
      scene: { kind: "comparison", nodes: [], panels: [] },
      controls: [],
      annotations: [],
      interaction_mode: "static",
      ephemeral: true,
      lifecycle_event: "visual_open",
    };
    const stream = createStream([
      `event: visual\ndata: ${JSON.stringify({ content: visual, node: "direct", display_role: "artifact", presentation: "compact" })}\n\n`,
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.visual_open).toHaveLength(1);
    expect(handlers.calls.visual_open[0]).toMatchObject({
      content: visual,
      node: "direct",
      display_role: "artifact",
      presentation: "compact",
    });
  });

  it("should parse visual lifecycle events", async () => {
    const visual = {
      id: "visual-2",
      visual_session_id: "vs-2",
      type: "process",
      renderer_kind: "template",
      shell_variant: "editorial",
      patch_strategy: "spec_merge",
      figure_group_id: "fg-vs-2",
      figure_index: 1,
      figure_total: 1,
      pedagogical_role: "mechanism",
      chrome_mode: "editorial",
      claim: "Figure nay cho thay quy trinh duoc patch.",
      narrative_anchor: "after-lead",
      runtime: "svg",
      title: "Pipeline",
      summary: "Process summary",
      spec: { steps: [{ title: "Start" }, { title: "End" }] },
      scene: { kind: "process", nodes: [], panels: [] },
      controls: [],
      annotations: [],
      interaction_mode: "scrubbable",
      ephemeral: true,
      lifecycle_event: "visual_patch",
    };
    const stream = createStream([
      `event: visual_patch\ndata: ${JSON.stringify({ content: visual, node: "direct" })}\n\n`,
      `event: visual_commit\ndata: ${JSON.stringify({ content: { visual_session_id: "vs-2", status: "committed" }, node: "direct" })}\n\n`,
      `event: visual_dispose\ndata: ${JSON.stringify({ content: { visual_session_id: "vs-2", status: "disposed", reason: "reset" }, node: "direct" })}\n\n`,
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.visual_patch).toHaveLength(1);
    expect(handlers.calls.visual_commit).toHaveLength(1);
    expect(handlers.calls.visual_dispose).toHaveLength(1);
  });

  it("should parse done event", async () => {
    const stream = createStream([
      'event: done\ndata: {"status":"complete"}\n\n',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.done).toHaveLength(1);
    expect(handlers.calls.done[0]).toEqual({ status: "complete" });
    expect(result.sawDone).toBe(true);
  });

  it("should pass terminal runtime ledger payload from done event", async () => {
    const ledger = {
      schema_version: "wiii.runtime_flow_ledger.v1",
      stream: {
        event_counts: { answer: 1, visual_open: 1, visual_commit: 1, done: 1 },
        done_seen: true,
      },
    };
    const stream = createStream([
      `event: done\ndata: ${JSON.stringify({
        status: "complete",
        runtime_flow_ledger: ledger,
      })}\n\n`,
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.done).toHaveLength(1);
    expect(handlers.calls.done[0]).toMatchObject({
      status: "complete",
      runtime_flow_ledger: ledger,
    });
    expect(result.sawDone).toBe(true);
  });

  it("should parse error event", async () => {
    const stream = createStream([
      'event: error\ndata: {"message":"Server overloaded"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.error).toHaveLength(1);
    expect(handlers.calls.error[0]).toEqual({ message: "Server overloaded" });
  });

  it("should handle buffer accumulation across TCP chunks", async () => {
    // Split an event across two chunks
    const stream = createStream([
      'event: answer\ndata: {"con',
      'tent":"split across chunks"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({ content: "split across chunks" });
  });

  it("should handle multiple events in a single chunk", async () => {
    const stream = createStream([
      'event: thinking\ndata: {"content":"step 1"}\n\nevent: answer\ndata: {"content":"Hello"}\n\nevent: done\ndata: {"status":"complete"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.thinking).toHaveLength(1);
    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.done).toHaveLength(1);
  });

  it("should handle a full streaming conversation", async () => {
    const stream = createStream([
      'event: thinking\ndata: {"content":"Analyzing...","step":"query_analysis","node":"supervisor"}\n\n',
      'event: thinking\ndata: {"content":"Searching knowledge base...","step":"retrieval","node":"rag_agent"}\n\n',
      'event: answer\ndata: {"content":"Theo Quy tắc 15 "}\n\n',
      'event: answer\ndata: {"content":"COLREGs, tàu "}\n\n',
      'event: answer\ndata: {"content":"phải nhường đường."}\n\n',
      `event: sources\ndata: ${JSON.stringify({ sources: [{ title: "COLREGs", content: "Rule 15", page_number: 1 }] })}\n\n`,
      'event: metadata\ndata: {"processing_time":2.1}\n\n',
      'event: done\ndata: {"status":"complete"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.thinking).toHaveLength(2);
    expect(handlers.calls.answer).toHaveLength(3);
    expect(handlers.calls.sources).toHaveLength(1);
    expect(handlers.calls.metadata).toHaveLength(1);
    expect(handlers.calls.done).toHaveLength(1);
    expect(handlers.calls.error).toHaveLength(0);
  });

  it("should stop on abort signal", async () => {
    const controller = new AbortController();
    let chunkIndex = 0;

    const stream = new ReadableStream<Uint8Array>({
      pull(streamController) {
        const encoder = new TextEncoder();
        if (chunkIndex === 0) {
          streamController.enqueue(
            encoder.encode('event: answer\ndata: {"content":"first"}\n\n')
          );
          chunkIndex++;
          // Abort after first chunk
          controller.abort();
        } else {
          streamController.enqueue(
            encoder.encode('event: answer\ndata: {"content":"second"}\n\n')
          );
          chunkIndex++;
          streamController.close();
        }
      },
    });

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers, controller.signal);

    // Should have processed first event but stopped before second
    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({ content: "first" });
  });

  it("should skip invalid JSON gracefully", async () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const stream = createStream([
      'event: answer\ndata: {invalid json}\n\n',
      'event: answer\ndata: {"content":"valid"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    // Only the valid event should be dispatched
    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({ content: "valid" });
    expect(consoleSpy).toHaveBeenCalled();

    consoleSpy.mockRestore();
  });

  it("should handle events with no data field", async () => {
    const stream = createStream([
      "event: ping\n\n", // No data field — should be skipped
      'event: answer\ndata: {"content":"ok"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
  });

  it("should handle data with 'data:' prefix (no space)", async () => {
    const stream = createStream([
      'event: answer\ndata:{"content":"no space"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({ content: "no space" });
  });

  it("should handle Vietnamese content in events", async () => {
    const stream = createStream([
      'event: answer\ndata: {"content":"Theo quy định, tàu thuyền phải nhường đường khi gặp tình huống cắt hướng."}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({
      content: "Theo quy định, tàu thuyền phải nhường đường khi gặp tình huống cắt hướng.",
    });
  });

  it("should handle empty stream", async () => {
    const stream = createStream([]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.thinking).toHaveLength(0);
    expect(handlers.calls.answer).toHaveLength(0);
    expect(handlers.calls.done).toHaveLength(0);
  });

  it("should handle unknown event types without crashing", async () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const stream = createStream([
      'event: unknown_event\ndata: {"foo":"bar"}\n\n',
      'event: answer\ndata: {"content":"still works"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("Unknown event type")
    );

    consoleSpy.mockRestore();
  });

  it("should parse tool_call event", async () => {
    const stream = createStream([
      'event: tool_call\ndata: {"content":{"name":"knowledge_search","args":{"query":"Rule 5"},"id":"tc-1"},"node":"rag_agent"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.tool_call).toHaveLength(1);
    expect(handlers.calls.tool_call[0]).toMatchObject({
      content: { name: "knowledge_search", args: { query: "Rule 5" }, id: "tc-1" },
      node: "rag_agent",
    });
  });

  it("should parse tool_result event", async () => {
    const stream = createStream([
      'event: tool_result\ndata: {"content":{"name":"knowledge_search","result":"Found 8 documents","id":"tc-1"},"node":"rag_agent"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.tool_result).toHaveLength(1);
    expect(handlers.calls.tool_result[0]).toMatchObject({
      content: { name: "knowledge_search", result: "Found 8 documents", id: "tc-1" },
    });
  });

  it("should parse status event", async () => {
    const stream = createStream([
      'event: status\ndata: {"content":"Processing query...","step":"routing","node":"supervisor"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.status).toHaveLength(1);
    expect(handlers.calls.status[0]).toMatchObject({
      content: "Processing query...",
      step: "routing",
      node: "supervisor",
    });
  });

  it("should parse chat lifecycle events without warning as unknown", async () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const stream = createStream([
      'event: chat_lifecycle\ndata: {"schema_version":"wiii.chat_runtime_lifecycle.v1","event_name":"path.selected","phase":"routing","status":"selected","message":"Đã chọn lane runtime chính.","lane":"native_turn","capabilities":{"host_surface":"desktop_chat","suppressed_tools":["host_action"]}}\n\n',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.chat_lifecycle).toHaveLength(1);
    expect(handlers.calls.chat_lifecycle[0]).toMatchObject({
      event_name: "path.selected",
      phase: "routing",
      lane: "native_turn",
      capabilities: {
        host_surface: "desktop_chat",
        suppressed_tools: ["host_action"],
      },
    });
    expect(result.eventOrder).toEqual(["chat_lifecycle"]);
    expect(consoleSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("Unknown event type")
    );

    consoleSpy.mockRestore();
  });

  it("should handle tool_call and tool_result in sequence", async () => {
    const stream = createStream([
      'event: tool_call\ndata: {"content":{"name":"search","args":{"q":"test"},"id":"tc-1"}}\n\n',
      'event: tool_result\ndata: {"content":{"name":"search","result":"3 results found","id":"tc-1"}}\n\n',
      'event: answer\ndata: {"content":"Based on the search..."}\n\n',
      'event: done\ndata: {"status":"complete"}\n\n',
    ]);

    const handlers = createHandlers();
    await parseSSEStream(stream, handlers);

    expect(handlers.calls.tool_call).toHaveLength(1);
    expect(handlers.calls.tool_result).toHaveLength(1);
    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.done).toHaveLength(1);
  });

  // =========================================================================
  // Sprint 68: SSE reconnection — id: field tracking
  // =========================================================================

  it("should track id: field and return lastEventId", async () => {
    const stream = createStream([
      'id: 1\nevent: status\ndata: {"content":"routing"}\n\n',
      'id: 2\nevent: answer\ndata: {"content":"hello"}\n\n',
      'id: 3\nevent: done\ndata: {"status":"complete"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    expect(result.lastEventId).toBe("3");
    expect(handlers.calls.status).toHaveLength(1);
    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.done).toHaveLength(1);
  });

  it("should return null lastEventId when no id: fields present", async () => {
    const stream = createStream([
      'event: answer\ndata: {"content":"no ids"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    expect(result.lastEventId).toBeNull();
  });

  it("should handle id: with no space after colon", async () => {
    const stream = createStream([
      'id:42\nevent: answer\ndata: {"content":"ok"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    expect(result.lastEventId).toBe("42");
    expect(handlers.calls.answer).toHaveLength(1);
  });

  it("should update lastEventId with each event", async () => {
    const stream = createStream([
      'id: 10\nevent: answer\ndata: {"content":"a"}\n\n',
      'id: 20\nevent: answer\ndata: {"content":"b"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    // Should have the LAST id
    expect(result.lastEventId).toBe("20");
  });

  it("should ignore retry: field gracefully", async () => {
    const stream = createStream([
      'retry: 3000\n\n',
      'id: 1\nevent: answer\ndata: {"content":"after retry"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    expect(result.lastEventId).toBe("1");
    expect(handlers.calls.answer).toHaveLength(1);
  });

  it("should handle mixed events with and without ids", async () => {
    const stream = createStream([
      'event: status\ndata: {"content":"no id"}\n\n',
      'id: 5\nevent: answer\ndata: {"content":"with id"}\n\n',
    ]);

    const handlers = createHandlers();
    const result: SSEStreamResult = await parseSSEStream(stream, handlers);

    expect(result.lastEventId).toBe("5");
    expect(handlers.calls.status).toHaveLength(1);
    expect(handlers.calls.answer).toHaveLength(1);
  });

  it("should parse streams that use CRLF separators", async () => {
    const stream = createStream([
      'event: answer\r\ndata: {"content":"hello"}\r\n\r\nevent: metadata\r\ndata: {"model":"gemini"}\r\n\r\nevent: done\r\ndata: {"status":"complete"}\r\n\r\n',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.metadata).toHaveLength(1);
    expect(handlers.calls.done).toHaveLength(1);
    expect(result.sawDone).toBe(true);
    expect(result.eventOrder).toEqual(["answer", "metadata", "done"]);
  });

  it("should flush a trailing event when stream closes without blank-line terminator", async () => {
    const stream = createStream([
      'event: answer\ndata: {"content":"tail event"}',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.answer).toHaveLength(1);
    expect(handlers.calls.answer[0]).toEqual({ content: "tail event" });
    expect(result.sawDone).toBe(false);
    expect(result.eventOrder).toEqual(["answer"]);
  });

  it("should parse metadata even when EOF arrives before a done event", async () => {
    const stream = createStream([
      'event: metadata\ndata: {"session_id":"sess-1","model":"gemini"}',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.metadata).toHaveLength(1);
    expect(result.sawDone).toBe(false);
    expect(result.eventOrder).toEqual(["metadata"]);
  });

  it("should treat keepalive comments as transport activity", async () => {
    const stream = createStream([
      ': keepalive\n\n',
      'event: answer\ndata: {"content":"hello"}\n\n',
    ]);

    const handlers = createHandlers();
    const result = await parseSSEStream(stream, handlers);

    expect(handlers.calls.keepalive).toHaveLength(1);
    expect(handlers.calls.answer).toHaveLength(1);
    expect(result.eventOrder).toEqual(["keepalive", "answer"]);
  });
});
